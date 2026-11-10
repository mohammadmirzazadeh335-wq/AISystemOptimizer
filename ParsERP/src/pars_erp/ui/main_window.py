"""Main application window: sidebar navigation, toolbar, pages, idle lock."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pars_erp import __phase__, __version__
from pars_erp.core.errors import AppError
from pars_erp.security.permissions import ADMIN_ROLE_CODE, SecurityContext
from pars_erp.services.context import AppServices
from pars_erp.ui.dialogs.common_dialogs import (
    ChangePasswordDialog,
    LockScreenDialog,
    show_error,
    show_info,
)
from pars_erp.ui.formatting import Formatter, to_display_digits
from pars_erp.ui.navigation import NavGroup, visible_items
from pars_erp.ui.pages.accounting.accounts_page import AccountsPage
from pars_erp.ui.pages.accounting.dashboard_page import AccountingDashboardPage
from pars_erp.ui.pages.accounting.dimensions_page import CurrenciesPage, DimensionsPage
from pars_erp.ui.pages.accounting.journals_page import JournalsPage
from pars_erp.ui.pages.accounting.periods_page import PeriodsPage
from pars_erp.ui.pages.accounting.reports_page import (
    BalanceSheetPage,
    GeneralLedgerPage,
    IncomeStatementPage,
    JournalBookPage,
    SubsidiaryLedgerPage,
    TrialBalancePage,
    TurnoverPage,
)
from pars_erp.ui.pages.accounting.settings_page import AccountingSettingsPage
from pars_erp.ui.pages.audit_page import AuditPage
from pars_erp.ui.pages.commerce.inventory_page import InventoryPage
from pars_erp.ui.pages.commerce.invoices_page import InvoicesPage
from pars_erp.ui.pages.commerce.orders_page import OrdersPage
from pars_erp.ui.pages.commerce.persons_page import PersonsPage
from pars_erp.ui.pages.commerce.pricing_page import PricingPage
from pars_erp.ui.pages.commerce.products_page import ProductsPage
from pars_erp.ui.pages.commerce.reports_page import CommerceReportsPage
from pars_erp.ui.pages.commerce.settings_page import CommerceSettingsPage
from pars_erp.ui.pages.backup_page import BackupPage
from pars_erp.ui.pages.treasury.cheques_page import (
    ChequeBooksPage,
    ChequeManagePage,
    IssuedChequesPage,
    PayableDocumentsPage,
    ReceivableDocumentsPage,
    ReceivedChequesPage,
)
from pars_erp.ui.pages.treasury.dashboard_page import TreasuryDashboardPage
from pars_erp.ui.pages.treasury.funds_page import BankAccountsPage, CashBoxesPage
from pars_erp.ui.pages.treasury.reconciliation_page import ReconciliationPage
from pars_erp.ui.pages.treasury.reports_page import FundFlowPage, TreasuryReportsPage
from pars_erp.ui.pages.treasury.settings_page import TreasurySettingsPage
from pars_erp.ui.pages.treasury.settlements_page import SettlementsPage
from pars_erp.ui.pages.treasury.transfers_page import TransfersPage
from pars_erp.ui.pages.treasury.vouchers_page import VouchersPage
from pars_erp.ui.pages.assets.assets_page import AssetsPage
from pars_erp.ui.pages.assets.categories_page import AssetCategoriesPage
from pars_erp.ui.pages.assets.depreciation_page import DepreciationPage
from pars_erp.ui.pages.assets.disposals_page import AssetDisposalsPage
from pars_erp.ui.pages.assets.reports_page import AssetReportsPage
from pars_erp.ui.pages.hr.attendance_page import AttendancePage
from pars_erp.ui.pages.hr.contracts_page import ContractsPage
from pars_erp.ui.pages.hr.employees_page import EmployeesPage
from pars_erp.ui.pages.hr.org_page import OrgStructurePage
from pars_erp.ui.pages.hr.reports_page import HRReportsPage
from pars_erp.ui.pages.hr.requests_page import LeaveMissionOvertimePage
from pars_erp.ui.pages.payroll.loans_page import LoansPage
from pars_erp.ui.pages.payroll.payments_page import PayrollPaymentsPage
from pars_erp.ui.pages.payroll.payslips_page import PayslipsPage
from pars_erp.ui.pages.payroll.reports_page import PayrollReportsPage
from pars_erp.ui.pages.payroll.runs_page import PayrollRunsPage
from pars_erp.ui.pages.payroll.settings_page import PayrollSettingsPage
from pars_erp.ui.pages.dashboard_page import DashboardPage
from pars_erp.ui.pages.roles_page import RolesPage
from pars_erp.ui.pages.settings_page import SettingsPage
from pars_erp.ui.pages.users_page import UsersPage
from pars_erp.ui.theme import apply_theme

NAV_ICON_DIR = Path(__file__).resolve().parent.parent / "resources" / "icons" / "nav"


def nav_icon(slug: str, *, muted: bool = False) -> QIcon:
    """Build a sidebar icon from the bundled SVG set (falls back to empty)."""
    state = "muted" if muted else "normal"
    icon = QIcon()
    for mode, suffix in ((QIcon.Mode.Normal, state),
                         (QIcon.Mode.Selected, "muted" if muted else "selected")):
        icon.addFile(str(NAV_ICON_DIR / f"{slug}_{suffix}.svg"), QSize(18, 18), mode)
    return icon


class MainWindow(QMainWindow):
    logoutRequested = Signal()
    exitRequested = Signal()

    def __init__(self, services: AppServices, ctx: SecurityContext) -> None:
        super().__init__()
        self.services = services
        self.ctx = ctx
        self._pages: dict[str, QWidget] = {}
        self._current_key: str | None = None
        self._last_activity = _dt.datetime.now()

        snapshot = services.settings.snapshot()
        self.formatter = Formatter(persian_digits=snapshot.persian_digits,
                                   currency_code=snapshot.currency_code)
        self.setWindowTitle(self._window_title())
        self.setMinimumSize(1180, 720)
        self.resize(1360, 840)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        self._build_ui()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self._install_idle_timer()
        QApplication.instance().installEventFilter(self)

        first = self._first_visible_key()
        if first:
            self.navigate(first)

    # ------------------------------------------------------------------- ui
    def _window_title(self) -> str:
        snapshot = self.services.settings.snapshot()
        company = snapshot.company_name
        base = snapshot.app_name
        return f"{base} — {company}" if company else base

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.top_bar = QFrame()
        self.top_bar.setObjectName("TopBar")
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(20, 10, 20, 10)
        top_layout.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        snapshot = self.services.settings.snapshot()
        self.page_title = QLabel(snapshot.company_name or snapshot.app_name)
        self.page_title.setObjectName("SectionTitle")
        self.page_subtitle = QLabel("")
        self.page_subtitle.setObjectName("HintText")
        title_box.addWidget(self.page_title)
        title_box.addWidget(self.page_subtitle)
        top_layout.addLayout(title_box)
        top_layout.addStretch(1)

        self.user_badge = QLabel("")
        self.user_badge.setObjectName("HintText")
        top_layout.addWidget(self.user_badge)

        self.theme_button = QPushButton("پوسته تاریک")
        self.theme_button.setProperty("variant", "ghost")
        self.theme_button.clicked.connect(self.toggle_theme)
        top_layout.addWidget(self.theme_button)

        self.lock_button = QPushButton("قفل نشست")
        self.lock_button.setProperty("variant", "ghost")
        self.lock_button.clicked.connect(self.lock_now)
        top_layout.addWidget(self.lock_button)

        self.password_button = QPushButton("تغییر رمز")
        self.password_button.setProperty("variant", "ghost")
        self.password_button.clicked.connect(self.change_password)
        top_layout.addWidget(self.password_button)

        self.logout_button = QPushButton("خروج")
        self.logout_button.setProperty("variant", "primary")
        self.logout_button.clicked.connect(self._confirm_logout)
        top_layout.addWidget(self.logout_button)
        right_layout.addWidget(self.top_bar)

        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)
        layout.addWidget(right, 1)
        self.setCentralWidget(central)

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(238)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 18, 12, 14)
        layout.setSpacing(10)

        brand_box = QVBoxLayout()
        brand_box.setSpacing(2)
        snapshot = self.services.settings.snapshot()
        title = QLabel(snapshot.app_name)
        title.setObjectName("BrandTitle")
        subtitle = QLabel(snapshot.company_name or "حسابداری و مدیریت کسب‌وکار")
        subtitle.setObjectName("BrandSubtitle")
        subtitle.setWordWrap(True)
        brand_box.addWidget(title)
        brand_box.addWidget(subtitle)
        layout.addLayout(brand_box)
        layout.addSpacing(6)

        self.nav = QListWidget()
        self.nav.setObjectName("NavList")
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav.itemClicked.connect(self._on_nav_clicked)
        self._groups: tuple[NavGroup, ...] = visible_items(self.ctx)
        from PySide6.QtGui import QBrush, QColor, QFont

        from pars_erp.ui.theme import palette_for

        muted_color = palette_for(snapshot.theme)["sidebar_muted"]
        for group in self._groups:
            header = QListWidgetItem(group.title_fa)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setData(Qt.ItemDataRole.UserRole, None)
            header.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            header_font = QFont()
            header_font.setPointSizeF(8.5)
            header.setFont(header_font)
            header.setForeground(QBrush(QColor(muted_color)))
            self.nav.addItem(header)
            for item in group.items:
                entry = QListWidgetItem(item.title_fa)
                entry.setData(Qt.ItemDataRole.UserRole, item.key)
                if item.is_placeholder:
                    entry.setFlags(Qt.ItemFlag.NoItemFlags)
                    entry.setIcon(nav_icon(item.icon, muted=True))
                    entry.setForeground(QBrush(QColor(muted_color)))
                    entry.setToolTip(
                        f"{item.title_fa} — در فاز "
                        f"{to_display_digits(str(item.planned_phase))} پیاده‌سازی می‌شود.")
                else:
                    entry.setIcon(nav_icon(item.icon))
                    entry.setToolTip(item.description_fa)
                self.nav.addItem(entry)
        layout.addWidget(self.nav, 1)

        version_label = QLabel(f"نسخه {__version__} — فاز {__phase__}")
        version_label.setObjectName("BrandSubtitle")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)
        return sidebar

    def _build_menus(self) -> None:
        menubar = self.menuBar()
        file_menu = menubar.addMenu("پرونده")
        refresh_action = QAction("بازخوانی صفحه", self)
        refresh_action.setShortcut(QKeySequence("F5"))
        refresh_action.triggered.connect(self.refresh_current_page)
        file_menu.addAction(refresh_action)
        file_menu.addSeparator()
        password_action = QAction("تغییر رمز عبور…", self)
        password_action.triggered.connect(self.change_password)
        file_menu.addAction(password_action)
        lock_action = QAction("قفل نشست", self)
        lock_action.setShortcut(QKeySequence("Ctrl+L"))
        lock_action.triggered.connect(self.lock_now)
        file_menu.addAction(lock_action)
        file_menu.addSeparator()
        logout_action = QAction("خروج از حساب", self)
        logout_action.triggered.connect(self._confirm_logout)
        file_menu.addAction(logout_action)
        exit_action = QAction("بستن برنامه", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = menubar.addMenu("نمایش")
        theme_action = QAction("تغییر پوسته روشن/تاریک", self)
        theme_action.triggered.connect(self.toggle_theme)
        view_menu.addAction(theme_action)
        settings_action = QAction("تنظیمات…", self)
        settings_action.triggered.connect(lambda: self.navigate("settings"))
        settings_action.setEnabled(self.ctx.has("settings.view"))
        view_menu.addAction(settings_action)

        for group in self._groups:
            menu = menubar.addMenu(group.title_fa)
            for item in group.items:
                action = QAction(item.title_fa, self)
                action.setEnabled(not item.is_placeholder)
                if item.is_placeholder:
                    action.setToolTip(f"در فاز {item.planned_phase} پیاده‌سازی می‌شود")
                action.triggered.connect(lambda _checked=False, key=item.key: self.navigate(key))
                menu.addAction(action)

        help_menu = menubar.addMenu("راهنما")
        about_action = QAction("درباره و اطلاعات نصب", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("نوار ابزار اصلی")
        toolbar.setMovable(False)
        toolbar.setIconSize(toolbar.iconSize())
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        refresh = QAction("↻  بازخوانی", self)
        refresh.triggered.connect(self.refresh_current_page)
        toolbar.addAction(refresh)
        toolbar.addSeparator()
        if self.ctx.has("users.create"):
            new_user = QAction("＋  کاربر جدید", self)
            new_user.triggered.connect(lambda: self._quick_action("users", "create"))
            toolbar.addAction(new_user)
        if self.ctx.has("backup.create"):
            backup = QAction("🗄  پشتیبان‌گیری سریع", self)
            backup.triggered.connect(self._quick_backup)
            toolbar.addAction(backup)
        toolbar.addSeparator()
        today = QAction("", self)
        snapshot = self.services.settings.snapshot()
        from pars_erp.core.jalali import JalaliDate
        today.setText(f"امروز: {JalaliDate.today().format(long=True)}")
        today.setEnabled(False)
        toolbar.addAction(today)
        self.toolbar = toolbar

    def _build_statusbar(self) -> None:
        bar = QStatusBar()
        self.setStatusBar(bar)
        self.status_user = QLabel("")
        self.status_db = QLabel("")
        self.status_clock = QLabel("")
        self.status_message = QLabel("")
        bar.addWidget(self.status_user)
        bar.addWidget(self._separator_label())
        bar.addWidget(self.status_db)
        bar.addPermanentWidget(self.status_message)
        bar.addPermanentWidget(self._separator_label())
        bar.addPermanentWidget(self.status_clock)
        self._update_status()
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(20_000)
        self._clock_timer.timeout.connect(self._update_status)
        self._clock_timer.start()

    @staticmethod
    def _separator_label() -> QLabel:
        label = QLabel("│")
        label.setStyleSheet("color: #b6bfcd;")
        return label

    def _update_status(self) -> None:
        self.status_user.setText(
            f"کاربر: {self.ctx.full_name} ({self.ctx.username}) — نقش: {self._role_titles()}")
        self.status_db.setText(
            f"پایگاه داده: {self.services.db.dialect_name()} — ساختار: "
            f"{self.services.db.schema_revision() or '—'}")
        now = _dt.datetime.now()
        from pars_erp.core.digits import to_persian_digits
        from pars_erp.core.jalali import JalaliDate
        jalali = JalaliDate.from_gregorian(now.date())
        clock = to_persian_digits(now.strftime("%H:%M")) if self.formatter.persian_digits \
            else now.strftime("%H:%M")
        self.status_clock.setText(
            f"{jalali.format(persian_digits=self.formatter.persian_digits)} — {clock}")

    # -------------------------------------------------------------- navigation
    def _first_visible_key(self) -> str | None:
        for group in self._groups:
            for item in group.items:
                if not item.is_placeholder:
                    return item.key
        return None

    def _on_nav_clicked(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        if key:
            self.navigate(str(key))

    def available_keys(self) -> list[str]:
        return [item.key for group in self._groups for item in group.items
                if not item.is_placeholder]

    def navigate(self, key: str) -> None:
        page = self._pages.get(key)
        if page is None:
            page = self._create_page(key)
            if page is None:
                return
            self._pages[key] = page
            self.stack.addWidget(page)
        self._current_key = key
        self.stack.setCurrentWidget(page)
        self._select_nav(key)
        now = _dt.datetime.now()
        from pars_erp.core.jalali import JalaliDate
        self.page_subtitle.setText(
            f"{self._title_for(key)} — امروز {JalaliDate.from_gregorian(now.date()).format(long=True)}")
        self.refresh_current_page()

    def _role_titles(self) -> str:
        try:
            mapping = dict(self.services.roles.role_choices())
            return "، ".join(mapping.get(code, code) for code in self.ctx.role_codes) or "—"
        except Exception:
            return "، ".join(self.ctx.role_codes) or "—"

    def _title_for(self, key: str) -> str:
        for group in self._groups:
            for item in group.items:
                if item.key == key:
                    return item.title_fa
        return key

    def _select_nav(self, key: str) -> None:
        for index in range(self.nav.count()):
            item = self.nav.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == key:
                self.nav.setCurrentItem(item)
                return

    def _create_page(self, key: str) -> QWidget | None:
        common = dict(services=self.services, ctx=self.ctx, formatter=self.formatter)
        if key == "dashboard":
            return DashboardPage(on_navigate=self.navigate, **common)
        if key == "acc_dashboard":
            return AccountingDashboardPage(on_navigate=self.navigate, **common)
        if key == "accounts":
            page = AccountsPage(**common)
        elif key == "journals":
            page = JournalsPage(**common)
        elif key == "acc_periods":
            page = PeriodsPage(**common)
        elif key == "acc_dimensions":
            page = DimensionsPage(**common)
        elif key == "acc_currencies":
            page = CurrenciesPage(**common)
        elif key == "acc_settings":
            page = AccountingSettingsPage(**common)
            page.settingsSaved.connect(self._on_settings_saved)
        elif key == "journal_book":
            page = JournalBookPage(**common)
        elif key == "general_ledger":
            page = GeneralLedgerPage(**common)
        elif key == "subsidiary_ledger":
            page = SubsidiaryLedgerPage(**common)
        elif key == "turnover":
            page = TurnoverPage(**common)
        elif key == "trial_balance":
            page = TrialBalancePage(**common)
        elif key == "balance_sheet":
            page = BalanceSheetPage(**common)
        elif key == "income_statement":
            page = IncomeStatementPage(**common)
        elif key == "products":
            page = ProductsPage(**common)
        elif key == "persons":
            page = PersonsPage(**common)
        elif key == "inventory":
            page = InventoryPage(**common)
        elif key == "purchase_invoices":
            page = InvoicesPage(family="purchase", **common)
        elif key == "sales_invoices":
            page = InvoicesPage(family="sales", **common)
        elif key == "purchase_orders":
            page = OrdersPage(family="purchase", **common)
        elif key == "sales_orders":
            page = OrdersPage(family="sales", **common)
        elif key == "pricing":
            page = PricingPage(**common)
        elif key == "commerce_reports":
            page = CommerceReportsPage(**common)
        elif key == "commerce_settings":
            page = CommerceSettingsPage(**common)
        elif key == "treasury_dashboard":
            page = TreasuryDashboardPage(**common)
        elif key == "receipt_cash":
            page = VouchersPage(**common, family="receipt")
        elif key == "payment_cash":
            page = VouchersPage(**common, family="payment")
        elif key == "receipt_customer":
            page = VouchersPage(**common, family="receipt", default_type="customer")
        elif key == "payment_supplier":
            page = VouchersPage(**common, family="payment", default_type="supplier")
        elif key == "cheque_received":
            page = ReceivedChequesPage(**common)
        elif key == "cheque_issued":
            page = IssuedChequesPage(**common)
        elif key == "cash_boxes":
            page = CashBoxesPage(**common)
        elif key == "bank_accounts":
            page = BankAccountsPage(**common)
        elif key == "treasury_transfer":
            page = TransfersPage(**common)
        elif key == "cheque_books":
            page = ChequeBooksPage(**common)
        elif key == "cheque_manage":
            page = ChequeManagePage(**common)
        elif key == "receivables":
            page = ReceivableDocumentsPage(**common)
        elif key == "payables":
            page = PayableDocumentsPage(**common)
        elif key == "reconciliation":
            page = ReconciliationPage(**common)
        elif key == "settlements":
            page = SettlementsPage(**common)
        elif key == "fund_flow":
            page = FundFlowPage(**common)
        elif key == "treasury_reports":
            page = TreasuryReportsPage(**common)
        elif key == "hr_employees":
            page = EmployeesPage(**common)
        elif key == "hr_org":
            page = OrgStructurePage(**common)
        elif key == "hr_contracts":
            page = ContractsPage(**common)
        elif key == "hr_attendance":
            page = AttendancePage(**common)
        elif key == "hr_leave":
            page = LeaveMissionOvertimePage(**common)
        elif key == "hr_reports":
            page = HRReportsPage(**common)
        elif key == "payroll_settings":
            page = PayrollSettingsPage(**common)
        elif key == "payroll_runs":
            page = PayrollRunsPage(**common)
        elif key == "payroll_payslips":
            page = PayslipsPage(**common)
        elif key == "payroll_payments":
            page = PayrollPaymentsPage(**common)
        elif key == "payroll_loans":
            page = LoansPage(**common)
        elif key == "payroll_reports":
            page = PayrollReportsPage(**common)
        elif key == "assets_categories":
            page = AssetCategoriesPage(**common)
        elif key == "assets_register":
            page = AssetsPage(**common)
        elif key == "assets_depreciation":
            page = DepreciationPage(**common)
        elif key == "assets_disposals":
            page = AssetDisposalsPage(**common)
        elif key == "asset_reports":
            page = AssetReportsPage(**common)
        elif key == "treasury_settings":
            page = TreasurySettingsPage(**common)
        elif key == "users":
            page = UsersPage(**common)
        elif key == "roles":
            page = RolesPage(**common)
        elif key == "audit":
            page = AuditPage(**common)
        elif key == "settings":
            page = SettingsPage(**common)
            page.settingsSaved.connect(self._on_settings_saved)
        elif key == "backup":
            page = BackupPage(on_restored=self._on_restored, **common)
        else:
            return None
        if hasattr(page, "statusMessage"):
            page.statusMessage.connect(self.show_status)
        return page

    def refresh_current_page(self) -> None:
        page = self.stack.currentWidget()
        if page is not None and hasattr(page, "refresh"):
            self.page_subtitle.setText("")
            # every page re-checks its permissions after a role/context change
            if hasattr(page, "update_context"):
                page.update_context(self.ctx)
            if hasattr(page, "update_formatter"):
                page.update_formatter(self.formatter)
            try:
                page.refresh()
            except AppError as exc:
                show_error(self, "خطا در بازخوانی اطلاعات", exc)

    def show_status(self, message: str) -> None:
        self.status_message.setText(message)
        self.statusBar().showMessage(message, 6000)

    # ------------------------------------------------------------------ actions
    def _quick_action(self, page_key: str, action: str) -> None:
        self.navigate(page_key)
        page = self._pages.get(page_key)
        if page is not None and hasattr(page, "_create_user"):
            page._create_user()

    def _quick_backup(self) -> None:
        try:
            info = self.services.backups.create_backup(self.ctx, note="پشتیبان سریع")
        except AppError as exc:
            show_error(self, "پشتیبان‌گیری ناموفق", exc)
            return
        self.show_status(f"پشتیبان «{info.filename}» با موفقیت ایجاد شد.")
        page = self._pages.get("backup")
        if page is not None:
            page.refresh()

    def change_password(self) -> None:
        dialog = ChangePasswordDialog(self, self.services, self.ctx)
        if dialog.exec():
            self.ctx = self.services.auth.reload_context(self.ctx)
            show_info(self, "رمز عبور تغییر کرد",
                      "رمز عبور شما با موفقیت تغییر کرد. سایر نشست‌های فعال بسته شدند.")
            self._apply_context()

    def _confirm_logout(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        answer = QMessageBox.question(
            self, "خروج از حساب",
            "از حساب کاربری خارج می‌شوید؟",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.logoutRequested.emit()

    def toggle_theme(self) -> None:
        snapshot = self.services.settings.snapshot()
        new_theme = "dark" if snapshot.theme == "light" else "light"
        if not self.ctx.has("settings.edit"):
            # A user without settings permission still expects the theme toggle to work
            # for their session; it is stored as a preference for the current session.
            self._session_theme = new_theme
            self._apply_theme(new_theme)
            self.show_status("پوسته تغییر کرد (برای این نشست).")
            return
        try:
            self.services.settings.update(self.ctx, {"theme": new_theme})
        except AppError as exc:
            show_error(self, "تغییر پوسته ممکن نیست", exc)
            return
        self._apply_theme(new_theme)
        self.show_status("پوسته برنامه تغییر کرد.")

    def _apply_theme(self, theme: str) -> None:
        from pars_erp.services.settings_service import SettingsSnapshot
        snapshot = self.services.settings.snapshot()
        themed = SettingsSnapshot({**snapshot.values, "theme": theme})
        apply_theme(QApplication.instance(), themed)
        self.theme_button.setText("پوسته روشن" if theme == "dark" else "پوسته تاریک")
        page = self._pages.get("dashboard")
        if page is not None:
            page.refresh()

    def _on_settings_saved(self) -> None:
        snapshot = self.services.settings.snapshot()
        self.formatter = Formatter(persian_digits=snapshot.persian_digits,
                                   currency_code=snapshot.currency_code)
        apply_theme(QApplication.instance(), snapshot)
        self.setWindowTitle(self._window_title())
        self.theme_button.setText("پوسته روشن" if snapshot.theme == "dark" else "پوسته تاریک")
        for page in self._pages.values():
            if hasattr(page, "update_formatter"):
                page.update_formatter(self.formatter)
            if hasattr(page, "update_context"):
                page.update_context(self.ctx)
        self.show_status("تنظیمات ذخیره و اعمال شد.")
        self.refresh_current_page()

    def _on_restored(self) -> None:
        """After a database restore every cached context must be re-read."""
        try:
            self.services.db.dispose()
            self.services.db.migrate()
            self.ctx = self.services.auth.reload_context(self.ctx)
        except AppError as exc:
            show_error(self, "بازخوانی پس از بازیابی", exc)
            return
        self._apply_context()
        self.show_status("پایگاه داده بازیابی شد و نشست بازخوانی شد.")

    def _apply_context(self) -> None:
        for page in self._pages.values():
            if hasattr(page, "update_context"):
                page.update_context(self.ctx)
        self.user_badge.setText(f"{self.ctx.full_name} — {self.ctx.username}")
        self._update_status()
        self.refresh_current_page()

    def _show_about(self) -> None:
        snapshot = self.services.settings.snapshot()
        info = self.services.auth.setup_status()
        details = "\n".join([
            f"برنامه: {snapshot.app_name}",
            f"نسخه: {__version__}",
            f"شرکت: {snapshot.company_name or '—'}",
            f"پایگاه داده: {self.services.db.dialect_name()}",
            f"ساختار: {self.services.db.schema_revision() or '—'}",
            f"مسیر داده: {self.services.paths.home}",
            f"کاربران: {info.user_count}",
            f"رایانه: {self.services.hostname}",
            "قلم: Vazirmatn (SIL Open Font License)",
        ])
        show_info(self, "درباره برنامه",
                  f"{snapshot.app_name} — نرم‌افزار جامع حسابداری و مدیریت کسب‌وکار",
                  details=details)

    # -------------------------------------------------------------- idle lock
    def _install_idle_timer(self) -> None:
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(10_000)
        self._idle_timer.timeout.connect(self._check_idle)
        self._idle_timer.start()
        self._locked = False

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress,
                            QEvent.Type.MouseMove, QEvent.Type.Wheel,
                            QEvent.Type.TouchBegin):
            self._last_activity = _dt.datetime.now()
        return super().eventFilter(watched, event)

    def _idle_minutes(self) -> int:
        return max(1, self.services.settings.snapshot().idle_lock_minutes)

    def _check_idle(self) -> None:
        if self._locked or not self.isActiveWindow():
            return
        if QApplication.activeModalWidget() is not None:
            return
        idle_seconds = (_dt.datetime.now() - self._last_activity).total_seconds()
        if idle_seconds >= self._idle_minutes() * 60:
            self.lock_now(reason="idle")

    def lock_now(self, reason: str = "manual") -> None:
        if self._locked:
            return
        self._locked = True
        try:
            self.services.auth.lock_session(self.ctx, reason=reason)
        except AppError:
            pass
        dialog = LockScreenDialog(self, self.services, self.ctx, formatter=self.formatter)
        accepted = dialog.exec()
        self._locked = False
        self._last_activity = _dt.datetime.now()
        if not accepted:
            self.logoutRequested.emit()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        try:
            self.services.auth.logout(self.ctx, reason="window_closed")
        except AppError:
            pass
        self.exitRequested.emit()
        super().closeEvent(event)
