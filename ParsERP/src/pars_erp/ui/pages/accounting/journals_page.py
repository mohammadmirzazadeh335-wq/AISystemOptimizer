"""Journal documents screen: list, filter, workflow actions, print and export."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from pars_erp.accounting import constants as C
from pars_erp.core.errors import AppError
from pars_erp.services.journals_service import JournalFilter
from pars_erp.services.report_render_service import (
    KIND_AMOUNT,
    KIND_TEXT,
    ReportColumn,
    ReportRenderer,
    ReportTable,
)
from pars_erp.ui.dialogs.common_dialogs import ConfirmDialog, show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.accounting.journal_editor import JournalEditorDialog
from pars_erp.ui.table_specs import AMOUNT, BADGE, DATE, NUMBER, ColumnSpec, TEXT
from pars_erp.ui.widgets.common import SearchInput
from pars_erp.ui.widgets.pagination import PaginationBar
from pars_erp.ui.widgets.table import DataTable

JOURNAL_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("number", "شماره", NUMBER, 78, "center"),
    ColumnSpec("entry_date", "تاریخ", DATE, 100, "center"),
    ColumnSpec("title_fa", "شرح سند", TEXT, None),
    ColumnSpec("status_fa", "وضعیت", BADGE, 116, "center",
               getter=lambda row: row.status),
    ColumnSpec("total_debit", "بدهکار", AMOUNT, 132, "left"),
    ColumnSpec("total_credit", "بستانکار", AMOUNT, 132, "left"),
    ColumnSpec("line_count", "سطر", NUMBER, 56, "center"),
    ColumnSpec("kind_fa", "نوع", TEXT, 80, "center"),
    ColumnSpec("fiscal_period_title", "دوره", TEXT, 120),
)

LINE_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("line_no", "ردیف", TEXT, 52, "center"),
    ColumnSpec("account_code", "کد", TEXT, 86, "center"),
    ColumnSpec("account_title", "عنوان حساب", TEXT, 190),
    ColumnSpec("detail_name", "تفصیلی", TEXT, 120),
    ColumnSpec("description", "شرح", TEXT, None),
    ColumnSpec("debit", "بدهکار", AMOUNT, 130, "left"),
    ColumnSpec("credit", "بستانکار", AMOUNT, 130, "left"),
)


def journal_report_table(journal, formatter) -> ReportTable:
    """Build the printable table of one document (shared by print/PDF/Excel)."""
    rows = tuple(
        (line.line_no, line.account_code, line.account_title,
         line.detail_name or "—", line.description or "",
         line.debit, line.credit)
        for line in journal.lines)
    return ReportTable(
        title=f"سند حسابداری شمارهٔ {journal.number}",
        columns=(
            ReportColumn("line_no", "ردیف", KIND_TEXT, 0.5),
            ReportColumn("account_code", "کد حساب", KIND_TEXT, 0.9),
            ReportColumn("account_title", "عنوان حساب", KIND_TEXT, 2.4),
            ReportColumn("detail_name", "تفصیلی", KIND_TEXT, 1.2),
            ReportColumn("description", "شرح", KIND_TEXT, 2.0),
            ReportColumn("debit", "بدهکار", KIND_AMOUNT, 1.3),
            ReportColumn("credit", "بستانکار", KIND_AMOUNT, 1.3),
        ),
        rows=rows,
        subtitle=journal.title_fa,
        meta=(
            f"شماره سند: {journal.number}",
            f"تاریخ: {formatter.date(journal.entry_date)}",
            f"وضعیت: {journal.status_fa}",
            f"دوره: {journal.fiscal_period_title}",
            f"ارجاع: {journal.reference_no}" if journal.reference_no else "بدون ارجاع",
        ),
        totals=("", "", "جمع", "", "", journal.total_debit, journal.total_credit),
        notes=(f"مبلغ به حروف: — · ارز: {journal.currency_code}",),
        currency_code=journal.currency_code,
    )


class JournalDetailDialog(QDialog):
    """Read-only view of one document with print/PDF/Excel buttons."""

    def __init__(self, services, ctx, formatter, journal, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.formatter = formatter
        self.journal = journal
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle(f"سند شمارهٔ {journal.number}")
        self.resize(980, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        info = CardPanel(f"{journal.title_fa}")
        form = QFormLayout()
        period = journal.fiscal_period_title
        for label, value in (
                ("شماره سند", self.formatter.number(journal.number)),
                ("تاریخ", self.formatter.date(journal.entry_date)),
                ("وضعیت", journal.status_fa),
                ("نوع", journal.kind_fa),
                ("دوره مالی", period),
                ("شماره ارجاع", journal.reference_no or "—"),
                ("ارز / نرخ", f"{journal.currency_code} / {journal.exchange_rate}"),
                ("تعداد سطر", self.formatter.number(journal.line_count))):
            row = QLabel(value)
            row.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(label, row)
        if journal.void_reason:
            form.addRow("دلیل ابطال", QLabel(journal.void_reason))
        info.add_layout(form)
        layout.addWidget(info)

        lines_card = CardPanel("سطرها")
        table = DataTable(LINE_COLUMNS, formatter=self.formatter)
        table.set_rows([{
            "line_no": line.line_no,
            "account_code": line.account_code,
            "account_title": line.account_title,
            "detail_name": line.detail_name or "—",
            "description": line.description or "",
            "debit": line.debit,
            "credit": line.credit,
        } for line in journal.lines])
        lines_card.add(table, 1)
        totals = QLabel(
            f"جمع بدهکار: <b>{self.formatter.amount(journal.total_debit)}</b> · "
            f"جمع بستانکار: <b>{self.formatter.amount(journal.total_credit)}</b> · "
            f"اختلاف: <b>{self.formatter.amount(journal.difference)}</b>")
        totals.setTextFormat(Qt.TextFormat.RichText)
        lines_card.add(totals)
        layout.addWidget(lines_card, 1)

        buttons = QHBoxLayout()
        for text, slot in (("چاپ / پیش‌نمایش", self._preview),
                           ("خروجی PDF", lambda: self._export("pdf")),
                           ("خروجی Excel", lambda: self._export("xlsx"))):
            button = QPushButton(text)
            button.setProperty("variant", "ghost")
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        close = QPushButton("بستن")
        close.setProperty("variant", "primary")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    # ---------------------------------------------------------------- exports
    def _table(self) -> ReportTable:
        return journal_report_table(self.journal, self.formatter)

    def _renderer(self) -> ReportRenderer:
        snapshot = self.services.settings.snapshot()
        return ReportRenderer(app_name=snapshot.app_name,
                              persian_digits=self.formatter.persian_digits)

    def _preview(self) -> None:
        from pars_erp.ui.dialogs.report_preview import ReportPreviewDialog

        ReportPreviewDialog(self._table(), self._renderer(), parent=self).exec()

    def _export(self, kind: str) -> None:
        suffix = "pdf" if kind == "pdf" else "xlsx"
        suggested = f"journal-{self.journal.number}.{suffix}"
        path, _filter = QFileDialog.getSaveFileName(
            self, "ذخیره خروجی", suggested,
            "PDF (*.pdf)" if suffix == "pdf" else "Excel (*.xlsx)")
        if not path:
            return
        try:
            renderer = self._renderer()
            if kind == "pdf":
                outcome = renderer.to_pdf(self._table(), Path(path))
            else:
                outcome = renderer.to_excel(self._table(), Path(path))
        except AppError as error:
            show_error(self, "خروجی سند", error)
            return
        show_info(self, "خروجی سند", outcome.message_fa, tone="success")


class JournalsPage(PageBase):
    """All journal documents with the full draft→posted workflow."""

    def __init__(self, services, ctx, formatter, *, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self._page_no = 1
        self._page_size = self.services.settings.snapshot().table_page_size
        self._rows = []

        self.header = PageHeader("اسناد حسابداری",
                                 "ثبت، تأیید، قطعی‌سازی، ابطال و اصلاح اسناد")
        self.new_button = self.header.add_action("سند جدید", slot=self._new_journal,
                                                 tooltip="ایجاد سند دستی (Ctrl+N)")
        self.header.add_action("بازخوانی", variant="ghost", slot=self.refresh)
        self.root.addWidget(self.header)

        filters = CardPanel()
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.search = SearchInput("جست‌وجو در شرح، ارجاع یا شماره سند…")
        self.search.searchChanged.connect(self._on_filter_changed)
        row1.addWidget(self.search, 2)

        self.status_combo = QComboBox()
        self.status_combo.addItem("همه وضعیت‌ها", None)
        for status in C.JOURNAL_STATUSES:
            self.status_combo.addItem(C.STATUS_TITLES_FA[status], status)
        self.status_combo.currentIndexChanged.connect(self._on_filter_changed)
        row1.addWidget(self.status_combo)

        self.period_combo = QComboBox()
        self.period_combo.currentIndexChanged.connect(self._on_filter_changed)
        row1.addWidget(self.period_combo, 1)
        filters.add_layout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.date_from = JalaliDateEdit(None, persian_digits=formatter.persian_digits,
                                        allow_empty=True)
        self.date_to = JalaliDateEdit(None, persian_digits=formatter.persian_digits,
                                      allow_empty=True)
        self.date_from.dateChanged.connect(lambda _v: self._on_filter_changed())
        self.date_to.dateChanged.connect(lambda _v: self._on_filter_changed())
        row2.addWidget(QLabel("از تاریخ"))
        row2.addWidget(self.date_from)
        row2.addWidget(QLabel("تا تاریخ"))
        row2.addWidget(self.date_to)

        self.number_spin = QSpinBox()
        self.number_spin.setRange(0, 9_999_999)
        self.number_spin.setSpecialValueText("همه شماره‌ها")
        self.number_spin.valueChanged.connect(lambda _v: self._on_filter_changed())
        row2.addWidget(self.number_spin)
        row2.addStretch(1)

        self.clear_button = QPushButton("پاک کردن فیلترها")
        self.clear_button.setProperty("variant", "ghost")
        self.clear_button.clicked.connect(self._clear_filters)
        row2.addWidget(self.clear_button)
        filters.add_layout(row2)
        self.root.addWidget(filters)

        table_card = CardPanel("فهرست اسناد")
        self.table = DataTable(JOURNAL_COLUMNS, formatter=self.formatter)
        self.table.rowActivated.connect(lambda _i: self._open_detail())
        table_card.add(self.table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        for text, slot in (("مشاهده", self._open_detail),
                           ("ویرایش پیش‌نویس", self._edit_draft),
                           ("ارسال برای تأیید", lambda: self._transition("submit")),
                           ("تأیید", lambda: self._transition("approve")),
                           ("ثبت نهایی", lambda: self._transition("post")),
                           ("برگشت به پیش‌نویس", lambda: self._transition("return")),
                           ("ابطال", lambda: self._transition("void")),
                           ("اصلاح (سند معکوس)", lambda: self._transition("reverse")),
                           ("کپی سند", self._duplicate),
                           ("حذف پیش‌نویس", self._delete_draft)):
            button = QPushButton(text)
            button.setProperty("variant", "ghost")
            button.clicked.connect(slot)
            actions.addWidget(button)
        table_card.add_layout(actions)

        self.pagination = PaginationBar()
        self.pagination.pageChanged.connect(self._on_page_changed)
        table_card.add(self.pagination)
        self.root.addWidget(table_card, 1)

    # ------------------------------------------------------------------ filters
    def _load_periods(self) -> None:
        current = self.period_combo.currentData()
        self.period_combo.blockSignals(True)
        self.period_combo.clear()
        self.period_combo.addItem("همه دوره‌ها", None)
        try:
            for period in self.services.periods.list_periods(self.ctx):
                self.period_combo.addItem(period.title_fa, period.id)
            active = self.services.periods.active_period(self.ctx)
            if active is not None:
                index = self.period_combo.findData(active.id)
                if index >= 0:
                    self.period_combo.setCurrentIndex(index)
        except AppError:
            pass
        position = self.period_combo.findData(current) if current else -1
        if position >= 0:
            self.period_combo.setCurrentIndex(position)
        self.period_combo.blockSignals(False)

    def _clear_filters(self) -> None:
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.status_combo.setCurrentIndex(0)
        self.period_combo.setCurrentIndex(0)
        self.date_from.set_date(None)
        self.date_to.set_date(None)
        self.number_spin.setValue(0)
        self._page_no = 1
        self.refresh()

    def _on_filter_changed(self, *_args) -> None:
        self._page_no = 1
        self.refresh()

    def _on_page_changed(self, page: int) -> None:
        self._page_no = page
        self._load()

    # --------------------------------------------------------------------- data
    def refresh(self) -> None:
        self._load_periods()
        self._load()

    def _load(self) -> None:
        filters = JournalFilter(
            status=self.status_combo.currentData(),
            fiscal_period_id=self.period_combo.currentData(),
            date_from=self.date_from.date(),
            date_to=self.date_to.date(),
            number=self.number_spin.value() or None,
            search=self.search.text().strip() or None,
        )
        try:
            page = self.services.journals.list(self.ctx, filters, page=self._page_no,
                                               page_size=self._page_size)
        except AppError as error:
            show_error(self, "بارگذاری اسناد", error)
            return
        self._rows = list(page.items)
        self.table.set_rows(self._rows)
        self.pagination.update_page(page)

    def _selected(self):
        return self.table.current_row()

    # ------------------------------------------------------------------ actions
    def _new_journal(self) -> None:
        if not self.can("journals.create"):
            self.notify("برای ایجاد سند مجوز «ایجاد سند» لازم است.")
            return
        dialog = JournalEditorDialog(self.services, self.ctx, self.formatter, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_row is not None:
            self.notify(f"سند شمارهٔ {dialog.result_row.number} ذخیره شد "
                        f"({dialog.result_row.status_fa}).")
            self.refresh()

    def _edit_draft(self) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک سند را انتخاب کنید.")
            return
        if not row.is_editable:
            self.notify("فقط سند پیش‌نویس قابل ویرایش است.")
            return
        journal = self.services.journals.get(self.ctx, row.id)
        dialog = JournalEditorDialog(self.services, self.ctx, self.formatter,
                                     journal=journal, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.notify("پیش‌نویس سند به‌روزرسانی شد.")
            self.refresh()

    def _open_detail(self) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک سند را انتخاب کنید.")
            return
        try:
            journal = self.services.journals.get(self.ctx, row.id)
        except AppError as error:
            show_error(self, "نمایش سند", error)
            return
        JournalDetailDialog(self.services, self.ctx, self.formatter, journal, parent=self).exec()

    def _transition(self, action: str) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک سند را انتخاب کنید.")
            return
        reason = ""
        if action == "void":
            reason = self._ask_reason("ابطال سند",
                                      f"سند شمارهٔ {row.number} باطل شود؟ دلیل ابطال ثبت می‌شود.")
            if reason is None:
                return
        elif action == "reverse":
            reason = self._ask_reason(
                "اصلاح سند",
                f"برای سند شمارهٔ {row.number} سند معکوس ایجاد شود؟")
            if reason is None:
                return
        try:
            if action == "submit":
                self.services.journals.submit(self.ctx, row.id)
            elif action == "approve":
                self.services.journals.approve(self.ctx, row.id)
            elif action == "post":
                self.services.journals.post(self.ctx, row.id)
            elif action == "return":
                self.services.journals.return_to_draft(self.ctx, row.id, reason=reason)
            elif action == "void":
                self.services.journals.void(self.ctx, row.id, reason or "ابطال توسط کاربر")
            elif action == "reverse":
                self.services.journals.reverse(self.ctx, row.id, reason=reason)
        except AppError as error:
            show_error(self, "عملیات سند", error)
            return
        self.notify("عملیات با موفقیت انجام شد.")
        self.refresh()

    def _duplicate(self) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک سند را انتخاب کنید.")
            return
        try:
            clone = self.services.journals.duplicate(self.ctx, row.id)
        except AppError as error:
            show_error(self, "کپی سند", error)
            return
        self.notify(f"سند جدید شمارهٔ {clone.number} از روی سند {row.number} ساخته شد.")
        self.refresh()

    def _delete_draft(self) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک سند را انتخاب کنید.")
            return
        confirm = ConfirmDialog(self, title="حذف پیش‌نویس",
                                message=f"پیش‌نویس سند شمارهٔ {row.number} حذف شود؟",
                                confirm_text="حذف", danger=True)
        if confirm.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.services.journals.delete_draft(self.ctx, row.id)
        except AppError as error:
            show_error(self, "حذف پیش‌نویس", error)
            return
        self.notify("پیش‌نویس حذف شد.")
        self.refresh()

    def _ask_reason(self, title: str, message: str) -> str | None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout = QVBoxLayout(dialog)
        note = QLabel(message)
        note.setWordWrap(True)
        layout.addWidget(note)
        edit = QPlainTextEdit()
        edit.setFixedHeight(70)
        edit.setPlaceholderText("دلیل (در تاریخچه ثبت می‌شود)")
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
