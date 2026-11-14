"""Shared controls for the commerce screens (all RTL, all Persian)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QLineEdit, QWidget

from pars_erp.ui.pages.accounting.widgets import MoneyEdit, form_row  # noqa: F401  (re-export)


class PickCombo(QComboBox):
    """A combo box carrying ``id`` in ``userData`` (products, persons, warehouses)."""

    def load(self, choices, *, placeholder: str = "— انتخاب کنید —") -> None:
        current = self.currentData()
        self.blockSignals(True)
        self.clear()
        if placeholder:
            self.addItem(placeholder, None)
        for identifier, label in choices:
            self.addItem(label, identifier)
        # restoring the previous value must not re-emit ``currentIndexChanged``:
        # a screen that reloads its combo while refreshing would otherwise loop.
        if current is not None:
            index = self.findData(current)
            if index >= 0:
                self.setCurrentIndex(index)
        self.blockSignals(False)

    def value(self) -> int | None:
        data = self.currentData()
        return int(data) if data not in (None, "") else None

    def set_value(self, identifier: int | None) -> None:
        if identifier is None:
            self.setCurrentIndex(0)
            return
        index = self.findData(identifier)
        if index >= 0:
            self.setCurrentIndex(index)


class QtyEdit(QLineEdit):
    """Quantity input that only accepts digits, a dot and Persian digits."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setPlaceholderText("۰")

    def quantity(self):
        from pars_erp.services.commerce_common import to_quantity

        return to_quantity(self.text() or 0)

    def set_quantity(self, value) -> None:
        from decimal import Decimal

        text = "" if value in (None, "") else str(Decimal(str(value)).normalize())
        self.setText(text.replace("E+", ""))


def confirm(parent: QWidget | None, title: str, message: str, *,
            danger: bool = False, require_phrase: str | None = None) -> bool:
    """RTL confirmation dialog; returns ``True`` when the user accepted."""
    from pars_erp.ui.dialogs.common_dialogs import ConfirmDialog

    dialog = ConfirmDialog(parent, title=title, message=message, danger=danger,
                           require_phrase=require_phrase)
    return dialog.exec() == QDialog.DialogCode.Accepted


def ask_reason(parent: QWidget | None, title: str, prompt: str) -> str | None:
    """Ask for a short mandatory reason (used by reversal/void actions)."""
    from PySide6.QtWidgets import QInputDialog

    text, accepted = QInputDialog.getText(parent, title, prompt)
    text = (text or "").strip()
    if not accepted or len(text) < 5:
        return None
    return text


__all__ = ["PickCombo", "QtyEdit", "MoneyEdit", "form_row", "confirm", "ask_reason"]
