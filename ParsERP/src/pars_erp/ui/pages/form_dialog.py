"""Small RTL form dialog shared by the phase-5 (HR / payroll / assets) screens.

The dialog owns the boring parts every create/edit window needs: a scrollable
body, ``label + control`` rows, an inline Persian error message instead of a raw
traceback, a primary "save" button and a cancel button. Subclasses only build the
fields and implement :meth:`save`.

Validation errors raised by the service layer (``AppError`` descendants) are
shown inside the dialog so the user can correct the form without losing what
they typed - nothing is silently swallowed.
"""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import QTime, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.ui.pages.accounting.widgets import form_row


class TimeEdit(QTimeEdit):
    """Clock editor returning ``datetime.time`` (or ``None`` when cleared)."""

    def __init__(self, value=None, *, optional: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDisplayFormat("HH:mm")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._optional = optional
        if value is not None:
            if isinstance(value, _dt.time):
                self.setTime(QTime(value.hour, value.minute, value.second))
            else:
                self.setTime(QTime(value.hour(), value.minute()))
        elif optional:
            self.setMinimumTime(QTime(0, 0))
            self.setSpecialValueText("—")
            self.setTime(QTime(0, 0))

    def time_value(self):
        if self._optional and self.time() == QTime(0, 0):
            return None
        return self.time().toPython()


class FormDialog(QDialog):
    """Base dialog: body grid, error label, save/cancel buttons."""

    title_fa = "فرم"
    save_text = "ذخیره"
    width = 640

    def __init__(self, services, ctx, *, parent: QWidget | None = None,
                 subtitle: str = "") -> None:
        super().__init__(parent)
        self.services = services
        self.ctx = ctx
        self.saved = None
        self.setWindowTitle(self.title_fa)
        self.setModal(True)
        self.setMinimumWidth(self.width)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)

        heading = QLabel(self.title_fa)
        heading.setObjectName("SectionTitle")
        outer.addWidget(heading)
        if subtitle:
            note = QLabel(subtitle)
            note.setObjectName("HintText")
            note.setWordWrap(True)
            outer.addWidget(note)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._content = QWidget()
        self.body = QGridLayout(self._content)
        self.body.setContentsMargins(0, 0, 6, 0)
        self.body.setHorizontalSpacing(12)
        self.body.setVerticalSpacing(10)
        scroll.setWidget(self._content)
        scroll.setMinimumHeight(320)
        outer.addWidget(scroll, 1)

        self.error_label = QLabel("")
        self.error_label.setObjectName("ErrorText")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        outer.addWidget(self.error_label)

        self.button_box = QDialogButtonBox()
        self.save_button = self.button_box.addButton(self.save_text,
                                                     QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.setProperty("variant", "primary")
        cancel = self.button_box.addButton("انصراف", QDialogButtonBox.ButtonRole.RejectRole)
        cancel.setProperty("variant", "ghost")
        self.button_box.accepted.connect(self.submit)
        self.button_box.rejected.connect(self.reject)
        outer.addWidget(self.button_box)

        self._row = 0
        self._build()

    # ------------------------------------------------------------------ layout
    def add_row(self, label: str, widget: QWidget, *, hint: str = "",
                required: bool = False) -> QWidget:
        text = f"{label} *" if required else label
        container = form_row(text, widget, hint=hint)
        self.body.addWidget(container, self._row, 0, 1, 2)
        self._row += 1
        return widget

    def add_pair(self, left: tuple[str, QWidget], right: tuple[str, QWidget], *,
                 left_hint: str = "", right_hint: str = "",
                 left_required: bool = False, right_required: bool = False) -> None:
        for column, (label, widget, hint, required) in enumerate((
                (left[0], left[1], left_hint, left_required),
                (right[0], right[1], right_hint, right_required))):
            text = f"{label} *" if required else label
            self.body.addWidget(form_row(text, widget, hint=hint), self._row, column)
        self._row += 1

    def add_widget(self, widget: QWidget) -> QWidget:
        self.body.addWidget(widget, self._row, 0, 1, 2)
        self._row += 1
        return widget

    def add_section(self, title: str) -> None:
        label = QLabel(title)
        label.setObjectName("CardTitle")
        self.body.addWidget(label, self._row, 0, 1, 2)
        self._row += 1

    # ----------------------------------------------------------------- helpers
    def can(self, permission: str) -> bool:
        return bool(self.ctx is not None and self.ctx.has(permission))

    # -------------------------------------------------------------------- hooks
    def _build(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def save(self):  # pragma: no cover - overridden
        raise NotImplementedError

    def submit(self) -> None:
        self.error_label.setVisible(False)
        try:
            self.saved = self.save()
        except AppError as error:
            self.error_label.setText(str(error))
            self.error_label.setVisible(True)
            return
        self.accept()


# --------------------------------------------------------------------- helpers
def fill_combo(combo: QComboBox, choices, *, current=None,
               placeholder: str = "— انتخاب کنید —") -> QComboBox:
    combo.clear()
    if placeholder:
        combo.addItem(placeholder, None)
    for value, label in choices:
        combo.addItem(str(label), value)
    select_combo(combo, current)
    return combo


def select_combo(combo: QComboBox, value) -> None:
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)


def combo_value(combo: QComboBox):
    return combo.currentData()


def check(value: bool, text: str, *, checked: bool | None = None) -> QCheckBox:
    box = QCheckBox(text)
    box.setChecked(bool(value) if checked is None else bool(checked))
    return box
