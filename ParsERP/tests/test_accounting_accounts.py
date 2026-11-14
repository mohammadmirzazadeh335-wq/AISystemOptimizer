"""Chart of accounts, subsidiary details and accounting permissions."""

from __future__ import annotations

import datetime as _dt

import pytest

from pars_erp.accounting import constants as C
from pars_erp.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from pars_erp.services.accounts_service import AccountInput
from pars_erp.services.parties_service import DetailInput


def _group(code="1", title="دارایی‌ها", account_type=C.TYPE_ASSET):
    return AccountInput(code=code, title_fa=title, level=C.LEVEL_GROUP,
                        account_type=account_type)


def _total(parent_id: int, code="101", title="دارایی جاری"):
    return AccountInput(code=code, title_fa=title, level=C.LEVEL_TOTAL,
                        account_type=C.TYPE_ASSET, parent_id=parent_id)


def _sub(parent_id: int, code="101001", title="موجودی نقد"):
    return AccountInput(code=code, title_fa=title, level=C.LEVEL_SUBSIDIARY,
                        account_type=C.TYPE_ASSET, parent_id=parent_id)


# --------------------------------------------------------------------- creation
def test_create_hierarchy_and_nature_defaults(services, admin):
    group = services.accounts.create(admin, _group())
    assert group.level_fa == "گروه حساب"
    total = services.accounts.create(admin, _total(group.id))
    sub = services.accounts.create(admin, _sub(total.id))
    assert sub.level_fa == "حساب معین"
    assert sub.nature == C.NATURE_DEBIT  # assets are debit by default
    assert sub.statement_section == "current_assets"
    assert sub.parent_title == "دارایی جاری"
    assert sub.display == "101001 — موجودی نقد"


def test_code_length_follows_the_configured_mask(services, admin):
    group = services.accounts.create(admin, _group())
    with pytest.raises(ValidationError) as exc:
        services.accounts.create(admin, AccountInput(
            code="12", title_fa="کل نامعتبر", level=C.LEVEL_TOTAL,
            account_type=C.TYPE_ASSET, parent_id=group.id))
    assert "3 رقم" in str(exc.value)


def test_child_code_must_start_with_parent(services, admin):
    group = services.accounts.create(admin, _group())
    with pytest.raises(ValidationError):
        services.accounts.create(admin, AccountInput(
            code="999", title_fa="کل نامعتبر", level=C.LEVEL_TOTAL,
            account_type=C.TYPE_ASSET, parent_id=group.id))


def test_duplicate_code_is_rejected(services, admin):
    services.accounts.create(admin, _group())
    with pytest.raises(ConflictError):
        services.accounts.create(admin, _group(title="دارایی تکراری"))


def test_account_requires_parent_of_correct_level(services, admin):
    group = services.accounts.create(admin, _group())
    total = services.accounts.create(admin, _total(group.id))
    with pytest.raises(ValidationError) as exc:
        services.accounts.create(admin, AccountInput(
            code="101001", title_fa="معین نامعتبر", level=C.LEVEL_SUBSIDIARY,
            account_type=C.TYPE_ASSET, parent_id=group.id))
    assert "حساب کل" in str(exc.value)
    # a group may not have a parent
    with pytest.raises(ValidationError):
        services.accounts.create(admin, AccountInput(
            code="2", title_fa="گروه با والد", level=C.LEVEL_GROUP,
            account_type=C.TYPE_ASSET, parent_id=total.id))


def test_nature_must_match_account_type(services, admin):
    with pytest.raises(ValidationError):
        services.accounts.create(admin, AccountInput(
            code="5", title_fa="هزینه‌ها", level=C.LEVEL_GROUP,
            account_type=C.TYPE_EXPENSE, nature=C.NATURE_CREDIT))


def test_statement_section_must_match_type(services, admin):
    with pytest.raises(ValidationError):
        services.accounts.create(admin, AccountInput(
            code="4", title_fa="درآمدها", level=C.LEVEL_GROUP,
            account_type=C.TYPE_REVENUE, statement_section="current_assets"))


