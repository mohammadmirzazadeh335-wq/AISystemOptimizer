"""Shared pytest fixtures.

Every test gets an isolated installation directory and a real (SQLite) database
created through **the real Alembic migrations**, not ``create_all`` - so the test
suite exercises the same schema path the shipped application uses.

Passwords are hashed with the production Argon2id implementation but with a
reduced cost profile so the suite stays fast; one dedicated test still asserts
the production parameters.
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pars_erp.config.paths import AppPaths  # noqa: E402
from pars_erp.config.settings import FileConfig  # noqa: E402
from pars_erp.db.session import Database  # noqa: E402
from pars_erp.security.passwords import Argon2PasswordHasher  # noqa: E402
from pars_erp.services.bootstrap_service import ensure_reference_data  # noqa: E402
from pars_erp.services.context import AppServices, build_services  # noqa: E402

ADMIN_PASSWORD = "ModirPass1234"
TEST_USER_PASSWORD = "Sandogh1404!"


@pytest.fixture(scope="session")
def fast_hasher() -> Argon2PasswordHasher:
    return Argon2PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1,
                                hash_len=16, salt_len=8)


@pytest.fixture()
def app_paths(tmp_path: Path) -> AppPaths:
    paths = AppPaths(tmp_path / "home")
    paths.ensure()
    return paths


@pytest.fixture()
def file_config(app_paths: AppPaths) -> FileConfig:
    return FileConfig(
        database_url=f"sqlite:///{(app_paths.data_dir / 'pars_erp.db').as_posix()}",
        log_level="DEBUG",
    )


@pytest.fixture()
def database(file_config: FileConfig) -> Database:
    db = Database(file_config.database_url)
    db.migrate()
    yield db
    db.dispose()


@pytest.fixture()
def services(app_paths: AppPaths, file_config: FileConfig, fast_hasher: Argon2PasswordHasher,
             database: Database) -> AppServices:
    services = build_services(paths=app_paths, config=file_config, db=database,
                              hasher=fast_hasher, hostname="test-host")
    ensure_reference_data(services.db)
    yield services
    services.dispose()


@pytest.fixture()
def admin(services: AppServices):
    """A freshly created administrator, already logged in (context + session row)."""
    ctx = services.auth.create_initial_admin(
        full_name="مدیر سیستم",
        username="admin",
        password=ADMIN_PASSWORD,
        confirm_password=ADMIN_PASSWORD,
        company_name="شرکت آزمون",
    )
    return ctx


@pytest.fixture()
def second_admin(services: AppServices, admin):
    """A second administrator, so tests may safely remove/deactivate the first."""
    services.users.create_user(admin, __import__("pars_erp.services.user_service",
                                                 fromlist=["UserCreateData"]).UserCreateData(
        username="admin2", full_name="مدیر دوم", password=ADMIN_PASSWORD,
        confirm_password=ADMIN_PASSWORD, role_codes=("admin",)))
    return services.auth.authenticate("admin2", ADMIN_PASSWORD)


@pytest.fixture()
def accountant(services: AppServices, admin):
    from pars_erp.services.user_service import UserCreateData
    services.users.create_user(admin, UserCreateData(
        username="hesabdar", full_name="حسابدار شرکت", password=TEST_USER_PASSWORD,
        confirm_password=TEST_USER_PASSWORD, role_codes=("accountant",)))
    ctx = services.auth.authenticate("hesabdar", TEST_USER_PASSWORD)
    return ctx


@pytest.fixture()
def chart(services, admin):
    """A ready-to-use accounting setup: standard chart of accounts + open period.

    Returns ``(accounts_by_code, period)`` so accounting tests can stay short and
    focused on the rule under test instead of on fixtures.
    """
    services.accounting.ensure_basic_setup(admin)
    accounts = {row.code: row for row in
                services.accounts.list_accounts(admin, level="subsidiary")}
    period = services.periods.list_periods(admin)[0]
    return accounts, period


@pytest.fixture()
def commerce(services: AppServices, admin, chart):
    """A ready-made commerce world: units, products, a warehouse and two persons.

    Returns a small namespace of the created rows so the phase-3 tests can stay
    focused on behaviour instead of on setup.
    """
    from types import SimpleNamespace

    from pars_erp.services.catalogue_service import ProductInput
    from pars_erp.services.inventory_service import WarehouseInput, WarehouseInput as _W
    from pars_erp.services.persons_service import PersonInput

    services.posting.ensure_default_rules(admin)
    piece = services.catalogue.create_unit(admin, code="PCS", title_fa="عدد", kind="count")
    carton = services.catalogue.create_unit(admin, code="CTN", title_fa="کارتن",
                                            kind="carton", factor=12,
                                            base_unit_id=piece.id)
    category = services.catalogue.create_category(admin, code="CAT1",
                                                  title_fa="مواد اولیه")
    brand = services.catalogue.create_brand(admin, code="BR1", title_fa="برند آزمون")
    product = services.catalogue.create(admin, ProductInput(
        code="P-100", name_fa="کالای آزمون", name_en="Test Product",
        unit_id=piece.id, category_id=category.id, brand_id=brand.id,
        barcode="6260000000011", purchase_price=1000, sale_price=1500,
        reorder_point=5, min_stock=2, max_stock=100))
    second = services.catalogue.create(admin, ProductInput(
        code="P-200", name_fa="کالای دوم", unit_id=piece.id,
        purchase_price=2000, sale_price=2600))
    service_product = services.catalogue.create(admin, ProductInput(
        code="S-100", name_fa="خدمات نصب", kind="service", unit_id=piece.id,
        sale_price=5000))
    warehouse = services.inventory.create_warehouse(admin, _W(
        code="WH1", title_fa="انبار مرکزی", keeper="انباردار آزمون", is_primary=True))
    second_warehouse = services.inventory.create_warehouse(admin, _W(
        code="WH2", title_fa="انبار فروشگاه"))
    supplier = services.persons.create(admin, PersonInput(
        code="SUP-1", name="تأمین‌کننده آزمون", role="supplier",
        national_id="1111111111", phone="02100000000"))
    customer = services.persons.create(admin, PersonInput(
        code="CUS-1", name="مشتری آزمون", role="customer",
        national_id="2222222222", mobile="09120000000", credit_limit=0))
    return SimpleNamespace(
        unit=piece, carton=carton, category=category, brand=brand,
        product=product, second=second, service=service_product,
        warehouse=warehouse, warehouse2=second_warehouse,
        supplier=supplier, customer=customer,
    )


@pytest.fixture()
def treasury(services: AppServices, admin, commerce):
    """A treasury world: a bank account, two cash boxes and open invoices.

    Everything is created through the real services, so the fixture exercises the
    same validation a user goes through (chart links, duplicate accounts, ...).
    """
    from types import SimpleNamespace

    from pars_erp.commerce import constants as CC
    from pars_erp.services.funds_service import BankAccountInput, CashBoxInput
    from pars_erp.services.inventory_service import StockLineInput
    from pars_erp.services.invoice_service import InvoiceInput, InvoiceLineInput

    accounts = {row.code: row for row in
                services.accounts.list_accounts(admin, level="subsidiary")}
    bank = services.funds.create_bank_account(admin, BankAccountInput(
        code="BNK-1", bank_name="بانک ملت", branch_name="شعبه مرکزی",
        account_number="1234567890", account_id=accounts["101006"].id,
        opening_balance=100_000_000, opening_date=_dt.date(2026, 1, 1),
        iban="IR120170000000123456789012", holder_name="زرین هرمز"))
    box = services.funds.create_cash_box(admin, CashBoxInput(
        code="CASH-1", title_fa="صندوق مرکزی", account_id=accounts["101005"].id,
        keeper_name="صندوق‌دار آزمون", opening_balance=10_000_000,
        opening_date=_dt.date(2026, 1, 1)))
    small = services.funds.create_cash_box(admin, CashBoxInput(
        code="CASH-2", title_fa="صندوق فروشگاه",
        parent_account_id=accounts["101005"].id,
        opening_balance=1_000_000, opening_date=_dt.date(2026, 1, 1)))
    services.inventory.record_receipt(
        admin, warehouse_id=commerce.warehouse.id, doc_date=_dt.date(2026, 1, 5),
        lines=(StockLineInput(product_id=commerce.product.id, quantity=100, unit_cost=800),
               StockLineInput(product_id=commerce.second.id, quantity=100, unit_cost=1800)))
    sale = services.invoices.create(admin, InvoiceInput(
        kind=CC.INVOICE_SALE, invoice_date=_dt.date(2026, 4, 1),
        party_detail_id=commerce.customer.id, warehouse_id=commerce.warehouse.id,
        lines=(InvoiceLineInput(product_id=commerce.product.id, quantity=10,
                                unit_price=1000),)))
    services.invoices.post(admin, sale.id)
    sale = services.invoices.get(admin, sale.id)
    purchase = services.invoices.create(admin, InvoiceInput(
        kind=CC.INVOICE_PURCHASE, invoice_date=_dt.date(2026, 4, 2),
        party_detail_id=commerce.supplier.id, warehouse_id=commerce.warehouse.id,
        lines=(InvoiceLineInput(product_id=commerce.second.id, quantity=5,
                                unit_price=2000),)))
    services.invoices.post(admin, purchase.id)
    purchase = services.invoices.get(admin, purchase.id)
    return SimpleNamespace(bank=bank, box=box, small_box=small, accounts=accounts,
                           customer=commerce.customer, supplier=commerce.supplier,
                           sale=sale, purchase=purchase, commerce=commerce)


@pytest.fixture()
def clock() -> _dt.datetime:
    return _dt.datetime(2026, 10, 30, 9, 15, tzinfo=_dt.timezone.utc)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch) -> None:
    """Never let a developer's real installation leak into the test run."""
    monkeypatch.delenv("PARSERP_HOME", raising=False)
    monkeypatch.delenv("PARSERP_DATABASE_URL", raising=False)
