"""The payroll calculation engine: pure functions, no database, no Qt.

Every rule lives in data (a dated settings version); this module only applies it.
That is deliberate: the formulas below can be unit-tested on their own, and an
accountant can change a rate without a code change - and an old, approved month
is never recalculated because the run stores the version it used.

The engine never invents a statutory number. If a rate is missing the settings
layer supplies ``0`` and the payslip line says so in its detail text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Sequence

from pars_erp.payroll import constants as P

HUNDRED = Decimal("100")
CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: Decimal | int | str | None) -> Decimal:
    """Round to two decimals, half-up - the only rounding money ever gets."""
    if value is None:
        return ZERO
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def round_to_step(value: Decimal, step: Decimal | None) -> Decimal:
    """Round to a configured step (e.g. 1,000 ریال); a zero step means 0.01."""
    step = money(step or CENT)
    if step <= CENT:
        return money(value)
    units = (value / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return money(units * step)


def percent_of(base: Decimal, rate_percent: Decimal | None) -> Decimal:
    if not rate_percent:
        return ZERO
    return money(Decimal(base) * Decimal(rate_percent) / HUNDRED)


def hourly_rate(base_salary: Decimal, base_hours_per_month: Decimal | None) -> Decimal:
    hours = Decimal(base_hours_per_month or 0)
    if hours <= 0:
        return ZERO
    return (Decimal(base_salary) / hours)


def daily_rate(base_salary: Decimal, work_days_per_month: Decimal | None) -> Decimal:
    days = Decimal(work_days_per_month or 0)
    if days <= 0:
        return ZERO
    return (Decimal(base_salary) / days)


def overtime_amount(base_salary: Decimal, hours: Decimal,
                    base_hours_per_month: Decimal | None,
                    factor: Decimal | None) -> Decimal:
    if not hours:
        return ZERO
    return money(hourly_rate(base_salary, base_hours_per_month) * Decimal(hours)
                 * Decimal(factor or 0))


def seniority_amount(years: Decimal | int, per_year: Decimal | None) -> Decimal:
    if not per_year or not years:
        return ZERO
    return money(Decimal(years) * Decimal(per_year))


def progressive_tax(taxable: Decimal,
                    brackets: Iterable[tuple[Decimal, Decimal | None, Decimal]]) -> Decimal:
    """Apply dated brackets ``(from, to, rate_percent)``; ``to=None`` is the top."""
    remaining = Decimal(taxable)
    if remaining <= 0:
        return ZERO
    total = ZERO
    for start, end, rate in sorted(brackets, key=lambda row: row[0]):
        if remaining <= 0:
            break
        start = Decimal(start or 0)
        if taxable <= start:
            break
        upper = Decimal(end) if end is not None else taxable
        slice_top = min(Decimal(taxable), upper)
        slice_amount = slice_top - start
        if slice_amount <= 0:
            continue
        total += slice_amount * Decimal(rate or 0) / HUNDRED
    return money(total)


@dataclass(frozen=True)
class PayInputs:
    """Everything the engine needs for one employee and one month."""

    base_salary: Decimal = ZERO
    worked_days: Decimal = ZERO
    absent_days: Decimal = ZERO
    paid_leave_days: Decimal = ZERO
    overtime_hours: Decimal = ZERO
    holiday_overtime_hours: Decimal = ZERO
    work_days_per_month: Decimal = Decimal("30")
    base_hours_per_month: Decimal = Decimal("176")
    overtime_factor: Decimal = Decimal("1.4")
    holiday_overtime_factor: Decimal = Decimal("2")
    housing_allowance: Decimal = ZERO
    food_allowance: Decimal = ZERO
    child_allowance_per_child: Decimal = ZERO
    children_count: int = 0
    marriage_allowance: Decimal = ZERO
    is_married: bool = False
    seniority_years: Decimal = ZERO
    seniority_allowance_per_year: Decimal = ZERO
    continuous_benefit: Decimal = ZERO
    non_continuous_benefit: Decimal = ZERO
    bonus: Decimal = ZERO
    mission_allowance: Decimal = ZERO
    insurance_employee_rate: Decimal = ZERO
    insurance_employer_rate: Decimal = ZERO
    insurance_base_cap: Decimal = ZERO
    tax_exempt_amount: Decimal = ZERO
    tax_brackets: Sequence[tuple[Decimal, Decimal | None, Decimal]] = field(
        default_factory=tuple)
    absence_deduction_per_day: Decimal = ZERO
    loan_installment: Decimal = ZERO
    advance_deduction: Decimal = ZERO
    other_deductions: Decimal = ZERO
    rounding_step: Decimal = CENT
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PayLine:
    kind: str
    title_fa: str
    side: str  # "earning" | "deduction"
    amount: Decimal
    detail: str = ""


@dataclass(frozen=True)
class PayResult:
    base_salary: Decimal
    benefits_total: Decimal
    overtime_amount: Decimal
    bonus: Decimal
    gross: Decimal
    absence_deduction: Decimal
    insurance_employee: Decimal
    insurance_employer: Decimal
    income_tax: Decimal
    loan_installment: Decimal
    advance_deduction: Decimal
    other_deductions: Decimal
    deductions_total: Decimal
    net: Decimal
    lines: tuple[PayLine, ...]
    notes: tuple[str, ...] = ()

    @property
    def employer_cost(self) -> Decimal:
        return money(self.gross + self.insurance_employer)


def calculate(inputs: PayInputs) -> PayResult:
    """Turn attendance/contract/settings inputs into a payslip."""
    notes = list(inputs.notes)
    base = money(inputs.base_salary)

    continuous_parts = {
        P.LINE_HOUSING: inputs.housing_allowance,
        P.LINE_FOOD: inputs.food_allowance,
        P.LINE_CHILD: (Decimal(inputs.child_allowance_per_child or 0)
                       * Decimal(inputs.children_count or 0)),
        P.LINE_MARRIAGE: inputs.marriage_allowance if inputs.is_married else ZERO,
        P.LINE_SENIORITY: seniority_amount(inputs.seniority_years,
                                           inputs.seniority_allowance_per_year),
        P.LINE_CONTINUOUS: inputs.continuous_benefit,
        P.LINE_NON_CONTINUOUS: inputs.non_continuous_benefit,
    }
    benefits = {kind: money(value) for kind, value in continuous_parts.items()}
    benefits_total = money(sum(benefits.values(), ZERO))

    overtime = overtime_amount(base, inputs.overtime_hours,
                               inputs.base_hours_per_month, inputs.overtime_factor)
    if inputs.holiday_overtime_hours:
        overtime += overtime_amount(base, inputs.holiday_overtime_hours,
                                    inputs.base_hours_per_month,
                                    inputs.holiday_overtime_factor)
    overtime = money(overtime)
    bonus = money(Decimal(inputs.bonus or 0) + Decimal(inputs.mission_allowance or 0))

    gross = money(base + benefits_total + overtime + bonus)

    # ---- statutory-looking deductions: only what the settings actually define
    insurance_base = base + sum((benefits[kind] for kind in (
        P.LINE_HOUSING, P.LINE_FOOD, P.LINE_CHILD, P.LINE_MARRIAGE,
        P.LINE_SENIORITY, P.LINE_CONTINUOUS)), ZERO)
    if inputs.insurance_base_cap and insurance_base > inputs.insurance_base_cap:
        insurance_base = Decimal(inputs.insurance_base_cap)
    insurance_employee = percent_of(insurance_base, inputs.insurance_employee_rate)
    insurance_employer = percent_of(insurance_base, inputs.insurance_employer_rate)
    if not inputs.insurance_employee_rate and not inputs.insurance_employer_rate:
        notes.append("نرخ بیمه در نسخهٔ تنظیمات این دوره تعریف نشده است؛ بیمه صفر محاسبه شد.")

    taxable = max(ZERO, gross - insurance_employee - money(inputs.tax_exempt_amount or 0))
    if inputs.tax_brackets:
        tax = progressive_tax(taxable, inputs.tax_brackets)
    else:
        tax = ZERO
        if taxable > 0:
            notes.append("پله‌های مالیات در تنظیمات این دوره تعریف نشده است؛ مالیات صفر محاسبه شد.")

    if inputs.absence_deduction_per_day:
        absence = money(Decimal(inputs.absent_days or 0)
                        * Decimal(inputs.absence_deduction_per_day))
    else:
        absence = money(Decimal(inputs.absent_days or 0)
                        * daily_rate(base, inputs.work_days_per_month))

    loan = money(inputs.loan_installment or 0)
    advance = money(inputs.advance_deduction or 0)
    other = money(inputs.other_deductions or 0)
    deductions = money(insurance_employee + tax + absence + loan + advance + other)
    net = money(gross - deductions)
    if net < 0:
        notes.append("کسورات از حقوق ناخالص بیشتر است؛ خالص صفر در نظر گرفته شد.")
        net = ZERO

    net = round_to_step(net, inputs.rounding_step) if inputs.rounding_step != CENT else net
    deductions = money(gross - net)

    lines: list[PayLine] = [
        PayLine(P.LINE_BASE, P.LINE_TITLES_FA[P.LINE_BASE], "earning", base,
                f"{inputs.worked_days} روز کارکرد از {inputs.work_days_per_month} روز"),
    ]
    for kind, amount in benefits.items():
        if amount:
            lines.append(PayLine(kind, P.LINE_TITLES_FA[kind], "earning", amount))
    if overtime:
        lines.append(PayLine(P.LINE_OVERTIME, P.LINE_TITLES_FA[P.LINE_OVERTIME],
                             "earning", overtime,
                             f"{inputs.overtime_hours} ساعت عادی + "
                             f"{inputs.holiday_overtime_hours} ساعت تعطیل"))
    if bonus:
        lines.append(PayLine(P.LINE_BONUS, P.LINE_TITLES_FA[P.LINE_BONUS], "earning",
                             bonus))
    if absence:
        lines.append(PayLine(P.LINE_ABSENCE, P.LINE_TITLES_FA[P.LINE_ABSENCE],
                             "deduction", absence, f"{inputs.absent_days} روز غیبت"))
    if insurance_employee:
        lines.append(PayLine(P.LINE_INSURANCE, P.LINE_TITLES_FA[P.LINE_INSURANCE],
                             "deduction", insurance_employee,
                             f"{inputs.insurance_employee_rate}٪ از {insurance_base:,}"))
    if tax:
        lines.append(PayLine(P.LINE_TAX, P.LINE_TITLES_FA[P.LINE_TAX], "deduction",
                             tax, f"مبنای مشمول {taxable:,}"))
    if loan or advance:
        lines.append(PayLine(P.LINE_LOAN, P.LINE_TITLES_FA[P.LINE_LOAN], "deduction",
                             loan + advance,
                             "اقساط وام و مساعدهٔ این ماه"))
    if other:
        lines.append(PayLine(P.LINE_OTHER, P.LINE_TITLES_FA[P.LINE_OTHER], "deduction",
                             other))

    return PayResult(
        base_salary=base, benefits_total=benefits_total, overtime_amount=overtime,
        bonus=bonus, gross=gross, absence_deduction=absence,
        insurance_employee=insurance_employee, insurance_employer=insurance_employer,
        income_tax=tax, loan_installment=loan, advance_deduction=advance,
        other_deductions=other, deductions_total=deductions, net=net,
        lines=tuple(lines), notes=tuple(notes))
