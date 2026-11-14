"""Rendering of accounting reports to HTML, PDF and Excel.

The *same* :class:`ReportTable` object feeds the screen, the printed page and the
exported file, so a number can never differ between them. Rendering is split into
two layers:

* this module - Qt-free HTML/Excel generation plus a thin Qt PDF writer;
* the screens - which only call :meth:`ReportRenderer.to_pdf`/``to_excel``.

PDF output goes through ``QTextDocument`` so Persian shaping and the bundled
Vazirmatn font are handled by Qt itself (no external PDF library, no broken
Arabic glyph joining).
"""

from __future__ import annotations

import datetime as _dt
import html
import os
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Sequence

from pars_erp import APP_NAME_DEFAULT, __version__
from pars_erp.core.errors import ConfigurationError
from pars_erp.core.jalali import format_datetime_as_jalali, format_gregorian_as_jalali
from pars_erp.core.money import format_amount

KIND_TEXT = "text"
KIND_AMOUNT = "amount"
KIND_NUMBER = "number"
KIND_DATE = "date"


@dataclass(frozen=True)
class ReportColumn:
    key: str
    title_fa: str
    kind: str = KIND_TEXT
    width: float = 1.0
    align: str = "right"


@dataclass(frozen=True)
class ReportTable:
    title: str
    columns: tuple[ReportColumn, ...]
    rows: tuple[tuple, ...]
    company: str = ""
    subtitle: str = ""
    meta: tuple[str, ...] = ()
    totals: tuple | None = None
    notes: tuple[str, ...] = ()
    currency_code: str = "IRR"

    @property
    def is_empty(self) -> bool:
        return not self.rows


#: Kept alive so Qt is not torn down while a headless export is still running.
_headless_app = None


def _ensure_qt_application():
    """Return a running ``QGuiApplication``, creating a headless one if needed.

    ``QTextDocument`` + ``QPdfWriter`` crash without an application object, so a
    command-line export (or a test) must not depend on the GUI having been
    started first.
    """
    global _headless_app
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    if app is not None:
        return app
    if not os.environ.get("QT_QPA_PLATFORM") and not os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    _headless_app = QGuiApplication([])
    return _headless_app


@dataclass(frozen=True)
class ExportOutcome:
    path: Path
    rows: int
    kind: str

    @property
    def message_fa(self) -> str:
        return f"{self.rows} سطر در فایل «{self.path.name}» ذخیره شد."


def _numeric_cell_value(value, column: ReportColumn):
    """Return a Decimal for Excel numeric cells, or ``None`` if not numeric.

    ``float`` is never used: a Rial amount can exceed the 15 significant digits
    a float can hold, and the accounting rules require exact decimals.
    """
    if value in (None, ""):
        return None
    try:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value).replace(",", "").strip())
    except (ArithmeticError, ValueError):
        return None


def _persian(digits: bool, value: str) -> str:
    """Convert ASCII digits (and only digits) to Persian ones."""
    if not digits:
        return value
    from pars_erp.core.digits import to_persian_digits

    return to_persian_digits(value)


def _persian_number(digits: bool, value: str) -> str:
    """Convert digits *and* the thousand/decimal separators of a number."""
    if not digits:
        return value
    from pars_erp.core.money import DECIMAL_SEPARATOR_FA, THOUSANDS_SEPARATOR_FA

    return (_persian(True, value)
            .replace(",", THOUSANDS_SEPARATOR_FA)
            .replace(".", DECIMAL_SEPARATOR_FA))


def cell_text(value, kind: str, *, currency_code: str = "IRR",
              persian_digits: bool = True) -> str:
    """Render one cell for display (screen/HTML/PDF)."""
    if value is None or value == "":
        return "—"
    if kind == KIND_AMOUNT:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
        return format_amount(amount, currency_code, persian_digits=persian_digits,
                             with_symbol=False)
    if kind == KIND_NUMBER:
        text = f"{int(value):,}" if not isinstance(value, Decimal) else f"{value:,}"
        return _persian_number(persian_digits, text)
    if kind == KIND_DATE:
        if isinstance(value, _dt.datetime):
            return format_datetime_as_jalali(value, persian_digits=persian_digits) or "—"
        if isinstance(value, _dt.date):
            return format_gregorian_as_jalali(value, persian_digits=persian_digits) or "—"
    return _persian(persian_digits, str(value))


