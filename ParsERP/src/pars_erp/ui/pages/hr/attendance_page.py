"""حضور و غیاب — شیفت‌ها، ثبت روزانه، ورود از فایل و اصلاح با دلیل."""

from __future__ import annotations

import csv
import datetime as _dt
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTabWidget,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.core.jalali import JalaliDate
from pars_erp.hr import constants as H
from pars_erp.services.attendance_service import AttendanceInput, ShiftInput
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit, form_row
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.commerce.widgets import PickCombo
from pars_erp.ui.pages.form_dialog import FormDialog, TimeEdit, fill_combo
from pars_erp.ui.pages.hr.widgets import EmployeePicker
from pars_erp.ui.table_specs import ATTENDANCE_COLUMNS, SHIFT_COLUMNS
from pars_erp.ui.widgets.table import DataTable


def _month_bounds(kind: str = "current") -> tuple[_dt.date, _dt.date]:
    today = JalaliDate.today()
    if kind == "current":
        start = JalaliDate(today.year, today.month, 1).to_gregorian()
    else:  # pragma: no cover - kept for future ranges
        start = JalaliDate(today.year, 1, 1).to_gregorian()
    return start, today.to_gregorian()


# --------------------------------------------------------------------- dialogs
class ShiftDialog(FormDialog):
    title_fa = "شیفت کاری"
    width = 620

    def __init__(self, services, ctx, *, shift=None, parent: QWidget | None = None) -> None:
        self.shift = shift
        super().__init__(services, ctx, parent=parent,
                         subtitle="ساعت کاری، استراحت، مهلت تأخیر و روزهای کاری شیفت.")

    def _build(self) -> None:
        shift = self.shift
        self.code_edit = QLineEdit(shift.code if shift else "")
        self.code_edit.setPlaceholderText("خودکار")
        self.title_edit = QLineEdit(shift.title_fa if shift else "")
        self.add_pair(("کد شیفت", self.code_edit), ("عنوان *", self.title_edit),
                      right_required=True)
        self.kind_combo = fill_combo(
            QComboBox(), H.SHIFT_KINDS, current=shift.kind if shift else H.SHIFT_MORNING,
            placeholder="")
        self.is_night = QCheckBox("شیفت شب")
        self.is_night.setChecked(bool(shift.is_night) if shift else False)
        self.add_pair(("نوع شیفت", self.kind_combo), ("", self.is_night))

        self.start_edit = TimeEdit(shift.start_time if shift else _dt.time(8, 0))
        self.end_edit = TimeEdit(shift.end_time if shift else _dt.time(17, 0))
        self.add_pair(("ساعت شروع", self.start_edit), ("ساعت پایان", self.end_edit))

        self.break_spin = QSpinBox()
        self.break_spin.setRange(0, 240)
        self.break_spin.setValue(int(shift.break_minutes) if shift else 60)
        self.grace_spin = QSpinBox()
        self.grace_spin.setRange(0, 120)
        self.grace_spin.setValue(int(shift.grace_minutes) if shift else 10)
        self.add_pair(("استراحت (دقیقه)", self.break_spin), ("مهلت تأخیر (دقیقه)", self.grace_spin))

        days_label = QLabel("روزهای کاری")
        days_label.setObjectName("FieldLabel")
        self.add_widget(days_label)
        self.day_checks: list[QCheckBox] = []
        row = QHBoxLayout()
        selected = []
        if shift is not None:
            selected = [int(part) for part in str(shift.working_days or "").split(",")
                        if part.strip().isdigit()]
        if not selected:
            selected = list(H.DEFAULT_WORKING_DAYS)
        for index, title in enumerate(H.WEEKDAY_TITLES_FA):
            box = QCheckBox(title)
            box.setChecked(index in selected)
            self.day_checks.append(box)
            row.addWidget(box)
        holder = QWidget()
        holder.setLayout(row)
        self.add_widget(holder)

        self.description_edit = QLineEdit()
        self.add_row("توضیحات", self.description_edit)
        self.active_check = QCheckBox("شیفت فعال است")
        self.active_check.setChecked(bool(shift.is_active) if shift else True)
        self.add_widget(self.active_check)

    def save(self):
        days = [str(index) for index, box in enumerate(self.day_checks) if box.isChecked()]
        data = ShiftInput(
            code=self.code_edit.text().strip(),
            title_fa=self.title_edit.text().strip(),
            kind=str(self.kind_combo.currentData()),
            start_time=self.start_edit.time_value(),
            end_time=self.end_edit.time_value(),
            break_minutes=self.break_spin.value(),
            grace_minutes=self.grace_spin.value(),
            working_days=",".join(days),
            is_night=self.is_night.isChecked(),
            is_active=self.active_check.isChecked(),
            description=self.description_edit.text().strip(),
        )
        if self.shift is None:
            return self.services.attendance.create_shift(self.ctx, data)
        return self.services.attendance.update_shift(self.ctx, self.shift.id, data)


