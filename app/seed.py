"""Labelled demo data so the first launch is not an empty database.

Client A has two months so last-month comparison is visible.
Client B turns from green to amber when a licence enters the 90-day window.
Client C is a cover-only check, so the light stays Not started.
Addresses use the documentation range 192.0.2.0/24.
"""

from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Check,
    CheckItem,
    Client,
    CustomCheckItem,
    Device,
    DeviceMonth,
    Expiry,
    Issue,
    IssueMonth,
    Meta,
)
from app.storage import save_attachment

D = date


def seed_if_empty(db: Session, upload_dir: Path) -> None:
    if db.get(Meta, "seeded"):
        return
    if db.scalar(select(func.count()).select_from(Client)) == 0:
        _seed(db, upload_dir)
    db.add(Meta(key="seeded", value="1"))


def _seed(db: Session, upload_dir: Path) -> None:
    client_a = _client(db, "Client A", "Example site", "Example data. Delete before real use.")
    srv, fw, sw, ap, nvr = _devices_a(db, client_a)
    ups = CustomCheckItem(client_id=client_a.id, name="UPS battery status", sort_order=10, active=True)
    db.add(ups)
    db.flush()

    oct_a = _check(
        db,
        client_a,
        D(2026, 10, 1),
        "VPN",
        1.5,
        "Example: October visit. AP-01 is still offline under ISS-001.",
    )
    nov_a = _check(
        db,
        client_a,
        D(2026, 11, 1),
        "AnyDesk",
        2,
        "Example: November visit. AP still offline; NVR disk is a new fault; backup has recovered.",
    )
    _items(
        db,
        oct_a,
        ups,
        {
            1: ("Normal", "Example: core gateway replies", None),
            2: ("Normal", None, None),
            3: ("Normal", None, None),
            4: ("Abnormal", "Example: AP-01 offline, see ISS-001", None),
            5: ("Normal", None, None),
            6: ("Normal", "Example: space is acceptable", None),
            7: ("Abnormal", "Example: last successful backup is older than 14 days", None),
            8: ("Normal", "Example: licence runs to 2026-12-31", None),
            9: ("Normal", None, None),
            10: ("N/A", "Example: no firmware check planned this month", None),
        },
        custom_result=("Normal", "Example: battery self-test passed", None),
    )
    _items(
        db,
        nov_a,
        ups,
        {
            1: ("Normal", None, "Normal"),
            2: ("Normal", None, "Normal"),
            3: ("Normal", None, "Normal"),
            4: ("Abnormal", "Example: AP-01 still offline, see ISS-001", "Abnormal"),
            5: ("Normal", None, "Normal"),
            6: ("Abnormal", "Example: NVR-01 has under 15% free", "Normal"),
            7: ("Normal", "Example: successful backup record dated 2026-10-28 received", "Abnormal"),
            8: ("Normal", "Example: licence to 2026-12-31, see expiries", "Normal"),
            9: ("Normal", None, "Normal"),
            10: ("Normal", "Example: sampled FW-01 v2.0.0", "N/A"),
        },
        custom_result=("Normal", None, "Normal"),
    )
    _device_months(
        db,
        oct_a,
        [
            (srv, "Normal", None, None, None, D(2026, 9, 1)),
            (fw, "Normal", None, None, None, D(2026, 9, 1)),
            (sw, "Normal", None, None, None, D(2026, 9, 1)),
            (ap, "Abnormal", "Example: controller shows offline", "See ISS-001", D(2026, 9, 15), D(2026, 9, 1)),
            (nvr, "Normal", None, None, None, D(2026, 9, 1)),
        ],
    )
    ap_nov, nvr_nov = _device_months(
        db,
        nov_a,
        [
            (srv, "Normal", None, None, None, D(2026, 10, 1)),
            (fw, "Normal", None, None, None, D(2026, 10, 1)),
            (sw, "Normal", None, None, None, D(2026, 10, 1)),
            (ap, "Abnormal", "Example: controller shows offline", "See ISS-001", D(2026, 9, 15), D(2026, 10, 1)),
            (nvr, "Abnormal", "Example: disk space is low", "See ISS-004", D(2026, 11, 1), D(2026, 10, 1)),
        ],
    )

    iss1 = _issue(
        db,
        client_a,
        "ISS-001",
        D(2026, 9, 15),
        "Inventory",
        "AP-01",
        ap.id,
        "Example: AP offline",
        "Open",
        "Example: waiting for the client to check on site",
        None,
    )
    iss2 = _issue(
        db,
        client_a,
        "ISS-002",
        D(2026, 8, 1),
        "Checklist",
        "Last successful backup",
        None,
        "Example: backup was overdue and already logged",
        "Closed",
        "Example: no further follow-up",
        D(2026, 11, 1),
    )
    iss3 = _issue(
        db,
        client_a,
        "ISS-003",
        D(2026, 7, 1),
        "Expiry",
        "FW-01",
        fw.id,
        "Example: licence renewal completed",
        "Closed",
        None,
        D(2026, 10, 20),
    )
    iss4 = _issue(
        db,
        client_a,
        "ISS-004",
        D(2026, 11, 1),
        "Checklist",
        "Disk space / NVR-01",
        nvr.id,
        "Example: NVR disk space is low",
        "Open",
        "Example: ask the client to confirm retention days",
        None,
    )
    _issue_month(db, iss1, oct_a, "Open", "Example: still offline this month", "Example: waiting for an on-site check")
    _issue_month(db, iss2, oct_a, "In progress", "Example: still waiting for a backup record", "Example: review next month")
    _issue_month(db, iss3, oct_a, "In progress", "Example: renewal in progress", "Example: waiting for the vendor")
    _issue_month(db, iss1, nov_a, "Open", "Example: still offline this month", "Example: waiting for an on-site check")
    _issue_month(db, iss2, nov_a, "Closed", "Example: October backup record received", "Example: no further follow-up")
    _issue_month(db, iss3, nov_a, "Closed", "Example: renewal done; kept as a record", None)
    _issue_month(db, iss4, nov_a, "Open", "Example: under 15% free", "Example: ask the client to confirm retention")

    db.add_all(
        [
            Expiry(
                client_id=client_a.id,
                kind="Licence",
                name="Firewall licence (example)",
                device_id=fw.id,
                related_label="FW-01",
                expiry_date=D(2026, 12, 31),
                notes="Example: 60 days from 1 Nov, so within 90 days.",
            ),
            Expiry(
                client_id=client_a.id,
                kind="Warranty",
                name="Server warranty (example)",
                device_id=srv.id,
                related_label="SRV-01",
                expiry_date=D(2027, 6, 30),
                notes="Example: copied from the device warranty.",
                copied_from_device=True,
            ),
            Expiry(
                client_id=client_a.id,
                kind="SSL certificate",
                name="Example SSL certificate",
                device_id=srv.id,
                related_label="192.0.2.10",
                expiry_date=D(2026, 11, 15),
                notes="Example: installed on SRV-01. 14 days from 1 Nov.",
            ),
            Expiry(
                client_id=client_a.id,
                kind="Support contract",
                name="Core switch support (example)",
                device_id=sw.id,
                related_label="SW-01",
                expiry_date=D(2026, 9, 1),
                notes="Example: support contract has expired. Hardware warranty runs to 2027-03-31 and has not been copied.",
            ),
        ]
    )
    db.flush()

    ap_png = _demo_png(
        "Controller (example screen)",
        ["AP-01    offline", "AP-02    online", "192.0.2.20"],
    )
    disk_png = _demo_png(
        "NVR storage (example screen)",
        ["NVR-01  disk 12% free", "Clear files or add capacity"],
    )
    item4 = db.scalar(
        select(CheckItem).where(CheckItem.check_id == nov_a.id, CheckItem.seq == 4)
    )
    item6 = db.scalar(
        select(CheckItem).where(CheckItem.check_id == nov_a.id, CheckItem.seq == 6)
    )
    save_attachment(
        db, upload_dir,
        client_id=client_a.id, target_type="device_month", target_id=ap_nov.id,
        original_name="example-AP-01-offline.png", data=ap_png, mime="image/png",
    )
    save_attachment(
        db, upload_dir,
        client_id=client_a.id, target_type="check_item", target_id=item4.id,
        original_name="example-AP-offline-list.png", data=ap_png, mime="image/png",
    )
    save_attachment(
        db, upload_dir,
        client_id=client_a.id, target_type="issue", target_id=iss1.id,
        original_name="example-ISS-001.png", data=ap_png, mime="image/png",
    )
    save_attachment(
        db, upload_dir,
        client_id=client_a.id, target_type="device_month", target_id=nvr_nov.id,
        original_name="example-NVR-disk-space.png", data=disk_png, mime="image/png",
    )
    save_attachment(
        db, upload_dir,
        client_id=client_a.id, target_type="check_item", target_id=item6.id,
        original_name="example-disk-space.png", data=disk_png, mime="image/png",
    )

    client_b = _client(db, "Client B", "Head office", "Example of a green month turning amber. Delete before real use.")
    fw2, srv2, ap2 = _devices_b(db, client_b)
    oct_b = _check(
        db, client_b, D(2026, 10, 1), "VPN", 1,
        "Example: everything normal, licence not yet inside 90 days.",
    )
    nov_b = _check(
        db, client_b, D(2026, 11, 1), "VPN", 1,
        "Example: results match last month, but the firewall licence is now inside 90 days, so the light is amber.",
    )
    b_oct = {n: ("N/A" if n == 3 else "Normal", "Example: this site has no NVR" if n == 3 else None, None) for n in range(1, 11)}
    b_nov = {
        n: (
            "N/A" if n == 3 else "Normal",
            "Example: this site has no NVR" if n == 3 else None,
            "N/A" if n == 3 else "Normal",
        )
        for n in range(1, 11)
    }
    _items(db, oct_b, None, b_oct, None)
    _items(db, nov_b, None, b_nov, None)
    for check, last in ((oct_b, D(2026, 9, 1)), (nov_b, D(2026, 10, 1))):
        _device_months(
            db,
            check,
            [
                (fw2, "Normal", None, None, None, last),
                (srv2, "Normal", None, None, None, last),
                (ap2, "Normal", None, None, None, last),
            ],
        )
    db.add(
        Expiry(
            client_id=client_b.id,
            kind="Licence",
            name="Firewall licence (example)",
            device_id=fw2.id,
            related_label="FW-02",
            expiry_date=D(2027, 1, 15),
            notes="Example: still normal on 1 Oct; inside 90 days on 1 Nov.",
        )
    )

    client_c = _client(db, "Client C", "Warehouse", "Example of a month that has not been filled in. Delete before real use.")
    nvr3 = Device(
        client_id=client_c.id,
        device_type="NVR",
        name="NVR-03",
        model="Model-NVR",
        serial_no="SN-NVR003",
        ip_address="192.0.2.210",
        firmware="v4.0.0",
        warranty_expiry=D(2028, 12, 31),
        added_on=D(2026, 11, 6),
        sort_order=10,
    )
    db.add(nvr3)
    db.flush()
    nov_c = _check(
        db, client_c, D(2026, 11, 6), "Other", 0.5,
        "Example: cover only. The checklist has not been filled in.",
    )
    _items(db, nov_c, None, {}, None)
    db.add(DeviceMonth(check_id=nov_c.id, device_id=nvr3.id, last_check_date=None))
    db.add(
        Expiry(
            client_id=client_c.id,
            kind="Warranty",
            name="NVR warranty (example)",
            device_id=nvr3.id,
            related_label="NVR-03",
            expiry_date=D(2028, 12, 31),
            notes="Example: status is Normal, which is not enough on its own to turn the light green.",
            copied_from_device=True,
        )
    )
    db.flush()


