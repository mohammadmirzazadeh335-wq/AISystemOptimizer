"""Bank reconciliation: import the bank's statement, match it, explain differences.

The service never posts anything by itself. An unmatched statement line becomes a
*suggested* correction; only an explicit, permitted ``create_adjustment`` call
writes a journal entry, and that entry is linked to the line it explains.
"""

from __future__ import annotations

import csv
import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from pars_erp.core.errors import NotFoundError, ValidationError
from pars_erp.db.models import (
    Account,
    BankAccount,
    BankStatement,
    BankStatementLine,
    Payment,
    Receipt,
)
from pars_erp.db.session import Database
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.audit_service import AuditService
from pars_erp.services.commerce_common import ZERO, clean_text, get_or_404, to_money
from pars_erp.services.treasury_common import (
    fund_balance,
    post_system_journal,
    reverse_journal,
)
from pars_erp.treasury import constants as TC

MONEY = Decimal("0.01")
DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y")


@dataclass(frozen=True)
class StatementLineInput:
    tx_date: _dt.date
    description: str = ""
    reference: str = ""
    amount_in: Decimal | str | int = 0
    amount_out: Decimal | str | int = 0


@dataclass(frozen=True)
class StatementRow:
    id: int
    bank_account_id: int
    bank_label: str
    statement_date: _dt.date
    period_start: _dt.date
    period_end: _dt.date
    opening_balance: Decimal
    closing_balance: Decimal
    status: str
    status_fa: str
    file_name: str
    note: str
    line_count: int
    matched_count: int
    unmatched_count: int

    @property
    def display(self) -> str:
        return f"{self.bank_label} — {self.period_start} تا {self.period_end}"


@dataclass(frozen=True)
class StatementLineRow:
    id: int
    statement_id: int
    tx_date: _dt.date
    description: str
    reference: str
    amount_in: Decimal
    amount_out: Decimal
    status: str
    status_fa: str
    matched_kind: str
    matched_id: int | None
    matched_label: str
    note: str
    journal_id: int | None

    @property
    def amount(self) -> Decimal:
        return self.amount_in - self.amount_out


@dataclass(frozen=True)
class SuggestionRow:
    line_id: int
    tx_date: _dt.date
    amount: Decimal
    direction: str
    kind: str
    document_id: int
    number: str
    party_name: str
    reason_fa: str


