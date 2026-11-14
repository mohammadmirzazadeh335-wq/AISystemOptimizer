"""«درباره زرین هرمز» — the honest version page: only real, verifiable facts."""

from __future__ import annotations

import platform

from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from pars_erp import APP_NAME_DEFAULT, APP_NAME_EN, __version__
from pars_erp.core.errors import AppError
from pars_erp.core.jalali import JalaliDate
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.widgets.common import InfoRow

#: Libraries the shipped application imports, with their licence. Kept next to the
#: About screen so the list cannot silently drift away from what is bundled.
LIBRARIES: tuple[tuple[str, str, str], ...] = (
    ("PySide6 (Qt for Python)", "LGPL-3.0", "رابط کاربری دسکتاپ"),
    ("SQLAlchemy", "MIT", "دسترسی به پایگاه داده"),
    ("Alembic", "MIT", "مهاجرت ساختار پایگاه داده"),
    ("argon2-cffi", "MIT", "هش رمز عبور (Argon2id)"),
    ("openpyxl", "MIT", "خروجی Excel"),
    ("Vazirmatn", "SIL OFL 1.1", "قلم فارسی همراه برنامه"),
    ("cryptography", "Apache-2.0 / BSD-3-Clause", "بررسی امضای بستهٔ به‌روزرسانی"),
)


