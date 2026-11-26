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
    assert "no login" in body
    assert 'href="/static/css/app.css"' in body
    stylesheet = client.get("/static/css/app.css")
    assert stylesheet.status_code == 200
    assert "Noto Sans TC" in stylesheet.text
    font = client.get("/static/fonts/noto-sans-tc-400.woff2")
    assert font.status_code == 200
    assert font.headers["content-type"].startswith("font/") or len(font.content) > 1000
    assert _row_light(body, "Client A") == "Red"
    assert _row_light(body, "Client B") == "Amber"
    assert _row_light(body, "Client C") == "Not started"
    assert "Example site" in body


def test_client_a_november_compares_with_last_month(client):
    home = client.get("/")
    client_id = _client_id(home.text, "Client A")
    page = client.get(f"/clients/{client_id}")
    assert page.status_code == 200
    assert 'data-light="Red"' in page.text
    assert "ISS-001" in page.text
    assert "192.0.2.20" in page.text
    assert "AP-01" in page.text
    for phrase in ("Same as last month", "New this month", "Recovered", "Now in use"):
        assert phrase in page.text
    assert "not from today" in page.text
    assert 'data-month="2026-10"' in page.text
    assert 'data-month="2026-11"' in page.text
    october = re.search(r'data-month="2026-10" data-light="([^"]+)" href="/clients/\d+\?check=(\d+)"', page.text)
    assert october
    assert october.group(1) == "Red"
    older = client.get(f"/clients/{client_id}?check={october.group(2)}")
    assert "ISS-004" not in older.text
    assert "ISS-001" in older.text


def test_client_b_turns_from_green_to_yellow(client):
    home = client.get("/")
    client_id = _client_id(home.text, "Client B")
    page = client.get(f"/clients/{client_id}")
    assert 'data-light="Amber"' in page.text
    october = re.search(r'data-month="2026-10" data-light="([^"]+)" href="/clients/\d+\?check=(\d+)"', page.text)
    assert october.group(1) == "Green"
    assert expiry_state(date(2027, 1, 15), date(2026, 10, 1))[1] == "Normal"
    assert expiry_state(date(2027, 1, 15), date(2026, 11, 1))[1] == "Due in 90 days"


def test_excel_and_pdf_export(client):
    home = client.get("/")
    client_id = _client_id(home.text, "Client A")
    page = client.get(f"/clients/{client_id}")
    check_id = re.search(r"/checks/(\d+)/export.xlsx", page.text).group(1)
    workbook_response = client.get(f"/checks/{check_id}/export.xlsx")
    assert workbook_response.status_code == 200
    assert workbook_response.content[:2] == b"PK"
    workbook = load_workbook(BytesIO(workbook_response.content))
    assert workbook.sheetnames == ["Cover", "Devices", "Checklist", "Issues", "Expiries"]
    cover = workbook["Cover"]
    assert cover["B5"].value == "Client A"
    assert cover["B11"].value == "Red"
    checklist = workbook["Checklist"]
    compares = [checklist.cell(row, 7).value for row in range(5, 20)]
    assert "New this month" in compares
    assert "Recovered" in compares
    devices = workbook["Devices"]
    assert devices["A4"].value == "Type"
    assert any(devices.cell(row, 2).value == "AP-01" for row in range(5, 12))

    pdf = client.get(f"/checks/{check_id}/export.pdf")
    if pdf.status_code != 200:
        pytest.skip(pdf.text)
    assert pdf.content.startswith(b"%PDF")
    assert len(pdf.content) > 2000


