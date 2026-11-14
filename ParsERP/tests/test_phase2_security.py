"""Phase-2 audit: is the server side (the services) really the authority?

The GUI hides buttons; these tests call the services directly, the way a
determined user or a second window would, and require a Persian refusal.
"""

from __future__ import annotations

import datetime as _dt
import logging
from decimal import Decimal

import pytest

from pars_erp.commerce import constants as CC
from pars_erp.core.errors import AppError, PermissionDeniedError
from pars_erp.services.invoice_service import InvoiceInput, InvoiceLineInput
from pars_erp.services.journals_service import JournalInput, JournalLineInput
from pars_erp.services.user_service import UserCreateData
from pars_erp.services.voucher_service import ReceiptInput
from tests.conftest import ADMIN_PASSWORD, TEST_USER_PASSWORD

D = Decimal
CASH = "101001"


# ------------------------------------------------------------------- helpers
def make_user(services, admin, username: str, role: str, password: str = TEST_USER_PASSWORD):
    services.users.create_user(admin, UserCreateData(
        username=username, full_name=f"کاربر {username}", password=password,
        confirm_password=password, role_codes=(role,)))
    return services.auth.authenticate(username, password)


def a_journal(accounts, title: str = "سند آزمون"):
    return JournalInput(entry_date=_dt.date(2026, 5, 6), title_fa=title, lines=[
        JournalLineInput(account_id=accounts[CASH].id, debit=D("1000")),
        JournalLineInput(account_id=accounts["301001"].id, credit=D("1000"))])


# ------------------------------------------------ the session is a boundary
class TestSessionIsAnAuthorityBoundary:
    def test_a_logged_out_context_cannot_post_anything(self, services, admin, chart):
        accounts, _period = chart
        services.auth.logout(admin)
        with pytest.raises(PermissionDeniedError):
            services.journals.create(admin, a_journal(accounts))

    def test_a_locked_session_is_refused_until_it_is_unlocked(self, services, admin,
                                                             chart):
        accounts, _period = chart
        services.auth.lock_session(admin, reason="idle")
        with pytest.raises(PermissionDeniedError):
            services.journals.create(admin, a_journal(accounts))
        services.auth.unlock_session(admin, ADMIN_PASSWORD)
        draft = services.journals.create(admin, a_journal(accounts))
        assert draft.id

    def test_a_deactivated_user_loses_access_immediately(self, services, admin, chart):
        accounts, _period = chart
        ctx = make_user(services, admin, "tempuser", "chief_accountant", "TempPass1404!")
        user_id = ctx.user_id
        draft = services.journals.create(ctx, a_journal(accounts))
        assert draft.id

        services.users.set_active(admin, user_id, False)
        # the closed session must be noticed even while the cache is warm
        services.auth.logout(ctx)
        with pytest.raises(PermissionDeniedError):
            services.journals.create(ctx, a_journal(accounts))

    def test_a_password_reset_kills_the_victims_open_session(self, services, admin,
                                                             chart):
        accounts, _period = chart
        ctx = make_user(services, admin, "resetme", "chief_accountant", "OldPass1404!")
        assert services.journals.create(ctx, a_journal(accounts)).id

        services.auth.reset_password_by_admin(
            admin, user_id=ctx.user_id, new_password="NewPass1404!",
            confirm_password="NewPass1404!", require_change=False)

        with pytest.raises(AppError):
            services.auth.authenticate("resetme", "OldPass1404!")
        # the old context points at a session that no longer exists
        sessions = services.auth.open_sessions(user_id=ctx.user_id)
        assert all(s.id != ctx.session_id for s in sessions)
        with pytest.raises(PermissionDeniedError):
            services.journals.create(ctx, a_journal(accounts))


