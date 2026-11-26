"""Monthly workbook and PDF. Values are calculated; they are not Excel macros."""

import base64
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from app.constants import STAGE_HEADINGS
from app.storage import thumbnail_bytes

NAVY = "0F4C81"
INK = "1C2430"
RED = "B42318"
RED_BG = "FDECEA"
AMBER = "B54708"
AMBER_BG = "FFF6E8"
GREEN = "067647"
GREEN_BG = "E7F6EE"
SLATE = "475467"
SLATE_BG = "F2F4F7"
LINE = "D5DEE8"
ZEBRA = "F7F9FB"
WHITE = "FFFFFF"

THIN = Border(
    left=Side(style="thin", color=LINE),
    right=Side(style="thin", color=LINE),
    top=Side(style="thin", color=LINE),
    bottom=Side(style="thin", color=LINE),
)
WRAP = Alignment(wrap_text=True, vertical="center")
CENTER = Alignment(wrap_text=True, vertical="center", horizontal="center")


def build_xlsx(view: dict) -> bytes:
    client = view["client"]
    check = view["check"]
    wb = Workbook()
    _cover(wb.active, view)
    _devices(wb.create_sheet("Devices"), view)
    _issues(wb.create_sheet("Issues"), view)
    site = view.get("site")
    customer = view.get("customer") or client
    wb.properties.title = f"{customer.name} {site.name if site else ''} {check.year_month} health check"
    wb.properties.creator = "Monthly remote health check"
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_pdf(view: dict, upload_dir: Path) -> bytes:
    from weasyprint import HTML

    images, skipped = _pdf_images(view, upload_dir)
    html = _pdf_html(view, images, skipped)
    font_css = _font_face_css()
    return HTML(string=font_css + html, base_url=str(upload_dir)).write_pdf()


def _cover(ws, view):
    ws.title = "Cover"
    client, check, counts = view["client"], view["check"], view["counts"]
    ws.sheet_properties.tabColor = NAVY
    ws["A1"] = "Monthly remote health check"
    ws.merge_cells("A1:D1")
    ws["A2"] = "Monthly remote health check"
    ws.merge_cells("A2:D2")
    ws["A4"] = "This check"
    rows = [
        (5, "Customer", client.name),
        (6, "Site", view["site"].name if view.get("site") else ""),
        (7, "Check date", check.check_date),
        (8, "Engineer", check.engineer),
        (9, "Duration (hours)", check.duration_hours),
        (10, "Overall", view["light"]),
        (11, "Notes", check.notes or ""),
    ]
    for row, label, value in rows:
        ws.cell(row, 1, label)
        ws.cell(row, 2, value)
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
    ws["A14"] = "This month"
    ws.merge_cells("A14:D14")
    summary = [
        (15, "Abnormal checklist items", counts["abnormal_items"]),
        (16, "Checklist items filled", counts["filled_items"]),
        (17, "Abnormal devices", counts["abnormal_devices"]),
    ]
    for row, label, value in summary:
        ws.cell(row, 1, label)
        ws.cell(row, 2, value)
    ws["A23"] = "How the light is decided"
    legend = [
        (24, "Red: a device check is Abnormal."),
        (25, "Green: at least one check is filled in, and none are Abnormal."),
        (26, "Not started: no check result yet."),
        (27, "This report is this site only. Other sites of the customer are separate reports."),
        (28, "A check records that moment only. It is not 24-hour monitoring."),
        (31, "Repeat issues keep the same ID. Screenshot file names are listed; images are not embedded in this workbook."),
    ]
    for row, text in legend:
        ws.cell(row, 1, text)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    _paint_title(ws["A1"])
    ws["A2"].font = Font(name="Calibri", size=12, color=SLATE)
    ws["A4"].font = Font(name="Calibri", bold=True, size=13, color=NAVY)
    ws["A14"].font = Font(name="Calibri", bold=True, size=13, color=NAVY)
    ws["A23"].font = Font(name="Calibri", bold=True, size=13, color=NAVY)
    for row in range(5, 13):
        _label(ws.cell(row, 1))
        _value(ws.cell(row, 2))
    _paint_light(ws.cell(10, 2), view["light"])
    for row in range(15, 22):
        _label(ws.cell(row, 1))
        cell = ws.cell(row, 2)
        _value(cell)
        cell.alignment = CENTER
    for row in (24, 25, 26, 27, 29, 30, 31):
        ws.cell(row, 1).font = Font(name="Calibri", size=11, color=INK)
        ws.cell(row, 1).alignment = WRAP
    ws.row_dimensions[12].height = 36
    for col, width in {"A": 28, "B": 22, "C": 18, "D": 28}.items():
        ws.column_dimensions[col].width = width
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    site_name = view["site"].name if view.get("site") else ""
    ws.oddFooter.right.text = f"{client.name}  {site_name}  {check.year_month}"
    ws.print_title_rows = "1:2"
    ws.sheet_view.showGridLines = False


