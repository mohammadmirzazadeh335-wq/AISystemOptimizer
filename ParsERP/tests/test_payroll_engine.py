"""Unit tests for the pure payroll and depreciation formulas (no database)."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from pars_erp.assets import constants as A
from pars_erp.assets.depreciation import (
    book_value,
    build_schedule,
    first_period,
    monthly_amount,
    months_between,
    period_end_date,
)
from pars_erp.payroll import constants as P
from pars_erp.payroll.engine import (
    PayInputs,
    calculate,
    hourly_rate,
    overtime_amount,
    percent_of,
    progressive_tax,
    round_to_step,
)

D = Decimal


# --------------------------------------------------------------------- money
def test_round_to_step_respects_configured_granularity():
    assert round_to_step(D("12345.67"), D("1000")) == D("12000.00")
    assert round_to_step(D("12500"), D("1000")) == D("13000.00")
    assert round_to_step(D("12345.678"), D("0")) == D("12345.68")


def test_percent_of_uses_decimal_only():
    assert percent_of(D("1000000"), D("7")) == D("70000.00")
    assert percent_of(D("1000000"), None) == D("0.00")


def test_progressive_tax_slices_each_bracket():
    brackets = [(D("0"), D("10000000"), D("10")),
                (D("10000000"), None, D("15"))]
    # 10,000,000 at 10% + the next 10,000,000 at 15%
    assert progressive_tax(D("20000000"), brackets) == D("2500000.00")
    assert progressive_tax(D("0"), brackets) == D("0.00")


def test_progressive_tax_without_brackets_is_zero():
    assert progressive_tax(D("5000000"), []) == D("0.00")


def test_hourly_and_overtime_amounts():
    assert hourly_rate(D("17600000"), D("176")) == D("100000")
    assert overtime_amount(D("17600000"), D("10"), D("176"), D("1.4")) == D("1400000.00")
    assert overtime_amount(D("17600000"), D("0"), D("176"), D("1.4")) == D("0.00")
    assert hourly_rate(D("1000000"), D("0")) == D("0")


# ------------------------------------------------------------------- payroll
def test_empty_settings_produce_zero_tax_and_insurance_with_a_note():
    result = calculate(PayInputs(base_salary=D("20000000"), worked_days=D("30")))
    assert result.gross == D("20000000.00")
    assert result.income_tax == D("0.00")
    assert result.insurance_employee == D("0.00")
    assert any("بیمه" in note for note in result.notes)
    assert any("مالیات" in note for note in result.notes)


def test_full_payslip_arithmetic_is_balanced():
    result = calculate(PayInputs(
        base_salary=D("30000000"), worked_days=D("30"), work_days_per_month=D("30"),
        base_hours_per_month=D("176"), overtime_hours=D("10"),
        overtime_factor=D("1.4"), housing_allowance=D("1000000"),
        food_allowance=D("800000"), child_allowance_per_child=D("300000"),
        children_count=2, insurance_employee_rate=D("7"),
        insurance_employer_rate=D("23"), tax_exempt_amount=D("5000000"),
        tax_brackets=((D("0"), D("10000000"), D("10")),
                      (D("10000000"), None, D("15"))),
        absence_deduction_per_day=D("0"), loan_installment=D("2000000"),
        other_deductions=D("100000")))

    # overtime = 30,000,000/176 × 10 × 1.4
    assert result.overtime_amount == D("2386363.64")
    assert result.benefits_total == D("2400000.00")   # 1,000,000 + 800,000 + 600,000
    assert result.gross == D("34786363.64")
    # insurance base = base + continuous benefits (bonus and overtime excluded)
    assert result.insurance_employee == D("2268000.00")  # 7% of 32,400,000
    assert result.insurance_employer == D("7452000.00")
    taxable = result.gross - result.insurance_employee - D("5000000")
    assert result.income_tax == progressive_tax(
        taxable, ((D("0"), D("10000000"), D("10")),
                  (D("10000000"), None, D("15"))))
    assert result.net == result.gross - result.deductions_total
    assert result.deductions_total == (
        result.insurance_employee + result.income_tax
        + result.absence_deduction + result.loan_installment
        + result.advance_deduction + result.other_deductions)


def test_insurance_base_is_capped_when_configured():
    result = calculate(PayInputs(
        base_salary=D("100000000"), insurance_employee_rate=D("7"),
        insurance_base_cap=D("50000000")))
    assert result.insurance_employee == D("3500000.00")


def test_absence_is_deducted_from_daily_rate():
    result = calculate(PayInputs(
        base_salary=D("30000000"), work_days_per_month=D("30"), absent_days=D("2")))
    assert result.absence_deduction == D("2000000.00")
    assert result.gross == D("30000000.00")
    assert result.net == D("28000000.00")


def test_deductions_never_push_the_net_below_zero():
    result = calculate(PayInputs(
        base_salary=D("1000000"), other_deductions=D("5000000")))
    assert result.net == D("0.00")
    assert any("خالص" in note for note in result.notes)


def test_payslip_lines_cover_both_sides():
    result = calculate(PayInputs(
        base_salary=D("10000000"), housing_allowance=D("500000"),
        insurance_employee_rate=D("7"), loan_installment=D("1000000")))
    sides = {line.side for line in result.lines}
    assert sides == {"earning", "deduction"}
    kinds = {line.kind for line in result.lines}
    assert P.LINE_BASE in kinds and P.LINE_HOUSING in kinds
    assert P.LINE_INSURANCE in kinds and P.LINE_LOAN in kinds


def test_worked_days_are_reported_not_used_to_prorate_base():
    """The contract salary is the base; absence is a deduction, not a pro-rata cut."""
    full = calculate(PayInputs(base_salary=D("10000000"), worked_days=D("30")))
    part = calculate(PayInputs(base_salary=D("10000000"), worked_days=D("15")))
    assert full.base_salary == part.base_salary == D("10000000.00")


# -------------------------------------------------------------- depreciation
def test_straight_line_monthly_amount():
    amount = monthly_amount(method=A.METHOD_STRAIGHT_LINE,
                            initial_value=D("12000000"), salvage_value=D("0"),
                            useful_life_months=12, accumulated=D("0"))
    assert amount == D("1000000.00")


def test_straight_line_never_dips_below_salvage():
    amount = monthly_amount(method=A.METHOD_STRAIGHT_LINE,
                            initial_value=D("1000000"), salvage_value=D("100000"),
                            useful_life_months=12, accumulated=D("890000"))
    assert amount == D("10000.00")     # only the remaining 10,000 is depreciable
    fully = monthly_amount(method=A.METHOD_STRAIGHT_LINE,
                           initial_value=D("1000000"), salvage_value=D("100000"),
                           useful_life_months=12, accumulated=D("900000"))
    assert fully == D("0.00")


def test_declining_balance_uses_the_current_book_value():
    amount = monthly_amount(method=A.METHOD_DECLINING, initial_value=D("12000000"),
                            salvage_value=D("0"), useful_life_months=60,
                            accumulated=D("0"), declining_rate=D("24"))
    assert amount == D("240000.00")   # 12,000,000 × 24% ÷ 12
    later = monthly_amount(method=A.METHOD_DECLINING, initial_value=D("12000000"),
                           salvage_value=D("0"), useful_life_months=60,
                           accumulated=D("6000000"), declining_rate=D("24"))
    assert later == D("120000.00")


def test_units_of_production_needs_a_reading():
    amount = monthly_amount(method=A.METHOD_UNITS, initial_value=D("1000000"),
                            salvage_value=D("0"), useful_life_months=12,
                            accumulated=D("0"), units_period=D("100"),
                            total_units=D("1000"))
    assert amount == D("100000.00")
    assert monthly_amount(method=A.METHOD_UNITS, initial_value=D("1000000"),
                          salvage_value=D("0"), useful_life_months=12,
                          accumulated=D("0"), units_period=D("0"),
                          total_units=D("1000")) == D("0.00")


def test_first_period_and_month_end_in_jalali():
    # 1405/01/31 = 2026-04-20
    assert first_period(_dt.date(2026, 4, 20)) == (1405, 1)
    assert first_period(_dt.date(2026, 4, 20), next_month=True) == (1405, 2)
    assert period_end_date(1405, 1) == _dt.date(2026, 4, 20)
    assert months_between(1404, 12, 1405, 2) == 2


def test_schedule_stops_at_the_salvage_floor():
    schedule = build_schedule(method=A.METHOD_STRAIGHT_LINE,
                              initial_value=D("1200000"), salvage_value=D("0"),
                              useful_life_months=12, start_year=1405,
                              start_month=1, months=14)
    assert len(schedule) == 14
    assert sum(schedule) == D("1200000.00")
    assert schedule[-1] == D("0.00")
    assert book_value(D("1200000"), sum(schedule)) == D("0.00")


def test_unknown_method_returns_zero():
    assert monthly_amount(method="magic", initial_value=D("1000"),
                          salvage_value=D("0"), useful_life_months=12,
                          accumulated=D("0")) == D("0.00")
