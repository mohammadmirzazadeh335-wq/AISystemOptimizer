"""Read-only list dialog (history, installments, batch items, payslip lines)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from pars_erp.ui.formatting import Formatter
from pars_erp.ui.table_specs import ColumnSpec
from pars_erp.ui.widgets.table import DataTable


class TableDialog(QDialog):
    """A modal window showing rows in the standard table; nothing is editable."""

    def __init__(self, title: str, columns: tuple[ColumnSpec, ...], rows,
                 *, parent: QWidget | None = None, subtitle: str = "",
                 formatter: Formatter | None = None, width: int = 860) -> None:
        super().__init__(parent)
        self.rows = list(rows)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(width, 460)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)

        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        if subtitle:
            note = QLabel(subtitle)
            note.setObjectName("HintText")
            note.setWordWrap(True)
            layout.addWidget(note)

        self.table = DataTable(columns, formatter=formatter or Formatter())
        self.table.set_rows(self.rows)
        layout.addWidget(self.table, 1)

        self.summary = QLabel(f"{len(self.rows):,} ردیف")
        self.summary.setObjectName("HintText")
        layout.addWidget(self.summary)

        buttons = QDialogButtonBox()
        close = buttons.addButton("بستن", QDialogButtonBox.ButtonRole.AcceptRole)
        close.setProperty("variant", "primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)


def show_rows(parent: QWidget | None, title: str, columns: tuple[ColumnSpec, ...], rows,
              *, formatter: Formatter | None = None, subtitle: str = "") -> None:
    TableDialog(title, columns, rows, parent=parent, subtitle=subtitle,
                formatter=formatter).exec()
