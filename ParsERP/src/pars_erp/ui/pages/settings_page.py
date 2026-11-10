"""Settings screen generated from the settings registry, plus an About panel."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pars_erp import __version__
from pars_erp.core.errors import AppError
from pars_erp.services.settings_service import SettingDef, SettingsService, TYPE_BOOL, TYPE_CHOICE, TYPE_INT
from pars_erp.ui.dialogs.common_dialogs import ConfirmDialog, show_info
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.widgets.common import InfoRow


class SettingsPage(PageBase):
    settingsSaved = Signal()

    def __init__(self, services, ctx, formatter, *, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self._widgets: dict[str, QWidget] = {}
        self._defs: dict[str, SettingDef] = {}

        self.header = PageHeader("تنظیمات", "پیکربندی شرکت، ظاهر برنامه، امنیت و پشتیبان‌گیری")
        self.save_button = self.header.add_action("ذخیره تغییرات", slot=self._save)
        self.reset_button = self.header.add_action("بازگردانی پیش‌فرض‌ها", variant="ghost",
                                                   slot=self._reset)
        self.header.add_action("بازخوانی", variant="ghost", slot=self.refresh)
        self.root.addWidget(self.header)

        self.tabs = QTabWidget()
        grouped = SettingsService.definitions_by_group()
        for code, title in SettingsService.group_titles():
            if code == "general":
                continue
            self.tabs.addTab(self._build_tab(grouped.get(code, [])), title)
        self.tabs.insertTab(0, self._build_general_tab(grouped.get("general", [])), "اطلاعات شرکت")
        self.tabs.addTab(self._build_about_tab(), "درباره برنامه")
        self.root.addWidget(self.tabs, 1)

        self.error_label = QLabel("")
        self.error_label.setObjectName("ErrorText")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        self.root.addWidget(self.error_label)
        self.save_button.setVisible(self.can("settings.edit"))

    # ------------------------------------------------------------------ build
    def _build_general_tab(self, definitions: list[SettingDef]) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        card = CardPanel("اطلاعات شرکت", "این اطلاعات در سرصفحه گزارش‌ها و عنوان پنجره استفاده می‌شود")
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for definition in definitions:
            widget = self._create_widget(definition)
            label = QLabel(definition.label_fa)
            label.setObjectName("FieldLabel")
            form.addRow(label, widget)
            if definition.help_fa:
                hint = QLabel(definition.help_fa)
                hint.setObjectName("HintText")
                hint.setWordWrap(True)
                form.addRow(QLabel(""), hint)
        card.add_layout(form)
        layout.addWidget(card)
        layout.addStretch(1)
        return self._wrap_scroll(container)

    def _build_tab(self, definitions: list[SettingDef]) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        card = CardPanel()
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for definition in definitions:
            widget = self._create_widget(definition)
            label = QLabel(definition.label_fa)
            label.setObjectName("FieldLabel")
            form.addRow(label, widget)
            if definition.help_fa:
                hint = QLabel(definition.help_fa)
                hint.setObjectName("HintText")
                hint.setWordWrap(True)
                form.addRow(QLabel(""), hint)
        card.add_layout(form)
        layout.addWidget(card)
        layout.addStretch(1)
        return self._wrap_scroll(container)

    @staticmethod
    def _wrap_scroll(container: QWidget) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(container)
        return scroll

    def _create_widget(self, definition: SettingDef) -> QWidget:
        self._defs[definition.key] = definition
        if definition.type == TYPE_BOOL:
            widget: QWidget = QCheckBox("فعال")
        elif definition.type == TYPE_INT:
            spin = QSpinBox()
            spin.setRange(definition.min_value if definition.min_value is not None else 0,
                          definition.max_value if definition.max_value is not None else 100000)
            spin.setMinimumWidth(150)
            spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            widget = spin
        elif definition.type == TYPE_CHOICE:
            combo = QComboBox()
            for code, title in definition.choices:
                combo.addItem(title, code)
            combo.setMinimumWidth(180)
            widget = combo
        else:
            edit = QLineEdit()
            if definition.max_length:
                edit.setMaxLength(definition.max_length)
            widget = edit
        widget.setEnabled(self.can("settings.edit"))
        widget.setMaximumWidth(360)
        self._widgets[definition.key] = widget
        return widget

    def _build_about_tab(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        card = CardPanel("درباره برنامه",
                         "ParsERP — نرم‌افزار جامع حسابداری و مدیریت کسب‌وکار (نسخه مستقل)")
        self.about_rows: dict[str, InfoRow] = {}
        for key, label in (("version", "نسخه برنامه"), ("phase", "فاز توسعه"),
                           ("schema", "نسخه ساختار پایگاه داده"),
                           ("backend", "موتور پایگاه داده"),
                           ("database", "مسیر پایگاه داده"),
                           ("home", "پوشه داده برنامه"),
                           ("logs", "پوشه گزارش‌ها"),
                           ("backups", "پوشه پشتیبان‌ها"),
                           ("hostname", "نام رایانه"),
                           ("fonts", "قلم رابط کاربری")):
            row = InfoRow(label, "—")
            self.about_rows[key] = row
            card.add(row)
        note = QLabel(
            "این نسخه شامل زیرساخت امنیتی، مدیریت کاربران و نقش‌ها، تنظیمات، "
            "ثبت رویدادها، داشبورد و پشتیبان‌گیری است. ماژول‌های حسابداری، فروش، انبار، "
            "خزانه، حقوق و تولید در فازهای ۲ تا ۷ افزوده می‌شوند.")
        note.setWordWrap(True)
        note.setObjectName("HintText")
        card.add(note)
        layout.addWidget(card)
        layout.addStretch(1)
        return self._wrap_scroll(container)

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        snapshot = self.services.settings.snapshot()
        for key, widget in self._widgets.items():
            value = snapshot.raw(key)
            definition = self._defs[key]
            if definition.type == TYPE_BOOL:
                widget.setChecked(bool(value))
            elif definition.type == TYPE_INT:
                widget.setValue(int(value))
            elif definition.type == TYPE_CHOICE:
                index = widget.findData(value)
                widget.setCurrentIndex(index if index >= 0 else 0)
            else:
                widget.setText("" if value is None else str(value))
        self._refresh_about()
        self.error_label.setVisible(False)

    def _refresh_about(self) -> None:
        if not hasattr(self, "about_rows"):
            return
        services = self.services
        config = services.config
        from pars_erp.ui.fonts import available_families
        families = available_families()
        family_hint = "وزیرمتن (همراه برنامه)" if "Vazirmatn" in families else "قلم پیش‌فرض سیستم"
        safe_url = services.db.url
        if "@" in safe_url:
            prefix, rest = safe_url.split("://", 1)
            safe_url = f"{prefix}://***@{rest.split('@', 1)[1]}"
        values = {
            "version": __version__,
            "phase": "فاز ۱ — هسته، امنیت و مدیریت",
            "schema": services.db.schema_revision() or "—",
            "backend": services.db.dialect_name(),
            "database": safe_url,
            "home": str(services.paths.home),
            "logs": str(services.paths.logs_dir),
            "backups": str(services.paths.backups_dir),
            "hostname": services.hostname,
            "fonts": family_hint,
        }
        for key, value in values.items():
            self.about_rows[key].set_value(value)

    def _collect(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for key, widget in self._widgets.items():
            definition = self._defs[key]
            if definition.type == TYPE_BOOL:
                values[key] = widget.isChecked()
            elif definition.type == TYPE_INT:
                values[key] = widget.value()
            elif definition.type == TYPE_CHOICE:
                values[key] = widget.currentData()
            else:
                values[key] = widget.text()
        return values

    # --------------------------------------------------------------- actions
    def _save(self) -> None:
        self.error_label.setVisible(False)
        try:
            changed = self.services.settings.update(self.ctx, self._collect())
        except AppError as exc:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
            return
        if not changed:
            self.notify("تغییری برای ذخیره وجود نداشت.")
            return
        self.notify(f"{len(changed)} تنظیم ذخیره شد.")
        self.settingsSaved.emit()
        self.refresh()

    def _reset(self) -> None:
        dialog = ConfirmDialog(
            self, title="بازگردانی تنظیمات",
            message="همه تنظیمات به مقادیر پیش‌فرض کارخانه بازمی‌گردند. ادامه می‌دهید؟",
            confirm_text="بازگردانی", danger=True)
        if not dialog.exec():
            return
        try:
            self.services.settings.reset_to_defaults(
                self.ctx, [definition.key for definition in self._defs.values()])
        except AppError as exc:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)
            return
        self.notify("تنظیمات به مقادیر پیش‌فرض بازگردانده شد.")
        self.settingsSaved.emit()
        self.refresh()
