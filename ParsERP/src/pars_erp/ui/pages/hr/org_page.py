"""ساختار سازمانی — درخت واحدها، مدیر هر واحد و انتقال کارکنان."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.hr import constants as H
from pars_erp.services.hr_service import OrgUnitInput
from pars_erp.ui.dialogs.common_dialogs import show_error, show_info
from pars_erp.ui.pages.accounting.widgets import JalaliDateEdit
from pars_erp.ui.pages.base import CardPanel, PageBase, PageHeader
from pars_erp.ui.pages.commerce.widgets import PickCombo
from pars_erp.ui.pages.form_dialog import FormDialog, fill_combo
from pars_erp.ui.pages.hr.widgets import EmployeePicker
from pars_erp.ui.widgets.common import InfoRow

_UNIT_ROLE = Qt.ItemDataRole.UserRole


class UnitDialog(FormDialog):
    title_fa = "واحد سازمانی"
    width = 560

    def __init__(self, services, ctx, *, unit=None, units=(), parent: QWidget | None = None) -> None:
        self.unit = unit
        self.units = units
        super().__init__(services, ctx, parent=parent,
                         subtitle="سلسله‌مراتب سازمانی با کد یکتا و مدیر مشخص.")

    def _build(self) -> None:
        raw = self.unit
        self.code_edit = QLineEdit(raw.code if raw else "")
        self.code_edit.setPlaceholderText("خودکار")
        self.title_edit = QLineEdit(raw.title_fa if raw else "")
        self.add_pair(("کد واحد", self.code_edit), ("عنوان *", self.title_edit),
                      right_required=True)
        self.kind_combo = fill_combo(QComboBox(), H.ORG_UNIT_KINDS,
                                     current=raw.kind if raw else H.UNIT_UNIT,
                                     placeholder="")
        self.parent_combo = PickCombo()
        choices = [(unit.id, f"{unit.code} — {unit.title_fa}") for unit in self.units
                   if raw is None or unit.id != raw.id]
        self.parent_combo.load(choices)
        if raw is not None:
            self.parent_combo.set_value(raw.parent_id)
        self.add_pair(("نوع واحد", self.kind_combo), ("واحد بالادست", self.parent_combo))

        self.manager_picker = EmployeePicker()
        self.manager_picker.attach(self.services, self.ctx)
        if raw is not None:
            self.manager_picker.set_value(raw.manager_employee_id)
        self.sort_spin = QSpinBox()
        self.sort_spin.setRange(0, 999)
        self.sort_spin.setValue(int(getattr(raw, "sort_order", 0) or 0) if raw else 0)
        self.add_pair(("مدیر واحد", self.manager_picker), ("ترتیب نمایش", self.sort_spin))

        self.description_edit = QLineEdit(raw.description if raw and raw.description else "")
        self.add_row("توضیحات", self.description_edit)
        self.active_check = QCheckBox("واحد فعال است")
        self.active_check.setChecked(bool(raw.is_active) if raw is not None else True)
        self.add_widget(self.active_check)

    def save(self):
        data = OrgUnitInput(
            code=self.code_edit.text().strip(),
            title_fa=self.title_edit.text().strip(),
            kind=str(self.kind_combo.currentData() or H.UNIT_UNIT),
            parent_id=self.parent_combo.value(),
            manager_employee_id=self.manager_picker.value(),
            cost_center_id=getattr(self.unit, "cost_center_id", None),
            sort_order=self.sort_spin.value(),
            is_active=self.active_check.isChecked(),
            description=self.description_edit.text().strip(),
        )
        if self.unit is None:
            return self.services.hr.create_unit(self.ctx, data)
        return self.services.hr.update_unit(self.ctx, self.unit.id, data)


class MoveEmployeesDialog(FormDialog):
    title_fa = "انتقال کارکنان"
    width = 560

    def __init__(self, services, ctx, *, unit, units, parent: QWidget | None = None) -> None:
        self.unit = unit
        self.units = units
        super().__init__(services, ctx, parent=parent,
                         subtitle=f"انتقال کارکنان از «{unit.title_fa}» به واحد دیگر؛ "
                                  "در سابقهٔ هر کارمند ثبت می‌شود.")

    def _build(self) -> None:
        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(200)
        try:
            employees = self.services.hr.list_employees(
                self.ctx, None)
        except AppError:
            employees = []
        self._employees = [row for row in employees if row.org_unit_id == self.unit.id]
        for row in self._employees:
            item = QListWidgetItem(f"{row.code} — {row.full_name}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(_UNIT_ROLE, row.id)
            self.list_widget.addItem(item)
        self.add_widget(self.list_widget)

        self.target_combo = PickCombo()
        self.target_combo.load([(unit.id, f"{unit.code} — {unit.title_fa}")
                                for unit in self.units if unit.id != self.unit.id])
        self.date_edit = JalaliDateEdit()
        self.add_pair(("واحد مقصد *", self.target_combo), ("تاریخ اجرا", self.date_edit))
        self.note_edit = QLineEdit()
        self.add_row("توضیح", self.note_edit)

    def selected_ids(self) -> tuple[int, ...]:
        ids = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                ids.append(int(item.data(_UNIT_ROLE)))
        return tuple(ids)

    def save(self):
        employee_ids = self.selected_ids()
        if not employee_ids:
            from pars_erp.core.errors import ValidationError

            raise ValidationError("حداقل یک کارمند را انتخاب کنید.", field="employees")
        target = self.target_combo.value()
        if target is None:
            from pars_erp.core.errors import ValidationError

            raise ValidationError("واحد مقصد را انتخاب کنید.", field="target")
        count = self.services.hr.move_employees(
            self.ctx, employee_ids=employee_ids, target_unit_id=int(target),
            effective_date=self.date_edit.date(), note=self.note_edit.text().strip())
        return count


class OrgStructurePage(PageBase):
    def __init__(self, services, ctx, formatter, parent: QWidget | None = None) -> None:
        super().__init__(services, ctx, formatter, parent)
        self.units = []
        self._nodes: dict[int, QTreeWidgetItem] = {}
        self.header = PageHeader(
            "ساختار سازمانی",
            "درخت شرکت/شعبه/واحد/بخش، مدیر هر واحد، تعداد کارکنان و انتقال سازمانی")
        self.new_button = self.header.add_action("واحد جدید", slot=self._new)
        self.edit_button = self.header.add_action("ویرایش واحد", variant="secondary",
                                                  slot=self._edit)
        self.move_button = self.header.add_action("انتقال کارکنان", variant="secondary",
                                                  slot=self._move)
        self.root.addWidget(self.header)

        body = QHBoxLayout()
        tree_card = CardPanel("درخت سازمان")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["واحد سازمانی", "نوع", "کارکنان"])
        self.tree.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnWidth(0, 260)
        self.tree.currentItemChanged.connect(lambda *_args: self._show_detail())
        tree_card.add(self.tree, 1)
        body.addWidget(tree_card, 3)

        detail_card = CardPanel("جزئیات واحد")
        detail_card.setMaximumWidth(340)
        detail_layout = QVBoxLayout()
        detail_layout.setSpacing(4)
        self.rows: dict[str, InfoRow] = {}
        for key, label in (("code", "کد"), ("title", "عنوان"), ("kind", "نوع"),
                           ("parent", "واحد بالادست"), ("manager", "مدیر"),
                           ("employees", "تعداد کارکنان"), ("status", "وضعیت")):
            info = InfoRow(label)
            self.rows[key] = info
            detail_layout.addWidget(info)
        detail_layout.addStretch(1)
        self.empty_detail = QLabel("یک واحد را انتخاب کنید.")
        self.empty_detail.setObjectName("HintText")
        detail_layout.addWidget(self.empty_detail)
        detail_card.add_layout(detail_layout)
        body.addWidget(detail_card, 1)
        self.root.addLayout(body, 1)

        self.new_button.setEnabled(self.can("hr.org.edit"))
        self.edit_button.setEnabled(self.can("hr.org.edit"))
        self.move_button.setEnabled(self.can("hr.org.edit") and
                                    self.can("hr.employees.edit"))
        self.refresh()

    # -------------------------------------------------------------------- data
    def refresh(self) -> None:
        try:
            self.units = self.services.hr.list_units(self.ctx, active_only=False)
            chart = self.services.hr.org_chart(self.ctx)
        except AppError as error:
            show_error(self, "ساختار سازمانی", error)
            return
        self.tree.clear()
        self._nodes.clear()
        for node in chart:
            self._add_node(None, node)
        self.tree.expandAll()
        self._show_detail()

    def _add_node(self, parent, node) -> None:
        unit = node.unit
        item = QTreeWidgetItem([unit.title_fa, unit.kind_fa, str(unit.employees_count)])
        item.setData(0, _UNIT_ROLE, unit.id)
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        self._nodes[unit.id] = item
        for child in node.children:
            self._add_node(item, child)

    def _selected_unit(self):
        item = self.tree.currentItem()
        if item is None:
            return None
        unit_id = item.data(0, _UNIT_ROLE)
        return next((unit for unit in self.units if unit.id == unit_id), None)

    def _show_detail(self) -> None:
        unit = self._selected_unit()
        self.empty_detail.setVisible(unit is None)
        for info in self.rows.values():
            info.setVisible(unit is not None)
        if unit is None:
            return
        self.rows["code"].set_value(unit.code)
        self.rows["title"].set_value(unit.title_fa)
        self.rows["kind"].set_value(unit.kind_fa)
        self.rows["parent"].set_value(unit.parent_title or "—")
        self.rows["manager"].set_value(unit.manager_name or "—")
        self.rows["employees"].set_value(self.formatter.number(unit.employees_count))
        self.rows["status"].set_value("فعال" if unit.is_active else "غیرفعال")

    # ----------------------------------------------------------------- actions
    def _new(self) -> None:
        dialog = UnitDialog(self.services, self.ctx, units=self.units, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"واحد «{dialog.saved.title_fa}» ایجاد شد.")

    def _edit(self) -> None:
        unit = self._selected_unit()
        if unit is None:
            show_info(self, "ویرایش واحد", "ابتدا یک واحد را انتخاب کنید.")
            return
        dialog = UnitDialog(self.services, self.ctx, unit=unit, units=self.units, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify(f"واحد «{dialog.saved.title_fa}» به‌روزرسانی شد.")

    def _move(self) -> None:
        unit = self._selected_unit()
        if unit is None:
            show_info(self, "انتقال کارکنان", "ابتدا یک واحد را انتخاب کنید.")
            return
        dialog = MoveEmployeesDialog(self.services, self.ctx, unit=unit,
                                     units=self.units, parent=self)
        if dialog.exec():
            self.refresh()
            self.notify("انتقال سازمانی ثبت شد.")
