"""فروش و کنارگذاری دارایی‌ها + فهرست تعمیر و نگهداری."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtWidgets import QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget

from pars_erp.core.errors import AppError
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.table_specs import DISPOSAL_COLUMNS, MAINTENANCE_COLUMNS
from pars_erp.ui.widgets.table import DataTable


class AssetDisposalsPage(PageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.disposals = []
        self.maintenance = []
        self.header = PageHeader(
            "فروش و کنارگذاری",
            "واگذاری دارایی با سند فروش/زیان، و فهرست تعمیر و نگهداری با هزینه")
        self.print_button = self.header.add_action("چاپ / PDF", slot=self._print)
        self.root.addWidget(self.header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_disposals(), "واگذاری‌ها")
        self.tabs.addTab(self._build_maintenance(), "تعمیر و نگهداری")
        self.root.addWidget(self.tabs, 1)

        self.print_button.setEnabled(self.can("assets.print"))
        self.refresh()

    def _build_disposals(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        self.disposal_table = DataTable(DISPOSAL_COLUMNS, formatter=self.formatter)
        card = CardPanel("واگذاری‌های ثبت‌شده")
        self.disposal_summary = QLabel("")
        self.disposal_summary.setObjectName("HintText")
        card.add_header_widget(self.disposal_summary)
        card.add(self.disposal_table, 1)
        layout.addWidget(card, 1)
        return page

    def _build_maintenance(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        actions = QHBoxLayout()
        from PySide6.QtWidgets import QPushButton

        self.new_maintenance = QPushButton("ثبت تعمیر/سرویس")
        self.new_maintenance.setProperty("variant", "primary")
        self.new_maintenance.setMinimumHeight(32)
        self.new_maintenance.clicked.connect(self._add_maintenance)
        actions.addWidget(self.new_maintenance)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.maintenance_table = DataTable(MAINTENANCE_COLUMNS, formatter=self.formatter)
        card = CardPanel("تعمیر و نگهداری")
        card.add(self.maintenance_table, 1)
        layout.addWidget(card, 1)
        return page

    def refresh(self) -> None:
        try:
            self.disposals = self.services.assets.list_disposals(self.ctx)
            self.maintenance = self.services.assets.list_maintenance(self.ctx)
        except AppError as error:
            show_error(self, "فروش و کنارگذاری", error)
            return
        self.set_rows(self.disposal_table, self.disposals)
        self.set_rows(self.maintenance_table, self.maintenance)
        gain = sum((row.gain_loss for row in self.disposals), Decimal("0"))
        cost = sum((row.cost for row in self.maintenance), Decimal("0"))
        self.disposal_summary.setText(
            f"{len(self.disposals):,} واگذاری — سود/زیان جمع {self.formatter.amount(gain)} — "
            f"{len(self.maintenance):,} تعمیر با هزینهٔ "
            f"{self.formatter.amount(cost)}")

    def _add_maintenance(self) -> None:
        from pars_erp.ui.pages.assets.assets_page import MaintenanceDialog

        asset_id = None
        try:
            choices = self.services.assets.asset_choices(self.ctx)
        except AppError:
            choices = []
        if not choices:
            show_info(self, "تعمیر", "هیچ دارایی ثبت‌شده‌ای وجود ندارد.")
            return
        from PySide6.QtWidgets import QInputDialog

        labels = [label for _id, label in choices]
        label, accepted = QInputDialog.getItem(self, "ثبت تعمیر", "دارایی:", labels, 0, False)
        if not accepted:
            return
        asset_id = next(identifier for identifier, text in choices if text == label)
        try:
            asset = self.services.assets.get_asset(self.ctx, int(asset_id))
        except AppError as error:
            show_error(self, "تعمیر", error)
            return
        dialog = MaintenanceDialog(self.services, self.ctx, asset, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify("تعمیر و نگهداری ثبت شد.")

    def _print(self) -> None:
        from pars_erp.services.report_render_service import ReportRenderer
        from pars_erp.ui.dialogs.report_preview import ReportPreviewDialog
        from pars_erp.ui.pages.report_view import render_table

        try:
            if self.tabs.currentIndex() == 0:
                table = self.services.asset_reports.disposals(self.ctx)
            else:
                table = self.services.asset_reports.maintenance(self.ctx)
        except AppError as error:
            show_error(self, "چاپ", error)
            return
        snapshot = self.services.settings.snapshot()
        renderer = ReportRenderer(app_name=snapshot.app_name,
                                  persian_digits=snapshot.persian_digits)
        ReportPreviewDialog(render_table(self.services, table), renderer,
                            parent=self).exec()
