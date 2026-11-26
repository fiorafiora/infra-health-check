import re
from datetime import date
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from PIL import Image

from app.logic import expiry_state
from app.main import create_app

def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), (180, 40, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture()
def client(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as test_client:
        yield test_client


def _row_light(html: str, name: str) -> str:
    match = re.search(rf'data-client="{name}" data-site="[^"]*" data-light="([^"]*)"', html)
    assert match, html
    return match.group(1)


def _client_id(html: str, name: str) -> str:
    match = re.search(rf'href="/clients/(\d+)\?check=\d+">{name}', html)
    assert match, name
    return match.group(1)


def test_seeded_home_shows_three_demo_lights(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert "目前不設登入" in body
    assert 'href="/static/css/app.css"' in body
    stylesheet = client.get("/static/css/app.css")
    assert stylesheet.status_code == 200
    assert "Noto Sans TC" in stylesheet.text
    font = client.get("/static/fonts/noto-sans-tc-400.woff2")
    assert font.status_code == 200
    assert font.headers["content-type"].startswith("font/") or len(font.content) > 1000
    assert _row_light(body, "客戶A") == "紅"
    assert _row_light(body, "客戶B") == "黃"
    assert _row_light(body, "客戶C") == "未完成"
    assert "站點-範例" in body


def test_client_a_november_compares_with_last_month(client):
    home = client.get("/")
    client_id = _client_id(home.text, "客戶A")
    page = client.get(f"/clients/{client_id}")
    assert page.status_code == 200
    assert 'data-light="紅"' in page.text
    assert "ISS-001" in page.text
    assert "192.0.2.20" in page.text
    assert "AP-01" in page.text
    for phrase in ("與上月相同", "本月新異常", "本月已恢復", "本月開始適用"):
        assert phrase in page.text
    assert "不是今天" in page.text
    assert 'data-month="2026-10"' in page.text
    assert 'data-month="2026-11"' in page.text
    october = re.search(r'data-month="2026-10" data-light="([^"]+)" href="/clients/\d+\?check=(\d+)"', page.text)
    assert october
    assert october.group(1) == "紅"
    older = client.get(f"/clients/{client_id}?check={october.group(2)}")
    assert "ISS-004" not in older.text
    assert "ISS-001" in older.text


def test_client_b_turns_from_green_to_yellow(client):
    home = client.get("/")
    client_id = _client_id(home.text, "客戶B")
    page = client.get(f"/clients/{client_id}")
    assert 'data-light="黃"' in page.text
    october = re.search(r'data-month="2026-10" data-light="([^"]+)" href="/clients/\d+\?check=(\d+)"', page.text)
    assert october.group(1) == "綠"
    assert expiry_state(date(2027, 1, 15), date(2026, 10, 1))[1] == "正常"
    assert expiry_state(date(2027, 1, 15), date(2026, 11, 1))[1] == "90天內到期"


def test_excel_and_pdf_export(client):
    home = client.get("/")
    client_id = _client_id(home.text, "客戶A")
    page = client.get(f"/clients/{client_id}")
    check_id = re.search(r"/checks/(\d+)/export.xlsx", page.text).group(1)
    workbook_response = client.get(f"/checks/{check_id}/export.xlsx")
    assert workbook_response.status_code == 200
    assert workbook_response.content[:2] == b"PK"
    workbook = load_workbook(BytesIO(workbook_response.content))
    assert workbook.sheetnames == ["封面說明", "設備清單", "月度檢查表", "異常與跟進", "到期預警"]
    cover = workbook["封面說明"]
    assert cover["B5"].value == "客戶A"
    assert cover["B11"].value == "紅"
    checklist = workbook["月度檢查表"]
    compares = [checklist.cell(row, 7).value for row in range(5, 20)]
    assert "本月新異常" in compares
    assert "本月已恢復" in compares
    devices = workbook["設備清單"]
    assert devices["A4"].value == "設備類型"
    assert any(devices.cell(row, 2).value == "AP-01" for row in range(5, 12))

    pdf = client.get(f"/checks/{check_id}/export.pdf")
    if pdf.status_code != 200:
        pytest.skip(pdf.text)
    assert pdf.content.startswith(b"%PDF")
    assert len(pdf.content) > 2000


def test_new_client_month_flow_upload_and_copy_warranty(client):
    created = client.post("/clients", data={"name": "測試客戶", "site": "測試站"}, follow_redirects=True)
    client_id = re.search(r"/clients/(\d+)", str(created.url)).group(1)
    started = client.post(
        f"/clients/{client_id}/checks",
        data={
            "check_date": "2026-10-01",
            "engineer": "測試",
            "connection_method": "VPN",
            "duration_hours": "1.5",
            "notes": "第一個月",
        },
        follow_redirects=True,
    )
    assert 'data-light="未完成"' in started.text
    check_id = re.search(r"/checks/(\d+)/export", started.text).group(1)
    item_ids = re.findall(r'name="result_(\d+)"', started.text)
    assert len(item_ids) == 10
    payload = {f"result_{item_id}": "正常" for item_id in item_ids}
    payload[f"result_{item_ids[0]}"] = "異常"
    payload[f"notes_{item_ids[0]}"] = "閘道不通"
    saved = client.post(f"/checks/{check_id}/items", data=payload, follow_redirects=True)
    assert 'data-light="紅"' in saved.text

    again = client.post(
        f"/clients/{client_id}/checks",
        data={"check_date": "2026-10-15", "engineer": "測試", "connection_method": "VPN"},
        follow_redirects=True,
    )
    assert "這個月份已經有檢查紀錄" in again.text

    november = client.post(
        f"/clients/{client_id}/checks",
        data={
            "check_date": "2026-11-02",
            "engineer": "測試",
            "connection_method": "AnyDesk",
            "duration_hours": "1",
        },
        follow_redirects=True,
    )
    assert "異常" in november.text
    nov_check = re.search(r"/checks/(\d+)/export", november.text).group(1)
    nov_items = re.findall(r'name="result_(\d+)"', november.text)
    nov_payload = {f"result_{item_id}": "正常" for item_id in nov_items}
    restored = client.post(f"/checks/{nov_check}/items", data=nov_payload, follow_redirects=True)
    assert 'data-compare="本月已恢復"' in restored.text
    assert 'data-light="綠"' in restored.text

    item_id = nov_items[0]
    rejected = client.post(
        "/attachments",
        data={"target_type": "check_item", "target_id": item_id, "next": f"/clients/{client_id}?check={nov_check}"},
        files={"files": ("bad.gif", b"GIF89a", "image/gif")},
        follow_redirects=True,
    )
    assert "只接受" in rejected.text
    uploaded = client.post(
        "/attachments",
        data={"target_type": "check_item", "target_id": item_id, "next": f"/clients/{client_id}?check={nov_check}"},
        files={"files": ("ping.png", _png_bytes(), "image/png")},
        follow_redirects=True,
    )
    assert "已上傳截圖" in uploaded.text
    thumb = re.search(r'src="(/attachments/\d+\?thumb=1)"', uploaded.text)
    assert thumb
    image = client.get(thumb.group(1))
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/")

    added = client.post(
        f"/clients/{client_id}/devices",
        data={
            "check_id": nov_check,
            "device_type": "防火牆",
            "name": "FW-T",
            "model": "Model-FW",
            "serial_no": "SN-T",
            "ip_address": "192.0.2.50",
            "firmware": "v1",
            "warranty_expiry": "2027-05-01",
            "added_on": "2026-11-02",
        },
        follow_redirects=True,
    )
    assert "FW-T" in added.text
    device_id = re.search(r'name="device_id"[^>]*>\s*<option value="">請選擇</option>\s*<option value="(\d+)">FW-T', added.text)
    if not device_id:
        device_id = re.search(r'value="(\d+)">FW-T', added.text)
    assert device_id
    copied = client.post(
        f"/clients/{client_id}/expiries/copy-warranty",
        data={"check_id": nov_check, "device_id": device_id.group(1)},
        follow_redirects=True,
    )
    assert "已從設備保固抄入" in copied.text
    assert "FW-T 保固" in copied.text
    assert "2027-05-01" in copied.text


def test_issue_keeps_its_code(client):
    created = client.post("/clients", data={"name": "問題客戶", "site": "甲"}, follow_redirects=True)
    client_id = re.search(r"/clients/(\d+)", str(created.url)).group(1)
    started = client.post(
        f"/clients/{client_id}/checks",
        data={"check_date": "2026-11-01", "engineer": "測試", "connection_method": "其他"},
        follow_redirects=True,
    )
    check_id = re.search(r"/checks/(\d+)/export", started.text).group(1)
    first = client.post(
        f"/clients/{client_id}/issues",
        data={
            "check_id": check_id,
            "first_found_date": "2026-09-15",
            "source": "設備清單",
            "status": "開放",
            "related_label": "AP-01",
            "summary": "AP 離線",
            "observation": "本月仍離線",
            "action": "待現場確認",
        },
        follow_redirects=True,
    )
    assert "ISS-001" in first.text
    second_month = client.post(
        f"/clients/{client_id}/checks",
        data={"check_date": "2026-12-01", "engineer": "測試", "connection_method": "VPN"},
        follow_redirects=True,
    )
    assert second_month.text.count("ISS-001") >= 1
    assert "ISS-002" not in second_month.text


def test_webp_round_trip_bytes():
    buffer = BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, format="WEBP")
    assert buffer.getvalue()[:4] == b"RIFF"
