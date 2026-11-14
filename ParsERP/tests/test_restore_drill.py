"""A real backup → damage → restore drill on a throw-away database.

The drill is deliberately harsher than the ordinary backup tests: it records the
business figures *before* the backup (journal lines, their debit/credit totals,
stock balances, user count), damages the live database in several independent
ways (wipes the journal, adds and then deactivates a user, removes stock), then
restores the backup and proves that the restored database holds exactly the
pre-backup figures, that the ledger is still balanced and that the schema is
current.  Everything runs against the temporary SQLite file created by the
``services`` fixture - no user database is ever touched.
"""

from __future__ import annotations

import datetime as _dt
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from pars_erp.core.errors import RestoreError
from pars_erp.db.models import User
from pars_erp.db.models.accounting import JournalLine
from pars_erp.db.models.commerce import StockBalance
from pars_erp.services.backup_service import BACKUP_PREFIX


# ------------------------------------------------------------------ helpers
def _stock_in(services, admin, commerce, *, quantity: str = "10") -> str:
    from pars_erp.services.invoice_service import InvoiceInput, InvoiceLineInput

    invoice = services.invoices.create(admin, InvoiceInput(
        kind="purchase", invoice_date=_dt.date.today(),
        party_detail_id=commerce.supplier.id, warehouse_id=commerce.warehouse.id,
        lines=[InvoiceLineInput(product_id=commerce.product.id,
                                quantity=Decimal(quantity), unit_price=Decimal("1000"))]))
    services.invoices.post(admin, invoice.id)
    return services.invoices.get(admin, invoice.id)


def _sell(services, admin, commerce, *, amount: str = "1000000") -> str:
    from pars_erp.services.invoice_service import InvoiceInput, InvoiceLineInput

    invoice = services.invoices.create(admin, InvoiceInput(
        kind="sale", invoice_date=_dt.date.today(),
        party_detail_id=commerce.customer.id, warehouse_id=commerce.warehouse.id,
        lines=[InvoiceLineInput(product_id=commerce.product.id, quantity=Decimal("1"),
                                unit_price=Decimal(amount))]))
    services.invoices.post(admin, invoice.id)
    return services.invoices.get(admin, invoice.id)


def _snapshot(services) -> dict[str, object]:
    with services.db.session_scope() as session:
        lines = int(session.execute(select(func.count()).select_from(JournalLine)).scalar_one())
        debit, credit = session.execute(
            select(func.coalesce(func.sum(JournalLine.debit), 0),
                   func.coalesce(func.sum(JournalLine.credit), 0))).one()
        users = int(session.execute(select(func.count()).select_from(User)).scalar_one())
        stock_rows = int(session.execute(select(func.count()).select_from(StockBalance)).scalar_one())
        stock_qty = session.execute(
            select(func.coalesce(func.sum(StockBalance.quantity), 0))).scalar_one()
    return {"journal_lines": lines, "debit": Decimal(debit), "credit": Decimal(credit),
            "users": users, "stock_rows": stock_rows, "stock_qty": Decimal(stock_qty)}


def _new_user(services, admin, username: str):
    from pars_erp.services.user_service import UserCreateData

    return services.users.create_user(admin, UserCreateData(
        username=username, full_name="کاربر آزمون بازیابی",
        password="DrillPass1234", confirm_password="DrillPass1234",
        role_codes=("viewer",)))


