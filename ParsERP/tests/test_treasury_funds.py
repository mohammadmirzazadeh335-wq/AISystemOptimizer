"""Phase 4 - bank accounts and cash boxes."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from pars_erp.core.errors import ConflictError, PermissionDeniedError, ValidationError
from pars_erp.services.context import AppServices
from pars_erp.services.funds_service import BankAccountInput, CashBoxInput
from pars_erp.services.user_service import UserCreateData


class TestBankAccounts:
    def test_create_and_list(self, services: AppServices, admin, treasury) -> None:
        rows = services.funds.list_bank_accounts(admin)
        assert [row.code for row in rows] == ["BNK-1"]
        row = rows[0]
        assert row.bank_name == "بانک ملت"
        assert row.balance == Decimal("100000000")
        assert row.account_label.startswith("101006")

    def test_duplicate_account_number_per_bank_is_refused(
            self, services: AppServices, admin, treasury) -> None:
        with pytest.raises(ConflictError):
            services.funds.create_bank_account(admin, BankAccountInput(
                code="BNK-2", bank_name="بانک ملت", account_number="1234567890"))

    def test_same_number_in_a_different_bank_is_allowed(
            self, services: AppServices, admin, treasury) -> None:
        row = services.funds.create_bank_account(admin, BankAccountInput(
            code="BNK-3", bank_name="بانک صادرات", account_number="1234567890"))
        assert row.id != treasury.bank.id

    def test_account_must_be_a_subsidiary_account(
            self, services: AppServices, admin, treasury) -> None:
        group = services.accounts.list_accounts(admin, level="total")[0]
        with pytest.raises(ValidationError):
            services.funds.create_bank_account(admin, BankAccountInput(
                code="BNK-9", bank_name="بانک", account_number="9",
                account_id=group.id))

    def test_one_ledger_account_cannot_back_two_funds(
            self, services: AppServices, admin, treasury) -> None:
        with pytest.raises(ConflictError):
            services.funds.create_bank_account(admin, BankAccountInput(
                code="BNK-5", bank_name="بانک تجارت", account_number="5555",
                account_id=treasury.bank.account_id))

    def test_iban_length_is_validated(self, services: AppServices, admin, treasury) -> None:
        with pytest.raises(ValidationError):
            services.funds.create_bank_account(admin, BankAccountInput(
                code="BNK-4", bank_name="بانک", account_number="4444", iban="IR12"))

    def test_deactivate_keeps_history(self, services: AppServices, admin, treasury) -> None:
        services.funds.set_bank_account_active(admin, treasury.bank.id, False)
        assert services.funds.get_bank_account(admin, treasury.bank.id).is_active is False
        assert services.funds.list_bank_accounts(admin, active=True) == []


class TestCashBoxes:
    def test_each_box_gets_its_own_ledger_account(self, services: AppServices, admin,
                                                 treasury) -> None:
        rows = services.funds.list_cash_boxes(admin)
        assert len({row.account_id for row in rows}) == 2

    def test_multiple_boxes_per_account(self, services: AppServices, admin, treasury) -> None:
        rows = services.funds.list_cash_boxes(admin)
        assert len(rows) == 2
        assert {row.code for row in rows} == {"CASH-1", "CASH-2"}

    def test_balances(self, services: AppServices, admin, treasury) -> None:
        balances = services.funds.balances(admin)
        assert balances["cash_total"] == Decimal("11000000")
        assert balances["bank_total"] == Decimal("100000000")

    def test_duplicate_code_is_refused(self, services: AppServices, admin,
                                       treasury) -> None:
        with pytest.raises(ConflictError):
            services.funds.create_cash_box(admin, CashBoxInput(
                code="CASH-1", title_fa="صندوق تکراری",
                account_id=treasury.accounts["101005"].id))

    def test_user_access_restriction(self, services: AppServices, admin,
                                     treasury) -> None:
        services.users.create_user(admin, UserCreateData(
            username="sandogh", full_name="صندوق‌دار", password="Kassadari1404!",
            confirm_password="Kassadari1404!", role_codes=("treasurer",)))
        ctx = services.auth.authenticate("sandogh", "Kassadari1404!")
        # box 1 is restricted to the administrator, box 2 stays open to everybody
        services.funds.set_cash_box_users(admin, treasury.box.id, [admin.user_id])
        allowed = services.funds.list_cash_boxes(ctx)
        assert [row.id for row in allowed] == [treasury.small_box.id]
        with services.db.session_scope() as session:
            from pars_erp.db.models import CashBox

            with pytest.raises(ValidationError):
                services.funds.assert_cash_box_allowed(
                    session, ctx, session.get(CashBox, treasury.box.id))
        # the administrator always sees every box
        assert len(services.funds.list_cash_boxes(admin)) == 2
        services.funds.set_cash_box_users(admin, treasury.box.id, [ctx.user_id])
        assert [row.id for row in services.funds.list_cash_boxes(ctx)] == \
            [treasury.box.id, treasury.small_box.id]

    def test_balances_hidden_without_permission(self, services: AppServices, admin,
                                                treasury) -> None:
        services.users.create_user(admin, UserCreateData(
            username="anbardar", full_name="انباردار", password="Anbar1404!",
            confirm_password="Anbar1404!", role_codes=("storekeeper",)))
        ctx = services.auth.authenticate("anbardar", "Anbar1404!")
        with pytest.raises(PermissionDeniedError):
            services.funds.balances(ctx)


class TestFundMovements:
    def test_statement_starts_with_opening_balance(self, services: AppServices, admin,
                                                   treasury) -> None:
        rows = services.funds.fund_movements(admin, cash_box_id=treasury.box.id)
        assert rows[0].kind == "opening"
        assert rows[0].balance == Decimal("10000000")

    def test_statement_includes_posted_receipt(self, services: AppServices, admin,
                                               treasury) -> None:
        from pars_erp.services.voucher_service import ReceiptInput
        from pars_erp.treasury import constants as TC

        receipt = services.vouchers.create_receipt(admin, ReceiptInput(
            receipt_date=_dt.date(2026, 4, 10), amount=250_000,
            receipt_type=TC.RECEIPT_OTHER, method=TC.METHOD_CASH,
            cash_box_id=treasury.box.id,
            counter_account_id=treasury.accounts["503001"].id))
        services.vouchers.approve_receipt(admin, receipt.id)
        services.vouchers.post_receipt(admin, receipt.id)
        rows = services.funds.fund_movements(admin, cash_box_id=treasury.box.id)
        assert rows[-1].amount_in == Decimal("250000")
        assert rows[-1].balance == Decimal("10250000")
        assert services.funds.get_cash_box(admin, treasury.box.id).balance == \
            Decimal("10250000")

    def test_date_filter(self, services: AppServices, admin, treasury) -> None:
        rows = services.funds.fund_movements(
            admin, cash_box_id=treasury.box.id,
            date_from=_dt.date(2030, 1, 1), date_to=_dt.date(2030, 12, 31))
        assert [row.kind for row in rows] == ["opening"]
