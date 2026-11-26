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
    _devices(wb.create_sheet("設備清單"), view)
    _checklist(wb.create_sheet("月度檢查表"), view)
    _issues(wb.create_sheet("異常與跟進"), view)
    _expiries(wb.create_sheet("到期預警"), view)
    wb.properties.title = f"{client.name} {client.site} {check.year_month} 健康檢查"
    wb.properties.creator = "月度遠端健康檢查"
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
    ws.title = "封面說明"
    client, check, counts = view["client"], view["check"], view["counts"]
    ws.sheet_properties.tabColor = NAVY
    ws["A1"] = "月度遠端健康檢查"
    ws.merge_cells("A1:D1")
    ws["A2"] = "每月遠端健康檢查（VPN / AnyDesk）"
    ws.merge_cells("A2:D2")
    ws["A4"] = "本次檢查資料"
    rows = [
        (5, "客戶名稱", client.name),
        (6, "站點", client.site),
        (7, "檢查日期", check.check_date),
        (8, "工程師", check.engineer),
        (9, "連線方式", check.connection_method),
        (10, "檢查時長（小時）", check.duration_hours),
        (11, "整體燈號", view["light"]),
        (12, "整體備註", check.notes or ""),
    ]
    for row, label, value in rows:
        ws.cell(row, 1, label)
        ws.cell(row, 2, value)
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
    ws["A14"] = "本月摘要（由系統按 Excel 範本同一規則計算）"
    ws.merge_cells("A14:D14")
    summary = [
        (15, "月度檢查表異常項數", counts["abnormal_items"]),
        (16, "月度檢查表已填項數", counts["filled_items"]),
        (17, "設備清單異常數", counts["abnormal_devices"]),
        (18, "未關閉跟進數", counts["open_followups"]),
        (19, "已過期數", counts["expired"]),
        (20, "30天內到期數", counts["within_30"]),
        (21, "90天內到期數", counts["within_90"]),
    ]
    for row, label, value in summary:
        ws.cell(row, 1, label)
        ws.cell(row, 2, value)
    ws["A23"] = "燈號規則"
    legend = [
        (24, "紅：本月檢查或設備有「異常」，或有已過期項目。"),
        (25, "黃：無上述紅燈，但有未關閉跟進，或 30／90 天內到期。"),
        (26, "綠：已填寫檢查結果，且無上述紅／黃情況。"),
        (27, "未完成：檢查表尚未填寫，且無異常、未關閉跟進或到期預警項目。"),
        (29, "此檢查只反映檢查當下的狀態，是時點快照；不能取代 24 小時監控。"),
        (30, "剩餘日數依本次檢查日期計算，不是匯出當天。"),
        (31, "重複問題沿用原問題編號。截圖檔名列於各表最後一欄，圖片存在系統，不嵌入此活頁簿。"),
    ]
    for row, text in legend:
        ws.cell(row, 1, text)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
    _paint_title(ws["A1"])
    ws["A2"].font = Font(name="Microsoft JhengHei", size=12, color=SLATE)
    ws["A4"].font = Font(name="Microsoft JhengHei", bold=True, size=13, color=NAVY)
    ws["A14"].font = Font(name="Microsoft JhengHei", bold=True, size=13, color=NAVY)
    ws["A23"].font = Font(name="Microsoft JhengHei", bold=True, size=13, color=NAVY)
    for row in range(5, 13):
        _label(ws.cell(row, 1))
        _value(ws.cell(row, 2))
    _paint_light(ws.cell(11, 2), view["light"])
    for row in range(15, 22):
        _label(ws.cell(row, 1))
        cell = ws.cell(row, 2)
        _value(cell)
        cell.alignment = CENTER
    for row in (24, 25, 26, 27, 29, 30, 31):
        ws.cell(row, 1).font = Font(name="Microsoft JhengHei", size=11, color=INK)
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
    ws.oddFooter.right.text = f"{client.name}  {check.year_month}"
    ws.print_title_rows = "1:2"
    ws.sheet_view.showGridLines = False


