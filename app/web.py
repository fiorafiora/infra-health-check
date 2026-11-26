"""HTML routes. No login: this tool is meant for an internal network or VPN."""

from datetime import date
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import (
    CHECK_RESULTS,
    CONNECTION_METHODS,
    DEVICE_STATUSES,
    DEVICE_TYPES,
    EXPIRY_KINDS,
    ISSUE_SOURCES,
    ISSUE_STATUSES,
    STAGE_HEADINGS,
)
from app.exports import build_pdf, build_xlsx
from app.models import (
    Attachment,
    Check,
    Client,
    CustomCheckItem,
    Customer,
    Device,
    DeviceCheck,
    Expiry,
    Issue,
    Site,
)
from app.service import (
    FormError,
    add_custom_item,
    parse_hours,
    add_device,
    add_device_check,
    build_check_view,
    clean,
    copy_warranty,
    create_expiry,
    create_issue,
    delete_check_files,
    delete_client_files,
    delete_custom_item,
    delete_device_check,
    delete_device_files,
    delete_issue_files,
    include_known_issues,
    parse_date,
    resolve_attachment_target,
    save_check_cover,
    save_check_items,
    save_device_check_results,
    save_device_months,
    start_check,
    update_device,
    update_expiry,
    update_issue,
)
from app.storage import (
    attachment_path,
    delete_attachment_row,
    save_attachment,
    thumbnail_bytes,
    validate_image,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _format_date(value) -> str:
    if not value:
        return "—"
    return value.isoformat()


def _format_hours(value) -> str:
    if value is None or value == "":
        return ""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:g}"


templates.env.filters["d"] = _format_date
templates.env.filters["hours"] = _format_hours
templates.env.globals["stage_heading"] = lambda stage: STAGE_HEADINGS.get(stage, stage)
templates.env.globals["DEVICE_TYPES"] = DEVICE_TYPES
templates.env.globals["CONNECTION_METHODS"] = CONNECTION_METHODS
templates.env.globals["ISSUE_SOURCES"] = ISSUE_SOURCES
templates.env.globals["ISSUE_STATUSES"] = ISSUE_STATUSES
templates.env.globals["EXPIRY_KINDS"] = EXPIRY_KINDS
templates.env.globals["DEVICE_RESULTS"] = DEVICE_STATUSES
templates.env.globals["CHECK_RESULTS"] = CHECK_RESULTS


def get_db(request: Request):
    db = request.app.state.Session()
    try:
        yield db
    finally:
        db.close()


def render(request: Request, name: str, **context):
    context.setdefault("msg", request.query_params.get("msg", ""))
    context.setdefault("err", request.query_params.get("err", ""))
    context["request"] = request
    try:
        return templates.TemplateResponse(request, name, context)
    except TypeError:
        return templates.TemplateResponse(name, context)


def not_found() -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'><title>Not found</title>"
        "<p style='font-family:sans-serif'>That page was not found.</p>",
        status_code=404,
    )


def go(url: str, **params):
    fragment = ""
    if "#" in url:
        url, fragment = url.split("#", 1)
        fragment = "#" + fragment
    kept = {key: value for key, value in params.items() if value}
    if kept:
        url = url + ("&" if "?" in url else "?") + urlencode(kept)
    return RedirectResponse(url + fragment, status_code=303)


def safe_next(value, fallback: str) -> str:
    text = str(value or "")
    if not text.startswith("/") or text.startswith("//") or "\\" in text:
        return fallback
    return text


def _device_anchor(form) -> str:
    text = clean(form.get("device_anchor"), 40) or ""
    if text.startswith("device-") and text.removeprefix("device-").isdigit():
        return text
    return "devices"


def site_url(site_id: int, check_id: int | None = None, anchor: str = "") -> str:
    url = f"/sites/{site_id}"
    if check_id:
        url += f"?check={check_id}"
    if anchor:
        url += f"#{anchor}"
    return url


def _commit(db: Session, fallback: str, ok: str):
    db.commit()
    return go(fallback, msg=ok)


@router.get("/health")
def health():
    return {"status": "ok"}


