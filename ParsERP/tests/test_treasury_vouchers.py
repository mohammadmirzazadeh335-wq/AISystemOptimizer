"""Phase 4 - receipts, payments, settlement and fund transfers."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from pars_erp.core.errors import ConflictError, PermissionDeniedError, ValidationError
from pars_erp.services.context import AppServices
from pars_erp.services.voucher_service import (
    AllocationInput,
    ChequeInput,
    PaymentInput,
    ReceiptInput,
    TransferInput,
)
from pars_erp.treasury import constants as TC

DAY = _dt.date(2026, 4, 10)


def _receipt(services, admin, treasury, **kwargs) -> object:
    payload = dict(receipt_date=DAY, amount=4_000, receipt_type=TC.RECEIPT_CUSTOMER,
                   method=TC.METHOD_CASH, cash_box_id=treasury.box.id,
                   payer_detail_id=treasury.customer.id)
    payload.update(kwargs)
    return services.vouchers.create_receipt(admin, ReceiptInput(**payload))


def _payment(services, admin, treasury, **kwargs) -> object:
    payload = dict(payment_date=DAY, amount=5_000, payment_type=TC.PAYMENT_SUPPLIER,
                   method=TC.METHOD_TRANSFER, bank_account_id=treasury.bank.id,
                   payee_detail_id=treasury.supplier.id)
    payload.update(kwargs)
    return services.vouchers.create_payment(admin, PaymentInput(**payload))


def _journal_lines(services, journal_id: int) -> list[tuple[str, Decimal, Decimal]]:
    from pars_erp.db.models import Account, JournalLine

    with services.db.session_scope() as session:
        rows = session.execute(JournalLine.__table__.select().where(
            JournalLine.journal_id == journal_id)).all()
        return [(session.get(Account, row.account_id).code, Decimal(row.debit),
                 Decimal(row.credit)) for row in rows]


class TestReceiptLifecycle:
    def test_draft_to_posted_posts_one_balanced_journal(self, services: AppServices,
                                                        admin, treasury) -> None:
        receipt = _receipt(services, admin, treasury)
        assert receipt.status == TC.STATUS_DRAFT
        assert receipt.journal_id is None
        approved = services.vouchers.approve_receipt(admin, receipt.id)
        assert approved.status == TC.STATUS_APPROVED
        posted = services.vouchers.post_receipt(admin, receipt.id)
        assert posted.status == TC.STATUS_POSTED
        lines = _journal_lines(services, posted.journal_id)
        assert sum(line[1] for line in lines) == sum(line[2] for line in lines) == 4000
        assert any(code == "101005" and debit == 4000 for code, debit, _ in lines)
        assert any(code == "101002" for code, _, _ in lines)

    def test_posting_twice_is_idempotent(self, services: AppServices, admin,
                                        treasury) -> None:
        receipt = _receipt(services, admin, treasury)
        services.vouchers.approve_receipt(admin, receipt.id)
        first = services.vouchers.post_receipt(admin, receipt.id)
        second = services.vouchers.post_receipt(admin, receipt.id)
        assert first.journal_id == second.journal_id
        from pars_erp.db.models import Journal

        with services.db.session_scope() as session:
            count = session.query(Journal).filter(
                Journal.idempotency_key == f"receipt:{receipt.id}:journal").count()
        assert count == 1

    def test_cannot_post_a_draft(self, services: AppServices, admin, treasury) -> None:
        receipt = _receipt(services, admin, treasury)
        with pytest.raises(ConflictError):
            services.vouchers.post_receipt(admin, receipt.id)

    def test_approved_document_is_frozen(self, services: AppServices, admin,
                                         treasury) -> None:
        receipt = _receipt(services, admin, treasury)
        services.vouchers.approve_receipt(admin, receipt.id)
        with pytest.raises(ConflictError):
            services.vouchers.update_receipt(admin, receipt.id, ReceiptInput(
                receipt_date=DAY, amount=1_000, cash_box_id=treasury.box.id))

    def test_void_posts_mirror_and_keeps_original(self, services: AppServices, admin,
                                                  treasury) -> None:
        receipt = _receipt(services, admin, treasury)
        services.vouchers.approve_receipt(admin, receipt.id)
        posted = services.vouchers.post_receipt(admin, receipt.id)
        original = _journal_lines(services, posted.journal_id)
        voided = services.vouchers.void_receipt(admin, receipt.id, "اشتباه در ثبت مبلغ")
        assert voided.status == TC.STATUS_VOID
        assert voided.journal_id != posted.journal_id
        mirror = _journal_lines(services, voided.journal_id)
        assert [(code, credit, debit) for code, debit, credit in original] == mirror
        assert treasury.accounts["101005"].id  # the fund account still exists
        assert services.funds.balances(admin)["cash_total"] == Decimal("11000000")

    def test_void_requires_reason(self, services: AppServices, admin, treasury) -> None:
        receipt = _receipt(services, admin, treasury)
        with pytest.raises(ValidationError):
            services.vouchers.void_receipt(admin, receipt.id, "خطا")

    def test_numbers_are_sequential_and_unique(self, services: AppServices, admin,
                                               treasury) -> None:
        first = _receipt(services, admin, treasury)
        second = _receipt(services, admin, treasury)
        assert first.number != second.number
        assert first.number.startswith("RCV-")
        assert services.vouchers.next_receipt_number(admin, DAY) != second.number


class TestPaymentRules:
    def test_supplier_payment_settles_the_invoice(self, services: AppServices, admin,
                                                  treasury) -> None:
        payment = _payment(services, admin, treasury, amount=4_000,
                           allocations=(AllocationInput(invoice_id=treasury.purchase.id,
                                                         amount=4_000),))
        services.vouchers.approve_payment(admin, payment.id)
        posted = services.vouchers.post_payment(admin, payment.id)
        assert posted.settlement_total == Decimal("4000")
        rows = services.vouchers.allocations_of(admin, "payment", payment.id)
        assert rows[0]["invoice_id"] == treasury.purchase.id
        lines = _journal_lines(services, posted.journal_id)
        assert any(code == "201001" for code, _, _ in lines)

    def test_over_settlement_is_refused(self, services: AppServices, admin,
                                        treasury) -> None:
        with pytest.raises(ValidationError):
            _payment(services, admin, treasury, amount=20_000,
                     allocations=(AllocationInput(invoice_id=treasury.purchase.id,
                                                  amount=20_000),))

    def test_settlement_of_two_invoices(self, services: AppServices, admin,
                                        treasury) -> None:
        receipt = _receipt(
            services, admin, treasury, amount=6_000,
            allocations=(AllocationInput(invoice_id=treasury.sale.id, amount=6_000),))
        assert receipt.settlement_total == Decimal("6000")
        open_rows = services.vouchers.open_invoices(admin, direction="receipt")
        assert open_rows[0].open_amount == Decimal("4000")
        assert open_rows[0].is_partial is True

    def test_expense_payment_uses_the_chosen_expense_account(
            self, services: AppServices, admin, treasury) -> None:
        payment = _payment(services, admin, treasury, amount=1_500_000,
                           payment_type=TC.PAYMENT_EXPENSE,
                           payee_detail_id=None,
                           counter_account_id=treasury.accounts["503001"].id)
        services.vouchers.approve_payment(admin, payment.id)
        posted = services.vouchers.post_payment(admin, payment.id)
        lines = _journal_lines(services, posted.journal_id)
        codes = {code for code, _, _ in lines}
        assert "503001" in codes and "101006" in codes

    def test_payment_cannot_overdraw_the_fund(self, services: AppServices, admin,
                                              treasury) -> None:
        with pytest.raises(ValidationError):
            _payment(services, admin, treasury, amount=10_000_000,
                     payment_type=TC.PAYMENT_OTHER, payee_detail_id=None,
                     counter_account_id=treasury.accounts["503001"].id,
                     cash_box_id=treasury.small_box.id, method=TC.METHOD_CASH,
                     bank_account_id=None)

    def test_cheque_payment_creates_an_issued_cheque(self, services: AppServices,
                                                     admin, treasury) -> None:
        payment = _payment(services, admin, treasury, amount=3_000,
                           method=TC.METHOD_CHEQUE, bank_account_id=treasury.bank.id,
                           cheque=ChequeInput(number="556677", bank_name="بانک ملت",
                                              amount=3_000, issue_date=DAY,
                                              due_date=_dt.date(2026, 5, 10)))
        assert payment.cheque_id is not None
        cheque = services.cheques.get_cheque(admin, payment.cheque_id)
        assert cheque.status == TC.CHQ_ISSUED
        assert cheque.direction == TC.CHEQUE_ISSUED


class TestPermissions:
    def test_treasurer_cannot_approve(self, services: AppServices, admin,
                                      treasury) -> None:
        from pars_erp.services.user_service import UserCreateData

        services.users.create_user(admin, UserCreateData(
            username="khazanedar", full_name="خزانه‌دار", password="Khazane1404!",
            confirm_password="Khazane1404!", role_codes=("treasurer",)))
        ctx = services.auth.authenticate("khazanedar", "Khazane1404!")
        receipt = _receipt(services, admin, treasury)
        with pytest.raises(PermissionDeniedError):
            services.vouchers.approve_receipt(ctx, receipt.id)

    def test_viewer_can_read_but_not_write(self, services: AppServices, admin,
                                           treasury) -> None:
        from pars_erp.services.user_service import UserCreateData

        services.users.create_user(admin, UserCreateData(
            username="nazer", full_name="ناظر", password="Negahban1404!",
            confirm_password="Negahban1404!", role_codes=("viewer",)))
        ctx = services.auth.authenticate("nazer", "Negahban1404!")
        _receipt(services, admin, treasury)
        assert services.vouchers.list_receipts(ctx)
        with pytest.raises(PermissionDeniedError):
            _receipt(services, ctx, treasury)


class TestTransfers:
    def test_bank_to_cash_box_with_fee(self, services: AppServices, admin,
                                       treasury) -> None:
        transfer = services.vouchers.create_transfer(admin, TransferInput(
            transfer_date=DAY, amount=2_000_000, from_bank_account_id=treasury.bank.id,
            to_cash_box_id=treasury.box.id, fee=5_000))
        posted = services.vouchers.post_transfer(admin, transfer.id)
        assert posted.status == TC.STATUS_POSTED
        lines = _journal_lines(services, posted.journal_id)
        assert sum(line[1] for line in lines) == sum(line[2] for line in lines)
        assert any(code == "502004" and debit == 5000 for code, debit, _ in lines)
        assert services.funds.get_cash_box(admin, treasury.box.id).balance == \
            Decimal("12000000")
        assert services.funds.get_bank_account(admin, treasury.bank.id).balance == \
            Decimal("97995000")

    def test_cash_box_to_cash_box(self, services: AppServices, admin, treasury) -> None:
        transfer = services.vouchers.create_transfer(admin, TransferInput(
            transfer_date=DAY, amount=500_000, from_cash_box_id=treasury.box.id,
            to_cash_box_id=treasury.small_box.id))
        services.vouchers.post_transfer(admin, transfer.id)
        assert services.funds.get_cash_box(admin, treasury.small_box.id).balance == \
            Decimal("1500000")
        assert services.funds.get_cash_box(admin, treasury.box.id).balance == \
            Decimal("9500000")

    def test_transfer_needs_two_different_funds(self, services: AppServices, admin,
                                                treasury) -> None:
        with pytest.raises(ValidationError):
            services.vouchers.create_transfer(admin, TransferInput(
                transfer_date=DAY, amount=1_000, from_cash_box_id=treasury.box.id,
                to_cash_box_id=treasury.box.id))

    def test_transfer_cannot_overdraw(self, services: AppServices, admin,
                                      treasury) -> None:
        with pytest.raises(ValidationError):
            services.vouchers.create_transfer(admin, TransferInput(
                transfer_date=DAY, amount=99_000_000,
                from_cash_box_id=treasury.small_box.id,
                to_bank_account_id=treasury.bank.id))


class TestCurrency:
    def test_foreign_currency_keeps_both_amounts(self, services: AppServices, admin,
                                                 treasury) -> None:
        receipt = _receipt(services, admin, treasury, amount=100, currency_code="USD",
                           exchange_rate=600_000)
        assert receipt.amount == Decimal("100")
        assert receipt.base_amount == Decimal("60000000")

    def test_rate_must_be_positive(self, services: AppServices, admin, treasury) -> None:
        with pytest.raises(ValidationError):
            _receipt(services, admin, treasury, currency_code="USD", exchange_rate=0)
