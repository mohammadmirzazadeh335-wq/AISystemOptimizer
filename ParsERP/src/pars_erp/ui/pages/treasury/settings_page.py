"""Treasury settings: fund policy, alert days and the posting patterns."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QSpinBox, QWidget

from pars_erp.core.errors import AppError
from pars_erp.treasury import constants as TC
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.table_specs import TEXT, ColumnSpec
from pars_erp.ui.widgets.table import DataTable


class TreasurySettingsPage(PageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.header = PageHeader(
            "تنظیمات خزانه‌داری",
            "سیاست موجودی، روزهای هشدار چک و الگوهای ثبت حسابداری هر عملیات خزانه")
        self.header.add_action("ذخیره", slot=self._save)
        self.root.addWidget(self.header)

        policy = CardPanel("سیاست‌های خزانه‌داری")
        row = QHBoxLayout()
        self.negative_check = QCheckBox("اجازهٔ منفی شدن موجودی صندوق/بانک (نیازمند مجوز)")
        row.addWidget(self.negative_check)
        row.addStretch(1)
        self.alert_spin = QSpinBox()
        self.alert_spin.setRange(0, 120)
        self.alert_spin.setSuffix(" روز")
        row.addWidget(QLabel("هشدار سررسید چک:"))
        row.addWidget(self.alert_spin)
        self.stale_spin = QSpinBox()
        self.stale_spin.setRange(1, 365)
        self.stale_spin.setSuffix(" روز")
        row.addWidget(QLabel("آستانهٔ چک معوق:"))
        row.addWidget(self.stale_spin)
        policy.add_layout(row)
        self.root.addWidget(policy)

        rules_card = CardPanel("الگوهای ثبت حسابداری خزانه‌داری")
        self.rules_table = DataTable((
            ColumnSpec("operation_fa", "عملیات", TEXT, 240),
            ColumnSpec("title_fa", "عنوان الگو", TEXT, None),
            ColumnSpec("line_count", "تعداد سطر", TEXT, 110, "center"),
            ColumnSpec("is_active_fa", "وضعیت", TEXT, 90, "center"),
        ), formatter=formatter)
        rules_card.add(self.rules_table, 1)
        hint = QLabel("حساب‌های هر الگو از کدینگ حسابداری خوانده می‌شود؛ برای تغییر، از صفحهٔ "
                      "«تنظیمات بازرگانی → الگوهای ثبت» استفاده کنید. سند ثبت‌شده هرگز "
                      "تغییر نمی‌کند و اصلاح فقط با سند برگشتی انجام می‌شود.")
        hint.setObjectName("HintText")
        hint.setWordWrap(True)
        rules_card.add(hint)
        self.root.addWidget(rules_card, 1)
        self.refresh()

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        snapshot = self.services.settings.snapshot()
        try:
            self.negative_check.setChecked(snapshot.bool("treasury_allow_negative_fund"))
            self.alert_spin.setValue(snapshot.int("treasury_cheque_alert_days"))
            self.stale_spin.setValue(snapshot.int("treasury_stale_cheque_days"))
        except AppError:
            pass
        try:
            rules = self.services.posting.list_rules(self.ctx)
        except AppError as error:
            show_error(self, "الگوهای ثبت", error)
            return
        treasury_rules = [rule for rule in rules
                          if rule.operation in TC.POSTING_OPERATIONS]
        self.rules_table.set_rows([
            {"operation_fa": rule.operation_fa, "title_fa": rule.title_fa,
             "line_count": len(rule.lines),
             "is_active_fa": "فعال" if rule.is_active else "غیرفعال"}
            for rule in treasury_rules])

    def _save(self) -> None:
        try:
            self.services.settings.update(self.ctx, {
                "treasury_allow_negative_fund": "true" if self.negative_check.isChecked()
                else "false",
                "treasury_cheque_alert_days": str(self.alert_spin.value()),
                "treasury_stale_cheque_days": str(self.stale_spin.value()),
            })
        except AppError as error:
            show_error(self, "تنظیمات خزانه‌داری", error)
            return
        self.statusMessage.emit("تنظیمات خزانه‌داری ذخیره شد.")
        show_info(self, "تنظیمات", "تنظیمات خزانه‌داری ذخیره شد.", tone="success")
