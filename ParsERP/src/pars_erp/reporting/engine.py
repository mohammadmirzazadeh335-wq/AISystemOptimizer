"""Central reporting engine for Zarrin Hormoz (phase 7).

Design (see ``docs/phase7/01-reporting-engine.md``)::

    definition  = a *code* object: id, title, section, permission, allowed filters,
                  and a Python fetcher ``(ctx, query) -> ReportTable``
    query       = what the user chose (dates, warehouse, party, columns, sort, ...)
    engine      = applies column selection, search, sorting, grouping, aggregates and
                  pagination *on top of* the table the fetcher returned

Two rules make the whole module safe and boring:

* **no SQL from the UI.** A report can only ever call one of the registered
  fetchers; the fetcher itself re-checks the caller's permission through the
  service it belongs to. There is no string concatenation of SQL anywhere, so the
  report designer cannot be used to read a table the user may not see.
* **one description, four outputs.** The engine returns a
  :class:`pars_erp.services.report_render_service.ReportTable` next to the paged
  rows; the screen, the print preview, the PDF, the Excel and the CSV all use that
  same table, so a number cannot differ between them.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Iterable, Mapping, Sequence

from pars_erp.core.errors import ValidationError
from pars_erp.security.permissions import SecurityContext, require_permission
from pars_erp.services.report_render_service import (
    KIND_AMOUNT,
    KIND_NUMBER,
    ReportColumn,
    ReportTable,
)

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1000

# ----------------------------------------------------------------- filter kinds
FILTER_DATE_RANGE = "date_range"
FILTER_DATE = "date"
FILTER_SELECT = "select"
FILTER_TEXT = "text"

# ---------------------------------------------------------------- aggregations
AGG_SUM = "sum"
AGG_AVG = "avg"
AGG_COUNT = "count"
AGG_MIN = "min"
AGG_MAX = "max"
AGGREGATIONS: tuple[tuple[str, str], ...] = (
    (AGG_SUM, "جمع"),
    (AGG_AVG, "میانگین"),
    (AGG_COUNT, "تعداد"),
    (AGG_MIN, "حداقل"),
    (AGG_MAX, "حداکثر"),
)
AGGREGATION_TITLES_FA: dict[str, str] = dict(AGGREGATIONS)

NUMERIC_KINDS = (KIND_AMOUNT, KIND_NUMBER)


@dataclass(frozen=True)
class FilterSpec:
    """One filter a report accepts (the UI draws it, the fetcher honours it)."""

    key: str
    title_fa: str
    kind: str = FILTER_TEXT
    required: bool = False

    def __post_init__(self) -> None:
        if self.kind not in (FILTER_DATE_RANGE, FILTER_DATE, FILTER_SELECT, FILTER_TEXT):
            raise ValueError(f"unknown filter kind: {self.kind}")


@dataclass(frozen=True)
class ReportQuery:
    """Everything the user selected. Frozen so a saved report is a value."""

    date_from: _dt.date | None = None
    date_to: _dt.date | None = None
    period_id: int | None = None
    party_id: int | None = None
    account_id: int | None = None
    cost_center_id: int | None = None
    project_id: int | None = None
    product_id: int | None = None
    warehouse_id: int | None = None
    org_unit_id: int | None = None
    search: str = ""
    sort_key: str | None = None
    sort_desc: bool = False
    group_by: str | None = None
    column_keys: tuple[str, ...] | None = None
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    params: Mapping[str, object] = field(default_factory=dict)

    def validated(self) -> "ReportQuery":
        if self.date_from and self.date_to and self.date_to < self.date_from:
            raise ValidationError("تاریخ پایان گزارش نمی‌تواند قبل از تاریخ شروع باشد.")
        page = max(1, int(self.page or 1))
        size = int(self.page_size or DEFAULT_PAGE_SIZE)
        if size < 1 or size > MAX_PAGE_SIZE:
            raise ValidationError(
                f"تعداد سطر هر صفحه باید بین ۱ و {MAX_PAGE_SIZE} باشد.")
        return ReportQuery(
            date_from=self.date_from, date_to=self.date_to, period_id=self.period_id,
            party_id=self.party_id, account_id=self.account_id,
            cost_center_id=self.cost_center_id, project_id=self.project_id,
            product_id=self.product_id, warehouse_id=self.warehouse_id,
            org_unit_id=self.org_unit_id, search=(self.search or "").strip(),
            sort_key=self.sort_key, sort_desc=bool(self.sort_desc),
            group_by=self.group_by,
            column_keys=tuple(self.column_keys) if self.column_keys else None,
            page=page, page_size=size, params=dict(self.params or {}))

    @property
    def has_period(self) -> bool:
        return bool(self.date_from and self.date_to)


@dataclass(frozen=True)
class DrillTarget:
    """Where a report row came from: a page key plus an id and/or a search text."""

    page_key: str
    record_id: int | None = None
    search: str = ""
    note_fa: str = ""


@dataclass(frozen=True)
class ReportDefinition:
    """A report the engine may run."""

    key: str
    title_fa: str
    section: str
    section_title_fa: str
    permission: str
    description_fa: str
    fetcher: Callable[[SecurityContext | None, ReportQuery], ReportTable]
    filters: tuple[FilterSpec, ...] = ()
    drill: Callable[[Sequence], DrillTarget | None] | None = None
    sort_order: int = 0
    supports_grouping: bool = True
    label_fa: str = ""

    def __post_init__(self) -> None:
        if not self.key or not self.key.replace("_", "").isalnum():
            raise ValueError(f"invalid report key: {self.key!r}")

    @property
    def display_fa(self) -> str:
        return self.label_fa or self.title_fa


@dataclass(frozen=True)
class AggregateValue:
    column_key: str
    column_title_fa: str
    kind: str
    value: object

    @property
    def title_fa(self) -> str:
        return AGGREGATION_TITLES_FA.get(self.kind, self.kind)


@dataclass(frozen=True)
class GroupRow:
    """One subtotal block produced by ``group_by``."""

    key: object
    label_fa: str
    count: int
    values: tuple[object, ...]


@dataclass(frozen=True)
class ReportResult:
    definition_key: str
    title_fa: str
    columns: tuple[ReportColumn, ...]
    rows: tuple[tuple, ...]
    total_rows: int
    page: int
    page_size: int
    pages: int
    aggregates: tuple[AggregateValue, ...] = ()
    groups: tuple[GroupRow, ...] = ()
    table: ReportTable | None = None
    filter_labels: tuple[str, ...] = ()
    group_by: str | None = None

    @property
    def is_empty(self) -> bool:
        return not self.rows

    @property
    def page_label_fa(self) -> str:
        return f"صفحهٔ {self.page} از {self.pages} — {self.total_rows} سطر"

    def target_for(self, definition: ReportDefinition, row: Sequence) -> DrillTarget | None:
        """Drill-through target of one row (``None`` when the report has no link)."""
        if definition.drill is None:
            return None
        return definition.drill(row)


# --------------------------------------------------------------------- helpers
def _text(value) -> str:
    if value is None:
        return ""
    return str(value)


def _as_decimal(value) -> Decimal | None:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):  # never expected, but never silently trusted
        return Decimal(str(value))
    return None


def _search(rows: list[tuple], columns: Sequence[ReportColumn], needle: str) -> list[tuple]:
    """Case-insensitive search that accepts Persian and Latin digits alike."""
    from pars_erp.core.digits import normalize_text, to_latin_digits, to_persian_digits

    needle = needle.strip()
    if not needle:
        return rows
    variants = {needle.lower(), normalize_text(needle),
                to_persian_digits(needle).lower(), to_latin_digits(needle).lower()}
    result = []
    for row in rows:
        haystack = []
        for value in row:
            if value is None:
                continue
            text = str(value)
            if isinstance(value, Decimal):
                text = f"{value}"
            haystack.append(text.lower())
        joined = " ".join(haystack)
        if any(variant in joined for variant in variants if variant):
            result.append(row)
    return result


def _sort(rows: list[tuple], columns: Sequence[ReportColumn], key: str | None,
          descending: bool) -> list[tuple]:
    if not key:
        return rows
    index = next((i for i, column in enumerate(columns) if column.key == key), None)
    if index is None:
        raise ValidationError("ستون مرتب‌سازی در این گزارش وجود ندارد.")

    def sort_key(row: tuple):
        value = row[index] if index < len(row) else None
        if value is None:
            return (1, "")
        numeric = _as_decimal(value)
        if numeric is not None:
            return (0, numeric)
        if isinstance(value, (_dt.date, _dt.datetime)):
            return (2, value.isoformat())
        return (3, str(value))

    return sorted(rows, key=sort_key, reverse=descending)


def _aggregates(rows: Sequence[tuple], columns: Sequence[ReportColumn]) -> tuple[AggregateValue, ...]:
    values: list[AggregateValue] = []
    for index, column in enumerate(columns):
        if column.kind not in NUMERIC_KINDS:
            continue
        numbers = [_as_decimal(row[index]) for row in rows if index < len(row)]
        numbers = [number for number in numbers if number is not None]
        total = sum(numbers, Decimal("0")) if numbers else Decimal("0")
        values.append(AggregateValue(column.key, column.title_fa, AGG_SUM, total))
        if numbers:
            average = (total / Decimal(len(numbers)))
            if column.kind == KIND_AMOUNT:
                average = average.quantize(Decimal("0.0001"))
            values.append(AggregateValue(column.key, column.title_fa, AGG_AVG, average))
            values.append(AggregateValue(column.key, column.title_fa, AGG_MIN, min(numbers)))
            values.append(AggregateValue(column.key, column.title_fa, AGG_MAX, max(numbers)))
        values.append(AggregateValue(column.key, column.title_fa, AGG_COUNT, len(numbers)))
    return tuple(values)


def _group(rows: Sequence[tuple], columns: Sequence[ReportColumn],
           group_by: str) -> tuple[GroupRow, ...]:
    index = next((i for i, column in enumerate(columns) if column.key == group_by), None)
    if index is None:
        raise ValidationError("ستون گروه‌بندی در این گزارش وجود ندارد.")
    buckets: dict[object, list[tuple]] = {}
    for row in rows:
        key = row[index] if index < len(row) else None
        buckets.setdefault(key, []).append(row)
    groups: list[GroupRow] = []
    numeric_indexes = [i for i, column in enumerate(columns) if column.kind in NUMERIC_KINDS]
    for key, bucket in sorted(buckets.items(), key=lambda item: (item[0] is None, str(item[0]))):
        totals = []
        for i in numeric_indexes:
            numbers = [_as_decimal(row[i]) for row in bucket if i < len(row)]
            totals.append(sum((n for n in numbers if n is not None), Decimal("0")))
        groups.append(GroupRow(key=key, label_fa=_text(key) or "—", count=len(bucket),
                               values=tuple(totals)))
    return tuple(groups)


def _totals_row(columns: Sequence[ReportColumn], rows: Sequence[tuple]) -> tuple | None:
    sums = []
    found = False
    for index, column in enumerate(columns):
        if column.kind in NUMERIC_KINDS:
            numbers = [_as_decimal(row[index]) for row in rows if index < len(row)]
            numbers = [n for n in numbers if n is not None]
            sums.append(sum(numbers, Decimal("0")))
            found = True
        else:
            sums.append("جمع" if index == 0 else None)
    return tuple(sums) if found else None


def apply_columns(table: ReportTable, column_keys: Sequence[str] | None,
                  ) -> tuple[tuple[ReportColumn, ...], list[tuple]]:
    """Select the requested columns (default: all) and rebuild the rows."""
    columns = tuple(table.columns)
    if not column_keys:
        return columns, [tuple(row) for row in table.rows]
    known = {column.key for column in columns}
    missing = [key for key in column_keys if key not in known]
    if missing:
        raise ValidationError("ستون‌های انتخاب‌شده در این گزارش وجود ندارند.")
    indexes = [i for i, column in enumerate(columns) if column.key in set(column_keys)]
    indexes.sort()
    selected = tuple(columns[i] for i in indexes)
    rows = [tuple(row[i] if i < len(row) else None for i in indexes) for row in table.rows]
    return selected, rows


def run(definition: ReportDefinition, query: ReportQuery,
        ctx: SecurityContext | None) -> ReportResult:
    """Run one report: fetch, then apply every generic feature on top."""
    query = query.validated()
    require_permission(ctx, definition.permission)
    table = definition.fetcher(ctx, query)
    columns, rows = apply_columns(table, query.column_keys)
    if query.search:
        rows = _search(rows, columns, query.search)
    rows = _sort(rows, columns, query.sort_key, query.sort_desc)
    aggregates = _aggregates(rows, columns)
    groups: tuple[GroupRow, ...] = ()
    if query.group_by:
        if not definition.supports_grouping:
            raise ValidationError("این گزارش گروه‌بندی ندارد.")
        groups = _group(rows, columns, query.group_by)
    total = len(rows)
    pages = max(1, (total + query.page_size - 1) // query.page_size)
    page = min(query.page, pages)
    start = (page - 1) * query.page_size
    page_rows = tuple(rows[start:start + query.page_size])
    export_table = ReportTable(
        title=table.title or definition.title_fa,
        columns=columns,
        rows=tuple(rows),
        company=table.company,
        subtitle=table.subtitle,
        meta=table.meta,
        totals=_totals_row(columns, rows),
        notes=table.notes,
        currency_code=table.currency_code,
    )
    return ReportResult(
        definition_key=definition.key,
        title_fa=definition.title_fa,
        columns=columns,
        rows=page_rows,
        total_rows=total,
        page=page,
        page_size=query.page_size,
        pages=pages,
        aggregates=aggregates,
        groups=groups,
        table=export_table,
        filter_labels=_filter_labels(query),
        group_by=query.group_by,
    )


def _filter_labels(query: ReportQuery) -> tuple[str, ...]:
    from pars_erp.core.jalali import format_gregorian_as_jalali

    labels: list[str] = []
    if query.date_from and query.date_to:
        labels.append(f"از {format_gregorian_as_jalali(query.date_from)} "
                      f"تا {format_gregorian_as_jalali(query.date_to)}")
    elif query.date_from:
        labels.append(f"از {format_gregorian_as_jalali(query.date_from)}")
    elif query.date_to:
        labels.append(f"تا {format_gregorian_as_jalali(query.date_to)}")
    if query.search:
        labels.append(f"جست‌وجو: {query.search}")
    if query.group_by:
        labels.append(f"گروه‌بندی بر اساس {query.group_by}")
    return tuple(labels)


class ReportCatalogue:
    """The registry of every report the engine can run."""

    def __init__(self, definitions: Iterable[ReportDefinition]) -> None:
        self._definitions: dict[str, ReportDefinition] = {}
        for definition in definitions:
            if definition.key in self._definitions:
                raise ValueError(f"duplicate report key: {definition.key}")
            self._definitions[definition.key] = definition

    def __len__(self) -> int:
        return len(self._definitions)

    def __iter__(self):
        return iter(sorted(self._definitions.values(),
                           key=lambda d: (d.section, d.sort_order, d.key)))

    def get(self, key: str) -> ReportDefinition:
        definition = self._definitions.get(key)
        if definition is None:
            raise ValidationError("گزارش درخواستی در فهرست گزارش‌های مجاز نیست.")
        return definition

    def has(self, key: str) -> bool:
        return key in self._definitions

    def visible(self, ctx: SecurityContext | None) -> tuple[ReportDefinition, ...]:
        return tuple(definition for definition in self
                     if ctx is not None and ctx.has(definition.permission))

    def sections(self, ctx: SecurityContext | None) -> tuple[tuple[str, str, tuple[ReportDefinition, ...]], ...]:
        grouped: dict[str, list[ReportDefinition]] = {}
        titles: dict[str, str] = {}
        for definition in self.visible(ctx):
            grouped.setdefault(definition.section, []).append(definition)
            titles[definition.section] = definition.section_title_fa
        return tuple((section, titles[section], tuple(items))
                     for section, items in grouped.items())
