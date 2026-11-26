from datetime import date

from app.constants import FIXED_ITEMS
from app.logic import compare_result, expiry_state, rag_light


def test_fixed_checklist_order():
    names = [item[2] for item in FIXED_ITEMS]
    assert names == [
        "Ping 核心/閘道",
        "Ping 伺服器",
        "Ping NVR",
        "控制器 AP 離線清單",
        "NVR/伺服器硬碟或 RAID 狀態",
        "磁碟空間",
        "最近一次成功備份",
        "防火牆/授權到期",
        "日誌檢視",
        "韌體檢查",
    ]
    assert [item[1] for item in FIXED_ITEMS[:4]] == ["先查中斷"] * 4
    assert [item[1] for item in FIXED_ITEMS[4:8]] == ["業務關鍵"] * 4
    assert [item[1] for item in FIXED_ITEMS[8:]] == ["建議稍後（可選）"] * 2


def test_compare_matches_excel_formula():
    assert compare_result("", "正常") == ""
    assert compare_result("正常", "") == ""
    assert compare_result("正常", "正常") == "與上月相同"
    assert compare_result("異常", "異常") == "與上月相同"
    assert compare_result("不適用", "不適用") == "與上月相同"
    assert compare_result("異常", "正常") == "本月新異常"
    assert compare_result("正常", "異常") == "本月已恢復"
    assert compare_result("正常", "不適用") == "本月開始適用"
    assert compare_result("異常", "不適用") == "本月開始適用"
    assert compare_result("不適用", "正常") == "與上月不同"
    assert compare_result("不適用", "異常") == "與上月不同"


def test_expiry_boundaries_use_check_date():
    anchor = date(2026, 11, 1)
    assert expiry_state(date(2026, 10, 31), anchor) == (-1, "已過期")
    assert expiry_state(anchor, anchor) == (0, "30天內到期")
    assert expiry_state(date(2026, 12, 1), anchor) == (30, "30天內到期")
    assert expiry_state(date(2026, 12, 2), anchor) == (31, "90天內到期")
    assert expiry_state(date(2027, 1, 30), anchor) == (90, "90天內到期")
    assert expiry_state(date(2027, 1, 31), anchor) == (91, "正常")
    assert expiry_state(None, anchor) == (None, "")


def test_rag_priority_matches_cover_formula():
    assert rag_light(0, 0, 0, 0, 0, 0, 0) == "未完成"
    assert rag_light(1, 1, 0, 0, 0, 0, 0) == "紅"
    assert rag_light(0, 0, 1, 0, 0, 0, 0) == "紅"
    assert rag_light(0, 0, 0, 0, 1, 0, 0) == "紅"
    assert rag_light(1, 1, 0, 1, 0, 1, 1) == "紅"
    assert rag_light(0, 3, 0, 1, 0, 0, 0) == "黃"
    assert rag_light(0, 3, 0, 0, 0, 1, 0) == "黃"
    assert rag_light(0, 3, 0, 0, 0, 0, 1) == "黃"
    assert rag_light(0, 3, 0, 0, 0, 0, 0) == "綠"
    assert rag_light(0, 1, 0, 0, 0, 0, 0) == "綠"