# ---------------------------------------------------------------------- safety
def test_delete_is_blocked_for_accounts_with_children_or_history(services, admin, chart):
    accounts, _period = chart
    cash = accounts["101001"]
    parent = next(row for row in services.accounts.list_accounts(admin, level="total")
                  if row.code == cash.code[:3])
    with pytest.raises(ValidationError):
        services.accounts.delete(admin, parent.id)

    from pars_erp.services.journals_service import JournalInput, JournalLineInput
    from decimal import Decimal

    capital = accounts["301001"]
    journal = services.journals.create(admin, JournalInput(
        entry_date=_dt.date(2026, 4, 1), title_fa="سرمایه اولیه",
        lines=[JournalLineInput(account_id=cash.id, debit=Decimal("1000000")),
               JournalLineInput(account_id=capital.id, credit=Decimal("1000000"))]))
    assert journal.total_debit == Decimal("1000000.0000")
    with pytest.raises(ValidationError) as exc:
        services.accounts.delete(admin, cash.id)
    assert "غیرفعال" in str(exc.value)
    assert services.accounts.usage_count(admin, cash.id) == 1


def test_unused_leaf_can_be_deleted(services, admin):
    group = services.accounts.create(admin, _group())
    total = services.accounts.create(admin, _total(group.id))
    sub = services.accounts.create(admin, _sub(total.id))
    services.accounts.delete(admin, sub.id)
    with pytest.raises(NotFoundError):
        services.accounts.get(admin, sub.id)


def test_deactivation_requires_children_inactive(services, admin, chart):
    accounts, _ = chart
    cash = accounts["101001"]
    total = next(row for row in services.accounts.list_accounts(admin, level="total")
                 if row.code == cash.code[:3])
    with pytest.raises(ValidationError):
        services.accounts.set_active(admin, total.id, False)
    deactivated = services.accounts.set_active(admin, cash.id, False)
    assert deactivated.is_active is False
    assert deactivated.status_fa == "غیرفعال"


def test_update_keeps_tree_consistent(services, admin):
    group = services.accounts.create(admin, _group())
    total = services.accounts.create(admin, _total(group.id))
    sub = services.accounts.create(admin, _sub(total.id))
    updated = services.accounts.update(admin, sub.id, AccountInput(
        code="101001", title_fa="موجودی نقد و بانک", level=C.LEVEL_SUBSIDIARY,
        account_type=C.TYPE_ASSET, parent_id=total.id))
    assert updated.title_fa == "موجودی نقد و بانک"
    with pytest.raises(ValidationError):
        services.accounts.update(admin, sub.id, AccountInput(
            code="101001", title_fa="سطح نامعتبر", level=C.LEVEL_TOTAL,
            account_type=C.TYPE_ASSET, parent_id=total.id))


def test_tree_and_next_code_suggestion(services, admin, chart):
    tree = services.accounts.tree(admin)
    assert tree and tree[0].row.code == "1"
    assert tree[0].children, "گروه باید زیرمجموعه داشته باشد"
    accounts, _ = chart
    cash = accounts["101001"]
    suggested = services.accounts.next_suggested_code(admin, cash.parent_id,
                                                      C.LEVEL_SUBSIDIARY)
    assert suggested.startswith(cash.code[:3])
    assert len(suggested) == 6
    assert suggested != cash.code


def test_statement_mapping_can_be_changed(services, admin, chart):
    accounts, _ = chart
    account = services.accounts.set_statement_section(admin, accounts["101004"].id,
                                                      "non_current_assets")
    assert account.statement_section == "non_current_assets"
    with pytest.raises(ValidationError):
        services.accounts.set_statement_section(admin, accounts["101004"].id, "revenue")


