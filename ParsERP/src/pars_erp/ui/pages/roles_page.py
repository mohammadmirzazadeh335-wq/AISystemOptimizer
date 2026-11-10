"""Role and permission management screen."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton

from pars_erp.core.errors import AppError
from pars_erp.services.role_service import RoleRow
from pars_erp.ui.dialogs.common_dialogs import ConfirmDialog, show_error
from pars_erp.ui.dialogs.role_dialog import RoleDialog
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.table_specs import ROLE_COLUMNS
from pars_erp.ui.widgets.common import Badge, InfoRow
from pars_erp.ui.widgets.table import DataTable


class RolesPage(PageBase):
    def __init__(self, services, ctx, formatter, *, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)

        self.header = PageHeader("نقش‌ها و دسترسی‌ها",
                                 "هر نقش مجموعه‌ای از مجوزها را دارد؛ دسترسی‌ها در لایه سرویس کنترل می‌شوند")
        self.new_button = self.header.add_action("نقش جدید", slot=self._create_role)
        self.header.add_action("بازخوانی", variant="ghost", slot=self.refresh)
        self.root.addWidget(self.header)

        content = QHBoxLayout()
        content.setSpacing(14)

        list_card = CardPanel("نقش‌های تعریف‌شده")
        self.table = DataTable(ROLE_COLUMNS, formatter=self.formatter)
        self.table.rowActivated.connect(lambda _row: self._edit_role())
        self.table.setMinimumHeight(360)
        list_card.add(self.table, 1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.edit_button = QPushButton("ویرایش دسترسی‌ها")
        self.edit_button.setProperty("variant", "ghost")
        self.edit_button.clicked.connect(self._edit_role)
        self.delete_button = QPushButton("حذف نقش")
        self.delete_button.setProperty("variant", "danger")
        self.delete_button.clicked.connect(self._delete_role)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        list_card.add_layout(actions)
        content.addWidget(list_card, 3)

        detail_card = CardPanel("جزئیات نقش", "برای مشاهده، یک نقش را انتخاب کنید")
        self.detail_title = QLabel("—")
        self.detail_title.setObjectName("SectionTitle")
        detail_card.add(self.detail_title)
        self.info_code = InfoRow("کد نقش")
        self.info_kind = InfoRow("نوع نقش")
        self.info_members = InfoRow("تعداد کاربران")
        self.info_permissions = InfoRow("تعداد مجوزها")
        self.permission_badges = QLabel("")
        self.permission_badges.setWordWrap(True)
        detail_card.add(self.info_code)
        detail_card.add(self.info_kind)
        detail_card.add(self.info_members)
        detail_card.add(self.info_permissions)
        detail_card.add(self.permission_badges)
        detail_card.add(QLabel(""))
        self.detail_note = QLabel("")
        self.detail_note.setObjectName("HintText")
        self.detail_note.setWordWrap(True)
        detail_card.add(self.detail_note)
        detail_card.setMaximumWidth(330)
        content.addWidget(detail_card, 2)
        self.root.addLayout(content, 1)

        self.table.on_selection_changed(self._sync_detail)
        self.new_button.setVisible(self.can("roles.create"))
        self.edit_button.setEnabled(self.can("roles.edit"))
        self.delete_button.setEnabled(self.can("roles.delete"))

    # ---------------------------------------------------------------- helpers
    def _selected(self) -> RoleRow | None:
        return self.table.current_row()

    def _sync_detail(self) -> None:
        role = self._selected()
        if role is None:
            self.detail_title.setText("—")
            return
        from pars_erp.security.permissions import permission_title
        self.detail_title.setText(role.title_fa)
        self.info_code.set_value(role.code)
        self.info_kind.set_value(role.kind_fa)
        self.info_members.set_value(self.formatter.number(role.member_count))
        self.info_permissions.set_value(self.formatter.number(role.permissions_count))
        titles = sorted(permission_title(code).split(" - ")[0] for code in role.permission_codes)
        unique = list(dict.fromkeys(titles))
        self.permission_badges.setText(
            "  •  ".join(unique) if unique else "بدون مجوز")
        self.detail_note.setText(
            "نقش سیستمی است و قابل حذف نیست." if role.is_system else
            "نقش سفارشی؛ در صورت نداشتن کاربر قابل حذف است.")
        if role.code == "admin":
            self.edit_button.setEnabled(False)
            self.delete_button.setEnabled(False)
        else:
            self.edit_button.setEnabled(self.can("roles.edit"))
            self.delete_button.setEnabled(self.can("roles.delete"))

    def refresh(self) -> None:
        try:
            roles = self.services.roles.list_roles(self.ctx)
        except AppError as exc:
            show_error(self, "خطا در خواندن نقش‌ها", exc)
            return
        self.table.set_rows(roles)
        self.header.set_subtitle(f"{self.formatter.number(len(roles))} نقش تعریف شده است")
        self._sync_detail()

    # ---------------------------------------------------------------- actions
    def _create_role(self) -> None:
        dialog = RoleDialog(self, self.services, self.ctx)
        if dialog.exec():
            self.notify("نقش جدید ایجاد شد.")
            self.refresh()

    def _edit_role(self) -> None:
        role = self._selected()
        if role is None:
            self.notify("ابتدا یک نقش را انتخاب کنید.")
            return
        dialog = RoleDialog(self, self.services, self.ctx, role=role)
        if dialog.exec():
            after = self.services.auth.reload_context(self.ctx)
            self.update_context(after)
            self.notify("دسترسی‌های نقش به‌روزرسانی شد.")
            self.refresh()

    def _delete_role(self) -> None:
        role = self._selected()
        if role is None:
            self.notify("ابتدا یک نقش را انتخاب کنید.")
            return
        dialog = ConfirmDialog(
            self, title="حذف نقش",
            message=f"نقش «{role.title_fa}» حذف می‌شود. این عملیات قابل بازگشت نیست.",
            confirm_text="حذف نقش", danger=True)
        if not dialog.exec():
            return
        try:
            self.services.roles.delete_role(self.ctx, role.id)
        except AppError as exc:
            show_error(self, "حذف نقش ممکن نیست", exc)
            return
        self.notify("نقش حذف شد.")
        self.refresh()
