"""Composition root: builds every service with its dependencies.

The UI receives an :class:`AppServices` instance and never constructs
repositories or sessions itself, which keeps responsibilities clean and makes
the whole application testable with an in-memory/temporary database.
"""

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass, field

from pars_erp import __version__
from pars_erp.config.paths import AppPaths
from pars_erp.config.settings import FileConfig, load_config
from pars_erp.db.session import Database, mask_database_url
from pars_erp.security.passwords import Argon2PasswordHasher
from pars_erp.services.accounting_setup_service import AccountingSetupService
from pars_erp.services.asset_report_service import AssetReportService
from pars_erp.services.assets_service import AssetService
from pars_erp.services.attendance_service import AttendanceService
from pars_erp.services.depreciation_service import DepreciationService
from pars_erp.services.hr_report_service import HRReportService
from pars_erp.services.hr_service import HRService
from pars_erp.services.loans_service import LoanService
from pars_erp.services.payroll_payment_service import PayrollPaymentService
from pars_erp.services.payroll_report_service import PayrollReportService
from pars_erp.services.payroll_service import PayrollService
from pars_erp.services.accounts_service import AccountService
from pars_erp.services.audit_service import AuditService
from pars_erp.services.auth_service import AuthService
from pars_erp.services.backup_service import BackupService
from pars_erp.services.bootstrap_service import BootstrapResult, ensure_reference_data
from pars_erp.services.catalogue_service import CatalogueService
from pars_erp.services.cheque_service import ChequeService
from pars_erp.services.commerce_reports_service import CommerceReportService
from pars_erp.services.dashboard_service import DashboardService
from pars_erp.services.dimensions_service import CurrencyService, DimensionService
from pars_erp.services.export_service import ExportService
from pars_erp.services.inventory_service import InventoryService
from pars_erp.services.invoice_service import InvoiceService
from pars_erp.services.journals_service import JournalService
from pars_erp.services.ledger_service import LedgerService
from pars_erp.services.order_service import OrderService
from pars_erp.services.parties_service import PartyService
from pars_erp.services.persons_service import PersonService
from pars_erp.services.posting_service import PostingService
from pars_erp.services.funds_service import FundsService
from pars_erp.services.pricing_service import PricingService
from pars_erp.services.periods_service import PeriodService
from pars_erp.services.alert_service import AlertService
from pars_erp.services.update_service import UpdateService
from pars_erp.services.management_dashboard_service import ManagementDashboardService
from pars_erp.services.report_engine_service import ReportEngineService
from pars_erp.services.reconciliation_service import ReconciliationService
from pars_erp.services.reports_service import ReportsService
from pars_erp.services.role_service import RoleService
from pars_erp.services.settings_service import SettingsService
from pars_erp.services.treasury_dashboard_service import TreasuryDashboardService
from pars_erp.services.treasury_reports_service import TreasuryReportService
from pars_erp.services.user_service import UserService
from pars_erp.services.voucher_service import VoucherService

logger = logging.getLogger(__name__)


@dataclass
class AppServices:
    paths: AppPaths
    config: FileConfig
    db: Database
    audit: AuditService
    settings: SettingsService
    auth: AuthService
    users: UserService
    roles: RoleService
    backups: BackupService
    dashboard: DashboardService
    exporter: ExportService
    # ------------------------------------------------------------- accounting
    accounts: AccountService
    parties: PartyService
    periods: PeriodService
    journals: JournalService
    ledger: LedgerService
    reports: ReportsService
    dimensions: DimensionService
    currency: CurrencyService
    accounting: AccountingSetupService
    # --------------------------------------------------------------- commerce
    catalogue: CatalogueService
    persons: PersonService
    inventory: InventoryService
    pricing: PricingService
    posting: PostingService
    invoices: InvoiceService
    orders: OrderService
    commerce_reports: CommerceReportService
    # --------------------------------------------------------------- treasury
    funds: FundsService
    cheques: ChequeService
    vouchers: VoucherService
    reconciliation: ReconciliationService
    treasury_reports: TreasuryReportService
    treasury_dashboard: TreasuryDashboardService
    # -------------------------------------------------------------------- hr
    hr: HRService
    attendance: AttendanceService
    payroll: PayrollService
    loans: LoanService
    payroll_payments: PayrollPaymentService
    hr_reports: HRReportService
    payroll_reports: PayrollReportService
    # ------------------------------------------------------------------ assets
    assets: AssetService
    depreciation: DepreciationService
    asset_reports: AssetReportService
    report_engine: ReportEngineService
    alerts: AlertService
    management_dashboard: ManagementDashboardService
    updates: UpdateService
    hasher: Argon2PasswordHasher
    hostname: str = field(default=platform.node() or "unknown-host")
    app_version: str = __version__

    def dispose(self) -> None:
        self.db.dispose()


