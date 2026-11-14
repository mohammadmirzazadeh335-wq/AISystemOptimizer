"""Phase-2 audit: two users, one database - does anything get counted twice?

These tests really run threads against the same SQLite database the other tests
use (``Database`` opens one session per operation, so the threads contend the way
two copies of the program would).
"""

from __future__ import annotations

import datetime as _dt
import threading
from decimal import Decimal

import pytest

from pars_erp.commerce import constants as CC
from pars_erp.db.models import Invoice, Receipt
from pars_erp.services.inventory_service import StockLineInput
from pars_erp.services.invoice_service import InvoiceInput, InvoiceLineInput
from pars_erp.services.journals_service import JournalInput, JournalLineInput
from pars_erp.services.voucher_service import ReceiptInput

D = Decimal
CASH = "101001"


def run_threads(count: int, target) -> list:
    """Run ``target(index)`` in ``count`` threads and return their results."""
    results: list = [None] * count
    errors: list = [None] * count
    barrier = threading.Barrier(count)

    def worker(index: int) -> None:
        barrier.wait()
        try:
            results[index] = target(index)
        except BaseException as exc:  # noqa: BLE001 - collected, not swallowed
            errors[index] = exc

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    return results, errors


class TestConcurrentWrites:
    def test_parallel_journals_get_unique_sequential_numbers(self, services, admin,
                                                             chart):
        accounts, _period = chart
        day = _dt.date(2026, 5, 7)

        def create(index: int):
            return services.journals.create(admin, JournalInput(
                entry_date=day, title_fa=f"سند هم‌زمان {index}",
                lines=[JournalLineInput(account_id=accounts[CASH].id, debit=D("1000")),
                       JournalLineInput(account_id=accounts["301001"].id,
                                        credit=D("1000"))]))

        results, errors = run_threads(8, create)
        assert all(error is None for error in errors), errors
        numbers = sorted(row.number for row in results)
        assert len(set(numbers)) == 8, f"duplicate document numbers: {numbers}"

    def test_only_one_of_two_simultaneous_sales_of_the_last_units_succeeds(
            self, services, admin, commerce):
        """One unit on the shelf; two sellers each promise it to a customer."""
        services.inventory.record_receipt(
            admin, warehouse_id=commerce.warehouse.id,
            doc_date=_dt.date(2026, 1, 5),
            lines=(StockLineInput(product_id=commerce.product.id, quantity=1,
                                  unit_cost=D("800")),))

        def sell(index: int):
            invoice = services.invoices.create(admin, InvoiceInput(
                kind=CC.INVOICE_SALE, invoice_date=_dt.date(2026, 4, 18),
                party_detail_id=commerce.customer.id,
                warehouse_id=commerce.warehouse.id,
                lines=(InvoiceLineInput(product_id=commerce.product.id, quantity=1,
                                        unit_price=D("1500")),)))
            return services.invoices.post(admin, invoice.id)

        results, errors = run_threads(2, sell)
        successes = [row for row, error in zip(results, errors) if error is None]
        assert len(successes) == 1, f"errors: {errors}"
        assert sum(1 for error in errors if error is not None) == 1
        # the loser was refused, and the shelf is empty - never negative
        stock = services.inventory.valuation(admin)["quantity"]
        assert stock == D("0")

    def test_a_retried_receipt_with_the_same_key_posts_one_document(self, services,
                                                                    admin, treasury):
        key = "retry-after-timeout-1"
        first = services.vouchers.create_receipt(admin, ReceiptInput(
            receipt_date=_dt.date(2026, 4, 21), amount=D("500000"),
            bank_account_id=treasury.bank.id, payer_detail_id=treasury.customer.id,
            description="دریافت با کلید تکرار", idempotency_key=key))
        second = services.vouchers.create_receipt(admin, ReceiptInput(
            receipt_date=_dt.date(2026, 4, 21), amount=D("500000"),
            bank_account_id=treasury.bank.id, payer_detail_id=treasury.customer.id,
            description="دریافت با کلید تکرار", idempotency_key=key))
        assert first.id == second.id, "a retry must return the first document"
        with services.db.session_scope() as session:
            from sqlalchemy import func, select
            count = session.scalar(
                select(func.count()).select_from(Receipt)
                .where(Receipt.idempotency_key == key))
        assert count == 1

    def test_a_retried_invoice_with_the_same_key_is_not_duplicated(self, services,
                                                                   admin, commerce):
        key = "invoice-retry-1"

        def create() -> int:
            row = services.invoices.create(admin, InvoiceInput(
                kind=CC.INVOICE_PURCHASE, invoice_date=_dt.date(2026, 4, 19),
                party_detail_id=commerce.supplier.id,
                warehouse_id=commerce.warehouse.id,
                lines=(InvoiceLineInput(product_id=commerce.product.id, quantity=2,
                                        unit_price=D("900")),),
                idempotency_key=key))
            return row.id

        first = create()
        second = create()
        assert first == second
        with services.db.session_scope() as session:
            from sqlalchemy import func, select
            assert session.scalar(
                select(func.count()).select_from(Invoice)
                .where(Invoice.idempotency_key == key)) == 1

    def test_two_parallel_receipts_with_one_key_produce_one_row(self, services, admin,
                                                                treasury):
        key = "parallel-receipt-key"

        def create(index: int):
            return services.vouchers.create_receipt(admin, ReceiptInput(
                receipt_date=_dt.date(2026, 4, 22), amount=D("250000"),
                bank_account_id=treasury.bank.id,
                payer_detail_id=treasury.customer.id,
                description=f"موازی {index}", idempotency_key=key))

        results, errors = run_threads(2, create)
        assert all(error is None for error in errors), errors
        assert results[0].id == results[1].id
        with services.db.session_scope() as session:
            from sqlalchemy import func, select
            assert session.scalar(
                select(func.count()).select_from(Receipt)
                .where(Receipt.idempotency_key == key)) == 1


