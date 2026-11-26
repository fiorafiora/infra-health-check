"""Calculations copied from the Excel template formulas.

Overall light (封面 E11):

    未完成  when every summary count is 0
    紅      when checklist abnormalities, device abnormalities, or expired items > 0
    黃      when open follow-ups, 30-day, or 90-day expiries > 0
    綠      otherwise (checklist has been filled and nothing above applies)

Expiry status uses the selected check date, not the day the page is opened.
Comparison text matches the checklist formula on column G.
"""

from datetime import date

from app.constants import OPEN_ISSUE_STATUSES

FILLED_RESULTS = ("正常", "異常", "不適用")


def year_month(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def compare_result(current: str | None, previous: str | None) -> str:
    if not current or not previous:
        return ""
    if current == previous:
        return "與上月相同"
    if previous == "正常" and current == "異常":
        return "本月新異常"
    if previous == "異常" and current == "正常":
        return "本月已恢復"
    if previous == "不適用" and current != "不適用":
        return "本月開始適用"
    return "與上月不同"


def expiry_state(expiry_date: date | None, check_date: date | None) -> tuple[int | None, str]:
    """Return (remaining days, status). Days = expiry date − check date."""
    if expiry_date is None or check_date is None:
        return None, ""
    days = (expiry_date - check_date).days
    if days < 0:
        return days, "已過期"
    if days <= 30:
        return days, "30天內到期"
    if days <= 90:
        return days, "90天內到期"
    return days, "正常"


def rag_light(
    abnormal_items: int,
    filled_items: int,
    abnormal_devices: int,
    open_followups: int,
    expired: int,
    within_30: int,
    within_90: int,
) -> str:
    if (
        abnormal_items == 0
        and filled_items == 0
        and abnormal_devices == 0
        and open_followups == 0
        and expired == 0
        and within_30 == 0
        and within_90 == 0
    ):
        return "未完成"
    if abnormal_items > 0 or abnormal_devices > 0 or expired > 0:
        return "紅"
    if open_followups > 0 or within_30 > 0 or within_90 > 0:
        return "黃"
    return "綠"


def is_open_status(status: str | None) -> bool:
    return status in OPEN_ISSUE_STATUSES
