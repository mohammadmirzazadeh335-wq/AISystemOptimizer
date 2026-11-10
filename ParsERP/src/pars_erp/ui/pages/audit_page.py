"""Security events and audit trail with filters, paging and CSV export."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.services.audit_service import (
    AuditFilter,
    AuditService,
    EventType,
    EVENT_TITLES_FA,
    SEVERITY_TITLES_FA,
    SecurityEventFilter,
)
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.table_specs import AUDIT_COLUMNS, SECURITY_EVENT_COLUMNS
from pars_erp.ui.widgets.common import SearchInput
from pars_erp.ui.widgets.pagination import PaginationBar
from pars_erp.ui.widgets.table import DataTable


class _EventTab(QWidget):
    """Security events tab."""

    def __init__(self, page: "AuditPage") -> None:
        super().__init__()
        self.page = page
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.search = SearchInput("جست‌وجو در شرح رویداد یا کاربر…")
        self.search.searchChanged.connect(lambda _t: page.reload(reset_page=True))
        filters.addWidget(self.search, 1)

        self.event_combo = QComboBox()
        self.event_combo.addItem("همه رویدادها", None)
        for code in EventType.ALL:
            self.event_combo.addItem(EVENT_TITLES_FA.get(code, code), code)
        self.event_combo.currentIndexChanged.connect(lambda _i: page.reload(reset_page=True))
        filters.addWidget(self.event_combo)

        self.severity_combo = QComboBox()
        self.severity_combo.addItem("همه سطوح", None)
        for code, title in SEVERITY_TITLES_FA.items():
            self.severity_combo.addItem(title, code)
        self.severity_combo.currentIndexChanged.connect(lambda _i: page.reload(reset_page=True))
        filters.addWidget(self.severity_combo)
        layout.addLayout(filters)

        self.table = DataTable(SECURITY_EVENT_COLUMNS, formatter=page.formatter)
        self.table.setMinimumHeight(300)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.pagination = PaginationBar()
        self.pagination.set_persian_digits(page.formatter.persian_digits)
        self.pagination.pageChanged.connect(lambda p: page.reload(page=p))
        footer.addStretch(1)
        footer.addWidget(self.pagination)
        layout.addLayout(footer)

    def filters(self) -> SecurityEventFilter:
        return SecurityEventFilter(
            event_type=self.event_combo.currentData(),
            severity=self.severity_combo.currentData(),
            search=self.search.text() or None,
        )


class _AuditTab(QWidget):
    """Business change history tab."""

    def __init__(self, page: "AuditPage") -> None:
        super().__init__()
        self.page = page
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.search = SearchInput("جست‌وجو در شرح تغییرات…")
        self.search.searchChanged.connect(lambda _t: page.reload(reset_page=True))
        filters.addWidget(self.search, 1)

        self.entity_combo = QComboBox()
        self.entity_combo.addItem("همه موجودیت‌ها", None)
        for code, title in (("user", "کاربر"), ("role", "نقش"),
                            ("app_setting", "تنظیمات"), ("database", "پایگاه داده")):
            self.entity_combo.addItem(title, code)
        self.entity_combo.currentIndexChanged.connect(lambda _i: page.reload(reset_page=True))
        filters.addWidget(self.entity_combo)

        self.action_combo = QComboBox()
        self.action_combo.addItem("همه عملیات", None)
        for code, title in (("create", "ایجاد"), ("update", "ویرایش"), ("delete", "حذف"),
                            ("disable", "غیرفعال‌سازی"), ("enable", "فعال‌سازی"),
                            ("reset_password", "بازنشانی رمز"), ("restore", "بازیابی"),
                            ("change_password", "تغییر رمز")):
            self.action_combo.addItem(title, code)
        self.action_combo.currentIndexChanged.connect(lambda _i: page.reload(reset_page=True))
        filters.addWidget(self.action_combo)
        layout.addLayout(filters)

        self.table = DataTable(AUDIT_COLUMNS, formatter=page.formatter)
        self.table.setMinimumHeight(300)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.pagination = PaginationBar()
        self.pagination.set_persian_digits(page.formatter.persian_digits)
        self.pagination.pageChanged.connect(lambda p: page.reload(page=p))
        footer.addStretch(1)
        footer.addWidget(self.pagination)
        layout.addLayout(footer)

    def filters(self) -> AuditFilter:
        return AuditFilter(
            entity_type=self.entity_combo.currentData(),
            action=self.action_combo.currentData(),
            search=self.search.text() or None,
        )


class AuditPage(PageBase):
    def __init__(self, services, ctx, formatter, *, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.header = PageHeader(
            "رویدادها و تاریخچه",
            "رویدادهای امنیتی و تغییرات مهم، همراه با کاربر، زمان و رایانه انجام‌دهنده")
        self.export_button = self.header.add_action("خروجی CSV", variant="ghost",
                                                    slot=self._export)
        self.header.add_action("بازخوانی", variant="ghost", slot=self.refresh)
        self.root.addWidget(self.header)

        card = CardPanel()
        self.tabs = QTabWidget()
        self.events_tab = _EventTab(self)
        self.audit_tab = _AuditTab(self)
        self.tabs.addTab(self.events_tab, "رویدادهای امنیتی")
        self.tabs.addTab(self.audit_tab, "تاریخچه تغییرات")
        self.tabs.currentChanged.connect(lambda _i: self.reload(reset_page=True))
        card.add(self.tabs, 1)
        self.root.addWidget(card, 1)
        self.export_button.setVisible(self.can("audit.export"))
        self._page = 1

    # ---------------------------------------------------------------- queries
    def reload(self, *, page: int | None = None, reset_page: bool = False) -> None:
        if reset_page:
            self._page = 1
        if page is not None:
            self._page = page
        page_size = self.services.settings.snapshot().table_page_size
        try:
            if self.tabs.currentIndex() == 0:
                result = self.services.audit.list_security_events(
                    self.events_tab.filters(), page=self._page, page_size=page_size)
                self.events_tab.table.set_rows([self._decorate(e) for e in result.items])
                self.events_tab.pagination.update_page(result)
            else:
                result = self.services.audit.list_audit_logs(
                    self.audit_tab.filters(), page=self._page, page_size=page_size)
                self.audit_tab.table.set_rows(list(result.items))
                self.audit_tab.pagination.update_page(result)
        except AppError as exc:
            show_error(self, "خطا در خواندن رویدادها", exc)
            return
        self._page = result.page
        self.header.set_subtitle(f"{self.formatter.number(result.total)} رکورد مطابق فیلترهای فعلی")

    def _decorate(self, event):
        """Badge column needs a tone key; severity codes already match the tone map."""
        return event

    def refresh(self) -> None:
        self.reload()

    def _export(self) -> None:
        is_events = self.tabs.currentIndex() == 0
        prefix = "security_events" if is_events else "audit_logs"
        suggested = self.services.exporter.default_filename(prefix)
        path, _ = QFileDialog.getSaveFileName(self, "ذخیره خروجی", str(suggested), "CSV (*.csv)")
        if not path:
            return
        try:
            if is_events:
                result = self.services.exporter.export_security_events(
                    self.ctx, Path(path), filters=self.events_tab.filters())
            else:
                result = self.services.exporter.export_audit_logs(
                    self.ctx, Path(path), filters=self.audit_tab.filters())
        except AppError as exc:
            show_error(self, "خطا در خروجی گرفتن", exc)
            return
        self.notify(result.message_fa)
        show_info(self, "خروجی گرفته شد", result.message_fa, details=str(result.path))
