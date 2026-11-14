"""Printable preview of a :class:`ReportTable`.

The preview shows exactly the HTML that the PDF exporter writes, so what the
accountant checks on screen is what leaves the office. Printing goes through
QtPrintSupport when a printer (or CUPS) is available; otherwise the dialog says
so in Persian instead of crashing.
"""

from __future__ import annotations

import io

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from pars_erp.core.errors import AppError
from pars_erp.services.report_render_service import ReportRenderer, ReportTable


class ReportPreviewDialog(QDialog):
    def __init__(self, table: ReportTable, renderer: ReportRenderer, *,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.table = table
        self.renderer = renderer
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setWindowTitle(f"پیش‌نمایش چاپ — {table.title}")
        self.resize(1080, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        self.note = QLabel("این پیش‌نمایش همان خروجی PDF است.")
        self.note.setObjectName("HintText")
        layout.addWidget(self.note)

        self.browser = QTextBrowser()
        self.browser.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.browser.setHtml(self.renderer.to_html(table))
        layout.addWidget(self.browser, 1)

        buttons = QHBoxLayout()
        self.print_button = QPushButton("ارسال به چاپگر")
        self.print_button.setProperty("variant", "primary")
        self.print_button.clicked.connect(self._print)
        buttons.addWidget(self.print_button)
        buttons.addStretch(1)
        close = QPushButton("بستن")
        close.setProperty("variant", "ghost")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _print(self) -> None:
        try:
            from PySide6.QtGui import QTextDocument
            from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        except Exception:  # pragma: no cover - Qt built without print support
            self.note.setText("پشتیبانی چاپ در این نسخهٔ Qt موجود نیست؛ از خروجی PDF استفاده کنید.")
            return
        try:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            dialog = QPrintDialog(printer, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            document = QTextDocument()
            document.setHtml(self.renderer.to_html(self.table))
            document.print_(printer)
            self.note.setText("سند به چاپگر ارسال شد.")
        except AppError as error:
            self.note.setText(str(error))
        except Exception as error:  # pragma: no cover - no CUPS in the sandbox
            self.note.setText(f"چاپ انجام نشد: {error}")


def preview_bytes(table: ReportTable, renderer: ReportRenderer) -> io.BytesIO:
    """Helper for tests: the HTML payload of a preview as bytes."""
    return io.BytesIO(renderer.to_html(table).encode("utf-8"))