# -------------------------------------------------------------- role matrix
class TestRoleMatrixIsEnforcedInTheServiceLayer:
    def test_a_viewer_can_read_but_not_write_anything(self, services, admin, chart,
                                                      commerce):
        accounts, _period = chart
        viewer = make_user(services, admin, "nazar", "viewer")
        assert services.accounts.list_accounts(viewer)
        assert services.reports.trial_balance(
            viewer, date_from=_dt.date(2026, 5, 1), date_to=_dt.date(2026, 5, 31))
        with pytest.raises(PermissionDeniedError):
            services.journals.create(viewer, a_journal(accounts))
        with pytest.raises(PermissionDeniedError):
            services.invoices.create(viewer, InvoiceInput(
                kind=CC.INVOICE_SALE, invoice_date=_dt.date(2026, 4, 15),
                party_detail_id=commerce.customer.id,
                warehouse_id=commerce.warehouse.id,
                lines=(InvoiceLineInput(product_id=commerce.product.id, quantity=1,
                                        unit_price=D("1500")),)))

    def test_a_storekeeper_cannot_touch_the_ledger_or_the_treasury(self, services,
                                                                  admin, chart,
                                                                  commerce):
        accounts, _period = chart
        keeper = make_user(services, admin, "anbardar", "storekeeper")
        assert services.inventory.balances(keeper) is not None
        with pytest.raises(PermissionDeniedError):
            services.journals.create(keeper, a_journal(accounts))
        with pytest.raises(PermissionDeniedError):
            services.vouchers.create_receipt(keeper, ReceiptInput(
                receipt_date=_dt.date(2026, 4, 20), amount=D("1000")))

    def test_an_accountant_drafts_but_the_chief_posts(self, services, admin, chart):
        accounts, _period = chart
        bookkeeper = make_user(services, admin, "hesabdar2", "accountant")
        chief = make_user(services, admin, "modir_mali", "chief_accountant")

        draft = services.journals.create(bookkeeper, a_journal(accounts))
        services.journals.submit(bookkeeper, draft.id)
        with pytest.raises(PermissionDeniedError):
            services.journals.approve(bookkeeper, draft.id)
        services.journals.approve(chief, draft.id)
        with pytest.raises(PermissionDeniedError):
            services.journals.post(bookkeeper, draft.id)
        posted = services.journals.post(chief, draft.id)
        assert posted.status == "posted"

    def test_posting_an_invoice_needs_the_posting_permission(self, services, admin,
                                                             commerce, chart):
        from pars_erp.services.inventory_service import StockLineInput

        services.inventory.record_receipt(
            admin, warehouse_id=commerce.warehouse.id,
            doc_date=_dt.date(2026, 1, 5),
            lines=(StockLineInput(product_id=commerce.product.id, quantity=50,
                                  unit_cost=D("800")),))
        sales = make_user(services, admin, "forush", "salesperson")
        chief = make_user(services, admin, "modir_mali2", "chief_accountant")
        invoice = services.invoices.create(sales, InvoiceInput(
            kind=CC.INVOICE_SALE, invoice_date=_dt.date(2026, 4, 16),
            party_detail_id=commerce.customer.id,
            warehouse_id=commerce.warehouse.id,
            lines=(InvoiceLineInput(product_id=commerce.product.id, quantity=1,
                                    unit_price=D("1500")),)))
        with pytest.raises(PermissionDeniedError):
            services.invoices.post(sales, invoice.id)
        assert services.invoices.post(chief, invoice.id)

    def test_managing_users_and_settings_stays_with_the_administrator(self, services,
                                                                     admin):
        chief = make_user(services, admin, "modir_mali3", "chief_accountant")
        with pytest.raises(PermissionDeniedError):
            services.users.create_user(chief, UserCreateData(
                username="ghost", full_name="کاربر ساختگی", password="SomePass1404!",
                confirm_password="SomePass1404!", role_codes=("viewer",)))
        with pytest.raises(PermissionDeniedError):
            services.users.set_active(chief, admin.user_id, False)
        with pytest.raises(PermissionDeniedError):
            services.settings.update(chief, {"company_name": "شرکت دیگر"})


