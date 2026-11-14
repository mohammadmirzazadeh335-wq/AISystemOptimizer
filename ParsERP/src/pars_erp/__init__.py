"""زرین هرمز (Zarrin Hormoz) - Persian corporate accounting and ERP suite.

Phase 1 delivered the application core: architecture, database, security,
users/roles/permissions, settings, audit trail, dashboard and backup/restore.
Phase 2 adds the financial accounting core: chart of accounts, journal entries,
general/subsidiary ledgers, trial balance, financial statements, fiscal periods
and reporting dimensions.
Phase 3 adds the commerce core: catalogue, warehouses, stock movements,
purchase and sale invoices.
Phase 4 adds the treasury core: bank accounts, cash boxes, receipts, payments,
transfers, cheque lifecycle, bank reconciliation, settlements and treasury
reporting.
Phase 7 adds the reporting engine, the report designer, management
dashboards and alerts, report exports, and the controlled update/install path.
Phase 5 added human resources, attendance/leave, a versioned payroll engine,
employee loans and advances, payroll payment batches, fixed assets and
depreciation - wired into the phase 2-4 accounting, commerce and treasury layers.

The Python package keeps the historical ``pars_erp`` name: it is an internal
identifier (imports, database file name, entry point) and renaming it would break
existing installations, while every *user visible* string uses the official
brand below.
"""

from __future__ import annotations

APP_NAME_DEFAULT = "زرین هرمز"
APP_NAME_EN = "Zarrin Hormoz"
__version__ = "0.7.0"
__phase__ = 7

__all__ = ["APP_NAME_DEFAULT", "APP_NAME_EN", "__version__", "__phase__"]
