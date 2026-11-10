"""Create / edit a user account."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError, ValidationError
from pars_erp.security.permissions import SecurityContext
from pars_erp.services.context import AppServices
from pars_erp.services.user_service import UserCreateData, UserRow, UserUpdateData
from pars_erp.ui.widgets.common import FieldRow, PasswordField


class UserDialog(QDialog):
    def __init__(self, parent: QWidget | None, services: AppServices, ctx: SecurityContext, *,
                 user: UserRow | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.user = user
        self.is_edit = user is not None
        self.setWindowTitle("ویرایش کاربر" if self.is_edit else "کاربر جدید")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setMinimumHeight(560)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)

        heading = QLabel("ویرایش اطلاعات کاربر" if self.is_edit else "ایجاد کاربر جدید")
        heading.setObjectName("SectionTitle")
        outer.addWidget(heading)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(10)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("مثال: hesabdar")
        if self.is_edit:
            self.username_input.setText(user.username)
            self.username_input.setEnabled(False)
        self.username_field = FieldRow(
            "نام کاربری", self.username_input, required=not self.is_edit,
            hint="حروف کوچک انگلیسی، ارقام، نقطه، خط تیره یا زیرخط (۳ تا ۳۲ نویسه)")
        layout.addWidget(self.username_field)

        self.full_name_input = QLineEdit()
        self.full_name_field = FieldRow("نام و نام خانوادگی", self.full_name_input, required=True)
        layout.addWidget(self.full_name_field)

        contact = QGridLayout()
        contact.setSpacing(10)
        self.email_input = QLineEdit()
        self.email_field = FieldRow("ایمیل", self.email_input)
        self.phone_input = QLineEdit()
        self.phone_field = FieldRow("تلفن همراه", self.phone_input)
        contact.addWidget(self.email_field, 0, 0)
        contact.addWidget(self.phone_field, 0, 1)
        layout.addLayout(contact)

        if not self.is_edit:
            self.password_field = PasswordField("رمز عبور اولیه", show_strength=True)
            self.confirm_field = PasswordField("تکرار رمز عبور")
            layout.addWidget(FieldRow("رمز عبور اولیه", self.password_field, required=True))
            layout.addWidget(FieldRow("تکرار رمز عبور", self.confirm_field, required=True))
            hint = QLabel("کاربر در اولین ورود ملزم به تغییر رمز خواهد بود.")
            hint.setObjectName("HintText")
            layout.addWidget(hint)
        else:
            self.password_field = None
            self.confirm_field = None

        roles_label = QLabel("نقش‌ها")
        roles_label.setObjectName("FieldLabel")
        layout.addWidget(roles_label)
        self._role_checks: dict[str, QCheckBox] = {}
        roles_box = QWidget()
        roles_layout = QVBoxLayout(roles_box)
        roles_layout.setContentsMargins(0, 0, 0, 0)
        roles_layout.setSpacing(4)
        selected = set(user.role_codes) if self.is_edit else set()
        for code, title in services.users.selectable_roles(ctx):
            check = QCheckBox(title)
            check.setChecked(code in selected)
            check.setEnabled(True)
            check.setProperty("role_code", code)
            self._role_checks[code] = check
            roles_layout.addWidget(check)
        layout.addWidget(roles_box)
        self.roles_error = QLabel("")
        self.roles_error.setObjectName("ErrorText")
        self.roles_error.setVisible(False)
        layout.addWidget(self.roles_error)

        self.notes_input = QLineEdit()
        self.notes_field = FieldRow("یادداشت", self.notes_input)
        layout.addWidget(self.notes_field)

        if self.is_edit:
            self.full_name_input.setText(user.full_name)
            self.email_input.setText(user.email or "")
            self.phone_input.setText(user.phone or "")
            self.notes_input.setText(user.notes or "")

        layout.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

        self.error_label = QLabel("")
        self.error_label.setObjectName("ErrorText")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        outer.addWidget(self.error_label)

        buttons = QDialogButtonBox()
        save = buttons.addButton("ذخیره", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        cancel = buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        cancel.setProperty("variant", "ghost")
        buttons.accepted.connect(self._submit)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        (self.password_field if self.password_field else self.full_name_input).setFocus()

    # ------------------------------------------------------------------ logic
    def selected_roles(self) -> tuple[str, ...]:
        return tuple(code for code, check in self._role_checks.items() if check.isChecked())

    def _clear_errors(self) -> None:
        for field in (self.username_field, self.full_name_field, self.email_field,
                      self.phone_field, self.notes_field):
            field.set_error(None)
        self.roles_error.setVisible(False)
        self.error_label.setVisible(False)

    def _show_error(self, error: AppError) -> None:
        field = getattr(error, "field", None)
        mapping = {
            "username": self.username_field, "full_name": self.full_name_field,
            "email": self.email_field, "phone": self.phone_field, "notes": self.notes_field,
            "password": getattr(self, "password_field", None),
            "confirm_password": getattr(self, "confirm_field", None),
        }
        target = mapping.get(field or "")
        if field == "password" and target is not None:
            self.error_label.setText(str(error))
            self.error_label.setVisible(True)
        elif target is not None and hasattr(target, "set_error"):
            target.set_error(str(error))
        elif field == "roles":
            self.roles_error.setText(str(error))
            self.roles_error.setVisible(True)
        else:
            self.error_label.setText(str(error))
            self.error_label.setVisible(True)

    def _submit(self) -> None:
        self._clear_errors()
        roles = self.selected_roles()
        try:
            if self.is_edit:
                data = UserUpdateData(
                    full_name=self.full_name_input.text(),
                    role_codes=roles,
                    email=self.email_input.text(),
                    phone=self.phone_input.text(),
                    notes=self.notes_input.text(),
                )
                self.services.users.update_user(self.ctx, self.user.id, data)
            else:
                data = UserCreateData(
                    username=self.username_input.text(),
                    full_name=self.full_name_input.text(),
                    password=self.password_field.text(),
                    confirm_password=self.confirm_field.text(),
                    role_codes=roles,
                    email=self.email_input.text(),
                    phone=self.phone_input.text(),
                    notes=self.notes_input.text(),
                )
                self.services.users.create_user(self.ctx, data)
        except AppError as exc:
            self._show_error(exc)
            return
        self.accept()