def _site_summary(db: Session, site: Site) -> dict:
    latest = db.scalar(
        select(Check)
        .where(Check.site_id == site.id)
        .order_by(Check.check_date.desc(), Check.id.desc())
    )
    light = ""
    year_month = ""
    check_date = ""
    check_id = None
    if latest:
        view = build_check_view(db, latest)
        light = view["light"]
        year_month = latest.year_month
        check_date = latest.check_date.isoformat()
        check_id = latest.id
    site_devices = db.scalars(
        select(Device).where(Device.site_id == site.id).order_by(Device.sort_order, Device.id)
    ).all()
    return {
        "site": site,
        "light": light,
        "year_month": year_month,
        "check_date": check_date,
        "device_count": len(site_devices),
        "devices": site_devices,
        "check_id": check_id,
    }


@router.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    customers = db.scalars(select(Customer).order_by(Customer.id)).all()
    groups = []
    for customer in customers:
        sites = db.scalars(select(Site).where(Site.customer_id == customer.id).order_by(Site.id)).all()
        groups.append(
            {
                "customer": customer,
                "sites": [_site_summary(db, site) for site in sites],
            }
        )
    db.commit()
    return render(
        request,
        "index.html",
        groups=groups,
        has_demo=any(customer.is_demo for customer in customers),
        today=date.today(),
    )


