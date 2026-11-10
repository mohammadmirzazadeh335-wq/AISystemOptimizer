"""Confirmation and password dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError, PasswordPolicyError, ValidationError
from pars_erp.security.passwords import PasswordPolicy, validate_password
from pars_erp.services.context import AppServices
from pars_erp.security.permissions import SecurityContext
from pars_erp.ui.widgets.common import Card, FieldRow, PasswordField
from pars_erp.ui.formatting import Formatter


class ConfirmDialog(QDialog):
    """Destructive-action confirmation with an optional typed phrase."""

    def __init__(self, parent: QWidget | None, *, title: str, message: str,
                 confirm_text: str = "تأیید", cancel_text: str = "انصراف",
                 danger: bool = False, require_phrase: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(430)
        self._required_phrase = require_phrase

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)

        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        body = QLabel(message)
        body.setWordWrap(True)
        layout.addWidget(body)

        self.phrase_field: FieldRow | None = None
        if require_phrase:
            self.phrase_input = QLineEdit()
            self.phrase_input.setPlaceholderText(require_phrase)
            self.phrase_field = FieldRow(f"برای تأیید عبارت «{require_phrase}» را وارد کنید",
                                         self.phrase_input, required=True)
            layout.addWidget(self.phrase_field)

        buttons = QDialogButtonBox()
        self.confirm_button = buttons.addButton(confirm_text, QDialogButtonBox.ButtonRole.AcceptRole)
        self.confirm_button.setProperty("variant", "danger" if danger else "primary")
        cancel = buttons.addButton(cancel_text, QDialogButtonBox.ButtonRole.RejectRole)
        cancel.setProperty("variant", "ghost")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if require_phrase:
            self.confirm_button.setEnabled(False)
            self.phrase_input.textChanged.connect(self._check_phrase)

    def _check_phrase(self, text: str) -> None:
        self.confirm_button.setEnabled(text.strip() == self._required_phrase)

    def _on_accept(self) -> None:
        if self._required_phrase and self.phrase_input.text().strip() != self._required_phrase:
            if self.phrase_field:
                self.phrase_field.set_error("عبارت تأیید درست وارد نشده است.")
            return
        self.accept()

    def phrase(self) -> str:
        return self.phrase_input.text().strip() if self.phrase_field else ""


class ChangePasswordDialog(QDialog):
    """A user changing their own password (current password required)."""

    def __init__(self, parent: QWidget | None, services: AppServices, ctx: SecurityContext,
                 *, mandatory: bool = False) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.setWindowTitle("تغییر رمز عبور")
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(10)

        self.mandatory = mandatory
        title = QLabel("تغییر رمز عبور" + (" (الزامی)" if mandatory else ""))
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        if mandatory:
            requirement = QLabel("مدیر سیستم تعیین کرده است که پیش از ادامه، رمز عبور خود را "
                                 "تغییر دهید. برای انصراف باید از حساب خارج شوید.")
            requirement.setWordWrap(True)
            requirement.setObjectName("HintText")
            layout.addWidget(requirement)
        subtitle = QLabel(f"کاربر: {ctx.full_name} ({ctx.username})")
        subtitle.setObjectName("HintText")
        layout.addWidget(subtitle)

        self.current_field = PasswordField("رمز عبور فعلی")
        self.new_field = PasswordField("رمز عبور جدید", show_strength=True)
        self.confirm_field = PasswordField("تکرار رمز عبور جدید")

        policy = PasswordPolicy(min_length=services.settings.snapshot().password_min_length)
        for label, widget in (("رمز عبور فعلی", self.current_field),
                              ("رمز عبور جدید", self.new_field),
                              ("تکرار رمز عبور جدید", self.confirm_field)):
            layout.addWidget(FieldRow(label, widget, required=True))
        layout.addWidget(QLabel(f"سیاست رمز عبور: {policy.describe_fa()}"))

        self.error_label = QLabel("")
        self.error_label.setObjectName("ErrorText")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox()
        save = buttons.addButton("تغییر رمز", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        cancel = buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        cancel.setProperty("variant", "ghost")
        buttons.accepted.connect(self._submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.current_field.setFocus()

    def _submit(self) -> None:
        self.error_label.setVisible(False)
        try:
            self.services.auth.change_password(
                self.ctx,
                current_password=self.current_field.text(),
                new_password=self.new_field.text(),
                confirm_password=self.confirm_field.text())
        except (PasswordPolicyError, ValidationError, AppError) as exc:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
            return
        self.accept()


class ResetPasswordDialog(QDialog):
    """Administrator resetting another user's password."""

    def __init__(self, parent: QWidget | None, services: AppServices, ctx: SecurityContext,
                 *, user_id: int, username: str) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.user_id = user_id
        self.setWindowTitle(f"بازنشانی رمز عبور — {username}")
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(10)
        heading = QLabel(f"بازنشانی رمز عبور «{username}»")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        note = QLabel("پس از بازنشانی، نشست‌های فعال این کاربر بسته می‌شود و در ورود بعدی "
                      "ملزم به تغییر رمز خواهد بود.")
        note.setObjectName("HintText")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.new_field = PasswordField("رمز عبور جدید", show_strength=True)
        self.confirm_field = PasswordField("تکرار رمز عبور جدید")
        layout.addWidget(FieldRow("رمز عبور جدید", self.new_field, required=True))
        layout.addWidget(FieldRow("تکرار رمز عبور جدید", self.confirm_field, required=True))
        self.require_change = QCheckBox("کاربر در ورود بعدی ملزم به تغییر رمز باشد")
        self.require_change.setChecked(True)
        layout.addWidget(self.require_change)

        self.error_label = QLabel("")
        self.error_label.setObjectName("ErrorText")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox()
        save = buttons.addButton("بازنشانی رمز", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        cancel = buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        cancel.setProperty("variant", "ghost")
        buttons.accepted.connect(self._submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _submit(self) -> None:
        self.error_label.setVisible(False)
        try:
            self.services.auth.reset_password_by_admin(
                self.ctx, user_id=self.user_id, new_password=self.new_field.text(),
                confirm_password=self.confirm_field.text(),
                require_change=self.require_change.isChecked())
        except AppError as exc:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
            return
        self.accept()


class LockScreenDialog(QDialog):
    """Idle-lock overlay: the session stays open, but the screen is locked."""

    def __init__(self, parent: QWidget | None, services: AppServices, ctx: SecurityContext,
                 *, formatter: Formatter) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.setWindowTitle("صفحه قفل شده است")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        icon = QLabel("🔒")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 30pt;")
        layout.addWidget(icon)
        title = QLabel("نشست شما قفل شده است")
        title.setObjectName("SectionTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        info = QLabel(f"{ctx.full_name} ({ctx.username})")
        info.setObjectName("HintText")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info)
        reset_hint = QLabel("برای ادامه، رمز عبور خود را وارد کنید.")
        reset_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(reset_hint)

        self.password_field = PasswordField("رمز عبور")
        layout.addWidget(FieldRow("رمز عبور", self.password_field, required=True))
        self.error_label = QLabel("")
        self.error_label.setObjectName("ErrorText")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        row = QHBoxLayout()
        unlock = QDialogButtonBox()
        self.unlock_button = unlock.addButton("باز کردن", QDialogButtonBox.ButtonRole.AcceptRole)
        self.unlock_button.setProperty("variant", "primary")
        logout_button = unlock.addButton("خروج از حساب", QDialogButtonBox.ButtonRole.DestructiveRole)
        unlock.accepted.connect(self._unlock)
        unlock.rejected.connect(self.reject)
        logout_button.clicked.connect(self.reject)
        row.addWidget(unlock)
        layout.addLayout(row)
        self._logged_out = False
        self.password_field.input.returnPressed.connect(self._unlock)

    @property
    def logged_out(self) -> bool:
        return self._logged_out

    def _unlock(self) -> None:
        self.error_label.setVisible(False)
        try:
            self.services.auth.unlock_session(self.ctx, self.password_field.text())
        except AppError as exc:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
            self.password_field.clear()
            return
        self.accept()


def show_error(parent: QWidget | None, title: str, error: Exception) -> None:
    from PySide6.QtWidgets import QMessageBox
    message = str(error) if isinstance(error, Exception) else str(error)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(title)
    box.setInformativeText(message)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.button(QMessageBox.StandardButton.Ok).setText("باشه")
    box.exec()


def show_info(parent: QWidget | None, title: str, message: str,
              details: str | None = None, *, tone: str = "info") -> None:
    """Informational message box.

    ``tone`` only changes the icon: ``success``/``info`` show the information
    icon, ``warning``/``danger`` show the warning icon.
    """
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning if tone in ("warning", "danger")
                else QMessageBox.Icon.Information)
    box.setWindowTitle(title)
    box.setText(message)
    if details:
        box.setDetailedText(details)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.button(QMessageBox.StandardButton.Ok).setText("باشه")
    box.exec()
