"""Labelled demo data so the first launch is not an empty database.

客戶A has two months so last-month comparison is visible.
客戶B shows a green month turning yellow when a licence enters the 90-day window.
客戶C is a cover-only check, so the light stays 未完成.
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
    client_a = _client(db, "客戶A", "站點-範例", "示範用。請在正式使用前刪除。")
    srv, fw, sw, ap, nvr = _devices_a(db, client_a)
    ups = CustomCheckItem(client_id=client_a.id, name="UPS 電池狀態", sort_order=10, active=True)
    db.add(ups)
    db.flush()

    oct_a = _check(
        db,
        client_a,
        D(2026, 10, 1),
        "VPN",
        1.5,
        "範例：十月例行檢查。AP-01 離線沿用 ISS-001。",
    )
    nov_a = _check(
        db,
        client_a,
        D(2026, 11, 1),
        "AnyDesk",
        2,
        "範例：十一月例行檢查。AP 仍離線；NVR 磁碟空間新異常；備份已恢復。",
    )
    _items(
        db,
        oct_a,
        ups,
        {
            1: ("正常", "範例：核心閘道有回應", None),
            2: ("正常", None, None),
            3: ("正常", None, None),
            4: ("異常", "範例：AP-01 離線，見 ISS-001", None),
            5: ("正常", None, None),
            6: ("正常", "範例：空間尚可", None),
            7: ("異常", "範例：最近成功備份超過 14 日", None),
            8: ("正常", "範例：授權至 2026-12-31", None),
            9: ("正常", None, None),
            10: ("不適用", "範例：本月未安排韌體檢查", None),
        },
        custom_result=("正常", "範例：電池自測通過", None),
    )
    _items(
        db,
        nov_a,
        ups,
        {
            1: ("正常", None, "正常"),
            2: ("正常", None, "正常"),
            3: ("正常", None, "正常"),
            4: ("異常", "範例：AP-01 仍離線，見 ISS-001", "異常"),
            5: ("正常", None, "正常"),
            6: ("異常", "範例：NVR-01 剩餘空間低於 15%", "正常"),
            7: ("正常", "範例：已收到 2026-10-28 備份成功紀錄", "異常"),
            8: ("正常", "範例：授權 2026-12-31，見到期預警", "正常"),
            9: ("正常", None, "正常"),
            10: ("正常", "範例：已抽查 FW-01 v2.0.0", "不適用"),
        },
        custom_result=("正常", None, "正常"),
    )
    _device_months(
        db,
        oct_a,
        [
            (srv, "正常", None, None, None, D(2026, 9, 1)),
            (fw, "正常", None, None, None, D(2026, 9, 1)),
            (sw, "正常", None, None, None, D(2026, 9, 1)),
            (ap, "異常", "範例：控制器顯示離線", "見 ISS-001", D(2026, 9, 15), D(2026, 9, 1)),
            (nvr, "正常", None, None, None, D(2026, 9, 1)),
        ],
    )
    ap_nov, nvr_nov = _device_months(
        db,
        nov_a,
        [
            (srv, "正常", None, None, None, D(2026, 10, 1)),
            (fw, "正常", None, None, None, D(2026, 10, 1)),
            (sw, "正常", None, None, None, D(2026, 10, 1)),
            (ap, "異常", "範例：控制器顯示離線", "見 ISS-001", D(2026, 9, 15), D(2026, 10, 1)),
            (nvr, "異常", "範例：磁碟空間不足", "見 ISS-004", D(2026, 11, 1), D(2026, 10, 1)),
        ],
    )

    iss1 = _issue(
        db,
        client_a,
        "ISS-001",
        D(2026, 9, 15),
        "設備清單",
        "AP-01",
        ap.id,
        "範例：AP 離線",
        "開放",
        "範例：待客戶現場確認",
        None,
    )
    iss2 = _issue(
        db,
        client_a,
        "ISS-002",
        D(2026, 8, 1),
        "月度檢查表",
        "最近一次成功備份",
        None,
        "範例：備份逾期，上月已登記",
        "已關閉",
        "範例：無需再跟進",
        D(2026, 11, 1),
    )
    iss3 = _issue(
        db,
        client_a,
        "ISS-003",
        D(2026, 7, 1),
        "到期預警",
        "FW-01",
        fw.id,
        "範例：授權續約已完成",
        "已關閉",
        None,
        D(2026, 10, 20),
    )
    iss4 = _issue(
        db,
        client_a,
        "ISS-004",
        D(2026, 11, 1),
        "月度檢查表",
        "磁碟空間 / NVR-01",
        nvr.id,
        "範例：NVR 磁碟空間不足",
        "開放",
        "範例：請客戶確認保留天數",
        None,
    )
    _issue_month(db, iss1, oct_a, "開放", "範例：本月仍離線", "範例：待客戶現場確認")
    _issue_month(db, iss2, oct_a, "跟進中", "範例：仍待客戶提供備份紀錄", "範例：下月覆核")
    _issue_month(db, iss3, oct_a, "跟進中", "範例：續約處理中", "範例：待廠商確認")
    _issue_month(db, iss1, nov_a, "開放", "範例：本月仍離線", "範例：待客戶現場確認")
    _issue_month(db, iss2, nov_a, "已關閉", "範例：十月備份紀錄已補齊", "範例：無需再跟進")
    _issue_month(db, iss3, nov_a, "已關閉", "範例：續約完成，可留作紀錄", None)
    _issue_month(db, iss4, nov_a, "開放", "範例：剩餘低於 15%", "範例：請客戶確認保留天數")

    db.add_all(
        [
            Expiry(
                client_id=client_a.id,
                kind="授權",
                name="防火牆授權（範例）",
                device_id=fw.id,
                related_label="FW-01",
                expiry_date=D(2026, 12, 31),
                notes="範例：相對 11 月 1 日剩餘 60 日，屬 90 天內。",
            ),
            Expiry(
                client_id=client_a.id,
                kind="保固",
                name="伺服器保固（範例）",
                device_id=srv.id,
                related_label="SRV-01",
                expiry_date=D(2027, 6, 30),
                notes="範例：由設備保固抄入的寫法。",
                copied_from_device=True,
            ),
            Expiry(
                client_id=client_a.id,
                kind="SSL憑證",
                name="範例 SSL 憑證",
                device_id=srv.id,
                related_label="192.0.2.10",
                expiry_date=D(2026, 11, 15),
                notes="範例：裝在 SRV-01。相對 11 月 1 日剩餘 14 日。",
            ),
            Expiry(
                client_id=client_a.id,
                kind="支援合約",
                name="核心交換器支援（範例）",
                device_id=sw.id,
                related_label="SW-01",
                expiry_date=D(2026, 9, 1),
                notes="範例：支援合約已過期；硬體保固仍至 2027-03-31，尚未抄入。",
            ),
        ]
    )
    db.flush()

    ap_png = _demo_png(
        "控制器（範例畫面）",
        ["AP-01    離線", "AP-02    在線", "192.0.2.20"],
    )
    disk_png = _demo_png(
        "NVR 儲存（範例畫面）",
        ["NVR-01  磁碟剩餘 12%", "建議清檔或擴充"],
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
        original_name="範例-AP-01-離線.png", data=ap_png, mime="image/png",
    )
    save_attachment(
        db, upload_dir,
        client_id=client_a.id, target_type="check_item", target_id=item4.id,
        original_name="範例-AP離線清單.png", data=ap_png, mime="image/png",
    )
    save_attachment(
        db, upload_dir,
        client_id=client_a.id, target_type="issue", target_id=iss1.id,
        original_name="範例-ISS-001.png", data=ap_png, mime="image/png",
    )
    save_attachment(
        db, upload_dir,
        client_id=client_a.id, target_type="device_month", target_id=nvr_nov.id,
        original_name="範例-NVR-磁碟空間.png", data=disk_png, mime="image/png",
    )
    save_attachment(
        db, upload_dir,
        client_id=client_a.id, target_type="check_item", target_id=item6.id,
        original_name="範例-磁碟空間.png", data=disk_png, mime="image/png",
    )

    client_b = _client(db, "客戶B", "總部-範例", "示範燈號由綠轉黃。請在正式使用前刪除。")
    fw2, srv2, ap2 = _devices_b(db, client_b)
    oct_b = _check(
        db, client_b, D(2026, 10, 1), "VPN", 1,
        "範例：各項正常，授權尚未進入 90 天。",
    )
    nov_b = _check(
        db, client_b, D(2026, 11, 1), "VPN", 1,
        "範例：檢查結果與上月相同，但防火牆授權已進入 90 天內，燈號轉黃。",
    )
    b_oct = {n: ("不適用" if n == 3 else "正常", "範例：此站沒有 NVR" if n == 3 else None, None) for n in range(1, 11)}
    b_nov = {
        n: (
            "不適用" if n == 3 else "正常",
            "範例：此站沒有 NVR" if n == 3 else None,
            "不適用" if n == 3 else "正常",
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
                (fw2, "正常", None, None, None, last),
                (srv2, "正常", None, None, None, last),
                (ap2, "正常", None, None, None, last),
            ],
        )
    db.add(
        Expiry(
            client_id=client_b.id,
            kind="授權",
            name="防火牆授權（範例）",
            device_id=fw2.id,
            related_label="FW-02",
            expiry_date=D(2027, 1, 15),
            notes="範例：相對 10 月 1 日仍屬正常；相對 11 月 1 日進入 90 天內。",
        )
    )

    client_c = _client(db, "客戶C", "倉庫-範例", "示範尚未開始填寫的月份。請在正式使用前刪除。")
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
        db, client_c, D(2026, 11, 6), "其他", 0.5,
        "範例：只填了封面，尚未填寫檢查表。",
    )
    _items(db, nov_c, None, {}, None)
    db.add(DeviceMonth(check_id=nov_c.id, device_id=nvr3.id, last_check_date=None))
    db.add(
        Expiry(
            client_id=client_c.id,
            kind="保固",
            name="NVR 保固（範例）",
            device_id=nvr3.id,
            related_label="NVR-03",
            expiry_date=D(2028, 12, 31),
            notes="範例：狀態為正常，不足以讓燈號變成綠。",
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
        ("伺服器", "SRV-01", "Model-X", "SN-XXXX", "192.0.2.10", "v1.2.0", D(2027, 6, 30), 10),
        ("防火牆", "FW-01", "Model-FW", "SN-FW001", "192.0.2.1", "v2.0.0", D(2026, 12, 31), 20),
        ("交換器", "SW-01", "Model-SW", "SN-SW001", "192.0.2.2", "v1.0.5", D(2027, 3, 31), 30),
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
        ("防火牆", "FW-02", "Model-FW", "SN-FW002", "192.0.2.101", "v2.1.0", D(2028, 6, 30), 10),
        ("伺服器", "SRV-02", "Model-X", "SN-SRV002", "192.0.2.110", "v1.4.0", D(2028, 6, 30), 20),
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
        engineer="工程師（範例）",
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
                stage="其他項目（按站點需要自行新增）",
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
    draw.text((24, 340), "DEMO  示範截圖  非真實畫面", fill="#5c6b7a", font=small)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