def _devices(ws, view):
    headers = [
        "Type", "Name", "Model", "Serial", "IP address", "Firmware",
        "Warranty / support", "Last check", "Checks", "Screenshot",
    ]
    _sheet_banner(ws, view, "Devices")
    _header_row(ws, 4, headers)
    for index, row in enumerate(view["devices"], start=5):
        device, month = row["device"], row["month"]
        values = [
            device.device_type, device.name, device.model, device.serial_no,
            device.ip_address, device.firmware, device.warranty_expiry,
            month.last_check_date, _check_summary(row), _names(_check_files(row)),
        ]
        _write_row(ws, index, values)
    _finish_table(ws, 4, len(headers), 5 + len(view["devices"]))
    _list_validation(ws, "A5:A200", '"Server,Router,Switch,Firewall,AP,NVR,Other"')
    widths = [12, 18, 16, 16, 16, 14, 18, 16, 42, 28]
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width


def _checklist(ws, view):
    headers = ["#", "Stage", "Item", "This month", "Notes", "Last month", "Compared with last month", "Screenshot"]
    _sheet_banner(ws, view, "Checklist (keep this order)")
    _header_row(ws, 4, headers)
    for index, row in enumerate(view["items"], start=5):
        item = row["item"]
        values = [
            item.seq, item.stage, item.name, item.result, item.notes,
            item.prev_result, row["compare"], _names(row["attachments"]),
        ]
        _write_row(ws, index, values)
        _paint_status(ws.cell(index, 4), item.result)
        _paint_compare(ws.cell(index, 7), row["compare"])
    _finish_table(ws, 4, len(headers), 5 + len(view["items"]))
    _list_validation(ws, "D5:D80", '"Normal,Abnormal,N/A"')
    _list_validation(ws, "F5:F80", '"Normal,Abnormal,N/A"')
    for i, width in enumerate([8, 28, 32, 12, 36, 12, 16, 28], start=1):
        ws.column_dimensions[get_column_letter(i)].width = width


def _issues(ws, view):
    headers = [
        "Issue", "First found", "Source", "Related item", "Summary",
        "Status this month", "Update this month", "Action", "Closed on", "Screenshot",
    ]
    _sheet_banner(ws, view, "Issues (keep the same ID while it is open)")
    _header_row(ws, 4, headers)
    excel_row = 5
    for row in view["issues"]:
        issue, month = row["issue"], row["month"]
        if month is None:
            continue
        values = [
            issue.code, issue.first_found_date, issue.source, issue.related_label,
            issue.summary, month.status, month.observation, month.action,
            issue.close_date, _names(row["attachments"]),
        ]
        _write_row(ws, excel_row, values)
        _paint_issue(ws.cell(excel_row, 6), month.status)
        excel_row += 1
    _finish_table(ws, 4, len(headers), excel_row)
    _list_validation(ws, "C5:C80", '"Inventory,Checklist,Expiry,Other"')
    _list_validation(ws, "F5:F80", '"Open,In progress,Closed"')
    for i, width in enumerate([12, 16, 14, 24, 32, 12, 28, 24, 14, 28], start=1):
        ws.column_dimensions[get_column_letter(i)].width = width


