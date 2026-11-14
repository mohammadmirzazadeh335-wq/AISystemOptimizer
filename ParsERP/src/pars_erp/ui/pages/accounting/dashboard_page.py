"""Accounting dashboard: real counters from the database plus a quick start.

Nothing here is decorative: every number comes from
:class:`~pars_erp.services.accounting_setup_service.AccountingDashboard`, and the
quick-start buttons are the same service calls the other pages use.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton

from pars_erp.core.errors import AppError
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.formatting import to_display_digits
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.widgets.common import KpiCard


class AccountingDashboardPage(PageBase):
    def __init__(self, services, ctx, formatter, *, on_navigate=None, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self._on_navigate = on_navigate
        self.header = PageHeader("داشبورد حسابداری",
                                 "وضعیت کدینگ، دوره مالی و اسناد در یک نگاه")
        self.header.add_action("سند جدید", slot=lambda: self._go("journals"))
        self.header.add_action("بازخوانی", variant="ghost", slot=self.refresh)
        self.root.addWidget(self.header)

        kpi_card = CardPanel()
        grid = QGridLayout()
        grid.setSpacing(10)
        self.kpi_accounts = KpiCard("حساب‌های فعال", "—")
        self.kpi_details = KpiCard("حساب‌های تفصیلی", "—")
        self.kpi_period = KpiCard("دورهٔ جاری", "—")
        self.kpi_posted = KpiCard("اسناد ثبت‌نهایی", "—")
        self.kpi_pending = KpiCard("در انتظار تأیید", "—")
        self.kpi_total = KpiCard("جمع مبالغ ثبت‌شده", "—")
        for index, card in enumerate((self.kpi_accounts, self.kpi_details, self.kpi_period,
                                      self.kpi_posted, self.kpi_pending, self.kpi_total)):
            grid.addWidget(card, index // 3, index % 3)
        kpi_card.add_layout(grid)
        self.root.addWidget(kpi_card)

        workflow = CardPanel("گردش کار اسناد")
        self.workflow_label = QLabel("—")
        self.workflow_label.setTextFormat(Qt.TextFormat.RichText)
        self.workflow_label.setWordWrap(True)
        workflow.add(self.workflow_label)
        self.root.addWidget(workflow)

        quick = CardPanel("شروع سریع",
                          "اگر ساختار حسابداری خالی است، از همین‌جا کدینگ و دورهٔ مالی ساخته می‌شود.")
        quick_row = QHBoxLayout()
        quick_row.setSpacing(8)
        self.setup_button = QPushButton("ایجاد کدینگ و دورهٔ استاندارد")
        self.setup_button.setProperty("variant", "primary")
        self.setup_button.clicked.connect(self._quick_setup)
        quick_row.addWidget(self.setup_button)
        for text, key in (("کدینگ حساب‌ها", "accounts"),
                          ("اسناد حسابداری", "journals"),
                          ("تراز آزمایشی", "trial_balance"),
                          ("ترازنامه", "balance_sheet")):
            button = QPushButton(text)
            button.setProperty("variant", "ghost")
            button.clicked.connect(lambda _checked=False, k=key: self._go(k))
            quick_row.addWidget(button)
        quick_row.addStretch(1)
        quick.add_layout(quick_row)
        self.root.addWidget(quick)

        self.hints = QLabel("")
        self.hints.setObjectName("HintText")
        self.hints.setWordWrap(True)
        self.root.addWidget(self.hints)
        self.root.addStretch(1)

    # ------------------------------------------------------------------- data
    def refresh(self) -> None:
        try:
            data = self.services.accounting.dashboard(self.ctx)
        except AppError as error:
            show_error(self, "داشبورد حسابداری", error)
            return
        self.kpi_accounts.set_value(self.formatter.number(data.accounts_active),
                                    f"از {self.formatter.number(data.accounts_total)} حساب")
        self.kpi_details.set_value(self.formatter.number(data.details_total))
        self.kpi_period.set_value(to_display_digits(data.active_period or "تعیین نشده",
                                                    self.formatter.persian_digits))
        self.kpi_posted.set_value(self.formatter.number(data.journals_posted))
        self.kpi_pending.set_value(self.formatter.number(data.journals_pending))
        self.kpi_total.set_value(
            self.formatter.amount(data.posted_total),
            f"{self.formatter.number(data.periods_total)} دوره مالی")
        self.workflow_label.setText(
            f"<span>پیش‌نویس: <b>{self.formatter.number(data.journals_draft)}</b> سند</span>"
            f" &nbsp;·&nbsp; <span>در انتظار تأیید: "
            f"<b>{self.formatter.number(data.journals_pending)}</b> سند</span>"
            f" &nbsp;·&nbsp; <span>تأییدشده و آمادهٔ ثبت: "
            f"<b>{self.formatter.number(data.journals_approved)}</b> سند</span>"
            f" &nbsp;·&nbsp; <span>ثبت‌نهایی: "
            f"<b>{self.formatter.number(data.journals_posted)}</b> سند</span>")
        self.setup_button.setEnabled(not data.is_ready)
        self.hints.setText(to_display_digits(
            " · ".join(data.hints) if data.hints else "ساختار حسابداری آماده است.",
            self.formatter.persian_digits))

    # ---------------------------------------------------------------- actions
    def _go(self, key: str) -> None:
        if self._on_navigate is not None:
            self._on_navigate(key)

    def _quick_setup(self) -> None:
        try:
            result = self.services.accounting.ensure_basic_setup(self.ctx)
        except AppError as error:
            show_error(self, "شروع سریع", error)
            return
        show_info(self, "شروع سریع",
                  f"{result.created_accounts} حساب و {result.created_periods} دوره مالی ایجاد شد.",
                  tone="success")
        self.refresh()
