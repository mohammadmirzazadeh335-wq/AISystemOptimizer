"""Chart-of-accounts screen: four-level coding plus detail (تفصیلی) accounts.

The screen never computes anything financial - it collects input, calls
:class:`~pars_erp.services.accounts_service.AccountService` (which validates the
structure, the code mask and the permissions) and shows the result. That is why
every rule the accountant sees is also enforced for the CLI and for tests.
"""

from __future__ import annotations

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
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pars_erp.accounting import constants as C
from pars_erp.core.errors import AppError
from pars_erp.services.accounts_service import AccountInput, AccountRow
from pars_erp.services.parties_service import DetailInput
from pars_erp.ui.dialogs.common_dialogs import ConfirmDialog, show_error, show_info
from pars_erp.ui.pages.accounting.widgets import AccountPicker, form_row
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.table_specs import BADGE, TEXT, ColumnSpec
from pars_erp.ui.widgets.common import SearchInput
from pars_erp.ui.widgets.table import DataTable

ACCOUNT_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("code", "کد", TEXT, 88, "center"),
    ColumnSpec("title_fa", "عنوان حساب", TEXT, None),
    ColumnSpec("level_fa", "سطح", TEXT, 76, "center"),
    ColumnSpec("account_type_fa", "نوع", TEXT, 86, "center"),
    ColumnSpec("nature_fa", "ماهیت", TEXT, 82, "center"),
    ColumnSpec("status", "وضعیت", BADGE, 74, "center",
               getter=lambda row: "active" if row.is_active else "inactive"),
    ColumnSpec("statement_section_fa", "بخش صورت‌ها", TEXT, 132),
)

DETAIL_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("code", "کد تفصیلی", TEXT, 100, "center"),
    ColumnSpec("name", "عنوان", TEXT, None),
    ColumnSpec("kind_fa", "نوع", TEXT, 100, "center"),
    ColumnSpec("account_label", "حساب معین", TEXT, 200),
    ColumnSpec("phone", "تلفن", TEXT, 110, "center"),
    ColumnSpec("national_id", "شناسه/کد ملی", TEXT, 130, "center"),
    ColumnSpec("status", "وضعیت", BADGE, 86, "center",
               getter=lambda row: "active" if row.is_active else "inactive"),
)


