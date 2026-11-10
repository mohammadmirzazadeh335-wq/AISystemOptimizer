"""Fiscal periods: create, activate, close (with checkpoint report) and reopen."""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.services.periods_service import PeriodInput
from pars_erp.ui.dialogs.common_dialogs import ConfirmDialog, show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.table_specs import AMOUNT, BADGE, DATE, NUMBER, TEXT, ColumnSpec
from pars_erp.ui.widgets.table import DataTable

PERIOD_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("code", "کد", TEXT, 90, "center"),
    ColumnSpec("title_fa", "عنوان دوره", TEXT, None),
    ColumnSpec("start_date", "شروع", DATE, 100, "center"),
    ColumnSpec("end_date", "پایان", DATE, 100, "center"),
    ColumnSpec("status", "وضعیت", BADGE, 92, "center",
               getter=lambda row: "active" if row.is_open else "locked"),
    ColumnSpec("is_active", "دوره جاری", TEXT, 90, "center",
               getter=lambda row: "✔" if row.is_active else "—"),
    ColumnSpec("journal_count", "تعداد سند", NUMBER, 90, "center"),
    ColumnSpec("posted_count", "ثبت‌شده", NUMBER, 80, "center"),
    ColumnSpec("total_debit", "جمع مبالغ", AMOUNT, 140, "left"),
)


