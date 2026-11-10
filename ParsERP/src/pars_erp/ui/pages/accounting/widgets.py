"""Shared widgets for the financial-accounting screens.

Everything here is deliberately small and reusable so the seventeen accounting
pages share one look: a Jalali date picker, a Rial (Decimal) amount field, an
account autocomplete, a currency picker and a report shell that can print,
preview and export the *same* table the user sees.
"""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.digits import to_latin_digits, to_persian_digits
from pars_erp.core.errors import AppError
from pars_erp.core.jalali import JalaliDate, days_in_month, gregorian_to_jalali, is_leap_year
from pars_erp.core.money import DECIMAL_SEPARATOR_FA, THOUSANDS_SEPARATOR_FA

_WEEKDAY_HEADERS = ("ش", "ی", "د", "س", "چ", "پ", "ج")
_MONTH_NAMES = ("فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
                "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند")


class JalaliMonthGrid(QWidget):
    """Month grid with Jalali day numbers; emits the picked Gregorian date."""

    picked = Signal(object)  # datetime.date

    def __init__(self, value: JalaliDate | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._today = JalaliDate.today()
        self._year = (value or self._today).year
        self._month = (value or self._today).month

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        nav = QHBoxLayout()
        nav.setSpacing(4)
        self.prev_button = QToolButton()
        self.prev_button.setText("‹")
        self.prev_button.setToolTip("ماه قبل")
        self.prev_button.clicked.connect(lambda: self._shift(-1))
        nav.addWidget(self.prev_button)

        self.title = QLabel()
        self.title.setObjectName("SectionTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav.addWidget(self.title, 1)

        self.next_button = QToolButton()
        self.next_button.setText("›")
        self.next_button.setToolTip("ماه بعد")
        self.next_button.clicked.connect(lambda: self._shift(1))
        nav.addWidget(self.next_button)
        layout.addLayout(nav)

        self.grid = QGridLayout()
        self.grid.setSpacing(2)
        layout.addLayout(self.grid)
        for column, label in enumerate(_WEEKDAY_HEADERS):
            header = QLabel(label)
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header.setObjectName("HintText")
            self.grid.addWidget(header, 0, column)
        self._rebuild()

    # ------------------------------------------------------------------ state
    def set_date(self, value: JalaliDate) -> None:
        self._year, self._month = value.year, value.month
        self._rebuild()

    def _shift(self, delta: int) -> None:
        month = self._month + delta
        year = self._year
        if month < 1:
            month, year = 12, year - 1
        elif month > 12:
            month, year = 1, year + 1
        self._year, self._month = year, month
        self._rebuild()

    def _rebuild(self) -> None:
        while self.grid.count() > len(_WEEKDAY_HEADERS):
            item = self.grid.takeAt(len(_WEEKDAY_HEADERS))
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.title.setText(to_persian_digits(
            f"{_MONTH_NAMES[self._month - 1]} {self._year}"))

        first = JalaliDate(self._year, self._month, 1).to_gregorian()
        # Jalali weeks start on Saturday: python weekday() Monday=0 → Saturday=5
        offset = (first.weekday() + 2) % 7
        length = days_in_month(self._year, self._month)
        for day in range(1, length + 1):
            cell = (day - 1 + offset)
            row, column = divmod(cell, 7)
            button = QPushButton(to_persian_digits(str(day)))
            button.setProperty("variant", "ghost")
            button.setMinimumSize(30, 26)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            if (self._year, self._month, day) == (
                    self._today.year, self._today.month, self._today.day):
                button.setProperty("variant", "primary")
            button.clicked.connect(lambda _checked=False, d=day: self._pick(d))
            self.grid.addWidget(button, row + 1, column)

    def _pick(self, day: int) -> None:
        self.picked.emit(JalaliDate(self._year, self._month, day).to_gregorian())


class JalaliDatePicker(QDialog):
    """Small popup hosting :class:`JalaliMonthGrid` plus a «برو به امروز» button."""

    def __init__(self, value: _dt.date | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("انتخاب تاریخ")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setModal(True)
        self.selected: _dt.date | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        start = gregorian_to_jalali(value) if value else None
        self.grid = JalaliMonthGrid(JalaliDate(*start) if start else None, self)
        self.grid.picked.connect(self._on_picked)
        layout.addWidget(self.grid)

        buttons = QHBoxLayout()
        today_button = QPushButton("امروز")
        today_button.setProperty("variant", "ghost")
        today_button.clicked.connect(self._pick_today)
        buttons.addWidget(today_button)
        buttons.addStretch(1)
        cancel = QPushButton("بستن")
        cancel.setProperty("variant", "ghost")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def _on_picked(self, value: _dt.date) -> None:
        self.selected = value
        self.accept()

    def _pick_today(self) -> None:
        self.selected = _dt.date.today()
        self.accept()


class JalaliDateEdit(QWidget):
    """Line edit holding a Jalali date (``1405/08/10``) with a calendar button.

    The value is stored as a plain :class:`datetime.date` so the database always
    receives the standard Gregorian date; only the presentation is Jalali.
    """

    dateChanged = Signal(object)

    def __init__(self, value: _dt.date | None = None, *, persian_digits: bool = True,
                 allow_empty: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.persian_digits = persian_digits
        self.allow_empty = allow_empty
        self._date: _dt.date | None = value

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("۱۴۰۵/۰۸/۱۰")
        self.edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit.setInputMask("")
        self.edit.setMaxLength(10)
        self.edit.editingFinished.connect(self._on_edited)
        layout.addWidget(self.edit, 1)

        self.button = QToolButton()
        self.button.setText("تقویم")
        self.button.setFixedWidth(58)
        self.button.setToolTip("انتخاب تاریخ از تقویم شمسی")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self.open_calendar)
        layout.addWidget(self.button)

        self.set_date(value)

    # ------------------------------------------------------------------ value
    def date(self) -> _dt.date | None:
        return self._date

    def set_date(self, value: _dt.date | None) -> None:
        self._date = value
        if value is None:
            self.edit.clear()
        else:
            text = JalaliDate.from_gregorian(value).format(persian_digits=self.persian_digits)
            self.edit.setText(text)
        self.dateChanged.emit(value)

    def set_persian_digits(self, persian: bool) -> None:
        self.persian_digits = persian
        self.set_date(self._date)

    def open_calendar(self) -> None:
        dialog = JalaliDatePicker(self._date, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected is not None:
            self.set_date(dialog.selected)

    def _on_edited(self) -> None:
        text = to_latin_digits(self.edit.text()).strip().replace("-", "/").replace(".", "/")
        if not text:
            if self.allow_empty:
                self._date = None
                self.dateChanged.emit(None)
            else:
                self.set_date(self._date)
            return
        parts = [part for part in text.split("/") if part]
        try:
            if len(parts) != 3:
                raise ValueError
            year, month, day = (int(part) for part in parts)
            if year < 100:
                year += 1400
            JalaliDate(year, month, day)
            self.set_date(JalaliDate(year, month, day).to_gregorian())
        except (ValueError, TypeError, AppError):
            # keep the previous valid value and show the canonical text again
            self.set_date(self._date)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._on_edited()
            return
        super().keyPressEvent(event)


class MoneyEdit(QLineEdit):
    """Amounts typed by an accountant: digits only, grouped, always ``Decimal``."""

    valueChanged = Signal(object)

    def __init__(self, *, persian_digits: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.persian_digits = persian_digits
        self.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.setPlaceholderText("۰")
        font = QFont(self.font())
        font.setFamilies([font.family(), "DejaVu Sans"])
        self.setFont(font)
        self.editingFinished.connect(self._reformat)

    # ------------------------------------------------------------------ value
    @property
    def amount(self) -> Decimal:
        text = to_latin_digits(self.text())
        for character in (THOUSANDS_SEPARATOR_FA, ",", " "):
            text = text.replace(character, "")
        text = text.replace(DECIMAL_SEPARATOR_FA, ".").strip()
        if not text:
            return Decimal(0)
        try:
            return Decimal(text)
        except InvalidOperation:
            return Decimal(0)

    def set_amount(self, value: Decimal | int | str | None) -> None:
        if value in (None, ""):
            self.setText("")
            return
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
        text = f"{amount:f}"
        if self.persian_digits:
            text = (to_persian_digits(text)
                    .replace(",", THOUSANDS_SEPARATOR_FA)
                    .replace(".", DECIMAL_SEPARATOR_FA))
        self.setText(text)

    def clear_value(self) -> None:
        self.setText("")

    def _reformat(self) -> None:
        amount = self.amount
        if amount == 0 and not to_latin_digits(self.text()).strip():
            self.setText("")
            return
        self.set_amount(amount)
        self.valueChanged.emit(amount)


class AccountPicker(QComboBox):
    """Editable combo with autocomplete over ``code — title`` account labels."""

    accountChanged = Signal(object)

    def __init__(self, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMaxVisibleItems(18)
        completer = self.completer()
        if completer is not None:
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.currentIndexChanged.connect(self._emit_change)

    def load(self, choices, *, placeholder: str = "— انتخاب حساب —",
             empty: bool = True) -> None:
        self.blockSignals(True)
        self.clear()
        if empty:
            self.addItem(placeholder, None)
        for account_id, label in choices:
            self.addItem(label, account_id)
        self.setCurrentIndex(0)
        self.blockSignals(False)

    def current_account_id(self) -> int | None:
        text = self.currentText().strip()
        if not text:
            return None
        # an exact label always wins: setEditText() does not move the index
        for index in range(self.count()):
            if self.itemText(index) == text:
                return self.itemData(index)
        # the user may have typed/pasted just the code, so match on the prefix
        code = text.split("—")[0].strip()
        for index in range(self.count()):
            label = self.itemText(index)
            if code and label.startswith(code + " "):
                return self.itemData(index)
        return None

    def set_account(self, account_id: int | None) -> None:
        index = self.findData(account_id) if account_id is not None else 0
        self.setCurrentIndex(index if index >= 0 else 0)

    def _emit_change(self, _index: int) -> None:
        self.accountChanged.emit(self.current_account_id())


def form_row(label: str, widget: QWidget, *, hint: str = "") -> QWidget:
    """Label above control, RTL aligned - the layout used by every accounting form."""
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    title = QLabel(label)
    title.setObjectName("FieldLabel")
    layout.addWidget(title)
    layout.addWidget(widget)
    if hint:
        note = QLabel(hint)
        note.setObjectName("HintText")
        note.setWordWrap(True)
        layout.addWidget(note)
    return container
