"""Backup, verification and restore screen."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)

from pars_erp.core.errors import AppError
from pars_erp.services.backup_service import BackupInfo
from pars_erp.ui.dialogs.common_dialogs import (
    ConfirmDialog,
    show_error,
    show_info,
)
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.table_specs import BACKUP_COLUMNS
from pars_erp.ui.widgets.common import InfoRow
from pars_erp.ui.widgets.table import DataTable


class BackupPage(PageBase):
    def __init__(self, services, ctx, formatter, *, on_restored=None, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self._on_restored = on_restored

        self.header = PageHeader("پشتیبان‌گیری و بازیابی",
                                 "نسخه پشتیبان معتبر، قابل بررسی و قابل بازیابی از پایگاه داده")
        self.create_button = self.header.add_action("ایجاد پشتیبان", slot=self._create_backup)
        self.header.add_action("بازخوانی", variant="ghost", slot=self.refresh)
        self.root.addWidget(self.header)

        note_row = QHBoxLayout()
        note_row.setSpacing(8)
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("یادداشت اختیاری برای این نسخه پشتیبان (مثلاً: پایان ماه مهر)")
        note_row.addWidget(self.note_input, 1)
        self.current_backup_button = QPushButton("پشتیبان‌گیری همین حالا")
        self.current_backup_button.setProperty("variant", "primary")
        self.current_backup_button.clicked.connect(self._create_backup)
        note_row.addWidget(self.current_backup_button)
        self.root.addLayout(note_row)

        info_card = CardPanel("وضعیت پشتیبان‌گیری")
        info_grid = QGridLayout()
        info_grid.setSpacing(8)
        self.info_last = InfoRow("آخرین پشتیبان")
        self.info_count = InfoRow("تعداد پشتیبان‌ها")
        self.info_size = InfoRow("حجم کل پشتیبان‌ها")
        self.info_folder = InfoRow("پوشه پشتیبان")
        self.info_retention = InfoRow("سیاست نگهداری")
        self.info_database = InfoRow("پایگاه داده")
        for index, row in enumerate((self.info_last, self.info_count, self.info_size,
                                     self.info_folder, self.info_retention,
                                     self.info_database)):
            info_grid.addWidget(row, index // 3, index % 3)
        info_card.add_layout(info_grid)
        self.root.addWidget(info_card)

        table_card = CardPanel("نسخه‌های پشتیبان موجود")
        self.table = DataTable(BACKUP_COLUMNS, formatter=self.formatter)
        self.table.setMinimumHeight(240)
        table_card.add(self.table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.verify_button = QPushButton("بررسی صحت")
        self.verify_button.setProperty("variant", "ghost")
        self.verify_button.clicked.connect(self._verify)
        self.restore_button = QPushButton("بازیابی این نسخه")
        self.restore_button.setProperty("variant", "danger")
        self.restore_button.clicked.connect(self._restore)
        self.delete_button = QPushButton("حذف فایل پشتیبان")
        self.delete_button.setProperty("variant", "ghost")
        self.delete_button.clicked.connect(self._delete)
        self.import_button = QPushButton("افزودن فایل پشتیبان از دیسک")
        self.import_button.setProperty("variant", "ghost")
        self.import_button.clicked.connect(self._import_copy)
        for button in (self.verify_button, self.restore_button, self.delete_button,
                       self.import_button):
            actions.addWidget(button)
        actions.addStretch(1)
        table_card.add_layout(actions)
        self.root.addWidget(table_card, 1)

        warning = QLabel(
            "بازیابی، پایگاه داده فعلی را با نسخه انتخاب‌شده جایگزین می‌کند. پیش از بازیابی "
            "به‌صورت خودکار یک پشتیبان ایمنی از وضعیت فعلی گرفته می‌شود.")
        warning.setWordWrap(True)
        warning.setObjectName("HintText")
        self.root.addWidget(warning)

        self.create_button.setVisible(self.can("backup.create"))
        self.current_backup_button.setVisible(self.can("backup.create"))
        self.restore_button.setEnabled(self.can("backup.restore"))
        self.delete_button.setEnabled(self.can("backup.delete"))

    # ---------------------------------------------------------------- helpers
    def _selected(self) -> BackupInfo | None:
        return self.table.current_row()

    def refresh(self) -> None:
        try:
            backups = self.services.backups.list_backups(self.ctx)
        except AppError as exc:
            show_error(self, "خطا در خواندن پشتیبان‌ها", exc)
            return
        self.table.set_rows(backups)
        snapshot = self.services.settings.snapshot()
        last = backups[0] if backups else None
        self.info_last.set_value(
            f"{self.formatter.datetime(last.created_at)} — {last.filename}" if last
            else "بدون پشتیبان")
        self.info_count.set_value(
            self.formatter.number(len(backups)) if backups else "هیچ نسخه‌ای ثبت نشده")
        total_mb = round(sum(item.size_bytes for item in backups) / (1024 * 1024), 2)
        self.info_size.set_value(
            f"{self.formatter.number(int(total_mb))} مگابایت" if backups else "—")
        self.info_folder.set_value(str(self.services.backups.backup_dir()))
        self.info_retention.set_value(
            f"نگهداری {self.formatter.number(snapshot.backup_retention)} نسخه — "
            f"{'خودکار فعال' if snapshot.bool('auto_backup_on_startup') else 'خودکار غیرفعال'}")
        self.info_database.set_value(self.services.db.dialect_name())
        self.header.set_subtitle(f"{self.formatter.number(len(backups))} نسخه پشتیبان در پوشه پشتیبان‌گیری")

    # ---------------------------------------------------------------- actions
    def _create_backup(self) -> None:
        if not self.can("backup.create"):
            self.notify("شما مجوز ایجاد پشتیبان را ندارید.")
            return
        try:
            info = self.services.backups.create_backup(self.ctx, note=self.note_input.text().strip() or None)
            retention = self.services.settings.snapshot().backup_retention
            self.services.backups.prune(self.ctx, keep=retention)
        except AppError as exc:
            show_error(self, "پشتیبان‌گیری ناموفق بود", exc)
            return
        self.note_input.clear()
        self.notify(f"پشتیبان «{info.filename}» ایجاد شد ({info.size_mb} مگابایت).")
        self.refresh()

    def _verify(self) -> None:
        info = self._selected()
        if info is None:
            self.notify("ابتدا یک نسخه پشتیبان را انتخاب کنید.")
            return
        result = self.services.backups.verify_backup(info.path, ctx=self.ctx)
        if result.ok:
            show_info(self, "صحت پشتیبان تأیید شد",
                      f"فایل «{info.filename}» سالم است و قابل بازیابی است.",
                      details="\n".join(f"{key}: {'✓' if value else '✗'}"
                                        for key, value in result.checks.items()))
            self.refresh()
        else:
            show_error(self, "پشتیبان معتبر نیست", Exception(result.message_fa))

    def _restore(self) -> None:
        info = self._selected()
        if info is None:
            self.notify("ابتدا یک نسخه پشتیبان را انتخاب کنید.")
            return
        snapshot = self.services.settings.snapshot()
        password_hint = ""
        password = ""
        if snapshot.bool("require_password_for_restore"):
            from PySide6.QtWidgets import QInputDialog
            password, ok = QInputDialog.getText(
                self, "تأیید هویت", "برای بازیابی، رمز عبور خود را وارد کنید:",
                QLineEdit.EchoMode.Password)
            if not ok:
                return
            if not self.services.auth.verify_password(self.ctx, password):
                show_error(self, "تأیید هویت ناموفق",
                           Exception("رمز عبور نادرست است. بازیابی انجام نشد."))
                return

        dialog = ConfirmDialog(
            self, title="بازیابی پایگاه داده",
            message=(f"پایگاه داده فعلی با نسخه «{info.filename}» "
                     f"({self.formatter.datetime(info.created_at)}) جایگزین می‌شود.\n"
                     "تغییرات پس از تاریخ این پشتیبان از دست می‌روند. "
                     "یک پشتیبان ایمنی خودکار گرفته می‌شود."),
            confirm_text="بازیابی کن", danger=True, require_phrase="بازیابی")
        if not dialog.exec():
            return
        try:
            result = self.services.backups.restore_backup(
                self.ctx, info.path, confirm_phrase=dialog.phrase())
        except AppError as exc:
            show_error(self, "بازیابی ناموفق بود", exc)
            return
        show_info(self, "بازیابی انجام شد",
                  "پایگاه داده با موفقیت بازیابی شد.",
                  details=f"پشتیبان ایمنی: {result.safety_backup}")
        self.notify("بازیابی انجام شد.")
        if self._on_restored:
            self._on_restored()
        self.refresh()

    def _delete(self) -> None:
        info = self._selected()
        if info is None:
            self.notify("ابتدا یک نسخه پشتیبان را انتخاب کنید.")
            return
        dialog = ConfirmDialog(self, title="حذف فایل پشتیبان",
                               message=f"فایل «{info.filename}» حذف شود؟ این عملیات قابل بازگشت نیست.",
                               confirm_text="حذف", danger=True)
        if not dialog.exec():
            return
        try:
            self.services.backups.delete_backup(self.ctx, info.path)
        except AppError as exc:
            show_error(self, "حذف ناموفق", exc)
            return
        self.notify("فایل پشتیبان حذف شد.")
        self.refresh()

    def _import_copy(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "انتخاب فایل پشتیبان", "", "Zip (*.zip)")
        if not path:
            return
        source = Path(path)
        verification = self.services.backups.verify_backup(source, ctx=self.ctx)
        if not verification.ok:
            show_error(self, "فایل معتبر نیست", Exception(verification.message_fa))
            return
        target = self.services.backups.backup_dir() / source.name
        if not target.exists():
            import shutil
            shutil.copy2(source, target)
        show_info(self, "فایل افزوده شد",
                  f"فایل «{source.name}» در پوشه پشتیبان‌گیری قرار گرفت و قابل بازیابی است.")
        self.refresh()
