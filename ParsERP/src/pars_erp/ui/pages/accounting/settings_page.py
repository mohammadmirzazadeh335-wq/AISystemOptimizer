"""Accounting settings: coding mask, workflow enforcement and currency column."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
)

from pars_erp.core.errors import AppError
from pars_erp.services.accounting_common import parse_mask
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader


class AccountingSettingsPage(PageBase):
    settingsSaved = Signal()

    def __init__(self, services, ctx, formatter, *, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.header = PageHeader("تنظیمات حسابداری",
                                 "الگوی کدینگ، اجرای گردش تأیید و نمایش ارز در سند")
        self.save_button = self.header.add_action("ذخیره تنظیمات", slot=self._save)
        self.header.add_action("بازخوانی", variant="ghost", slot=self.refresh)
        self.root.addWidget(self.header)

        card = CardPanel("کدینگ حساب‌ها",
                         "الگوی کدینگ را می‌توان پیش از ثبت حساب‌ها تغییر داد.")
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.mask_edit = QLineEdit()
        self.mask_edit.setPlaceholderText("1-2-3")
        self.mask_edit.setMaximumWidth(200)
        form.addRow("الگوی کدینگ", self.mask_edit)
        self.mask_hint = QLabel("")
        self.mask_hint.setObjectName("HintText")
        self.mask_hint.setWordWrap(True)
        form.addRow("", self.mask_hint)
        self.mask_edit.textChanged.connect(self._update_hint)

        self.workflow_check = QCheckBox("سند باید مراحل «در انتظار تأیید» و «تأییدشده» را طی کند")
        form.addRow("گردش تأیید", self.workflow_check)

        self.currency_check = QCheckBox("ستون ارز و نرخ در فرم سند نمایش داده شود")
        form.addRow("نمایش ارز", self.currency_check)

        card.add_layout(form)
        self.root.addWidget(card)

        info = CardPanel("راهنما")
        text = QLabel(
            "• تغییر الگوی کدینگ پس از ثبت حساب‌ها مجاز نیست؛ برای شروع دوباره، ابتدا "
            "حساب‌های بدون گردش را حذف کنید.\n"
            "• با فعال بودن گردش تأیید، سند پس از ذخیره در وضعیت پیش‌نویس است و تا "
            "تأیید و ثبت نهایی در گزارش‌ها اثری ندارد.\n"
            "• تمام گزارش‌ها فقط اسناد «ثبت نهایی» را محاسبه می‌کنند.")
        text.setWordWrap(True)
        text.setObjectName("HintText")
        info.add(text)
        self.root.addWidget(info)

        self.status_label = QLabel("")
        self.status_label.setObjectName("HintText")
        self.root.addWidget(self.status_label)
        self.root.addStretch(1)

    # ------------------------------------------------------------------- data
    def refresh(self) -> None:
        snapshot = self.services.settings.snapshot()
        self.mask_edit.setText(str(snapshot.raw("accounting_code_mask") or "1-2-3"))
        self.workflow_check.setChecked(bool(snapshot.raw("accounting_enforce_workflow")))
        self.currency_check.setChecked(bool(snapshot.raw("accounting_show_currency")))
        self._update_hint()
        try:
            count = len(self.services.accounts.list_accounts(self.ctx))
        except AppError:
            count = 0
        self.status_label.setText(
            f"{count} حساب ثبت شده است. "
            + ("تغییر الگوی کدینگ پس از ثبت حساب مجاز نیست." if count else
               "هنوز حسابی ثبت نشده؛ می‌توانید الگوی کدینگ را آزادانه تغییر دهید."))

    def _update_hint(self) -> None:
        try:
            mask = parse_mask(self.mask_edit.text())
        except AppError as error:
            self.mask_hint.setText(getattr(error, "message_fa", None) or str(error))
            return
        self.mask_hint.setText(
            "گروه {0} رقم · کل {1} رقم · معین {2} رقم".format(
                mask[0], sum(mask[:2]), sum(mask[:3])))

    # ------------------------------------------------------------------ write
    def _save(self) -> None:
        if not self.can("accounting.settings"):
            self.notify("برای تغییر تنظیمات حسابداری مجوز لازم است.")
            return
        updates = {
            "accounting_code_mask": self.mask_edit.text().strip(),
            "accounting_enforce_workflow": self.workflow_check.isChecked(),
            "accounting_show_currency": self.currency_check.isChecked(),
        }
        try:
            changed = self.services.settings.update(self.ctx, updates)
        except AppError as error:
            show_error(self, "ذخیره تنظیمات حسابداری", error)
            return
        if changed:
            show_info(self, "تنظیمات حسابداری",
                      f"{len(changed)} تنظیم ذخیره شد.", tone="success")
            self.settingsSaved.emit()
        else:
            show_info(self, "تنظیمات حسابداری", "تغییری برای ذخیره وجود نداشت.")
        self.refresh()
