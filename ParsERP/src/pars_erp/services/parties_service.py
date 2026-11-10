"""Subsidiary details (حساب‌های تفصیلی: مشتری، تأمین‌کننده، کارمند، بانک، صندوق).

A detail may be linked to one subsidiary account (معین). Journal lines can then
carry the detail, which is what makes "مانده حساب مشتری" possible without any
invoice module.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from pars_erp.accounting import constants as C
from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import Account, DetailAccount, JournalLine
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService


@dataclass(frozen=True)
class DetailInput:
    code: str
    name: str
    kind: str
    account_id: int | None = None
    phone: str = ""
    national_id: str = ""
    address: str = ""
    description: str = ""
    is_active: bool = True


@dataclass(frozen=True)
class DetailRow:
    id: int
    code: str
    name: str
    kind: str
    kind_fa: str
    account_id: int | None
    account_label: str
    phone: str
    national_id: str
    address: str
    description: str
    is_active: bool

    @property
    def display(self) -> str:
        return f"{self.code} — {self.name}"

    @property
    def status_fa(self) -> str:
        return "فعال" if self.is_active else "غیرفعال"


class PartyService:
    def __init__(self, db: Database, audit: AuditService) -> None:
        self.db = db
        self.audit = audit

    # ------------------------------------------------------------------ read
    def list_details(self, ctx: SecurityContext | None, *, kind: str | None = None,
                     search: str | None = None, account_id: int | None = None,
                     active: bool | None = None) -> list[DetailRow]:
        require_permission(ctx, "details.view")
        query = select(DetailAccount).order_by(DetailAccount.code)
        if kind:
            query = query.where(DetailAccount.kind == kind)
        if account_id:
            query = query.where(DetailAccount.account_id == account_id)
        if active is not None:
            query = query.where(DetailAccount.is_active.is_(bool(active)))
        if search:
            needle = f"%{search.strip()}%"
            query = query.where(or_(DetailAccount.code.like(needle),
                                    DetailAccount.name.like(needle),
                                    DetailAccount.phone.like(needle),
                                    DetailAccount.national_id.like(needle)))
        with self.db.session_scope() as session:
            return [self._row(item) for item in session.execute(query).scalars()]

    def choices(self, ctx: SecurityContext | None, account_id: int | None = None,
                *, active_only: bool = True) -> list[tuple[int, str]]:
        require_permission(ctx, "details.view")
        query = select(DetailAccount).order_by(DetailAccount.code)
        if active_only:
            query = query.where(DetailAccount.is_active.is_(True))
        if account_id:
            query = query.where(or_(DetailAccount.account_id == account_id,
                                    DetailAccount.account_id.is_(None)))
        with self.db.session_scope() as session:
            return [(item.id, f"{item.code} — {item.name}")
                    for item in session.execute(query).scalars()]

    def get(self, ctx: SecurityContext | None, detail_id: int) -> DetailRow:
        require_permission(ctx, "details.view")
        with self.db.session_scope() as session:
            item = session.get(DetailAccount, detail_id)
            if item is None:
                raise NotFoundError("حساب تفصیلی مورد نظر یافت نشد.")
            return self._row(item)

    # ----------------------------------------------------------------- write
    def create(self, ctx: SecurityContext | None, data: DetailInput) -> DetailRow:
        require_permission(ctx, "details.edit")
        payload = self._validated(data)
        with self.db.session_scope() as session:
            item = DetailAccount(**payload, created_by_id=ctx.user_id if ctx else None)
            session.add(item)
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("حساب تفصیلی با این کد قبلاً تعریف شده است.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="detail_account", entity_id=item.id, action="create",
                summary_fa=f"ایجاد حساب تفصیلی {item.code} — {item.name}",
                after=item.to_dict(), session=session)
            return self._row(item)

    def update(self, ctx: SecurityContext | None, detail_id: int,
               data: DetailInput) -> DetailRow:
        require_permission(ctx, "details.edit")
        payload = self._validated(data)
        with self.db.session_scope() as session:
            item = session.get(DetailAccount, detail_id)
            if item is None:
                raise NotFoundError("حساب تفصیلی مورد نظر یافت نشد.")
            before = item.to_dict()
            for key, value in payload.items():
                setattr(item, key, value)
            item.updated_by_id = ctx.user_id if ctx else None
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("حساب تفصیلی با این کد قبلاً تعریف شده است.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="detail_account", entity_id=item.id, action="update",
                summary_fa=f"ویرایش حساب تفصیلی {item.code} — {item.name}",
                before=before, after=item.to_dict(), session=session)
            return self._row(item)

    def set_active(self, ctx: SecurityContext | None, detail_id: int, active: bool) -> DetailRow:
        require_permission(ctx, "details.edit")
        with self.db.session_scope() as session:
            item = session.get(DetailAccount, detail_id)
            if item is None:
                raise NotFoundError("حساب تفصیلی مورد نظر یافت نشد.")
            before = item.to_dict()
            item.is_active = bool(active)
            item.updated_by_id = ctx.user_id if ctx else None
            self.audit.log_audit(
                ctx=ctx, entity_type="detail_account", entity_id=item.id,
                action="activate" if active else "deactivate",
                summary_fa=("فعال‌سازی" if active else "غیرفعال‌سازی")
                           + f" حساب تفصیلی {item.code}",
                before=before, after=item.to_dict(), session=session)
            return self._row(item)

    def delete(self, ctx: SecurityContext | None, detail_id: int) -> None:
        require_permission(ctx, "details.edit")
        with self.db.session_scope() as session:
            item = session.get(DetailAccount, detail_id)
            if item is None:
                raise NotFoundError("حساب تفصیلی مورد نظر یافت نشد.")
            used = session.execute(
                select(func.count(JournalLine.id))
                .where(JournalLine.detail_id == detail_id)).scalar() or 0
            if used:
                raise ValidationError(
                    "این تفصیلی در اسناد استفاده شده است؛ حذف مجاز نیست. آن را غیرفعال کنید.")
            before = item.to_dict()
            session.delete(item)
            self.audit.log_audit(
                ctx=ctx, entity_type="detail_account", entity_id=detail_id, action="delete",
                summary_fa=f"حذف حساب تفصیلی {before.get('name')}", before=before,
                session=session)

    # --------------------------------------------------------------- helpers
    def _validated(self, data: DetailInput) -> dict:
        code = (data.code or "").strip()
        name = (data.name or "").strip()
        if not code:
            raise ValidationError("کد تفصیلی را وارد کنید.", field="code")
        if not code.isdigit():
            raise ValidationError("کد تفصیلی باید عددی باشد.", field="code")
        if len(name) < 2:
            raise ValidationError("نام تفصیلی را کامل وارد کنید.", field="name")
        if data.kind not in C.DETAIL_KINDS:
            raise ValidationError("نوع تفصیلی نامعتبر است.", field="kind")
        account_id = data.account_id
        if account_id:
            with self.db.session_scope() as session:
                account = session.get(Account, account_id)
                if account is None:
                    raise NotFoundError("حساب معین انتخاب‌شده یافت نشد.")
                if account.level != C.LEVEL_SUBSIDIARY:
                    raise ValidationError(
                        "تفصیلی فقط به حساب معین قابل اتصال است.", field="account_id")
        return {
            "code": code,
            "name": name,
            "kind": data.kind,
            "account_id": account_id or None,
            "phone": (data.phone or "").strip() or None,
            "national_id": (data.national_id or "").strip() or None,
            "address": (data.address or "").strip() or None,
            "description": (data.description or "").strip() or None,
            "is_active": bool(data.is_active),
        }

    @staticmethod
    def _row(item: DetailAccount) -> DetailRow:
        return DetailRow(
            id=item.id, code=item.code, name=item.name, kind=item.kind,
            kind_fa=C.DETAIL_KIND_TITLES_FA.get(item.kind, item.kind),
            account_id=item.account_id,
            account_label=(f"{item.account.code} — {item.account.title_fa}"
                           if item.account else ""),
            phone=item.phone or "", national_id=item.national_id or "",
            address=item.address or "", description=item.description or "",
            is_active=item.is_active)