@router.post("/customers")
async def create_customer(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    name = clean(form.get("name"), 200)
    if not name:
        return go("/", err="Enter a customer name.")
    customer = Customer(name=name, notes=clean(form.get("notes")), is_demo=False)
    db.add(customer)
    db.commit()
    return go(f"/customers/{customer.id}", msg="Customer added.")


@router.get("/customers/{customer_id}")
def customer_page(customer_id: int, request: Request, db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if customer is None:
        return not_found()
    sites = db.scalars(select(Site).where(Site.customer_id == customer.id).order_by(Site.id)).all()
    rows = [_site_summary(db, site) for site in sites]
    db.commit()
    return render(request, "customer.html", customer=customer, rows=rows)


@router.post("/customers/{customer_id}")
async def update_customer(customer_id: int, request: Request, db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if customer is None:
        return not_found()
    form = await request.form()
    name = clean(form.get("name"), 200)
    if not name:
        return go(f"/customers/{customer.id}", err="Enter a customer name.")
    customer.name = name
    customer.notes = clean(form.get("notes"))
    db.commit()
    return go(f"/customers/{customer.id}", msg="Customer saved.")


@router.post("/customers/{customer_id}/delete")
async def remove_customer(customer_id: int, request: Request, db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if customer is None:
        return not_found()
    delete_client_files(db, customer, request.app.state.upload_dir)
    db.delete(customer)
    db.commit()
    return go("/", msg="Customer and its sites were deleted.")


@router.post("/customers/{customer_id}/sites")
async def create_site(customer_id: int, request: Request, db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if customer is None:
        return not_found()
    form = await request.form()
    name = clean(form.get("name"), 200)
    if not name:
        return go(f"/customers/{customer.id}", err="Enter a site name.")
    site = Site(customer_id=customer.id, name=name)
    db.add(site)
    db.commit()
    return go(f"/sites/{site.id}", msg="Site added.")


@router.get("/sites/{site_id}")
def site_page(
    site_id: int,
    request: Request,
    check: int | None = None,
    db: Session = Depends(get_db),
):
    site = db.get(Site, site_id)
    if site is None:
        return not_found()
    customer = db.get(Customer, site.customer_id)
    checks = db.scalars(
        select(Check).where(Check.site_id == site.id).order_by(Check.check_date.desc())
    ).all()
    current = None
    if check is not None:
        current = next((item for item in checks if item.id == check), None)
        if current is None:
            return not_found()
    elif checks:
        current = checks[0]
    pills = []
    view = None
    for item in checks:
        if current is not None and item.id == current.id and view is None:
            built = build_check_view(db, item)
            view = built
        else:
            built = build_check_view(db, item)
            if current is not None and item.id == current.id:
                view = built
        pills.append({"check": item, "light": built["light"]})
    if current is not None and view is None:
        view = build_check_view(db, current)
    devices = db.scalars(
        select(Device).where(Device.site_id == site.id).order_by(Device.sort_order, Device.id)
    ).all()
    db.commit()
    return render(
        request,
        "client.html",
        customer=customer,
        site=site,
        client=customer,
        checks=checks,
        current=current,
        pills=pills,
        view=view,
        devices=devices,
        today=date.today(),
    )


@router.post("/sites/{site_id}")
async def update_site(site_id: int, request: Request, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if site is None:
        return not_found()
    form = await request.form()
    name = clean(form.get("name"), 200)
    if not name:
        return go(f"/sites/{site.id}", err="Enter a site name.")
    site.name = name
    db.commit()
    return go(site_url(site.id, _int_or_none(form.get("check_id"))), msg="Site saved.")


@router.post("/sites/{site_id}/checks")
async def create_check(site_id: int, request: Request, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if site is None:
        return not_found()
    form = await request.form()
    try:
        check_date = parse_date(form.get("check_date"))
        if check_date is None:
            raise FormError("Enter the check date.")
        check = start_check(
            db,
            site,
            check_date=check_date,
            engineer=form.get("engineer"),
            connection_method=form.get("connection_method"),
            duration_hours=parse_hours(form.get("duration_hours")),
            notes=form.get("notes"),
        )
        db.commit()
    except FormError as exc:
        return go(f"/sites/{site.id}", err=str(exc))
    return go(site_url(site.id, check.id), msg="Monthly check started.")


@router.post("/checks/{check_id}")
async def update_check(check_id: int, request: Request, db: Session = Depends(get_db)):
    check = db.get(Check, check_id)
    if check is None:
        return not_found()
    form = await request.form()
    try:
        save_check_cover(db, check, form)
        db.commit()
    except FormError as exc:
        return go(site_url(check.site_id, check.id), err=str(exc))
    return go(site_url(check.site_id, check.id, "summary"), msg="Cover saved.")


@router.post("/checks/{check_id}/delete")
async def remove_check(check_id: int, request: Request, db: Session = Depends(get_db)):
    check = db.get(Check, check_id)
    if check is None:
        return not_found()
    client_id = check.site_id
    delete_check_files(db, check, request.app.state.upload_dir)
    db.delete(check)
    db.commit()
    return go(f"/sites/{client_id}", msg="That month was deleted.")


@router.post("/checks/{check_id}/devices")
async def save_devices(check_id: int, request: Request, db: Session = Depends(get_db)):
    check = db.get(Check, check_id)
    if check is None:
        return not_found()
    form = await request.form()
    try:
        save_device_months(db, check, form)
        db.commit()
    except FormError as exc:
        return go(site_url(check.site_id, check.id, "devices"), err=str(exc))
    return go(site_url(check.site_id, check.id, "devices"), msg="Device status saved.")


@router.post("/checks/{check_id}/device-checks")
async def save_device_checks(check_id: int, request: Request, db: Session = Depends(get_db)):
    check = db.get(Check, check_id)
    if check is None:
        return not_found()
    form = await request.form()
    try:
        save_device_check_results(db, check, form)
        db.commit()
    except FormError as exc:
        return go(site_url(check.site_id, check.id, _device_anchor(form)), err=str(exc))
    return go(site_url(check.site_id, check.id, _device_anchor(form)), msg="This device was saved.")


@router.post("/devices/{device_id}/checks")
async def create_device_check(device_id: int, request: Request, db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if device is None:
        return not_found()
    form = await request.form()
    check_id = _int_or_none(form.get("check_id"))
    try:
        add_device_check(db, device, form.get("name"), form.get("command"))
        db.commit()
    except FormError as exc:
        return go(site_url(device.site_id, check_id, "devices"), err=str(exc))
    return go(site_url(device.site_id, check_id, "devices"), msg="Check added.")


@router.post("/device-checks/{item_id}/delete")
async def remove_device_check(item_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(DeviceCheck, item_id)
    if item is None:
        return not_found()
    device = db.get(Device, item.device_id)
    form = await request.form()
    check_id = _int_or_none(form.get("check_id"))
    client_id = device.site_id if device else 0
    delete_device_check(db, item, request.app.state.upload_dir)
    db.commit()
    return go(site_url(client_id, check_id, "devices"), msg="Check removed.")


@router.post("/sites/{site_id}/devices")
async def create_device(site_id: int, request: Request, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if site is None:
        return not_found()
    form = await request.form()
    check_id = _int_or_none(form.get("check_id"))
    try:
        added_on = parse_date(form.get("added_on")) or date.today()
        add_device(
            db,
            site,
            device_type=form.get("device_type"),
            name=form.get("name"),
            model=form.get("model"),
            serial_no=form.get("serial_no"),
            ip_address=form.get("ip_address"),
            firmware=form.get("firmware"),
            warranty_expiry=parse_date(form.get("warranty_expiry")),
            added_on=added_on,
        )
        db.commit()
    except FormError as exc:
        return go(site_url(site.id, check_id, "add-device"), err=str(exc))
    return go(site_url(site.id, check_id, "add-device"), msg="Device added.")


@router.post("/devices/{device_id}")
async def edit_device(device_id: int, request: Request, db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if device is None:
        return not_found()
    form = await request.form()
    check_id = _int_or_none(form.get("check_id"))
    try:
        update_device(db, device, form)
        db.commit()
    except FormError as exc:
        return go(site_url(device.site_id, check_id, "devices"), err=str(exc))
    return go(site_url(device.site_id, check_id, "devices"), msg="Device saved.")


@router.post("/devices/{device_id}/delete")
async def remove_device(device_id: int, request: Request, db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if device is None:
        return not_found()
    form = await request.form()
    client_id = device.site_id
    check_id = _int_or_none(form.get("check_id"))
    delete_device_files(db, device, request.app.state.upload_dir)
    db.delete(device)
    db.commit()
    return go(site_url(client_id, check_id, "devices"), msg="Device deleted.")


@router.post("/checks/{check_id}/items")
async def save_items(check_id: int, request: Request, db: Session = Depends(get_db)):
    check = db.get(Check, check_id)
    if check is None:
        return not_found()
    form = await request.form()
    try:
        save_check_items(db, check, form)
        db.commit()
    except FormError as exc:
        return go(site_url(check.site_id, check.id, "checklist"), err=str(exc))
    return go(site_url(check.site_id, check.id, "checklist"), msg="Checklist saved.")


@router.post("/clients/{client_id}/custom-items")
async def create_custom(client_id: int, request: Request, db: Session = Depends(get_db)):
    client = db.get(Client, client_id)
    if client is None:
        return not_found()
    form = await request.form()
    check_id = _int_or_none(form.get("check_id"))
    check = db.get(Check, check_id) if check_id else None
    if check and check.site_id != client.id:
        return not_found()
    try:
        add_custom_item(db, client, form.get("name"), check)
        db.commit()
    except FormError as exc:
        return go(site_url(client.id, check_id, "checklist"), err=str(exc))
    return go(site_url(client.id, check_id, "checklist"), msg="Extra item added.")


@router.post("/custom-items/{item_id}/delete")
async def remove_custom(item_id: int, request: Request, db: Session = Depends(get_db)):
    custom = db.get(CustomCheckItem, item_id)
    if custom is None:
        return not_found()
    form = await request.form()
    client_id = custom.client_id
    check_id = _int_or_none(form.get("check_id"))
    delete_custom_item(db, custom, request.app.state.upload_dir)
    db.commit()
    return go(site_url(client_id, check_id, "checklist"), msg="Extra item deleted.")


@router.post("/sites/{site_id}/issues")
async def create_issue_route(site_id: int, request: Request, db: Session = Depends(get_db)):
    site = db.get(Site, site_id)
    if site is None:
        return not_found()
    form = await request.form()
    check_id = _int_or_none(form.get("check_id"))
    check = db.get(Check, check_id) if check_id else None
    if check is not None and check.site_id != site.id:
        return not_found()
    back = site_url(site.id, check_id)
    try:
        issue = create_issue(db, site, check, form)
        db.commit()
    except FormError as exc:
        return go(back, err=str(exc))
    return go(back, msg=f"{issue.code} logged.")


@router.post("/issues/{issue_id}")
async def edit_issue(issue_id: int, request: Request, db: Session = Depends(get_db)):
    issue = db.get(Issue, issue_id)
    if issue is None:
        return not_found()
    form = await request.form()
    check_id = _int_or_none(form.get("check_id"))
    check = db.get(Check, check_id) if check_id else None
    if check is not None and check.site_id != issue.site_id:
        return not_found()
    try:
        update_issue(db, issue, check, form)
        db.commit()
    except FormError as exc:
        return go(site_url(issue.site_id, check_id), err=str(exc))
    return go(site_url(issue.site_id, check_id), msg=f"{issue.code} saved.")


@router.post("/issues/{issue_id}/delete")
async def remove_issue(issue_id: int, request: Request, db: Session = Depends(get_db)):
    issue = db.get(Issue, issue_id)
    if issue is None:
        return not_found()
    form = await request.form()
    site_id = issue.site_id
    check_id = _int_or_none(form.get("check_id"))
    code = issue.code
    delete_issue_files(db, issue, request.app.state.upload_dir)
    db.delete(issue)
    db.commit()
    return go(site_url(site_id, check_id), msg=f"{code} deleted.")


@router.post("/checks/{check_id}/include-issues")
async def include_issues(check_id: int, request: Request, db: Session = Depends(get_db)):
    check = db.get(Check, check_id)
    if check is None:
        return not_found()
    added = include_known_issues(db, check)
    db.commit()
    message = "No extra issues to include." if added == 0 else f"Included {added} existing issue(s) in this month."
    return go(site_url(check.site_id, check.id, "issues"), msg=message)


@router.post("/clients/{client_id}/expiries")
async def create_expiry_route(client_id: int, request: Request, db: Session = Depends(get_db)):
    client = db.get(Client, client_id)
    if client is None:
        return not_found()
    form = await request.form()
    check_id = _int_or_none(form.get("check_id"))
    try:
        create_expiry(db, client, form)
        db.commit()
    except FormError as exc:
        return go(site_url(client.id, check_id, "expiries"), err=str(exc))
    return go(site_url(client.id, check_id, "expiries"), msg="Expiry added.")


@router.post("/expiries/{expiry_id}")
async def edit_expiry(expiry_id: int, request: Request, db: Session = Depends(get_db)):
    expiry = db.get(Expiry, expiry_id)
    if expiry is None:
        return not_found()
    form = await request.form()
    check_id = _int_or_none(form.get("check_id"))
    try:
        update_expiry(db, expiry, form)
        db.commit()
    except FormError as exc:
        return go(site_url(expiry.client_id, check_id, "expiries"), err=str(exc))
    return go(site_url(expiry.client_id, check_id, "expiries"), msg="Expiry saved.")


@router.post("/expiries/{expiry_id}/delete")
async def remove_expiry(expiry_id: int, request: Request, db: Session = Depends(get_db)):
    expiry = db.get(Expiry, expiry_id)
    if expiry is None:
        return not_found()
    form = await request.form()
    client_id = expiry.client_id
    check_id = _int_or_none(form.get("check_id"))
    db.delete(expiry)
    db.commit()
    return go(site_url(client_id, check_id, "expiries"), msg="Expiry deleted.")


@router.post("/clients/{client_id}/expiries/copy-warranty")
async def copy_warranty_route(client_id: int, request: Request, db: Session = Depends(get_db)):
    client = db.get(Client, client_id)
    if client is None:
        return not_found()
    form = await request.form()
    check_id = _int_or_none(form.get("check_id"))
    device = db.get(Device, _int_or_none(form.get("device_id")) or 0)
    if device is None:
        return go(site_url(client.id, check_id, "expiries"), err="Choose a device to copy.")
    try:
        copy_warranty(db, client, device)
        db.commit()
    except FormError as exc:
        return go(site_url(client.id, check_id, "expiries"), err=str(exc))
    return go(site_url(client.id, check_id, "expiries"), msg="Warranty copied onto the expiry list.")


@router.post("/attachments")
async def upload_attachment(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    target_type = str(form.get("target_type") or "")
    target_id = _int_or_none(form.get("target_id"))
    fallback = safe_next(form.get("next"), "/")
    if target_id is None:
        return go(fallback, err="Could not find the item for this screenshot.")
    resolved = resolve_attachment_target(db, target_type, target_id)
    if resolved is None:
        return go(fallback, err="Could not find the item for this screenshot.")
    client_id, _row = resolved
    uploads = [item for item in form.getlist("files") if getattr(item, "filename", None)]
    if not uploads:
        return go(fallback, err="Choose a jpg, png, or webp file.")
    if len(uploads) > 8:
        return go(fallback, err="Upload at most 8 files at a time.")
    prepared = []
    try:
        for upload in uploads:
            data = await upload.read()
            mime = validate_image(data)
            prepared.append((upload.filename, data, mime))
        for filename, data, mime in prepared:
            save_attachment(
                db,
                request.app.state.upload_dir,
                client_id=client_id,
                target_type=target_type,
                target_id=target_id,
                original_name=filename,
                data=data,
                mime=mime,
            )
        db.commit()
    except FormError as exc:
        db.rollback()
        return go(fallback, err=str(exc))
    except ValueError as exc:
        db.rollback()
        return go(fallback, err=str(exc))
    return go(fallback, msg="Screenshot uploaded.")


@router.post("/attachments/{attachment_id}/delete")
async def remove_attachment(attachment_id: int, request: Request, db: Session = Depends(get_db)):
    row = db.get(Attachment, attachment_id)
    form = await request.form()
    fallback = safe_next(form.get("next"), "/")
    if row is None:
        return go(fallback, err="Screenshot not found.")
    delete_attachment_row(db, request.app.state.upload_dir, row)
    db.commit()
    return go(fallback, msg="Screenshot deleted.")


@router.get("/attachments/{attachment_id}")
def show_attachment(
    attachment_id: int,
    request: Request,
    thumb: int = 0,
    db: Session = Depends(get_db),
):
    row = db.get(Attachment, attachment_id)
    if row is None:
        return not_found()
    try:
        path = attachment_path(request.app.state.upload_dir, row.stored_name)
    except ValueError:
        return not_found()
    if not path.is_file():
        return not_found()
    if thumb:
        try:
            data, mime = thumbnail_bytes(path)
        except OSError:
            return FileResponse(path, media_type=row.mime)
        return Response(content=data, media_type=mime)
    return FileResponse(path, media_type=row.mime, filename=row.original_name)


@router.get("/checks/{check_id}/export.xlsx")
def export_excel(check_id: int, db: Session = Depends(get_db)):
    check = db.get(Check, check_id)
    if check is None:
        return not_found()
    view = build_check_view(db, check)
    payload = build_xlsx(view)
    filename = _export_name(view["customer"], view["site"], check, "xlsx")
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _disposition(filename)},
    )


@router.get("/checks/{check_id}/export.pdf")
def export_pdf(check_id: int, request: Request, db: Session = Depends(get_db)):
    check = db.get(Check, check_id)
    if check is None:
        return not_found()
    view = build_check_view(db, check)
    try:
        payload = build_pdf(view, request.app.state.upload_dir)
    except Exception as exc:  # noqa: BLE001 — surface a short message, not a stack trace
        return HTMLResponse(
            "<!doctype html><meta charset='utf-8'><title>Could not build PDF</title>"
            f"<p style='font-family:sans-serif'>Could not build the PDF: {exc}</p>",
            status_code=500,
        )
    filename = _export_name(view["customer"], view["site"], check, "pdf")
    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": _disposition(filename)},
    )


def _owned_check(db: Session, customer_id: int, check_id: int | None) -> Check | None:
    if not check_id:
        return None
    check = db.get(Check, check_id)
    if check is None:
        return None
    site = db.get(Site, check.site_id)
    if site is None or site.customer_id != customer_id:
        return None
    return check


def _int_or_none(value) -> int | None:
    text = clean(value, 20)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _export_name(customer: Client, site: Site, check: Check, ext: str) -> str:
    raw = f"{customer.name}_{site.name}_{check.year_month}_health-check.{ext}"
    return raw.replace("/", "-").replace("\\", "-").replace('"', "")


def _disposition(filename: str) -> str:
    ext = Path(filename).suffix or ".bin"
    return f"attachment; filename=\"report{ext}\"; filename*=UTF-8''{quote(filename)}"