def _devices(ws, view):
    headers = [
        "設備類型", "名稱/主機名稱", "型號", "序號", "IP 位址", "韌體版本",
        "保固/支援到期日", "上次檢查日期", "本月狀態", "異常摘要", "跟進事項",
        "首次發現日期", "截圖",
    ]
    _sheet_banner(ws, view, "設備清單")
    _header_row(ws, 4, headers)
    for index, row in enumerate(view["devices"], start=5):
        device, month = row["device"], row["month"]
        values = [
            device.device_type, device.name, device.model, device.serial_no,
            device.ip_address, device.firmware, device.warranty_expiry,
            month.last_check_date, month.status, month.exception_summary,
            month.follow_up, month.first_found_date, _names(row["attachments"]),
        ]
        _write_row(ws, index, values)
        _paint_status(ws.cell(index, 9), month.status)
    _finish_table(ws, 4, len(headers), 5 + len(view["devices"]))
    _list_validation(ws, "A5:A200", '"伺服器,交換器,防火牆,AP,NVR,其他"')
    _list_validation(ws, "I5:I200", '"正常,異常"')
    widths = [12, 18, 16, 16, 16, 14, 18, 16, 12, 28, 22, 16, 28]
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width


def _checklist(ws, view):
    headers = ["項次", "階段", "檢查項目", "本月結果", "說明/備註", "上月結果", "與上月比較", "截圖路徑或備註"]
    _sheet_banner(ws, view, "月度檢查表（請依項次順序檢查）")
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
    _list_validation(ws, "D5:D80", '"正常,異常,不適用"')
    _list_validation(ws, "F5:F80", '"正常,異常,不適用"')
    for i, width in enumerate([8, 28, 32, 12, 36, 12, 16, 28], start=1):
        ws.column_dimensions[get_column_letter(i)].width = width


def _issues(ws, view):
    headers = [
        "問題編號", "首次發現日期", "來源", "相關設備或檢查項目", "問題摘要",
        "本月狀態", "本月觀察/更新", "跟進行動", "關閉日期", "截圖路徑或備註",
    ]
    _sheet_banner(ws, view, "異常與跟進（未關閉問題請沿用原編號）")
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
    _list_validation(ws, "C5:C80", '"設備清單,月度檢查表,到期預警,其他"')
    _list_validation(ws, "F5:F80", '"開放,跟進中,已關閉"')
    for i, width in enumerate([12, 16, 14, 24, 32, 12, 28, 24, 14, 28], start=1):
        ws.column_dimensions[get_column_letter(i)].width = width


