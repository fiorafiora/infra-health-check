"""Create months, edit records, and build the per-check view used by UI and exports."""

import re
from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.constants import (
    CHECK_RESULTS,
    CONNECTION_METHODS,
    CUSTOM_STAGE,
    DEVICE_STATUSES,
    DEVICE_TYPES,
    EXPIRY_KINDS,
    FIXED_ITEMS,
    ISSUE_SOURCES,
    ISSUE_STATUSES,
)
from app.logic import compare_result, expiry_state, is_open_status, rag_light, year_month
from app.models import (
    Attachment,
    Check,
    CheckItem,
    Client,
    CustomCheckItem,
    Device,
    DeviceMonth,
    Expiry,
    Issue,
    IssueMonth,
)
from app.storage import delete_attachments_for, unlink_stored


class FormError(ValueError):
    pass


def clean(value, limit: int = 4000) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def parse_date(value) -> date | None:
    text = clean(value, 40)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise FormError("Use a date in YYYY-MM-DD format.") from exc


def parse_hours(value) -> float | None:
    text = clean(value, 20)
    if text is None:
        return None
    try:
        number = float(text)
    except ValueError as exc:
        raise FormError("Duration must be a number of hours.") from exc
    if number < 0 or number > 72:
        raise FormError("Duration must be between 0 and 72 hours.")
    return number


def require_choice(value, choices: tuple[str, ...], label: str) -> str:
    text = clean(value, 40)
    if text not in choices:
        raise FormError(f"Choose a valid {label}.")
    return text


def optional_choice(value, choices: tuple[str, ...]) -> str | None:
    text = clean(value, 40)
    if text is None:
        return None
    if text not in choices:
        raise FormError("That choice is not valid.")
    return text


def previous_check(db: Session, check: Check) -> Check | None:
    return db.scalar(
        select(Check)
        .where(Check.client_id == check.client_id, Check.check_date < check.check_date)
        .order_by(Check.check_date.desc())
    )


def is_latest_check(db: Session, check: Check) -> bool:
    latest = db.scalar(
        select(func.max(Check.check_date)).where(Check.client_id == check.client_id)
    )
    return latest == check.check_date


def next_issue_code(db: Session, client_id: int) -> str:
    codes = db.scalars(select(Issue.code).where(Issue.client_id == client_id)).all()
    highest = 0
    for code in codes:
        match = re.fullmatch(r"ISS-(\d+)", code or "")
        if match:
            highest = max(highest, int(match.group(1)))
    return f"ISS-{highest + 1:03d}"


def _prev_item_map(db: Session, check: Check | None) -> dict:
    if check is None:
        return {}
    mapped = {}
    for item in db.scalars(select(CheckItem).where(CheckItem.check_id == check.id)):
        key = ("custom", item.custom_item_id) if item.is_custom else ("fixed", item.seq)
        mapped[key] = item.result
    return mapped


