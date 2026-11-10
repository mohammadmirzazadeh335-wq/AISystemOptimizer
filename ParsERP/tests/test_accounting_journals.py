"""Journal document lifecycle: balance rule, workflow, immutability, reversals."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from pars_erp.accounting import constants as C
from pars_erp.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from pars_erp.services.journals_service import (
    JournalFilter,
    JournalInput,
    JournalLineInput,
)
from pars_erp.services.periods_service import PeriodInput

ENTRY_DATE = _dt.date(2026, 4, 15)


def _entry(accounts, *, date=ENTRY_DATE, title="سند آزمون", debit_code="101001",
           credit_code="301001", amount="1000000"):
    return JournalInput(
        entry_date=date, title_fa=title,
        lines=[JournalLineInput(account_id=accounts[debit_code].id, debit=Decimal(amount)),
               JournalLineInput(account_id=accounts[credit_code].id, credit=Decimal(amount))])


def _post(services, ctx, journal):
    services.journals.submit(ctx, journal.id)
    services.journals.approve(ctx, journal.id)
    return services.journals.post(ctx, journal.id)


# ------------------------------------------------------------------- validation
def test_balanced_document_is_created_as_draft(services, admin, chart):
    accounts, period = chart
    journal = services.journals.create(admin, _entry(accounts))
    assert journal.status == C.STATUS_DRAFT
    assert journal.status_fa == "پیش‌نویس"
    assert journal.number == 1
    assert journal.total_debit == Decimal("1000000.0000")
    assert journal.total_credit == Decimal("1000000.0000")
    assert journal.is_balanced
    assert journal.line_count == 2
    assert journal.fiscal_period_id == period.id


def test_unbalanced_document_is_refused(services, admin, chart):
    accounts, _ = chart
    with pytest.raises(ValidationError) as exc:
        services.journals.create(admin, JournalInput(
            entry_date=ENTRY_DATE, title_fa="سند نامتوازن",
            lines=[JournalLineInput(account_id=accounts["101001"].id,
                                    debit=Decimal("1000")),
                   JournalLineInput(account_id=accounts["301001"].id,
                                    credit=Decimal("900"))]))
    assert "برابر نیست" in str(exc.value)


def test_each_line_has_exactly_one_side_and_positive_amount(services, admin, chart):
    accounts, _ = chart
    with pytest.raises(ValidationError):
        services.journals.create(admin, JournalInput(
            entry_date=ENTRY_DATE, title_fa="دو طرفه",
            lines=[JournalLineInput(account_id=accounts["101001"].id,
                                    debit=Decimal("100"), credit=Decimal("100")),
                   JournalLineInput(account_id=accounts["301001"].id,
                                    credit=Decimal("100"))]))
    with pytest.raises(ValidationError):
        services.journals.create(admin, JournalInput(
            entry_date=ENTRY_DATE, title_fa="مبلغ صفر",
            lines=[JournalLineInput(account_id=accounts["101001"].id, debit=Decimal("0")),
                   JournalLineInput(account_id=accounts["301001"].id, credit=Decimal("0"))]))
    with pytest.raises(ValidationError):
        services.journals.create(admin, JournalInput(
            entry_date=ENTRY_DATE, title_fa="مبلغ منفی",
            lines=[JournalLineInput(account_id=accounts["101001"].id,
                                    debit=Decimal("-5")),
                   JournalLineInput(account_id=accounts["301001"].id,
                                    credit=Decimal("-5"))]))


def test_document_requires_at_least_two_lines_and_a_title(services, admin, chart):
    accounts, _ = chart
    with pytest.raises(ValidationError):
        services.journals.create(admin, JournalInput(
            entry_date=ENTRY_DATE, title_fa="یک ردیف",
            lines=[JournalLineInput(account_id=accounts["101001"].id,
                                    debit=Decimal("10"))]))
    with pytest.raises(ValidationError):
        services.journals.create(admin, JournalInput(
            entry_date=ENTRY_DATE, title_fa="ب",
            lines=[JournalLineInput(account_id=accounts["101001"].id, debit=Decimal("10")),
                   JournalLineInput(account_id=accounts["301001"].id,
                                    credit=Decimal("10"))]))


def test_only_active_subsidiary_accounts_are_allowed(services, admin, chart):
    accounts, _ = chart
    total = next(row for row in services.accounts.list_accounts(admin, level="total")
                 if row.code == "101")
    with pytest.raises(ValidationError) as exc:
        services.journals.create(admin, JournalInput(
            entry_date=ENTRY_DATE, title_fa="حساب کل در سند",
            lines=[JournalLineInput(account_id=total.id, debit=Decimal("10")),
                   JournalLineInput(account_id=accounts["301001"].id,
                                    credit=Decimal("10"))]))
    assert "معین" in str(exc.value)

    services.accounts.set_active(admin, accounts["101004"].id, False)
    with pytest.raises(ValidationError) as exc:
        services.journals.create(admin, JournalInput(
            entry_date=ENTRY_DATE, title_fa="حساب غیرفعال",
            lines=[JournalLineInput(account_id=accounts["101004"].id, debit=Decimal("10")),
                   JournalLineInput(account_id=accounts["301001"].id,
                                    credit=Decimal("10"))]))
    assert "غیرفعال" in str(exc.value)


def test_detail_must_belong_to_the_selected_account(services, admin, chart):
    from pars_erp.services.parties_service import DetailInput

    accounts, _ = chart
    detail = services.parties.create(admin, DetailInput(
        code="5001", name="مشتری الف", kind=C.DETAIL_CUSTOMER,
        account_id=accounts["101002"].id))
    with pytest.raises(ValidationError) as exc:
        services.journals.create(admin, JournalInput(
            entry_date=ENTRY_DATE, title_fa="تفصیلی نامرتبط",
            lines=[JournalLineInput(account_id=accounts["101001"].id, debit=Decimal("10"),
                                    detail_id=detail.id),
                   JournalLineInput(account_id=accounts["301001"].id,
                                    credit=Decimal("10"))]))
    assert "تعلق ندارد" in str(exc.value)


def test_document_date_must_be_inside_an_open_period(services, admin, chart):
    accounts, _ = chart
    with pytest.raises(ValidationError):
        services.journals.create(admin, _entry(accounts, date=_dt.date(2019, 1, 1)))
    services.periods.create(admin, PeriodInput(
        code="1399", title_fa="سال مالی ۱۳۹۹",
        start_date=_dt.date(2020, 3, 20), end_date=_dt.date(2021, 3, 20)))
    closed = services.periods.create(admin, PeriodInput(
        code="1398", title_fa="سال مالی ۱۳۹۸",
        start_date=_dt.date(2019, 3, 21), end_date=_dt.date(2020, 3, 19)))
    services.periods.close(admin, closed.id)
    with pytest.raises(ValidationError) as exc:
        services.journals.create(admin, _entry(accounts, date=_dt.date(2019, 6, 1)))
    assert "بسته" in str(exc.value)


# -------------------------------------------------------------------- workflow
def test_post_requires_the_full_workflow(services, admin, chart):
    accounts, _ = chart
    journal = services.journals.create(admin, _entry(accounts))
    with pytest.raises(ValidationError):
        services.journals.post(admin, journal.id)          # still a draft
    submitted = services.journals.submit(admin, journal.id)
    assert submitted.status == C.STATUS_PENDING
    with pytest.raises(ValidationError):
        services.journals.post(admin, journal.id)          # not approved yet
    approved = services.journals.approve(admin, journal.id)
    assert approved.status == C.STATUS_APPROVED
    posted = services.journals.post(admin, journal.id)
    assert posted.status == C.STATUS_POSTED
    assert posted.posted_at is not None
    with pytest.raises(ValidationError):
        services.journals.post(admin, journal.id)          # already posted


def test_returned_document_becomes_editable_again(services, admin, chart):
    accounts, _ = chart
    journal = services.journals.create(admin, _entry(accounts))
    services.journals.submit(admin, journal.id)
    returned = services.journals.return_to_draft(admin, journal.id, reason="شرح ناقص")
    assert returned.status == C.STATUS_DRAFT
    updated = services.journals.update_draft(admin, journal.id, _entry(
        accounts, title="سند اصلاح‌شده", amount="2000000"))
    assert updated.title_fa == "سند اصلاح‌شده"
    assert updated.total_debit == Decimal("2000000.0000")


def test_posted_document_cannot_be_edited_or_deleted(services, admin, chart):
    accounts, _ = chart
    posted = _post(services, admin, services.journals.create(admin, _entry(accounts)))
    with pytest.raises(ValidationError):
        services.journals.update_draft(admin, posted.id, _entry(accounts))
    with pytest.raises(ValidationError):
        services.journals.delete_draft(admin, posted.id)


def test_draft_deletion_and_duplication(services, admin, chart):
    accounts, _ = chart
    draft = services.journals.create(admin, _entry(accounts))
    copy = services.journals.duplicate(admin, draft.id)
    assert copy.id != draft.id
    assert copy.number == draft.number + 1
    assert copy.total_debit == draft.total_debit
    services.journals.delete_draft(admin, draft.id)
    with pytest.raises(NotFoundError):
        services.journals.get(admin, draft.id)


def test_idempotency_key_prevents_duplicate_submission(services, admin, chart):
    accounts, _ = chart
    payload = JournalInput(
        entry_date=ENTRY_DATE, title_fa="ثبت تکراری",
        lines=[JournalLineInput(account_id=accounts["101001"].id, debit=Decimal("700")),
               JournalLineInput(account_id=accounts["301001"].id, credit=Decimal("700"))],
        idempotency_key="abc-123")
    first = services.journals.create(admin, payload)
    second = services.journals.create(admin, payload)
    assert first.id == second.id
    assert services.journals.list(admin).total == 1


def test_numbers_are_sequential_per_period(services, admin, chart):
    accounts, _ = chart
    numbers = [services.journals.create(admin, _entry(accounts)).number for _ in range(3)]
    assert numbers == [1, 2, 3]


# --------------------------------------------------------------- void/reversal
def test_void_requires_reason_and_posted_status(services, admin, chart):
    accounts, _ = chart
    draft = services.journals.create(admin, _entry(accounts))
    with pytest.raises(ValidationError):
        services.journals.void(admin, draft.id, "دلیل کافی")
    posted = _post(services, admin, services.journals.create(admin, _entry(accounts)))
    with pytest.raises(ValidationError):
        services.journals.void(admin, posted.id, "کم")
    voided = services.journals.void(admin, posted.id, "اشتباه در تاریخ سند")
    assert voided.status == C.STATUS_VOID
    assert voided.void_reason == "اشتباه در تاریخ سند"
    with pytest.raises(ValidationError):
        services.journals.void(admin, posted.id, "دوباره ابطال کنیم")


def test_reversal_creates_a_mirrored_posted_document(services, admin, chart):
    accounts, _ = chart
    posted = _post(services, admin, services.journals.create(admin, _entry(accounts)))
    mirror = services.journals.reverse(admin, posted.id, reason="اصلاح سند")
    assert mirror.status == C.STATUS_POSTED
    assert mirror.reverses_journal_id == posted.id
    assert mirror.total_debit == posted.total_credit
    assert [line.account_id for line in mirror.lines] == [
        line.account_id for line in posted.lines]
    assert mirror.lines[0].debit == posted.lines[0].credit
    assert mirror.lines[0].credit == posted.lines[0].debit
    with pytest.raises(ConflictError):
        services.journals.reverse(admin, posted.id)


def test_voided_document_no_longer_affects_balances(services, admin, chart):
    accounts, period = chart
    posted = _post(services, admin, services.journals.create(admin, _entry(accounts)))
    services.journals.void(admin, posted.id, "ابطال آزمون")
    report = services.reports.trial_balance(admin, date_from=period.start_date,
                                            date_to=period.end_date)
    assert report.rows == ()
    assert report.is_balanced


# ---------------------------------------------------------------- modification
def test_update_replaces_lines_atomically(services, admin, chart):
    accounts, _ = chart
    draft = services.journals.create(admin, _entry(accounts))
    updated = services.journals.update_draft(admin, draft.id, JournalInput(
        entry_date=ENTRY_DATE, title_fa="سند سه‌ردیفی",
        lines=[JournalLineInput(account_id=accounts["101001"].id, debit=Decimal("300")),
               JournalLineInput(account_id=accounts["502003"].id, debit=Decimal("200")),
               JournalLineInput(account_id=accounts["301001"].id, credit=Decimal("500"))]))
    assert updated.line_count == 3
    assert updated.total_debit == Decimal("500.0000")
    detail = services.journals.get(admin, draft.id)
    assert [line.line_no for line in detail.lines] == [1, 2, 3]


def test_filters_and_paging(services, admin, chart):
    accounts, period = chart
    for index in range(3):
        _post(services, admin, services.journals.create(
            admin, _entry(accounts, title=f"سند شماره {index}")))
    page = services.journals.list(admin, JournalFilter(status=C.STATUS_POSTED),
                                  page=1, page_size=2)
    assert page.total == 3
    assert len(page.items) == 2
    assert page.pages == 2
    found = services.journals.list(admin, JournalFilter(search="شماره 2"))
    assert found.total == 1
    by_account = services.journals.list(admin, JournalFilter(account_id=accounts["101001"].id))
    assert by_account.total == 3
    by_date = services.journals.list(admin, JournalFilter(
        date_from=ENTRY_DATE, date_to=ENTRY_DATE))
    assert by_date.total == 3
    summary = services.journals.summary(admin)
    assert summary["posted"] == 3


def test_accountant_cannot_post_documents(services, admin, accountant, chart):
    accounts, _ = chart
    journal = services.journals.create(accountant, _entry(accounts))
    services.journals.submit(accountant, journal.id)
    with pytest.raises(PermissionDeniedError):
        services.journals.approve(accountant, journal.id)
    with pytest.raises(PermissionDeniedError):
        services.journals.post(accountant, journal.id)
    # the administrator can finish the job (the document already waits for approval)
    services.journals.approve(admin, journal.id)
    assert services.journals.post(admin, journal.id).status == C.STATUS_POSTED
