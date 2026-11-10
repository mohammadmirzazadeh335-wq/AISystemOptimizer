"""Create / edit a role and its permission matrix."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.security.permissions import SecurityContext
from pars_erp.services.context import AppServices
from pars_erp.services.role_service import RoleRow, RoleService
from pars_erp.ui.widgets.common import FieldRow


class RoleDialog(QDialog):
    def __init__(self, parent: QWidget | None, services: AppServices, ctx: SecurityContext, *,
                 role: RoleRow | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.role = role
        self.is_edit = role is not None
        self.setWindowTitle("ویرایش نقش" if self.is_edit else "نقش جدید")
        self.setModal(True)
        self.setMinimumWidth(620)
        self.setMinimumHeight(600)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)

        heading = QLabel("ویرایش نقش" if self.is_edit else "ایجاد نقش جدید")
        heading.setObjectName("SectionTitle")
        outer.addWidget(heading)

        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("مثال: anbardar")
        self.title_input = QLineEdit()
        self.description_input = QLineEdit()

        grid = QGridLayout()
        grid.setSpacing(10)
        self.code_field = FieldRow("کد نقش", self.code_input, required=not self.is_edit,
                                   hint="حروف کوچک انگلیسی و زیرخط، شروع با حرف (مثال: warehouse_manager)")
        self.title_field = FieldRow("عنوان نقش", self.title_input, required=True)
        grid.addWidget(self.code_field, 0, 0)
        grid.addWidget(self.title_field, 0, 1)
        outer.addLayout(grid)
        self.description_field = FieldRow("توضیحات", self.description_input)
        outer.addWidget(self.description_field)

        permissions_label = QLabel("مجوزها")
        permissions_label.setObjectName("FieldLabel")
        outer.addWidget(permissions_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        groups_layout = QVBoxLayout(container)
        groups_layout.setContentsMargins(2, 2, 2, 2)
        groups_layout.setSpacing(8)

        selected = set(role.permission_codes) if self.is_edit else set()
        locked = bool(role and role.code == "admin")
        self._checks: dict[str, QCheckBox] = {}
        for group in RoleService.permission_groups():
            box = QGroupBox(group.title_fa)
            box_layout = QGridLayout(box)
            box_layout.setContentsMargins(12, 10, 12, 10)
            box_layout.setSpacing(6)
            for index, (code, title, _action) in enumerate(group.permissions):
                check = QCheckBox(title)
                check.setChecked(code in selected or locked)
                check.setEnabled(not locked)
                check.setToolTip(code)
                self._checks[code] = check
                box_layout.addWidget(check, index // 2, index % 2)
            groups_layout.addWidget(box)
        groups_layout.addStretch(1)
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

        if locked:
            note = QLabel("نقش «مدیر سیستم» همیشه تمام مجوزها را دارد و قابل تغییر نیست.")
            note.setObjectName("HintText")
            note.setWordWrap(True)
            outer.addWidget(note)

        self.error_label = QLabel("")
        self.error_label.setObjectName("ErrorText")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        outer.addWidget(self.error_label)

        buttons = QDialogButtonBox()
        save = self.save_button = buttons.addButton("ذخیره", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("variant", "primary")
        cancel = buttons.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        cancel.setProperty("variant", "ghost")
        buttons.accepted.connect(self._submit)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        select_all = QCheckBox("انتخاب همه مجوزها")
        select_all.setEnabled(not locked)
        select_all.toggled.connect(self._toggle_all)
        outer.insertWidget(4, select_all)

        if self.is_edit:
            self.code_input.setText(role.code)
            self.code_input.setEnabled(False)
            self.title_input.setText(role.title_fa)
            self.description_input.setText(role.description or "")
            if locked:
                self.save_button.setEnabled(False)

    def selected_permissions(self) -> tuple[str, ...]:
        return tuple(code for code, check in self._checks.items() if check.isChecked())

    def _toggle_all(self, checked: bool) -> None:
        for check in self._checks.values():
            if check.isEnabled():
                check.setChecked(checked)

    def _submit(self) -> None:
        self.error_label.setVisible(False)
        self.code_field.set_error(None)
        self.title_field.set_error(None)
        self.description_field.set_error(None)
        try:
            if self.is_edit:
                self.services.roles.update_role(
                    self.ctx, self.role.id, title_fa=self.title_input.text(),
                    description=self.description_input.text(),
                    permissions=self.selected_permissions())
            else:
                self.services.roles.create_role(
                    self.ctx, code=self.code_input.text(), title_fa=self.title_input.text(),
                    description=self.description_input.text(),
                    permissions=self.selected_permissions())
        except AppError as exc:
            field = getattr(exc, "field", None)
            if field == "code":
                self.code_field.set_error(str(exc))
            elif field == "title_fa":
                self.title_field.set_error(str(exc))
            elif field == "description":
                self.description_field.set_error(str(exc))
            else:
                self.error_label.setText(str(exc))
                self.error_label.setVisible(True)
            return
        self.accept()
