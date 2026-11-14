"""New/edit journal-document dialog (فرم سند حسابداری).

Entry model: the accountant fills one line at a time (account, detail, cost
center, project, description and exactly one of debit/credit) and presses Enter;
the line joins the list, totals update immediately, and the document can only be
saved when debits equal credits. All validation still happens in
:class:`~pars_erp.services.journals_service.JournalService`.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pars_erp.accounting import constants as C
from pars_erp.core.errors import AppError
from pars_erp.core.money import format_amount
from pars_erp.services.journals_service import JournalInput, JournalLineInput
from pars_erp.ui.dialogs.common_dialogs import show_error
from pars_erp.ui.pages.accounting.widgets import AccountPicker, JalaliDateEdit, MoneyEdit
from pars_erp.ui.pages.base import CardPanel
from pars_erp.ui.table_specs import AMOUNT, TEXT, ColumnSpec
from pars_erp.ui.widgets.table import DataTable

LINE_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("line_no", "ردیف", TEXT, 50, "center"),
    ColumnSpec("account_code", "کد حساب", TEXT, 88, "center"),
    ColumnSpec("account_title", "عنوان حساب", TEXT, 170),
    ColumnSpec("detail_name", "تفصیلی", TEXT, 110),
    ColumnSpec("description", "شرح", TEXT, None),
    ColumnSpec("debit", "بدهکار", AMOUNT, 120, "left"),
    ColumnSpec("credit", "بستانکار", AMOUNT, 120, "left"),
)


class _Line:
    """One editable line before it is handed to the service."""

    __slots__ = ("account_id", "account_code", "account_title", "detail_id", "detail_name",
                 "cost_center_id", "cost_center", "project_id", "project",
                 "description", "debit", "credit")

    def __init__(self, **kwargs) -> None:
        for name in self.__slots__:
            setattr(self, name, kwargs.get(name))

    def as_row(self, index: int) -> dict:
        return {
            "line_no": index + 1,
            "account_code": self.account_code,
            "account_title": self.account_title,
            "detail_name": self.detail_name or "—",
            "description": self.description or "",
            "debit": self.debit,
            "credit": self.credit,
        }


class JournalEditorDialog(QDialog):
    """Create a new document or edit an existing draft."""

    saved = Signal(object)

    def __init__(self, services, ctx, formatter, *, journal=None, period=None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.formatter = formatter
        self.journal = journal
        self.period = period
        self._lines: list[_Line] = []
        self._editing_index: int | None = None
        self.result_row = None

        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle("ویرایش پیش‌نویس سند" if journal else "سند حسابداری جدید")
        self.resize(1080, 760)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        root.addWidget(self._build_header())
        root.addWidget(self._build_entry(), 0)
        root.addWidget(self._build_lines(), 1)

        self.totals_label = QLabel("")
        self.totals_label.setObjectName("SectionTitle")
        root.addWidget(self.totals_label)
        root.addWidget(self._build_buttons())

        self._load_journal()
        self._refresh_totals()
        self._install_shortcuts()

    # ------------------------------------------------------------------ header
    def _build_header(self) -> QWidget:
        card = CardPanel("مشخصات سند")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)

        self.date_edit = JalaliDateEdit(
            self.journal.entry_date if self.journal else (
                self.period.start_date if self.period else _dt.date.today()),
            persian_digits=self.formatter.persian_digits)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("مثلاً پرداخت اجاره دفتر مرکزی")

        self.kind_combo = QComboBox()
        for kind in C.JOURNAL_KINDS:
            self.kind_combo.addItem(C.KIND_TITLES_FA[kind], kind)

        self.reference_edit = QLineEdit()
        self.reference_edit.setPlaceholderText("شماره پیگیری/ارجاع (اختیاری)")

        self.currency_combo = QComboBox()
        try:
            for code, title in self.services.currency.currency_choices():
                self.currency_combo.addItem(title, code)
        except AppError:
            self.currency_combo.addItem("ریال ایران", "IRR")

        self.rate_edit = MoneyEdit(persian_digits=self.formatter.persian_digits)
        self.rate_edit.setToolTip("نرخ ارز در تاریخ سند (برای ارز پایه همیشه ۱)")

        for row, (title, widget) in enumerate((
                ("تاریخ سند", self.date_edit), ("شرح سند", self.title_edit),
                ("نوع سند", self.kind_combo))):
            label = QLabel(title)
            label.setObjectName("FieldLabel")
            grid.addWidget(label, row, 0)
            grid.addWidget(widget, row, 1)
        for row, (title, widget) in enumerate((
                ("شماره ارجاع", self.reference_edit), ("ارز", self.currency_combo),
                ("نرخ ارز", self.rate_edit))):
            label = QLabel(title)
            label.setObjectName("FieldLabel")
            grid.addWidget(label, row, 2)
            grid.addWidget(widget, row, 3)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(3, 2)

        self.period_label = QLabel("")
        self.period_label.setObjectName("HintText")
        card.add_layout(grid)
        card.add(self.period_label)
        return card

    # ------------------------------------------------------------------- entry
    def _build_entry(self) -> QWidget:
        card = CardPanel("افزودن سطر", "حساب را انتخاب کنید و فقط یکی از بدهکار/بستانکار را پر کنید.")
        outer = QVBoxLayout()
        outer.setSpacing(8)

        first = QHBoxLayout()
        first.setSpacing(8)
        self.account_picker = AccountPicker()
        try:
            choices = self.services.accounts.choices(self.ctx)
        except AppError:
            choices = []
        self.account_picker.load(choices, placeholder="— حساب معین —")
        self.account_picker.setMinimumWidth(280)
        first.addWidget(self.account_picker, 2)

        self.detail_combo = QComboBox()
        self.detail_combo.setMinimumWidth(150)
        self.detail_combo.setToolTip("حساب تفصیلی (در صورت وجود)")
        first.addWidget(self.detail_combo, 1)

        self.cost_combo = QComboBox()
        self.cost_combo.setToolTip("مرکز هزینه")
        first.addWidget(self.cost_combo, 1)

        self.project_combo = QComboBox()
        self.project_combo.setToolTip("پروژه")
        first.addWidget(self.project_combo, 1)
        outer.addLayout(first)

        second = QHBoxLayout()
        second.setSpacing(8)
        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("شرح سطر")
        second.addWidget(self.description_edit, 2)
        self.debit_edit = MoneyEdit(persian_digits=self.formatter.persian_digits)
        self.debit_edit.setPlaceholderText("بدهکار")
        second.addWidget(self.debit_edit, 1)
        self.credit_edit = MoneyEdit(persian_digits=self.formatter.persian_digits)
        self.credit_edit.setPlaceholderText("بستانکار")
        second.addWidget(self.credit_edit, 1)

        self.add_button = QPushButton("افزودن سطر")
        self.add_button.setProperty("variant", "primary")
        self.add_button.setToolTip("افزودن سطر (Enter)")
        self.add_button.clicked.connect(self._commit_line)
        second.addWidget(self.add_button)
        outer.addLayout(second)
        card.add_layout(outer)

        for combo in (self.cost_combo, self.project_combo):
            combo.addItem("— بدون —", None)
        try:
            for item_id, label in self.services.dimensions.choices(self.ctx, "cost_center"):
                self.cost_combo.addItem(label, item_id)
            for item_id, label in self.services.dimensions.choices(self.ctx, "project"):
                self.project_combo.addItem(label, item_id)
        except AppError:
            pass
        self.account_picker.accountChanged.connect(self._reload_details)

        self.error_label = QLabel("")
        self.error_label.setObjectName("ErrorText")
        self.error_label.setWordWrap(True)
        card.add(self.error_label)
        return card

    def _build_lines(self) -> QWidget:
        card = CardPanel("سطرهای سند")
        self.lines_table = DataTable(LINE_COLUMNS, formatter=self.formatter)
        self.lines_table.setMinimumHeight(190)
        self.lines_table.rowActivated.connect(self._edit_line)
        card.add(self.lines_table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        for text, slot, tip in (
                ("ویرایش سطر", lambda: self._edit_line(self.lines_table.selected_row_index() or 0), ""),
                ("کپی سطر", self._copy_line, "Ctrl+D"),
                ("حذف سطر", self._delete_line, "Delete"),
                ("پاک کردن همه", self._clear_lines, "")):
            button = QPushButton(text)
            button.setProperty("variant", "ghost")
            button.setToolTip(f"{text} {tip}".strip())
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch(1)
        card.add_layout(actions)
        return card

    def _build_buttons(self) -> QWidget:
        bar = QDialogButtonBox()
        self.save_button = bar.addButton("ذخیره پیش‌نویس",
                                         QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setProperty("variant", "primary")
        self.submit_button = bar.addButton("ذخیره و ارسال برای تأیید",
                                           QDialogButtonBox.ButtonRole.ActionRole)
        bar.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        bar.accepted.connect(lambda: self._save(submit=False))
        bar.rejected.connect(self.reject)
        self.submit_button.clicked.connect(lambda: self._save(submit=True))
        return bar

    def _install_shortcuts(self) -> None:
        for edit in (self.debit_edit, self.credit_edit, self.description_edit):
            shortcut = QShortcut(QKeySequence(Qt.Key.Key_Return), edit)
            shortcut.activated.connect(self._commit_line)
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(lambda: self._save(False))
        QShortcut(QKeySequence("Ctrl+Return"), self).activated.connect(lambda: self._save(True))
        QShortcut(QKeySequence("Ctrl+D"), self).activated.connect(self._copy_line)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.lines_table).activated.connect(
            self._delete_line)

    # -------------------------------------------------------------------- data
    def _reload_details(self, account_id) -> None:
        self.detail_combo.clear()
        self.detail_combo.addItem("— بدون تفصیلی —", None)
        if account_id is None:
            return
        try:
            for detail_id, label in self.services.parties.choices(self.ctx, account_id):
                self.detail_combo.addItem(label, detail_id)
        except AppError:
            pass

    def _load_journal(self) -> None:
        period = self.period
        if period is None:
            try:
                period = (self.services.periods.period_for_date(
                    self.ctx, self.date_edit.date() or _dt.date.today())
                    or self.services.periods.active_period(self.ctx))
            except AppError:
                period = None
        self.period = period
        if period is not None:
            self.period_label.setText(
                f"دوره مالی: {period.title_fa} · {self.formatter.date(period.start_date)}"
                f" تا {self.formatter.date(period.end_date)} · وضعیت: "
                f"{'باز' if period.is_open else 'بسته'}")
        else:
            self.period_label.setText(
                "برای این تاریخ دورهٔ مالی بازی وجود ندارد؛ ابتدا دوره مالی ایجاد کنید.")

        if self.journal is None:
            self.rate_edit.set_amount(Decimal(1))
            return
        self.date_edit.set_date(self.journal.entry_date)
        self.title_edit.setText(self.journal.title_fa)
        self.reference_edit.setText(self.journal.reference_no or "")
        self.description_edit.clear()
        index = self.kind_combo.findData(self.journal.kind)
        self.kind_combo.setCurrentIndex(max(0, index))
        index = self.currency_combo.findData(self.journal.currency_code)
        self.currency_combo.setCurrentIndex(max(0, index))
        self.rate_edit.set_amount(self.journal.exchange_rate or Decimal(1))
        self._lines = [
            _Line(account_id=line.account_id, account_code=line.account_code,
                  account_title=line.account_title, detail_id=line.detail_id,
                  detail_name=line.detail_name, cost_center_id=None,
                  cost_center=line.cost_center, project_id=None, project=line.project,
                  description=line.description, debit=line.debit, credit=line.credit)
            for line in self.journal.lines]
        self._render_lines()

    # --------------------------------------------------------------- line ops
    def _commit_line(self) -> None:
        account_id = self.account_picker.current_account_id()
        if account_id is None:
            self._error("حساب سطر را انتخاب کنید.")
            return
        debit = self.debit_edit.amount
        credit = self.credit_edit.amount
        if debit > 0 and credit > 0:
            self._error("در هر سطر فقط یکی از بدهکار یا بستانکار قابل ثبت است.")
            return
        if debit == 0 and credit == 0:
            self._error("مبلغ بدهکار یا بستانکار سطر باید بزرگ‌تر از صفر باشد.")
            return
        text = self.account_picker.currentText()
        code, _, title = text.partition("—")
        line = _Line(
            account_id=account_id, account_code=code.strip(), account_title=title.strip() or text,
            detail_id=self.detail_combo.currentData(),
            detail_name=self.detail_combo.currentText() if self.detail_combo.currentData() else "",
            cost_center_id=self.cost_combo.currentData(),
            cost_center=self.cost_combo.currentText() if self.cost_combo.currentData() else "",
            project_id=self.project_combo.currentData(),
            project=self.project_combo.currentText() if self.project_combo.currentData() else "",
            description=self.description_edit.text().strip(), debit=debit, credit=credit)
        if self._editing_index is None:
            self._lines.append(line)
        else:
            self._lines[self._editing_index] = line
            self._editing_index = None
            self.add_button.setText("افزودن سطر")
        self._reset_entry()
        self._render_lines()
        self._refresh_totals()
        self.account_picker.setFocus()

    def _reset_entry(self) -> None:
        self.debit_edit.clear_value()
        self.credit_edit.clear_value()
        self.description_edit.clear()
        self.detail_combo.setCurrentIndex(0)
        self.cost_combo.setCurrentIndex(0)
        self.project_combo.setCurrentIndex(0)
        self.error_label.setText("")

    def _edit_line(self, index) -> None:
        if not isinstance(index, int) or not 0 <= index < len(self._lines):
            self._error("سطر انتخاب‌شده معتبر نیست.")
            return
        line = self._lines[index]
        self.account_picker.set_account(line.account_id)
        self._reload_details(line.account_id)
        if line.detail_id:
            position = self.detail_combo.findData(line.detail_id)
            if position >= 0:
                self.detail_combo.setCurrentIndex(position)
        for combo, value in ((self.cost_combo, line.cost_center_id),
                             (self.project_combo, line.project_id)):
            position = combo.findData(value) if value else 0
            combo.setCurrentIndex(position if position >= 0 else 0)
        self.description_edit.setText(line.description or "")
        self.debit_edit.set_amount(line.debit or Decimal(0))
        self.credit_edit.set_amount(line.credit or Decimal(0))
        self._editing_index = index
        self.add_button.setText("به‌روزرسانی سطر")

    def _delete_line(self) -> None:
        index = self.lines_table.selected_row_index()
        if index is None or not 0 <= index < len(self._lines):
            self._error("برای حذف، ابتدا یک سطر را انتخاب کنید.")
            return
        del self._lines[index]
        self._editing_index = None
        self._render_lines()
        self._refresh_totals()

    def _copy_line(self) -> None:
        index = self.lines_table.selected_row_index()
        if index is None or not 0 <= index < len(self._lines):
            self._error("برای کپی، ابتدا یک سطر را انتخاب کنید.")
            return
        import copy as _copy

        clone = _Line(**{name: getattr(self._lines[index], name) for name in _Line.__slots__})
        clone = _copy.copy(clone)
        self._lines.insert(index + 1, clone)
        self._render_lines()
        self._refresh_totals()

    def _clear_lines(self) -> None:
        self._lines.clear()
        self._editing_index = None
        self._render_lines()
        self._refresh_totals()

    # ----------------------------------------------------------------- render
    def _render_lines(self) -> None:
        self.lines_table.set_rows([line.as_row(index) for index, line in enumerate(self._lines)])

    def _refresh_totals(self) -> None:
        debit = sum((line.debit for line in self._lines), Decimal(0))
        credit = sum((line.credit for line in self._lines), Decimal(0))
        difference = debit - credit
        state = "متوازن" if difference == 0 and self._lines else "نامتوازن"
        color = "" if difference == 0 else " style='color:#b42318'"
        self.totals_label.setText(
            f"<span>جمع بدهکار: <b>{self._amount(debit)}</b></span> · "
            f"<span>جمع بستانکار: <b>{self._amount(credit)}</b></span> · "
            f"<span{color}>اختلاف: <b>{self._amount(difference)}</b></span> · "
            f"<span>تعداد سطر: <b>{self.formatter.number(len(self._lines))}</b></span> · "
            f"<span>{state}</span>")

    def _amount(self, value: Decimal) -> str:
        return format_amount(value, self.formatter.currency_code,
                             persian_digits=self.formatter.persian_digits)

    def _error(self, message: str) -> None:
        self.error_label.setText(message)

    # ------------------------------------------------------------------- save
    def _save(self, submit: bool) -> None:
        if not self._lines:
            self._error("سند بدون سطر قابل ذخیره نیست.")
            return
        debit = sum((line.debit for line in self._lines), Decimal(0))
        credit = sum((line.credit for line in self._lines), Decimal(0))
        if debit != credit:
            self._error("جمع بدهکار و بستانکار برابر نیست؛ سند نامتوازن ذخیره نمی‌شود.")
            return
        entry_date = self.date_edit.date()
        if entry_date is None:
            self._error("تاریخ سند را مشخص کنید.")
            return
        data = JournalInput(
            entry_date=entry_date,
            title_fa=self.title_edit.text().strip(),
            lines=[JournalLineInput(
                account_id=line.account_id, description=line.description or "",
                debit=line.debit, credit=line.credit, detail_id=line.detail_id,
                cost_center_id=line.cost_center_id, project_id=line.project_id)
                for line in self._lines],
            fiscal_period_id=self.period.id if self.period else None,
            reference_no=self.reference_edit.text().strip(),
            currency_code=str(self.currency_combo.currentData() or "IRR"),
            exchange_rate=self.rate_edit.amount or Decimal(1),
            notes="",
            kind=str(self.kind_combo.currentData() or C.KIND_NORMAL),
        )
        try:
            if self.journal is None:
                row = self.services.journals.create(self.ctx, data)
            else:
                row = self.services.journals.update_draft(self.ctx, self.journal.id, data)
            if submit:
                row = self.services.journals.submit(self.ctx, row.id)
        except AppError as error:
            show_error(self, "ذخیره سند", error)
            return
        self.result_row = row
        self.saved.emit(row)
        self.accept()
