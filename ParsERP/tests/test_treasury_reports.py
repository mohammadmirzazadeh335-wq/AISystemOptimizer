"""Phase 4 - treasury reports, dashboard and the due-date calendar."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from pars_erp.core.errors import PermissionDeniedError, ValidationError
from pars_erp.services.commerce_reports_service import ReportPeriod
from pars_erp.services.context import AppServices
from pars_erp.services.user_service import UserCreateData
from pars_erp.services.voucher_service import (
    AllocationInput,
    ChequeInput,
    PaymentInput,
    ReceiptInput,
    TransferInput,
)
from pars_erp.treasury import constants as TC

PERIOD = ReportPeriod(_dt.date(2026, 4, 1), _dt.date(2026, 4, 30))


def _post(services, admin, document) -> object:
    services.vouchers.approve_receipt(admin, document.id) \
        if document.kind == "receipt" else services.vouchers.approve_payment(admin, document.id)
    return (services.vouchers.post_receipt(admin, document.id)
            if document.kind == "receipt"
            else services.vouchers.post_payment(admin, document.id))


@pytest.fixture()
def busy_treasury(services: AppServices, admin, treasury):
    """Two posted receipts, one payment and one posted transfer in the period."""
    first = services.vouchers.create_receipt(admin, ReceiptInput(
        receipt_date=_dt.date(2026, 4, 6), amount=6_000,
        receipt_type=TC.RECEIPT_CUSTOMER, method=TC.METHOD_CASH,
        cash_box_id=treasury.box.id, payer_detail_id=treasury.customer.id,
        allocations=(AllocationInput(invoice_id=treasury.sale.id, amount=6_000),)))
    _post(services, admin, first)
    second = services.vouchers.create_receipt(admin, ReceiptInput(
        receipt_date=_dt.date(2026, 4, 8), amount=1_000_000,
        receipt_type=TC.RECEIPT_OTHER, method=TC.METHOD_TRANSFER,
        bank_account_id=treasury.bank.id,
        counter_account_id=treasury.accounts["503001"].id))
    _post(services, admin, second)
    payment = services.vouchers.create_payment(admin, PaymentInput(
        payment_date=_dt.date(2026, 4, 9), amount=2_000_000,
        payment_type=TC.PAYMENT_EXPENSE, method=TC.METHOD_TRANSFER,
        bank_account_id=treasury.bank.id,
        counter_account_id=treasury.accounts["503001"].id))
    _post(services, admin, payment)
    transfer = services.vouchers.create_transfer(admin, TransferInput(
        transfer_date=_dt.date(2026, 4, 10), amount=500_000,
        from_bank_account_id=treasury.bank.id, to_cash_box_id=treasury.box.id))
    services.vouchers.post_transfer(admin, transfer.id)
    return treasury


class TestFundReports:
    def test_bank_ledger_ties_to_the_balance(self, services: AppServices, admin,
                                             busy_treasury) -> None:
        table = services.treasury_reports.bank_ledger(admin, PERIOD)
        assert table.row_count >= 3
        assert table.rows[-1][-1] == services.funds.get_bank_account(
            admin, busy_treasury.bank.id).balance

    def test_cash_ledger(self, services: AppServices, admin, busy_treasury) -> None:
        table = services.treasury_reports.cash_ledger(admin, PERIOD)
        assert table.columns[0] == "تاریخ"
        assert table.row_count >= 3

    def test_balances_reports(self, services: AppServices, admin, busy_treasury) -> None:
        banks = services.treasury_reports.bank_balances(admin)
        boxes = services.treasury_reports.cash_balances(admin)
        assert banks.row_count == 1
        assert boxes.row_count == 2
        assert banks.totals()[-1] == Decimal("98500000")

    def test_period_validation(self) -> None:
        with pytest.raises(ValidationError):
            ReportPeriod(_dt.date(2026, 5, 1), _dt.date(2026, 4, 1))


class TestChequeReports:
    def test_received_and_issued_lists(self, services: AppServices, admin,
                                       treasury) -> None:
        services.vouchers.create_receipt(admin, ReceiptInput(
            receipt_date=_dt.date(2026, 4, 20), amount=4_000,
            receipt_type=TC.RECEIPT_CUSTOMER, method=TC.METHOD_CHEQUE,
            payer_detail_id=treasury.customer.id, cash_box_id=treasury.box.id,
            cheque=ChequeInput(number="PH-1", bank_name="بانک ملت", amount=4_000,
                               issue_date=_dt.date(2026, 4, 20),
                               due_date=_dt.date(2026, 5, 20))))
        table = services.treasury_reports.cheques(admin, PERIOD,
                                                  direction=TC.CHEQUE_RECEIVED)
        assert table.row_count == 1
        assert table.rows[0][0] == "PH-1"
        empty = services.treasury_reports.cheques(admin, PERIOD,
                                                  direction=TC.CHEQUE_ISSUED)
        assert empty.row_count == 0

    def test_invalid_direction(self, services: AppServices, admin, treasury) -> None:
        with pytest.raises(ValidationError):
            services.treasury_reports.cheques(admin, PERIOD, direction="sideways")

    def test_due_report_counts_days_left(self, services: AppServices, admin,
                                         treasury) -> None:
        services.vouchers.create_receipt(admin, ReceiptInput(
            receipt_date=_dt.date.today(), amount=4_000,
            receipt_type=TC.RECEIPT_CUSTOMER, method=TC.METHOD_CHEQUE,
            payer_detail_id=treasury.customer.id, cash_box_id=treasury.box.id,
            cheque=ChequeInput(number="PH-2", bank_name="بانک ملت", amount=4_000,
                               issue_date=_dt.date.today(),
                               due_date=_dt.date.today() + _dt.timedelta(days=3))))
        table = services.treasury_reports.cheques_due(admin, days=7)
        assert table.row_count == 1
        assert table.rows[0][-1] == 3


class TestPersonAndCashFlowReports:
    def test_person_flows(self, services: AppServices, admin, busy_treasury) -> None:
        table = services.treasury_reports.person_flows(admin, PERIOD, kind="receipt")
        assert table.row_count == 2

    def test_open_invoices_report(self, services: AppServices, admin,
                                  busy_treasury) -> None:
        table = services.treasury_reports.open_invoices(admin, PERIOD,
                                                        direction="receipt")
        assert table.row_count == 1
        assert table.rows[0][-1] == Decimal("4000")

    def test_cash_flow_and_forecast(self, services: AppServices, admin,
                                    busy_treasury) -> None:
        flow = services.treasury_reports.cash_flow(admin, PERIOD)
        assert flow.row_count == 3
        first = flow.rows[0]
        assert first[1] - first[2] == first[3]
        forecast = services.treasury_reports.forecast(admin, days=30)
        assert forecast.column_count == 4


class TestDashboard:
    def test_figures_come_from_posted_documents(self, services: AppServices, admin,
                                                busy_treasury) -> None:
        figures = services.treasury_dashboard.figures(admin, PERIOD)
        assert figures.cash_total > Decimal("10000000")
        assert figures.receipts_period == Decimal("1006000")
        assert figures.payments_period == Decimal("2000000")
        assert figures.net_flow == Decimal("-994000")

    def test_series_and_trend(self, services: AppServices, admin,
                              busy_treasury) -> None:
        series = services.treasury_dashboard.receipts_vs_payments(admin, PERIOD)
        assert [point.day.day for point in series] == [6, 8, 9]
        trend = services.treasury_dashboard.cash_flow_trend(admin, PERIOD)
        assert len(trend) >= 1

    def test_today_documents(self, services: AppServices, admin, busy_treasury) -> None:
        rows = services.treasury_dashboard.today_documents(
            admin, _dt.date(2026, 4, 6))
        assert len(rows) == 1 and rows[0].kind == "receipt"

    def test_watch_list_orders_by_due_date(self, services: AppServices, admin,
                                           treasury) -> None:
        services.vouchers.create_receipt(admin, ReceiptInput(
            receipt_date=_dt.date.today(), amount=1_000,
            receipt_type=TC.RECEIPT_CUSTOMER, method=TC.METHOD_CHEQUE,
            payer_detail_id=treasury.customer.id, cash_box_id=treasury.box.id,
            cheque=ChequeInput(number="W-1", bank_name="بانک ملت", amount=1_000,
                               issue_date=_dt.date.today(),
                               due_date=_dt.date.today() + _dt.timedelta(days=2))))
        rows = services.treasury_dashboard.watch_cheques(admin, days=7)
        assert rows and rows[0].days_left == 2


class TestCalendar:
    def test_cheques_and_planned_items(self, services: AppServices, admin,
                                       treasury) -> None:
        services.vouchers.create_receipt(admin, ReceiptInput(
            receipt_date=_dt.date.today(), amount=1_000,
            receipt_type=TC.RECEIPT_CUSTOMER, method=TC.METHOD_CHEQUE,
            payer_detail_id=treasury.customer.id, cash_box_id=treasury.box.id,
            cheque=ChequeInput(number="CAL-1", bank_name="بانک ملت", amount=1_000,
                               issue_date=_dt.date.today(),
                               due_date=_dt.date.today() + _dt.timedelta(days=5))))
        item_id = services.treasury_reports.add_planned_item(
            admin, kind=TC.PLAN_PAYMENT, title="پرداخت اجاره",
            due_date=_dt.date.today() + _dt.timedelta(days=6), amount=900_000)
        items = services.treasury_reports.calendar(
            admin, date_from=_dt.date.today(),
            date_to=_dt.date.today() + _dt.timedelta(days=30))
        assert {item.source_kind for item in items} == {"cheque", "planned"}
        services.treasury_reports.mark_planned_done(admin, item_id)
        done = [item for item in services.treasury_reports.calendar(
            admin, date_from=_dt.date.today(),
            date_to=_dt.date.today() + _dt.timedelta(days=30))
            if item.source_kind == "planned"]
        assert done[0].is_done is True

    def test_planned_item_kind_is_validated(self, services: AppServices, admin,
                                            treasury) -> None:
        with pytest.raises(ValidationError):
            services.treasury_reports.add_planned_item(
                admin, kind="birthday", title="تولد", due_date=_dt.date.today(),
                amount=1)


class TestPermissions:
    def test_storekeeper_cannot_read_treasury_reports(self, services: AppServices,
                                                     admin, treasury) -> None:
        services.users.create_user(admin, UserCreateData(
            username="anbardar", full_name="انباردار", password="Anbar1404!",
            confirm_password="Anbar1404!", role_codes=("storekeeper",)))
        ctx = services.auth.authenticate("anbardar", "Anbar1404!")
        with pytest.raises(PermissionDeniedError):
            services.treasury_reports.bank_ledger(ctx, PERIOD)
        with pytest.raises(PermissionDeniedError):
            services.treasury_dashboard.figures(ctx, PERIOD)

    def test_treasurer_can_read_but_not_approve(self, services: AppServices, admin,
                                                treasury) -> None:
        services.users.create_user(admin, UserCreateData(
            username="khazanedar", full_name="خزانه‌دار", password="Khazane1404!",
            confirm_password="Khazane1404!", role_codes=("treasurer",)))
        ctx = services.auth.authenticate("khazanedar", "Khazane1404!")
        assert services.treasury_reports.bank_ledger(ctx, PERIOD)
        assert services.treasury_dashboard.figures(ctx, PERIOD)
