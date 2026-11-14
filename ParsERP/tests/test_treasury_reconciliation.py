"""Phase 4 - bank statement import, matching and discrepancy handling."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal
from pathlib import Path

import pytest

from pars_erp.core.errors import ValidationError
from pars_erp.services.context import AppServices
from pars_erp.services.reconciliation_service import StatementLineInput
from pars_erp.services.voucher_service import PaymentInput, ReceiptInput
from pars_erp.treasury import constants as TC

DAY = _dt.date(2026, 4, 15)


def _posted_receipt(services, admin, treasury, amount=4_000, day=DAY):
    receipt = services.vouchers.create_receipt(admin, ReceiptInput(
        receipt_date=day, amount=amount, receipt_type=TC.RECEIPT_OTHER,
        method=TC.METHOD_TRANSFER, bank_account_id=treasury.bank.id,
        counter_account_id=treasury.accounts["503001"].id))
    services.vouchers.approve_receipt(admin, receipt.id)
    return services.vouchers.post_receipt(admin, receipt.id)


def _posted_payment(services, admin, treasury, amount=1_500_000, day=DAY):
    payment = services.vouchers.create_payment(admin, PaymentInput(
        payment_date=day, amount=amount, payment_type=TC.PAYMENT_EXPENSE,
        method=TC.METHOD_TRANSFER, bank_account_id=treasury.bank.id,
        counter_account_id=treasury.accounts["503001"].id))
    services.vouchers.approve_payment(admin, payment.id)
    return services.vouchers.post_payment(admin, payment.id)


class TestStatements:
    def test_create_with_lines_and_totals(self, services: AppServices, admin,
                                          treasury) -> None:
        statement = services.reconciliation.create_statement(
            admin, bank_account_id=treasury.bank.id, statement_date=DAY,
            period_start=_dt.date(2026, 4, 1), period_end=DAY,
            opening_balance=100_000_000, closing_balance=98_500_000,
            lines=(StatementLineInput(tx_date=DAY, description="هزینه",
                                      amount_out=1_500_000),))
        assert statement.line_count == 1
        assert statement.unmatched_count == 1
        assert services.reconciliation.list_statements(admin)[0].id == statement.id

    def test_line_without_amount_is_rejected(self, services: AppServices, admin,
                                             treasury) -> None:
        with pytest.raises(ValidationError):
            services.reconciliation.create_statement(
                admin, bank_account_id=treasury.bank.id, statement_date=DAY,
                period_start=DAY, period_end=DAY,
                lines=(StatementLineInput(tx_date=DAY, description="خالی"),))

    def test_period_order_is_validated(self, services: AppServices, admin,
                                       treasury) -> None:
        with pytest.raises(ValidationError):
            services.reconciliation.create_statement(
                admin, bank_account_id=treasury.bank.id, statement_date=DAY,
                period_start=DAY, period_end=_dt.date(2026, 4, 1))

    def test_csv_import(self, services: AppServices, admin, treasury,
                        tmp_path: Path) -> None:
        path = tmp_path / "statement.csv"
        path.write_text(
            "date,description,reference,in,out\n"
            "2026-04-15,واریز مشتری,TRX-1,4000,\n"
            "2026-04-15,هزینه بانکی,TRX-2,,1500000\n",
            encoding="utf-8")
        statement = services.reconciliation.import_file(
            admin, bank_account_id=treasury.bank.id, path=path)
        assert statement.line_count == 2
        assert statement.file_name == "statement.csv"

    def test_excel_import(self, services: AppServices, admin, treasury,
                          tmp_path: Path) -> None:
        from openpyxl import Workbook

        path = tmp_path / "statement.xlsx"
        book = Workbook()
        sheet = book.active
        sheet.append(["date", "description", "reference", "in", "out"])
        sheet.append(["2026-04-15", "واریز", "TRX-9", 4000, None])
        book.save(path)
        statement = services.reconciliation.import_file(
            admin, bank_account_id=treasury.bank.id, path=path)
        assert statement.line_count == 1


class TestMatching:
    def test_auto_match_pairs_the_exact_document(self, services: AppServices, admin,
                                                 treasury) -> None:
        payment = _posted_payment(services, admin, treasury)
        statement = services.reconciliation.create_statement(
            admin, bank_account_id=treasury.bank.id, statement_date=DAY,
            period_start=DAY, period_end=DAY,
            opening_balance=100_000_000, closing_balance=98_500_000,
            lines=(StatementLineInput(tx_date=DAY, description="هزینه جاری",
                                      amount_out=1_500_000),))
        suggestions = services.reconciliation.suggestions(admin, statement.id)
        assert [row.document_id for row in suggestions] == [payment.id]
        result = services.reconciliation.auto_match(admin, statement.id)
        assert result["matched"] == 1
        lines = services.reconciliation.statement_lines(admin, statement.id)
        assert lines[0].status == TC.LINE_MATCHED
        assert lines[0].matched_kind == "payment"

    def test_manual_match_and_unmatch(self, services: AppServices, admin,
                                      treasury) -> None:
        receipt = _posted_receipt(services, admin, treasury)
        statement = services.reconciliation.create_statement(
            admin, bank_account_id=treasury.bank.id, statement_date=DAY,
            period_start=DAY, period_end=DAY,
            lines=(StatementLineInput(tx_date=DAY, amount_in=4_000),))
        line = services.reconciliation.statement_lines(admin, statement.id)[0]
        matched = services.reconciliation.match_manually(
            admin, line.id, kind="receipt", document_id=receipt.id)
        assert matched.matched_id == receipt.id
        unmatched = services.reconciliation.unmatch(admin, line.id)
        assert unmatched.status == TC.LINE_UNMATCHED

    def test_manual_match_refuses_a_different_amount(self, services: AppServices, admin,
                                                     treasury) -> None:
        receipt = _posted_receipt(services, admin, treasury, amount=9_000)
        statement = services.reconciliation.create_statement(
            admin, bank_account_id=treasury.bank.id, statement_date=DAY,
            period_start=DAY, period_end=DAY,
            lines=(StatementLineInput(tx_date=DAY, amount_in=4_000),))
        line = services.reconciliation.statement_lines(admin, statement.id)[0]
        with pytest.raises(ValidationError):
            services.reconciliation.match_manually(
                admin, line.id, kind="receipt", document_id=receipt.id)

    def test_ignore_line_leaves_the_discrepancy_list(self, services: AppServices, admin,
                                                     treasury) -> None:
        statement = services.reconciliation.create_statement(
            admin, bank_account_id=treasury.bank.id, statement_date=DAY,
            period_start=DAY, period_end=DAY,
            lines=(StatementLineInput(tx_date=DAY, amount_out=12_345),))
        line = services.reconciliation.statement_lines(admin, statement.id)[0]
        services.reconciliation.ignore_line(admin, line.id, "کارمزد جزئی")
        report = services.reconciliation.discrepancy_report(admin, statement.id)
        assert report["unmatched_lines"] == []


class TestAdjustment:
    def test_adjustment_posts_a_balanced_journal(self, services: AppServices, admin,
                                                 treasury) -> None:
        statement = services.reconciliation.create_statement(
            admin, bank_account_id=treasury.bank.id, statement_date=DAY,
            period_start=DAY, period_end=DAY,
            opening_balance=100_000_000, closing_balance=99_995_000,
            lines=(StatementLineInput(tx_date=DAY, description="کارمزد بانک",
                                      amount_out=5_000),))
        line = services.reconciliation.statement_lines(admin, statement.id)[0]
        adjusted = services.reconciliation.create_adjustment(
            admin, line.id, counter_account_id=treasury.accounts["502004"].id,
            reason="کارمزد بانکی اعلام‌نشده")
        assert adjusted.status == TC.LINE_MATCHED
        assert adjusted.journal_id
        from pars_erp.db.models import JournalLine

        with services.db.session_scope() as session:
            rows = session.query(JournalLine).filter(
                JournalLine.journal_id == adjusted.journal_id).all()
            assert sum(row.debit for row in rows) == sum(row.credit for row in rows)

    def test_adjustment_needs_a_long_reason(self, services: AppServices, admin,
                                            treasury) -> None:
        statement = services.reconciliation.create_statement(
            admin, bank_account_id=treasury.bank.id, statement_date=DAY,
            period_start=DAY, period_end=DAY,
            lines=(StatementLineInput(tx_date=DAY, amount_out=5_000),))
        line = services.reconciliation.statement_lines(admin, statement.id)[0]
        with pytest.raises(ValidationError):
            services.reconciliation.create_adjustment(
                admin, line.id, counter_account_id=treasury.accounts["502004"].id,
                reason="خطا")

    def test_discrepancy_report_compares_statement_and_ledger(
            self, services: AppServices, admin, treasury) -> None:
        _posted_payment(services, admin, treasury)
        statement = services.reconciliation.create_statement(
            admin, bank_account_id=treasury.bank.id, statement_date=DAY,
            period_start=DAY, period_end=DAY,
            opening_balance=100_000_000, closing_balance=98_500_000,
            lines=(StatementLineInput(tx_date=DAY, amount_out=1_500_000),))
        services.reconciliation.auto_match(admin, statement.id)
        report = services.reconciliation.discrepancy_report(admin, statement.id)
        assert report["difference"] == Decimal("0")
        assert report["statement_closing"] == Decimal("98500000")
        assert report["open_balance_according_to_documents"] == Decimal("98500000")
