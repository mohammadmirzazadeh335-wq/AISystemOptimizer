"""Shared fixtures.

Every test runs against a throw-away workspace directory and the offscreen Qt
platform, so no test can touch a real user profile.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")

from myai.context import build_context  # noqa: E402


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    return tmp_path / "workspace"


@pytest.fixture()
def ctx(home: Path):
    context = build_context(home, log=False)
    context.boot()
    yield context
    context.shutdown()


@pytest.fixture()
def sample_conversation(ctx):
    conversation = ctx.conversations.create("Compiler sandbox notes", select=False)
    ctx.conversations.add_message(conversation.id, "user", "Draft a safe sandbox policy.")
    ctx.conversations.add_message(conversation.id, "assistant", "Jail the directory and cap runtime.")
    return ctx.conversations.get(conversation.id)


@pytest.fixture(autouse=True)
def _reclaim_widgets():
    """Destroy window trees between tests.

    ``deleteLater`` posts a DeferredDelete event that ``processEvents`` does not
    handle, so without an explicit flush every test left a full window alive.
    Qt then re-polished thousands of stale widgets on the next style change,
    which turned a minute of tests into a hang.
    """
    yield
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.setParent(None)
        widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([sys.argv[0] if sys.argv else "pytest"])
    yield app


@pytest.fixture()
def ui(home, qapp):
    """A fully wired main window on a temporary workspace."""
    from myai.ui.main_window import MainWindow
    from myai.ui.theme import runtime
    from myai.ui.theme.manager import ThemeManager

    context = build_context(home, log=False)
    context.boot()
    theme = ThemeManager(qapp, context.settings, context.paths)
    runtime.set_manager(theme)
    theme.apply()
    window = MainWindow(context, theme)
    window.resize(1440, 900)
    window.show()
    qapp.processEvents()
    yield window, context, theme
    # Delete the widget tree instead of leaving it for the garbage collector:
    # a session-scoped QApplication kept every window alive, and the next
    # ``setStyle`` had to re-polish thousands of stale widgets.
    window.close()
    window.setParent(None)
    window.deleteLater()
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    context.shutdown()