class AccountDialog(QDialog):
    """Create/edit one account; the parent/code suggestion follows the tree."""

    def __init__(self, services, ctx, *, account: AccountRow | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.account = account
        self.saved: AccountRow | None = None
        self.setWindowTitle("ویرایش حساب" if account else "حساب جدید")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        mask_note = QLabel("ساختار کدینگ: " + self.services.accounts.describe_mask())
        mask_note.setObjectName("HintText")
        layout.addWidget(mask_note)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.level_combo = QComboBox()
        for level in C.ACCOUNT_LEVELS:
            self.level_combo.addItem(C.LEVEL_TITLES_FA[level], level)
        form.addRow("سطح حساب", self.level_combo)

        self.parent_picker = AccountPicker()
        form.addRow("حساب والد", self.parent_picker)

        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("مثلاً ۱۰۱۰۰۱")
        form.addRow("کد حساب", self.code_edit)

        self.title_edit = QLineEdit()
        form.addRow("عنوان حساب", self.title_edit)

        self.type_combo = QComboBox()
        for account_type in C.ACCOUNT_TYPES:
            self.type_combo.addItem(C.TYPE_TITLES_FA[account_type], account_type)
        form.addRow("نوع حساب", self.type_combo)

        self.nature_combo = QComboBox()
        for nature in C.NATURES:
            self.nature_combo.addItem(C.NATURE_TITLES_FA[nature], nature)
        form.addRow("ماهیت", self.nature_combo)

        self.section_combo = QComboBox()
        form.addRow("بخش صورت‌های مالی", self.section_combo)

        self.active_check = QCheckBox("حساب فعال است")
        self.active_check.setChecked(True)
        form.addRow("", self.active_check)

        self.description_edit = QPlainTextEdit()
        self.description_edit.setFixedHeight(64)
        form.addRow("توضیحات", self.description_edit)
        layout.addLayout(form)

        self.hint = QLabel("")
        self.hint.setObjectName("HintText")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        buttons = QDialogButtonBox()
        self.save_button = buttons.addButton("ذخیره", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        self.save_button.setProperty("variant", "primary")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.level_combo.currentIndexChanged.connect(self._on_level_changed)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        self.parent_picker.accountChanged.connect(self._on_parent_changed)

        if account is not None:
            self._load(account)
        else:
            self._on_level_changed()

    # --------------------------------------------------------------- helpers
    def _level(self) -> str:
        return str(self.level_combo.currentData())

    def _load(self, account: AccountRow) -> None:
        index = self.level_combo.findData(account.level)
        self.level_combo.setCurrentIndex(max(0, index))
        self.code_edit.setText(account.code)
        self.title_edit.setText(account.title_fa)
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(account.account_type)))
        self.nature_combo.setCurrentIndex(max(0, self.nature_combo.findData(account.nature)))
        self.active_check.setChecked(account.is_active)
        self.description_edit.setPlainText(account.description or "")
        self._on_level_changed(preserve=True)
        if account.parent_id:
            self.parent_picker.set_account(account.parent_id)
        self._on_type_changed(account.statement_section)

    def _on_level_changed(self, *_args, preserve: bool = False) -> None:
        level = self._level()
        parent_level = C.PARENT_LEVEL.get(level)
        self.parent_picker.setEnabled(parent_level is not None)
        if parent_level is None:
            self.parent_picker.load([], placeholder="— سطح اول، بدون والد —", empty=True)
        else:
            try:
                choices = [(row.id, row.display)
                           for row in self.services.accounts.list_accounts(
                               self.ctx, level=parent_level, active=None)]
            except AppError:
                choices = []
            self.parent_picker.load(choices, placeholder="— انتخاب حساب والد —")
        if not preserve:
            self._suggest_code()
        self._update_hint()

    def _on_parent_changed(self, _account_id) -> None:
        if self.account is None:
            self._suggest_code()

    def _on_type_changed(self, *_args) -> None:
        account_type = self.type_combo.currentData()
        suggested = C.TYPE_NATURE.get(str(account_type))
        if suggested:
            index = self.nature_combo.findData(suggested)
            if index >= 0:
                self.nature_combo.setCurrentIndex(index)
        self.section_combo.clear()
        self.section_combo.addItem("— تعیین نشده —", None)
        for section in C.SECTIONS_FOR_TYPE.get(str(account_type), ()):
            self.section_combo.addItem(C.SECTION_TITLES_FA.get(section, section), section)

    def _suggest_code(self) -> None:
        try:
            suggestion = self.services.accounts.next_suggested_code(
                self.ctx, self.parent_picker.current_account_id(), self._level())
        except AppError:
            return
        if suggestion:
            self.code_edit.setText(suggestion)

    def _update_hint(self) -> None:
        length = self._expected_length()
        self.hint.setText(
            f"کد این سطح {length} رقم است و باید با کد حساب والد آغاز شود.")

    def _expected_length(self) -> int:
        try:
            from pars_erp.services.accounting_common import expected_code_length
            return expected_code_length(self._level(), self.services.accounts.code_mask()) or 0
        except Exception:  # pragma: no cover - defensive
            return 0

    # ------------------------------------------------------------------ save
    def _save(self) -> None:
        data = AccountInput(
            code=self.code_edit.text().strip(),
            title_fa=self.title_edit.text().strip(),
            level=self._level(),
            account_type=str(self.type_combo.currentData()),
            nature=str(self.nature_combo.currentData()),
            parent_id=self.parent_picker.current_account_id(),
            statement_section=self.section_combo.currentData(),
            description=self.description_edit.toPlainText().strip(),
            is_active=self.active_check.isChecked(),
        )
        try:
            if self.account is None:
                self.saved = self.services.accounts.create(self.ctx, data)
            else:
                self.saved = self.services.accounts.update(self.ctx, self.account.id, data)
        except AppError as error:
            show_error(self, "ثبت حساب", error)
            return
        self.accept()