# -------------------------------------------------------------------- drill
class TestRestoreDrill:
    def test_drill_restores_the_exact_business_state(self, services, admin, chart,
                                                     commerce) -> None:
        # 1) real, posted documents: stock in, then a sale on that stock
        _stock_in(services, admin, commerce)
        sale_code = _sell(services, admin, commerce)
        before = _snapshot(services)
        assert before["journal_lines"] > 0
        assert before["debit"] == before["credit"]
        assert before["stock_qty"] == Decimal("9")

        # 2) a verified backup
        info = services.backups.create_backup(admin, note="drill")
        assert info.filename.startswith(BACKUP_PREFIX) and info.path.exists()
        verification = services.backups.verify_backup(info.path, ctx=admin)
        assert verification.ok is True, verification.message_fa

        # 3) damage the live database in three independent ways
        with services.db.session_scope() as session:
            session.query(JournalLine).delete()
        with services.db.session_scope() as session:
            session.query(StockBalance).delete()
        _new_user(services, admin, "drilluser")
        row = services.users.list_users(admin, search="drilluser").items[0]
        services.users.set_active(admin, row.id, False)

        damaged = _snapshot(services)
        assert damaged["journal_lines"] == 0
        assert damaged["stock_rows"] == 0
        assert damaged["users"] == before["users"] + 1

        # 4) restore, which must take its own safety backup first
        result = services.backups.restore_backup(admin, info.path, confirm_phrase="بازیابی")
        assert result.ok is True
        assert result.safety_backup is not None and result.safety_backup.exists()

        # 5) every figure is back, and the ledger is still balanced
        after = _snapshot(services)
        assert after == before
        assert after["debit"] == after["credit"]

        # 6) the restored database is healthy and on the current schema
        assert services.db.ping() is True
        assert services.db.schema_revision() is not None
        assert services.auth.authenticate("admin", "ModirPass1234").username == "admin"

        # 7) the post-backup damage is gone, and the sale is queryable again
        assert services.users.list_users(admin, search="drilluser").total == 0
        assert any(row.kind == "sale" for row in services.invoices.list(admin))
        assert sale_code is not None

    def test_a_truncated_backup_is_refused_and_never_called_healthy(
            self, services, admin, tmp_path: Path) -> None:
        info = services.backups.create_backup(admin, note="truncate")
        payload = info.path.read_bytes()
        broken = tmp_path / "truncated.zip"
        broken.write_bytes(payload[: max(128, len(payload) // 2)])
        verification = services.backups.verify_backup(broken, ctx=admin)
        assert verification.ok is False
        assert verification.message_fa
        with pytest.raises(RestoreError):
            services.backups.restore_backup(admin, broken, confirm_phrase="بازیابی")
        assert services.db.ping() is True

    def test_an_archive_without_the_manifest_is_refused(self, services, admin,
                                                        tmp_path: Path) -> None:
        info = services.backups.create_backup(admin, note="no-manifest")
        stripped = tmp_path / "no-manifest.zip"
        with zipfile.ZipFile(info.path) as source, zipfile.ZipFile(stripped, "w") as target:
            for name in source.namelist():
                if name.endswith("manifest.json"):
                    continue
                target.writestr(name, source.read(name))
        assert services.backups.verify_backup(stripped, ctx=admin).ok is False
        with pytest.raises(RestoreError):
            services.backups.restore_backup(admin, stripped, confirm_phrase="بازیابی")


def _report_figures(services, admin) -> dict:
    """The numbers a manager would look at, read from the reports."""
    period = services.periods.list_periods(admin)[0]
    trial = services.reports.trial_balance(
        admin, date_from=period.start_date, date_to=period.end_date)
    income = services.reports.income_statement(
        admin, date_from=period.start_date, date_to=period.end_date)
    balance = services.reports.balance_sheet(admin, as_of=period.end_date)
    return {
        "period_debit": trial.totals["period_debit"],
        "period_credit": trial.totals["period_credit"],
        "profit": dict(income.summary)["سود (زیان) دوره"],
        "assets": dict(balance.summary)["جمع دارایی‌ها"],
        "difference": dict(balance.summary)["اختلاف"],
    }


class TestRestoreKeepsTheReportedFigures:
    def test_trial_balance_and_statements_are_identical_after_a_restore(
            self, services, admin, chart, commerce) -> None:
        _stock_in(services, admin, commerce)
        _sell(services, admin, commerce)
        before = _report_figures(services, admin)
        assert before["period_debit"] == before["period_credit"]
        assert before["difference"] == 0

        info = services.backups.create_backup(admin, note="report-drill")
        _sell(services, admin, commerce)          # a document the backup cannot know
        assert _report_figures(services, admin) != before

        result = services.backups.restore_backup(admin, info.path,
                                                 confirm_phrase="بازیابی")
        assert result.ok is True
        after = _report_figures(services, admin)
        assert after == before, "the reports must be identical after a restore"

    def test_a_backup_file_is_not_world_readable(self, services, admin) -> None:
        import stat

        info = services.backups.create_backup(admin, note="permissions")
        mode = stat.S_IMODE(info.path.stat().st_mode)
        assert mode & 0o077 == 0, f"backup is readable by others (mode {oct(mode)})"

    def test_a_backup_holds_hashes_not_plaintext_passwords(self, services, admin,
                                                          tmp_path: Path) -> None:
        import json

        info = services.backups.create_backup(admin, note="secrets")
        with zipfile.ZipFile(info.path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            name = next(n for n in archive.namelist() if n.startswith("database/"))
            archive.extract(name, tmp_path)
        payload = (tmp_path / name).read_bytes()
        assert b"ModirPass1234" not in payload, "a plaintext password leaked into the backup"
        assert payload.startswith(b"SQLite format 3"), "the archive must hold a real database"
        assert manifest["database_sha256"]
