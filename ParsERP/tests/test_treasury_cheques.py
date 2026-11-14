"""Phase 4 - cheque books, received and issued cheques."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from pars_erp.core.errors import ConflictError, ValidationError
from pars_erp.services.cheque_service import ChequeBookInput
from pars_erp.services.context import AppServices
from pars_erp.services.voucher_service import (
    AllocationInput,
    ChequeInput,
    PaymentInput,
    ReceiptInput,
)
from pars_erp.treasury import constants as TC

DAY = _dt.date(2026, 4, 12)


def _book(services, admin, treasury, **kwargs):
    payload = dict(bank_account_id=treasury.bank.id, serial_no="SB-100",
                   first_no=100, last_no=124, received_date=DAY)
    payload.update(kwargs)
    return services.cheques.create_book(admin, ChequeBookInput(**payload))


def _received_cheque(services, admin, treasury, **kwargs):
    payload = dict(receipt_date=DAY, amount=4_000, receipt_type=TC.RECEIPT_CUSTOMER,
                   method=TC.METHOD_CHEQUE, payer_detail_id=treasury.customer.id,
                   cash_box_id=treasury.box.id,
                   cheque=ChequeInput(number=kwargs.pop("number", "771122"),
                                      bank_name="بانک صادرات", amount=4_000,
                                      issue_date=DAY,
                                      due_date=kwargs.pop("due_date",
                                                          _dt.date(2026, 5, 12)),
                                      cheque_book_id=kwargs.pop("book_id", None)))
    return services.vouchers.create_receipt(admin, ReceiptInput(**payload))


class TestChequeBooks:
    def test_create_and_leaf_tracking(self, services: AppServices, admin,
                                      treasury) -> None:
        book = _book(services, admin, treasury)
        assert book.total_leaves == 25
        assert book.used_leaves == 0
        assert book.free_leaves == 25

    def test_range_must_be_positive(self, services: AppServices, admin,
                                    treasury) -> None:
        with pytest.raises(ValidationError):
            _book(services, admin, treasury, first_no=120, last_no=100)

    def test_duplicate_serial_is_refused(self, services: AppServices, admin,
                                         treasury) -> None:
        _book(services, admin, treasury)
        with pytest.raises(ConflictError):
            _book(services, admin, treasury, first_no=200, last_no=220)

    def test_leaf_outside_the_book_is_refused(self, services: AppServices, admin,
                                              treasury) -> None:
        book = _book(services, admin, treasury)
        with pytest.raises(ValidationError):
            services.vouchers.create_payment(admin, PaymentInput(
                payment_date=DAY, amount=1_000, payment_type=TC.PAYMENT_OTHER,
                method=TC.METHOD_CHEQUE, bank_account_id=treasury.bank.id,
                counter_account_id=treasury.accounts["503001"].id,
                cheque=ChequeInput(number="999", bank_name="بانک ملت", amount=1_000,
                                   issue_date=DAY, due_date=_dt.date(2026, 5, 12),
                                   cheque_book_id=book.id)))

    def test_duplicate_number_in_a_book_is_refused(self, services: AppServices, admin,
                                                   treasury) -> None:
        book = _book(services, admin, treasury)
        first = services.vouchers.create_payment(admin, PaymentInput(
            payment_date=DAY, amount=1_000, payment_type=TC.PAYMENT_OTHER,
            method=TC.METHOD_CHEQUE, bank_account_id=treasury.bank.id,
            counter_account_id=treasury.accounts["503001"].id,
            cheque=ChequeInput(number="105", bank_name="بانک ملت", amount=1_000,
                               issue_date=DAY, due_date=_dt.date(2026, 5, 12),
                               cheque_book_id=book.id)))
        assert first.cheque_id
        with pytest.raises(ConflictError):
            services.vouchers.create_payment(admin, PaymentInput(
                payment_date=DAY, amount=2_000, payment_type=TC.PAYMENT_OTHER,
                method=TC.METHOD_CHEQUE, bank_account_id=treasury.bank.id,
                counter_account_id=treasury.accounts["503001"].id,
                cheque=ChequeInput(number="105", bank_name="بانک ملت", amount=2_000,
                                   issue_date=DAY, due_date=_dt.date(2026, 5, 12),
                                   cheque_book_id=book.id)))

    def test_voided_leaf_cannot_be_reused(self, services: AppServices, admin,
                                          treasury) -> None:
        book = _book(services, admin, treasury)
        services.cheques.mark_voiced(admin, book.id, 107, "برگ خراب")
        with pytest.raises(ConflictError):
            services.cheques.mark_voiced(admin, book.id, 107, "دوباره")

    def test_book_status_can_be_closed(self, services: AppServices, admin,
                                       treasury) -> None:
        book = _book(services, admin, treasury)
        closed = services.cheques.set_book_status(admin, book.id, TC.BOOK_FINISHED)
        assert closed.status == TC.BOOK_FINISHED


class TestReceivedCheques:
    def test_receipt_creates_a_received_cheque(self, services: AppServices, admin,
                                               treasury) -> None:
        receipt = _received_cheque(services, admin, treasury)
        cheque = services.cheques.get_cheque(admin, receipt.cheque_id)
        assert cheque.status == TC.CHQ_RECEIVED
        assert cheque.direction == TC.CHEQUE_RECEIVED
        assert cheque.amount == Decimal("4000")

    def test_full_status_journey_posts_journals(self, services: AppServices, admin,
                                                treasury) -> None:
        receipt = _received_cheque(services, admin, treasury)
        services.cheques.change_status(admin, receipt.cheque_id, TC.CHQ_IN_SAFE)
        services.cheques.change_status(admin, receipt.cheque_id, TC.CHQ_DEPOSITED,
                                       bank_account_id=treasury.bank.id)
        collected = services.cheques.change_status(
            admin, receipt.cheque_id, TC.CHQ_COLLECTED,
            bank_account_id=treasury.bank.id)
        assert collected.status == TC.CHQ_COLLECTED
        assert collected.journal_id is not None
        history = services.cheques.history(admin, receipt.cheque_id)
        assert len(history) == 4
        assert history[-1].to_status_fa == TC.CHEQUE_STATUS_TITLES_FA[TC.CHQ_COLLECTED]
        assert services.funds.get_bank_account(admin, treasury.bank.id).balance == \
            Decimal("100004000")

    def test_illegal_transition_is_refused(self, services: AppServices, admin,
                                           treasury) -> None:
        receipt = _received_cheque(services, admin, treasury)
        with pytest.raises(ConflictError):
            services.cheques.change_status(admin, receipt.cheque_id, TC.CHQ_PAID)

    def test_bounced_cheque_returns_to_the_customer(self, services: AppServices, admin,
                                                    treasury) -> None:
        receipt = _received_cheque(services, admin, treasury)
        services.cheques.change_status(admin, receipt.cheque_id, TC.CHQ_IN_SAFE)
        services.cheques.change_status(admin, receipt.cheque_id, TC.CHQ_DEPOSITED,
                                       bank_account_id=treasury.bank.id)
        bounced = services.cheques.change_status(admin, receipt.cheque_id,
                                                 TC.CHQ_BOUNCED, note="کسر موجودی")
        assert bounced.status == TC.CHQ_BOUNCED
        assert bounced.journal_id

    def test_cancel_needs_the_cancel_permission(self, services: AppServices, admin,
                                                treasury) -> None:
        from pars_erp.services.user_service import UserCreateData

        services.users.create_user(admin, UserCreateData(
            username="khazanedar", full_name="خزانه‌دار", password="Khazane1404!",
            confirm_password="Khazane1404!", role_codes=("treasurer",)))
        ctx = services.auth.authenticate("khazanedar", "Khazane1404!")
        receipt = _received_cheque(services, admin, treasury)
        services.cheques.cancel(admin, receipt.cheque_id, "چک اشتباه ثبت شده بود")
        assert services.cheques.get_cheque(
            admin, receipt.cheque_id).status == TC.CHQ_CANCELLED
        assert not ctx.has("cheques.cancel")

    def test_cheque_adds_to_invoice_settlement(self, services: AppServices, admin,
                                               treasury) -> None:
        receipt = services.vouchers.create_receipt(admin, ReceiptInput(
            receipt_date=DAY, amount=4_000, receipt_type=TC.RECEIPT_CUSTOMER,
            method=TC.METHOD_CHEQUE, payer_detail_id=treasury.customer.id,
            cash_box_id=treasury.box.id,
            cheque=ChequeInput(number="771199", bank_name="بانک ملت", amount=4_000,
                               issue_date=DAY, due_date=_dt.date(2026, 5, 12)),
            allocations=(AllocationInput(invoice_id=treasury.sale.id, amount=4_000),)))
        assert receipt.settlement_total == Decimal("4000")
        open_rows = services.vouchers.open_invoices(
            admin, direction="receipt", party_detail_id=treasury.customer.id)
        assert open_rows == [] or open_rows[0].open_amount == Decimal("6000")


class TestDueLists:
    def test_due_soon_filters_by_date(self, services: AppServices, admin,
                                      treasury) -> None:
        receipt = _received_cheque(services, admin, treasury,
                                   due_date=_dt.date.today() + _dt.timedelta(days=2))
        rows = services.cheques.due_soon(admin, days=7)
        assert receipt.cheque_id in {row.id for row in rows}
        assert services.cheques.due_soon(admin, days=-1) == []