class DetailAccountDialog(QDialog):
    """Create/edit a detail (تفصیلی) account: customer, bank, employee, …"""

    def __init__(self, services, ctx, *, detail=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.detail = detail
        self.saved = None
        self.setWindowTitle("ویرایش حساب تفصیلی" if detail else "حساب تفصیلی جدید")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.kind_combo = QComboBox()
        for kind, title in C.DETAIL_KIND_TITLES_FA.items():
            self.kind_combo.addItem(title, kind)
        form.addRow("نوع تفصیلی", self.kind_combo)

        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("مثلاً 101001-001")
        form.addRow("کد", self.code_edit)

        self.name_edit = QLineEdit()
        form.addRow("عنوان", self.name_edit)

        self.account_picker = AccountPicker()
        try:
            choices = [(row.id, row.display) for row in self.services.accounts.list_accounts(
                self.ctx, level=C.LEVEL_SUBSIDIARY, active=None)]
        except AppError:
            choices = []
        self.account_picker.load(choices, placeholder="— انتخاب حساب معین —")
        form.addRow("حساب معین", self.account_picker)

        self.phone_edit = QLineEdit()
        form.addRow("تلفن", self.phone_edit)
        self.national_edit = QLineEdit()
        form.addRow("کد ملی / شناسه ملی", self.national_edit)
        self.address_edit = QPlainTextEdit()
        self.address_edit.setFixedHeight(56)
        form.addRow("نشانی", self.address_edit)
        self.description_edit = QPlainTextEdit()
        self.description_edit.setFixedHeight(48)
        form.addRow("توضیحات", self.description_edit)
        self.active_check = QCheckBox("فعال است")
        self.active_check.setChecked(True)
        form.addRow("", self.active_check)
        layout.addLayout(form)

        buttons = QDialogButtonBox()
        self.save_button = buttons.addButton("ذخیره", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        self.save_button.setProperty("variant", "primary")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if detail is not None:
            self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(detail.kind)))
            self.code_edit.setText(detail.code)
            self.name_edit.setText(detail.name)
            self.account_picker.set_account(detail.account_id)
            self.phone_edit.setText(detail.phone or "")
            self.national_edit.setText(detail.national_id or "")
            self.address_edit.setPlainText(detail.address or "")
            self.description_edit.setPlainText(detail.description or "")
            self.active_check.setChecked(detail.is_active)

    def _save(self) -> None:
        data = DetailInput(
            code=self.code_edit.text().strip(),
            name=self.name_edit.text().strip(),
            kind=str(self.kind_combo.currentData()),
            account_id=self.account_picker.current_account_id(),
            phone=self.phone_edit.text().strip(),
            national_id=self.national_edit.text().strip(),
            address=self.address_edit.toPlainText().strip(),
            description=self.description_edit.toPlainText().strip(),
            is_active=self.active_check.isChecked(),
        )
        try:
            if self.detail is None:
                self.saved = self.services.parties.create(self.ctx, data)
            else:
                self.saved = self.services.parties.update(self.ctx, self.detail.id, data)
        except AppError as error:
            show_error(self, "ثبت حساب تفصیلی", error)
            return
        self.accept()


