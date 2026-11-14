"""استهلاک — preview, calculate, approve, post and skip a monthly run."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from pars_erp.assets import constants as A
from pars_erp.core.errors import AppError
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import form_row
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.commerce.widgets import confirm
from pars_erp.ui.pages.hr.list_dialog import show_rows
from pars_erp.ui.pages.hr.widgets import YearMonthPicker, hint_label
from pars_erp.ui.table_specs import (
    DEPRECIATION_LINE_COLUMNS,
    DEPRECIATION_RUN_COLUMNS,
    TEXT,
    ColumnSpec,
)
from pars_erp.ui.widgets.table import DataTable

SKIPPED_COLUMNS = (
    ColumnSpec("c0", "کد دارایی", TEXT, 140, "center"),
    ColumnSpec("c1", "دلیل استهلاک‌نشدن", TEXT, None),
)


class ReadingsDialog(QDialog):
    """Units produced in the period, for assets depreciated by usage."""

    def __init__(self, services, ctx, year: int, month: int,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.readings: dict[int, Decimal] = {}
        self.setWindowTitle(f"قرائت کارکرد {year}/{month:02d}")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setLayoutDirection(self.layoutDirection())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)
        heading = QLabel("کارکرد دوره برای دارایی‌های روش «کارکردی»")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        layout.addWidget(hint_label(
            "اگر کارکرد یک دارایی ثبت نشود، آن دارایی در این دوره مستهلک نمی‌شود و در "
            "گزارش «استهلاک‌نشده‌ها» می‌آید."))
        try:
            assets = [row for row in services.assets.list_assets(ctx)
                      if row.method == A.METHOD_UNITS]
        except AppError:
            assets = []
        self.edits: dict[int, QLineEdit] = {}
        for asset in assets:
            edit = QLineEdit()
            edit.setPlaceholderText("۰")
            self.edits[asset.id] = edit
            layout.addWidget(form_row(f"{asset.code} — {asset.title_fa}", edit))
        if not assets:
            layout.addWidget(QLabel("دارایی با روش کارکردی وجود ندارد."))
        buttons = QDialogButtonBox()
        ok = buttons.addButton("ثبت", QDialogButtonBox.ButtonRole.AcceptRole)
        ok.setProperty("variant", "primary")
        buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        for asset_id, edit in self.edits.items():
            text = edit.text().strip()
            if not text:
                continue
            try:
                self.readings[asset_id] = Decimal(text)
            except InvalidOperation:
                self.readings[asset_id] = Decimal(0)
        self.accept()


class DepreciationPage(PageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.runs = []
        self.lines = []
        self.skipped: tuple[tuple[str, str], ...] = ()
        self.readings: dict[int, Decimal] = {}

        self.header = PageHeader(
            "استهلاک دارایی‌ها",
            "پیش‌نمایش، محاسبهٔ ماهانه، تأیید، ثبت سند و دورهٔ بدون استهلاک")
        self.root.addWidget(self.header)

        bar = CardPanel("دورهٔ استهلاک")
        row = QHBoxLayout()
        self.period_picker = YearMonthPicker()
        row.addWidget(form_row("دوره", self.period_picker), 2)
        self.readings_button = self._button("قرائت کارکرد", self._readings, "secondary")
        self.preview_button = self._button("پیش‌نمایش", self._preview, "secondary")
        self.calculate_button = self._button("محاسبه و ایجاد دوره", self._calculate)
        row.addWidget(self.readings_button)
        row.addWidget(self.preview_button)
        row.addWidget(self.calculate_button)
        bar.add_layout(row)
        self.root.addWidget(bar)

        action_row = QHBoxLayout()
        self.approve_button = self._button("تأیید دوره", self._approve, "secondary")
        self.post_button = self._button("ثبت سند استهلاک", self._post)
        self.skip_button = self._button("دورهٔ بدون استهلاک", self._skip, "secondary")
        self.lines_button = self._button("خطوط دوره", self._show_lines, "secondary")
        self.skipped_button = self._button("استهلاک‌نشده‌ها", self._show_skipped, "secondary")
        for button in (self.approve_button, self.post_button, self.skip_button,
                       self.lines_button, self.skipped_button):
            action_row.addWidget(button)
        action_row.addStretch(1)
        self.root.addLayout(action_row)

        self.table = DataTable(DEPRECIATION_RUN_COLUMNS, formatter=formatter)
        card = CardPanel("دوره‌های استهلاک")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        card.add_header_widget(self.summary)
        card.add(self.table, 1)
        self.root.addWidget(card, 1)

        can_calc = self.can("assets.depreciate")
        self.preview_button.setEnabled(can_calc)
        self.readings_button.setEnabled(can_calc)
        self.calculate_button.setEnabled(can_calc)
        self.skip_button.setEnabled(can_calc)
        self.approve_button.setEnabled(can_calc)
        self.post_button.setEnabled(self.can("assets.post_depreciation"))
        self.lines_button.setEnabled(self.can("assets.view"))
        self.skipped_button.setEnabled(can_calc)
        self.refresh()

    @staticmethod
    def _button(text: str, slot, variant: str = "primary"):
        from PySide6.QtWidgets import QPushButton

        button = QPushButton(text)
        button.setProperty("variant", variant)
        button.setMinimumHeight(32)
        button.clicked.connect(slot)
        return button

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        try:
            self.runs = self.services.depreciation.list_runs(self.ctx)
        except AppError as error:
            show_error(self, "استهلاک", error)
            return
        self.set_rows(self.table, self.runs)
        posted = sum(1 for run in self.runs if run.status == A.DEP_RUN_POSTED)
        total = sum((run.total_amount for run in self.runs), Decimal("0"))
        self.summary.setText(f"{len(self.runs):,} دوره — {posted:,} ثبت‌شده — جمع "
                             f"{self.formatter.amount(total)}")

    def _selected_run(self):
        rows = self.table.model.rows()
        index = self.table.selected_row_index()
        if index is None or index >= len(rows):
            return None
        return rows[index]

    # ----------------------------------------------------------------- actions
    def _readings(self) -> None:
        year, month = self.period_picker.value()
        dialog = ReadingsDialog(self.services, self.ctx, year, month, self)
        if dialog.exec():
            self.readings = dialog.readings
            self.notify(f"کارکرد {len(self.readings):,} دارایی ثبت شد.")

    def _preview(self) -> None:
        year, month = self.period_picker.value()
        try:
            result = self.services.depreciation.preview(self.ctx, year, month,
                                                        unit_readings=self.readings)
        except AppError as error:
            show_error(self, "پیش‌نمایش استهلاک", error)
            return
        self.lines = list(result.lines)
        self.skipped = result.skipped
        show_rows(self, f"پیش‌نمایش استهلاک {year}/{month:02d}",
                  DEPRECIATION_LINE_COLUMNS, self.lines, formatter=self.formatter,
                  subtitle=f"{len(self.lines):,} دارایی — جمع "
                           f"{self.formatter.amount(result.total_amount)} — "
                           f"{len(result.skipped):,} استهلاک‌نشده (فقط پیش‌نمایش، ثبت نشد)")

    def _calculate(self) -> None:
        year, month = self.period_picker.value()
        if not confirm(self, "محاسبهٔ استهلاک",
                       f"دورهٔ استهلاک {year}/{month:02d} ایجاد و محاسبه شود؟"):
            return
        try:
            result = self.services.depreciation.calculate(
                self.ctx, year, month, unit_readings=self.readings)
        except AppError as error:
            show_error(self, "محاسبهٔ استهلاک", error)
            return
        self.refresh()
        self.notify(f"دوره با {len(result.lines):,} ردیف محاسبه شد؛ جمع "
                    f"{self.formatter.amount(result.total_amount)}")

    def _approve(self) -> None:
        run = self._selected_run()
        if run is None:
            show_info(self, "تأیید", "ابتدا یک دوره را انتخاب کنید.")
            return
        try:
            self.services.depreciation.approve(self.ctx, run.id)
        except AppError as error:
            show_error(self, "تأیید دوره", error)
            return
        self.refresh()
        self.notify(f"دورهٔ {run.number} تأیید شد.")

    def _post(self) -> None:
        run = self._selected_run()
        if run is None:
            show_info(self, "ثبت سند", "ابتدا یک دوره را انتخاب کنید.")
            return
        if not confirm(self, "ثبت سند استهلاک",
                       "سند استهلاک به‌صورت قطعی ثبت شود؟ پس از ثبت قابل تغییر نیست.",
                       danger=True):
            return
        try:
            posted = self.services.depreciation.post(self.ctx, run.id)
        except AppError as error:
            show_error(self, "ثبت سند استهلاک", error)
            return
        self.refresh()
        self.notify(f"سند دورهٔ {posted.number} ثبت شد.")

    def _skip(self) -> None:
        year, month = self.period_picker.value()
        if not confirm(self, "دورهٔ بدون استهلاک",
                       f"برای {year}/{month:02d} دورهٔ «بدون استهلاک» ثبت شود؟"):
            return
        try:
            self.services.depreciation.skip_run(self.ctx, year, month,
                                                note="دورهٔ بدون استهلاک (ثبت کاربر)")
        except AppError as error:
            show_error(self, "دورهٔ بدون استهلاک", error)
            return
        self.refresh()
        self.notify("دورهٔ بدون استهلاک ثبت شد.")

    def _show_lines(self) -> None:
        run = self._selected_run()
        if run is None:
            show_info(self, "خطوط دوره", "ابتدا یک دوره را انتخاب کنید.")
            return
        try:
            lines = self.services.depreciation.run_lines(self.ctx, run.id)
        except AppError as error:
            show_error(self, "خطوط دوره", error)
            return
        show_rows(self, f"خطوط دورهٔ {run.number}", DEPRECIATION_LINE_COLUMNS, lines,
                  formatter=self.formatter, subtitle="ارزش آغاز، استهلاک ماه و ارزش دفتری")

    def _show_skipped(self) -> None:
        if not self.skipped:
            show_info(self, "استهلاک‌نشده‌ها",
                      "ابتدا «پیش‌نمایش» را اجرا کنید تا فهرست استهلاک‌نشده‌ها ساخته شود.")
            return
        rows = [{"c0": code, "c1": reason} for code, reason in self.skipped]
        show_rows(self, "دارایی‌های استهلاک‌نشده", SKIPPED_COLUMNS, rows,
                  formatter=self.formatter,
                  subtitle="این دارایی‌ها در دورهٔ جاری استهلاک نشدند؛ دلیل هرکدام آمده است.")