def start_check(
    db: Session,
    client: Client,
    *,
    check_date: date,
    engineer: str,
    connection_method: str,
    duration_hours: float | None,
    notes: str | None,
) -> Check:
    engineer = clean(engineer, 100) or ""
    if not engineer:
        raise FormError("Enter the engineer.")
    connection_method = require_choice(connection_method, CONNECTION_METHODS, "connection")
    ym = year_month(check_date)
    exists = db.scalar(
        select(Check.id).where(Check.client_id == client.id, Check.year_month == ym)
    )
    if exists:
        raise FormError("This month already has a check.")

    prev = db.scalar(
        select(Check)
        .where(Check.client_id == client.id, Check.check_date < check_date)
        .order_by(Check.check_date.desc())
    )
    prev_items = _prev_item_map(db, prev)
    check = Check(
        client_id=client.id,
        check_date=check_date,
        year_month=ym,
        engineer=engineer,
        connection_method=connection_method,
        duration_hours=duration_hours,
        notes=clean(notes),
    )
    db.add(check)
    db.flush()

    for seq, stage, name in FIXED_ITEMS:
        db.add(
            CheckItem(
                check_id=check.id,
                seq=seq,
                stage=stage,
                name=name,
                is_custom=False,
                prev_result=prev_items.get(("fixed", seq)),
            )
        )

    customs = db.scalars(
        select(CustomCheckItem)
        .where(CustomCheckItem.client_id == client.id, CustomCheckItem.active.is_(True))
        .order_by(CustomCheckItem.sort_order, CustomCheckItem.id)
    ).all()
    seq = 10
    for custom in customs:
        seq += 1
        db.add(
            CheckItem(
                check_id=check.id,
                seq=seq,
                stage=CUSTOM_STAGE,
                name=custom.name,
                is_custom=True,
                custom_item_id=custom.id,
                prev_result=prev_items.get(("custom", custom.id)),
            )
        )

    devices = db.scalars(
        select(Device)
        .where(Device.client_id == client.id, Device.added_on <= check_date)
        .order_by(Device.sort_order, Device.id)
    ).all()
    prev_months = {}
    if prev:
        prev_months = {
            row.device_id: row
            for row in db.scalars(select(DeviceMonth).where(DeviceMonth.check_id == prev.id))
        }
    for device in devices:
        previous_month = prev_months.get(device.id)
        db.add(
            DeviceMonth(
                check_id=check.id,
                device_id=device.id,
                last_check_date=prev.check_date if prev else None,
                first_found_date=previous_month.first_found_date if previous_month else None,
            )
        )

    issues = db.scalars(
        select(Issue)
        .where(Issue.client_id == client.id, Issue.first_found_date <= check_date)
        .order_by(Issue.code)
    ).all()
    for issue in issues:
        db.add(
            IssueMonth(
                issue_id=issue.id,
                check_id=check.id,
                status=issue.status,
                observation=None,
                action=issue.action,
            )
        )
    db.flush()
    return check


def add_device(
    db: Session,
    client: Client,
    *,
    device_type: str,
    name: str,
    model: str | None,
    serial_no: str | None,
    ip_address: str | None,
    firmware: str | None,
    warranty_expiry: date | None,
    added_on: date,
) -> Device:
    device_type = require_choice(device_type, DEVICE_TYPES, "device type")
    name = clean(name, 200)
    if not name:
        raise FormError("Enter a device name.")
    current_max = db.scalar(
        select(func.max(Device.sort_order)).where(Device.client_id == client.id)
    )
    device = Device(
        client_id=client.id,
        device_type=device_type,
        name=name,
        model=clean(model, 200),
        serial_no=clean(serial_no, 200),
        ip_address=clean(ip_address, 100),
        firmware=clean(firmware, 100),
        warranty_expiry=warranty_expiry,
        added_on=added_on,
        sort_order=(current_max or 0) + 10,
    )
    db.add(device)
    db.flush()
    checks = db.scalars(
        select(Check).where(Check.client_id == client.id, Check.check_date >= added_on)
    ).all()
    for check in checks:
        prev = previous_check(db, check)
        db.add(
            DeviceMonth(
                check_id=check.id,
                device_id=device.id,
                last_check_date=prev.check_date if prev else None,
            )
        )
    db.flush()
    return device


def add_custom_item(db: Session, client: Client, name: str, from_check: Check | None) -> CustomCheckItem:
    name = clean(name, 300)
    if not name:
        raise FormError("Enter a name for the extra item.")
    current_max = db.scalar(
        select(func.max(CustomCheckItem.sort_order)).where(
            CustomCheckItem.client_id == client.id
        )
    )
    custom = CustomCheckItem(
        client_id=client.id,
        name=name,
        sort_order=(current_max or 0) + 10,
        active=True,
    )
    db.add(custom)
    db.flush()
    if from_check is None:
        return custom
    checks = db.scalars(
        select(Check).where(
            Check.client_id == client.id,
            Check.check_date >= from_check.check_date,
        )
    ).all()
    for check in checks:
        exists = db.scalar(
            select(CheckItem.id).where(
                CheckItem.check_id == check.id,
                CheckItem.custom_item_id == custom.id,
            )
        )
        if exists:
            continue
        max_seq = db.scalar(
            select(func.max(CheckItem.seq)).where(CheckItem.check_id == check.id)
        ) or 10
        prev = previous_check(db, check)
        prev_result = None
        if prev:
            prev_result = db.scalar(
                select(CheckItem.result).where(
                    CheckItem.check_id == prev.id,
                    CheckItem.custom_item_id == custom.id,
                )
            )
        db.add(
            CheckItem(
                check_id=check.id,
                seq=max_seq + 1,
                stage=CUSTOM_STAGE,
                name=name,
                is_custom=True,
                custom_item_id=custom.id,
                prev_result=prev_result,
            )
        )
    db.flush()
    return custom


