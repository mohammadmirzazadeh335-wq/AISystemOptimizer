"""Commerce settings: valuation method and the configurable posting patterns."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pars_erp.commerce import constants as CC
from pars_erp.core.errors import AppError
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.commerce.widgets import PickCombo, confirm, form_row
from pars_erp.ui.table_specs import TEXT, ColumnSpec
from pars_erp.ui.widgets.table import DataTable

RULE_COLUMNS = (
    ColumnSpec("operation_fa", "عملیات", TEXT, 150),
    ColumnSpec("title_fa", "عنوان الگو", TEXT, None),
    ColumnSpec("status", "وضعیت", TEXT, 80, "center",
               getter=lambda row: "فعال" if row.is_active else "غیرفعال"),
)

RULE_LINE_COLUMNS = (
    ColumnSpec("side_fa", "طرف", TEXT, 80, "center"),
    ColumnSpec("account_label", "حساب معین", TEXT, None),
    ColumnSpec("amount_source_fa", "منبع مبلغ", TEXT, 150),
    ColumnSpec("description", "شرح", TEXT, 180),
)


class CommerceSettingsPage(PageBase):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.header = PageHeader(
            "تنظیمات بازرگانی",
            "روش ارزش‌گذاری موجودی و الگوهای ثبت خودکار اسناد حسابداری")
        self.header.add_action("ایجاد الگوهای پیش‌فرض", slot=self._seed)
        self.header.add_action("ذخیرهٔ ردیف‌ها", variant="primary", slot=self._save_rule)
        self.root.addWidget(self.header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_policy_tab(), "سیاست‌ها")
        self.tabs.addTab(self._build_rules_tab(), "الگوهای ثبت حسابداری")
        self.tabs.currentChanged.connect(lambda _index: self.refresh())
        self.root.addWidget(self.tabs, 1)
        self.refresh()

    # ------------------------------------------------------------------ tabs
    def _build_policy_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)
        card = CardPanel("روش ارزش‌گذاری موجودی",
                         "تغییر روش، اسناد و کاردکس گذشته را بازنویسی نمی‌کند؛ "
                         "فقط خروج‌های بعدی با روش جدید ارزش‌گذاری می‌شوند.")
        row = QHBoxLayout()
        self.method_combo = QComboBox()
        for method in CC.VALUATION_METHODS:
            self.method_combo.addItem(CC.VALUATION_TITLES_FA[method], method)
        row.addWidget(form_row("روش پیش‌فرض شرکت", self.method_combo), 1)
        save = QPushButton("ذخیره")
        save.setProperty("variant", "primary")
        save.clicked.connect(self._save_method)
        row.addWidget(save, alignment=Qt.AlignmentFlag.AlignBottom)
        row.addStretch(2)
        card.add_layout(row)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _build_rules_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)
        top = QHBoxLayout()
        self.operation_combo = PickCombo()
        self.operation_combo.load([(operation, CC.POSTING_TITLES_FA[operation])
                                   for operation in CC.POSTING_OPERATIONS],
                                  placeholder="")
        self.operation_combo.currentIndexChanged.connect(self._load_rule)
        top.addWidget(form_row("عملیات", self.operation_combo), 2)
        top.addStretch(1)
        layout.addLayout(top)

        self.rule_table = DataTable(RULE_COLUMNS, formatter=self.formatter)
        self.rule_table.on_selection_changed(lambda *_a: self._load_rule())
        layout.addWidget(self.rule_table, 1)

        self.line_table = DataTable(RULE_LINE_COLUMNS, formatter=self.formatter)
        layout.addWidget(QLabel("ردیف‌های الگوی انتخاب‌شده"))
        layout.addWidget(self.line_table, 1)

        editor = QHBoxLayout()
        self.side_combo = QComboBox()
        for side in CC.SIDES:
            self.side_combo.addItem(CC.SIDE_TITLES_FA[side], side)
        editor.addWidget(form_row("طرف", self.side_combo), 1)
        self.account_combo = PickCombo()
        try:
            self.account_combo.load(
                [(row.id, f"{row.code} — {row.title_fa}")
                 for row in self.services.accounts.list_accounts(
                     self.ctx, level="subsidiary", active=None)])
        except AppError:
            pass
        editor.addWidget(form_row("حساب معین", self.account_combo), 2)
        self.source_combo = QComboBox()
        for source in CC.AMOUNT_SOURCES:
            self.source_combo.addItem(CC.AMOUNT_SOURCE_TITLES_FA[source], source)
        editor.addWidget(form_row("منبع مبلغ", self.source_combo), 1)
        add = QPushButton("افزودن ردیف")
        add.clicked.connect(self._add_line)
        editor.addWidget(add, alignment=Qt.AlignmentFlag.AlignBottom)
        remove = QPushButton("حذف ردیف")
        remove.setProperty("variant", "ghost")
        remove.clicked.connect(self._remove_line)
        editor.addWidget(remove, alignment=Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(editor)

        reset = QPushButton("بازگردانی الگوی پیشنهادی برای این عملیات")
        reset.setProperty("variant", "ghost")
        reset.clicked.connect(self._reset_rule)
        layout.addWidget(reset, alignment=Qt.AlignmentFlag.AlignLeft)
        self._pending_lines: list[tuple[str, int, str, str]] = []
        return page

    # --------------------------------------------------------------- refresh
    def refresh(self) -> None:
        try:
            snapshot = self.services.settings.snapshot()
            current = snapshot.str("commerce_valuation_method")
            self.method_combo.setCurrentIndex(max(0, self.method_combo.findData(current)))
            self.rule_table.set_rows(self.services.posting.list_rules(self.ctx))
        except AppError as error:
            show_error(self, "تنظیمات بازرگانی", error)
            return
        if self.operation_combo.count() and self.rule_table.model.rows():
            self._select_rule_for_operation()

    def _select_rule_for_operation(self) -> None:
        operation = self.operation_combo.currentData()
        for row in self.rule_table.model.rows():
            if row.operation == operation:
                self._pending_lines = [(line.side, line.account_id,
                                        line.amount_source, line.description)
                                       for line in row.lines]
                self.line_table.set_rows(row.lines)
                return
        self._pending_lines = []
        self.line_table.set_rows([])

    def _load_rule(self, *_args) -> None:
        index = self.rule_table.selected_row_index()
        if index is not None:
            row = self.rule_table.model.row_at(index)
            self.operation_combo.set_value(row.operation)
            self._pending_lines = [(line.side, line.account_id, line.amount_source,
                                    line.description) for line in row.lines]
            self.line_table.set_rows(row.lines)
            return
        self._select_rule_for_operation()

    # --------------------------------------------------------------- actions
    def _save_method(self) -> None:
        try:
            self.services.settings.update(
                self.ctx, {"commerce_valuation_method": str(self.method_combo.currentData())})
        except AppError as error:
            show_error(self, "روش ارزش‌گذاری", error)
            return
        self.notify("روش ارزش‌گذاری ذخیره شد؛ اسناد گذشته تغییری نمی‌کنند.")

    def _seed(self) -> None:
        if not confirm(self, "الگوهای پیش‌فرض",
                       "برای عملیات‌هایی که الگو ندارند، الگوی پیشنهادی ساخته شود؟"):
            return
        try:
            created = self.services.posting.ensure_default_rules(self.ctx)
        except AppError as error:
            show_error(self, "الگوهای پیش‌فرض", error)
            return
        self.refresh()
        self.notify(f"{created} الگوی پیش‌فرض ایجاد شد.")

    def _add_line(self) -> None:
        if self.account_combo.value() is None:
            show_info(self, "افزودن ردیف", "حساب معین را انتخاب کنید.")
            return
        self._pending_lines.append((str(self.side_combo.currentData()),
                                    self.account_combo.value(),
                                    str(self.source_combo.currentData()), ""))
        self.line_table.set_rows([
            {"side_fa": CC.SIDE_TITLES_FA[side],
             "account_label": dict(self._accounts())[account_id],
             "amount_source_fa": CC.AMOUNT_SOURCE_TITLES_FA[source],
             "description": description}
            for side, account_id, source, description in self._pending_lines])

    def _accounts(self):
        try:
            return [(row.id, f"{row.code} — {row.title_fa}")
                    for row in self.services.accounts.list_accounts(
                        self.ctx, level="subsidiary", active=None)]
        except AppError:  # pragma: no cover
            return []

    def _remove_line(self) -> None:
        index = self.line_table.selected_row_index()
        if index is None:
            show_info(self, "حذف ردیف", "ابتدا یک ردیف را انتخاب کنید.")
            return
        del self._pending_lines[index]
        self.line_table.set_rows([
            {"side_fa": CC.SIDE_TITLES_FA[side],
             "account_label": dict(self._accounts())[account_id],
             "amount_source_fa": CC.AMOUNT_SOURCE_TITLES_FA[source],
             "description": description}
            for side, account_id, source, description in self._pending_lines])

    def _save_rule(self) -> None:
        operation = str(self.operation_combo.currentData() or "")
        if operation not in CC.POSTING_OPERATIONS:
            show_info(self, "ذخیرهٔ الگو", "عملیات را انتخاب کنید.")
            return
        if not self._pending_lines:
            show_info(self, "ذخیرهٔ الگو",
                      "الگو باید حداقل یک ردیف داشته باشد؛ ابتدا ردیف اضافه کنید.")
            return
        try:
            self.services.posting.save_rule(
                self.ctx, operation,
                lines=tuple(self._pending_lines))
        except AppError as error:
            show_error(self, "ذخیرهٔ الگو", error)
            return
        self.refresh()
        self.notify(f"الگوی «{CC.POSTING_TITLES_FA[operation]}» ذخیره شد.")

    def _reset_rule(self) -> None:
        from pars_erp.services.posting_service import DEFAULT_RULE_TEMPLATES

        operation = str(self.operation_combo.currentData() or "")
        template = DEFAULT_RULE_TEMPLATES.get(operation)
        if template is None:
            show_info(self, "بازگردانی", "برای این عملیات الگوی پیشنهادی تعریف نشده است.")
            return
        mapping = {code: account_id for account_id, label in self._accounts()
                   for code in [label.split(" — ")[0].strip()]}
        lines = []
        for side, source, account_code in template:
            account_id = mapping.get(account_code)
            if account_id:
                lines.append((side, account_id, source, ""))
        if not lines:
            show_info(self, "بازگردانی",
                      "حساب‌های استاندارد در کدینگ شرکت یافت نشد؛ "
                      "لطفاً ردیف‌ها را دستی انتخاب کنید.")
            return
        self._pending_lines = lines
        self.line_table.set_rows([
            {"side_fa": CC.SIDE_TITLES_FA[side],
             "account_label": dict(self._accounts())[account_id],
             "amount_source_fa": CC.AMOUNT_SOURCE_TITLES_FA[source],
             "description": ""} for side, account_id, source, _ in lines])
