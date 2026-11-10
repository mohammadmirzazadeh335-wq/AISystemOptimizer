"""Shared controls for the human-resources, payroll and fixed-asset screens."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QWidget,
)

from pars_erp.core.jalali import JalaliDate
from pars_erp.ui.pages.commerce.widgets import PickCombo  # noqa: F401  (re-export)

__all__ = [
    "EmployeePicker", "PickCombo", "YearMonthPicker", "MONTH_NAMES_FA",
    "month_choices", "masked", "hint_label", "employee_choices", "decimal_text",
    "current_jalali_year_month",
]

MONTH_NAMES_FA: tuple[str, ...] = (
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
)


def month_choices() -> tuple[tuple[int, str], ...]:
    return tuple((index + 1, name) for index, name in enumerate(MONTH_NAMES_FA))


def current_jalali_year_month() -> tuple[int, int]:
    today = JalaliDate.today()
    return today.year, today.month


def employee_choices(services, ctx, *, active_only: bool = True) -> list[tuple[int, str]]:
    try:
        return services.hr.employee_choices(ctx, active_only=active_only)
    except Exception:  # a user without the permission simply sees an empty list
        return []


class EmployeePicker(PickCombo):
    """Employee combo that fills itself from the service layer."""

    def __init__(self, *, active_only: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.active_only = active_only
        self.services = None
        self.ctx = None

    def attach(self, services, ctx) -> None:
        self.services = services
        self.ctx = ctx
        self.reload()

    def reload(self) -> None:
        self.load(employee_choices(self.services, self.ctx, active_only=self.active_only)
                  if self.services is not None else [])

    def require(self, label: str = "کارمند") -> int:
        from pars_erp.core.errors import ValidationError

        value = self.value()
        if value is None:
            raise ValidationError(f"{label} را انتخاب کنید.", field="employee_id")
        return int(value)


class YearMonthPicker(QWidget):
    """Jalali year + month pair used by payroll runs and depreciation."""

    changed = Signal(int, int)

    def __init__(self, year: int | None = None, month: int | None = None,
                 *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        default_year, default_month = current_jalali_year_month()
        self.year_spin = QSpinBox()
        self.year_spin.setRange(1300, 1500)
        self.year_spin.setValue(year or default_year)
        self.year_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.month_combo = QComboBox()
        for value, title in month_choices():
            self.month_combo.addItem(title, value)
        index = self.month_combo.findData(month or default_month)
        self.month_combo.setCurrentIndex(index if index >= 0 else 0)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(QLabel("سال"))
        row.addWidget(self.year_spin, 1)
        row.addWidget(QLabel("ماه"))
        row.addWidget(self.month_combo, 1)

        self.year_spin.valueChanged.connect(lambda _value: self._emit())
        self.month_combo.currentIndexChanged.connect(lambda _index: self._emit())

    def _emit(self) -> None:
        self.changed.emit(*self.value())

    def value(self) -> tuple[int, int]:
        return int(self.year_spin.value()), int(self.month_combo.currentData())

    def set_value(self, year: int, month: int) -> None:
        self.year_spin.setValue(int(year))
        index = self.month_combo.findData(int(month))
        if index >= 0:
            self.month_combo.setCurrentIndex(index)


def masked(value: str | None, *, visible: bool) -> str:
    """Show sensitive fields only when the user may see them (service masks too)."""
    if not value:
        return "—"
    return str(value) if visible else "••••"


def hint_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("HintText")
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignRight)
    return label


def decimal_text(value: Decimal | None) -> str:
    if value in (None, ""):
        return ""
    try:
        return f"{Decimal(value):f}"
    except (InvalidOperation, TypeError):
        return ""


def today() -> _dt.date:
    return _dt.date.today()
