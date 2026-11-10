"""Qt application bootstrap and window orchestration.

Responsibilities:

1. build the services (config → database → migrations → reference data);
2. create the QApplication, load the Persian font and apply the saved theme;
3. run the login / first-run setup loop and hand a SecurityContext to the main
   window;
4. enforce the "password change required" rule before the main window opens;
5. log out cleanly and keep the process alive when the main window closes only
   because of a logout.
"""

from __future__ import annotations

import logging
import sys
import traceback
from dataclasses import dataclass, field

from pars_erp import __version__
from pars_erp.config.paths import AppPaths
from pars_erp.config.settings import load_config
from pars_erp.core.errors import AppError
from pars_erp.security.permissions import SecurityContext
from pars_erp.services.context import AppServices, build_services, prepare_application

logger = logging.getLogger(__name__)


@dataclass
class AppOptions:
    paths: AppPaths = field(default_factory=AppPaths.default)
    run_startup_backup: bool = True
    show_setup: bool = True
    exit_after_setup: bool = False


class ApplicationController:
    """Owns the window stack: login window ⇄ main window."""

    def __init__(self, services: AppServices, app) -> None:
        self.services = services
        self.app = app
        self.login_window = None
        self.main_window = None
        self._quitting = False

    # --------------------------------------------------------------- windows
    def start(self) -> None:
        from pars_erp.ui.login_window import LoginWindow

        self.login_window = LoginWindow(self.services)
        self.login_window.authenticated.connect(self.open_main_window)
        self.login_window.destroyed.connect(self._on_login_destroyed)
        self.login_window.show()

    def open_main_window(self, ctx: SecurityContext) -> None:
        from pars_erp.ui.main_window import MainWindow

        if isinstance(ctx, bool):  # Qt can deliver the destroyed(bool) helper
            return
        if ctx.must_change_password and not self._force_password_change(ctx):
            return
        ctx = self.services.auth.reload_context(ctx)
        self.main_window = MainWindow(self.services, ctx)
        self.main_window.logoutRequested.connect(self.logout)
        self.main_window.exitRequested.connect(self.quit)
        self.main_window.show()
        if self.login_window is not None:
            self.login_window.hide()
            self.login_window.deleteLater()
            self.login_window = None

    def _force_password_change(self, ctx: SecurityContext) -> bool:
        from PySide6.QtWidgets import QMessageBox

        from pars_erp.ui.dialogs.common_dialogs import ChangePasswordDialog

        while ctx.must_change_password:
            dialog = ChangePasswordDialog(None, self.services, ctx, mandatory=True)
            if not dialog.exec():
                QMessageBox.information(
                    None, "تغییر رمز الزامی",
                    "بدون تغییر رمز عبور نمی‌توانید وارد شوید. از حساب خارج شدید.")
                self.services.auth.logout(ctx, reason="password_change_declined")
                return False
            ctx = self.services.auth.reload_context(ctx)
        return True

    # ---------------------------------------------------------------- events
    def logout(self) -> None:
        from pars_erp.ui.login_window import LoginWindow

        if self.main_window is not None:
            try:
                self.services.auth.logout(self.main_window.ctx, reason="logout")
            except AppError:
                logger.exception("logout failed")
            self.main_window.deleteLater()
            self.main_window = None
        self.login_window = LoginWindow(self.services)
        self.login_window.authenticated.connect(self.open_main_window)
        self.login_window.show()

    def quit(self) -> None:
        self._quitting = True
        if self.main_window is not None:
            self.main_window.deleteLater()
        if self.login_window is not None:
            self.login_window.deleteLater()
        self.app.quit()

    def _on_login_destroyed(self, *_args) -> None:
        # The user closed the login window (and did not log in): terminate.
        if not self._quitting and self.main_window is None:
            self.app.quit()


def _install_exception_hook(app) -> None:
    """Show a Persian error dialog instead of crashing with a traceback."""

    def hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.error("unhandled exception: %s", exc_value,
                     exc_info=(exc_type, exc_value, exc_tb))
        try:
            from PySide6.QtWidgets import QMessageBox
            details = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle("خطای غیرمنتظره")
            box.setText("خطای غیرمنتظره‌ای رخ داد.")
            box.setInformativeText(str(exc_value))
            box.setDetailedText(details)
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.button(QMessageBox.StandardButton.Ok).setText("باشه")
            box.exec()
        except Exception:  # pragma: no cover - GUI may not exist
            pass

    sys.excepthook = hook


def create_qt_app(argv: list[str]):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from pars_erp.ui.fonts import load_bundled_fonts
    from pars_erp.ui.theme import apply_theme

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    app = QApplication.instance() or QApplication(argv)
    # Fusion renders identically on Windows and Linux and cooperates well with QSS.
    app.setStyle("Fusion")
    app.setApplicationName("ParsERP")
    app.setApplicationDisplayName("ParsERP")
    app.setApplicationVersion(__version__)
    load_bundled_fonts()
    return app


def run_gui(options: AppOptions | None = None, argv: list[str] | None = None) -> int:
    """Start the desktop application. Returns the process exit code."""
    options = options or AppOptions()
    paths = options.paths.ensure()
    config = load_config(paths)

    from pars_erp.logging_setup import configure_logging
    log_file = configure_logging(paths.logs_dir, config)
    logger.info("%s %s starting (home=%s, log=%s)", "ParsERP", __version__, paths.home, log_file)

    services = build_services(paths=paths, config=config)
    try:
        prepare_application(services, run_startup_backup=options.run_startup_backup)
    except Exception:
        logger.exception("startup failed during database preparation")
        raise

    app = create_qt_app(argv or sys.argv)
    from pars_erp.ui.theme import apply_theme
    apply_theme(app, services.settings.snapshot())
    _install_exception_hook(app)

    controller = ApplicationController(services, app)
    controller.start()
    try:
        return int(app.exec())
    finally:
        services.dispose()
        logger.info("application stopped")


def main(argv: list[str] | None = None) -> int:
    from pars_erp.cli import main as cli_main
    return cli_main(argv)