class AssignShiftDialog(FormDialog):
    title_fa = "اختصاص شیفت"
    width = 520

    def __init__(self, services, ctx, *, shift=None, parent: QWidget | None = None) -> None:
        self.shift = shift
        super().__init__(services, ctx, parent=parent,
                         subtitle="بازهٔ اعتبار شیفت برای یک کارمند؛ بازهٔ قبلی حذف نمی‌شود.")

    def _build(self) -> None:
        self.employee_picker = EmployeePicker(active_only=False)
        self.employee_picker.attach(self.services, self.ctx)
        self.add_row("کارمند *", self.employee_picker, required=True)
        self.shift_combo = PickCombo()
        try:
            self.shift_combo.load(self.services.attendance.shift_choices(self.ctx))
        except AppError:
            self.shift_combo.load([])
        if self.shift is not None:
            self.shift_combo.set_value(self.shift.id)
        self.add_row("شیفت *", self.shift_combo, required=True)
        self.from_edit = JalaliDateEdit(_dt.date.today())
        self.to_edit = JalaliDateEdit(None, allow_empty=True)
        self.add_pair(("از تاریخ *", self.from_edit), ("تا تاریخ", self.to_edit),
                      left_required=True)
        self.note_edit = QLineEdit()
        self.add_row("یادداشت", self.note_edit)

    def save(self):
        shift_id = self.shift_combo.value()
        from pars_erp.core.errors import ValidationError

        if shift_id is None:
            raise ValidationError("شیفت را انتخاب کنید.", field="shift_id")
        self.services.attendance.assign_shift(
            self.ctx, employee_id=int(self.employee_picker.require()),
            shift_id=int(shift_id), from_date=self.from_edit.date(),
            to_date=self.to_edit.date(), note=self.note_edit.text().strip())
        return True


class AttendanceDialog(FormDialog):
    title_fa = "ثبت حضور"
    width = 560

    def __init__(self, services, ctx, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, parent=parent,
                         subtitle="برای رکورد موجود از «اصلاح حضور» استفاده کنید.")

    def _build(self) -> None:
        self.employee_picker = EmployeePicker(active_only=False)
        self.employee_picker.attach(self.services, self.ctx)
        self.date_edit = JalaliDateEdit(_dt.date.today())
        self.add_pair(("کارمند *", self.employee_picker), ("تاریخ *", self.date_edit),
                      left_required=True, right_required=True)
        self.shift_combo = PickCombo()
        try:
            self.shift_combo.load(self.services.attendance.shift_choices(self.ctx))
        except AppError:
            self.shift_combo.load([])
        self.status_combo = QComboBox()
        self.status_combo.addItem("خودکار (بر اساس ساعت)", None)
        for code, title in H.ATT_STATUSES:
            self.status_combo.addItem(title, code)
        self.add_pair(("شیفت", self.shift_combo), ("وضعیت", self.status_combo))
        self.in_edit = TimeEdit(None, optional=True)
        self.out_edit = TimeEdit(None, optional=True)
        self.add_pair(("ساعت ورود", self.in_edit), ("ساعت خروج", self.out_edit))
        self.note_edit = QLineEdit()
        self.add_row("یادداشت", self.note_edit)

    def save(self):
        data = AttendanceInput(
            employee_id=int(self.employee_picker.require()),
            work_date=self.date_edit.date(),
            check_in=self.in_edit.time_value(),
            check_out=self.out_edit.time_value(),
            shift_id=self.shift_combo.value(),
            status=self.status_combo.currentData(),
            note=self.note_edit.text().strip(),
        )
        return self.services.attendance.record(self.ctx, data)