def _expiries(ws, view):
    headers = ["Type", "Name", "Related device", "Expiry date", "Days left", "Status", "Notes"]
    check = view["check"]
    _sheet_banner(
        ws,
        view,
        f"Expiries (days left are from the check date {check.check_date.isoformat()}, not the export date)",
    )
    _header_row(ws, 4, headers)
    for index, row in enumerate(view["expiries"], start=5):
        expiry = row["expiry"]
        values = [
            expiry.kind, expiry.name, row["related"], expiry.expiry_date,
            row["days"] if row["days"] is not None else None,
            row["status"], expiry.notes,
        ]
        _write_row(ws, index, values)
        _paint_expiry(ws.cell(index, 6), row["status"])
    _finish_table(ws, 4, len(headers), 5 + len(view["expiries"]))
    _list_validation(ws, "A5:A80", '"Licence,Warranty,SSL certificate,Support contract,Other"')
    for i, width in enumerate([14, 28, 18, 16, 12, 16, 42], start=1):
        ws.column_dimensions[get_column_letter(i)].width = width


def _sheet_banner(ws, view, title: str):
    client, check = view["client"], view["check"]
    ws["A1"] = title
    ws.merge_cells("A1:F1")
    _paint_title(ws["A1"])
    site_name = view["site"].name if view.get("site") else ""
    ws["A2"] = f"Customer  {client.name}    Site  {site_name}"
    ws.merge_cells("A2:F2")
    ws["A3"] = f"Check date  {check.check_date.isoformat()}    Engineer  {check.engineer}    Overall  {view['light']}"
    ws.merge_cells("A3:F3")
    for cell in (ws["A2"], ws["A3"]):
        cell.font = Font(name="Calibri", size=11, color=INK)
    ws.row_dimensions[1].height = 24
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.horizontalCentered = True
    ws.page_margins.left = 0.4
    ws.page_margins.right = 0.4
    ws.page_margins.top = 0.6
    ws.page_margins.bottom = 0.6
    ws.oddFooter.left.text = "Internal tool. Point-in-time check, not live monitoring."
    ws.oddFooter.right.text = f"{client.name} {view['site'].name if view.get('site') else ''} {check.year_month}"
    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 110
    ws.freeze_panes = "A5"
    ws.print_title_rows = "1:4"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.sheet_properties.tabColor = NAVY


def _header_row(ws, row: int, headers: list[str]):
    for col, text in enumerate(headers, start=1):
        cell = ws.cell(row, col, text)
        cell.font = Font(name="Calibri", bold=True, color=WHITE, size=11)
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        cell.border = THIN
    ws.row_dimensions[row].height = 30
    ws.auto_filter.ref = f"A{row}:{get_column_letter(len(headers))}{row}"


def _write_row(ws, row: int, values: list):
    for col, value in enumerate(values, start=1):
        cell = ws.cell(row, col, None if value is None else value)
        cell.font = Font(name="Calibri", size=11, color=INK)
        cell.alignment = WRAP
        cell.border = THIN
        if hasattr(value, "isoformat") and not hasattr(value, "hour"):
            cell.number_format = "YYYY-MM-DD"
    ws.row_dimensions[row].height = 32


def _finish_table(ws, header_row: int, columns: int, next_row: int):
    if next_row > header_row + 1:
        ws.auto_filter.ref = f"A{header_row}:{get_column_letter(columns)}{next_row - 1}"
    ws.auto_filter.ref = f"A{header_row}:{get_column_letter(columns)}{max(next_row - 1, header_row)}"