def copy_warranty(db: Session, client: Client, device: Device) -> None:
    if device.client_id != client.id:
        raise FormError("That device does not belong to this client.")
    if device.warranty_expiry is None:
        raise FormError("This device has no warranty or support date to copy.")
    existing = db.scalar(
        select(Expiry.id).where(
            Expiry.client_id == client.id,
            Expiry.device_id == device.id,
            Expiry.kind == "Warranty",
            Expiry.expiry_date == device.warranty_expiry,
        )
    )
    if existing:
        raise FormError("That warranty is already on the expiry list.")
    db.add(
        Expiry(
            client_id=client.id,
            kind="Warranty",
            name=f"{device.name} warranty",
            device_id=device.id,
            related_label=device.name,
            expiry_date=device.warranty_expiry,
            notes="Copied from the device warranty / support date.",
            copied_from_device=True,
        )
    )


def include_known_issues(db: Session, check: Check) -> int:
    existing = set(
        db.scalars(select(IssueMonth.issue_id).where(IssueMonth.check_id == check.id)).all()
    )
    issues = db.scalars(
        select(Issue).where(
            Issue.client_id == check.client_id,
            Issue.first_found_date <= check.check_date,
        )
    ).all()
    added = 0
    for issue in issues:
        if issue.id in existing:
            continue
        db.add(
            IssueMonth(
                issue_id=issue.id,
                check_id=check.id,
                status=issue.status,
                observation=None,
                action=issue.action,
            )
        )
        added += 1
    return added


def build_check_view(db: Session, check: Check) -> dict:
    client = db.get(Client, check.client_id)
    att = _attachment_map(db, client.id)
    items = db.scalars(
        select(CheckItem).where(CheckItem.check_id == check.id).order_by(CheckItem.seq, CheckItem.id)
    ).all()
    item_views = []
    abnormal_items = 0
    filled_items = 0
    for item in items:
        if item.result == "Abnormal":
            abnormal_items += 1
        if item.result in ("Normal", "Abnormal", "N/A"):
            filled_items += 1
        item_views.append(
            {
                "item": item,
                "compare": compare_result(item.result, item.prev_result),
                "attachments": att.get(("check_item", item.id), []),
            }
        )

    months = {
        row.device_id: row
        for row in db.scalars(select(DeviceMonth).where(DeviceMonth.check_id == check.id))
    }
    prev = previous_check(db, check)
    prev_months = {}
    if prev:
        prev_months = {
            row.device_id: row
            for row in db.scalars(select(DeviceMonth).where(DeviceMonth.check_id == prev.id))
        }
    device_ids = list(months)
    devices = []
    if device_ids:
        devices = db.scalars(
            select(Device)
            .where(Device.id.in_(device_ids))
            .order_by(Device.sort_order, Device.id)
        ).all()
    device_views = []
    abnormal_devices = 0
    for device in devices:
        month = months[device.id]
        if month.status == "Abnormal":
            abnormal_devices += 1
        previous = prev_months.get(device.id)
        device_views.append(
            {
                "device": device,
                "month": month,
                "prev_status": previous.status if previous else None,
                "attachments": att.get(("device_month", month.id), []),
            }
        )

    issue_months = {
        row.issue_id: row
        for row in db.scalars(select(IssueMonth).where(IssueMonth.check_id == check.id))
    }
    issues = db.scalars(
        select(Issue).where(Issue.client_id == client.id).order_by(Issue.code)
    ).all()
    issue_views = []
    open_followups = 0
    missing_issues = 0
    for issue in issues:
        month = issue_months.get(issue.id)
        visible = month is not None or issue.first_found_date <= check.check_date
        if not visible:
            continue
        if month is None:
            missing_issues += 1
        elif is_open_status(month.status):
            open_followups += 1
        issue_views.append(
            {
                "issue": issue,
                "month": month,
                "attachments": att.get(("issue", issue.id), []),
            }
        )

    expiries = db.scalars(
        select(Expiry).where(Expiry.client_id == client.id).order_by(Expiry.expiry_date, Expiry.id)
    ).all()
    expiry_views = []
    expired = within_30 = within_90 = 0
    for expiry in expiries:
        days, status = expiry_state(expiry.expiry_date, check.check_date)
        if status == "Expired":
            expired += 1
        elif status == "Due in 30 days":
            within_30 += 1
        elif status == "Due in 90 days":
            within_90 += 1
        related = ""
        if expiry.device_id:
            device = db.get(Device, expiry.device_id)
            related = device.name if device else (expiry.related_label or "")
        else:
            related = expiry.related_label or ""
        expiry_views.append(
            {
                "expiry": expiry,
                "days": days,
                "status": status,
                "related": related,
            }
        )

    counts = {
        "abnormal_items": abnormal_items,
        "filled_items": filled_items,
        "abnormal_devices": abnormal_devices,
        "open_followups": open_followups,
        "expired": expired,
        "within_30": within_30,
        "within_90": within_90,
    }
    light = rag_light(
        abnormal_items,
        filled_items,
        abnormal_devices,
        open_followups,
        expired,
        within_30,
        within_90,
    )
    return {
        "client": client,
        "check": check,
        "light": light,
        "counts": counts,
        "items": item_views,
        "devices": device_views,
        "issues": issue_views,
        "expiries": expiry_views,
        "missing_issues": missing_issues,
        "prev_check": prev,
        "is_latest": is_latest_check(db, check),
    }


