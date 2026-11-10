"""Login window and the secure first-run setup wizard."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pars_erp import __phase__, __version__
from pars_erp.core.errors import AppError
from pars_erp.services.context import AppServices
from pars_erp.ui.formatting import Formatter
from pars_erp.ui.widgets.common import Card, FieldRow, PasswordField, apply_shadow


class BrandPanel(QFrame):
    """Dark brand column shared by the login and setup screens."""

    def __init__(self, app_name: str, company: str, subtitle: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LoginSide")
        self.setFixedWidth(300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 32, 26, 26)
        layout.setSpacing(10)

        logo = QLabel("پ")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(58, 58)
        logo.setStyleSheet(
            "background-color: #2563eb; color: white; border-radius: 16px;"
            " font-size: 26pt; font-weight: 700;")
        layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addSpacing(6)

        title = QLabel(app_name)
        title.setObjectName("BrandTitle")
        layout.addWidget(title)
        self.company_label = QLabel(company or "نرم‌افزار جامع حسابداری و مدیریت کسب‌وکار")
        self.company_label.setObjectName("BrandSubtitle")
        self.company_label.setWordWrap(True)
        layout.addWidget(self.company_label)
        layout.addStretch(1)

        # Only capabilities that really exist in this build are advertised.
        for text in ("مدیریت کاربران، نقش‌ها و دسترسی‌ها", "ثبت رویدادهای امنیتی و تاریخچه تغییرات",
                     "پشتیبان‌گیری و بازیابی پایگاه داده"):
            bullet = QLabel(f"•  {text}")
            bullet.setStyleSheet("color: #c9d4e5; font-size: 10pt;")
            layout.addWidget(bullet)
        layout.addSpacing(10)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: #23304a;")
        layout.addWidget(divider)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setStyleSheet("color: #7d8ba1;")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)
        version = QLabel(f"نسخه {__version__} — فاز {__phase__}")
        version.setStyleSheet("color: #7d8ba1;")
        layout.addWidget(version)


class LoginPage(QWidget):
    authenticated = Signal(object)

    def __init__(self, services: AppServices, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(10)

        heading = QLabel("ورود به سیستم")
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)
        subtitle = QLabel("برای ادامه، نام کاربری و رمز عبور خود را وارد کنید.")
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(8)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("نام کاربری")
        self.username_input.setMinimumHeight(36)
        self.username_field = FieldRow("نام کاربری", self.username_input, required=True)
        layout.addWidget(self.username_field)

        self.password_field = PasswordField("رمز عبور")
        self.password_row = FieldRow("رمز عبور", self.password_field, required=True)
        layout.addWidget(self.password_row)

        self.error_label = QLabel("")
        self.error_label.setObjectName("ErrorText")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.login_button = QPushButton("ورود")
        self.login_button.setProperty("variant", "primary")
        self.login_button.setMinimumHeight(38)
        self.login_button.clicked.connect(self.attempt_login)
        layout.addWidget(self.login_button)

        self.hint_label = QLabel("")
        self.hint_label.setObjectName("HintText")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)
        layout.addStretch(1)

        snapshot = services.settings.snapshot()
        footer = QLabel(f"نسخه {__version__} — پایگاه داده: {services.db.dialect_name()}")
        footer.setObjectName("HintText")
        layout.addWidget(footer)
        self.hint_label.setText(
            f"پس از {snapshot.max_failed_attempts} تلاش ناموفق، حساب کاربری برای "
            f"{snapshot.lockout_minutes} دقیقه قفل می‌شود.")
        self.password_field.input.returnPressed.connect(self.attempt_login)
        self.username_input.returnPressed.connect(lambda: self.password_field.setFocus())

    def attempt_login(self) -> None:
        self.error_label.setVisible(False)
        self.username_field.set_error(None)
        self.password_row.set_error(None)
        username = self.username_input.text().strip()
        password = self.password_field.text()
        if not username:
            self.username_field.set_error("نام کاربری را وارد کنید.")
            return
        if not password:
            self.password_row.set_error("رمز عبور را وارد کنید.")
            return
        self.login_button.setEnabled(False)
        self.login_button.setText("در حال بررسی…")
        try:
            ctx = self.services.auth.authenticate(username, password)
        except AppError as exc:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
            self.password_field.clear()
            self.password_field.setFocus()
            self.login_button.setEnabled(True)
            self.login_button.setText("ورود")
            return
        self.login_button.setEnabled(True)
        self.login_button.setText("ورود")
        self.password_field.clear()
        self.authenticated.emit(ctx)


class SetupPage(QWidget):
    """Three-step first-run wizard (company → administrator → review)."""

    completed = Signal(object)

    STEP_TITLES = ("اطلاعات شرکت", "حساب مدیر سیستم", "بازبینی و تکمیل")

    def __init__(self, services: AppServices, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.step = 0
        self._snapshot = services.settings.snapshot()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(8)

        self.step_label = QLabel("")
        self.step_label.setObjectName("PageSubtitle")
        layout.addWidget(self.step_label)
        self.heading = QLabel("")
        self.heading.setObjectName("PageTitle")
        layout.addWidget(self.heading)
        layout.addSpacing(6)

        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)

        # --- step 1: company -------------------------------------------------
        step1 = QWidget()
        step1_layout = QVBoxLayout(step1)
        step1_layout.setContentsMargins(0, 0, 0, 0)
        step1_layout.setSpacing(10)
        self.company_input = QLineEdit()
        self.company_field = FieldRow("نام شرکت / کسب‌وکار", self.company_input, required=True,
                                      hint="این نام در سرصفحه گزارش‌ها استفاده می‌شود.")
        step1_layout.addWidget(self.company_field)
        self.app_name_input = QLineEdit("ParsERP")
        self.app_name_field = FieldRow("نام نرم‌افزار", self.app_name_input,
                                       hint="در عنوان پنجره‌ها و پاورقی گزارش‌ها نمایش داده می‌شود.")
        step1_layout.addWidget(self.app_name_field)
        self.company_phone_input = QLineEdit()
        step1_layout.addWidget(FieldRow("تلفن شرکت (اختیاری)", self.company_phone_input))
        self.company_address_input = QLineEdit()
        step1_layout.addWidget(FieldRow("نشانی شرکت (اختیاری)", self.company_address_input))
        step1_layout.addStretch(1)
        self.pages.addWidget(step1)

        # --- step 2: administrator ------------------------------------------
        step2 = QWidget()
        step2_layout = QVBoxLayout(step2)
        step2_layout.setContentsMargins(0, 0, 0, 0)
        step2_layout.setSpacing(10)
        self.full_name_input = QLineEdit()
        self.full_name_field = FieldRow("نام و نام خانوادگی", self.full_name_input, required=True)
        step2_layout.addWidget(self.full_name_field)
        self.username_input = QLineEdit()
        self.username_field = FieldRow("نام کاربری مدیر", self.username_input, required=True,
                                       hint="حروف کوچک انگلیسی، ارقام، نقطه یا زیرخط")
        step2_layout.addWidget(self.username_field)
        self.password_field = PasswordField("رمز عبور", show_strength=True)
        self.confirm_field = PasswordField("تکرار رمز عبور")
        step2_layout.addWidget(FieldRow("رمز عبور", self.password_field, required=True))
        step2_layout.addWidget(FieldRow("تکرار رمز عبور", self.confirm_field, required=True))
        policy_hint = QLabel(
            f"حداقل طول رمز {self._snapshot.password_min_length} نویسه و باید شامل حرف و رقم باشد. "
            "رمزها با الگوریتم Argon2id ذخیره می‌شوند و به‌صورت خام نگهداری نمی‌شوند.")
        policy_hint.setObjectName("HintText")
        policy_hint.setWordWrap(True)
        step2_layout.addWidget(policy_hint)
        step2_layout.addStretch(1)
        self.pages.addWidget(step2)

        # --- step 3: review --------------------------------------------------
        step3 = QWidget()
        step3_layout = QVBoxLayout(step3)
        step3_layout.setContentsMargins(0, 0, 0, 0)
        step3_layout.setSpacing(8)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        step3_layout.addWidget(self.summary)
        security_note = QLabel(
            "پس از تکمیل، پنج نقش پیش‌فرض (مدیر سیستم، حسابدار، انباردار، فروشنده و مشاهده‌گر) "
            "ساخته می‌شود و می‌توانید کاربران و دسترسی‌ها را مدیریت کنید. "
            "پشتیبان‌گیری خودکار از پایگاه داده در شروع برنامه فعال خواهد بود.")
        security_note.setObjectName("HintText")
        security_note.setWordWrap(True)
        step3_layout.addWidget(security_note)
        step3_layout.addStretch(1)
        self.pages.addWidget(step3)

        self.error_label = QLabel("")
        self.error_label.setObjectName("ErrorText")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        self.back_button = QPushButton("مرحله قبل")
        self.back_button.setProperty("variant", "ghost")
        self.back_button.clicked.connect(self.go_back)
        self.next_button = QPushButton("مرحله بعد")
        self.next_button.setProperty("variant", "primary")
        self.next_button.setMinimumHeight(36)
        self.next_button.clicked.connect(self.go_next)
        buttons.addWidget(self.back_button)
        buttons.addStretch(1)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)
        self._sync_state()

    # ------------------------------------------------------------------ steps
    def _sync_state(self) -> None:
        self.step_label.setText(f"مرحله {self.step + 1} از 3 — راه‌اندازی اولیه")
        self.heading.setText(self.STEP_TITLES[self.step])
        self.pages.setCurrentIndex(self.step)
        self.back_button.setEnabled(self.step > 0)
        self.next_button.setText("تکمیل راه‌اندازی" if self.step == 2 else "مرحله بعد")
        if self.step == 2:
            self.summary.setText(
                f"<b>شرکت:</b> {self.company_input.text().strip() or '—'}<br>"
                f"<b>نام نرم‌افزار:</b> {self.app_name_input.text().strip() or 'ParsERP'}<br>"
                f"<b>مدیر سیستم:</b> {self.full_name_input.text().strip()} "
                f"({self.username_input.text().strip()})<br>"
                f"<b>پایگاه داده:</b> {self.services.db.dialect_name()}")

    def _validate_step(self) -> bool:
        self.error_label.setVisible(False)
        if self.step == 0:
            self.company_field.set_error(None)
            if not self.company_input.text().strip():
                self.company_field.set_error("نام شرکت را وارد کنید.")
                return False
            if not self.app_name_input.text().strip():
                self.app_name_field.set_error("نام نرم‌افزار را وارد کنید.")
                return False
        elif self.step == 1:
            self.full_name_field.set_error(None)
            self.username_field.set_error(None)
            if not self.full_name_input.text().strip():
                self.full_name_field.set_error("نام و نام خانوادگی را وارد کنید.")
                return False
            if not self.username_input.text().strip():
                self.username_field.set_error("نام کاربری را وارد کنید.")
                return False
            if not self.password_field.text():
                self.error_label.setText("رمز عبور را وارد کنید.")
                self.error_label.setVisible(True)
                return False
            if self.password_field.text() != self.confirm_field.text():
                self.error_label.setText("رمز عبور و تکرار آن یکسان نیستند.")
                self.error_label.setVisible(True)
                return False
        return True

    def go_next(self) -> None:
        if not self._validate_step():
            return
        if self.step < 2:
            self.step += 1
            self._sync_state()
            return
        self._finish()

    def go_back(self) -> None:
        if self.step > 0:
            self.step -= 1
            self._sync_state()

    def _finish(self) -> None:
        self.next_button.setEnabled(False)
        self.next_button.setText("در حال ایجاد…")
        try:
            ctx = self.services.auth.create_initial_admin(
                full_name=self.full_name_input.text(),
                username=self.username_input.text(),
                password=self.password_field.text(),
                confirm_password=self.confirm_field.text(),
                company_name=self.company_input.text(),
                app_name=self.app_name_input.text(),
            )
            phone = self.company_phone_input.text().strip()
            address = self.company_address_input.text().strip()
            updates = {}
            if phone:
                updates["company_phone"] = phone
            if address:
                updates["company_address"] = address
            if updates:
                self.services.settings.update(ctx, updates)
        except AppError as exc:
            field = getattr(exc, "field", None)
            if field == "username":
                self.username_field.set_error(str(exc))
            elif field == "full_name":
                self.full_name_field.set_error(str(exc))
            else:
                self.error_label.setText(str(exc))
                self.error_label.setVisible(True)
            self.next_button.setEnabled(True)
            self.next_button.setText("تکمیل راه‌اندازی")
            return
        self.next_button.setEnabled(True)
        self.completed.emit(ctx)


class LoginWindow(QWidget):
    """Container that shows either the login form or the setup wizard."""

    authenticated = Signal(object)
    setup_completed = Signal(object)

    def __init__(self, services: AppServices, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        snapshot = services.settings.snapshot()
        self.setWindowTitle(snapshot.app_name)
        self.setMinimumSize(880, 580)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        outer.setSpacing(0)

        card = QFrame()
        card.setObjectName("LoginCard")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        self.pages = QStackedWidget()
        self.login_page = LoginPage(services)
        self.login_page.authenticated.connect(self.authenticated.emit)
        self.setup_page = SetupPage(services)
        self.setup_page.completed.connect(self._on_setup_completed)
        self.pages.addWidget(self.login_page)
        self.pages.addWidget(self.setup_page)

        self.brand = BrandPanel(snapshot.app_name, snapshot.company_name,
                                "ورود امن، نقش‌محور و قابل حسابرسی")
        card_layout.addWidget(self.brand)
        card_layout.addWidget(self.pages, 1)
        outer.addWidget(card)
        apply_shadow(card, blur=40, alpha=40)

        status = services.auth.setup_status()
        if status.needs_setup:
            self.pages.setCurrentWidget(self.setup_page)
        else:
            self.pages.setCurrentWidget(self.login_page)
            self.login_page.username_input.setFocus()

    def _on_setup_completed(self, ctx) -> None:
        self.setup_completed.emit(ctx)
        self.authenticated.emit(ctx)


class SetupWindow(LoginWindow):
    """Alias kept for clarity in tests and documentation."""