class TestNoDoubleEffects:
    def test_posting_the_same_invoice_twice_is_refused(self, services, admin, commerce):
        services.inventory.record_receipt(
            admin, warehouse_id=commerce.warehouse.id,
            doc_date=_dt.date(2026, 1, 5),
            lines=(StockLineInput(product_id=commerce.product.id, quantity=10,
                                  unit_cost=D("800")),))
        invoice = services.invoices.create(admin, InvoiceInput(
            kind=CC.INVOICE_SALE, invoice_date=_dt.date(2026, 4, 23),
            party_detail_id=commerce.customer.id,
            warehouse_id=commerce.warehouse.id,
            lines=(InvoiceLineInput(product_id=commerce.product.id, quantity=2,
                                    unit_price=D("1500")),)))
        first = services.invoices.post(admin, invoice.id)
        with pytest.raises(Exception):
            services.invoices.post(admin, invoice.id)

        from sqlalchemy import func, select
        from pars_erp.db.models import Journal, StockDocument
        with services.db.session_scope() as session:
            assert session.scalar(
                select(func.count()).select_from(Journal)
                .where(Journal.source_kind == "invoice",
                       Journal.source_id == invoice.id)) == 1
            assert session.scalar(
                select(func.count()).select_from(StockDocument)
                .where(StockDocument.source_kind == "invoice",
                       StockDocument.source_id == invoice.id)) == 1
        assert first.journal_id

    def test_a_receipt_cannot_be_posted_twice(self, services, admin, treasury):
        receipt = services.vouchers.create_receipt(admin, ReceiptInput(
            receipt_date=_dt.date(2026, 4, 24), amount=D("100000"),
            bank_account_id=treasury.bank.id, payer_detail_id=treasury.customer.id))
        services.vouchers.approve_receipt(admin, receipt.id)
        services.vouchers.post_receipt(admin, receipt.id)
        journal_id = None
        from sqlalchemy import func, select
        from pars_erp.db.models import Journal
        with services.db.session_scope() as session:
            journal_id = session.scalar(
                select(Journal.id).where(Journal.source_kind == "receipt",
                                         Journal.source_id == receipt.id))
        again = services.vouchers.post_receipt(admin, receipt.id)
        assert again.status == "posted"
        with services.db.session_scope() as session:
            assert session.scalar(
                select(func.count()).select_from(Journal)
                .where(Journal.source_kind == "receipt",
                       Journal.source_id == receipt.id)) == 1
        assert journal_id