def _list_validation(ws, sqref: str, formula: str):
    rule = DataValidation(type="list", formula1=formula, allow_blank=True)
    rule.error = "Pick from the list"
    rule.errorTitle = "Choice"
    rule.sqref = sqref
    ws.add_data_validation(rule)


def _paint_title(cell):
    cell.font = Font(name="Calibri", bold=True, size=16, color=NAVY)
    cell.alignment = Alignment(vertical="center")


def _label(cell):
    cell.font = Font(name="Calibri", size=11, color=SLATE)
    cell.alignment = Alignment(vertical="center")


def _value(cell):
    cell.font = Font(name="Calibri", size=12, color=INK)
    cell.alignment = WRAP


def _fill_font(cell, bg: str, color: str):
    cell.fill = PatternFill("solid", fgColor=bg)
    cell.font = Font(name="Calibri", bold=True, size=12, color=color)
    cell.alignment = CENTER
    cell.border = THIN


def _paint_light(cell, light: str):
    colors = {
        "Red": (RED_BG, RED),
        "Amber": (AMBER_BG, AMBER),
        "Green": (GREEN_BG, GREEN),
        "Not started": (SLATE_BG, SLATE),
    }
    bg, fg = colors.get(light, (SLATE_BG, SLATE))
    _fill_font(cell, bg, fg)


def _paint_status(cell, value: str | None):
    if value == "Abnormal":
        _fill_font(cell, RED_BG, RED)
    elif value == "Normal":
        _fill_font(cell, GREEN_BG, GREEN)
    elif value == "N/A":
        _fill_font(cell, SLATE_BG, SLATE)


def _paint_issue(cell, value: str | None):
    if value == "Open":
        _fill_font(cell, RED_BG, RED)
    elif value == "In progress":
        _fill_font(cell, AMBER_BG, AMBER)
    elif value == "Closed":
        _fill_font(cell, SLATE_BG, SLATE)


def _paint_expiry(cell, value: str | None):
    if value == "Expired":
        _fill_font(cell, RED_BG, RED)
    elif value == "Due in 30 days":
        _fill_font(cell, AMBER_BG, AMBER)
    elif value == "Due in 90 days":
        _fill_font(cell, "FFF8E8", "8A6116")
    elif value == "Normal":
        _fill_font(cell, GREEN_BG, GREEN)


def _paint_compare(cell, value: str | None):
    if value == "New this month":
        _fill_font(cell, RED_BG, RED)
    elif value == "Recovered":
        _fill_font(cell, GREEN_BG, GREEN)
    elif value == "Now in use":
        _fill_font(cell, "E8F1FB", NAVY)
    elif value == "Different":
        _fill_font(cell, AMBER_BG, AMBER)
    elif value == "Same as last month":
        _fill_font(cell, SLATE_BG, SLATE)


def _check_summary(row: dict) -> str:
    lines = []
    for line in row.get("checks") or []:
        definition = line["definition"]
        result = line["result"]
        command = f" ({definition.command})" if definition.command else ""
        status = result.result or "—"
        issue = f" — {result.issue}" if result.issue else ""
        lines.append(f"{definition.name}{command}: {status}{issue}")
    return "\n".join(lines)


def _check_files(row: dict) -> list:
    files = list(row.get("attachments") or [])
    for line in row.get("checks") or []:
        files.extend(line.get("attachments") or [])
    return files


def _names(attachments) -> str:
    return "\n".join(item.original_name for item in attachments)


def _status_class(value: str | None) -> str:
    return {
        "Abnormal": "bad",
        "Open": "bad",
        "Expired": "bad",
        "Normal": "ok",
        "Closed": "ok",
        "In progress": "warn",
        "Due in 30 days": "warn",
        "Due in 90 days": "soon",
        "N/A": "na",
        "New this month": "bad",
        "Recovered": "ok",
    }.get(value or "", "")


