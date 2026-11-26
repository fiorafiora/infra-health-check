"""Status calculations for a monthly check.

Overall light:

    Not started  when every summary count is 0
    Red          when checklist items, devices, or expiries are abnormal / expired
    Amber        when open follow-ups, or 30-day / 90-day expiries, remain
    Green        when the checklist is filled and none of the above apply

Days remaining use the selected check date, not the day the page is opened.
"""

from datetime import date

from app.constants import OPEN_ISSUE_STATUSES

FILLED_RESULTS = ("Normal", "Abnormal", "N/A")


def year_month(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def compare_result(current: str | None, previous: str | None) -> str:
    if not current or not previous:
        return ""
    if current == previous:
        return "Same as last month"
    if previous == "Normal" and current == "Abnormal":
        return "New this month"
    if previous == "Abnormal" and current == "Normal":
        return "Recovered"
    if previous == "N/A" and current != "N/A":
        return "Now in use"
    return "Different"


def expiry_state(expiry_date: date | None, check_date: date | None) -> tuple[int | None, str]:
    """Return (remaining days, status). Days = expiry date minus check date."""
    if expiry_date is None or check_date is None:
        return None, ""
    days = (expiry_date - check_date).days
    if days < 0:
        return days, "Expired"
    if days <= 30:
        return days, "Due in 30 days"
    if days <= 90:
        return days, "Due in 90 days"
    return days, "Normal"


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
        return "Not started"
    if abnormal_items > 0 or abnormal_devices > 0 or expired > 0:
        return "Red"
    if open_followups > 0 or within_30 > 0 or within_90 > 0:
        return "Amber"
    return "Green"


def is_open_status(status: str | None) -> bool:
    return status in OPEN_ISSUE_STATUSES
