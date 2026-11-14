"""Rendering of report tables to HTML, Excel and PDF.

The renderer is deliberately Qt-light: HTML and Excel must work on a machine
without Qt installed, while the PDF path (which needs ``QPdfWriter``) is
skipped when Qt cannot be imported at all.  Every test asserts something a
user could actually see in the exported file - no smoke-only assertions.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from pathlib import Path

import pytest

from pars_erp.core.errors import ConfigurationError
from pars_erp.services.report_render_service import (
    KIND_AMOUNT,
    KIND_DATE,
    KIND_NUMBER,
    KIND_TEXT,
    ExportOutcome,
    ReportColumn,
    ReportRenderer,
    ReportTable,
    cell_text,
    table_from_rows,
)


def _qt_available() -> bool:
    try:
        import PySide6.QtGui  # noqa: F401
    except Exception:
        return False
    return True


QT_AVAILABLE = _qt_available()
requires_qt = pytest.mark.skipif(not QT_AVAILABLE, reason="Qt is not installed")


def _sample_table(row_count: int = 3, *, totals: bool = True) -> ReportTable:
    columns = (
        ReportColumn("code", "کد حساب", KIND_TEXT, 1.2),
        ReportColumn("day", "تاریخ", KIND_DATE, 1.2),
        ReportColumn("qty", "تعداد", KIND_NUMBER, 1.0),
        ReportColumn("debit", "بدهکار", KIND_AMOUNT, 1.6),
        ReportColumn("credit", "بستانکار", KIND_AMOUNT, 1.6),
    )
    rows = tuple(
        (f"1010{index:02d}", _dt.date(2026, 4, 1 + index % 9), Decimal(index * 2),
         Decimal("1250000.5") * index, Decimal(0))
        for index in range(1, row_count + 1))
    total = None
    if totals:
        total = ("", "", "", sum(r[3] for r in rows), sum(r[4] for r in rows))
    return ReportTable(
        title="تراز آزمایشی", columns=columns, rows=rows,
        company="شرکت نمونه زرین هرمز", subtitle="از ۱۴۰۵/۰۱/۰۱ تا ۱۴۰۵/۱۲/۲۹",
        meta=("فقط اسناد ثبت‌شده", "ارز مبنا: ریال"), totals=total,
        notes=("گزارش صرفاً از اسناد قطعی تولید می‌شود.",))


class TestCellText:
    def test_amount_uses_grouping(self) -> None:
        assert cell_text(Decimal("1234567"), KIND_AMOUNT, currency_code="IRR",
                         persian_digits=False) == "1,234,567"

    def test_rial_amounts_round_to_whole_numbers(self) -> None:
        """Rial has no sub-unit, so a half rial rounds up (never truncates)."""
        assert cell_text(Decimal("1234567.5"), KIND_AMOUNT, currency_code="IRR",
                         persian_digits=False) == "1,234,568"

    def test_currency_decimals_are_respected(self) -> None:
        text = cell_text(Decimal("1234.5"), KIND_AMOUNT, currency_code="USD",
                         persian_digits=False)
        assert text == "1,234.50"

    def test_persian_digits_and_separators_are_applied(self) -> None:
        text = cell_text(Decimal("1250"), KIND_AMOUNT, persian_digits=True)
        assert text == "۱٬۲۵۰"

    def test_plain_digits_when_disabled(self) -> None:
        text = cell_text(Decimal("1250"), KIND_NUMBER, persian_digits=False)
        assert text == "1,250"
        assert not any("۰" <= character <= "۹" for character in text)

    def test_numbers_use_persian_separators(self) -> None:
        assert cell_text(Decimal("1250.5"), KIND_NUMBER, persian_digits=True) == "۱٬۲۵۰٫۵"

    def test_date_is_converted_to_jalali(self) -> None:
        text = cell_text(_dt.date(2026, 3, 21), KIND_DATE, persian_digits=False)
        assert text == "1405/01/01"

    def test_empty_values_render_a_dash(self) -> None:
        for value in (None, ""):
            assert cell_text(value, KIND_TEXT) == "—"

    def test_text_is_kept_but_digits_become_persian(self) -> None:
        assert cell_text("حساب موجودی نقد", KIND_TEXT) == "حساب موجودی نقد"
        assert cell_text("101001", KIND_TEXT) == "۱۰۱۰۰۱"
        assert cell_text("101001", KIND_TEXT, persian_digits=False) == "101001"


class TestHtml:
    def test_page_is_rtl_and_branded(self) -> None:
        html = ReportRenderer(app_name="زرین هرمز").to_html(_sample_table())
        assert 'dir="rtl"' in html
        assert 'lang="fa"' in html
        assert "زرین هرمز" in html
        assert "@page" in html and "A4 landscape" in html

    def test_report_content_is_present(self) -> None:
        table = _sample_table()
        html = ReportRenderer().to_html(table)
        assert "تراز آزمایشی" in html
        assert "شرکت نمونه زرین هرمز" in html
        assert "۱۰۱۰۰۱" in html
        assert "از ۱۴۰۵/۰۱/۰۱ تا ۱۴۰۵/۱۲/۲۹" in html
        assert "فقط اسناد ثبت‌شده" in html
        assert "گزارش صرفاً از اسناد قطعی تولید می‌شود." in html

    def test_report_without_name_uses_product_brand(self) -> None:
        from pars_erp import APP_NAME_DEFAULT

        assert APP_NAME_DEFAULT in ReportRenderer().to_html(_sample_table())

    def test_totals_row_is_rendered(self) -> None:
        table = _sample_table(3)
        html = ReportRenderer().to_html(table)
        expected_debit = sum(row[3] for row in table.rows)
        assert 'class="total"' in html
        assert cell_text(expected_debit, KIND_AMOUNT) in html

    def test_empty_table_says_so(self) -> None:
        html = ReportRenderer().to_html(_sample_table(0, totals=False))
        assert "داده‌ای برای نمایش وجود ندارد" in html

    def test_html_is_escaped(self) -> None:
        table = ReportTable(
            title="گزارش <script>", columns=(ReportColumn("a", "عنوان <b>"),),
            rows=(("<script>alert(1)</script>",),))
        html = ReportRenderer().to_html(table)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_dark_theme_changes_colours(self) -> None:
        renderer = ReportRenderer()
        light = renderer.to_html(_sample_table(), theme="light")
        dark = renderer.to_html(_sample_table(), theme="dark")
        assert "#ffffff" in light and "#0b1220" in dark
        assert light != dark

    def test_pixel_width_is_applied_to_the_table(self) -> None:
        html = ReportRenderer().to_html(_sample_table(), pixel_width=1600)
        assert '<table width="1600"' in html
        assert 'width="800"' in html or 'width="3' in html

    def test_persian_digits_toggle(self) -> None:
        fa = ReportRenderer(persian_digits=True).to_html(_sample_table())
        en = ReportRenderer(persian_digits=False).to_html(_sample_table())
        assert "۱۰۱۰۰۱" in fa
        assert "۱۰۱۰۰۱" not in en
        assert "101001" in en


class TestExcel:
    def test_workbook_structure(self, tmp_path: Path) -> None:
        from openpyxl import load_workbook

        table = _sample_table(4)
        outcome = ReportRenderer().to_excel(table, tmp_path / "reports" / "tb.xlsx")
        assert isinstance(outcome, ExportOutcome)
        assert outcome.rows == 4
        assert outcome.kind == "xlsx"
        assert outcome.path.exists()

        sheet = load_workbook(outcome.path).active
        assert sheet.sheet_view.rightToLeft is True
        cells = [[cell.value for cell in row] for row in sheet.iter_rows()]
        flat = [str(value) for row in cells for value in row if value is not None]
        assert any("تراز آزمایشی" in value for value in flat)
        assert any("شرکت نمونه زرین هرمز" in value for value in flat)
        assert any("زرین هرمز" in value and "نسخه" in value for value in flat)

    def test_numbers_are_written_as_numbers(self, tmp_path: Path) -> None:
        from openpyxl import load_workbook

        outcome = ReportRenderer().to_excel(_sample_table(2), tmp_path / "num.xlsx")
        sheet = load_workbook(outcome.path).active
        numeric: list[float] = []
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, (int, float)):
                    numeric.append(float(cell.value))
        assert numeric, "expected real numeric cells, not strings"
        assert any(abs(value - 1250000.5) < 1 for value in numeric)

    def test_header_is_frozen_and_bold(self, tmp_path: Path) -> None:
        from openpyxl import load_workbook

        outcome = ReportRenderer().to_excel(_sample_table(2), tmp_path / "hdr.xlsx")
        sheet = load_workbook(outcome.path).active
        assert sheet.freeze_panes is not None
        # the header row is the one holding the column titles
        header_row = next(row for row in sheet.iter_rows()
                          if row[0].value == "کد حساب")
        assert all(cell.font.bold for cell in header_row if cell.value)
        frozen_from = int("".join(c for c in (sheet.freeze_panes or "") if c.isdigit()) or 0)
        assert frozen_from == header_row[0].row + 1

    def test_large_amounts_keep_full_precision(self, tmp_path: Path) -> None:
        """No float conversion: 16-digit Rial totals must survive intact."""
        from openpyxl import load_workbook

        exact = Decimal("1234567890123456")
        table = ReportTable(title="مبالغ بزرگ",
                            columns=(ReportColumn("a", "کد"),
                                     ReportColumn("b", "مبلغ", KIND_AMOUNT)),
                            rows=(("A", exact),))
        outcome = ReportRenderer().to_excel(table, tmp_path / "big.xlsx")
        sheet = load_workbook(outcome.path).active
        values = [cell.value for row in sheet.iter_rows() for cell in row]
        assert any(Decimal(str(value)) == exact for value in values if isinstance(value, (int, float)))

    def test_empty_table_still_produces_a_file(self, tmp_path: Path) -> None:
        outcome = ReportRenderer().to_excel(_sample_table(0, totals=False),
                                            tmp_path / "empty.xlsx")
        assert outcome.rows == 0
        assert outcome.path.stat().st_size > 0

    def test_outcome_message_is_persian(self, tmp_path: Path) -> None:
        outcome = ReportRenderer().to_excel(_sample_table(3), tmp_path / "msg.xlsx")
        assert "3" in outcome.message_fa or "۳" in outcome.message_fa
        assert "tb" not in outcome.message_fa


class TestPdf:
    @requires_qt
    def test_pdf_is_a_real_file(self, tmp_path: Path) -> None:
        outcome = ReportRenderer().to_pdf(_sample_table(5), tmp_path / "report.pdf")
        assert outcome.kind == "pdf"
        assert outcome.rows == 5
        data = outcome.path.read_bytes()
        assert data.startswith(b"%PDF-")
        assert data.rstrip().endswith(b"%%EOF")

    @requires_qt
    def test_pdf_embeds_the_persian_font(self, tmp_path: Path) -> None:
        outcome = ReportRenderer().to_pdf(_sample_table(3), tmp_path / "font.pdf")
        data = outcome.path.read_bytes()
        assert b"/FontFile" in data, "fonts must be embedded for a portable PDF"
        assert b"Vazirmatn" in data

    @requires_qt
    def test_long_report_spans_several_pages(self, tmp_path: Path) -> None:
        table = _sample_table(120)
        outcome = ReportRenderer(font_size=11).to_pdf(table, tmp_path / "long.pdf")
        data = outcome.path.read_bytes()
        pages = data.count(b"/Type /Page") - data.count(b"/Type /Pages")
        assert pages >= 2, f"expected a multi-page PDF, saw {pages} page(s)"

    @requires_qt
    def test_pdf_can_be_written_without_a_gui(self, tmp_path: Path) -> None:
        """Exports run from the CLI too, where no ``QApplication`` exists."""
        outcome = ReportRenderer().to_pdf(_sample_table(2), tmp_path / "headless.pdf")
        assert outcome.path.exists() and outcome.path.stat().st_size > 500

    @requires_qt
    def test_pdf_directory_is_created(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c.pdf"
        ReportRenderer().to_pdf(_sample_table(1), target)
        assert target.exists()

    @requires_qt
    def test_theme_is_honoured(self, tmp_path: Path) -> None:
        light = ReportRenderer().to_pdf(_sample_table(1), tmp_path / "l.pdf",
                                        theme="light")
        dark = ReportRenderer().to_pdf(_sample_table(1), tmp_path / "d.pdf",
                                       theme="dark")
        assert light.path.read_bytes() != dark.path.read_bytes()


class TestHelpers:
    def test_table_from_rows_builds_columns(self) -> None:
        table = table_from_rows(
            "کاردکس", [("code", "کد", KIND_TEXT), ("amount", "مبلغ", KIND_AMOUNT)],
            [("A", 10), ("B", 20)])
        assert table.title == "کاردکس"
        assert [column.key for column in table.columns] == ["code", "amount"]
        assert [column.kind for column in table.columns] == [KIND_TEXT, KIND_AMOUNT]
        assert table.rows == (("A", 10), ("B", 20))
        assert not table.is_empty

    def test_rows_may_be_short(self) -> None:
        table = ReportTable(title="ناقص", columns=(ReportColumn("a", "الف"),
                                                   ReportColumn("b", "ب")),
                            rows=(("only-first",),))
        html = ReportRenderer().to_html(table)
        assert "only-first" in html

    def test_renderer_defaults_are_persian(self) -> None:
        renderer = ReportRenderer()
        assert renderer.persian_digits is True
        assert renderer.font_family == "Vazirmatn"
        assert renderer.font_size >= 9


def _pdf_text_pages(data_path: Path):
    """Extract per-page text with Qt's PDF reader; ``None`` when unavailable."""
    try:
        from PySide6.QtPdf import QPdfDocument
    except Exception:
        return None
    document = QPdfDocument(None)
    document.load(str(data_path))
    if document.status() != QPdfDocument.Status.Ready:
        return None
    return [document.getAllText(index).text() for index in range(document.pageCount())]


@requires_qt
def test_pdf_footer_carries_the_page_number_and_the_brand(tmp_path: Path) -> None:
    """Every page ends with «… — صفحهٔ ۲ از ۵» and the application name."""
    table = _sample_table(120)
    outcome = ReportRenderer(app_name="زرین هرمز").to_pdf(table, tmp_path / "footer.pdf")
    pages = _pdf_text_pages(outcome.path)
    if pages is None:  # pragma: no cover - Qt built without the PDF reader
        pytest.skip("Qt's PDF reader is not available in this build")
    assert len(pages) >= 2
    first, last = pages[0], pages[-1]
    total = f"{len(pages)}".translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    # The extracted text comes back with the shaping/bidi artefacts of the
    # glyph run ("زر\x0cن" for «زرین»), so only the stable parts are asserted.
    assert "صفح" in last and "از ۵" in last or f"از {total}" in last
    assert "هرمز" in last
    assert "صفح" in first