def _client(db: Session, name: str, site: str, notes: str) -> Client:
    client = Client(name=name, site=site, notes=notes, is_demo=True)
    db.add(client)
    db.flush()
    return client


def _devices_a(db: Session, client: Client):
    rows = [
        ("Server", "SRV-01", "Model-X", "SN-XXXX", "192.0.2.10", "v1.2.0", D(2027, 6, 30), 10),
        ("Firewall", "FW-01", "Model-FW", "SN-FW001", "192.0.2.1", "v2.0.0", D(2026, 12, 31), 20),
        ("Switch", "SW-01", "Model-SW", "SN-SW001", "192.0.2.2", "v1.0.5", D(2027, 3, 31), 30),
        ("AP", "AP-01", "Model-AP", "SN-AP001", "192.0.2.20", "v3.1.0", None, 40),
        ("NVR", "NVR-01", "Model-NVR", "SN-NVR001", "192.0.2.30", "v4.0.0", None, 50),
    ]
    devices = []
    for device_type, name, model, serial_no, ip_address, firmware, warranty, sort_order in rows:
        device = Device(
            client_id=client.id,
            device_type=device_type,
            name=name,
            model=model,
            serial_no=serial_no,
            ip_address=ip_address,
            firmware=firmware,
            warranty_expiry=warranty,
            added_on=D(2026, 9, 1),
            sort_order=sort_order,
        )
        db.add(device)
        devices.append(device)
    db.flush()
    return devices