class PeriodDialog(QDialog):
    def __init__(self, services, ctx, *, period=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.period = period
        self.saved = None
        self.setWindowTitle("ویرایش دوره مالی" if period else "دوره مالی جدید")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.code_edit = QLineEdit()
        self.title_edit = QLineEdit()
        self.start_edit = JalaliDateEdit(_dt.date.today())
        self.end_edit = JalaliDateEdit(_dt.date.today())
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setFixedHeight(60)
        self.active_check = QCheckBox("این دوره، دورهٔ جاری باشد")
        form.addRow("کد دوره", self.code_edit)
        form.addRow("عنوان", self.title_edit)
        form.addRow("تاریخ شروع", self.start_edit)
        form.addRow("تاریخ پایان", self.end_edit)
        form.addRow("", self.active_check)
        form.addRow("یادداشت", self.notes_edit)
        layout.addLayout(form)

        hint = QLabel("تاریخ‌ها شمسی هستند و در پایگاه داده به شکل استاندارد ذخیره می‌شوند.")
        hint.setObjectName("HintText")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        if period is not None:
            self.code_edit.setText(period.code)
            self.title_edit.setText(period.title_fa)
            self.start_edit.set_date(period.start_date)
            self.end_edit.set_date(period.end_date)
            self.notes_edit.setPlainText(period.notes or "")
            self.active_check.setChecked(period.is_active)
        else:
            try:
                code, title, start, end = self.services.accounting.suggest_period(self.ctx)
                self.code_edit.setText(code)
                self.title_edit.setText(title)
                self.start_edit.set_date(start)
                self.end_edit.set_date(end)
            except AppError:
                pass

        buttons = QDialogButtonBox()
        self.save_button = buttons.addButton("ذخیره", QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        start = self.start_edit.date()
        end = self.end_edit.date()
        if start is None or end is None:
            show_info(self, "دوره مالی", "تاریخ شروع و پایان را وارد کنید.", tone="warning")
            return
        data = PeriodInput(
            code=self.code_edit.text().strip(), title_fa=self.title_edit.text().strip(),
            start_date=start, end_date=end,
            notes=self.notes_edit.toPlainText().strip(),
            is_active=self.active_check.isChecked())
        try:
            if self.period is None:
                self.saved = self.services.periods.create(self.ctx, data)
            else:
                self.saved = self.services.periods.update(self.ctx, self.period.id, data)
        except AppError as error:
            show_error(self, "دوره مالی", error)
            return
        self.accept()


class PeriodsPage(PageBase):
    def __init__(self, services, ctx, formatter, *, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.header = PageHeader("دوره‌های مالی",
                                 "ایجاد دوره، تعیین دوره جاری، بستن و بازگشایی کنترل‌شده")
        self.new_button = self.header.add_action("دوره جدید", slot=self._new_period)
        self.header.add_action("بازخوانی", variant="ghost", slot=self.refresh)
        self.root.addWidget(self.header)

        card = CardPanel("دوره‌ها", "سند فقط در دورهٔ باز قابل ثبت است.")
        self.table = DataTable(PERIOD_COLUMNS, formatter=self.formatter)
        self.table.rowActivated.connect(lambda _i: self._edit_period())
        card.add(self.table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        for text, slot in (("ویرایش", self._edit_period),
                           ("تعیین دوره جاری", self._set_active),
                           ("بستن دوره", self._close),
                           ("بازگشایی", self._reopen),
                           ("سند اختتامیه", self._closing_entry),
                           ("حذف", self._delete)):
            button = QPushButton(text)
            button.setProperty("variant", "ghost")
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch(1)
        card.add_layout(actions)
        self.root.addWidget(card, 1)

        self.info = QLabel("")
        self.info.setObjectName("HintText")
        self.info.setWordWrap(True)
        self.root.addWidget(self.info)

    # ------------------------------------------------------------------- data
    def refresh(self) -> None:
        try:
            rows = self.services.periods.list_periods(self.ctx)
        except AppError as error:
            show_error(self, "دوره‌های مالی", error)
            return
        self.table.set_rows(rows)
        active = next((row for row in rows if row.is_active), None)
        self.info.setText(
            f"{len(rows)} دوره ثبت شده است." +
            (f" دورهٔ جاری: {active.title_fa} ({self.formatter.date(active.start_date)} تا "
             f"{self.formatter.date(active.end_date)})" if active else
             " هیچ دوره‌ای به‌عنوان جاری انتخاب نشده است."))

    def _selected(self):
        return self.table.current_row()

    # ---------------------------------------------------------------- actions
    def _new_period(self) -> None:
        if not self.can("periods.create"):
            self.notify("برای ایجاد دوره مالی مجوز لازم است.")
            return
        dialog = PeriodDialog(self.services, self.ctx, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.saved is not None:
            self.notify(f"دوره «{dialog.saved.title_fa}» ایجاد شد.")
            self.refresh()

    def _edit_period(self) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک دوره را انتخاب کنید.")
            return
        if not self.can("periods.create"):
            self.notify("برای ویرایش دوره مالی مجوز لازم است.")
            return
        dialog = PeriodDialog(self.services, self.ctx, period=row, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.notify("دوره به‌روزرسانی شد.")
            self.refresh()

    def _set_active(self) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک دوره را انتخاب کنید.")
            return
        try:
            self.services.periods.set_active(self.ctx, row.id)
        except AppError as error:
            show_error(self, "تعیین دوره جاری", error)
            return
        self.notify(f"دورهٔ جاری به «{row.title_fa}» تغییر کرد.")
        self.refresh()

    def _close(self) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک دوره را انتخاب کنید.")
            return
        # checkpoint report before closing, exactly what the spec asks for
        try:
            from pars_erp.services.reports_service import ReportsService  # noqa: F401
            trial = self.services.reports.trial_balance(
                self.ctx, date_from=row.start_date, date_to=row.end_date, mode=6)
            summary = (f"تراز آزمایشی دوره: مانده بدهکار "
                       f"{self.formatter.amount(trial.totals['closing_debit'])} و مانده بستانکار "
                       f"{self.formatter.amount(trial.totals['closing_credit'])}")
            if not trial.is_balanced:
                summary += " — هشدار: تراز متوازن نیست."
        except AppError:
            summary = "گزارش تراز قبل از بستن قابل محاسبه نبود."
        confirm = ConfirmDialog(
            self, title="بستن دوره مالی",
            message=(f"دوره «{row.title_fa}» بسته شود؟ پس از بستن، ثبت سند جدید در این دوره "
                     f"ممکن نیست.\n\n{summary}"), confirm_text="بستن دوره", danger=True)
        if confirm.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.services.periods.close(self.ctx, row.id)
        except AppError as error:
            show_error(self, "بستن دوره", error)
            return
        self.notify("دوره بسته شد.")
        self.refresh()

    def _reopen(self) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک دوره را انتخاب کنید.")
            return
        reason = self._ask_reason("بازگشایی دوره", f"دلیل بازگشایی دوره «{row.title_fa}»:")
        if reason is None:
            return
        try:
            self.services.periods.reopen(self.ctx, row.id, reason)
        except AppError as error:
            show_error(self, "بازگشایی دوره", error)
            return
        self.notify("دوره بازگشایی شد.")
        self.refresh()

    def _closing_entry(self) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک دوره را انتخاب کنید.")
            return
        if not self.can("periods.close"):
            self.notify("برای ایجاد سند اختتامیه مجوز بستن دوره لازم است.")
            return
        try:
            choices = self.services.accounting.retained_earnings_choices(self.ctx)
        except AppError as error:
            show_error(self, "سند اختتامیه", error)
            return
        if not choices:
            show_info(self, "سند اختتامیه",
                      "حساب «سود و زیان انباشته» در کدینگ تعریف نشده است.",
                      tone="warning")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("سند اختتامیه")
        dialog.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout = QVBoxLayout(dialog)
        note = QLabel(f"حساب سود و زیان انباشته برای بستن دوره «{row.title_fa}» انتخاب شود.")
        note.setWordWrap(True)
        layout.addWidget(note)
        combo = QComboBox()
        for account_id, label in choices:
            combo.addItem(label, account_id)
        layout.addWidget(combo)
        buttons = QDialogButtonBox()
        buttons.addButton("ایجاد سند", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            journal = self.services.periods.create_closing_entry(
                self.ctx, row.id, retained_earnings_account_id=combo.currentData())
        except AppError as error:
            show_error(self, "سند اختتامیه", error)
            return
        show_info(self, "سند اختتامیه",
                  f"سند شمارهٔ {getattr(journal, 'number', '—')} ایجاد شد.", tone="success")
        self.refresh()

    def _delete(self) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک دوره را انتخاب کنید.")
            return
        confirm = ConfirmDialog(self, title="حذف دوره",
                                message=f"دوره «{row.title_fa}» حذف شود؟",
                                confirm_text="حذف", danger=True)
        if confirm.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.services.periods.delete(self.ctx, row.id)
        except AppError as error:
            show_error(self, "حذف دوره", error)
            return
        self.notify("دوره حذف شد.")
        self.refresh()

    def _ask_reason(self, title: str, message: str) -> str | None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(message))
        edit = QPlainTextEdit()
        edit.setFixedHeight(64)
        layout.addWidget(edit)
        buttons = QDialogButtonBox()
        buttons.addButton("تأیید", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return edit.toPlainText().strip() or "بدون توضیح"
