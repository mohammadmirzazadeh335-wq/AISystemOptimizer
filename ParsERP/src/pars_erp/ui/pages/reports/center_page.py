"""The report centre: pick a report, filter it, page it, export it, save it.

Everything the screen shows comes from :class:`ReportEngineService`; the screen
itself does no arithmetic and no filtering, so what is printed and exported is
exactly what the grid shows (the engine hands back one table for all of them).
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from pars_erp.core.errors import AppError
from pars_erp.core.money import format_amount
from pars_erp.reporting.engine import (
    KIND_AMOUNT,
    KIND_NUMBER,
    ReportQuery,
    ReportResult,
)
from pars_erp.services.common import Page
from pars_erp.services.report_render_service import KIND_DATE, ReportRenderer
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.table_specs import AMOUNT, DATE, NUMBER, TEXT, ColumnSpec
from pars_erp.ui.widgets.common import SearchInput
from pars_erp.ui.widgets.pagination import PaginationBar
from pars_erp.ui.widgets.table import DataTable

_KIND_MAP = {KIND_AMOUNT: AMOUNT, KIND_NUMBER: NUMBER, KIND_DATE: DATE}


class ColumnChooserDialog(QDialog):
    """Choose which columns of a report are shown/exported."""

    def __init__(self, columns, selected: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("انتخاب ستون‌های گزارش")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(360, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("ستون‌هایی که می‌خواهید در گزارش ببینید:"))
        self.list = QListWidget()
        self._boxes: dict[str, QCheckBox] = {}
        for column in columns:
            item = QListWidgetItem()
            box = QCheckBox(column.title_fa)
            box.setChecked(column.key in selected or not selected)
            item.setData(Qt.ItemDataRole.UserRole, column.key)
            self.list.addItem(item)
            self.list.setItemWidget(item, box)
            self._boxes[column.key] = box
        layout.addWidget(self.list, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("اعمال")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("انصراف")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_keys(self) -> list[str]:
        return [key for key, box in self._boxes.items() if box.isChecked()]


class ReportCenterPage(PageBase):
    """Run any permitted report, page through it and export it."""

    drill_requested = Signal(str, str)

    def __init__(self, services, ctx, formatter, *, on_navigate=None, parent=None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self._on_navigate = on_navigate
        self._result: ReportResult | None = None
        self._definition_key: str | None = None
        self._column_keys: list[str] = []
        self._page = 1
        self._page_size = services.settings.snapshot().int("report_page_size") or 100

        self.header = PageHeader("مرکز گزارش‌ها",
                                 "همهٔ گزارش‌ها از اسناد واقعی پایگاه داده؛ یک جدول، همان چاپ و همان فایل")
        self.header.add_action("اجرا", slot=self.run_report)
        self.header.add_action("ستون‌ها", variant="ghost", slot=self.choose_columns)
        self.header.add_action("Excel", variant="ghost", slot=lambda: self.export("xlsx"))
        self.header.add_action("PDF", variant="ghost", slot=lambda: self.export("pdf"))
        self.header.add_action("CSV", variant="ghost", slot=lambda: self.export("csv"))
        self.header.add_action("چاپ", variant="ghost", slot=self.print_report)
        self.root.addWidget(self.header)

        # ------------------------------------------------------------ filters
        self.filters_card = CardPanel("گزارش و فیلترها", "گزارش‌های مجاز برای نقش شما")
        row = QHBoxLayout()
        self.section_combo = QComboBox()
        self.section_combo.currentIndexChanged.connect(self._fill_sources)
        self.source_combo = QComboBox()
        self.source_combo.currentIndexChanged.connect(self._source_changed)
        row.addWidget(QLabel("بخش:"))
        row.addWidget(self.section_combo, 1)
        row.addWidget(QLabel("گزارش:"))
        row.addWidget(self.source_combo, 2)
        self.filters_card.add_layout(row)

        dates = QHBoxLayout()
        today = _dt.date.today()
        self.date_from = JalaliDateEdit(today.replace(day=1), persian_digits=formatter.persian_digits)
        self.date_to = JalaliDateEdit(today, persian_digits=formatter.persian_digits)
        self.search = SearchInput("جست‌وجو در نتیجه…")
        self.search.textChanged.connect(lambda _text: self._run(page=1) if self._definition_key else None)
        dates.addWidget(QLabel("از تاریخ:"))
        dates.addWidget(self.date_from)
        dates.addWidget(QLabel("تا تاریخ:"))
        dates.addWidget(self.date_to)
        dates.addWidget(self.search, 1)
        self.filters_card.add_layout(dates)

        options = QHBoxLayout()
        self.sort_combo = QComboBox()
        self.sort_desc = QCheckBox("نزولی")
        self.sort_desc.stateChanged.connect(lambda _s: self._run(page=1) if self._definition_key else None)
        self.group_combo = QComboBox()
        self.group_combo.currentIndexChanged.connect(
            lambda _i: self._run(page=1) if self._definition_key else None)
        self.page_size_box = QSpinBox()
        self.page_size_box.setRange(10, 1000)
        self.page_size_box.setValue(self._page_size)
        self.page_size_box.valueChanged.connect(self._page_size_changed)
        options.addWidget(QLabel("مرتب‌سازی:"))
        options.addWidget(self.sort_combo, 2)
        options.addWidget(self.sort_desc)
        options.addWidget(QLabel("گروه‌بندی:"))
        options.addWidget(self.group_combo, 2)
        options.addWidget(QLabel("سطر در صفحه:"))
        options.addWidget(self.page_size_box)
        self.filters_card.add_layout(options)
        self.root.addWidget(self.filters_card)

        # -------------------------------------------------------------- table
        self.table_card = CardPanel("نتیجهٔ گزارش", "")
        self.table = DataTable([], formatter=formatter)
        self.table.rowActivated.connect(self._drill)
        self.table_card.add(self.table, 1)
        self.summary = QLabel("گزارشی اجرا نشده است.")
        self.summary.setWordWrap(True)
        self.table_card.add(self.summary)
        self.pagination = PaginationBar()
        self.pagination.pageChanged.connect(self._page_changed)
        self.table_card.add(self.pagination)
        self.root.addWidget(self.table_card, 1)

        # ------------------------------------------------------------- saved
        self.saved_card = CardPanel("گزارش‌های ذخیره‌شده", "گزارش خودتان را با همین تنظیمات ذخیره کنید")
        saved_row = QHBoxLayout()
        self.saved_combo = QComboBox()
        self.saved_combo.currentIndexChanged.connect(self._saved_selected)
        self.save_button = QPushButton("ذخیرهٔ گزارش")
        self.save_button.clicked.connect(self.save_current)
        self.delete_button = QPushButton("حذف")
        self.delete_button.setProperty("variant", "ghost")
        self.delete_button.clicked.connect(self.delete_saved)
        self.default_button = QPushButton("پیش‌فرض من")
        self.default_button.setProperty("variant", "ghost")
        self.default_button.clicked.connect(self.make_default)
        saved_row.addWidget(self.saved_combo, 1)
        saved_row.addWidget(self.save_button)
        saved_row.addWidget(self.default_button)
        saved_row.addWidget(self.delete_button)
        self.saved_card.add_layout(saved_row)
        self.root.addWidget(self.saved_card)

        self._fill_sections()
        self._apply_permissions()

    # ------------------------------------------------------------- population
    def refresh(self) -> None:
        self._fill_sections()
        self._fill_saved()

    def _apply_permissions(self) -> None:
        can_save = self.can("reports.center")
        self.save_button.setVisible(can_save)
        self.delete_button.setVisible(can_save)
        self.default_button.setVisible(can_save)

    def _fill_sections(self) -> None:
        current = self.section_combo.currentData()
        self.section_combo.blockSignals(True)
        self.section_combo.clear()
        try:
            for section, title, _definitions in self.services.report_engine.sections(self.ctx):
                self.section_combo.addItem(title, section)
        except AppError:
            pass
        index = self.section_combo.findData(current)
        self.section_combo.setCurrentIndex(index if index >= 0 else 0)
        self.section_combo.blockSignals(False)
        self._fill_sources()

    def _fill_sources(self) -> None:
        section = self.section_combo.currentData()
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        try:
            for definition in self.services.report_engine.definitions(self.ctx):
                if section and definition.section != section:
                    continue
                self.source_combo.addItem(definition.title_fa, definition.key)
        except AppError:
            pass
        self.source_combo.blockSignals(False)
        self._source_changed()

    def _source_changed(self) -> None:
        key = self.source_combo.currentData()
        if not key:
            return
        self._definition_key = key
        self._column_keys = []
        try:
            columns = self.services.report_engine.columns(self.ctx, key)
        except AppError as exc:
            show_error(self, "خطا", exc)
            return
        self.sort_combo.blockSignals(True)
        self.group_combo.blockSignals(True)
        self.sort_combo.clear()
        self.sort_combo.addItem("— بدون مرتب‌سازی —", None)
        self.group_combo.clear()
        self.group_combo.addItem("— بدون گروه‌بندی —", None)
        for column in columns:
            self.sort_combo.addItem(column.title_fa, column.key)
            self.group_combo.addItem(column.title_fa, column.key)
        self.sort_combo.blockSignals(False)
        self.group_combo.blockSignals(False)
        self.table.set_columns(self._specs(columns))
        self._run(page=1)

    # ---------------------------------------------------------------- running
    def _specs(self, columns) -> list[ColumnSpec]:
        specs = []
        for index, column in enumerate(columns):
            specs.append(ColumnSpec(
                key=column.key, title_fa=column.title_fa,
                kind=_KIND_MAP.get(column.kind, TEXT),
                getter=lambda row, i=index: row[i] if i < len(row) else None))
        return specs

    def _query(self, page: int) -> ReportQuery:
        return ReportQuery(
            date_from=self.date_from.date(), date_to=self.date_to.date(),
            search=self.search.text().strip(),
            sort_key=self.sort_combo.currentData() if hasattr(self, "sort_combo") else None,
            sort_desc=self.sort_desc.isChecked(),
            group_by=self.group_combo.currentData() if hasattr(self, "group_combo") else None,
            column_keys=tuple(self._column_keys) or None,
            page=page, page_size=self._page_size)

    def _run(self, *, page: int | None = None) -> None:
        if not self._definition_key:
            return
        self._page = page or self._page
        try:
            result = self.services.report_engine.run(
                self.ctx, definition_key=self._definition_key, query=self._query(self._page))
        except AppError as exc:
            show_error(self, "خطا", exc)
            return
        self._result = result
        self.table.set_columns(self._specs(result.columns))
        self.table.set_rows(list(result.rows))
        self.pagination.update_page(Page(items=result.rows, total=result.total_rows,
                                         page=result.page, page_size=result.page_size))
        self.summary.setText(self._summary_text(result))

    def _summary_text(self, result: ReportResult) -> str:
        parts = [result.title_fa, result.page_label_fa]
        sums = [value for value in result.aggregates
                if value.kind == "sum" and value.value not in (None, Decimal("0"))]
        for value in sums[:4]:
            parts.append(f"{value.title_fa} {value.column_title_fa}: "
                         f"{format_amount(value.value, 'IRR', persian_digits=False)}")
        if result.groups:
            parts.append(f"{len(result.groups)} گروه")
        if result.filter_labels:
            parts.append(" · ".join(result.filter_labels))
        return " — ".join(parts)

    def run_report(self) -> None:
        self._run(page=1)

    def _page_changed(self, page: int) -> None:
        self._run(page=page)

    def _page_size_changed(self, value: int) -> None:
        self._page_size = int(value)
        if self._definition_key:
            self._run(page=1)

    # --------------------------------------------------------------- actions
    def choose_columns(self) -> None:
        if not self._result:
            show_info(self, "زرین هرمز", "اول یک گزارش اجرا کنید.")
            return
        dialog = ColumnChooserDialog(self._result.columns, self._column_keys, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            keys = dialog.selected_keys()
            self._column_keys = keys if len(keys) < len(self._result.columns) else []
            self._run(page=1)

    def export(self, kind: str) -> None:
        if not self._result:
            show_info(self, "زرین هرمز", "اول یک گزارش اجرا کنید.")
            return
        suffix = {"xlsx": ".xlsx", "pdf": ".pdf", "csv": ".csv"}.get(kind, ".csv")
        default = str(self.services.paths.exports_dir /
                      f"{self._definition_key or 'report'}{suffix}")
        path, _ = QFileDialog.getSaveFileName(self, "ذخیرهٔ خروجی", default)
        if not path:
            return
        self.export_to(kind, path)

    def export_to(self, kind: str, path: str):
        """Write the current result to ``path`` (used by the tests as well)."""
        if not self._result:
            raise ValueError("no report has been run")
        engine = self.services.report_engine
        snapshot = self.services.settings.snapshot()
        if kind == "xlsx":
            outcome = engine.export_excel(self.ctx, self._result, __import__("pathlib").Path(path))
        elif kind == "pdf":
            outcome = engine.export_pdf(self.ctx, self._result, __import__("pathlib").Path(path),
                                        theme=snapshot.str("theme"))
        else:
            engine.export_csv(self.ctx, self._result, __import__("pathlib").Path(path),
                              delimiter=snapshot.str("report_csv_delimiter") or ",")
            outcome = None
        show_info(self, "زرین هرمز", outcome.message_fa if outcome else f"فایل «{path}» ذخیره شد.")
        return outcome

    def print_report(self) -> None:
        if not self._result or self._result.table is None:
            show_info(self, "زرین هرمز", "اول یک گزارش اجرا کنید.")
            return
        from pars_erp.ui.dialogs.report_preview import ReportPreviewDialog

        snapshot = self.services.settings.snapshot()
        renderer = ReportRenderer(app_name=snapshot.app_name,
                                  persian_digits=snapshot.bool("persian_digits"))
        dialog = ReportPreviewDialog(self._result.table, renderer, parent=self)
        dialog.exec()

    def _drill(self, row_index: int) -> None:
        if not self._result or self._definition_key is None or row_index < 0:
            return
        definition = self.services.report_engine.definition(self.ctx, self._definition_key)
        row = self._result.rows[row_index] if row_index < len(self._result.rows) else None
        if row is None:
            return
        target = self._result.target_for(definition, row)
        if target is None:
            show_info(self, "زرین هرمز", "این ردیف سند مبدأ قابل بازکردن ندارد.")
            return
        self.drill_requested.emit(target.page_key, target.search)

    # ------------------------------------------------------------------ saved
    def _fill_saved(self) -> None:
        self.saved_combo.blockSignals(True)
        self.saved_combo.clear()
        self.saved_combo.addItem("— گزارش ذخیره‌شده —", None)
        try:
            for row in self.services.report_engine.saved_reports(self.ctx):
                label = f"{row.name} ({row.scope_fa})"
                self.saved_combo.addItem(label, row.id)
        except AppError:
            pass
        self.saved_combo.blockSignals(False)

    def _saved_selected(self) -> None:
        saved_id = self.saved_combo.currentData()
        if not saved_id:
            return
        try:
            result = self.services.report_engine.run_saved(self.ctx, int(saved_id))
        except AppError as exc:
            show_error(self, "خطا", exc)
            return
        self._result = result
        self._definition_key = result.definition_key
        self.table.set_columns(self._specs(result.columns))
        self.table.set_rows(list(result.rows))
        self.pagination.update_page(Page(items=result.rows, total=result.total_rows,
                                         page=result.page, page_size=result.page_size))
        self.summary.setText(self._summary_text(result))

    def save_current(self) -> None:
        if not self._definition_key:
            show_info(self, "زرین هرمز", "اول یک گزارش اجرا کنید.")
            return
        from pars_erp.ui.pages.reports.designer_dialog import SaveReportDialog

        dialog = SaveReportDialog(self.services, self.ctx, self.formatter,
                                  definition_key=self._definition_key,
                                  query=self._query(1), parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.saved is not None:
            self._fill_saved()
            show_info(self, "زرین هرمز", f"گزارش «{dialog.saved.name}» ذخیره شد.")

    def delete_saved(self) -> None:
        saved_id = self.saved_combo.currentData()
        if not saved_id:
            show_info(self, "زرین هرمز", "گزارشی را از فهرست انتخاب کنید.")
            return
        try:
            self.services.report_engine.delete(self.ctx, int(saved_id))
        except AppError as exc:
            show_error(self, "خطا", exc)
            return
        self._fill_saved()

    def make_default(self) -> None:
        saved_id = self.saved_combo.currentData()
        if not saved_id:
            show_info(self, "زرین هرمز", "گزارشی را از فهرست انتخاب کنید.")
            return
        try:
            self.services.report_engine.set_default(self.ctx, int(saved_id), True)
        except AppError as exc:
            show_error(self, "خطا", exc)
            return
        self._fill_saved()
        show_info(self, "زرین هرمز", "این گزارش به‌عنوان گزارش پیش‌فرض شما ثبت شد.")