class ReportRenderer:
    """Builds printable/exportable artefacts from a :class:`ReportTable`."""

    def __init__(self, *, app_name: str = "", persian_digits: bool = True,
                 font_family: str = "Vazirmatn", font_size: int = 11) -> None:
        self.app_name = app_name or APP_NAME_DEFAULT
        self.persian_digits = persian_digits
        self.font_family = font_family
        self.font_size = font_size

    # ------------------------------------------------------------------ html
    def to_html(self, table: ReportTable, *, theme: str = "light",
                pixel_width: int | None = None) -> str:
        dark = (theme or "light").lower() == "dark"
        background = "#0b1220" if dark else "#ffffff"
        foreground = "#e8edf7" if dark else "#101828"
        border = "#26324a" if dark else "#d0d5dd"
        header_bg = "#162034" if dark else "#f2f4f7"
        muted = "#93a1b8" if dark else "#667085"

        if pixel_width and pixel_width > 0:
            total_weight = sum(max(column.width, 0.01) for column in table.columns) or 1.0
            widths = [max(24, int(pixel_width * max(c.width, 0.01) / total_weight))
                      for c in table.columns]
            head_cells = "".join(
                f'<th width="{widths[index]}">{html.escape(column.title_fa)}</th>'
                for index, column in enumerate(table.columns))
            table_open = f'<table width="{pixel_width}" cellspacing="0" cellpadding="4">'
        else:
            head_cells = "".join(
                f'<th style="width:{column.width * 100:.0f}%">{html.escape(column.title_fa)}</th>'
                for column in table.columns)
            table_open = "<table>"
        def render_cell(value, column: ReportColumn) -> str:
            css = "num" if column.kind in (KIND_AMOUNT, KIND_NUMBER) else ""
            text = cell_text(value, column.kind, currency_code=table.currency_code,
                             persian_digits=self.persian_digits)
            return '<td class="' + css + '">' + html.escape(text) + "</td>"

        body_rows = []
        for row in table.rows:
            cells = "".join(
                render_cell(row[index] if index < len(row) else None, column)
                for index, column in enumerate(table.columns))
            body_rows.append("<tr>" + cells + "</tr>")
        total_row = ""
        if table.totals is not None:
            cells = "".join(
                render_cell(table.totals[index] if index < len(table.totals) else "",
                            column)
                for index, column in enumerate(table.columns))
            total_row = '<tr class="total">' + cells + "</tr>"

        meta = " · ".join(html.escape(item) for item in table.meta)
        notes = "".join(f"<p class='note'>{html.escape(item)}</p>" for item in table.notes)
        empty = ("<tr><td class='empty' colspan='%d'>داده‌ای برای نمایش وجود ندارد.</td></tr>"
                 % len(table.columns)) if table.is_empty else ""

        return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<title>{html.escape(table.title)}</title>
<style>
  @page {{ size: A4 landscape; margin: 12mm; }}
  body {{ font-family: '{self.font_family}', Tahoma, sans-serif; font-size: {self.font_size}pt;
         color: {foreground}; background: {background}; direction: rtl; }}
  header {{ border-bottom: 2px solid {border}; padding-bottom: 6px; margin-bottom: 10px; }}
  .brand {{ font-size: {self.font_size + 5}pt; font-weight: 700; }}
  .company {{ font-size: {self.font_size + 1}pt; color: {muted}; }}
  h1 {{ font-size: {self.font_size + 3}pt; margin: 8px 0 2px; }}
  .meta {{ color: {muted}; font-size: {self.font_size - 1}pt; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 6px; }}
  th {{ background: {header_bg}; border: 1px solid {border}; padding: 5px 6px;
        font-size: {self.font_size - 0.5}pt; text-align: center; }}
  td {{ border: 1px solid {border}; padding: 4px 6px; }}
  td.num {{ text-align: right; direction: ltr; font-variant-numeric: tabular-nums; }}
  tr.total td {{ font-weight: 700; background: {header_bg}; }}
  td.empty {{ text-align: center; color: {muted}; padding: 16px; }}
  .note {{ color: {muted}; font-size: {self.font_size - 1}pt; margin: 3px 0; }}
  footer {{ margin-top: 12px; color: {muted}; font-size: {self.font_size - 1}pt;
            border-top: 1px solid {border}; padding-top: 4px; }}
</style></head><body>
<header>
  <div class="brand">{html.escape(self.app_name)}</div>
  {f'<div class="company">{html.escape(table.company)}</div>' if table.company else ''}
