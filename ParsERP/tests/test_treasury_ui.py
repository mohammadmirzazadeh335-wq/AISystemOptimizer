"""Phase-4 treasury screens: navigation, permissions and real widget tests.

The Qt-free tests run everywhere. The ``gui`` tests build the real widgets and are
skipped when no Qt platform plugin can be created, so a green run never pretends a
screen was rendered when it was not.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from pars_erp.security.permissions import ALL_PERMISSIONS
from pars_erp.services.voucher_service import PaymentInput, ReceiptInput
from pars_erp.treasury import constants as TC
from pars_erp.ui.navigation import ALL_ITEMS, NAV_GROUPS, visible_items

TREASURY_KEYS = (
    "treasury_dashboard", "receipt_cash", "payment_cash", "receipt_customer",
    "payment_supplier", "cheque_received", "cheque_issued", "cash_boxes",
    "bank_accounts", "treasury_transfer", "cheque_books", "cheque_manage",
    "receivables", "payables", "reconciliation", "settlements", "fund_flow",
    "treasury_reports", "treasury_settings",
)

TREASURY_PERMISSIONS = (
    "bank_accounts.view", "bank_accounts.edit", "cash_boxes.view", "cash_boxes.edit",
    "receipts.view", "receipts.create", "payments.view", "payments.create",
    "vouchers.approve", "vouchers.post", "transfers.create",
    "cheques.view", "cheques.create", "cheques.change_status", "cheques.cancel",
    "cheque_books.manage", "reconciliation.manage", "reconciliation.approve",
    "settlements.manage", "treasury.reports", "treasury.calendar",
)


class TestTreasuryNavigation:
    def test_group_sits_between_commerce_and_accounting(self) -> None:
        keys = [group.key for group in NAV_GROUPS]
        assert keys.index("commerce") < keys.index("treasury") < keys.index("accounting")
        group = next(group for group in NAV_GROUPS if group.key == "treasury")
        assert group.title_fa == "خزانه‌داری"
        assert {item.key for item in group.items} == set(TREASURY_KEYS)
        assert len(group.items) == 19

    def test_every_page_is_real_and_described(self) -> None:
        for key in TREASURY_KEYS:
            item = ALL_ITEMS[key]
            assert not item.is_placeholder, f"{key} is a placeholder"
            assert item.enabled and item.description_fa, key
            assert item.icon in ("bank", "cashbox", "cheque", "transfer", "reconcile",
                                 "receipt", "payment", "wallet", "reports", "settings")

    def test_every_permission_exists(self) -> None:
        known = {definition.code for definition in ALL_PERMISSIONS}
        missing = [code for code in TREASURY_PERMISSIONS if code not in known]
        assert not missing, missing

    def test_every_item_requires_a_known_permission(self) -> None:
        known = {definition.code for definition in ALL_PERMISSIONS}
        for key in TREASURY_KEYS:
            assert ALL_ITEMS[key].permission in known, key

    def test_treasurer_sees_the_treasury_but_not_the_ledger(self) -> None:
        from pars_erp.security.permissions import SecurityContext

        ctx = SecurityContext(
            user_id=7, username="khazane", full_name="خزانه‌دار",
            role_codes=("treasurer",),
            permissions=frozenset(_role_permissions("treasurer")))
        keys = {item.key for group in visible_items(ctx) for item in group.items}
        assert {"receipt_cash", "payment_cash", "bank_accounts", "cash_boxes"} <= keys
        assert "roles" not in keys

    def test_storekeeper_does_not_see_the_treasury(self) -> None:
        from pars_erp.security.permissions import SecurityContext

        ctx = SecurityContext(
            user_id=8, username="anbardar", full_name="انباردار",
            role_codes=("storekeeper",),
            permissions=frozenset(_role_permissions("storekeeper")))
        keys = {item.key for group in visible_items(ctx) for item in group.items}
        assert not (set(TREASURY_KEYS) & keys)


def _role_permissions(code: str) -> tuple[str, ...]:
    from pars_erp.security.permissions import DEFAULT_ROLE_TEMPLATES

    for template in DEFAULT_ROLE_TEMPLATES:
        if template.code == code:
            return tuple(template.permissions)
    return ()


# --------------------------------------------------------------------- Qt tests
def qt_required() -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover - no Qt at all
        pytest.skip("PySide6 is not importable")
    try:
        QApplication.instance() or QApplication([])
    except Exception:  # pragma: no cover - no platform plugin
        pytest.skip("no Qt platform plugin available")


@pytest.fixture(autouse=True)
def _stub_dialogs(monkeypatch):
    try:
        from PySide6.QtWidgets import QDialog, QMessageBox
    except Exception:  # pragma: no cover
        return
    monkeypatch.setattr(QDialog, "exec", lambda self, *a, **k: QDialog.DialogCode.Rejected,
                        raising=False)
    monkeypatch.setattr(QMessageBox, "exec", lambda self, *a, **k: 0, raising=False)
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok),
                        raising=False)


@pytest.fixture()
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from pars_erp.services.settings_service import SettingsSnapshot
    from pars_erp.ui.theme import apply_theme

    apply_theme(app, SettingsSnapshot(values={}))
    return app


@pytest.fixture()
def formatter():
    from pars_erp.ui.formatting import Formatter

    return Formatter()


def _pages(services, admin, formatter, treasury):
    from pars_erp.ui.pages.treasury.cheques_page import (
        ChequeBooksPage, ChequeManagePage, IssuedChequesPage, PayableDocumentsPage,
        ReceivableDocumentsPage, ReceivedChequesPage,
    )
    from pars_erp.ui.pages.treasury.dashboard_page import TreasuryDashboardPage
    from pars_erp.ui.pages.treasury.funds_page import BankAccountsPage, CashBoxesPage
    from pars_erp.ui.pages.treasury.reconciliation_page import ReconciliationPage
    from pars_erp.ui.pages.treasury.reports_page import FundFlowPage, TreasuryReportsPage
    from pars_erp.ui.pages.treasury.settings_page import TreasurySettingsPage
    from pars_erp.ui.pages.treasury.settlements_page import SettlementsPage
    from pars_erp.ui.pages.treasury.transfers_page import TransfersPage
    from pars_erp.ui.pages.treasury.vouchers_page import VouchersPage

    common = (services, admin, formatter)
    return {
        "treasury_dashboard": TreasuryDashboardPage(*common),
        "receipt_cash": VouchersPage(*common, family="receipt"),
        "payment_cash": VouchersPage(*common, family="payment"),
        "receipt_customer": VouchersPage(*common, family="receipt", default_type="customer"),
        "payment_supplier": VouchersPage(*common, family="payment", default_type="supplier"),
        "cheque_received": ReceivedChequesPage(*common),
        "cheque_issued": IssuedChequesPage(*common),
        "cash_boxes": CashBoxesPage(*common),
        "bank_accounts": BankAccountsPage(*common),
        "treasury_transfer": TransfersPage(*common),
        "cheque_books": ChequeBooksPage(*common),
        "cheque_manage": ChequeManagePage(*common),
        "receivables": ReceivableDocumentsPage(*common),
        "payables": PayableDocumentsPage(*common),
        "reconciliation": ReconciliationPage(*common),
        "settlements": SettlementsPage(*common),
        "fund_flow": FundFlowPage(*common),
        "treasury_reports": TreasuryReportsPage(*common),
        "treasury_settings": TreasurySettingsPage(*common),
    }


def _select_row(table, row: int = 0) -> None:
    """Select a table row the way a user click does (Qt's selectRow fails in RTL)."""
    index = table.model.index(row, 0)
    table.setCurrentIndex(index)
    table.selectionModel().select(
        index, table.selectionModel().SelectionFlag.ClearAndSelect
        | table.selectionModel().SelectionFlag.Rows)


@pytest.mark.gui
class TestTreasuryPages:
    def test_every_page_builds_and_refreshes(self, qapp, services, admin, formatter,
                                             treasury) -> None:
        pages = _pages(services, admin, formatter, treasury)
        assert set(pages) == set(TREASURY_KEYS)
        for key, page in pages.items():
            page.refresh()
            assert page.layout() is not None, key
            assert page.header is not None, key

    def test_bank_and_box_pages_show_balances(self, qapp, services, admin, formatter,
                                              treasury) -> None:
        from pars_erp.ui.pages.treasury.funds_page import BankAccountsPage, CashBoxesPage

        banks = BankAccountsPage(services, admin, formatter)
        banks.refresh()
        assert len(banks.table.model.rows()) == 1
        _select_row(banks.table, 0)
        banks._statement()
        assert banks.movements

        boxes = CashBoxesPage(services, admin, formatter)
        boxes.refresh()
        assert len(boxes.table.model.rows()) == 2
        _select_row(boxes.table, 0)
        boxes._statement()
        assert boxes.movements

    def test_receipt_dialog_creates_a_real_document(self, qapp, services, admin,
                                                    treasury) -> None:
        from pars_erp.ui.pages.treasury.vouchers_page import VoucherDialog

        dialog = VoucherDialog(services, admin, "receipt")
        dialog.fund_picker.set_fund(TC.FUND_CASH, treasury.box.id)
        dialog.amount_edit.set_amount(4_000)
        dialog.party_combo.set_value(treasury.customer.id)
        dialog._fill_open_invoices()
        assert dialog.alloc_table.rowCount() == 1
        money = dialog.alloc_table.cellWidget(0, 5)
        money.set_amount(4_000)
        dialog._save()
        assert dialog.saved is not None
        assert dialog.saved.amount == Decimal("4000")
        assert dialog.saved.status == TC.STATUS_DRAFT
        posted = services.vouchers.post_receipt(
            admin, services.vouchers.approve_receipt(admin, dialog.saved.id).id)
        assert posted.journal_id

    def test_payment_dialog_requires_a_fund(self, qapp, services, admin,
                                            treasury) -> None:
        from pars_erp.ui.pages.treasury.vouchers_page import VoucherDialog

        dialog = VoucherDialog(services, admin, "payment")
        dialog.amount_edit.set_amount(1_000)
        dialog.fund_picker.fund_combo.setCurrentIndex(0)
        dialog._save()
        assert dialog.saved is None

    def test_transfer_dialog_posts_one_journal(self, qapp, services, admin,
                                               treasury) -> None:
        from pars_erp.ui.pages.treasury.transfers_page import TransferDialog

        dialog = TransferDialog(services, admin)
        dialog.from_picker.set_fund(TC.FUND_BANK, treasury.bank.id)
        dialog.to_picker.set_fund(TC.FUND_CASH, treasury.box.id)
        dialog.amount_edit.set_amount(1_000_000)
        dialog.fee_edit.set_amount(5_000)
        dialog._save()
        assert dialog.saved is not None and dialog.saved.journal_id
        assert services.funds.get_bank_account(admin, treasury.bank.id).balance == \
            Decimal("98995000")

    def test_cheque_status_dialog_validates_transitions(self, qapp, services, admin,
                                                        treasury) -> None:
        from pars_erp.ui.pages.treasury.cheques_page import ChequeStatusDialog
        from pars_erp.services.voucher_service import ChequeInput

        receipt = services.vouchers.create_receipt(admin, ReceiptInput(
            receipt_date=_dt.date.today(), amount=4_000,
            receipt_type=TC.RECEIPT_CUSTOMER, method=TC.METHOD_CHEQUE,
            payer_detail_id=treasury.customer.id, cash_box_id=treasury.box.id,
            cheque=ChequeInput(number="UI-1", bank_name="بانک ملت", amount=4_000,
                               issue_date=_dt.date.today(),
                               due_date=_dt.date.today() + _dt.timedelta(days=20))))
        cheque = services.cheques.get_cheque(admin, receipt.cheque_id)
        dialog = ChequeStatusDialog(services, admin, cheque)
        assert dialog.target_combo.count() == len(
            TC.RECEIVED_TRANSITIONS[TC.CHQ_RECEIVED])
        dialog.target_combo.setCurrentIndex(
            dialog.target_combo.findData(TC.CHQ_IN_SAFE))
        dialog._save()
        assert dialog.changed is not None
        assert dialog.changed.status == TC.CHQ_IN_SAFE

    def test_reports_page_every_report_renders(self, qapp, services, admin, formatter,
                                               treasury) -> None:
        from pars_erp.ui.pages.treasury.reports_page import (
            FundFlowPage, REPORT_CHOICES, TreasuryReportsPage,
        )

        for page_class in (TreasuryReportsPage, FundFlowPage):
            page = page_class(services, admin, formatter)
            for key, _title, _fund, _direction in page.choices:
                index = page.report_combo.findData(key)
                page.report_combo.setCurrentIndex(index)
                page._run()
                assert page.current is not None, key

    def test_dashboard_shows_real_figures(self, qapp, services, admin, formatter,
                                          treasury) -> None:
        from pars_erp.ui.pages.treasury.dashboard_page import TreasuryDashboardPage

        payment = services.vouchers.create_payment(admin, PaymentInput(
            payment_date=_dt.date.today(), amount=1_000,
            payment_type=TC.PAYMENT_OTHER, method=TC.METHOD_TRANSFER,
            bank_account_id=treasury.bank.id,
            counter_account_id=treasury.accounts["503001"].id))
        services.vouchers.approve_payment(admin, payment.id)
        services.vouchers.post_payment(admin, payment.id)
        page = TreasuryDashboardPage(services, admin, formatter)
        page.refresh()
        assert "99,999,000" in page.cards["bank"].value_label.text()
        assert len(page.trend_table.model.rows()) >= 1

    def test_settings_page_saves(self, qapp, services, admin, formatter,
                                 treasury) -> None:
        from pars_erp.ui.pages.treasury.settings_page import TreasurySettingsPage

        page = TreasurySettingsPage(services, admin, formatter)
        page.alert_spin.setValue(11)
        page._save()
        assert services.settings.snapshot().int("treasury_cheque_alert_days") == 11

    def test_main_window_opens_every_visible_page(self, qapp, services, admin) -> None:
        from pars_erp.ui.main_window import MainWindow

        window = MainWindow(services, admin)
        window.show()
        try:
            for group in visible_items(admin):
                for item in group.items:
                    window.navigate(item.key)
            window.toggle_theme()
            window.toggle_theme()
        finally:
            window.close()
