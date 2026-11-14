"""Chart of accounts service (گروه حساب، حساب کل، حساب معین).

Every mutation is permission-checked **here** - the UI only hides controls - and
is written to the business audit trail with a before/after snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from pars_erp.accounting import constants as C
from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import Account, JournalLine
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.accounting_common import (
    expected_code_length,
    parse_mask,
    validate_account_code,
)
from pars_erp.services.audit_service import AuditService

# --------------------------------------------------------------------- inputs
@dataclass(frozen=True)
class AccountInput:
    code: str
    title_fa: str
    level: str
    account_type: str
    nature: str | None = None
    parent_id: int | None = None
    statement_section: str | None = None
    description: str = ""
    is_active: bool = True


@dataclass(frozen=True)
class AccountRow:
    id: int
    code: str
    title_fa: str
    level: str
    level_fa: str
    account_type: str
    account_type_fa: str
    nature: str
    nature_fa: str
    statement_section: str
    statement_section_fa: str
    parent_id: int | None
    parent_title: str
    is_active: bool
    is_system: bool
    description: str
    is_used: bool = False

    @property
    def display(self) -> str:
        return f"{self.code} — {self.title_fa}"

    @property
    def status_fa(self) -> str:
        return "فعال" if self.is_active else "غیرفعال"


@dataclass
class AccountNode:
    row: AccountRow
    children: list["AccountNode"] = field(default_factory=list)

    def walk(self, depth: int = 0):
        yield self, depth
        for child in self.children:
            yield from child.walk(depth + 1)


class AccountService:
    """CRUD + validation for the chart of accounts."""

    def __init__(self, db: Database, settings, audit: AuditService) -> None:
        self.db = db
        self.settings = settings
        self.audit = audit

    # ------------------------------------------------------------- structure
    def code_mask(self) -> tuple[int, ...]:
        try:
            return parse_mask(self.settings.snapshot().str("accounting_code_mask"))
        except Exception:  # invalid stored value must not break the module
            return parse_mask(None)

    def describe_mask(self) -> str:
        mask = self.code_mask()
        return " — ".join(
            f"{C.LEVEL_TITLES_FA[level]}: {expected_code_length(level, mask)} رقم"
            for level in C.ACCOUNT_LEVELS)

    # ------------------------------------------------------------------ read
    def list_accounts(self, ctx: SecurityContext | None, *, level: str | None = None,
                      account_type: str | None = None, active: bool | None = None,
                      search: str | None = None, parent_id: int | None = None,
                      only_roots: bool = False) -> list[AccountRow]:
        require_permission(ctx, "accounts.view")
        query = select(Account).order_by(Account.code)
        if level:
            if level not in C.ACCOUNT_LEVELS:
                raise ValidationError("سطح حساب نامعتبر است.", field="level")
            query = query.where(Account.level == level)
        if account_type:
            query = query.where(Account.account_type == account_type)
        if active is not None:
            query = query.where(Account.is_active == bool(active))
        if only_roots:
            query = query.where(Account.parent_id.is_(None))
        elif parent_id is not None:
            query = query.where(Account.parent_id == parent_id)
        if search:
            needle = f"%{search.strip()}%"
            query = query.where(Account.code.like(needle) | Account.title_fa.like(needle))
        with self.db.session_scope() as session:
            accounts = list(session.execute(query).scalars())
            used = self._used_account_ids(session)
            return [self._row(account, used=account.id in used) for account in accounts]

    def tree(self, ctx: SecurityContext | None, *, active: bool | None = None) -> list[AccountNode]:
        require_permission(ctx, "accounts.view")
        with self.db.session_scope() as session:
            accounts = list(session.execute(
                select(Account).order_by(Account.code)).scalars())
            used = self._used_account_ids(session)
            nodes = {a.id: AccountNode(self._row(a, used=a.id in used)) for a in accounts}
            roots: list[AccountNode] = []
            for account in accounts:
                node = nodes[account.id]
                if active is not None and account.is_active != active:
                    # keep hierarchy intact but skip filtered nodes
                    continue
                if account.parent_id and account.parent_id in nodes:
                    nodes[account.parent_id].children.append(node)
                else:
                    roots.append(node)
            return roots

    def get(self, ctx: SecurityContext | None, account_id: int) -> AccountRow:
        require_permission(ctx, "accounts.view")
        with self.db.session_scope() as session:
            account = session.get(Account, account_id)
            if account is None:
                raise NotFoundError("حساب مورد نظر یافت نشد.")
            used = self._used_account_ids(session)
            return self._row(account, used=account.id in used)

    def choices(self, ctx: SecurityContext | None, *, level: str | None = C.LEVEL_SUBSIDIARY,
                active_only: bool = True) -> list[tuple[int, str]]:
        """``(id, "code — title")`` pairs for combo boxes."""
        require_permission(ctx, "accounts.view")
        query = select(Account).order_by(Account.code)
        if level:
            query = query.where(Account.level == level)
        if active_only:
            query = query.where(Account.is_active.is_(True))
        with self.db.session_scope() as session:
            return [(a.id, f"{a.code} — {a.title_fa}")
                    for a in session.execute(query).scalars()]

    def next_suggested_code(self, ctx: SecurityContext | None, parent_id: int | None,
                            level: str) -> str:
        """Suggest the next free code under ``parent`` following the mask."""
        require_permission(ctx, "accounts.view")
        mask = self.code_mask()
        length = expected_code_length(level, mask) or 2
        prefix = ""
        with self.db.session_scope() as session:
            if parent_id is not None:
                parent = session.get(Account, parent_id)
                if parent is None:
                    raise NotFoundError("حساب والد یافت نشد.")
                prefix = parent.code
            siblings = session.execute(
                select(Account.code).where(Account.parent_id == parent_id)).scalars().all()
        tail_len = max(1, length - len(prefix))
        used = {code[len(prefix):] for code in siblings if code.startswith(prefix)}
        for number in range(1, 10 ** tail_len):
            candidate = str(number).zfill(tail_len)
            if candidate not in used:
                return prefix + candidate
        raise ConflictError("ظرفیت کدگذاری در این سطح تکمیل شده است؛ الگوی کدینگ را بازبینی کنید.")

    def usage_count(self, ctx: SecurityContext | None, account_id: int) -> int:
        require_permission(ctx, "accounts.view")
        with self.db.session_scope() as session:
            return int(session.execute(
                select(func.count(JournalLine.id))
                .where(JournalLine.account_id == account_id)).scalar() or 0)

    # ----------------------------------------------------------------- write
    def create(self, ctx: SecurityContext | None, data: AccountInput) -> AccountRow:
        require_permission(ctx, "accounts.create")
        payload = self._validated(data, parent=self._parent_for(None, data))
        with self.db.session_scope() as session:
            account = Account(**payload, created_by_id=ctx.user_id if ctx else None)
            session.add(account)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("حسابی با این کد قبلاً تعریف شده است.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="account", entity_id=account.id, action="create",
                summary_fa=f"ایجاد حساب {account.code} — {account.title_fa}",
                after=account.to_dict(), session=session)
            row = self._row(account)
        return row

    def update(self, ctx: SecurityContext | None, account_id: int,
               data: AccountInput) -> AccountRow:
        require_permission(ctx, "accounts.edit")
        with self.db.session_scope() as session:
            account = session.get(Account, account_id)
            if account is None:
                raise NotFoundError("حساب مورد نظر یافت نشد.")
            before = account.to_dict()
            parent = None
            if data.parent_id is not None:
                parent = session.get(Account, data.parent_id)
                if parent is None:
                    raise NotFoundError("حساب والد یافت نشد.")
            payload = self._validated(data, parent=parent, existing=account)
            if account.is_system and payload["level"] != account.level:
                raise ValidationError("سطح حساب‌های سیستمی قابل تغییر نیست.", field="level")
            if payload["level"] != account.level and self._has_children(session, account.id):
                raise ValidationError("سطح حسابی که دارای زیرمجموعه است قابل تغییر نیست.",
                                      field="level")
            for key, value in payload.items():
                setattr(account, key, value)
            account.updated_by_id = ctx.user_id if ctx else None
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("حسابی با این کد قبلاً تعریف شده است.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="account", entity_id=account.id, action="update",
                summary_fa=f"ویرایش حساب {account.code} — {account.title_fa}",
                before=before, after=account.to_dict(), session=session)
            return self._row(account)

    def set_active(self, ctx: SecurityContext | None, account_id: int, active: bool) -> AccountRow:
        require_permission(ctx, "accounts.deactivate")
        with self.db.session_scope() as session:
            account = session.get(Account, account_id)
            if account is None:
                raise NotFoundError("حساب مورد نظر یافت نشد.")
            if not active and account.is_system:
                raise ValidationError("حساب سیستمی قابل غیرفعال‌سازی نیست.")
            if not active and self._has_children(session, account.id):
                raise ValidationError(
                    "ابتدا زیرمجموعه‌های این حساب را غیرفعال کنید.", field="is_active")
            before = account.to_dict()
            account.is_active = bool(active)
            account.updated_by_id = ctx.user_id if ctx else None
            self.audit.log_audit(
                ctx=ctx, entity_type="account", entity_id=account.id,
                action="activate" if active else "deactivate",
                summary_fa=(f"فعال‌سازی حساب {account.code}" if active
                            else f"غیرفعال‌سازی حساب {account.code}"),
                before=before, after=account.to_dict(), session=session)
            return self._row(account)

    def delete(self, ctx: SecurityContext | None, account_id: int) -> None:
        """Delete only unreferenced leaves - financial history is never orphaned."""
        require_permission(ctx, "accounts.delete")
        with self.db.session_scope() as session:
            account = session.get(Account, account_id)
            if account is None:
                raise NotFoundError("حساب مورد نظر یافت نشد.")
            if account.is_system:
                raise ValidationError("حساب سیستمی قابل حذف نیست.")
            if self._has_children(session, account.id):
                raise ValidationError("حسابی که زیرمجموعه دارد قابل حذف نیست.")
            used = session.execute(
                select(func.count(JournalLine.id))
                .where(JournalLine.account_id == account.id)).scalar() or 0
            if used:
                raise ValidationError(
                    "این حساب در اسناد حسابداری استفاده شده است؛ حذف مجاز نیست. "
                    "به‌جای حذف، آن را غیرفعال کنید.")
            before = account.to_dict()
            session.delete(account)
            self.audit.log_audit(
                ctx=ctx, entity_type="account", entity_id=account_id, action="delete",
                summary_fa=f"حذف حساب {before.get('code')} — {before.get('title_fa')}",
                before=before, session=session)

    def set_statement_section(self, ctx: SecurityContext | None, account_id: int,
                              section: str | None) -> AccountRow:
        """Re-map an account to a financial statement line (configurable mapping)."""
        require_permission(ctx, "accounts.edit")
        with self.db.session_scope() as session:
            account = session.get(Account, account_id)
            if account is None:
                raise NotFoundError("حساب مورد نظر یافت نشد.")
            if section and section not in C.SECTIONS_BY_TYPE.get(account.account_type, ()):
                raise ValidationError(
                    f"سرفصل «{section}» با نوع حساب «{account.account_type}» سازگار نیست.",
                    field="statement_section")
            before = account.to_dict()
            account.statement_section = section
            account.updated_by_id = ctx.user_id if ctx else None
            self.audit.log_audit(
                ctx=ctx, entity_type="account", entity_id=account.id, action="update",
                summary_fa=f"تغییر سرفصل صورت‌های مالی حساب {account.code}",
                before=before, after=account.to_dict(), session=session)
            return self._row(account)

    # --------------------------------------------------------------- helpers
    def _parent_for(self, session_existing: Account | None, data: AccountInput) -> Account | None:
        if data.parent_id is None:
            return None
        with self.db.session_scope() as session:
            parent = session.get(Account, data.parent_id)
            if parent is None:
                raise NotFoundError("حساب والد یافت نشد.")
            session.expunge(parent)
            return parent

    def _validated(self, data: AccountInput, *, parent: Account | None,
                   existing: Account | None = None) -> dict:
        if data.level not in C.ACCOUNT_LEVELS:
            raise ValidationError("سطح حساب نامعتبر است.", field="level")
        if data.account_type not in C.ACCOUNT_TYPES:
            raise ValidationError("نوع حساب نامعتبر است.", field="account_type")
        title = (data.title_fa or "").strip()
        if len(title) < 2:
            raise ValidationError("عنوان حساب باید حداقل دو نویسه باشد.", field="title_fa")
        if len(title) > C.TITLE_MAX_LENGTH:
            raise ValidationError("عنوان حساب بیش از حد طولانی است.", field="title_fa")

        required_parent = C.PARENT_LEVEL[data.level]
        if required_parent is None and data.parent_id is not None:
            raise ValidationError("گروه حساب نمی‌تواند حساب والد داشته باشد.", field="parent_id")
        if required_parent is not None:
            if parent is None:
                raise ValidationError(
                    f"برای «{C.LEVEL_TITLES_FA[data.level]}» انتخاب حساب والد الزامی است.",
                    field="parent_id")
            if parent.level != required_parent:
                raise ValidationError(
                    f"حساب والد باید از سطح «{C.LEVEL_TITLES_FA[required_parent]}» باشد.",
                    field="parent_id")
        if existing is not None and parent is not None and existing.id == parent.id:
            raise ValidationError("یک حساب نمی‌تواند والد خودش باشد.", field="parent_id")

        mask = self.code_mask()
        code = validate_account_code(data.code, data.level, mask, parent)

        nature = (data.nature or C.TYPE_NATURE[data.account_type]).strip()
        if nature not in C.NATURES:
            raise ValidationError("ماهیت حساب نامعتبر است.", field="nature")
        if nature != C.TYPE_NATURE[data.account_type]:
            raise ValidationError(
                f"ماهیت حساب با نوع «{C.TYPE_TITLES_FA[data.account_type]}» سازگار نیست.",
                field="nature")

        section = data.statement_section or C.DEFAULT_SECTION_BY_TYPE[data.account_type]
        if section not in C.SECTIONS_BY_TYPE.get(data.account_type, ()):
            raise ValidationError("سرفصل صورت‌های مالی با نوع حساب سازگار نیست.",
                                  field="statement_section")

        return {
            "code": code,
            "title_fa": title,
            "level": data.level,
            "account_type": data.account_type,
            "nature": nature,
            "parent_id": data.parent_id,
            "statement_section": section,
            "description": (data.description or "").strip() or None,
            "is_active": bool(data.is_active),
            "sort_order": int(code),
        }

    @staticmethod
    def _has_children(session, account_id: int) -> bool:
        return session.execute(
            select(func.count(Account.id))
            .where(Account.parent_id == account_id)).scalar() not in (0, None)

    @staticmethod
    def _used_account_ids(session) -> set[int]:
        rows = session.execute(select(JournalLine.account_id).distinct()).scalars().all()
        return {int(value) for value in rows}

    @staticmethod
    def _row(account: Account, *, used: bool = False) -> AccountRow:
        return AccountRow(
            id=account.id,
            code=account.code,
            title_fa=account.title_fa,
            level=account.level,
            level_fa=C.LEVEL_TITLES_FA.get(account.level, account.level),
            account_type=account.account_type,
            account_type_fa=C.TYPE_TITLES_FA.get(account.account_type, account.account_type),
            nature=account.nature,
            nature_fa=C.NATURE_TITLES_FA.get(account.nature, account.nature),
            statement_section=account.statement_section or "",
            statement_section_fa=C.SECTION_TITLES_FA.get(account.statement_section or "", "—"),
            parent_id=account.parent_id,
            parent_title=(account.parent.title_fa if account.parent else ""),
            is_active=account.is_active,
            is_system=account.is_system,
            description=account.description or "",
            is_used=used,
        )

    def export_rows(self, ctx: SecurityContext | None) -> tuple[tuple[str, ...], list[tuple]]:
        """Column titles + rows for CSV/Excel export of the chart of accounts."""
        rows = self.list_accounts(ctx)
        headers = ("کد حساب", "عنوان", "سطح", "نوع", "ماهیت", "سرفصل", "وضعیت")
        return headers, [(r.code, r.title_fa, r.level_fa, r.account_type_fa,
                          r.nature_fa, r.statement_section_fa, r.status_fa) for r in rows]
