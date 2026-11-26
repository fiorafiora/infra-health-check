"""Fixed choices and the monthly checklist order."""

DEVICE_TYPES = ("Server", "Router", "Switch", "Firewall", "AP", "NVR", "Other")
DEVICE_STATUSES = ("Normal", "Abnormal")
CHECK_RESULTS = ("Normal", "Abnormal", "N/A")
CONNECTION_METHODS = ("VPN", "AnyDesk", "Other")
ISSUE_SOURCES = ("Inventory", "Checklist", "Expiry", "Other")
ISSUE_STATUSES = ("Open", "In progress", "Closed")
OPEN_ISSUE_STATUSES = ("Open", "In progress")
EXPIRY_KINDS = ("Licence", "Warranty", "SSL certificate", "Support contract", "Other")
EXPIRY_STATUSES = ("Expired", "Due in 30 days", "Due in 90 days", "Normal")
RAG_LIGHTS = ("Red", "Amber", "Green", "Not started")

FIXED_ITEMS: tuple[tuple[int, str, str], ...] = (
    (1, "Outage first", "Ping core / gateway"),
    (2, "Outage first", "Ping servers"),
    (3, "Outage first", "Ping NVR"),
    (4, "Outage first", "Controller AP offline list"),
    (5, "Business critical", "NVR / server disk or RAID"),
    (6, "Business critical", "Disk space"),
    (7, "Business critical", "Last successful backup"),
    (8, "Business critical", "Firewall / licence expiry"),
    (9, "Later, optional", "Log review"),
    (10, "Later, optional", "Firmware check"),
)

CUSTOM_STAGE = "Extra items for this site"

STAGE_HEADINGS = {
    "Outage first": "Stage 1 — Outage first",
    "Business critical": "Stage 2 — Business critical",
    "Later, optional": "Stage 3 — Later, optional",
    CUSTOM_STAGE: "Extra items for this site",
}

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENTS_PER_TARGET = 8
ALLOWED_IMAGE_MIMES = ("image/jpeg", "image/png", "image/webp")