def build_services(*, paths: AppPaths | None = None, config: FileConfig | None = None,
                   db: Database | None = None, hasher: Argon2PasswordHasher | None = None,
                   hostname: str | None = None) -> AppServices:
    paths = (paths or AppPaths.default()).ensure()
    config = config or load_config(paths)
    database = db or Database(config.database_url, echo=config.echo_sql)
    hasher = hasher or Argon2PasswordHasher()
    host = hostname or platform.node() or "unknown-host"

    audit = AuditService(database, hostname=host)
    settings = SettingsService(database, audit)
    auth = AuthService(database, settings, audit, hasher=hasher, hostname=host)
    users = UserService(database, settings, audit, hasher=hasher)
    roles = RoleService(database, audit)
    backups = BackupService(database, paths, audit)
    dashboard = DashboardService(database, settings, audit, backups)
    exporter = ExportService(users, audit, paths)

    accounts = AccountService(database, settings, audit)
    parties = PartyService(database, audit)
    periods = PeriodService(database, audit, settings)
    journals = JournalService(database, audit, settings)
    ledger = LedgerService(database)
    reports = ReportsService(database, ledger)
    dimensions = DimensionService(database, audit)
    currency = CurrencyService(database, audit, settings)
    accounting = AccountingSetupService(database, audit, accounts, periods, settings)

    catalogue = CatalogueService(database, audit)
    persons = PersonService(database, audit)
    inventory = InventoryService(database, audit, settings)
    pricing = PricingService(database, audit)
    posting = PostingService(database, audit)
    invoices = InvoiceService(database, audit, inventory=inventory, journals=journals,
                              settings=settings, pricing=pricing)
    orders = OrderService(database, audit)
    commerce_reports = CommerceReportService(database)

    funds = FundsService(database, audit)
    cheques = ChequeService(database, audit, journals=journals, settings=settings)
    vouchers = VoucherService(database, audit, journals=journals, inventory=inventory,
                              cheques=cheques, settings=settings)
    reconciliation = ReconciliationService(database, audit, journals=journals)
    treasury_reports = TreasuryReportService(database, settings)
    treasury_dashboard = TreasuryDashboardService(database, treasury_reports)

    hr = HRService(database, audit, settings=settings)
    attendance = AttendanceService(database, audit, settings=settings)
    payroll = PayrollService(database, audit, journals=journals, posting=posting,
                             settings=settings, attendance=attendance)
    loans = LoanService(database, audit, vouchers=vouchers, journals=journals)
    payroll_payments = PayrollPaymentService(database, audit, vouchers=vouchers,
                                             settings=settings)
    hr_reports = HRReportService(database, settings)
    payroll_reports = PayrollReportService(database, settings)

    assets = AssetService(database, audit, vouchers=vouchers, journals=journals,
                          settings=settings)
    depreciation = DepreciationService(database, audit, journals=journals,
                                       settings=settings)
    asset_reports = AssetReportService(database, settings)

    from pars_erp.services.alert_service import AlertService
    from pars_erp.services.management_dashboard_service import ManagementDashboardService

    alerts = AlertService(database, audit, backups=backups,
                          treasury_reports=treasury_reports,
                          commerce_reports=commerce_reports)
    management_dashboard = ManagementDashboardService(
        database, settings, treasury_reports=treasury_reports,
        commerce_reports=commerce_reports, hr_reports=hr_reports,
        payroll_reports=payroll_reports, asset_reports=asset_reports,
        reports=reports, alerts=alerts)

    # The report catalogue needs the report services (not the whole AppServices
    # object), so it is built from a small namespace and injected here.
    from types import SimpleNamespace

    from pars_erp.reporting.catalogue import build_catalogue
    from pars_erp.services.report_engine_service import ReportEngineService

    report_engine = ReportEngineService(database, settings, audit, build_catalogue(
        SimpleNamespace(settings=settings, ledger=ledger, reports=reports,
                        commerce_reports=commerce_reports,
                        treasury_reports=treasury_reports, hr_reports=hr_reports,
                        payroll_reports=payroll_reports,
                        asset_reports=asset_reports)))

    updates = UpdateService(database, settings, audit, backups, paths)

    return AppServices(
        paths=paths, config=config, db=database, audit=audit, settings=settings,
        auth=auth, users=users, roles=roles, backups=backups, dashboard=dashboard,
        exporter=exporter, hasher=hasher, hostname=host,
        accounts=accounts, parties=parties, periods=periods, journals=journals,
        ledger=ledger, reports=reports, dimensions=dimensions, currency=currency,
        accounting=accounting,
        catalogue=catalogue, persons=persons, inventory=inventory, pricing=pricing,
        posting=posting, invoices=invoices, orders=orders,
        commerce_reports=commerce_reports,
        funds=funds, cheques=cheques, vouchers=vouchers,
        reconciliation=reconciliation, treasury_reports=treasury_reports,
        treasury_dashboard=treasury_dashboard,
        hr=hr, attendance=attendance, payroll=payroll, loans=loans,
        payroll_payments=payroll_payments, hr_reports=hr_reports,
        payroll_reports=payroll_reports,
        assets=assets, depreciation=depreciation, asset_reports=asset_reports,
        report_engine=report_engine, alerts=alerts,
        management_dashboard=management_dashboard,
        updates=updates,
    )


def prepare_application(services: AppServices, *, run_startup_backup: bool = True) -> BootstrapResult:
    """Migrate, seed reference data and record the application start."""
    logger.info("preparing database at %s", mask_database_url(services.db.url))
    revision = services.db.migrate()
    logger.info("schema revision: %s", revision)
    result = ensure_reference_data(services.db)
    if run_startup_backup:
        snapshot = services.settings.snapshot()
        if snapshot.bool("auto_backup_on_startup") and services.auth.setup_status().user_count > 0:
            try:
                info = services.backups.startup_backup_if_due(
                    interval_hours=snapshot.int("backup_interval_hours"))
                if info is not None:
                    logger.info("startup backup created: %s", info.filename)
                    services.backups.prune(None, keep=snapshot.backup_retention)
            except Exception:  # a failed automatic backup must not block startup
                logger.exception("startup backup failed")
    services.audit.log_security(
        event_type="app.started",
        message_fa=f"برنامه {services.settings.snapshot().app_name} اجرا شد.",
        details={"app_version": services.app_version, "schema_revision": revision,
                 "hostname": services.hostname})
    return result
