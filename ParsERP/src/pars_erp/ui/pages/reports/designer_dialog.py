"""Save (or update) a report definition from the report centre."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from pars_erp.core.errors import AppError
from pars_erp.reporting.engine import ReportQuery
from pars_erp.services.report_engine_service import SaveReportInput


class SaveReportDialog(QDialog):
    """Ask for a name and the options to remember, then store the definition."""

    def __init__(self, services, ctx, formatter, *, definition_key: str,
                 query: ReportQuery, saved_id: int | None = None, parent=None) -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.definition_key = definition_key
        self.query = query
        self.saved_id = saved_id
        self.saved = None
        self.error_label = QLabel("")
        self.error_label.setObjectName("ErrorText")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)

        self.setWindowTitle("ذخیرهٔ گزارش")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.resize(420, 320)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("مثلاً فروش ماهانهٔ انبار مرکزی")
        self.description_edit = QLineEdit()
        self.page_size_box = QSpinBox()
        self.page_size_box.setRange(10, 1000)
        self.page_size_box.setValue(query.page_size)
        self.include_filters = QCheckBox("بازهٔ تاریخ و جست‌وجوی فعلی هم ذخیره شود")
        self.include_filters.setChecked(True)
        self.as_default = QCheckBox("این گزارش پیش‌فرض من باشد")
        form.addRow("نام گزارش", self.name_edit)
        form.addRow("توضیح", self.description_edit)
        form.addRow("سطر در صفحه", self.page_size_box)
        form.addRow("", self.include_filters)
        form.addRow("", self.as_default)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("ذخیره")
        buttons.button(QDialogButtonBox.StandardButton.Save).setProperty("variant", "primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("انصراف")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        use_filters = self.include_filters.isChecked()
        data = SaveReportInput(
            name=self.name_edit.text(),
            definition_key=self.definition_key,
            description=self.description_edit.text(),
            column_keys=tuple(self.query.column_keys or ()),
            date_from=self.query.date_from if use_filters else None,
            date_to=self.query.date_to if use_filters else None,
            sort_key=self.query.sort_key,
            sort_desc=self.query.sort_desc,
            group_by=self.query.group_by,
            page_size=self.page_size_box.value(),
            params=dict(self.query.params or {}),
            is_default=self.as_default.isChecked())
        try:
            if self.saved_id:
                self.saved = self.services.report_engine.update(self.ctx, self.saved_id, data)
            else:
                self.saved = self.services.report_engine.save(self.ctx, data)
        except AppError as exc:
            self.error_label.setText(getattr(exc, "message_fa", str(exc)))
            self.error_label.setVisible(True)
            return
        self.accept()