def _expiries(ws, view):
    headers = ["類型", "項目名稱", "相關設備", "到期日", "剩餘日數", "預警狀態", "備註"]
    check = view["check"]
    _sheet_banner(
        ws,
        view,
        f"到期預警（剩餘日數相對檢查日期 {check.check_date.isoformat()}，不是匯出當天）",
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
    _list_validation(ws, "A5:A80", '"授權,保固,SSL憑證,支援合約,其他"')
    for i, width in enumerate([14, 28, 18, 16, 12, 16, 42], start=1):
        ws.column_dimensions[get_column_letter(i)].width = width


def _sheet_banner(ws, view, title: str):
    client, check = view["client"], view["check"]
    ws["A1"] = title
    ws.merge_cells("A1:F1")
    _paint_title(ws["A1"])
    ws["A2"] = f"客戶名稱  {client.name}　　站點  {client.site}"
    ws.merge_cells("A2:F2")
    ws["A3"] = f"檢查日期  {check.check_date.isoformat()}　　工程師  {check.engineer}　　整體燈號  {view['light']}"
    ws.merge_cells("A3:F3")
    for cell in (ws["A2"], ws["A3"]):
        cell.font = Font(name="Microsoft JhengHei", size=11, color=INK)
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
    ws.oddFooter.left.text = "內部工具　時點快照　非即時監控"
    ws.oddFooter.right.text = f"{client.name} {client.site} {check.year_month}"
    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 110
    ws.freeze_panes = "A5"
    ws.print_title_rows = "1:4"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.sheet_properties.tabColor = NAVY


def _header_row(ws, row: int, headers: list[str]):
    for col, text in enumerate(headers, start=1):
        cell = ws.cell(row, col, text)
        cell.font = Font(name="Microsoft JhengHei", bold=True, color=WHITE, size=11)
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        cell.border = THIN
    ws.row_dimensions[row].height = 30
    ws.auto_filter.ref = f"A{row}:{get_column_letter(len(headers))}{row}"


def _write_row(ws, row: int, values: list):
    for col, value in enumerate(values, start=1):
        cell = ws.cell(row, col, None if value is None else value)
        cell.font = Font(name="Microsoft JhengHei", size=11, color=INK)
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
    rule.error = "請從清單選擇"
    rule.errorTitle = "選項"
    rule.sqref = sqref
    ws.add_data_validation(rule)


def _paint_title(cell):
    cell.font = Font(name="Microsoft JhengHei", bold=True, size=16, color=NAVY)
    cell.alignment = Alignment(vertical="center")


def _label(cell):
    cell.font = Font(name="Microsoft JhengHei", size=11, color=SLATE)
    cell.alignment = Alignment(vertical="center")


def _value(cell):
    cell.font = Font(name="Microsoft JhengHei", size=12, color=INK)
    cell.alignment = WRAP


def _fill_font(cell, bg: str, color: str):
    cell.fill = PatternFill("solid", fgColor=bg)
    cell.font = Font(name="Microsoft JhengHei", bold=True, size=12, color=color)
    cell.alignment = CENTER
    cell.border = THIN


def _paint_light(cell, light: str):
    colors = {
        "紅": (RED_BG, RED),
        "黃": (AMBER_BG, AMBER),
        "綠": (GREEN_BG, GREEN),
        "未完成": (SLATE_BG, SLATE),
    }
    bg, fg = colors.get(light, (SLATE_BG, SLATE))
    _fill_font(cell, bg, fg)


def _paint_status(cell, value: str | None):
    if value == "異常":
        _fill_font(cell, RED_BG, RED)
    elif value == "正常":
        _fill_font(cell, GREEN_BG, GREEN)
    elif value == "不適用":
        _fill_font(cell, SLATE_BG, SLATE)


def _paint_issue(cell, value: str | None):
    if value == "開放":
        _fill_font(cell, RED_BG, RED)
    elif value == "跟進中":
        _fill_font(cell, AMBER_BG, AMBER)
    elif value == "已關閉":
        _fill_font(cell, SLATE_BG, SLATE)


def _paint_expiry(cell, value: str | None):
    if value == "已過期":
        _fill_font(cell, RED_BG, RED)
    elif value == "30天內到期":
        _fill_font(cell, AMBER_BG, AMBER)
    elif value == "90天內到期":
        _fill_font(cell, "FFF8E8", "8A6116")
    elif value == "正常":
        _fill_font(cell, GREEN_BG, GREEN)


def _paint_compare(cell, value: str | None):
    if value == "本月新異常":
        _fill_font(cell, RED_BG, RED)
    elif value == "本月已恢復":
        _fill_font(cell, GREEN_BG, GREEN)
    elif value == "本月開始適用":
        _fill_font(cell, "E8F1FB", NAVY)
    elif value == "與上月不同":
        _fill_font(cell, AMBER_BG, AMBER)
    elif value == "與上月相同":
        _fill_font(cell, SLATE_BG, SLATE)


def _names(attachments) -> str:
    return "\n".join(item.original_name for item in attachments)


def _status_class(value: str | None) -> str:
    return {
        "異常": "bad",
        "開放": "bad",
        "已過期": "bad",
        "正常": "ok",
        "已關閉": "ok",
        "跟進中": "warn",
        "30天內到期": "warn",
        "90天內到期": "soon",
        "不適用": "na",
        "本月新異常": "bad",
        "本月已恢復": "ok",
    }.get(value or "", "")


def _pdf_images(view, upload_dir: Path, limit: int = 8):
    found = []

    def take(rows, caption):
        for att in rows:
            found.append((att, caption))

    for row in view["devices"]:
        take(row["attachments"], f"設備 {row['device'].name}")
    for row in view["items"]:
        take(row["attachments"], f"檢查項 {row['item'].seq} {row['item'].name}")
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
            f"<td class='st nowrap {_status_class(month.status)}'>{esc(month.status or '—')}</td>"
            f"<td>{esc(month.exception_summary or '')}</td>"
            f"<td>{esc(month.follow_up or '')}</td>"
            f"<td class='nowrap'>{date_text(month.first_found_date)}</td>"
            f"<td>{esc(_names(row['attachments']))}</td>"
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
        status = month.status if month else "未列入本月"
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
        skipped_html = "<p class='note'>其餘截圖檔名：" + esc("、".join(skipped)) + "</p>"
    duration = "—" if check.duration_hours is None else f"{check.duration_hours:g}"
    return f"""
    <article>
      <header>
        <p class="kicker">每月遠端健康檢查（VPN / AnyDesk）</p>
        <h1>月度遠端健康檢查</h1>
        <p class="meta">{esc(client.name)}　{esc(client.site)}　{check.year_month}</p>
      </header>
      <section class="hero light-{esc(light)}">
        <div>
          <span>整體燈號</span>
          <strong>{esc(light)}</strong>
        </div>
        <ul>
          <li>檢查日期　{check.check_date.isoformat()}</li>
          <li>工程師　{esc(check.engineer)}</li>
          <li>連線方式　{esc(check.connection_method)}</li>
          <li>檢查時長　{duration} 小時</li>
        </ul>
      </section>
      <p class="note">{esc(check.notes or "")}</p>
      <p class="note">此檢查只反映檢查當下的狀態，是時點快照，不能取代 24 小時監控。剩餘日數相對檢查日期 {check.check_date.isoformat()}，不是匯出當天。</p>
      <h2>本月摘要</h2>
      <table class="stats">
        <tr>
          <th>檢查表異常</th><th>已填項數</th><th>設備異常</th><th>未關閉跟進</th>
          <th>已過期</th><th>30天內</th><th>90天內</th>
        </tr>
        <tr>
          <td>{counts["abnormal_items"]}</td><td>{counts["filled_items"]}</td>
          <td>{counts["abnormal_devices"]}</td><td>{counts["open_followups"]}</td>
          <td>{counts["expired"]}</td><td>{counts["within_30"]}</td><td>{counts["within_90"]}</td>
        </tr>
      </table>
      <h2>設備清單</h2>
      <table>
        <tr>
          <th>類型</th><th>名稱（型號 · 韌體 · 序號）</th><th>IP</th><th>保固/支援到期</th>
          <th>上次檢查</th><th>本月狀態</th><th>異常摘要</th><th>跟進</th><th>首次發現</th><th>截圖</th>
        </tr>
        {''.join(device_rows) or "<tr><td colspan='10'>沒有設備</td></tr>"}
      </table>
      <h2>月度檢查表</h2>
      <table>
        <tr>
          <th>項次</th><th>檢查項目</th><th>本月結果</th><th>說明</th>
          <th>上月結果</th><th>與上月比較</th><th>截圖</th>
        </tr>
        {''.join(item_rows)}
      </table>
      <h2>異常與跟進</h2>
      <table>
        <tr>
          <th>編號</th><th>首次發現</th><th>來源</th><th>相關</th><th>摘要</th>
          <th>本月狀態</th><th>本月觀察</th><th>跟進行動</th><th>關閉日期</th><th>截圖</th>
        </tr>
        {''.join(issue_rows) or "<tr><td colspan='10'>沒有問題</td></tr>"}
      </table>
      <h2>到期預警</h2>
      <p class="note">剩餘日數相對檢查日期 {check.check_date.isoformat()}。</p>
      <table>
        <tr>
          <th>類型</th><th>項目名稱</th><th>相關設備</th><th>到期日</th><th>剩餘日數</th><th>預警狀態</th><th>備註</th>
        </tr>
        {''.join(expiry_rows) or "<tr><td colspan='7'>沒有到期項目</td></tr>"}
      </table>
      <h2>截圖</h2>
      <div class="shots">{''.join(figures) or "<p class='note'>本月沒有截圖。</p>"}</div>
      {skipped_html}
      <footer>內部工具，目前不設登入。只反映檢查當下，不是即時監控。</footer>
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
      .light-紅 {{ border-left-color: #b42318; }}
      .light-紅 strong {{ color: #b42318; }}
      .light-黃 {{ border-left-color: #b54708; }}
      .light-黃 strong {{ color: #b54708; }}
      .light-綠 {{ border-left-color: #067647; }}
      .light-綠 strong {{ color: #067647; }}
      .light-未完成 {{ border-left-color: #475467; }}
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