class ReconciliationService:
    def __init__(self, db: Database, audit: AuditService, *, journals) -> None:
        self.db = db
        self.audit = audit
        self.journals = journals

    # ------------------------------------------------------------- statements
    def create_statement(self, ctx: SecurityContext | None, *, bank_account_id: int,
                         statement_date: _dt.date, period_start: _dt.date,
                         period_end: _dt.date, opening_balance=0, closing_balance=0,
                         file_name: str = "", note: str = "",
                         lines: tuple[StatementLineInput, ...] = ()) -> StatementRow:
        require_permission(ctx, "reconciliation.manage")
        if period_end < period_start:
            raise ValidationError("پایان دوره نباید قبل از شروع آن باشد.", field="period_end")
        with self.db.session_scope() as session:
            get_or_404(session, BankAccount, bank_account_id, "حساب بانکی یافت نشد.")
            statement = BankStatement(
                bank_account_id=bank_account_id, statement_date=statement_date,
                period_start=period_start, period_end=period_end,
                opening_balance=to_money(opening_balance, field="opening_balance"),
                closing_balance=to_money(closing_balance, field="closing_balance"),
                file_name=clean_text(file_name, field="file_name", label="نام فایل",
                                     max_length=255),
                note=clean_text(note, field="note", label="توضیح", max_length=500),
                created_by_id=getattr(ctx, "user_id", None))
            session.add(statement)
            session.flush()
            for entry in lines:
                self._add_line(session, statement, entry)
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="bank_statement", entity_id=statement.id,
                action="create", summary_fa="ثبت صورت‌حساب بانکی",
                after={"lines": len(statement.lines)}, session=session)
            return self._statement_row(session, statement)

    def import_file(self, ctx: SecurityContext | None, *, bank_account_id: int,
                    path: str | Path, statement_date: _dt.date | None = None) -> StatementRow:
        """Import a CSV/Excel statement (columns: date, description, reference, in, out)."""
        require_permission(ctx, "reconciliation.manage")
        file_path = Path(path)
        if not file_path.exists():
            raise NotFoundError("فایل صورت‌حساب یافت نشد.")
        rows = (self._read_excel(file_path) if file_path.suffix.lower() in (".xlsx", ".xlsm")
                else self._read_csv(file_path))
        if not rows:
            raise ValidationError("فایل انتخاب‌شده هیچ ردیف قابل خواندنی ندارد.")
        dates = [row.tx_date for row in rows]
        return self.create_statement(
            ctx, bank_account_id=bank_account_id,
            statement_date=statement_date or max(dates),
            period_start=min(dates), period_end=max(dates), file_name=file_path.name,
            lines=tuple(rows))

    def list_statements(self, ctx: SecurityContext | None, *,
                        bank_account_id: int | None = None) -> list[StatementRow]:
        require_permission(ctx, "reconciliation.manage")
        query = select(BankStatement).order_by(BankStatement.period_end.desc())
        if bank_account_id:
            query = query.where(BankStatement.bank_account_id == bank_account_id)
        with self.db.session_scope() as session:
            return [self._statement_row(session, row)
                    for row in session.execute(query).scalars()]

    def statement_lines(self, ctx: SecurityContext | None,
                        statement_id: int) -> list[StatementLineRow]:
        require_permission(ctx, "reconciliation.manage")
        with self.db.session_scope() as session:
            statement = get_or_404(session, BankStatement, statement_id,
                                   "صورت‌حساب یافت نشد.")
            return [self._line_row(session, line) for line in statement.lines]

    # ---------------------------------------------------------------- matching
    def suggestions(self, ctx: SecurityContext | None,
                    statement_id: int) -> list[SuggestionRow]:
        require_permission(ctx, "reconciliation.manage")
        with self.db.session_scope() as session:
            statement = get_or_404(session, BankStatement, statement_id,
                                   "صورت‌حساب یافت نشد.")
            used_receipts = {line.matched_id for line in statement.lines
                             if line.matched_kind == "receipt"}
            used_payments = {line.matched_id for line in statement.lines
                             if line.matched_kind == "payment"}
            result: list[SuggestionRow] = []
            for line in statement.lines:
                if line.status != TC.LINE_UNMATCHED:
                    continue
                if line.amount_in > 0:
                    candidates = session.execute(select(Receipt).where(
                        Receipt.bank_account_id == statement.bank_account_id,
                        Receipt.status == TC.STATUS_POSTED)).scalars()
                    kind = "receipt"
                    used = used_receipts
                else:
                    candidates = session.execute(select(Payment).where(
                        Payment.bank_account_id == statement.bank_account_id,
                        Payment.status == TC.STATUS_POSTED)).scalars()
                    kind = "payment"
                    used = used_payments
                for doc in candidates:
                    if doc.id in used:
                        continue
                    amount = Decimal(doc.base_amount)
                    if amount != abs(line.signed_amount):
                        continue
                    delta = abs((doc.receipt_date if kind == "receipt"
                                 else doc.payment_date) - line.tx_date).days
                    if delta > 5:
                        continue
                    reason = ("مبلغ و تاریخ نزدیک" if delta <= 1
                              else f"مبلغ یکسان، اختلاف تاریخ {delta} روز")
                    if line.reference and doc.tracking_no \
                            and line.reference.strip() == (doc.tracking_no or "").strip():
                        reason = "مبلغ و شماره پیگیری یکسان"
                    result.append(SuggestionRow(
                        line_id=line.id, tx_date=line.tx_date,
                        amount=abs(line.signed_amount), direction=line.status, kind=kind,
                        document_id=doc.id, number=doc.number,
                        party_name=(doc.payer_name if kind == "receipt" else doc.payee_name)
                        or "", reason_fa=reason))
            return result

    def auto_match(self, ctx: SecurityContext | None, statement_id: int) -> dict:
        """Match every line that has exactly one unambiguous candidate."""
        require_permission(ctx, "reconciliation.manage")
        suggestions = self.suggestions(ctx, statement_id)
        grouped: dict[int, list[SuggestionRow]] = {}
        for suggestion in suggestions:
            grouped.setdefault(suggestion.line_id, []).append(suggestion)
        matched = 0
        ambiguous = 0
        with self.db.session_scope() as session:
            for line_id, options in grouped.items():
                if len(options) != 1:
                    ambiguous += 1
                    continue
                option = options[0]
                line = session.get(BankStatementLine, line_id)
                if line is None:  # pragma: no cover - race guard
                    continue
                line.status = TC.LINE_MATCHED
                line.matched_kind = option.kind
                line.matched_id = option.document_id
                line.note = f"تطبیق خودکار: {option.reason_fa}"
                matched += 1
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="bank_statement", entity_id=statement_id,
                action="auto_match", summary_fa=f"تطبیق خودکار {matched} ردیف",
                after={"matched": matched, "ambiguous": ambiguous}, session=session)
        return {"matched": matched, "ambiguous": ambiguous,
                "unmatched": len(grouped) - matched}

    def match_manually(self, ctx: SecurityContext | None, line_id: int, *,
                       kind: str, document_id: int) -> StatementLineRow:
        require_permission(ctx, "reconciliation.manage")
        if kind not in ("receipt", "payment"):
            raise ValidationError("نوع سند تطبیق معتبر نیست.", field="kind")
        with self.db.session_scope() as session:
            line = get_or_404(session, BankStatementLine, line_id, "ردیف صورت‌حساب یافت نشد.")
            statement = session.get(BankStatement, line.statement_id)
            model = Receipt if kind == "receipt" else Payment
            document = get_or_404(session, model, document_id, "سند مورد نظر یافت نشد.")
            if statement and document.bank_account_id != statement.bank_account_id:
                raise ValidationError("سند به حساب بانکی این صورت‌حساب تعلق ندارد.",
                                      field="document_id")
            amount = Decimal(document.base_amount)
            if amount != abs(line.signed_amount):
                raise ValidationError(
                    f"مبلغ سند ({amount:,}) با مبلغ ردیف صورت‌حساب ({abs(line.signed_amount):,}) "
                    "یکسان نیست.", field="document_id")
            line.status = TC.LINE_MATCHED
            line.matched_kind = kind
            line.matched_id = document.id
            line.note = "تطبیق دستی"
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="bank_statement_line", entity_id=line.id,
                action="match", summary_fa="تطبیق دستی ردیف صورت‌حساب",
                after={"kind": kind, "document_id": document.id}, session=session)
            return self._line_row(session, line)

    def unmatch(self, ctx: SecurityContext | None, line_id: int) -> StatementLineRow:
        require_permission(ctx, "reconciliation.manage")
        with self.db.session_scope() as session:
            line = get_or_404(session, BankStatementLine, line_id, "ردیف صورت‌حساب یافت نشد.")
            if line.journal_id:
                raise ValidationError(
                    "این ردیف سند اصلاحی دارد؛ ابتدا سند اصلاحی را ابطال کنید.",
                    field="line_id")
            line.status = TC.LINE_UNMATCHED
            line.matched_kind = None
            line.matched_id = None
            line.note = ""
            session.flush()
            return self._line_row(session, line)

    def ignore_line(self, ctx: SecurityContext | None, line_id: int,
                    note: str) -> StatementLineRow:
        require_permission(ctx, "reconciliation.approve")
        with self.db.session_scope() as session:
            line = get_or_404(session, BankStatementLine, line_id, "ردیف صورت‌حساب یافت نشد.")
            line.status = TC.LINE_IGNORED
            line.note = clean_text(note, field="note", label="علت اختلاف", required=True,
                                   max_length=300)
            session.flush()
            return self._line_row(session, line)

    # ------------------------------------------------------------- adjustments
    def create_adjustment(self, ctx: SecurityContext | None, line_id: int, *,
                          counter_account_id: int, reason: str) -> StatementLineRow:
        """Post the correction for one unmatched line (user approved it explicitly)."""
        require_permission(ctx, "reconciliation.approve")
        reason = clean_text(reason, field="reason", label="دلیل اصلاح", required=True,
                            max_length=300)
        if len(reason) < 5:
            raise ValidationError("دلیل اصلاح باید حداقل ۵ نویسه باشد.", field="reason")
        with self.db.session_scope() as session:
            line = get_or_404(session, BankStatementLine, line_id, "ردیف صورت‌حساب یافت نشد.")
            if line.journal_id:
                raise ValidationError("برای این ردیف قبلاً سند اصلاحی ثبت شده است.",
                                      field="line_id")
            statement = session.get(BankStatement, line.statement_id)
            bank = session.get(BankAccount, statement.bank_account_id)
            counter = get_or_404(session, Account, counter_account_id,
                                 "حساب طرف مقابل یافت نشد.")
            from pars_erp.accounting import constants as AC

            if counter.level != AC.LEVEL_SUBSIDIARY:
                raise ValidationError("حساب طرف مقابل باید معین باشد.",
                                      field="counter_account_id")
            from pars_erp.services.journals_service import JournalInput, JournalLineInput
            from pars_erp.services.posting_service import EntryDraft, EntryLine

            amount = abs(line.signed_amount)
            if amount == 0:
                raise ValidationError("ردیف بدون مبلغ قابل اصلاح نیست.", field="line_id")
            bank_side = (EntryLine(account_id=bank.account_id, debit=amount, credit=ZERO,
                                   description=f"اصلاح مغایرت بانکی: {reason}"))
            counter_side = (EntryLine(account_id=counter.id, debit=ZERO, credit=amount,
                                      description=f"اصلاح مغایرت بانکی: {reason}"))
            lines = (bank_side, counter_side) if line.amount_in > 0 else (
                EntryLine(account_id=counter.id, debit=amount, credit=ZERO,
                          description=f"اصلاح مغایرت بانکی: {reason}"),
                EntryLine(account_id=bank.account_id, debit=ZERO, credit=amount,
                          description=f"اصلاح مغایرت بانکی: {reason}"))
            draft = EntryDraft(lines=lines, total_debit=amount, total_credit=amount)
            journal = post_system_journal(
                session, journals=self.journals, ctx=ctx, entry_date=line.tx_date,
                title_fa=f"اصلاح مغایرت بانکی — {bank.bank_name}",
                reference_no=statement.file_name or "statement",
                idempotency_key=f"statement-line:{line.id}:adjust",
                notes=reason, draft=draft, source_kind="bank_reconciliation",
                source_id=line.id)
            line.journal_id = journal.id
            line.status = TC.LINE_MATCHED
            line.matched_kind = "journal"
            line.matched_id = journal.id
            line.note = reason
            session.flush()
            self.audit.log_audit(
                ctx=ctx, entity_type="bank_statement_line", entity_id=line.id,
                action="adjust", summary_fa="ثبت سند اصلاحی مغایرت بانکی",
                after={"journal_id": journal.id}, session=session)
            return self._line_row(session, line)

    # ---------------------------------------------------------------- reporting
    def discrepancy_report(self, ctx: SecurityContext | None,
                           statement_id: int) -> dict:
        require_permission(ctx, "reconciliation.manage")
        with self.db.session_scope() as session:
            statement = get_or_404(session, BankStatement, statement_id,
                                   "صورت‌حساب یافت نشد.")
            bank = session.get(BankAccount, statement.bank_account_id)
            ledger = fund_balance(session, bank_account_id=statement.bank_account_id)
            matched = sum((line.signed_amount for line in statement.lines
                           if line.status == TC.LINE_MATCHED), ZERO)
            unmatched = [self._line_row(session, line) for line in statement.lines
                         if line.status == TC.LINE_UNMATCHED]
            reconciled = (Decimal(statement.opening_balance) + matched).quantize(MONEY)
            return {
                "statement_id": statement.id,
                "bank_label": (f"{bank.bank_name} — {bank.account_number}"
                               if bank else ""),
                "statement_opening": Decimal(statement.opening_balance),
                "statement_closing": Decimal(statement.closing_balance),
                "open_balance_according_to_documents": ledger,
                "matched_amount": matched,
                "expected_balance": reconciled,
                "difference": (Decimal(statement.closing_balance) - reconciled
                               ).quantize(MONEY),
                "unmatched_lines": unmatched,
            }

    # ---------------------------------------------------------------- internals
    def _add_line(self, session, statement: BankStatement,
                  entry: StatementLineInput) -> None:
        amount_in = to_money(entry.amount_in, field="amount_in")
        amount_out = to_money(entry.amount_out, field="amount_out")
        if amount_in < 0 or amount_out < 0:
            raise ValidationError("مبلغ ردیف صورت‌حساب نمی‌تواند منفی باشد.",
                                  field="amount_in")
        if amount_in == 0 and amount_out == 0:
            raise ValidationError(
                "هر ردیف صورت‌حساب باید مبلغ واریز یا برداشت داشته باشد.",
                field="amount_in")
        session.add(BankStatementLine(
            statement_id=statement.id, tx_date=entry.tx_date,
            description=clean_text(entry.description, field="description",
                                   label="شرح", max_length=300),
            reference=clean_text(entry.reference, field="reference", label="شماره مرجع",
                                 max_length=80),
            amount_in=amount_in, amount_out=amount_out, status=TC.LINE_UNMATCHED))

    @staticmethod
    def _parse_date(text: str) -> _dt.date:
        text = (text or "").strip()
        for fmt in DATE_FORMATS:
            try:
                return _dt.datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        raise ValidationError(f"تاریخ «{text}» در فایل قابل خواندن نیست.",
                              field="tx_date")

    def _read_csv(self, path: Path) -> list[StatementLineInput]:
        rows: list[StatementLineInput] = []
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for raw in reader:
                normalised = {(key or "").strip().lower(): (value or "").strip()
                              for key, value in raw.items()}
                if not normalised.get("date"):
                    continue
                if not (normalised.get("in") or normalised.get("credit")
                        or normalised.get("out") or normalised.get("debit")):
                    continue  # a totals/blank row, not a transaction
                rows.append(StatementLineInput(
                    tx_date=self._parse_date(normalised["date"]),
                    description=normalised.get("description", ""),
                    reference=normalised.get("reference", ""),
                    amount_in=normalised.get("in") or normalised.get("credit") or 0,
                    amount_out=normalised.get("out") or normalised.get("debit") or 0))
        return rows

    def _read_excel(self, path: Path) -> list[StatementLineInput]:
        try:
            from openpyxl import load_workbook
        except Exception as exc:  # pragma: no cover
            raise ValidationError("خواندن فایل Excel نیازمند بستهٔ openpyxl است.") from exc
        workbook = load_workbook(path, data_only=True, read_only=True)
        sheet = workbook.active
        headers = [str(cell.value or "").strip().lower()
                   for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
        index = {name: position for position, name in enumerate(headers)}
        rows: list[StatementLineInput] = []
        for values in sheet.iter_rows(min_row=2, values_only=True):
            if not values or values[index.get("date", 0)] in (None, ""):
                continue

            def cell(key: str):
                position = index.get(key)
                return values[position] if position is not None and position < len(values) else ""

            raw_date = cell("date")
            if isinstance(raw_date, _dt.datetime):
                tx_date = raw_date.date()
            else:
                tx_date = self._parse_date(str(raw_date))
            rows.append(StatementLineInput(
                tx_date=tx_date, description=str(cell("description") or ""),
                reference=str(cell("reference") or ""),
                amount_in=cell("in") or cell("credit") or 0,
                amount_out=cell("out") or cell("debit") or 0))
        workbook.close()
        return rows

    def _statement_row(self, session, statement: BankStatement) -> StatementRow:
        bank = session.get(BankAccount, statement.bank_account_id)
        matched = sum(1 for line in statement.lines if line.status == TC.LINE_MATCHED)
        return StatementRow(
            id=statement.id, bank_account_id=statement.bank_account_id,
            bank_label=(f"{bank.bank_name} — {bank.account_number}" if bank else ""),
            statement_date=statement.statement_date, period_start=statement.period_start,
            period_end=statement.period_end,
            opening_balance=Decimal(statement.opening_balance),
            closing_balance=Decimal(statement.closing_balance), status=statement.status,
            status_fa=TC.RECON_STATUS_TITLES_FA.get(statement.status, statement.status),
            file_name=statement.file_name or "", note=statement.note or "",
            line_count=len(statement.lines), matched_count=matched,
            unmatched_count=len(statement.lines) - matched)

    def _line_row(self, session, line: BankStatementLine) -> StatementLineRow:
        label = ""
        if line.matched_kind in ("receipt", "payment") and line.matched_id:
            document = session.get(Receipt if line.matched_kind == "receipt" else Payment,
                                   line.matched_id)
            label = document.number if document else ""
        elif line.matched_kind == "journal" and line.matched_id:
            from pars_erp.db.models import Journal

            journal = session.get(Journal, line.matched_id)
            label = f"سند {journal.number}" if journal else ""
        return StatementLineRow(
            id=line.id, statement_id=line.statement_id, tx_date=line.tx_date,
            description=line.description or "", reference=line.reference or "",
            amount_in=Decimal(line.amount_in), amount_out=Decimal(line.amount_out),
            status=line.status,
            status_fa=TC.LINE_STATUS_TITLES_FA.get(line.status, line.status),
            matched_kind=line.matched_kind or "", matched_id=line.matched_id,
            matched_label=label, note=line.note or "", journal_id=line.journal_id)
