"""The alert inbox: what the rules found, and the rules themselves."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton

from pars_erp.core.errors import AppError
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.table_specs import BADGE, DATETIME, TEXT, ColumnSpec
from pars_erp.ui.widgets.table import DataTable

ALERT_COLUMNS = (
    ColumnSpec("severity_fa", "اهمیت", BADGE, 90),
    ColumnSpec("title_fa", "هشدار", TEXT),
    ColumnSpec("message_fa", "شرح", TEXT),
    ColumnSpec("raised_at", "زمان", DATETIME, 140),
    ColumnSpec("note_fa", "یادداشت", TEXT, 160),
)

RULE_COLUMNS = (
    ColumnSpec("title_fa", "قاعده", TEXT),
    ColumnSpec("section", "بخش", TEXT, 90),
    ColumnSpec("severity_fa", "اهمیت", BADGE, 90),
    ColumnSpec("is_enabled", "فعال", TEXT, 70),
    ColumnSpec("threshold_text", "آستانه", TEXT, 180),
    ColumnSpec("last_evaluated_at", "آخرین ارزیابی", DATETIME, 150),
)


class AlertsPage(PageBase):
    def __init__(self, services, ctx, formatter, *, on_navigate=None, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self._on_navigate = on_navigate
        self.header = PageHeader("هشدارهای مدیریتی",
                                 "هشدارها فقط از دادهٔ واقعی ساخته می‌شوند و تکرار نمی‌شوند")
        self.header.add_action("ارزیابی دوباره", slot=self.evaluate)
        self.root.addWidget(self.header)

        self.open_card = CardPanel("هشدارهای باز", "به ترتیب اهمیت")
        self.table = DataTable(ALERT_COLUMNS, formatter=formatter)
        self.open_card.add(self.table, 1)
        actions = QHBoxLayout()
        self.ack_button = QPushButton("تأیید مشاهده")
        self.ack_button.clicked.connect(lambda: self._act("acknowledge"))
        self.resolve_button = QPushButton("بستن هشدار")
        self.resolve_button.setProperty("variant", "ghost")
        self.resolve_button.clicked.connect(lambda: self._act("resolve"))
        self.note_edit = QLabel("یادداشت در فهرست هشدارهای باز قابل ویرایش نیست؛ "
                                "در بستن هشدار ثبت می‌شود.")
        self.note_edit.setObjectName("HintText")
        actions.addWidget(self.ack_button)
        actions.addWidget(self.resolve_button)
        actions.addWidget(self.note_edit, 1)
        self.open_card.add_layout(actions)
        self.root.addWidget(self.open_card, 1)

        self.rules_card = CardPanel("قواعد هشدار", "روشن/خاموش کردن و تغییر سطح اهمیت")
        self.rules_table = DataTable(RULE_COLUMNS, formatter=formatter)
        self.rules_card.add(self.rules_table, 1)
        rule_actions = QHBoxLayout()
        self.severity_combo = QComboBox()
        self.severity_combo.addItem("اطلاع", "info")
        self.severity_combo.addItem("هشدار", "warning")
        self.severity_combo.addItem("بحرانی", "critical")
        self.enabled_check = QCheckBox("قاعده فعال باشد")
        self.apply_button = QPushButton("اعمال روی قاعدهٔ انتخاب‌شده")
        self.apply_button.clicked.connect(self._apply_rule)
        rule_actions.addWidget(self.enabled_check)
        rule_actions.addWidget(self.severity_combo)
        rule_actions.addWidget(self.apply_button)
        rule_actions.addStretch(1)
        self.rules_card.add_layout(rule_actions)
        self.root.addWidget(self.rules_card, 1)

        self._apply_permissions()
        self.refresh()

    def _apply_permissions(self) -> None:
        can_manage = self.can("alerts.manage")
        self.ack_button.setEnabled(can_manage)
        self.resolve_button.setEnabled(can_manage)
        self.apply_button.setEnabled(can_manage)
        self.enabled_check.setEnabled(can_manage)
        self.severity_combo.setEnabled(can_manage)

    def refresh(self) -> None:
        try:
            alerts = list(self.services.alerts.open_alerts(self.ctx))
            rules = list(self.services.alerts.rules(self.ctx))
        except AppError as exc:
            show_error(self, "خطا", exc)
            return
        self._alerts = alerts
        self._rules = rules
        self.table.set_rows(alerts)
        rows = [_RuleRow(rule) for rule in rules]
        self.rules_table.set_rows(rows)

    def evaluate(self) -> None:
        try:
            created = self.services.alerts.evaluate(self.ctx)
        except AppError as exc:
            show_error(self, "خطا", exc)
            return
        self.refresh()
        show_info(self, "زرین هرمز", f"{len(created)} هشدار تازه ثبت شد." if created
                  else "هشدار تازه‌ای پیدا نشد.")

    def _selected_alert(self):
        index = self.table.selected_row_index()
        if index is None or index >= len(self._alerts):
            return None
        return self._alerts[index]

    def _act(self, action: str) -> None:
        alert = self._selected_alert()
        if alert is None:
            show_info(self, "زرین هرمز", "یک هشدار را انتخاب کنید.")
            return
        try:
            if action == "acknowledge":
                self.services.alerts.acknowledge(self.ctx, alert.id)
            else:
                self.services.alerts.resolve(self.ctx, alert.id)
        except AppError as exc:
            show_error(self, "خطا", exc)
            return
        self.refresh()

    def _apply_rule(self) -> None:
        index = self.rules_table.selected_row_index()
        if index is None or index >= len(self._rules):
            show_info(self, "زرین هرمز", "یک قاعده را انتخاب کنید.")
            return
        rule = self._rules[index]
        try:
            self.services.alerts.set_rule(
                self.ctx, rule.key, is_enabled=self.enabled_check.isChecked(),
                severity=self.severity_combo.currentData())
        except AppError as exc:
            show_error(self, "خطا", exc)
            return
        self.refresh()


class _RuleRow:
    """Flat view of an alert rule for the table."""

    def __init__(self, rule) -> None:
        self.id = rule.id
        self.key = rule.key
        self.title_fa = rule.title_fa
        self.section = rule.section
        self.severity_fa = rule.severity_fa
        self.is_enabled = "بله" if rule.is_enabled else "خیر"
        self.threshold_text = "، ".join(f"{key}={value}"
                                        for key, value in rule.threshold.items()) or "—"
        self.last_evaluated_at = rule.last_evaluated_at
