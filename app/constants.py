"""Choices and fixed checklist copied from the Excel template."""

DEVICE_TYPES = ("伺服器", "交換器", "防火牆", "AP", "NVR", "其他")
DEVICE_STATUSES = ("正常", "異常")
CHECK_RESULTS = ("正常", "異常", "不適用")
CONNECTION_METHODS = ("VPN", "AnyDesk", "其他")
ISSUE_SOURCES = ("設備清單", "月度檢查表", "到期預警", "其他")
ISSUE_STATUSES = ("開放", "跟進中", "已關閉")
OPEN_ISSUE_STATUSES = ("開放", "跟進中")
EXPIRY_KINDS = ("授權", "保固", "SSL憑證", "支援合約", "其他")
EXPIRY_STATUSES = ("已過期", "30天內到期", "90天內到期", "正常")
RAG_LIGHTS = ("紅", "黃", "綠", "未完成")

# Stage labels match the workbook. Item names match the fixed rows.
FIXED_ITEMS: tuple[tuple[int, str, str], ...] = (
    (1, "先查中斷", "Ping 核心/閘道"),
    (2, "先查中斷", "Ping 伺服器"),
    (3, "先查中斷", "Ping NVR"),
    (4, "先查中斷", "控制器 AP 離線清單"),
    (5, "業務關鍵", "NVR/伺服器硬碟或 RAID 狀態"),
    (6, "業務關鍵", "磁碟空間"),
    (7, "業務關鍵", "最近一次成功備份"),
    (8, "業務關鍵", "防火牆/授權到期"),
    (9, "建議稍後（可選）", "日誌檢視"),
    (10, "建議稍後（可選）", "韌體檢查"),
)

CUSTOM_STAGE = "其他項目（按站點需要自行新增）"

STAGE_HEADINGS = {
    "先查中斷": "階段 1　先查中斷",
    "業務關鍵": "階段 2　業務關鍵",
    "建議稍後（可選）": "階段 3　建議稍後（可選）",
    CUSTOM_STAGE: "其他項目（按站點需要自行新增）",
}

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENTS_PER_TARGET = 8
ALLOWED_IMAGE_MIMES = ("image/jpeg", "image/png", "image/webp")
