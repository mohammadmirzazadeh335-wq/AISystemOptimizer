"""User management screen: list, search, create, edit, status, password reset."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
)

from pars_erp.core.errors import AppError
from pars_erp.services.user_service import STATUS_TITLES_FA, UserRow
from pars_erp.ui.dialogs.common_dialogs import (
    ConfirmDialog,
    ResetPasswordDialog,
    show_error,
    show_info,
)
from pars_erp.ui.dialogs.user_dialog import UserDialog
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.table_specs import USER_COLUMNS
from pars_erp.ui.widgets.common import SearchInput
from pars_erp.ui.widgets.pagination import PaginationBar
from pars_erp.ui.widgets.table import DataTable


class UsersPage(PageBase):
    def __init__(self, services, ctx, formatter, *, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self._page = 1
        self._page_size = self.services.settings.snapshot().table_page_size

        self.header = PageHeader("کاربران", "مدیریت حساب‌های کاربری، نقش‌ها و وضعیت دسترسی")
        self.new_button = self.header.add_action("کاربر جدید", slot=self._create_user,
                                                 tooltip="ایجاد حساب کاربری جدید")
        self.export_button = self.header.add_action("خروجی CSV", variant="ghost",
                                                    slot=self._export)
        self.header.add_action("بازخوانی", variant="ghost", slot=self.refresh)
        self.root.addWidget(self.header)

        self.error_banner = QLabel("")
        self.error_banner.setObjectName("ErrorText")
        self.error_banner.setWordWrap(True)
        self.error_banner.setVisible(False)
        self.root.addWidget(self.error_banner)

        filters = CardPanel()
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.search_input = SearchInput("جست‌وجو در نام کاربری، نام، ایمیل یا تلفن…")
        self.search_input.searchChanged.connect(self._on_search)
        filter_row.addWidget(self.search_input, 1)

        self.status_combo = QComboBox()
        for code, title in STATUS_TITLES_FA.items():
            self.status_combo.addItem(title, code)
        self.status_combo.currentIndexChanged.connect(lambda _i: self._reload(reset_page=True))
        filter_row.addWidget(self.status_combo)

        self.role_combo = QComboBox()
        self.role_combo.addItem("همه نقش‌ها", None)
        for code, title in self.services.roles.role_choices():
            self.role_combo.addItem(title, code)
        self.role_combo.currentIndexChanged.connect(lambda _i: self._reload(reset_page=True))
        filter_row.addWidget(self.role_combo)
        filters.add_layout(filter_row)
        self.root.addWidget(filters)

        table_card = CardPanel()
        self.table = DataTable(USER_COLUMNS, formatter=self.formatter)
        self.table.rowActivated.connect(lambda _row: self._edit_user())
        self.table.setMinimumHeight(320)
        table_card.add(self.table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.edit_button = QPushButton("ویرایش")
        self.edit_button.clicked.connect(self._edit_user)
        self.toggle_button = QPushButton("غیرفعال‌سازی")
        self.toggle_button.clicked.connect(self._toggle_active)
        self.reset_button = QPushButton("بازنشانی رمز")
        self.reset_button.clicked.connect(self._reset_password)
        self.unlock_button = QPushButton("رفع قفل")
        self.unlock_button.clicked.connect(self._unlock)
        for button in (self.edit_button, self.toggle_button, self.reset_button, self.unlock_button):
            button.setProperty("variant", "ghost")
            actions.addWidget(button)
        actions.addStretch(1)
        self.pagination = PaginationBar()
        self.pagination.set_persian_digits(self.formatter.persian_digits)
        self.pagination.pageChanged.connect(self._on_page)
        actions.addWidget(self.pagination)
        table_card.add_layout(actions)
        self.root.addWidget(table_card, 1)

        self.table.on_selection_changed(self._sync_actions)
        self._apply_permissions()

    # ---------------------------------------------------------------- helpers
    def _apply_permissions(self) -> None:
        self.new_button.setVisible(self.can("users.create"))
        self.edit_button.setEnabled(self.can("users.edit"))
        self.toggle_button.setEnabled(self.can("users.disable"))
        self.reset_button.setEnabled(self.can("users.reset_password"))
        self.unlock_button.setEnabled(self.can("users.unlock"))
        self.export_button.setVisible(self.can("users.view"))

    def _selected(self) -> UserRow | None:
        return self.table.current_row()

    def _sync_actions(self) -> None:
        row = self._selected()
        if row is None:
            self.toggle_button.setText("غیرفعال‌سازی")
            return
        self.toggle_button.setText("فعال‌سازی" if not row.is_active else "غیرفعال‌سازی")
        if row.id == self.ctx.user_id:
            self.toggle_button.setEnabled(False)
            self.reset_button.setEnabled(False)
        else:
            self.toggle_button.setEnabled(self.can("users.disable"))
            self.reset_button.setEnabled(self.can("users.reset_password"))

    def _show_error(self, error: Exception) -> None:
        self.error_banner.setText(str(error))
        self.error_banner.setVisible(True)
        show_error(self, "خطا در انجام عملیات", error)

    def _on_search(self, _text: str) -> None:
        self._reload(reset_page=True)

    def _on_page(self, page: int) -> None:
        self._page = page
        self._reload()

    def _reload(self, *, reset_page: bool = False) -> None:
        if reset_page:
            self._page = 1
        self.error_banner.setVisible(False)
        try:
            result = self.services.users.list_users(
                self.ctx,
                search=self.search_input.text(),
                status=self.status_combo.currentData(),
                role_code=self.role_combo.currentData(),
                page=self._page,
                page_size=self._page_size,
            )
        except AppError as exc:
            self._show_error(exc)
            return
        self._page = result.page
        self.table.set_rows(result.items)
        self.pagination.update_page(result)
        self.header.set_subtitle(
            f"مدیریت حساب‌های کاربری — {self.formatter.number(result.total)} کاربر")
        self._sync_actions()

    def refresh(self) -> None:
        self._reload()

    # ---------------------------------------------------------------- actions
    def _create_user(self) -> None:
        dialog = UserDialog(self, self.services, self.ctx)
        if dialog.exec():
            self.notify("کاربر جدید ایجاد شد.")
            self._reload(reset_page=True)

    def _edit_user(self) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک کاربر را از فهرست انتخاب کنید.")
            return
        if not self.can("users.edit"):
            self.notify("شما مجوز ویرایش کاربران را ندارید.")
            return
        dialog = UserDialog(self, self.services, self.ctx, user=row)
        if dialog.exec():
            self.notify(f"اطلاعات کاربر «{row.username}» ذخیره شد.")
            self._reload()

    def _toggle_active(self) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک کاربر را انتخاب کنید.")
            return
        target_state = not row.is_active
        title = "فعال‌سازی کاربر" if target_state else "غیرفعال‌سازی کاربر"
        message = (f"آیا از فعال‌سازی کاربر «{row.full_name}» مطمئن هستید؟"
                   if target_state else
                   f"با غیرفعال‌سازی، کاربر «{row.full_name}» نمی‌تواند وارد سیستم شود. "
                   "ادامه می‌دهید؟")
        dialog = ConfirmDialog(self, title=title, message=message,
                               confirm_text="تأیید", danger=not target_state)
        if not dialog.exec():
            return
        try:
            self.services.users.set_active(self.ctx, row.id, target_state)
        except AppError as exc:
            self._show_error(exc)
            return
        self.notify("وضعیت کاربر به‌روزرسانی شد.")
        self._reload()

    def _reset_password(self) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک کاربر را انتخاب کنید.")
            return
        dialog = ResetPasswordDialog(self, self.services, self.ctx,
                                     user_id=row.id, username=row.username)
        if dialog.exec():
            self.notify(f"رمز عبور «{row.username}» بازنشانی شد.")
            self._reload()

    def _unlock(self) -> None:
        row = self._selected()
        if row is None:
            self.notify("ابتدا یک کاربر را انتخاب کنید.")
            return
        if not row.is_locked and row.failed_login_attempts == 0:
            self.notify("این حساب قفل نیست.")
            return
        try:
            self.services.auth.unlock_user(self.ctx, row.id)
        except AppError as exc:
            self._show_error(exc)
            return
        self.notify(f"قفل حساب «{row.username}» برداشته شد.")
        self._reload()

    def _export(self) -> None:
        suggested = self.services.exporter.default_filename("users")
        path, _filter = QFileDialog.getSaveFileName(
            self, "ذخیره خروجی کاربران", str(suggested), "CSV (*.csv)")
        if not path:
            return
        try:
            result = self.services.exporter.export_users(
                self.ctx, __import__("pathlib").Path(path),
                search=self.search_input.text(), status=self.status_combo.currentData())
        except AppError as exc:
            self._show_error(exc)
            return
        self.notify(result.message_fa)
        show_info(self, "خروجی گرفته شد", result.message_fa, details=str(result.path))
