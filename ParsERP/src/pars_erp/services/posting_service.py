"""Configurable posting patterns that connect commerce to the phase-2 ledger.

A :class:`PostingRule` is a list of lines, each of which says *which side*,
*which account* and *which amount component* of the commercial document to use.
Nothing about accounts or rates is hard-coded: the default rules are only
**suggestions** created from the company's own chart of accounts, and the user
can change every line through the settings page.

The engine never invents an amount: it reads the components the invoice service
computed (subtotal, total discount, tax, charges, net, COGS, inventory value) and
refuses to post an unbalanced entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from pars_erp.accounting import constants as AC
from pars_erp.commerce import constants as CC
from pars_erp.treasury import constants as TC
from pars_erp.payroll import constants as PC
from pars_erp.core.errors import ConflictError, NotFoundError, ValidationError
from pars_erp.db.models import Account, PostingRule, PostingRuleLine
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService
from pars_erp.services.commerce_common import ZERO, clean_text, get_or_404, to_money

#: Commerce + treasury operations share one table of posting patterns.
POSTING_OPERATIONS: tuple[str, ...] = (CC.POSTING_OPERATIONS + TC.POSTING_OPERATIONS
                                       + PC.POSTING_OPERATIONS)
POSTING_TITLES_FA: dict[str, str] = {**CC.POSTING_TITLES_FA, **TC.POSTING_TITLES_FA,
                                     **PC.POSTING_TITLES_FA}
AMOUNT_SOURCES: tuple[str, ...] = CC.AMOUNT_SOURCES + TC.AMOUNT_SOURCES + PC.AMOUNT_SOURCES
AMOUNT_SOURCE_TITLES_FA: dict[str, str] = {**CC.AMOUNT_SOURCE_TITLES_FA,
                                           **TC.AMOUNT_SOURCE_TITLES_FA,
                                           **PC.AMOUNT_SOURCE_TITLES_FA}

#: Suggested chart codes per default rule line, in the *standard* phase-2 chart.
#: They are only used to seed a rule once; afterwards the stored accounts rule.
DEFAULT_RULE_TEMPLATES: dict[str, tuple[tuple[str, str, str], ...]] = {
    CC.POSTING_PURCHASE: (
        ("debit", CC.SRC_INVENTORY_VALUE, "101003"),   # موجودی کالا
        ("debit", CC.SRC_TAX, "201002"),               # مالیات پرداختنی
        ("debit", CC.SRC_CHARGES, "502003"),           # هزینه‌های اداری و عمومی
        ("credit", CC.SRC_NET, "201001"),              # حساب‌های پرداختنی تجاری
    ),
    CC.POSTING_PURCHASE_RETURN: (
        ("credit", CC.SRC_INVENTORY_VALUE, "101003"),
        ("credit", CC.SRC_TAX, "201002"),
        ("credit", CC.SRC_CHARGES, "502003"),
        ("debit", CC.SRC_NET, "201001"),
    ),
    CC.POSTING_SALE: (
        ("debit", CC.SRC_NET, "101002"),               # حساب‌های دریافتنی تجاری
        ("debit", CC.SRC_DISCOUNT, "401001"),          # تخفیف (کاهندهٔ درآمد)
        ("credit", CC.SRC_SUBTOTAL, "401001"),         # فروش کالا
        ("credit", CC.SRC_TAX, "201002"),
        ("credit", CC.SRC_CHARGES, "402001"),          # درآمد متفرقه
        ("debit", CC.SRC_COGS, "501001"),              # بهای تمام‌شده
        ("credit", CC.SRC_COGS, "101003"),             # خروج از موجودی
    ),
    CC.POSTING_SALE_RETURN: (
        ("credit", CC.SRC_NET, "101002"),
        ("credit", CC.SRC_DISCOUNT, "401001"),
        ("debit", CC.SRC_SUBTOTAL, "401001"),
        ("debit", CC.SRC_TAX, "201002"),
        ("debit", CC.SRC_CHARGES, "402001"),
        ("debit", CC.SRC_INVENTORY_VALUE, "101003"),
        ("credit", CC.SRC_COGS, "501001"),
    ),
    CC.POSTING_GOODS_RECEIPT: (
        ("debit", CC.SRC_INVENTORY_VALUE, "101003"),
        ("credit", CC.SRC_INVENTORY_VALUE, "201001"),
    ),
    CC.POSTING_GOODS_ISSUE: (
        ("debit", CC.SRC_INVENTORY_VALUE, "501001"),
        ("credit", CC.SRC_INVENTORY_VALUE, "101003"),
    ),
    CC.POSTING_COUNT_ADJUSTMENT: (
        ("debit", CC.SRC_ADJUSTMENT_VALUE, "101003"),
        ("credit", CC.SRC_ADJUSTMENT_VALUE, "503001"),
    ),
    # ------------------------------------------------------------------ phase 4
    #: the fund line (``SRC_FUND``) takes its account from the document itself
    TC.POSTING_RECEIPT_CASH: (
        ("debit", TC.SRC_FUND, "101005"),               # صندوق (پویا)
        ("credit", TC.SRC_AMOUNT, "101002"),            # حساب‌های دریافتنی
    ),
    TC.POSTING_RECEIPT_BANK: (
        ("debit", TC.SRC_FUND, "101006"),               # بانک (پویا)
        ("credit", TC.SRC_AMOUNT, "101002"),
    ),
    TC.POSTING_RECEIPT_CHEQUE: (
        ("debit", TC.SRC_AMOUNT, "101007"),             # چک‌های در جریان وصول
        ("credit", TC.SRC_AMOUNT, "101002"),
    ),
    TC.POSTING_PAYMENT_CASH: (
        ("debit", TC.SRC_AMOUNT, "201001"),             # حساب‌های پرداختنی
        ("credit", TC.SRC_FUND, "101005"),
    ),
    TC.POSTING_PAYMENT_BANK: (
        ("debit", TC.SRC_AMOUNT, "201001"),
        ("credit", TC.SRC_FUND, "101006"),
    ),
    TC.POSTING_PAYMENT_CHEQUE: (
        ("debit", TC.SRC_AMOUNT, "201001"),
        ("credit", TC.SRC_AMOUNT, "201004"),            # چک‌های پرداختنی
    ),
    TC.POSTING_CHEQUE_COLLECTED: (
        ("debit", TC.SRC_FUND, "101006"),               # بانک (پویا)
        ("credit", TC.SRC_AMOUNT, "101007"),
    ),
    TC.POSTING_CHEQUE_BOUNCED: (
        ("debit", TC.SRC_AMOUNT, "101002"),
        ("credit", TC.SRC_AMOUNT, "101007"),
    ),
    TC.POSTING_CHEQUE_CLEARED: (
        ("debit", TC.SRC_AMOUNT, "201004"),
        ("credit", TC.SRC_FUND, "101006"),
    ),
    TC.POSTING_TRANSFER: (
        ("debit", TC.SRC_FUND_TO, "101006"),            # مقصد (پویا)
        ("debit", TC.SRC_FEE, "502004"),                # کارمزد انتقال
        ("credit", TC.SRC_FUND_FROM, "101005"),         # مبدأ (پویا)
    ),
    TC.POSTING_BANK_FEE: (
        ("debit", TC.SRC_FEE, "502004"),                # کارمزد بانکی
        ("credit", TC.SRC_FUND, "101006"),
    ),
    # ----------------------------------------------------------- phase 5 payroll
    # debit  حقوق ناخالص + بیمهٔ سهم کارفرما
    # credit بیمهٔ پرداختنی (کارمند + کارفرما)، مالیات، خالص، اقساط وام و مساعده
    PC.POSTING_SALARY: (
        ("debit", PC.SRC_SALARY_EXPENSE, "502001"),      # هزینهٔ حقوق و دستمزد
        ("debit", PC.SRC_EMPLOYER_INSURANCE, "502006"),  # بیمهٔ سهم کارفرما
        ("credit", PC.SRC_INSURANCE_TOTAL, "201005"),    # بیمهٔ پرداختنی
        ("credit", PC.SRC_TAX, "201002"),                # مالیات پرداختنی
        ("credit", PC.SRC_LOAN, "101008"),               # وام کارکنان
        ("credit", PC.SRC_ADVANCE, "101008"),            # مساعدهٔ کارکنان
        ("credit", PC.SRC_OTHER_DEDUCTION, "503001"),    # سایر کسور
        ("credit", PC.SRC_NET, "201003"),                # حقوق پرداختنی
    ),
}


@dataclass(frozen=True)
class RuleLineRow:
    id: int
    line_no: int
    side: str
    side_fa: str
    account_id: int
    account_label: str
    amount_source: str
    amount_source_fa: str
    description: str

    @property
    def display(self) -> str:
        return f"{self.side_fa} {self.account_label} ← {self.amount_source_fa}"


@dataclass(frozen=True)
class PostingRuleRow:
    id: int
    operation: str
    operation_fa: str
    title_fa: str
    is_active: bool
    note: str
    lines: tuple[RuleLineRow, ...]

    @property
    def display(self) -> str:
        return f"{self.operation_fa} — {self.title_fa}"


@dataclass(frozen=True)
class EntryLine:
    account_id: int
    debit: Decimal
    credit: Decimal
    description: str
    detail_id: int | None = None


@dataclass(frozen=True)
class EntryDraft:
    lines: tuple[EntryLine, ...]
    total_debit: Decimal
    total_credit: Decimal

    @property
    def is_balanced(self) -> bool:
        return self.total_debit == self.total_credit


class PostingService:
    def __init__(self, db: Database, audit: AuditService) -> None:
        self.db = db
        self.audit = audit

    # ------------------------------------------------------------------ read
    def list_rules(self, ctx: SecurityContext | None, *,
                   operation: str | None = None) -> list[PostingRuleRow]:
        require_permission(ctx, "commerce.reports")
        query = select(PostingRule).order_by(PostingRule.operation, PostingRule.id)
        if operation:
            query = query.where(PostingRule.operation == operation)
        with self.db.session_scope() as session:
            return [self._rule_row(rule) for rule in session.execute(query).scalars()]

    def rule_for(self, ctx: SecurityContext | None,
                 operation: str) -> PostingRuleRow | None:
        require_permission(ctx, "commerce.reports")
        with self.db.session_scope() as session:
            rule = session.execute(
                select(PostingRule).where(PostingRule.operation == operation,
                                          PostingRule.is_active.is_(True))
            ).scalars().first()
            return self._rule_row(rule) if rule else None

    def ensure_default_rules(self, ctx: SecurityContext | None) -> int:
        """Seed a rule for every operation that has none yet.

        Accounts are resolved from the company's own chart; when the standard
        code is missing the line is skipped, so the rule may start incomplete and
        the settings page will show exactly what still needs to be chosen.
        """
        require_permission(ctx, "commerce.settings")
        created = 0
        with self.db.session_scope() as session:
            existing = {rule.operation for rule in
                        session.execute(select(PostingRule)).scalars()}
            for operation, template in DEFAULT_RULE_TEMPLATES.items():
                if operation in existing:
                    continue
                rule = PostingRule(
                    operation=operation,
                    title_fa=POSTING_TITLES_FA.get(operation, operation),
                    is_active=True,
                    note="الگوی پیشنهادی؛ حساب‌ها از کدینگ شرکت خوانده شده است.",
                )
                for index, (side, source, account_code) in enumerate(template, start=1):
                    account = session.execute(
                        select(Account).where(Account.code == account_code)).scalars().first()
                    if account is None:
                        continue
                    rule.lines.append(PostingRuleLine(
                        line_no=len(rule.lines) + 1, side=side, account_id=account.id,
                        amount_source=source,
                        description=AMOUNT_SOURCE_TITLES_FA.get(source, source),
                    ))
                session.add(rule)
                created += 1
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="posting_rule", entity_id=None, action="seed",
                summary_fa=f"ایجاد {created} الگوی ثبت پیش‌فرض بازرگانی",
                session=session)
        return created

    # ---------------------------------------------------------------- writes
    def save_rule(self, ctx: SecurityContext | None, operation: str, *,
                  title_fa: str | None = None, is_active: bool = True,
                  lines: tuple[tuple[str, int, str, str], ...] = (),
                  note: str = "") -> PostingRuleRow:
        """Replace the lines of ``operation``'s rule.

        ``lines`` is ``(side, account_id, amount_source, description)``.
        """
        require_permission(ctx, "commerce.settings")
        if operation not in POSTING_OPERATIONS:
            raise ValidationError("عملیات ثبت معتبر نیست.", field="operation")
        if not lines:
            raise ValidationError("الگوی ثبت باید حداقل یک ردیف داشته باشد.")
        with self.db.session_scope() as session:
            rule = session.execute(
                select(PostingRule).where(PostingRule.operation == operation)
            ).scalars().first()
            if rule is None:
                rule = PostingRule(operation=operation,
                                   title_fa=POSTING_TITLES_FA.get(operation, operation))
                session.add(rule)
                session.flush()
            rule.title_fa = clean_text(title_fa or rule.title_fa, field="title_fa",
                                       label="عنوان الگو", required=True, max_length=120)
            rule.is_active = bool(is_active)
            rule.note = clean_text(note, field="note", label="توضیح", max_length=500)
            rule.lines.clear()
            for index, (side, account_id, source, description) in enumerate(lines, start=1):
                if side not in CC.SIDES:
                    raise ValidationError(f"ردیف {index}: طرف حساب نامعتبر است.",
                                          field="side")
                if source not in AMOUNT_SOURCES:
                    raise ValidationError(f"ردیف {index}: منبع مبلغ نامعتبر است.",
                                          field="amount_source")
                account = get_or_404(session, Account, account_id,
                                     f"ردیف {index}: حساب یافت نشد.")
                if account.level != AC.LEVEL_SUBSIDIARY:
                    raise ValidationError(
                        f"ردیف {index}: فقط حساب معین قابل استفاده است.", field="account_id")
                if not account.is_active:
                    raise ValidationError(f"ردیف {index}: حساب غیرفعال است.",
                                          field="account_id")
                rule.lines.append(PostingRuleLine(
                    line_no=index, side=side, account_id=account.id,
                    amount_source=source,
                    description=clean_text(description, field="description",
                                           label="شرح", max_length=200),
                ))
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError("ذخیرهٔ الگوی ثبت با خطا مواجه شد.") from exc
            self.audit.log_audit(
                ctx=ctx, entity_type="posting_rule", entity_id=rule.id, action="update",
                summary_fa=f"ذخیرهٔ الگوی ثبت «{rule.title_fa}»",
                after={"lines": len(rule.lines)}, session=session)
            return self._rule_row(rule)

    # ---------------------------------------------------------------- engine
    def build_entry(self, session, *, operation: str, components: dict[str, Decimal],
                    party_detail_id: int | None, party_account_hint_id: int | None,
                    description: str, dynamic_accounts: dict[str, int] | None = None,
                    counter_account_id: int | None = None) -> EntryDraft:
        """Turn the components into a balanced, ready-to-post journal draft.

        Two documents-specific hooks keep the patterns flexible without ever
        hard-coding an account in code:

        * ``dynamic_accounts`` supplies the account for rule lines whose amount
          source is one of :data:`pars_erp.treasury.constants.DYNAMIC_SOURCES`
          (``fund``, ``fund_from``, ``fund_to``) - that is how one receipt
          pattern works for *any* cash box or bank account;
        * ``counter_account_id`` replaces the account of the non-fund line when a
          payment is an expense or salary payment (no supplier involved).
        """
        rule = session.execute(
            select(PostingRule).where(PostingRule.operation == operation,
                                      PostingRule.is_active.is_(True))
        ).scalars().first()
        if rule is None:
            raise ValidationError(
                f"الگوی ثبت حسابداری برای «{POSTING_TITLES_FA.get(operation, operation)}» "
                "تعریف نشده است. در تنظیمات بازرگانی آن را تعریف کنید.")
        dynamic_accounts = dynamic_accounts or {}
        lines: list[EntryLine] = []
        total_debit = ZERO
        total_credit = ZERO
        for rule_line in rule.lines:
            if rule_line.side not in CC.SIDES:
                raise ValidationError("الگوی ثبت شامل طرف حساب نامعتبر است.")
            amount = to_money(components.get(rule_line.amount_source, ZERO),
                              field="amount_source")
            if amount == 0:
                continue
            account_id = rule_line.account_id
            detail_id = None
            if rule_line.amount_source in TC.DYNAMIC_SOURCES:
                account_id = dynamic_accounts.get(rule_line.amount_source)
                if not account_id:
                    raise ValidationError(
                        "حساب صندوق/بانک سند برای ثبت سند حسابداری مشخص نشده است.",
                        field="fund")
            elif (party_detail_id and party_account_hint_id
                    and rule_line.account_id == party_account_hint_id):
                detail_id = party_detail_id
            elif counter_account_id and rule_line.amount_source == TC.SRC_AMOUNT:
                # expense/salary payments replace the payable line with the
                # expense account chosen on the document
                account_id = counter_account_id
            text = (rule_line.description or "").strip() or description
            if rule_line.side == CC.SIDE_DEBIT:
                lines.append(EntryLine(account_id=account_id, debit=amount,
                                       credit=ZERO, description=text[:300],
                                       detail_id=detail_id))
                total_debit += amount
            else:
                lines.append(EntryLine(account_id=account_id, debit=ZERO,
                                       credit=amount, description=text[:300],
                                       detail_id=detail_id))
                total_credit += amount
        if not lines:
            raise ValidationError("مبلغ قابل ثبت در این سند صفر است؛ الگوی ثبت را بررسی کنید.")
        draft = EntryDraft(lines=tuple(lines), total_debit=total_debit,
                           total_credit=total_credit)
        if not draft.is_balanced:
            raise ValidationError(
                "الگوی ثبت حسابداری تراز نیست "
                f"(بدهکار {total_debit} / بستانکار {total_credit}). "
                "الگوی تنظیمات بازرگانی را اصلاح کنید.")
        return draft

    # ------------------------------------------------------------- internals
    @staticmethod
    def _rule_row(rule: PostingRule) -> PostingRuleRow:
        return PostingRuleRow(
            id=rule.id, operation=rule.operation,
            operation_fa=POSTING_TITLES_FA.get(rule.operation, rule.operation),
            title_fa=rule.title_fa, is_active=rule.is_active, note=rule.note or "",
            lines=tuple(RuleLineRow(
                id=line.id, line_no=line.line_no, side=line.side,
                side_fa=CC.SIDE_TITLES_FA.get(line.side, line.side),
                account_id=line.account_id,
                account_label=(f"{line.account.code} — {line.account.title_fa}"
                               if line.account else ""),
                amount_source=line.amount_source,
                amount_source_fa=AMOUNT_SOURCE_TITLES_FA.get(line.amount_source,
                                                              line.amount_source),
                description=line.description or "") for line in rule.lines))