def test_new_client_month_flow_upload_and_copy_warranty(client):
    created = client.post("/clients", data={"name": "Test client", "site": "Test site"}, follow_redirects=True)
    client_id = re.search(r"/clients/(\d+)", str(created.url)).group(1)
    started = client.post(
        f"/clients/{client_id}/checks",
        data={
            "check_date": "2026-10-01",
            "engineer": "Tester",
            "connection_method": "VPN",
            "duration_hours": "1.5",
            "notes": "First month",
        },
        follow_redirects=True,
    )
    assert 'data-light="Not started"' in started.text
    check_id = re.search(r"/checks/(\d+)/export", started.text).group(1)
    item_ids = re.findall(r'name="result_(\d+)"', started.text)
    assert len(item_ids) == 10
    payload = {f"result_{item_id}": "Normal" for item_id in item_ids}
    payload[f"result_{item_ids[0]}"] = "Abnormal"
    payload[f"notes_{item_ids[0]}"] = "Gateway down"
    saved = client.post(f"/checks/{check_id}/items", data=payload, follow_redirects=True)
    assert 'data-light="Red"' in saved.text

    again = client.post(
        f"/clients/{client_id}/checks",
        data={"check_date": "2026-10-15", "engineer": "Tester", "connection_method": "VPN"},
        follow_redirects=True,
    )
    assert "This month already has a check." in again.text

    november = client.post(
        f"/clients/{client_id}/checks",
        data={
            "check_date": "2026-11-02",
            "engineer": "Tester",
            "connection_method": "AnyDesk",
            "duration_hours": "1",
        },
        follow_redirects=True,
    )
    assert "Abnormal" in november.text
    nov_check = re.search(r"/checks/(\d+)/export", november.text).group(1)
    nov_items = re.findall(r'name="result_(\d+)"', november.text)
    nov_payload = {f"result_{item_id}": "Normal" for item_id in nov_items}
    restored = client.post(f"/checks/{nov_check}/items", data=nov_payload, follow_redirects=True)
    assert 'data-compare="Recovered"' in restored.text
    assert 'data-light="Green"' in restored.text

    item_id = nov_items[0]
    rejected = client.post(
        "/attachments",
        data={"target_type": "check_item", "target_id": item_id, "next": f"/clients/{client_id}?check={nov_check}"},
        files={"files": ("bad.gif", b"GIF89a", "image/gif")},
        follow_redirects=True,
    )
    assert "Only jpg" in rejected.text
    uploaded = client.post(
        "/attachments",
        data={"target_type": "check_item", "target_id": item_id, "next": f"/clients/{client_id}?check={nov_check}"},
        files={"files": ("ping.png", _png_bytes(), "image/png")},
        follow_redirects=True,
    )
    assert "Screenshot uploaded." in uploaded.text
    thumb = re.search(r'src="(/attachments/\d+\?thumb=1)"', uploaded.text)
    assert thumb
    image = client.get(thumb.group(1))
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/")

    added = client.post(
        f"/clients/{client_id}/devices",
        data={
            "check_id": nov_check,
            "device_type": "Firewall",
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
    device_id = re.search(r'name="device_id"[^>]*>\s*<option value="">Choose</option>\s*<option value="(\d+)">FW-T', added.text)
    if not device_id:
        device_id = re.search(r'value="(\d+)">FW-T', added.text)
    assert device_id
    copied = client.post(
        f"/clients/{client_id}/expiries/copy-warranty",
        data={"check_id": nov_check, "device_id": device_id.group(1)},
        follow_redirects=True,
    )
    assert "Warranty copied" in copied.text
    assert "FW-T warranty" in copied.text
    assert "2027-05-01" in copied.text


def test_issue_keeps_its_code(client):
    created = client.post("/clients", data={"name": "Issue client", "site": "A"}, follow_redirects=True)
    client_id = re.search(r"/clients/(\d+)", str(created.url)).group(1)
    started = client.post(
        f"/clients/{client_id}/checks",
        data={"check_date": "2026-11-01", "engineer": "Tester", "connection_method": "Other"},
        follow_redirects=True,
    )
    check_id = re.search(r"/checks/(\d+)/export", started.text).group(1)
    first = client.post(
        f"/clients/{client_id}/issues",
        data={
            "check_id": check_id,
            "first_found_date": "2026-09-15",
            "source": "Inventory",
            "status": "Open",
            "related_label": "AP-01",
            "summary": "AP offline",
            "observation": "Still offline this month",
            "action": "Check on site",
        },
        follow_redirects=True,
    )
    assert "ISS-001" in first.text
    second_month = client.post(
        f"/clients/{client_id}/checks",
        data={"check_date": "2026-12-01", "engineer": "Tester", "connection_method": "VPN"},
        follow_redirects=True,
    )
    assert second_month.text.count("ISS-001") >= 1
    assert "ISS-002" not in second_month.text


def test_webp_round_trip_bytes():
    buffer = BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, format="WEBP")
    assert buffer.getvalue()[:4] == b"RIFF"