class AboutPage(PageBase):
    def __init__(self, services, ctx, formatter, *, on_navigate=None, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.header = PageHeader("دربارهٔ زرین هرمز", "اطلاعات نسخه و اجزای نرم‌افزار")
        self.root.addWidget(self.header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        about = CardPanel("شناسنامهٔ برنامه", "همهٔ مقادیر از خود برنامه خوانده می‌شوند")
        for label, value in self._identity_rows():
            about.add(InfoRow(label, value))
        layout.addWidget(about)

        environment = CardPanel("محیط اجرا", "نسخه‌های واقعی همین نصب")
        for label, value in self._environment_rows():
            environment.add(InfoRow(label, value))
        layout.addWidget(environment)

        libraries = CardPanel("کتابخانه‌ها و مجوزها", "فهرست اقلام همراه نسخهٔ اجرایی")
        grid = QGridLayout()
        grid.addWidget(self._header_label("کتابخانه"), 0, 0)
        grid.addWidget(self._header_label("مجوز"), 0, 1)
        grid.addWidget(self._header_label("کاربرد"), 0, 2)
        for index, (name, licence, usage) in enumerate(LIBRARIES, start=1):
            grid.addWidget(QLabel(name), index, 0)
            grid.addWidget(QLabel(licence), index, 1)
            grid.addWidget(QLabel(usage), index, 2)
        libraries.add_layout(grid)
        layout.addWidget(libraries)

        support = CardPanel("پشتیبانی", "اطلاعات پشتیبانی تنها در صورت تعریف در تنظیمات شرکت")
        self.support_label = QLabel("—")
        self.support_label.setWordWrap(True)
        support.add(self.support_label)
        layout.addWidget(support)

        updates = CardPanel("به‌روزرسانی برنامه",
                            "بررسی نسخه تنها وقتی انجام می‌شود که منبع آن تنظیم شده باشد")
        self.update_status_label = QLabel(self._update_summary())
        self.update_status_label.setWordWrap(True)
        updates.add(self.update_status_label)
        self.update_notes_label = QLabel("")
        self.update_notes_label.setObjectName("HintText")
        self.update_notes_label.setWordWrap(True)
        self.update_notes_label.setVisible(False)
        updates.add(self.update_notes_label)
        buttons = QHBoxLayout()
        self.check_button = QPushButton("بررسی به‌روزرسانی")
        self.check_button.clicked.connect(self.check_for_updates)
        self.stage_button = QPushButton("دریافت و آماده‌سازی نصب")
        self.stage_button.setProperty("variant", "primary")
        self.stage_button.setEnabled(False)
        self.stage_button.clicked.connect(self.stage_update)
        buttons.addWidget(self.check_button)
        buttons.addWidget(self.stage_button)
        buttons.addStretch(1)
        updates.add_layout(buttons)
        layout.addWidget(updates)

        note = QLabel(
            "فایل اجرایی و نصب‌کنندهٔ ویندوز در این محفظه ساخته نشده‌اند؛ برای ساخت آن‌ها "
            "به docs/phase7/09-packaging.md و packaging/ مراجعه کنید.")
        note.setObjectName("HintText")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        scroll.setWidget(container)
        self.root.addWidget(scroll, 1)

    # -------------------------------------------------------------- updates
    def _update_summary(self) -> str:
        pending = self.services.updates.pending()
        if pending:
            return (f"نسخهٔ {pending.get('to_version')} آمادهٔ نصب است؛ پس از بستن برنامه، "
                    f"نصب‌کننده آن را اعمال می‌کند (امضا: {pending.get('signature_status')}).")
        source = self.services.updates.source()
        if not source:
            return ("منبع به‌روزرسانی تنظیم نشده است. نشانی مانیفست را در تنظیمات "
                    "«به‌روزرسانی برنامه» وارد کنید.")
        return f"منبع بررسی: {source}"

    def check_for_updates(self) -> None:
        try:
            result = self.services.updates.check(self.ctx)
        except AppError as exc:
            show_error(self, "بررسی به‌روزرسانی", exc)
            return
        self.update_status_label.setText(f"{result.status_fa} — {result.message_fa}")
        release = result.release
        if release is not None:
            notes = release.notes_text()
            self.update_notes_label.setText(
                (f"تغییرات نسخهٔ {release.version} ({release.released_at}):\n{notes}"
                 if notes else f"نسخهٔ {release.version} تغییرات ثبت‌شده‌ای ندارد."))
            self.update_notes_label.setVisible(True)
            can_stage = "settings.edit" in (self.ctx.permissions if self.ctx else ())
            self.stage_button.setEnabled(can_stage)
        else:
            self.update_notes_label.setVisible(False)
            self.stage_button.setEnabled(False)

    def stage_update(self) -> None:
        try:
            result = self.services.updates.check(self.ctx)
            if not result.has_update or result.release is None:
                show_error(self, "به‌روزرسانی", "نسخهٔ تازه‌تری برای آماده‌سازی وجود ندارد.")
                return
            release = result.release
            package = self.services.updates.download(self.ctx, release)
            staged = self.services.updates.stage(self.ctx, release, package)
        except AppError as exc:
            show_error(self, "به‌روزرسانی", exc)
            return
        self.update_status_label.setText(staged.message_fa)
        show_info(self, "به‌روزرسانی", staged.message_fa, details=(
            f"نسخهٔ هدف: {release.version}\n"
            f"پشتیبان پیش از به‌روزرسانی: {staged.backup.name if staged.backup else '—'}"))

    # ---------------------------------------------------------------- content
    @staticmethod
    def _header_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("CardTitle")
        return label

    def _identity_rows(self) -> list[tuple[str, str]]:
        rows = [
            ("نام فارسی", APP_NAME_DEFAULT),
            ("نام انگلیسی", APP_NAME_EN),
            ("نسخه", __version__),
            ("شمارهٔ ساخت", self._build_number()),
            ("تاریخ این نصب", self._installed_at()),
        ]
        try:
            snapshot = self.services.settings.snapshot()
            rows.insert(3, ("نام شرکت", snapshot.company_name or "—"))
            rows.insert(4, ("کد اقتصادی", snapshot.str("company_economic_code") or "—"))
        except AppError:
            pass
        return rows

    def _environment_rows(self) -> list[tuple[str, str]]:
        rows = [
            ("نسخهٔ پایتون", platform.python_version()),
            ("سیستم عامل", f"{platform.system()} {platform.release()}"),
            ("پایگاه داده", self.services.db.dialect_name()),
            ("نسخهٔ ساختار پایگاه داده", self.services.db.schema_revision() or "—"),
        ]
        try:
            metadata = self.services.settings.snapshot()
            rows.append(("واحد پول", metadata.currency_code))
        except AppError:
            pass
        return rows

    def _build_number(self) -> str:
        """The build is the schema revision plus the version — never invented."""
        revision = self.services.db.schema_revision()
        return f"{__version__}+{revision}" if revision else __version__

    def _installed_at(self) -> str:
        try:
            with self.services.db.session_scope() as session:
                from pars_erp.db.models import AppMetadata
                metadata = session.get(AppMetadata, 1)
                if metadata is not None and metadata.first_run_at is not None:
                    return JalaliDate.from_gregorian(
                        metadata.first_run_at.date()).format(long=True)
        except Exception:  # pragma: no cover - a database without metadata yet
            return "—"
        return "—"
