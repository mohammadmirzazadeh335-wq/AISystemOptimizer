"""Phase-7 reporting engine: catalogue, permissions, features, saved reports, exports."""

from __future__ import annotations

import datetime as _dt
import os
import zipfile
from dataclasses import replace
from decimal import Decimal

import pytest

from pars_erp.accounting import constants as C
from pars_erp.core.errors import (
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from pars_erp.reporting.engine import (
    AGG_AVG,
    AGG_SUM,
    FILTER_DATE_RANGE,
    FilterSpec,
    ReportCatalogue,
    ReportDefinition,
    ReportQuery,
    run as run_report,
)
from pars_erp.services.journals_service import JournalInput, JournalLineInput
from pars_erp.services.report_engine_service import SaveReportInput
from pars_erp.security.permissions import build_context
from pars_erp.services.report_render_service import (
    KIND_AMOUNT,
    KIND_TEXT,
    ReportColumn,
    ReportTable,
)

ENTRY_DATE = _dt.date(2026, 4, 15)


def _ctx():
    """A minimal caller that may open the report centre (no database needed)."""
    return build_context(user_id=1, username="tester", full_name="آزمون",
                         role_codes=("viewer",), permissions={"reports.center"})


# --------------------------------------------------------------------- helpers
def _post(services, ctx, *, title, amount="1000000", date=ENTRY_DATE,
          debit="101001", credit="301001"):
    accounts = {row.code: row for row in
                services.accounts.list_accounts(ctx, level="subsidiary")}
    entry = JournalInput(
        entry_date=date, title_fa=title,
        lines=[JournalLineInput(account_id=accounts[debit].id, debit=Decimal(amount)),
               JournalLineInput(account_id=accounts[credit].id, credit=Decimal(amount))])
    journal = services.journals.create(ctx, entry)
    services.journals.submit(ctx, journal.id)
    services.journals.approve(ctx, journal.id)
    return services.journals.post(ctx, journal.id)


def _sample_catalogue() -> ReportCatalogue:
    """A tiny in-memory report, used to test the generic engine features."""

    def fetch(ctx, query):
        rows = [
            ("الف", "تهران", Decimal("1000"), 3),
            ("ب", "تهران", Decimal("2500"), 5),
            ("ج", "شیراز", Decimal("500"), 1),
            ("د", "شیراز", Decimal("1500"), 0),
        ]
        if query.params.get("empty"):
            rows = []
        return ReportTable(
            title="گزارش نمونه",
            columns=(ReportColumn("name", "نام", KIND_TEXT),
                     ReportColumn("city", "شهر", KIND_TEXT),
                     ReportColumn("amount", "مبلغ", KIND_AMOUNT),
                     ReportColumn("count", "تعداد", "number")),
            rows=tuple(rows))

    return ReportCatalogue([
        ReportDefinition(
            key="demo_report", title_fa="گزارش نمونه", section="demo",
            section_title_fa="نمونه", permission="reports.center",
            description_fa="برای آزمون موتور", fetcher=fetch,
            filters=(FilterSpec("date_range", "بازه", FILTER_DATE_RANGE),)),
    ])


# ------------------------------------------------------------------ catalogue
def test_catalogue_only_lists_reports_the_user_may_run(services, admin):
    engine = services.report_engine
    definitions = engine.definitions(admin)
    keys = {definition.key for definition in definitions}
    assert "acc_journal_book" in keys
    assert "hr_staff_list" in keys
    assert all(definition.permission in admin.permissions for definition in definitions)

    limited = replace(admin, permissions=frozenset({"reports.center"}))
    visible = engine.definitions(limited)
    assert visible == ()


def test_report_centre_requires_its_own_permission(services, admin):
    engine = services.report_engine
    without = replace(admin, permissions=frozenset({"reports.journal_book"}))
    with pytest.raises(PermissionDeniedError):
        engine.definitions(without)


def test_running_a_report_requires_the_report_permission(services, admin):
    engine = services.report_engine
    without = replace(admin, permissions=frozenset({"reports.center"}))
    with pytest.raises(PermissionDeniedError):
        engine.run(without, definition_key="acc_journal_book",
                   query=ReportQuery(date_from=ENTRY_DATE, date_to=ENTRY_DATE))


# -------------------------------------------------------- generic features
def test_engine_searches_sorts_and_pages():
    catalogue = _sample_catalogue()
    definition = catalogue.get("demo_report")
    result = run_report(definition, ReportQuery(page=1, page_size=10), _ctx())
    assert result.total_rows == 4
    assert result.columns[0].key == "name"

    searched = run_report(definition, ReportQuery(search="شیراز", page_size=10), _ctx())
    assert [row[0] for row in searched.rows] == ["ج", "د"]

    sorted_result = run_report(definition, ReportQuery(sort_key="amount", sort_desc=True,
                                                       page_size=10), _ctx())
    assert [row[2] for row in sorted_result.rows] == [
        Decimal("2500"), Decimal("1500"), Decimal("1000"), Decimal("500")]

    first_page = run_report(definition, ReportQuery(page=1, page_size=2, sort_key="amount"), _ctx())
    second_page = run_report(definition, ReportQuery(page=2, page_size=2, sort_key="amount"), _ctx())
    assert len(first_page.rows) == 2 and first_page.pages == 2
    assert [row[0] for row in second_page.rows] == ["د", "ب"]  # 1500, 2500


def test_engine_computes_aggregates_and_groups():
    catalogue = _sample_catalogue()
    definition = catalogue.get("demo_report")
    result = run_report(definition, ReportQuery(page_size=10), _ctx())
    sums = {value.column_key: value.value for value in result.aggregates
            if value.kind == AGG_SUM}
    assert sums["amount"] == Decimal("5500")
    assert sums["count"] == 9
    averages = {value.column_key: value.value for value in result.aggregates
                if value.kind == AGG_AVG}
    assert averages["amount"] == Decimal("1375.0000")

    grouped = run_report(definition, ReportQuery(group_by="city", page_size=10), _ctx())
    labels = {group.label_fa: group.count for group in grouped.groups}
    assert labels == {"تهران": 2, "شیراز": 2}
    tehran = next(group for group in grouped.groups if group.label_fa == "تهران")
    assert tehran.values[0] == Decimal("3500")


def test_column_selection_and_totals_row():
    catalogue = _sample_catalogue()
    definition = catalogue.get("demo_report")
    result = run_report(definition,
                        ReportQuery(column_keys=("name", "amount"), page_size=10), _ctx())
    assert tuple(column.key for column in result.columns) == ("name", "amount")
    assert result.table.totals[1] == Decimal("5500")


def test_engine_refuses_unknown_options():
    catalogue = _sample_catalogue()
    definition = catalogue.get("demo_report")
    with pytest.raises(ValidationError):
        run_report(definition, ReportQuery(sort_key="nope"), _ctx())
    with pytest.raises(ValidationError):
        run_report(definition, ReportQuery(group_by="nope"), _ctx())
    with pytest.raises(ValidationError):
        run_report(definition, ReportQuery(column_keys=("nope",)), _ctx())
    with pytest.raises(ValidationError):
        run_report(definition, ReportQuery(page_size=-1), _ctx())
    with pytest.raises(ValidationError):
        run_report(definition, ReportQuery(date_from=_dt.date(2026, 5, 1),
                                           date_to=_dt.date(2026, 4, 1)), _ctx())


# ---------------------------------------------------- real service integration
def test_journal_book_report_runs_on_real_documents(services, admin, chart):
    _post(services, admin, title="فروش نقدی", amount="1000000")
    _post(services, admin, title="خرید مواد", amount="400000", debit="501001", credit="101001")

    result = services.report_engine.run(
        admin, definition_key="acc_journal_book",
        query=ReportQuery(date_from=ENTRY_DATE, date_to=ENTRY_DATE, page_size=100))
    assert result.total_rows == 4  # the daybook is line-based: two lines per document
    titles = [row[2] for row in result.rows]
    assert "فروش نقدی" in titles and "خرید مواد" in titles
    debit = next(value for value in result.aggregates
                 if value.column_key == "debit" and value.kind == AGG_SUM)
    credit = next(value for value in result.aggregates
                  if value.column_key == "credit" and value.kind == AGG_SUM)
    assert debit.value == credit.value == Decimal("1400000.0000")  # documents are balanced


def test_report_without_documents_is_empty_not_invented(services, admin, chart):
    result = services.report_engine.run(
        admin, definition_key="acc_trial_balance",
        query=ReportQuery(date_from=ENTRY_DATE, date_to=ENTRY_DATE))
    assert result.total_rows == 0
    assert result.table.rows == ()


# ------------------------------------------------------------ saved reports
def test_saved_report_lifecycle(services, admin):
    engine = services.report_engine
    saved = engine.save(admin, SaveReportInput(
        name="روزنامهٔ من", definition_key="acc_journal_book",
        column_keys=(), page_size=50, is_default=True))
    assert saved.is_mine
    assert saved.definition_title_fa == "دفتر روزنامه"

    rows = engine.saved_reports(admin)
    assert [row.name for row in rows] == ["روزنامهٔ من"]
    assert engine.default_report(admin).id == saved.id

    updated = engine.update(admin, saved.id, SaveReportInput(
        name="روزنامهٔ کاری", definition_key="acc_journal_book", page_size=200,
        sort_key="c0", sort_desc=True))
    assert updated.name == "روزنامهٔ کاری"
    assert updated.page_size == 200

    engine.delete(admin, saved.id)
    assert engine.saved_reports(admin) == ()


def test_saved_report_runs_with_the_stored_options(services, admin, chart):
    engine = services.report_engine
    _post(services, admin, title="سند ذخیره‌شده")
    saved = engine.save(admin, SaveReportInput(
        name="دفتر روزنامهٔ بازه", definition_key="acc_journal_book",
        date_from=ENTRY_DATE, date_to=ENTRY_DATE, page_size=25))
    result = engine.run_saved(admin, saved.id)
    assert result.total_rows == 2  # one document = two balanced lines
    row = engine.saved_reports(admin)[0]
    assert row.run_count == 1 and row.last_run_at is not None


def test_saved_reports_are_private_until_shared(services, admin, accountant):
    engine = services.report_engine
    saved = engine.save(admin, SaveReportInput(name="گزارش مدیر",
                                               definition_key="acc_journal_book"))
    assert engine.saved_reports(accountant) == ()
    with pytest.raises(NotFoundError):
        engine.run_saved(accountant, saved.id)

    engine.share(admin, saved.id, role_codes=("accountant",))
    shared = engine.saved_reports(accountant)
    assert [row.name for row in shared] == ["گزارش مدیر"]
    assert shared[0].is_mine is False
    assert engine.run_saved(accountant, saved.id).definition_key == "acc_journal_book"

    with pytest.raises(NotFoundError):
        engine.delete(accountant, saved.id)


def test_duplicate_report_name_is_refused(services, admin):
    engine = services.report_engine
    engine.save(admin, SaveReportInput(name="تکراری", definition_key="acc_journal_book"))
    with pytest.raises(Exception):
        engine.save(admin, SaveReportInput(name="تکراری",
                                           definition_key="acc_journal_book"))


def test_saved_report_rejects_columns_that_do_not_exist(services, admin):
    engine = services.report_engine
    with pytest.raises(ValidationError):
        engine.save(admin, SaveReportInput(name="بد", definition_key="acc_journal_book",
                                           column_keys=("nope",)))


# ------------------------------------------------------------------ exports
def test_exports_write_real_files(services, admin, chart, tmp_path):
    _post(services, admin, title="سند خروجی")
    engine = services.report_engine
    result = engine.run(admin, definition_key="acc_journal_book",
                        query=ReportQuery(date_from=ENTRY_DATE, date_to=ENTRY_DATE))

    csv_path = engine.export_csv(admin, result, tmp_path / "report.csv", delimiter=";")
    text = csv_path.read_text(encoding="utf-8-sig")
    assert "دفتر روزنامه" in text
    assert "سند خروجی" in text
    assert ";" in text

    xlsx_path = tmp_path / "report.xlsx"
    outcome = engine.export_excel(admin, result, xlsx_path)
    assert outcome.rows == result.total_rows
    assert zipfile.ZipFile(xlsx_path).testzip() is None

    pdf_path = tmp_path / "report.pdf"
    pdf_outcome = engine.export_pdf(admin, result, pdf_path)
    assert pdf_path.read_bytes()[:4] == b"%PDF"
    assert pdf_outcome.rows == result.total_rows


def test_export_requires_the_export_permission(services, admin, chart, tmp_path):
    engine = services.report_engine
    result = engine.run(admin, definition_key="acc_trial_balance",
                        query=ReportQuery(date_from=ENTRY_DATE, date_to=ENTRY_DATE))
    limited = replace(admin, permissions=frozenset({"reports.center"}))
    with pytest.raises(PermissionDeniedError):
        engine.export_csv(limited, result, tmp_path / "denied.csv")