def _devices_b(db: Session, client: Client):
    rows = [
        ("Firewall", "FW-02", "Model-FW", "SN-FW002", "192.0.2.101", "v2.1.0", D(2028, 6, 30), 10),
        ("Server", "SRV-02", "Model-X", "SN-SRV002", "192.0.2.110", "v1.4.0", D(2028, 6, 30), 20),
        ("AP", "AP-02", "Model-AP", "SN-AP002", "192.0.2.120", "v3.2.0", None, 30),
    ]
    devices = []
    for device_type, name, model, serial_no, ip_address, firmware, warranty, sort_order in rows:
        device = Device(
            client_id=client.id,
            device_type=device_type,
            name=name,
            model=model,
            serial_no=serial_no,
            ip_address=ip_address,
            firmware=firmware,
            warranty_expiry=warranty,
            added_on=D(2026, 9, 1),
            sort_order=sort_order,
        )
        db.add(device)
        devices.append(device)
    db.flush()
    return devices


def _check(db: Session, client: Client, check_date: date, method: str, hours: float, notes: str) -> Check:
    check = Check(
        client_id=client.id,
        check_date=check_date,
        year_month=f"{check_date.year:04d}-{check_date.month:02d}",
        engineer="Example engineer",
        connection_method=method,
        duration_hours=hours,
        notes=notes,
    )
    db.add(check)
    db.flush()
    return check


