"""Declarative Qt table model + view wrapper.

Screens pass a tuple of :class:`ColumnSpec` and a list of row objects; sorting,
number alignment, badge colouring and Persian formatting are handled here.
"""

from __future__ import annotations

from typing import Any, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QTableWidget,
    QWidget,
)

from pars_erp.ui.formatting import Formatter
from pars_erp.ui.table_specs import BADGE, ColumnSpec, badge_tone, format_cell

_ALIGN = {
    "right": Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
    "left": Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    "center": Qt.AlignmentFlag.AlignCenter,
}

_TONE_COLORS = {
    "success": "#067647",
    "warning": "#b54708",
    "danger": "#b42318",
    "info": "#175cd3",
    "neutral": "#475467",
}

# readable foregrounds for dark surfaces
_TONE_COLORS_DARK = {
    "success": "#6ee7a8",
    "warning": "#f3b664",
    "danger": "#f19b95",
    "info": "#8fb8ff",
    "neutral": "#c4cdd9",
}


class BadgeDelegate(QStyledItemDelegate):
    """Paints ``BADGE`` columns as small rounded status pills."""

    def __init__(self, model: "DataTableModel", parent=None) -> None:
        super().__init__(parent)
        self._model = model

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        column = self._model.columns[index.column()]
        row = self._model.row_at(index.row())
        tone = badge_tone(column, row)
        if tone is None:
            super().paint(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget else QApplication.style()
        text = str(opt.text)
        opt.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        base = option.palette.base().color()
        dark_surface = base.lightness() < 140
        fg = QColor((_TONE_COLORS_DARK if dark_surface else _TONE_COLORS).get(tone, "#475467"))
        bg = QColor(fg)
        bg.setAlpha(52 if dark_surface else 34)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(option.font)
        font.setBold(True)
        font.setPointSizeF(max(7.0, font.pointSizeF() - 0.5))
        painter.setFont(font)
        # measure with the font itself: painter.fontMetrics() follows the
        # device transform and under-reports on scaled grabs
        metrics = QFontMetricsF(font)
        pill_width = min(metrics.horizontalAdvance(text) + 26, option.rect.width() - 4)
        pill_height = min(option.rect.height() - 8, 22)
        rect = QRectF(
            option.rect.center().x() - pill_width / 2.0,
            option.rect.center().y() - pill_height / 2.0,
            pill_width,
            pill_height,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, pill_height / 2.0, pill_height / 2.0)
        painter.setPen(fg)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class DataTableModel(QAbstractTableModel):
    def __init__(self, columns: Sequence[ColumnSpec], rows: Sequence[Any] | None = None,
                 formatter: Formatter | None = None, parent=None) -> None:
        super().__init__(parent)
        self._columns = list(columns)
        self._rows: list[Any] = list(rows or [])
        self._formatter = formatter or Formatter()

    # ---------------------------------------------------------- Qt interface
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._columns)

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._columns[section].title_fa
        return str(section + 1)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        column = self._columns[index.column()]
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return format_cell(column, row, self._formatter)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return _ALIGN.get(column.align, _ALIGN["right"])
        if role == Qt.ItemDataRole.ForegroundRole:
            tone = badge_tone(column, row)
            if tone:
                return QColor(_TONE_COLORS.get(tone, "#475467"))
        if role == Qt.ItemDataRole.ToolTipRole:
            text = format_cell(column, row, self._formatter)
            return text if len(text) > 30 else None
        if role == Qt.ItemDataRole.UserRole:
            return row
        return None

    # --------------------------------------------------------------- helpers
    @property
    def columns(self) -> list[ColumnSpec]:
        return list(self._columns)

    def set_rows(self, rows: Sequence[Any]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def set_columns(self, columns: Sequence[ColumnSpec]) -> None:
        """Swap the column set (used by screens that show different reports)."""
        self.beginResetModel()
        self._columns = list(columns)
        self.endResetModel()

    def set_formatter(self, formatter: Formatter) -> None:
        self._formatter = formatter
        if self._rows:
            top = self.index(0, 0)
            bottom = self.index(len(self._rows) - 1, len(self._columns) - 1)
            self.dataChanged.emit(top, bottom)

    def row_at(self, row_index: int) -> Any:
        return self._rows[row_index]

    def rows(self) -> list[Any]:
        return list(self._rows)


class DataTable(QTableView):
    """Pre-configured table view (RTL, sortable, alternating rows)."""

    rowActivated = Signal(int)
    rowContextRequested = Signal(int)

    def __init__(self, columns: Sequence[ColumnSpec], *, formatter: Formatter | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = DataTableModel(columns, [], formatter)
        self.setModel(self.model)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(34)
        self.horizontalHeader().setHighlightSections(False)

        self.setWordWrap(False)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.horizontalHeader().setStretchLastSection(False)
        for index, column in enumerate(columns):
            if column.width:
                self.setColumnWidth(index, column.width)
                self.horizontalHeader().setSectionResizeMode(
                    index, QHeaderView.ResizeMode.Interactive)
            else:
                self.horizontalHeader().setSectionResizeMode(
                    index, QHeaderView.ResizeMode.Stretch)
        badge_delegate = BadgeDelegate(self.model, self)
        for index, column in enumerate(columns):
            if column.kind == BADGE:
                self.setItemDelegateForColumn(index, badge_delegate)
        self.doubleClicked.connect(self._on_double_clicked)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def _on_double_clicked(self, index: QModelIndex) -> None:
        if index.isValid():
            self.rowActivated.emit(index.row())

    def _on_context_menu(self, position) -> None:
        index = self.indexAt(position)
        if index.isValid():
            self.rowContextRequested.emit(index.row())

    def on_selection_changed(self, callback) -> None:
        """QTableView has no itemSelectionChanged; wrap the selection model."""
        self.selectionModel().selectionChanged.connect(lambda *_args: callback())

    def set_rows(self, rows: Sequence[Any]) -> None:
        self.model.set_rows(rows)

    def set_columns(self, columns: Sequence[ColumnSpec]) -> None:
        self.model.set_columns(columns)

    def set_formatter(self, formatter: Formatter) -> None:
        self.model.set_formatter(formatter)

    def current_row(self) -> Any | None:
        index = self.currentIndex()
        if not index.isValid():
            return None
        return self.model.row_at(index.row())

    def selected_row_index(self) -> int | None:
        index = self.currentIndex()
        return index.row() if index.isValid() else None


class SimpleTableView(QTableWidget):
    """Plain grid used for read-only matrix views (permission checklist)."""

    def __init__(self, rows: int = 0, columns: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(rows, columns, parent)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)