def _attachment_map(db: Session, client_id: int) -> dict[tuple[str, int], list[Attachment]]:
    grouped: dict[tuple[str, int], list[Attachment]] = {}
    rows = db.scalars(
        select(Attachment).where(Attachment.client_id == client_id).order_by(Attachment.id)
    ).all()
    for row in rows:
        grouped.setdefault((row.target_type, row.target_id), []).append(row)
    return grouped


def save_check_cover(db: Session, check: Check, form) -> None:
    check_date = parse_date(form.get("check_date"))
    if check_date is None:
        raise FormError("Enter the check date.")
    engineer = clean(form.get("engineer"), 100)
    if not engineer:
        raise FormError("Enter the engineer.")
    method = require_choice(form.get("connection_method"), CONNECTION_METHODS, "connection")
    ym = year_month(check_date)
    clash = db.scalar(
        select(Check.id).where(
            Check.client_id == check.client_id,
            Check.year_month == ym,
            Check.id != check.id,
        )
    )
    if clash:
        raise FormError("Another check already exists for this month.")
    check.check_date = check_date
    check.year_month = ym
    check.engineer = engineer
    check.connection_method = method
    check.duration_hours = parse_hours(form.get("duration_hours"))
    check.notes = clean(form.get("notes"))


def save_device_months(db: Session, check: Check, form) -> None:
    rows = db.scalars(select(DeviceMonth).where(DeviceMonth.check_id == check.id)).all()
    for row in rows:
        status = optional_choice(form.get(f"status_{row.id}"), DEVICE_STATUSES)
        row.status = status
        row.exception_summary = clean(form.get(f"summary_{row.id}"))
        row.follow_up = clean(form.get(f"follow_{row.id}"))
        row.first_found_date = parse_date(form.get(f"found_{row.id}"))
        row.last_check_date = parse_date(form.get(f"last_{row.id}"))


def save_check_items(db: Session, check: Check, form) -> None:
    items = db.scalars(select(CheckItem).where(CheckItem.check_id == check.id)).all()
    for item in items:
        item.result = optional_choice(form.get(f"result_{item.id}"), CHECK_RESULTS)
        item.notes = clean(form.get(f"notes_{item.id}"))
        if not item.is_custom:
            continue
        new_name = clean(form.get(f"name_{item.id}"), 300)
        if not new_name:
            continue
        item.name = new_name
        if item.custom_item_id:
            db.execute(
                update(CheckItem)
                .where(CheckItem.custom_item_id == item.custom_item_id)
                .values(name=new_name)
            )
            custom = db.get(CustomCheckItem, item.custom_item_id)
            if custom:
                custom.name = new_name