# ---------------------------------------------------------------------- details
def test_detail_accounts_attach_to_subsidiary_accounts(services, admin, chart):
    accounts, _ = chart
    detail = services.parties.create(admin, DetailInput(
        code="1001", name="شرکت مشتری الف", kind=C.DETAIL_CUSTOMER,
        account_id=accounts["101002"].id, phone="02112345678"))
    assert detail.kind_fa == "مشتری"
    assert detail.account_label.startswith("101002")
    assert services.parties.choices(admin, accounts["101002"].id)[0][0] == detail.id

    total = next(row for row in services.accounts.list_accounts(admin, level="total")
                 if row.code == "101")
    with pytest.raises(ValidationError):
        services.parties.create(admin, DetailInput(
            code="1002", name="مشتری نامعتبر", kind=C.DETAIL_CUSTOMER,
            account_id=total.id))


def test_detail_codes_are_unique_and_validated(services, admin, chart):
    accounts, _ = chart
    services.parties.create(admin, DetailInput(
        code="2001", name="تأمین‌کننده الف", kind=C.DETAIL_SUPPLIER,
        account_id=accounts["201001"].id))
    with pytest.raises(ConflictError):
        services.parties.create(admin, DetailInput(
            code="2001", name="تأمین‌کننده تکراری", kind=C.DETAIL_SUPPLIER))
    with pytest.raises(ValidationError):
        services.parties.create(admin, DetailInput(
            code="abc", name="کد نامعتبر", kind=C.DETAIL_OTHER))
    with pytest.raises(ValidationError):
        services.parties.create(admin, DetailInput(
            code="2002", name="نوع نامعتبر", kind="unknown-kind"))


def test_detail_used_in_journal_cannot_be_deleted(services, admin, chart):
    from decimal import Decimal

    from pars_erp.services.journals_service import JournalInput, JournalLineInput

    accounts, _ = chart
    detail = services.parties.create(admin, DetailInput(
        code="3001", name="مشتری نمونه", kind=C.DETAIL_CUSTOMER,
        account_id=accounts["101002"].id))
    services.journals.create(admin, JournalInput(
        entry_date=_dt.date(2026, 4, 2), title_fa="فروش نسیه",
        lines=[JournalLineInput(account_id=accounts["101002"].id, debit=Decimal("500"),
                                detail_id=detail.id),
               JournalLineInput(account_id=accounts["401001"].id, credit=Decimal("500"))]))
    with pytest.raises(ValidationError):
        services.parties.delete(admin, detail.id)


# ------------------------------------------------------------------ permissions
def test_account_permissions_are_enforced_in_the_service(services, admin, accountant, chart):
    accounts, _ = chart
    # an accountant may create accounts and read everything ...
    created = services.accounts.create(accountant, _group(code="9", title="گروه جدید"))
    assert created.code == "9"
    services.accounts.list_accounts(accountant)
    # ... but may not delete accounts nor change role-level settings
    with pytest.raises(PermissionDeniedError):
        services.accounts.delete(accountant, accounts["101003"].id)
    with pytest.raises(PermissionDeniedError):
        services.accounts.set_active(accountant, accounts["101004"].id, False)


def test_standard_chart_can_be_loaded_once(services, admin):
    first = services.accounting.load_standard_chart(admin)
    assert first.created_accounts == len(__import__(
        "pars_erp.services.accounting_setup_service", fromlist=["STANDARD_CHART"]
    ).STANDARD_CHART)
    second = services.accounting.load_standard_chart(admin)
    assert second.created_accounts == 0
    assert second.skipped_accounts == first.created_accounts
    rows = services.accounts.list_accounts(admin)
    assert {row.level for row in rows} == set(C.ACCOUNT_LEVELS)


def test_accounting_dashboard_reports_real_state(services, admin):
    empty = services.accounting.dashboard(admin)
    assert empty.is_ready is False
    assert empty.accounts_total == 0
    assert any("کدینگ" in hint for hint in empty.hints)
    services.accounting.ensure_basic_setup(admin)
    ready = services.accounting.dashboard(admin)
    assert ready.is_ready is True
    assert ready.accounts_total > 0
    assert ready.periods_total == 1
    assert ready.active_period.startswith("سال مالی")