def _items(db, check, custom, fixed_map, custom_result):
    from app.constants import FIXED_ITEMS

    for seq, stage, name in FIXED_ITEMS:
        result, notes, prev = fixed_map.get(seq, (None, None, None))
        db.add(
            CheckItem(
                check_id=check.id,
                seq=seq,
                stage=stage,
                name=name,
                is_custom=False,
                result=result,
                notes=notes,
                prev_result=prev,
            )
        )
    if custom is not None and custom_result is not None:
        result, notes, prev = custom_result
        db.add(
            CheckItem(
                check_id=check.id,
                seq=11,
                stage="Extra items for this site",
                name=custom.name,
                is_custom=True,
                custom_item_id=custom.id,
                result=result,
                notes=notes,
                prev_result=prev,
            )
        )
    db.flush()


def _device_months(db, check, rows):
    created = []
    for device, status, summary, follow, found, last in rows:
        row = DeviceMonth(
            check_id=check.id,
            device_id=device.id,
            status=status,
            exception_summary=summary,
            follow_up=follow,
            first_found_date=found,
            last_check_date=last,
        )
        db.add(row)
        created.append(row)
    db.flush()
    # Return the AP and NVR month rows when both are present (client A layout).
    by_name = {rows[i][0].name: created[i] for i in range(len(rows))}
    return by_name.get("AP-01"), by_name.get("NVR-01")


def _issue(db, client, code, found, source, related, device_id, summary, status, action, close_date):
    issue = Issue(
        client_id=client.id,
        code=code,
        first_found_date=found,
        source=source,
        related_label=related,
        device_id=device_id,
        summary=summary,
        status=status,
        action=action,
        close_date=close_date,
    )
    db.add(issue)
    db.flush()
    return issue


def _issue_month(db, issue, check, status, observation, action):
    db.add(
        IssueMonth(
            issue_id=issue.id,
            check_id=check.id,
            status=status,
            observation=observation,
            action=action,
        )
    )


def _font(size: int):
    candidates = []
    root = Path("/usr/share/fonts")
    if root.exists():
        candidates.extend(root.rglob("NotoSansCJK-Regular.ttc"))
        candidates.extend(root.rglob("NotoSansCJKtc-Regular.otf"))
        candidates.extend(root.rglob("NotoSansTC-Regular.otf"))
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    return ImageFont.load_default()


def _demo_png(title: str, lines: list[str]) -> bytes:
    image = Image.new("RGB", (720, 400), "#f4f7fb")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 720, 64), fill="#0f4c81")
    draw.rectangle((24, 96, 696, 300), outline="#d5deea", width=2)
    font = _font(22)
    small = _font(20)
    draw.text((20, 18), title, fill="white", font=font)
    y = 120
    for line in lines:
        draw.text((48, y), line, fill="#1c2430", font=small)
        y += 40
    draw.text((24, 340), "DEMO — example screenshot, not a live screen", fill="#5c6b7a", font=small)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
