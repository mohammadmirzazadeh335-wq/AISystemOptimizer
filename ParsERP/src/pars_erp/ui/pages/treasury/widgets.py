"""Shared treasury controls (RTL, Persian, permission-aware).

The treasury screens share three things: a fund picker (cash box **or** bank
account), a report/period bar and the mapping from document rows to printable
report tables. Keeping them here means a receipt, a cheque collection and a
reconciliation adjustment all look and behave the same.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from pars_erp.services.report_render_service import (
    KIND_AMOUNT,
    KIND_DATE,
    KIND_TEXT,
    ReportColumn,
    ReportTable,
)
from pars_erp.treasury import constants as TC
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, MoneyEdit, form_row
from pars_erp.ui.pages.commerce.widgets import PickCombo, ask_reason, confirm  # noqa: F401

__all__ = [
    "FundPicker", "PickCombo", "MoneyEdit", "JalaliDateEdit", "form_row",
    "confirm", "ask_reason", "money_columns", "build_table", "renderer_for",
    "show_preview", "export_excel", "status_key", "DIRECTION_PERMISSION",
]


class FundPicker(QWidget):
    """Pick a *cash box* or a *bank account* and then the fund itself."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = None
        self.ctx = None
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.kind_combo = QComboBox()
        self.kind_combo.addItem(TC.FUND_TITLES_FA[TC.FUND_CASH], TC.FUND_CASH)
        self.kind_combo.addItem(TC.FUND_TITLES_FA[TC.FUND_BANK], TC.FUND_BANK)
        self.fund_combo = PickCombo()
        row.addWidget(form_row("نوع", self.kind_combo))
        row.addWidget(form_row("صندوق / حساب", self.fund_combo), 1)
        self.kind_combo.currentIndexChanged.connect(self._reload_funds)
        self.fund_combo.currentIndexChanged.connect(lambda _index: self.changed.emit())

    # ------------------------------------------------------------------ api
    def attach(self, services, ctx) -> None:
        self.services = services
        self.ctx = ctx
        self._reload_funds()

    def kind(self) -> str:
        return str(self.kind_combo.currentData())

    def cash_box_id(self) -> int | None:
        return self.fund_combo.value() if self.kind() == TC.FUND_CASH else None

    def bank_account_id(self) -> int | None:
        return self.fund_combo.value() if self.kind() == TC.FUND_BANK else None

    def fund_id(self) -> int | None:
        return self.fund_combo.value()

    def set_fund(self, kind: str, fund_id: int | None) -> None:
        index = self.kind_combo.findData(kind)
        if index >= 0:
            self.kind_combo.setCurrentIndex(index)
        self._reload_funds()
        if fund_id is not None:
            self.fund_combo.set_value(fund_id)

    def require(self) -> tuple[str, int]:
        fund_id = self.fund_combo.value()
        if fund_id is None:
            from pars_erp.core.errors import ValidationError

            raise ValidationError("صندوق یا حساب بانکی را انتخاب کنید.", field="fund")
        return self.kind(), int(fund_id)

    # -------------------------------------------------------------- internal
    def _reload_funds(self, *_args) -> None:
        if self.services is None:
            return
        try:
            if self.kind() == TC.FUND_CASH:
                choices = self.services.funds.cash_box_choices(self.ctx)
            else:
                choices = self.services.funds.bank_account_choices(self.ctx)
        except Exception:  # a user without the permission simply sees no fund
            choices = []
        self.fund_combo.load(choices)
        self.changed.emit()


# ------------------------------------------------------------------ reporting
def money_columns(titles: tuple[str, ...], *, first_text: bool = True
                  ) -> tuple[ReportColumn, ...]:
    columns = []
    for index, title in enumerate(titles):
        kind = KIND_TEXT if (first_text and index == 0) else (
            KIND_AMOUNT if any(word in title for word in
                               ("مبلغ", "مانده", "واریز", "برداشت", "دریافت", "پرداخت",
                                "ورودی", "خروجی", "خالص", "مبلغ", "کارمزد"))
            else KIND_TEXT)
        if title in ("تاریخ", "سررسید", "تاریخ صدور"):
            kind = KIND_DATE
        columns.append(ReportColumn(f"c{index}", title, kind))
    return tuple(columns)


def build_table(title: str, headers: tuple[str, ...], rows: tuple[tuple, ...],
                *, meta: str = "", company: str = "", totals: tuple | None = None,
                notes: tuple[str, ...] = ()) -> ReportTable:
    return ReportTable(title=title, columns=money_columns(headers), rows=rows,
                       company=company, meta=(meta,) if meta else (), totals=totals,
                       notes=notes)


def renderer_for(services):
    from pars_erp.services.report_render_service import ReportRenderer

    snapshot = services.settings.snapshot()
    return ReportRenderer(app_name=snapshot.app_name,
                          persian_digits=snapshot.persian_digits)


def show_preview(parent, services, table: ReportTable) -> None:
    from pars_erp.ui.dialogs.report_preview import ReportPreviewDialog

    ReportPreviewDialog(table, renderer_for(services), parent=parent).exec()


def export_excel(parent, services, table: ReportTable, *, prefix: str = "treasury") -> None:
    from pars_erp.core.errors import AppError
    from pars_erp.ui.dialogs.common_dialogs import show_error, show_info

    services.paths.exports_dir.mkdir(parents=True, exist_ok=True)
    path = services.paths.exports_dir / f"{prefix}_{_dt.datetime.now():%Y%m%d_%H%M%S}.xlsx"
    try:
        outcome = renderer_for(services).to_excel(table, path)
    except AppError as error:
        show_error(parent, "خروجی Excel", error)
        return
    show_info(parent, "خروجی Excel", outcome.message_fa, tone="success")


def status_key(status: str) -> str:
    """Map a document status to a table badge key (colour-coded statuses)."""
    return {
        TC.STATUS_DRAFT: "draft",
        TC.STATUS_APPROVED: "approved",
        TC.STATUS_POSTED: "posted",
        TC.STATUS_VOID: "void",
        TC.CHQ_RECEIVED: "draft" if status == TC.CHQ_DRAFT else "draft",
    }.get(status, status if status in (
        "in_safe", "deposited", "collected", "bounced", "spent", "transferred",
        "issued", "delivered", "pending", "paid", "returned", "cancelled") else "info")


#: the permission each treasury page checks for its *write* actions
DIRECTION_PERMISSION = {
    TC.FUND_CASH: "cash_boxes.view",
    TC.FUND_BANK: "bank_accounts.view",
}


def total_of(rows: list, attribute: str) -> Decimal:
    return sum((Decimal(getattr(row, attribute) or 0) for row in rows), Decimal("0"))


def money_label(value: Decimal, formatter=None) -> str:
    if formatter is not None:
        return formatter.amount(value)
    return f"{Decimal(value):,}"


def hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("HintText")
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignRight)
    return label


def stack(*widgets: QWidget) -> QWidget:
    """A small vertical container used by the dashboard cards."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    for widget in widgets:
        layout.addWidget(widget)
    return box