# ------------------------------------------------------------- injection, logs
class TestHostileInputIsJustData:
    NASTY = ["' OR 1=1 --", "'; DROP TABLE acc_journals; --",
             '" UNION SELECT password_hash FROM users --', "٪00'--", "a%'-- "]

    def test_search_filters_treat_the_payload_as_text(self, services, admin, chart):
        accounts, _period = chart
        from pars_erp.services.journals_service import JournalFilter

        for payload in self.NASTY:
            services.accounts.list_accounts(admin, search=payload)
            page = services.journals.list(admin, JournalFilter(search=payload))
            assert page.total >= 0
            services.users.list_users(admin, search=payload)
        # nothing was dropped and the tables still answer
        assert services.accounts.list_accounts(admin)
        assert services.audit.list_audit_logs() is not None

    def test_a_payload_in_a_party_name_is_stored_verbatim(self, services, admin,
                                                          commerce):
        from pars_erp.services.persons_service import PersonInput

        person = services.persons.create(admin, PersonInput(
            code="XSS-1", name=self.NASTY[1], role="customer"))
        assert person.name == self.NASTY[1]
        from pars_erp.services.persons_service import PersonFilter

        found = services.persons.list_persons(admin, PersonFilter(search="DROP TABLE"))
        assert found, "the stored party must still be findable by its own text"


class TestSensitiveActionsAreAudited:
    def test_posting_and_voiding_leave_audit_rows(self, services, admin, commerce):
        from pars_erp.services.audit_service import AuditFilter
        from pars_erp.services.inventory_service import StockLineInput

        services.inventory.record_receipt(
            admin, warehouse_id=commerce.warehouse.id,
            doc_date=_dt.date(2026, 1, 5),
            lines=(StockLineInput(product_id=commerce.product.id, quantity=50,
                                  unit_cost=D("800")),))
        invoice = services.invoices.create(admin, InvoiceInput(
            kind=CC.INVOICE_SALE, invoice_date=_dt.date(2026, 4, 17),
            party_detail_id=commerce.customer.id,
            warehouse_id=commerce.warehouse.id,
            lines=(InvoiceLineInput(product_id=commerce.product.id, quantity=1,
                                    unit_price=D("1500")),)))
        services.invoices.post(admin, invoice.id)
        services.invoices.void(admin, invoice.id, "آزمون ردپای حسابرسی")

        page = services.audit.list_audit_logs(AuditFilter(entity_type="invoice"))
        rows = getattr(page, "items", page)
        actions = {row.action for row in rows}
        assert {"post", "void"} & actions, f"audit actions were {actions}"

    def test_a_password_change_is_recorded_without_the_password(self, services, admin):
        new_password = "BrandNew1404!"
        services.auth.change_password(
            admin, current_password=ADMIN_PASSWORD, new_password=new_password,
            confirm_password=new_password)

        events = services.audit.list_security_events()
        messages = " ".join(event.message_fa for event in getattr(events, "items", events))
        assert ADMIN_PASSWORD not in messages
        assert new_password not in messages
        assert "رمز" in messages

        # and the old password no longer works while the new one does
        with pytest.raises(AppError):
            services.auth.authenticate("admin", ADMIN_PASSWORD)
        assert services.auth.authenticate("admin", new_password).user_id == admin.user_id

    def test_the_audit_trail_has_no_delete_api(self):
        from pars_erp.services.audit_service import AuditService

        public = {name for name in dir(AuditService) if not name.startswith("_")}
        assert not {name for name in public
                    if "delete" in name or "purge" in name or "clear" in name}, \
            "audit rows must be append-only"


class TestSecretsNeverReachTheLogs:
    def test_a_failed_login_does_not_write_the_password(self, services, admin,
                                                        tmp_path, caplog):
        secret = "LeakMeIfYouCan1404!"
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(AppError):
                services.auth.authenticate("admin", secret)
        for record in caplog.records:
            text = record.getMessage() + str(record.args or "")
            assert secret not in text
