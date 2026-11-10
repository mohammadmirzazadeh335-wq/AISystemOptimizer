"""تنظیمات حقوق — نسخه‌های تاریخ‌دار نرخ‌ها و پله‌های مالیات."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.payroll import constants as P
from pars_erp.services.payroll_service import TaxBracketInput, VersionInput
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, MoneyEdit
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.form_dialog import FormDialog, fill_combo
from pars_erp.ui.table_specs import PAY_VERSION_COLUMNS, TEXT, AMOUNT, ColumnSpec
from pars_erp.ui.widgets.table import DataTable
from pars_erp.ui.pages.hr.widgets import hint_label

ITEM_COLUMNS = (
    ColumnSpec("title", "عنوان تنظیم", TEXT, None),
    ColumnSpec("value", "مقدار", TEXT, 140, "center"),
)
BRACKET_COLUMNS = (
    ColumnSpec("c0", "از مبلغ", AMOUNT, 160),
    ColumnSpec("c1", "تا مبلغ", AMOUNT, 160),
    ColumnSpec("c2", "نرخ (درصد)", TEXT, 120, "center"),
)


class BracketRow(QWidget):
    """One tax bracket: from / to / rate."""

    def __init__(self, values=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        low, high, rate = values or (None, None, None)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.from_edit = MoneyEdit()
        self.from_edit.set_amount(low if low is not None else None)
        self.to_edit = MoneyEdit()
        self.to_edit.set_amount(high if high is not None else None)
        self.to_edit.setPlaceholderText("بدون سقف")
        self.rate_edit = QLineEdit(f"{Decimal(rate):f}" if rate is not None else "")
        self.rate_edit.setPlaceholderText("درصد")
        self.rate_edit.setMaximumWidth(90)
        layout.addWidget(QLabel("از"))
        layout.addWidget(self.from_edit, 1)
        layout.addWidget(QLabel("تا"))
        layout.addWidget(self.to_edit, 1)
        layout.addWidget(QLabel("نرخ"))
        layout.addWidget(self.rate_edit)

    def value(self):
        rate_text = self.rate_edit.text().strip()
        if not rate_text:
            return None
        if self.from_edit.amount == 0 and not self.from_edit.text().strip():
            return None
        return TaxBracketInput(from_amount=self.from_edit.amount,
                               to_amount=(self.to_edit.amount
                                          if self.to_edit.text().strip() else None),
                               rate_percent=Decimal(rate_text))


class VersionDialog(FormDialog):
    title_fa = "نسخهٔ تنظیمات حقوق"
    width = 720

    def __init__(self, services, ctx, *, version=None, parent: QWidget | None = None) -> None:
        self.version = version
        super().__init__(services, ctx, parent=parent,
                         subtitle="هر نسخه از تاریخ مشخصی معتبر است؛ دوره‌های گذشته را "
                                  "تغییر نمی‌دهد. منبع رسمی هر نرخ را ثبت کنید.")

    def _build(self) -> None:
        version = self.version
        self.code_edit = QLineEdit(version.code if version else "")
        self.code_edit.setPlaceholderText("مثلاً V1405")
        self.title_edit = QLineEdit(version.title_fa if version else "")
        self.add_pair(("کد نسخه *", self.code_edit), ("عنوان *", self.title_edit),
                      left_required=True, right_required=True)
        self.from_edit = JalaliDateEdit(version.effective_from if version else _dt.date.today())
        self.to_edit = JalaliDateEdit(version.effective_to if version else None,
                                      allow_empty=True)
        self.add_pair(("معتبر از *", self.from_edit), ("معتبر تا", self.to_edit),
                      left_required=True)
        self.status_combo = fill_combo(
            QComboBox(), P.VERSION_STATUSES,
            current=version.status if version else P.VERSION_DRAFT, placeholder="")
        self.add_row("وضعیت", self.status_combo)
        self.source_edit = QLineEdit(version.source_note if version else "")
        self.source_edit.setPlaceholderText("مثلاً: قانون کار ۱۴۰۵ و بخشنامهٔ تأمین اجتماعی")
        self.add_row("منبع/مبنای قانونی", self.source_edit)
        self.notes_edit = QLineEdit(version.notes if version else "")
        self.add_row("یادداشت", self.notes_edit)

        self.add_section("مقادیر (همه به ریال به‌جز نسبت‌ها و درصدها)")
        self.item_edits: dict[str, MoneyEdit] = {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        current = version.items if version else {}
        for index, key in enumerate(P.PAY_SETTING_KEYS):
            title = P.PAY_SETTING_TITLES_FA.get(key, key)
            edit = MoneyEdit()
            edit.set_amount(current.get(key) or 0)
            container = QWidget()
            box = QVBoxLayout(container)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(2)
            label = QLabel(title)
            label.setObjectName("FieldLabel")
            label.setWordWrap(True)
            box.addWidget(label)
            box.addWidget(edit)
            if key in P.PERCENT_KEYS or key in P.FACTOR_KEYS:
                box.addWidget(hint_label("درصد/ضریب — مثلاً 0.07 یا 1.4"))
            grid.addWidget(container, index // 2, index % 2)
            self.item_edits[key] = edit
        holder = QWidget()
        holder.setLayout(grid)
        self.add_widget(holder)

        self.add_section("پله‌های مالیات بر درآمد")
        brackets = list(version.brackets) if version else []
        self.bracket_rows: list[BracketRow] = []
        for index in range(5):
            values = brackets[index] if index < len(brackets) else None
            row = BracketRow(values)
            self.bracket_rows.append(row)
            self.add_widget(row)
        self.add_widget(hint_label(
            "ردیف خالی نادیده گرفته می‌شود؛ «تا مبلغ» خالی یعنی بدون سقف (بالاترین پله)."))

    def save(self):
        items = {key: str(edit.amount) for key, edit in self.item_edits.items()}
        brackets = tuple(row.value() for row in self.bracket_rows if row.value() is not None)
        data = VersionInput(
            code=self.code_edit.text().strip(),
            title_fa=self.title_edit.text().strip(),
            effective_from=self.from_edit.date(),
            effective_to=self.to_edit.date(),
            status=str(self.status_combo.currentData()),
            source_note=self.source_edit.text().strip(),
            notes=self.notes_edit.text().strip(),
            items=items,
            brackets=brackets,
        )
        if self.version is None:
            return self.services.payroll.create_version(self.ctx, data)
        return self.services.payroll.update_version(self.ctx, self.version.id, data)


class PayrollSettingsPage(PageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.rows = []
        self.header = PageHeader(
            "تنظیمات حقوق",
            "نسخه‌های تاریخ‌دار نرخ بیمه، مالیات، مزایا و ضرایب؛ تغییر نرخ، محاسبات "
            "گذشته را تغییر نمی‌دهد")
        self.new_button = self.header.add_action("نسخهٔ جدید", slot=self._new)
        self.edit_button = self.header.add_action("ویرایش", variant="secondary",
                                                  slot=self._edit)
        self.activate_button = self.header.add_action("فعال‌سازی", variant="secondary",
                                                      slot=self._activate)
        self.root.addWidget(self.header)

        self.table = DataTable(PAY_VERSION_COLUMNS, formatter=formatter)
        self.table.on_selection_changed(self._show_detail)
        card = CardPanel("نسخه‌های تنظیمات")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        card.add_header_widget(self.summary)
        card.add(self.table, 1)
        self.root.addWidget(card, 3)

        detail = CardPanel("مقادیر نسخهٔ انتخاب‌شده")
        row = QHBoxLayout()
        items_card = CardPanel("تنظیمات")
        self.items_table = DataTable(ITEM_COLUMNS, formatter=formatter)
        items_card.add(self.items_table, 1)
        row.addWidget(items_card, 2)
        bracket_card = CardPanel("پله‌های مالیات")
        self.bracket_table = DataTable(BRACKET_COLUMNS, formatter=formatter)
        bracket_card.add(self.bracket_table, 1)
        row.addWidget(bracket_card, 1)
        detail.add_layout(row)
        self.root.addWidget(detail, 2)

        self.new_button.setEnabled(self.can("payroll.settings"))
        self.edit_button.setEnabled(self.can("payroll.settings"))
        self.activate_button.setEnabled(self.can("payroll.settings"))
        self.refresh()

    def refresh(self) -> None:
        try:
            self.rows = self.services.payroll.list_versions(self.ctx)
        except AppError as error:
            show_error(self, "تنظیمات حقوق", error)
            return
        self.set_rows(self.table, self.rows)
        active = sum(1 for row in self.rows if row.status == P.VERSION_ACTIVE)
        self.summary.setText(f"{len(self.rows):,} نسخه — {active:,} فعال")
        self._show_detail()

    def _selected(self):
        index = self.table.selected_row_index()
        if index is None or index >= len(self.rows):
            return None
        return self.rows[index]

    def _show_detail(self) -> None:
        version = self._selected()
        if version is None:
            self.items_table.set_rows([])
            self.bracket_table.set_rows([])
            return
        items = [{"title": P.PAY_SETTING_TITLES_FA.get(key, key),
                  "value": version.items.get(key, "0")} for key in P.PAY_SETTING_KEYS]
        self.items_table.set_rows(items)
        brackets = [{"c0": low, "c1": high, "c2": f"{rate:f}٪"}
                    for low, high, rate in version.brackets]
        self.bracket_table.set_rows(brackets)

    def _new(self) -> None:
        dialog = VersionDialog(self.services, self.ctx, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"نسخهٔ {dialog.saved.code} ایجاد شد.")

    def _edit(self) -> None:
        version = self._selected()
        if version is None:
            show_info(self, "ویرایش نسخه", "ابتدا یک نسخه را انتخاب کنید.")
            return
        dialog = VersionDialog(self.services, self.ctx, version=version, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"نسخهٔ {version.code} به‌روزرسانی شد.")

    def _activate(self) -> None:
        version = self._selected()
        if version is None:
            show_info(self, "فعال‌سازی", "ابتدا یک نسخه را انتخاب کنید.")
            return
        try:
            self.services.payroll.activate_version(self.ctx, version.id)
        except AppError as error:
            show_error(self, "فعال‌سازی نسخه", error)
            return
        self.refresh()
        self.notify(f"نسخهٔ {version.code} فعال شد.")