def update_device(db: Session, device: Device, form) -> None:
    device.device_type = require_choice(form.get("device_type"), DEVICE_TYPES, "device type")
    name = clean(form.get("name"), 200)
    if not name:
        raise FormError("Enter a device name.")
    device.name = name
    device.model = clean(form.get("model"), 200)
    device.serial_no = clean(form.get("serial_no"), 200)
    device.ip_address = clean(form.get("ip_address"), 100)
    device.firmware = clean(form.get("firmware"), 100)
    device.warranty_expiry = parse_date(form.get("warranty_expiry"))
    sort_text = clean(form.get("sort_order"), 8)
    if sort_text is not None:
        try:
            device.sort_order = int(sort_text)
        except ValueError as exc:
            raise FormError("Sort order must be a whole number.") from exc


def create_issue(db: Session, client: Client, check: Check | None, form) -> Issue:
    summary = clean(form.get("summary"))
    if not summary:
        raise FormError("Enter an issue summary.")
    found = parse_date(form.get("first_found_date"))
    if found is None:
        raise FormError("Enter the date first found.")
    source = require_choice(form.get("source"), ISSUE_SOURCES, "source")
    status = require_choice(form.get("status"), ISSUE_STATUSES, "status")
    device_id = _optional_device_id(db, client.id, form.get("device_id"))
    related = clean(form.get("related_label"), 300)
    if related is None and device_id:
        device = db.get(Device, device_id)
        related = device.name if device else None
    close_date = parse_date(form.get("close_date"))
    if status == "Closed" and close_date is None:
        close_date = check.check_date if check else date.today()
    if status != "Closed":
        close_date = None
    issue = Issue(
        client_id=client.id,
        code=next_issue_code(db, client.id),
        first_found_date=found,
        source=source,
        related_label=related,
        device_id=device_id,
        summary=summary,
        status=status,
        action=clean(form.get("action")),
        close_date=close_date,
    )
    db.add(issue)
    db.flush()
    if check and found <= check.check_date:
        db.add(
            IssueMonth(
                issue_id=issue.id,
                check_id=check.id,
                status=status,
                observation=clean(form.get("observation")),
                action=issue.action,
            )
        )
    return issue


def update_issue(db: Session, issue: Issue, check: Check | None, form) -> None:
    summary = clean(form.get("summary"))
    if not summary:
        raise FormError("Enter an issue summary.")
    found = parse_date(form.get("first_found_date"))
    if found is None:
        raise FormError("Enter the date first found.")
    issue.summary = summary
    issue.first_found_date = found
    issue.source = require_choice(form.get("source"), ISSUE_SOURCES, "source")
    issue.device_id = _optional_device_id(db, issue.client_id, form.get("device_id"))
    related = clean(form.get("related_label"), 300)
    if related is None and issue.device_id:
        device = db.get(Device, issue.device_id)
        related = device.name if device else None
    issue.related_label = related
    close_date = parse_date(form.get("close_date"))
    month_status = require_choice(form.get("status"), ISSUE_STATUSES, "status")
    if month_status == "Closed" and close_date is None:
        close_date = check.check_date if check else date.today()
    if month_status != "Closed":
        close_date = None
    issue.close_date = close_date
    observation = clean(form.get("observation"))
    action = clean(form.get("action"))
    if check is not None:
        month = db.scalar(
            select(IssueMonth).where(
                IssueMonth.issue_id == issue.id,
                IssueMonth.check_id == check.id,
            )
        )
        if month is None:
            month = IssueMonth(issue_id=issue.id, check_id=check.id, status=month_status)
            db.add(month)
        month.status = month_status
        month.observation = observation
        month.action = action
        if is_latest_check(db, check):
            issue.status = month_status
            issue.action = action
    else:
        issue.status = month_status
        issue.action = action