class AccountsPage(PageBase):
    """Chart of accounts + detail accounts, in two tabs."""

    def __init__(self, services, ctx, formatter, *, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self._rows: list[AccountRow] = []
        self._details: list = []

        self.header = PageHeader("کدینگ حساب‌ها",
                                 "ساختار چهارسطحی: گروه ← حساب کل ← حساب معین ← تفصیلی")
        self.new_button = self.header.add_action("حساب جدید", slot=self._new_account,
                                                 tooltip="افزودن حساب در هر سطح")
        self.new_detail_button = self.header.add_action("تفصیلی جدید", variant="ghost",
                                                        slot=self._new_detail)
        self.setup_button = self.header.add_action(
            "بارگذاری کدینگ استاندارد", variant="ghost", slot=self._load_standard,
            tooltip="درج کدینگ استاندارد ایرانی در صورت خالی بودن ساختار")
        self.header.add_action("بازخوانی", variant="ghost", slot=self.refresh)
        self.root.addWidget(self.header)

        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)
        self._build_accounts_tab()
        self._build_details_tab()

    # -------------------------------------------------------------- accounts
    def _build_accounts_tab(self) -> None:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        tree_card = CardPanel("درخت حساب‌ها")
        tree_card.setMinimumWidth(300)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["عنوان", "کد"])
        self.tree.setColumnWidth(0, 210)
        self.tree.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.tree.itemClicked.connect(self._on_tree_clicked)
        tree_card.add(self.tree)
        layout.addWidget(tree_card)

        table_card = CardPanel("فهرست حساب‌ها")
        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.search = SearchInput("جست‌وجو در کد یا عنوان حساب…")
        self.search.searchChanged.connect(lambda _text: self._apply_filter())
        filters.addWidget(self.search, 1)

        self.level_filter = QComboBox()
        self.level_filter.addItem("همه سطوح", None)
        for level in C.ACCOUNT_LEVELS:
            self.level_filter.addItem(C.LEVEL_TITLES_FA[level], level)
        self.level_filter.currentIndexChanged.connect(lambda _i: self.refresh())
        filters.addWidget(self.level_filter)

        self.active_filter = QComboBox()
        self.active_filter.addItem("همه وضعیت‌ها", None)
        self.active_filter.addItem("فعال", True)
        self.active_filter.addItem("غیرفعال", False)
        self.active_filter.currentIndexChanged.connect(lambda _i: self.refresh())
        filters.addWidget(self.active_filter)
        table_card.add_layout(filters)

        self.table = DataTable(ACCOUNT_COLUMNS, formatter=self.formatter)
        self.table.rowActivated.connect(self._edit_selected)
        table_card.add(self.table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        for text, slot, variant in (
                ("ویرایش", self._edit_selected, "ghost"),
                ("فعال/غیرفعال", self._toggle_active, "ghost"),
                ("حذف", self._delete_account, "ghost"),
                ("بخش صورت‌های مالی", self._set_section, "ghost")):
            button = QPushButton(text)
            button.setProperty("variant", variant)
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch(1)
        self.count_label = QLabel("—")
        self.count_label.setObjectName("HintText")
        actions.addWidget(self.count_label)
        table_card.add_layout(actions)
        layout.addWidget(table_card, 1)
        self.tabs.addTab(page, "ساختار حساب‌ها")

    # --------------------------------------------------------------- details
    def _build_details_tab(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)
        card = CardPanel("حساب‌های تفصیلی (مشتری، تأمین‌کننده، کارمند، بانک، صندوق)",
                         "هر تفصیلی به یک حساب معین متصل می‌شود و در اسناد قابل انتخاب است.")
        filters = QHBoxLayout()
        self.detail_search = SearchInput("جست‌وجو در عنوان یا کد تفصیلی…")
        self.detail_search.searchChanged.connect(lambda _t: self._apply_detail_filter())
        filters.addWidget(self.detail_search, 1)

        self.kind_filter = QComboBox()
        self.kind_filter.addItem("همه انواع", None)
        for kind, title in C.DETAIL_KIND_TITLES_FA.items():
            self.kind_filter.addItem(title, kind)
        self.kind_filter.currentIndexChanged.connect(lambda _i: self.refresh())
        filters.addWidget(self.kind_filter)
        card.add_layout(filters)

        self.detail_table = DataTable(DETAIL_COLUMNS, formatter=self.formatter)
        self.detail_table.rowActivated.connect(self._edit_detail)
        card.add(self.detail_table, 1)

        actions = QHBoxLayout()
        for text, slot in (("ویرایش", self._edit_detail),
                           ("فعال/غیرفعال", self._toggle_detail),
                           ("حذف", self._delete_detail)):
            button = QPushButton(text)
            button.setProperty("variant", "ghost")
            button.clicked.connect(slot)
            actions.addWidget(button)
        actions.addStretch(1)
        card.add_layout(actions)
        layout.addWidget(card, 1)
        self.tabs.addTab(page, "حساب‌های تفصیلی")

    # ------------------------------------------------------------------- data
    def refresh(self) -> None:
        try:
            level = self.level_filter.currentData()
            active = self.active_filter.currentData()
            self._rows = self.services.accounts.list_accounts(
                self.ctx, level=level, active=active, search=self.search.text().strip() or None)
            self.table.set_rows(self._rows)
            self._fill_tree()
            self._apply_filter()
            kind = self.kind_filter.currentData()
            self._details = self.services.parties.list_details(
                self.ctx, kind=kind, active=None,
                search=self.detail_search.text().strip() or None)
            self.detail_table.set_rows(self._details)
        except AppError as error:
            show_error(self, "بارگذاری حساب‌ها", error)

    def _fill_tree(self) -> None:
        self.tree.clear()
        try:
            nodes = self.services.accounts.tree(self.ctx)
        except AppError:
            nodes = []

        def build(node, parent_item=None):
            item = QTreeWidgetItem([node.row.title_fa, node.row.code])
            item.setData(0, Qt.ItemDataRole.UserRole, node.row.id)
            if not node.row.is_active:
                item.setForeground(0, Qt.GlobalColor.gray)
            if parent_item is None:
                self.tree.addTopLevelItem(item)
            else:
                parent_item.addChild(item)
            for child in node.children:
                build(child, item)
            return item

        for node in nodes:
            build(node)
        self.tree.expandToDepth(0)

    def _apply_filter(self) -> None:
        text = self.search.text().strip()
        rows = self._rows
        if text:
            rows = [row for row in rows if text in row.code or text in row.title_fa]
        self.table.set_rows(rows)
        active = sum(1 for row in rows if row.is_active)
        self.count_label.setText(f"{len(rows)} حساب · {active} فعال")

    def _apply_detail_filter(self) -> None:
        text = self.detail_search.text().strip()
        rows = self._details
        if text:
            rows = [row for row in rows if text in row.code or text in row.name]
        self.detail_table.set_rows(rows)

    def _selected(self) -> AccountRow | None:
        return self.table.current_row()

    def _selected_detail(self):
        return self.detail_table.current_row()

    def _on_tree_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        account_id = item.data(0, Qt.ItemDataRole.UserRole)
        for row_index, row in enumerate(self.table.model.rows()):
            if row.id == account_id:
                self.table.selectRow(row_index)
                self.table.scrollTo(self.table.model.index(row_index, 0))
                return

    # ---------------------------------------------------------------- actions
    def _new_account(self) -> None:
        if not self.can("accounts.create"):
            self.notify("برای ایجاد حساب، مجوز «ایجاد حساب» لازم است.")
            return
        dialog = AccountDialog(self.services, self.ctx, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.saved is not None:
            self.notify(f"حساب «{dialog.saved.display}» ثبت شد.")
            self.refresh()

    def _edit_selected(self, *_args) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک حساب را انتخاب کنید.")
            return
        if not self.can("accounts.edit"):
            self.notify("برای ویرایش حساب، مجوز «ویرایش حساب» لازم است.")
            return
        dialog = AccountDialog(self.services, self.ctx, account=row, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.saved is not None:
            self.notify(f"حساب «{dialog.saved.display}» به‌روزرسانی شد.")
            self.refresh()

    def _toggle_active(self, *_args) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک حساب را انتخاب کنید.")
            return
        if not self.can("accounts.deactivate"):
            self.notify("برای تغییر وضعیت حساب، مجوز «غیرفعال‌سازی حساب» لازم است.")
            return
        try:
            updated = self.services.accounts.set_active(self.ctx, row.id, not row.is_active)
        except AppError as error:
            show_error(self, "تغییر وضعیت حساب", error)
            return
        self.notify(f"حساب «{updated.display}» {updated.status_fa} شد.")
        self.refresh()

    def _delete_account(self, *_args) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک حساب را انتخاب کنید.")
            return
        if not self.can("accounts.delete"):
            self.notify("برای حذف حساب، مجوز «حذف حساب» لازم است.")
            return
        used = self.services.accounts.usage_count(self.ctx, row.id)
        if used:
            show_info(self, "حذف حساب",
                      f"حساب «{row.display}» در {used} سطر سند استفاده شده و قابل حذف نیست؛ "
                      "آن را غیرفعال کنید.", tone="warning")
            return
        confirm = ConfirmDialog(
            self, title="حذف حساب",
            message=f"حساب «{row.display}» حذف شود؟ این عملیات قابل بازگشت نیست.",
            confirm_text="حذف", danger=True)
        if confirm.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.services.accounts.delete(self.ctx, row.id)
        except AppError as error:
            show_error(self, "حذف حساب", error)
            return
        self.notify("حساب حذف شد.")
        self.refresh()

    def _set_section(self, *_args) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک حساب را انتخاب کنید.")
            return
        if not self.can("accounts.edit"):
            self.notify("برای تغییر بخش صورت‌های مالی مجوز ویرایش لازم است.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("بخش صورت‌های مالی")
        dialog.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout = QVBoxLayout(dialog)
        note = QLabel(f"حساب: {row.display}\nبخش گزارش‌های مالی این حساب را انتخاب کنید.")
        note.setWordWrap(True)
        layout.addWidget(note)
        combo = QComboBox()
        combo.addItem("— تعیین نشده —", None)
        for section in C.SECTIONS_FOR_TYPE.get(row.account_type, ()):
            combo.addItem(C.SECTION_TITLES_FA.get(section, section), section)
        combo.setCurrentIndex(max(0, combo.findData(row.statement_section or None)))
        layout.addWidget(form_row("بخش", combo))
        buttons = QDialogButtonBox()
        buttons.addButton("ذخیره", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.services.accounts.set_statement_section(self.ctx, row.id, combo.currentData())
        except AppError as error:
            show_error(self, "بخش صورت‌های مالی", error)
            return
        self.notify("بخش صورت‌های مالی ذخیره شد.")
        self.refresh()

    def _new_detail(self) -> None:
        if not self.can("details.edit"):
            self.notify("برای ایجاد حساب تفصیلی مجوز «ویرایش تفصیلی» لازم است.")
            return
        dialog = DetailAccountDialog(self.services, self.ctx, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.saved is not None:
            self.notify(f"تفصیلی «{dialog.saved.display}» ثبت شد.")
            self.tabs.setCurrentIndex(1)
            self.refresh()

    def _edit_detail(self, *_args) -> None:
        row = self._selected_detail()
        if row is None:
            self.notify("ابتدا یک حساب تفصیلی را انتخاب کنید.")
            return
        if not self.can("details.edit"):
            self.notify("برای ویرایش تفصیلی مجوز لازم است.")
            return
        dialog = DetailAccountDialog(self.services, self.ctx, detail=row, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.notify("حساب تفصیلی به‌روزرسانی شد.")
            self.refresh()

    def _toggle_detail(self, *_args) -> None:
        row = self._selected_detail()
        if row is None:
            self.notify("ابتدا یک حساب تفصیلی را انتخاب کنید.")
            return
        if not self.can("details.edit"):
            self.notify("برای تغییر وضعیت تفصیلی مجوز لازم است.")
            return
        try:
            updated = self.services.parties.set_active(self.ctx, row.id, not row.is_active)
        except AppError as error:
            show_error(self, "تغییر وضعیت تفصیلی", error)
            return
        self.notify(f"تفصیلی «{updated.display}» {updated.status_fa} شد.")
        self.refresh()

    def _delete_detail(self, *_args) -> None:
        row = self._selected_detail()
        if row is None:
            self.notify("ابتدا یک حساب تفصیلی را انتخاب کنید.")
            return
        try:
            self.services.parties.delete(self.ctx, row.id)
        except AppError as error:
            show_error(self, "حذف تفصیلی", error)
            return
        self.notify("حساب تفصیلی حذف شد.")
        self.refresh()

    def _load_standard(self) -> None:
        if not self.can("accounts.create"):
            self.notify("برای بارگذاری کدینگ استاندارد مجوز ایجاد حساب لازم است.")
            return
        confirm = ConfirmDialog(
            self, title="بارگذاری کدینگ استاندارد",
            message="کدینگ استاندارد ایرانی (گروه/کل/معین) در ساختار فعلی درج می‌شود. "
                    "حساب‌های موجود تغییر نمی‌کنند.",
            confirm_text="بارگذاری")
        if confirm.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            result = self.services.accounting.load_standard_chart(self.ctx)
        except AppError as error:
            show_error(self, "بارگذاری کدینگ", error)
            return
        show_info(self, "بارگذاری کدینگ",
                  f"{result.created_accounts} حساب ایجاد شد و "
                  f"{result.skipped_accounts} حساب از قبل موجود بود.",
                  tone="success")
        self.refresh()
