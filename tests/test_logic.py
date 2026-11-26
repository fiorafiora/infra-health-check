from datetime import date

from app.constants import FIXED_ITEMS
from app.logic import compare_result, expiry_state, rag_light


def test_fixed_checklist_order():
    names = [item[2] for item in FIXED_ITEMS]
    assert names == [
        "Ping core / gateway",
        "Ping servers",
        "Ping NVR",
        "Controller Wi-Fi offline list",
        "NVR / server disk or RAID",
        "Disk space",
        "Last successful backup",
        "Firewall / licence expiry",
        "Log review",
        "Firmware check",
    ]
    assert [item[1] for item in FIXED_ITEMS[:4]] == ["Outage first"] * 4
    assert [item[1] for item in FIXED_ITEMS[4:8]] == ["Business critical"] * 4
    assert [item[1] for item in FIXED_ITEMS[8:]] == ["Later, optional"] * 2


def test_compare_result():
    assert compare_result("", "Normal") == ""
    assert compare_result("Normal", "") == ""
    assert compare_result("Normal", "Normal") == "Same as last month"
    assert compare_result("Abnormal", "Abnormal") == "Same as last month"
    assert compare_result("N/A", "N/A") == "Same as last month"
    assert compare_result("Abnormal", "Normal") == "New this month"
    assert compare_result("Normal", "Abnormal") == "Recovered"
    assert compare_result("Normal", "N/A") == "Now in use"
    assert compare_result("Abnormal", "N/A") == "Now in use"
    assert compare_result("N/A", "Normal") == "Different"
    assert compare_result("N/A", "Abnormal") == "Different"


def test_expiry_boundaries_use_check_date():
    anchor = date(2026, 11, 1)
    assert expiry_state(date(2026, 10, 31), anchor) == (-1, "Expired")
    assert expiry_state(anchor, anchor) == (0, "Due in 30 days")
    assert expiry_state(date(2026, 12, 1), anchor) == (30, "Due in 30 days")
    assert expiry_state(date(2026, 12, 2), anchor) == (31, "Due in 90 days")
    assert expiry_state(date(2027, 1, 30), anchor) == (90, "Due in 90 days")
    assert expiry_state(date(2027, 1, 31), anchor) == (91, "Normal")
    assert expiry_state(None, anchor) == (None, "")


def test_rag_priority():
    assert rag_light(0, 0, 0, 0, 0, 0, 0) == "Not started"
    assert rag_light(1, 1, 0, 0, 0, 0, 0) == "Red"
    assert rag_light(0, 0, 1, 0, 0, 0, 0) == "Red"
    assert rag_light(0, 0, 0, 0, 1, 0, 0) == "Red"
    assert rag_light(1, 1, 0, 1, 0, 1, 1) == "Red"
    assert rag_light(0, 3, 0, 1, 0, 0, 0) == "Amber"
    assert rag_light(0, 3, 0, 0, 0, 1, 0) == "Amber"
    assert rag_light(0, 3, 0, 0, 0, 0, 1) == "Amber"
    assert rag_light(0, 3, 0, 0, 0, 0, 0) == "Green"
    assert rag_light(0, 1, 0, 0, 0, 0, 0) == "Green"