def create_expiry(db: Session, client: Client, form) -> Expiry:
    name = clean(form.get("name"), 300)
    if not name:
        raise FormError("Enter an item name.")
    expiry_date = parse_date(form.get("expiry_date"))
    if expiry_date is None:
        raise FormError("Enter the expiry date.")
    kind = require_choice(form.get("kind"), EXPIRY_KINDS, "type")
    device_id = _optional_device_id(db, client.id, form.get("device_id"))
    related = clean(form.get("related_label"), 300)
    if related is None and device_id:
        device = db.get(Device, device_id)
        related = device.name if device else None
    row = Expiry(
        client_id=client.id,
        kind=kind,
        name=name,
        device_id=device_id,
        related_label=related,
        expiry_date=expiry_date,
        notes=clean(form.get("notes")),
        copied_from_device=False,
    )
    db.add(row)
    return row


def update_expiry(db: Session, expiry: Expiry, form) -> None:
    name = clean(form.get("name"), 300)
    if not name:
        raise FormError("Enter an item name.")
    expiry_date = parse_date(form.get("expiry_date"))
    if expiry_date is None:
        raise FormError("Enter the expiry date.")
    expiry.name = name
    expiry.expiry_date = expiry_date
    expiry.kind = require_choice(form.get("kind"), EXPIRY_KINDS, "type")
    expiry.device_id = _optional_device_id(db, expiry.client_id, form.get("device_id"))
    related = clean(form.get("related_label"), 300)
    if related is None and expiry.device_id:
        device = db.get(Device, expiry.device_id)
        related = device.name if device else None
    expiry.related_label = related
    expiry.notes = clean(form.get("notes"))


def _optional_device_id(db: Session, client_id: int, value) -> int | None:
    text = clean(value, 20)
    if text is None:
        return None
    try:
        device_id = int(text)
    except ValueError as exc:
        raise FormError("The related device is not valid.") from exc
    device = db.get(Device, device_id)
    if device is None or device.client_id != client_id:
        raise FormError("That device does not belong to this client.")
    return device_id


def delete_client_files(db: Session, client: Client, upload_dir) -> None:
    rows = db.scalars(select(Attachment).where(Attachment.client_id == client.id)).all()
    for row in rows:
        unlink_stored(upload_dir, row.stored_name)


def delete_check_files(db: Session, check: Check, upload_dir) -> None:
    dm_ids = list(
        db.scalars(select(DeviceMonth.id).where(DeviceMonth.check_id == check.id)).all()
    )
    item_ids = list(
        db.scalars(select(CheckItem.id).where(CheckItem.check_id == check.id)).all()
    )
    delete_attachments_for(db, upload_dir, "device_month", dm_ids)
    delete_attachments_for(db, upload_dir, "check_item", item_ids)


def delete_device_files(db: Session, device: Device, upload_dir) -> None:
    dm_ids = list(
        db.scalars(select(DeviceMonth.id).where(DeviceMonth.device_id == device.id)).all()
    )
    delete_attachments_for(db, upload_dir, "device_month", dm_ids)


def delete_issue_files(db: Session, issue: Issue, upload_dir) -> None:
    delete_attachments_for(db, upload_dir, "issue", [issue.id])


def delete_custom_item(db: Session, custom: CustomCheckItem, upload_dir) -> None:
    items = db.scalars(
        select(CheckItem).where(CheckItem.custom_item_id == custom.id)
    ).all()
    delete_attachments_for(db, upload_dir, "check_item", [item.id for item in items])
    for item in items:
        db.delete(item)
    db.delete(custom)


def resolve_attachment_target(db: Session, target_type: str, target_id: int):
    """Return (client_id, object) or None."""
    if target_type == "device_month":
        row = db.get(DeviceMonth, target_id)
        if row is None:
            return None
        device = db.get(Device, row.device_id)
        return (device.client_id, row) if device else None
    if target_type == "check_item":
        row = db.get(CheckItem, target_id)
        if row is None:
            return None
        check = db.get(Check, row.check_id)
        return (check.client_id, row) if check else None
    if target_type == "issue":
        row = db.get(Issue, target_id)
        if row is None:
            return None
        return row.client_id, row
    return None
