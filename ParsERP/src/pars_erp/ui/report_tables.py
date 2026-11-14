"""Backward-compatible import path for the shared report table builders.

Phase 7 moved the (Qt-free) builders into :mod:`pars_erp.reporting.accounting_tables`
so the reporting engine can use them without importing the UI package. Existing
imports keep working through this shim.
"""

from pars_erp.reporting.accounting_tables import *  # noqa: F401,F403
from pars_erp.reporting.accounting_tables import (  # noqa: F401
    balance_sheet_table,
    general_ledger_table,
    income_statement_table,
    journal_book_table,
    report_meta,
    statement_table,
    subsidiary_ledger_table,
    trial_balance_table,
    turnover_table,
)
