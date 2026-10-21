"""Application bootstrap: QApplication, single-instance lock, error handling."""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QLockFile, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .context import AppContext, build_context
from .i18n import set_language, tr
from .ui.brand import app_icon
from .ui.main_window import MainWindow
from .ui.theme import runtime
from .ui.theme.manager import ThemeManager
from .version import APP_NAME, APP_SHORT_NAME, APP_VENDOR, VERSION

logger = logging.getLogger(__name__)


def create_application(argv: Sequence[str]) -> QApplication:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(list(argv))
    app.setApplicationName(APP_SHORT_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_VENDOR)
    app.setApplicationVersion(VERSION)
    app.setWindowIcon(app_icon())
    return app


def _acquire_lock(home: Path, allow_multi: bool) -> tuple[QLockFile | None, bool]:
    if allow_multi:
        return None, True
    lock = QLockFile(str(home / "myai-studio.lock"))
    lock.setStaleLockTime(0)
    return lock, bool(lock.tryLock(150))


def install_exception_hook(window: MainWindow, ctx: AppContext) -> None:
    busy = {"active": False}

    def hook(exc_type, exc_value, exc_tb) -> None:  # noqa: ANN001
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.getLogger("myai.unhandled").error("unhandled_exception\n%s", text)
        if busy["active"]:
            return
        busy["active"] = True
        try:
            box = QMessageBox(window)
            box.setWindowTitle(tr("error.title"))
            box.setText(tr("error.unexpected"))
            box.setDetailedText(text[-4000:])
            box.setIcon(QMessageBox.Icon.Critical)
            box.exec()
        finally:
            busy["active"] = False

    sys.excepthook = hook


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="myai-studio", description=APP_NAME, add_help=True)
    parser.add_argument("--home", type=str, default=None, help="Override the application data directory")
    parser.add_argument("--lang", choices=["fa", "en"], default=None, help="Interface language for this run")
    parser.add_argument("--theme", choices=["midnight", "dawn", "aurora", "system"], default=None)
    parser.add_argument("--screenshot", type=str, default=None, help="Capture the window and exit")
    parser.add_argument("--smoke", action="store_true", help="Start the UI, then exit (CI check)")
    parser.add_argument("--allow-multi", action="store_true", help="Skip the single-instance lock")
    known, _qt_args = parser.parse_known_args(argv)

    paths_home = Path(known.home).expanduser() if known.home else None
    try:
        ctx = build_context(paths_home)
    except Exception as exc:  # pragma: no cover - fatal path
        logging.basicConfig(level=logging.ERROR)
        logging.getLogger(__name__).exception("startup_failed")
        app = create_application([sys.argv[0]])
        QMessageBox.critical(None, APP_NAME, f"{tr('error.db')}\n\n{exc}")
        return 1

    # boot() loads persisted settings; per-run overrides must be applied after it,
    # otherwise they would be replaced by the stored values.
    ctx.boot()
    if known.lang:
        ctx.settings.set("ui.language", known.lang, persist=False)
    if known.theme:
        ctx.settings.set("ui.theme", known.theme, persist=False)
    set_language(str(ctx.settings.get("ui.language", "fa")))

    app = create_application([sys.argv[0], *_qt_args])
    icon: QIcon = app_icon()
    app.setWindowIcon(icon)

    lock, acquired = _acquire_lock(ctx.paths.home, known.allow_multi)
    if not acquired:
        # Never show a modal box here: the user already has the window open, and a
        # blocking dialog in a headless/CI run would hang the process forever.
        logger.warning("second_instance_blocked home=%s", ctx.paths.home)
        print(tr("error.already_running"), file=sys.stderr)
        ctx.shutdown()
        return 0

    theme_manager = ThemeManager(app, ctx.settings, ctx.paths)
    runtime.set_manager(theme_manager)
    theme_manager.apply()

    window = MainWindow(ctx, theme_manager)
    window.show()
    install_exception_hook(window, ctx)
    logger.info("window_shown version=%s", VERSION)

    if known.screenshot:
        def capture() -> None:
            try:
                Path(known.screenshot).parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(known.screenshot)
                logger.info("screenshot_saved path=%s", known.screenshot)
            finally:
                app.quit()

        QTimer.singleShot(1300, capture)
    elif known.smoke:
        QTimer.singleShot(1200, app.quit)

    exit_code = app.exec()
    try:
        if not window._closing:
            ctx.shutdown()
    except Exception:
        pass
    if lock is not None:
        try:
            lock.unlock()
        except Exception:
            pass
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