def _pdf_images(view, upload_dir: Path, limit: int = 8):
    found = []

    def take(rows, caption):
        for att in rows:
            found.append((att, caption))

    for row in view["devices"]:
        take(row["attachments"], f"Device {row['device'].name}")
    for row in view["items"]:
        take(row["attachments"], f"Item {row['item'].seq} {row['item'].name}")
    for row in view["issues"]:
        take(row["attachments"], row["issue"].code)
    images = []
    skipped_names = []
    for att, caption in found[:limit]:
        path = upload_dir / att.stored_name
        if not path.is_file():
            skipped_names.append(att.original_name)
            continue
        try:
            data, mime = thumbnail_bytes(path, max_px=360)
        except OSError:
            skipped_names.append(att.original_name)
            continue
        images.append(
            {
                "src": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}",
                "name": att.original_name,
                "caption": caption,
            }
        )
    skipped_names.extend(att.original_name for att, _caption in found[limit:])
    return images, skipped_names


def _font_face_css() -> str:
    # TTC collections are registered with fontconfig (Noto Sans CJK TC). @font-face
    # only gets a single-file OTF/TTF when one is installed.
    roots = [Path("/usr/share/fonts")]
    regular = _find_font(roots, ("NotoSansCJKtc-Regular.otf", "NotoSansTC-Regular.otf"))
    bold = _find_font(roots, ("NotoSansCJKtc-Bold.otf", "NotoSansTC-Bold.otf"))
    if regular is None:
        return (
            "<style>body{font-family:'Noto Sans CJK HK','Noto Sans CJK TC',"
            "'Noto Sans TC',sans-serif}</style>"
        )
    bold_src = bold or regular
    return f"""<style>
    @font-face {{
      font-family: HealthCJK;
      src: url("file://{regular}");
      font-weight: 400;
    }}
    @font-face {{
      font-family: HealthCJK;
      src: url("file://{bold_src}");
      font-weight: 700;
    }}
    body {{ font-family: HealthCJK, "Noto Sans CJK TC", sans-serif; }}
    </style>"""


def _find_font(roots, names: tuple[str, ...]) -> str | None:
    for root in roots:
        if not root.exists():
            continue
        for name in names:
            matches = list(root.rglob(name))
            if matches:
                return matches[0].as_posix()
    return None