class AmendAttendanceDialog(FormDialog):
    title_fa = "اصلاح حضور"
    width = 560

    def __init__(self, services, ctx, row, parent: QWidget | None = None) -> None:
        self.row = row
        super().__init__(services, ctx, parent=parent,
                         subtitle=f"{row.employee_name} — {row.work_date}; اصلاح نیازمند "
                                  "مجوز و دلیل است.")

    def _build(self) -> None:
        self.in_edit = TimeEdit(self.row.check_in, optional=True)
        self.out_edit = TimeEdit(self.row.check_out, optional=True)
        self.add_pair(("ساعت ورود", self.in_edit), ("ساعت خروج", self.out_edit))
        self.status_combo = fill_combo(QComboBox(), H.ATT_STATUSES,
                                       current=self.row.status, placeholder="")
        self.add_row("وضعیت", self.status_combo)
        self.note_edit = QLineEdit()
        self.add_row("دلیل اصلاح *", self.note_edit, required=True)

    def save(self):
        return self.services.attendance.amend(
            self.ctx, self.row.id, check_in=self.in_edit.time_value(),
            check_out=self.out_edit.time_value(),
            status=str(self.status_combo.currentData()),
            note=self.note_edit.text().strip())


# ----------------------------------------------------------------------- page
class AttendancePage(PageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.rows = []
        self.shift_rows = []
        self.header = PageHeader(
            "حضور و غیاب",
            "ثبت روزانه، اصلاح با دلیل، ورود از فایل، شیفت‌ها و تخصیص شیفت")
        self.record_button = self.header.add_action("ثبت حضور", slot=self._new_record)
        self.amend_button = self.header.add_action("اصلاح", variant="secondary",
                                                   slot=self._amend)
        self.import_button = self.header.add_action("ورود از فایل", variant="secondary",
                                                    slot=self._import)
        self.root.addWidget(self.header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_records_tab(), "رکوردهای حضور")
        self.tabs.addTab(self._build_shifts_tab(), "شیفت‌ها")
        self.root.addWidget(self.tabs, 1)

        self.record_button.setEnabled(self.can("hr.attendance.record"))
        self.amend_button.setEnabled(self.can("hr.attendance.amend"))
        self.import_button.setEnabled(self.can("hr.attendance.record"))
        self.shift_new_button.setEnabled(self.can("hr.org.edit"))
        self.shift_edit_button.setEnabled(self.can("hr.org.edit"))
        self.assign_button.setEnabled(self.can("hr.org.edit"))
        self.refresh()

    # ------------------------------------------------------------------- tabs
    def _build_records_tab(self) -> QWidget:
        page = QWidget()
        from PySide6.QtWidgets import QVBoxLayout

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        bar = CardPanel("بازه و فیلتر")
        row = QHBoxLayout()
        start, end = _month_bounds()
        self.from_edit = JalaliDateEdit(start)
        self.to_edit = JalaliDateEdit(end)
        self.from_edit.dateChanged.connect(lambda _value: self.refresh())
        self.to_edit.dateChanged.connect(lambda _value: self.refresh())
        row.addWidget(form_row("از تاریخ", self.from_edit), 1)
        row.addWidget(form_row("تا تاریخ", self.to_edit), 1)
        self.employee_combo = PickCombo()
        self.employee_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        row.addWidget(form_row("کارمند", self.employee_combo), 2)
        self.status_filter = QComboBox()
        self.status_filter.addItem("همهٔ وضعیت‌ها", None)
        for code, title in H.ATT_STATUSES:
            self.status_filter.addItem(title, code)
        self.status_filter.currentIndexChanged.connect(lambda _index: self.refresh())
        row.addWidget(form_row("وضعیت", self.status_filter), 1)
        bar.add_layout(row)
        layout.addWidget(bar)

        self.table = DataTable(ATTENDANCE_COLUMNS, formatter=self.formatter)
        card = CardPanel("رکوردهای حضور")
        self.summary = QLabel("")
        self.summary.setObjectName("HintText")
        card.add_header_widget(self.summary)
        card.add(self.table, 1)
        layout.addWidget(card, 1)
        return page

    def _build_shifts_tab(self) -> QWidget:
        page = QWidget()
        from PySide6.QtWidgets import QVBoxLayout

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        actions = QHBoxLayout()
        self.shift_new_button = self._button("شیفت جدید", self._new_shift)
        self.shift_edit_button = self._button("ویرایش شیفت", self._edit_shift, "secondary")
        self.assign_button = self._button("اختصاص شیفت", self._assign_shift, "secondary")
        actions.addWidget(self.shift_new_button)
        actions.addWidget(self.shift_edit_button)
        actions.addWidget(self.assign_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.shift_table = DataTable(SHIFT_COLUMNS, formatter=self.formatter)
        card = CardPanel("شیفت‌های تعریف‌شده")
        card.add(self.shift_table, 1)
        layout.addWidget(card, 1)
        return page

    @staticmethod
    def _button(text: str, slot, variant: str = "primary"):
        from PySide6.QtWidgets import QPushButton

        button = QPushButton(text)
        button.setProperty("variant", variant)
        button.setMinimumHeight(32)
        button.clicked.connect(slot)
        return button

    # ------------------------------------------------------------------- data
    def refresh(self) -> None:
        try:
            self.employee_combo.load(self.services.hr.employee_choices(self.ctx,
                                                                      active_only=False))
        except AppError:
            self.employee_combo.load([])
        try:
            self.rows = self.services.attendance.list_attendance(
                self.ctx, employee_id=self.employee_combo.value(),
                date_from=self.from_edit.date(), date_to=self.to_edit.date(),
                status=self.status_filter.currentData())
            self.shift_rows = self.services.attendance.list_shifts(self.ctx)
        except AppError as error:
            show_error(self, "حضور و غیاب", error)
            return
        self.set_rows(self.table, self.rows)
        self.set_rows(self.shift_table, self.shift_rows)
        worked = sum(row.worked_minutes for row in self.rows)
        late = sum(1 for row in self.rows if row.late_minutes)
        overtime = sum(row.overtime_minutes for row in self.rows)
        self.summary.setText(
            f"{len(self.rows):,} رکورد — {late:,} تأخیر — "
            f"{self.formatter.number(worked // 60)} ساعت کارکرد — "
            f"{self.formatter.number(overtime // 60)} ساعت اضافه‌کار")

    def _selected(self):
        index = self.table.selected_row_index()
        if index is None or index >= len(self.rows):
            return None
        return self.rows[index]

    def _selected_shift(self):
        index = self.shift_table.selected_row_index()
        if index is None or index >= len(self.shift_rows):
            return None
        return self.shift_rows[index]

    # ---------------------------------------------------------------- actions
    def _new_record(self) -> None:
        dialog = AttendanceDialog(self.services, self.ctx, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify("حضور ثبت شد.")

    def _amend(self) -> None:
        row = self._selected()
        if row is None:
            show_info(self, "اصلاح حضور", "ابتدا یک رکورد را انتخاب کنید.")
            return
        dialog = AmendAttendanceDialog(self.services, self.ctx, row, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify("رکورد حضور اصلاح شد.")

    def _import(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "انتخاب فایل حضور و غیاب", "", "CSV (*.csv);;همهٔ فایل‌ها (*)")
        if not path:
            return
        try:
            with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except OSError as error:
            show_info(self, "ورود از فایل", f"فایل خوانده نشد: {error}", tone="warning")
            return
        if not rows:
            show_info(self, "ورود از فایل", "فایل هیچ ردیفی ندارد.", tone="warning")
            return
        try:
            result = self.services.attendance.import_rows(self.ctx, rows)
        except AppError as error:
            show_error(self, "ورود از فایل", error)
            return
        details = ""
        if result.errors:
            details = "\n".join(result.errors[:20])
        self.refresh()
        show_info(self, "ورود از فایل",
                  f"{result.created:,} رکورد جدید، {result.updated:,} رکورد به‌روزرسانی "
                  f"و {len(result.errors):,} خطا.",
                  details or None,
                  tone="success" if not result.errors else "warning")

    def _new_shift(self) -> None:
        dialog = ShiftDialog(self.services, self.ctx, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"شیفت «{dialog.saved.title_fa}» ایجاد شد.")

    def _edit_shift(self) -> None:
        shift = self._selected_shift()
        if shift is None:
            show_info(self, "ویرایش شیفت", "ابتدا یک شیفت را انتخاب کنید.")
            return
        dialog = ShiftDialog(self.services, self.ctx, shift=shift, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify("شیفت به‌روزرسانی شد.")

    def _assign_shift(self) -> None:
        shift = self._selected_shift()
        dialog = AssignShiftDialog(self.services, self.ctx, shift=shift, parent=self)
        if dialog.exec():
            self.notify("شیفت به کارمند اختصاص یافت.")