</header>
<h1>{html.escape(table.title)}</h1>
<div class="meta">{html.escape(table.subtitle)}</div>
<div class="meta">{meta}</div>
{table_open}<thead><tr>{head_cells}</tr></thead>
<tbody>{''.join(body_rows)}{empty}{total_row}</tbody></table>
{notes}
<footer>{html.escape(self.app_name)} — نسخهٔ \u200e{__version__}\u200e · تاریخ تهیه: {format_datetime_as_jalali(_dt.datetime.now(_dt.timezone.utc))}</footer>
</body></html>"""

    # ------------------------------------------------------------------ fonts
    def _ensure_font(self) -> str:
        """Register the bundled Persian font (idempotent) and pick a family.

        Without this a headless PDF export would fall back to a Latin-only
        system font and Persian text would come out as empty boxes.
        """
        try:
            from pars_erp.ui.fonts import load_bundled_fonts, resolve_family

            load_bundled_fonts()
            return resolve_family(self.font_family)
        except Exception:  # pragma: no cover - Qt/font subsystem unavailable
            return self.font_family

    # ------------------------------------------------------------------- pdf
    def to_pdf(self, table: ReportTable, path: Path, *, theme: str = "light") -> ExportOutcome:
        """Write a real, right-to-left PDF with a footer and page numbers.

        Qt renders the rich text (so Persian shaping and the bundled Vazirmatn font
        are correct), but ``QTextDocument.print_`` gives no chance to add a page
        number, so the document is painted page by page: the body is clipped to the
        page box and the footer ("گزارش — صفحهٔ ۲ از ۵") is drawn after it.
        """
        try:
            from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
            from PySide6.QtGui import (
                QColor,
                QFont,
                QPageLayout,
                QPageSize,
                QPainter,
                QPdfWriter,
                QTextDocument,
            )
        except Exception as exc:  # pragma: no cover - Qt missing in a headless box
            raise ConfigurationError(
                "برای تولید PDF، کتابخانهٔ Qt در دسترس نیست.") from exc

        path.parent.mkdir(parents=True, exist_ok=True)
        _ensure_qt_application()
        family = self._ensure_font()
        handle, temp_name = tempfile.mkstemp(prefix=".report_", suffix=".pdf",
                                             dir=str(path.parent))
        os.close(handle)
        painter = None
        try:
            writer = QPdfWriter(temp_name)
            writer.setPageLayout(QPageLayout(
                QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Landscape,
                QMarginsF(10, 10, 10, 10), QPageLayout.Unit.Millimeter))
            writer.setResolution(150)
            writer.setTitle(table.title)
            writer.setCreator(self.app_name)

            painter = QPainter(writer)
            viewport = painter.viewport()
            margin = max(18, int(writer.resolution() * 0.16))       # ~4 mm
            footer_height = max(16, int(writer.resolution() * 0.10))
            body_width = max(100, viewport.width() - 2 * margin)
            body_height = max(100, viewport.height() - 2 * margin - footer_height)

            document = QTextDocument()
            document.setDefaultFont(QFont(family, self.font_size))
            document.setPageSize(QSizeF(body_width, body_height))
            document.setHtml(self.to_html(table, theme=theme, pixel_width=int(body_width * 0.99)))
            pages = max(1, document.pageCount())

            footer_font = QFont(family, max(7, self.font_size - 3))
            footer_color = QColor("#e8edf7" if (theme or "").lower() == "dark" else "#475467")
            for index in range(pages):
                if index:
                    writer.newPage()
                painter.save()
                painter.translate(margin, margin)
                painter.setClipRect(0, 0, body_width, body_height)
                painter.translate(0, -index * body_height)
                document.drawContents(painter)
                painter.restore()

                painter.setFont(footer_font)
                painter.setPen(footer_color)
                page_text = _persian(
                    self.persian_digits, f"صفحهٔ {index + 1} از {pages}")
                painter.drawText(
                    QRectF(0, viewport.height() - footer_height, viewport.width(), footer_height),
                    int(Qt.AlignmentFlag.AlignCenter), f"{table.title} — {page_text}")
                painter.drawText(
                    QRectF(margin, viewport.height() - footer_height,
                           viewport.width() - 2 * margin, footer_height),
                    int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                    _persian(self.persian_digits, self.app_name))
            painter.end()
            painter = None
            os.replace(temp_name, path)
        except Exception:
            if painter is not None:
                painter.end()
            Path(temp_name).unlink(missing_ok=True)
            raise
        return ExportOutcome(path=path, rows=len(table.rows), kind="pdf")

    # ----------------------------------------------------------------- excel
    def to_excel(self, table: ReportTable, path: Path) -> ExportOutcome:
        """Write a real ``.xlsx`` workbook (right-to-left, formatted, frozen header)."""
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
            from openpyxl.utils import get_column_letter
        except Exception as exc:  # pragma: no cover - optional dependency
            raise ConfigurationError(
                "برای خروجی Excel بستهٔ openpyxl نصب نیست. "
                "با دستور «pip install openpyxl» آن را نصب کنید.") from exc

        path.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = table.title[:28] or "گزارش"
        sheet.sheet_view.rightToLeft = True

        try:
            from pars_erp.core.money import get_currency

            places = max(0, min(4, get_currency(table.currency_code).places))
        except Exception:  # pragma: no cover - unknown currency code
            places = 0
        amount_format = "#,##0." + "0" * places if places else "#,##0"
        number_format = "#,##0.###"

        thin = Side(style="thin", color="D0D5DD")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        header_fill = PatternFill("solid", fgColor="F2F4F7")

        sheet.cell(row=1, column=1, value=self.app_name).font = Font(bold=True, size=13)
        sheet.cell(row=2, column=1, value=table.title).font = Font(bold=True, size=12)
        row_cursor = 3
        if table.company:
            sheet.cell(row=row_cursor, column=1, value=table.company)
            row_cursor += 1
        if table.subtitle:
            sheet.cell(row=row_cursor, column=1, value=table.subtitle)
            row_cursor += 1
        for item in table.meta:
            sheet.cell(row=row_cursor, column=1, value=item)
            row_cursor += 1
        row_cursor += 1

        for index, column in enumerate(table.columns, start=1):
            cell = sheet.cell(row=row_cursor, column=index, value=column.title_fa)
            cell.font = Font(bold=True)
            cell.fill = header_fill
            cell.border = border
            cell.alignment = Alignment(horizontal="center", vertical="center")
            letter = get_column_letter(index)
            sheet.column_dimensions[letter].width = max(12, int(16 * column.width))
        header_row = row_cursor
        sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)

        for row_index, row in enumerate(table.rows, start=header_row + 1):
            for col_index, column in enumerate(table.columns, start=1):
                value = row[col_index - 1] if col_index - 1 < len(row) else None
                numeric = (_numeric_cell_value(value, column)
                           if column.kind in (KIND_AMOUNT, KIND_NUMBER) else None)
                if numeric is not None:
                    cell = sheet.cell(row=row_index, column=col_index, value=numeric)
                    cell.number_format = amount_format if column.kind == KIND_AMOUNT else number_format
                elif column.kind == KIND_DATE and isinstance(value, (_dt.date, _dt.datetime)):
                    cell = sheet.cell(
                        row=row_index, column=col_index,
                        value=format_gregorian_as_jalali(value, persian_digits=False))
                else:
                    cell = sheet.cell(
                        row=row_index, column=col_index,
                        value=cell_text(value, column.kind,
                                        currency_code=table.currency_code,
                                        persian_digits=False))
                cell.border = border
                cell.alignment = Alignment(
                    horizontal="left" if column.kind in (KIND_AMOUNT, KIND_NUMBER) else "right",
                    vertical="center")

        if table.totals is not None:
            total_row_index = header_row + len(table.rows) + 1
            for col_index, column in enumerate(table.columns, start=1):
                value = table.totals[col_index - 1] if col_index - 1 < len(table.totals) else ""
                numeric = (_numeric_cell_value(value, column)
                           if column.kind in (KIND_AMOUNT, KIND_NUMBER) else None)
                if numeric is not None:
                    cell = sheet.cell(row=total_row_index, column=col_index, value=numeric)
                    cell.number_format = amount_format if column.kind == KIND_AMOUNT else number_format
                else:
                    cell = sheet.cell(row=total_row_index, column=col_index,
                                      value=cell_text(value, column.kind,
                                                      persian_digits=False))
                cell.font = Font(bold=True)
                cell.fill = header_fill
                cell.border = border

        footer_row = header_row + len(table.rows) + 3
        sheet.cell(row=footer_row, column=1,
                   value=f"{self.app_name} — نسخه {__version__} · "
                         f"تاریخ تهیه: {format_datetime_as_jalali(_dt.datetime.now(_dt.timezone.utc), persian_digits=False)}")

        workbook.properties.title = table.title
        workbook.properties.creator = self.app_name
        workbook.save(path)
        return ExportOutcome(path=path, rows=len(table.rows), kind="xlsx")


def table_from_rows(title: str, columns: Sequence[tuple[str, str, str]],
                    rows: Iterable[Sequence]) -> ReportTable:
    """Small helper for tests and simple callers: ``(key, title, kind)`` columns."""
    return ReportTable(
        title=title,
        columns=tuple(ReportColumn(key=key, title_fa=title_fa, kind=kind)
                      for key, title_fa, kind in columns),
        rows=tuple(tuple(row) for row in rows))