def _pdf_html(view: dict, images: list[dict], skipped: list[str]) -> str:
    client, check, counts = view["client"], view["check"], view["counts"]
    light = view["light"]

    def esc(value) -> str:
        if value is None:
            return ""
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    def date_text(value) -> str:
        return value.isoformat() if value else "—"

    device_rows = []
    for row in view["devices"]:
        device, month = row["device"], row["month"]
        device_rows.append(
            "<tr>"
            f"<td class='nowrap'>{esc(device.device_type)}</td>"
            f"<td>{esc(device.name)}<br><span class='sub'>{esc(device.model or '—')} · {esc(device.firmware or '—')} · {esc(device.serial_no or '—')}</span></td>"
            f"<td class='nowrap'>{esc(device.ip_address or '—')}</td>"
            f"<td class='nowrap'>{date_text(device.warranty_expiry)}</td>"
            f"<td class='nowrap'>{date_text(month.last_check_date)}</td>"
            f"<td>{esc(_check_summary(row)).replace(chr(10), '<br>')}</td>"
            f"<td>{esc(_names(_check_files(row)))}</td>"
            "</tr>"
        )
    item_rows = []
    last_stage = None
    for row in view["items"]:
        item = row["item"]
        if item.stage != last_stage:
            last_stage = item.stage
            heading = STAGE_HEADINGS.get(item.stage, item.stage)
            item_rows.append(f"<tr class='stage'><td colspan='7'>{esc(heading)}</td></tr>")
        item_rows.append(
            "<tr>"
            f"<td class='num'>{item.seq}</td>"
            f"<td>{esc(item.name)}</td>"
            f"<td class='st nowrap {_status_class(item.result)}'>{esc(item.result or '—')}</td>"
            f"<td>{esc(item.notes or '')}</td>"
            f"<td class='nowrap'>{esc(item.prev_result or '—')}</td>"
            f"<td class='nowrap'>{esc(row['compare'] or '—')}</td>"
            f"<td>{esc(_names(row['attachments']))}</td>"
            "</tr>"
        )
    issue_rows = []
    for row in view["issues"]:
        issue, month = row["issue"], row["month"]
        status = month.status if month else "Not on this month"
        observation = month.observation if month else ""
        action = month.action if month else issue.action
        issue_rows.append(
            "<tr>"
            f"<td class='nowrap'>{esc(issue.code)}</td>"
            f"<td class='nowrap'>{date_text(issue.first_found_date)}</td>"
            f"<td class='nowrap'>{esc(issue.source)}</td>"
            f"<td>{esc(issue.related_label or '')}</td>"
            f"<td>{esc(issue.summary)}</td>"
            f"<td class='st nowrap {_status_class(status)}'>{esc(status)}</td>"
            f"<td>{esc(observation or '')}</td>"
            f"<td>{esc(action or '')}</td>"
            f"<td>{date_text(issue.close_date)}</td>"
            f"<td>{esc(_names(row['attachments']))}</td>"
            "</tr>"
        )
    expiry_rows = []
    for row in view["expiries"]:
        expiry = row["expiry"]
        days = "—" if row["days"] is None else str(row["days"])
        expiry_rows.append(
            "<tr>"
            f"<td>{esc(expiry.kind)}</td>"
            f"<td>{esc(expiry.name)}</td>"
            f"<td>{esc(row['related'])}</td>"
            f"<td>{date_text(expiry.expiry_date)}</td>"
            f"<td class='num'>{days}</td>"
            f"<td class='st {_status_class(row['status'])}'>{esc(row['status'] or '—')}</td>"
            f"<td>{esc(expiry.notes or '')}</td>"
            "</tr>"
        )
    figures = []
    for image in images:
        figures.append(
            "<figure>"
            f"<img src='{image['src']}' alt='{esc(image['name'])}'>"
            f"<figcaption>{esc(image['caption'])}<br>{esc(image['name'])}</figcaption>"
            "</figure>"
        )
    skipped_html = ""
    if skipped:
        skipped_html = "<p class='note'>Other screenshot files: " + esc(", ".join(skipped)) + "</p>"
    duration = "—" if check.duration_hours is None else f"{check.duration_hours:g}"
    return f"""
    <article>
      <header>
        <p class="kicker">Monthly remote health check</p>
        <h1>Monthly remote health check</h1>
        <p class="meta">{esc(client.name)}　{esc(view['site'].name if view.get('site') else '')}　{check.year_month}</p>
        <p class="note">This report is this site only. Other sites of the customer are separate reports.</p>
      </header>
      <section class="hero light-{esc(light).split()[0]}">
        <div>
          <span>Overall</span>
          <strong>{esc(light)}</strong>
        </div>
        <ul>
          <li>Check date  {check.check_date.isoformat()}</li>
          <li>Engineer  {esc(check.engineer)}</li>
          <li>Duration  {duration} h</li>
        </ul>
      </section>
      <p class="note">{esc(check.notes or "")}</p>
      <p class="note">This check records that moment only. It is not 24-hour monitoring.</p>
      <h2>This month</h2>
      <table class="stats">
        <tr>
          <th>Abnormal checks</th><th>Filled</th><th>Abnormal devices</th>
        </tr>
        <tr>
          <td>{counts["abnormal_items"]}</td><td>{counts["filled_items"]}</td>
          <td>{counts["abnormal_devices"]}</td>
        </tr>
      </table>
      <h2>Devices</h2>
      <table>
        <tr>
          <th>Type</th><th>Name (model, firmware, serial)</th><th>IP</th><th>Warranty / support</th>
          <th>Last check</th><th>Checks</th><th>Screenshot</th>
        </tr>
        {''.join(device_rows) or "<tr><td colspan='7'>No devices</td></tr>"}
      </table>
      <h2>Issues</h2>
      <table>
        <tr>
          <th>ID</th><th>First found</th><th>Source</th><th>Related</th><th>Summary</th>
          <th>Status</th><th>Update</th><th>Action</th><th>Closed on</th><th>Screenshot</th>
        </tr>
        {''.join(issue_rows) or "<tr><td colspan='10'>No issues</td></tr>"}
      </table>
      <h2>Screenshots</h2>
      <div class="shots">{''.join(figures) or "<p class='note'>No screenshots this month.</p>"}</div>
      {skipped_html}
      <footer>Internal tool with no login. A point-in-time check, not live monitoring.</footer>
    </article>
    <style>
      @page {{
        size: A4;
        margin: 12mm 10mm 14mm;
        @bottom-center {{
          content: counter(page) " / " counter(pages);
          font-size: 9pt;
          color: #5c6b7a;
        }}
      }}
      body {{ color: #1c2430; font-size: 8.5pt; line-height: 1.4; }}
      h1 {{ font-size: 18pt; margin: 0; color: #0f4c81; }}
      h2 {{ font-size: 12pt; margin: 14px 0 6px; color: #0f4c81; page-break-after: avoid; }}
      .kicker {{ margin: 0; color: #5c6b7a; font-size: 9pt; }}
      .meta {{ margin: 2px 0 8px; }}
      .hero {{ display: flex; justify-content: space-between; border: 1px solid #d5dee8; border-left-width: 6px; padding: 8px 12px; }}
      .hero span {{ display: block; color: #5c6b7a; font-size: 8.5pt; }}
      .hero strong {{ font-size: 16pt; }}
      .hero ul {{ margin: 0; padding: 0; list-style: none; }}
      .light-Red {{ border-left-color: #b42318; }}
      .light-Red strong {{ color: #b42318; }}
      .light-Amber {{ border-left-color: #b54708; }}
      .light-Amber strong {{ color: #b54708; }}
      .light-Green {{ border-left-color: #067647; }}
      .light-Green strong {{ color: #067647; }}
      .light-Not {{ border-left-color: #475467; }}
      .note {{ color: #3d4b5c; margin: 6px 0; }}
      table {{ width: 100%; border-collapse: collapse; margin-bottom: 8px; page-break-inside: auto; }}
      th, td {{ border: 1px solid #d5dee8; padding: 2px 3px; vertical-align: top; }}
      .nowrap {{ white-space: nowrap; }}
      .sub {{ color: #5c6b7a; font-size: 7.5pt; }}
      th {{ background: #0f4c81; color: white; font-weight: 700; }}
      tr {{ page-break-inside: avoid; }}
      .stage td {{ background: #eef3f8; font-weight: 700; color: #0f4c81; }}
      .num {{ text-align: center; }}
      .st.bad {{ background: #fdecea; color: #b42318; font-weight: 700; }}
      .st.ok {{ background: #e7f6ee; color: #067647; font-weight: 700; }}
      .st.warn {{ background: #fff6e8; color: #b54708; font-weight: 700; }}
      .st.soon {{ background: #fff8e8; color: #8a6116; font-weight: 700; }}
      .st.na {{ background: #f2f4f7; color: #475467; }}
      .shots {{ display: flex; flex-wrap: wrap; gap: 8px; }}
      figure {{ width: 46%; margin: 0; page-break-inside: avoid; }}
      img {{ width: 100%; height: auto; border: 1px solid #d5dee8; }}
      figcaption {{ font-size: 8pt; color: #3d4b5c; }}
      footer {{ margin-top: 12px; color: #5c6b7a; font-size: 8.5pt; }}
      .stats td {{ text-align: center; font-weight: 700; font-size: 12pt; }}
    </style>
    """
