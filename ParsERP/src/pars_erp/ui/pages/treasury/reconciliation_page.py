"""Bank reconciliation: statement import, matching and discrepancy handling."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.services.reconciliation_service import StatementLineInput, StatementRow
from pars_erp.treasury import constants as TC
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, MoneyEdit
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.treasury.widgets import (
    PickCombo,
    ask_reason,
    build_table,
    show_preview,
)
from pars_erp.ui.table_specs import AMOUNT, BADGE, DATE, TEXT, ColumnSpec
from pars_erp.ui.widgets.table import DataTable

STATEMENT_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("bank_label", "حساب بانکی", TEXT, None),
    ColumnSpec("statement_date", "تاریخ صورت‌حساب", DATE, 130, "center"),
    ColumnSpec("period_start", "از", DATE, 96, "center"),
    ColumnSpec("period_end", "تا", DATE, 96, "center"),
    ColumnSpec("opening_balance", "مانده ابتدا", AMOUNT, 130),
    ColumnSpec("closing_balance", "مانده بانک", AMOUNT, 130),
    ColumnSpec("line_count", "ردیف‌ها", TEXT, 80, "center"),
    ColumnSpec("unmatched_count", "تطبیق‌نشده", TEXT, 96, "center"),
)

LINE_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("tx_date", "تاریخ", DATE, 96, "center"),
    ColumnSpec("description", "شرح", TEXT, None),
    ColumnSpec("reference", "مرجع", TEXT, 110, "center"),
    ColumnSpec("amount_in", "واریز", AMOUNT, 120),
    ColumnSpec("amount_out", "برداشت", AMOUNT, 120),
    ColumnSpec("status_fa", "وضعیت", BADGE, 110, "center",
               getter=lambda row: row.status),
    ColumnSpec("matched_label", "تطبیق با", TEXT, 180),
)


class StatementDialog(QDialog):
    """Create a statement by hand (the CSV/Excel path is a separate button)."""

    def __init__(self, services, ctx, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.saved = None
        self.setWindowTitle("صورت‌حساب بانکی جدید")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.bank_combo = PickCombo()
        try:
            self.bank_combo.load(services.funds.bank_account_choices(ctx))
        except AppError:
            self.bank_combo.load([])
        form.addRow("حساب بانکی *", self.bank_combo)
        self.date_edit = JalaliDateEdit(_dt.date.today())
        form.addRow("تاریخ صورت‌حساب", self.date_edit)
        self.from_edit = JalaliDateEdit(_dt.date.today().replace(day=1))
        form.addRow("از تاریخ", self.from_edit)
        self.to_edit = JalaliDateEdit(_dt.date.today())
        form.addRow("تا تاریخ", self.to_edit)
        self.opening_edit = MoneyEdit()
        form.addRow("مانده ابتدای صورت‌حساب", self.opening_edit)
        self.closing_edit = MoneyEdit()
        form.addRow("مانده انتهای صورت‌حساب", self.closing_edit)
        self.note_edit = QPlainTextEdit()
        self.note_edit.setFixedHeight(50)
        form.addRow("توضیح", self.note_edit)
        layout.addLayout(form)
        hint = QLabel("برای ورود انبوه ردیف‌ها از دکمهٔ «ورود فایل CSV/Excel» استفاده کنید.")
        hint.setObjectName("HintText")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox()
        save = buttons.addButton("ذخیره", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        try:
            self.saved = self.services.reconciliation.create_statement(
                self.ctx, bank_account_id=self.bank_combo.value() or 0,
                statement_date=self.date_edit.date() or _dt.date.today(),
                period_start=self.from_edit.date() or _dt.date.today(),
                period_end=self.to_edit.date() or _dt.date.today(),
                opening_balance=self.opening_edit.amount,
                closing_balance=self.closing_edit.amount,
                note=self.note_edit.toPlainText().strip(),
                lines=(StatementLineInput(tx_date=self.date_edit.date() or _dt.date.today(),
                                          description="ردیف افتتاحیه", amount_in=1),))
        except AppError as error:
            show_error(self, "صورت‌حساب", error)
            return
        self.accept()


class ReconciliationPage(PageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.statements: list[StatementRow] = []
        self.lines: list = []
        self.header = PageHeader(
            "مغایرت‌گیری بانکی",
            "ورود صورت‌حساب، تطبیق خودکار/دستی، فهرست تطبیق‌نشده‌ها و سند اصلاحی با تأیید")
        self.header.add_action("صورت‌حساب جدید", slot=self._create)
        self.header.add_action("ورود CSV/Excel", variant="secondary", slot=self._import)
        self.header.add_action("تطبیق خودکار", variant="secondary", slot=self._auto_match)
        self.header.add_action("تطبیق دستی", variant="secondary", slot=self._match)
        self.header.add_action("سند اصلاحی", variant="secondary", slot=self._adjust)
        self.header.add_action("گزارش مغایرت", variant="secondary", slot=self._discrepancy)
        self.root.addWidget(self.header)

        self.statement_table = DataTable(STATEMENT_COLUMNS, formatter=formatter)
        self.statement_table.rowActivated.connect(lambda _row: self._load_lines())
        card = CardPanel("صورت‌حساب‌ها")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        card.add_header_widget(self.summary)
        card.add(self.statement_table, 1)
        self.root.addWidget(card, 1)
        self.line_table = DataTable(LINE_COLUMNS, formatter=formatter)
        lines_card = CardPanel("ردیف‌های صورت‌حساب")
        self.line_label = QLabel("یک صورت‌حساب را انتخاب کنید.")
        self.line_label.setObjectName("HintText")
        lines_card.add_header_widget(self.line_label)
        lines_card.add(self.line_table, 1)
        self.root.addWidget(lines_card, 1)
        self.refresh()

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        try:
            self.statements = self.services.reconciliation.list_statements(self.ctx)
        except AppError as error:
            show_error(self, "مغایرت‌گیری", error)
            return
        self.statement_table.set_rows(self.statements)
        unmatched = sum(row.unmatched_count for row in self.statements)
        self.summary.setText(f"{len(self.statements):,} صورت‌حساب — "
                             f"{unmatched:,} ردیف تطبیق‌نشده")

    def _selected(self) -> StatementRow | None:
        index = self.statement_table.currentIndex()
        if not index.isValid() or index.row() >= len(self.statements):
            return None
        return self.statements[index.row()]

    def _load_lines(self) -> None:
        statement = self._selected()
        if statement is None:
            return
        try:
            self.lines = self.services.reconciliation.statement_lines(self.ctx,
                                                                      statement.id)
        except AppError as error:
            show_error(self, "ردیف‌ها", error)
            return
        self.line_table.set_rows(self.lines)
        self.line_label.setText(f"{statement.bank_label} — {len(self.lines):,} ردیف")

    def _selected_line(self):
        index = self.line_table.currentIndex()
        if not index.isValid() or index.row() >= len(self.lines):
            return None
        return self.lines[index.row()]

    # --------------------------------------------------------------- actions
    def _create(self) -> None:
        dialog = StatementDialog(self.services, self.ctx, parent=self)
        if dialog.exec():
            self.refresh()
            self.statusMessage.emit("صورت‌حساب ثبت شد.")

    def _import(self) -> None:
        bank_id = None
        try:
            choices = self.services.funds.bank_account_choices(self.ctx)
        except AppError as error:
            show_error(self, "ورود فایل", error)
            return
        if not choices:
            show_info(self, "ورود فایل", "ابتدا یک حساب بانکی تعریف کنید.")
            return
        bank_id = choices[0][0]
        path, _filter = QFileDialog.getOpenFileName(
            self, "انتخاب فایل صورت‌حساب", "",
            "صورت‌حساب (*.csv *.xlsx *.xlsm);;همه فایل‌ها (*)")
        if not path:
            return
        try:
            statement = self.services.reconciliation.import_file(
                self.ctx, bank_account_id=bank_id, path=path)
        except AppError as error:
            show_error(self, "ورود فایل", error)
            return
        self.refresh()
        self.statusMessage.emit(f"{statement.line_count:,} ردیف از «{statement.file_name}» "
                                "خوانده شد.")

    def _auto_match(self) -> None:
        statement = self._selected()
        if statement is None:
            show_info(self, "تطبیق خودکار", "یک صورت‌حساب را انتخاب کنید.")
            return
        try:
            result = self.services.reconciliation.auto_match(self.ctx, statement.id)
        except AppError as error:
            show_error(self, "تطبیق خودکار", error)
            return
        self.refresh()
        self._load_lines()
        self.statusMessage.emit(
            f"{result['matched']:,} ردیف تطبیق شد؛ {result['ambiguous']:,} ردیف مبهم ماند.")

    def _match(self) -> None:
        line = self._selected_line()
        statement = self._selected()
        if line is None or statement is None:
            show_info(self, "تطبیق دستی", "یک ردیف از صورت‌حساب را انتخاب کنید.")
            return
        try:
            kind = "receipt" if float(line.amount_in or 0) > 0 else "payment"
            from pars_erp.db.models import Payment, Receipt

            with self.services.db.session_scope() as session:
                model = Receipt if kind == "receipt" else Payment
                amount = Decimal(line.amount_in or 0) + Decimal(line.amount_out or 0)
                bank_id = statement.bank_account_id
                candidates = [row for row in session.query(model).filter(
                    model.bank_account_id == bank_id,
                    model.status == TC.STATUS_POSTED).all()
                    if Decimal(row.base_amount) == amount]
            if not candidates:
                show_info(self, "تطبیق دستی",
                          "سند هم‌مبلغی در این حساب بانکی پیدا نشد؛ می‌توانید سند اصلاحی "
                          "ثبت کنید.")
                return
            chosen = self.services.reconciliation.match_manually(
                self.ctx, line.id, kind=kind, document_id=candidates[0].id)
        except AppError as error:
            show_error(self, "تطبیق دستی", error)
            return
        self._load_lines()
        self.statusMessage.emit(f"ردیف با سند {chosen.matched_label} تطبیق شد.")

    def _adjust(self) -> None:
        line = self._selected_line()
        if line is None:
            show_info(self, "سند اصلاحی", "یک ردیف را انتخاب کنید.")
            return
        reason = ask_reason(self, "سند اصلاحی",
                            "دلیل اصلاح مغایرت را بنویسید (حداقل ۵ نویسه):")
        if not reason:
            return
        try:
            accounts = self.services.accounts.choices(self.ctx, level="subsidiary")
        except AppError as error:
            show_error(self, "سند اصلاحی", error)
            return
        from PySide6.QtWidgets import QInputDialog

        labels = [label for _id, label in accounts]
        label, accepted = QInputDialog.getItem(
            self, "حساب طرف مقابل", "حساب طرف مقابل سند اصلاحی:", labels, 0, False)
        if not accepted:
            return
        account_id = accounts[labels.index(label)][0]
        try:
            self.services.reconciliation.create_adjustment(
                self.ctx, line.id, counter_account_id=account_id, reason=reason)
        except AppError as error:
            show_error(self, "سند اصلاحی", error)
            return
        self._load_lines()
        self.statusMessage.emit("سند اصلاحی ثبت و ردیف تطبیق شد.")

    def _discrepancy(self) -> None:
        statement = self._selected()
        if statement is None:
            show_info(self, "گزارش مغایرت", "یک صورت‌حساب را انتخاب کنید.")
            return
        try:
            report = self.services.reconciliation.discrepancy_report(self.ctx,
                                                                      statement.id)
        except AppError as error:
            show_error(self, "گزارش مغایرت", error)
            return
        table = build_table(
            "گزارش مغایرت بانکی",
            ("شرح", "مبلغ"),
            (("مانده انتهای صورت‌حساب", report["statement_closing"]),
             ("مانده اسناد (دفتر)", report["open_balance_according_to_documents"]),
             ("جمع ردیف‌های تطبیق‌شده", report["matched_amount"]),
             ("مانده مورد انتظار", report["expected_balance"]),
             ("مغایرت", report["difference"]),
             ("ردیف‌های تطبیق‌نشده", len(report["unmatched_lines"]))),
            meta=report["bank_label"],
            company=self.services.settings.snapshot().company_name)
        show_preview(self, self.services, table)
