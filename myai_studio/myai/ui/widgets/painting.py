"""Exception-safe custom painting.

A Python exception raised inside a ``QWidget.paintEvent`` while a ``QPainter``
is active aborts the paint cycle and can crash the process.  ``paint_event``
centralises painter creation, enables antialiasing, logs failures and always
ends the painter.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable

from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


def paint_event(func: Callable[[QWidget, QPainter, object], None]):
    @functools.wraps(func)
    def wrapper(self: QWidget, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        try:
            func(self, painter, event)
        except Exception:  # pragma: no cover - defensive path
            logger.exception("paint_failed widget=%s", type(self).__name__)
        finally:
            if painter.isActive():
                painter.end()

    return wrapper
