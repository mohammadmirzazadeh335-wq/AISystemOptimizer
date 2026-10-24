"""Token usage and estimated spend.

Costs are **estimates**: they use the per-million-token prices of the cached
OpenRouter catalogue and the token counts the provider reported for each
assistant reply.  A model without a cached price is counted in the token totals
but reported as unpriced instead of being given an invented number.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from ..core.errors import ValidationError

logger = logging.getLogger(__name__)

RANGES = (7, 30, 90)
DEFAULT_RANGE = 30
CURRENCY = "USD"


def _utc_day(value: datetime | date | str) -> date:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


@dataclass(frozen=True)
class DayUsage:
    day: date
    requests: int
    input_tokens: int
    output_tokens: int
    cost: float

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class ModelUsage:
    model_id: str
    name: str
    requests: int
    input_tokens: int
    output_tokens: int
    cost: float
    priced: bool

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class UsageReport:
    days: int
    start: date
    end: date
    slices: list[DayUsage] = field(default_factory=list)
    models: list[ModelUsage] = field(default_factory=list)
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    unpriced_tokens: int = 0
    unpriced_models: int = 0
    budget: float = 0.0
    currency: str = CURRENCY

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def has_data(self) -> bool:
        return self.requests > 0 or self.tokens > 0

    @property
    def budget_ratio(self) -> float:
        if self.budget <= 0:
            return 0.0
        return max(0.0, min(1.0, self.cost / self.budget))

    @property
    def priced(self) -> bool:
        return self.unpriced_models == 0

    def peak_day(self) -> DayUsage | None:
        return max(self.slices, key=lambda item: item.cost, default=None)


class UsageService:
    def __init__(self, messages, settings) -> None:  # noqa: ANN001
        self._messages = messages
        self._settings = settings

    # ------------------------------------------------------------------ prices
    def catalogue(self) -> dict[str, dict]:
        """Prices from every provider's cached catalogue, merged by model id.

        Only OpenRouter publishes prices. The other catalogues are included
        anyway because their rows carry ``price_known=False`` and therefore no
        price at all, so merging cannot invent a number — and it lets a model
        that later gains a price be picked up without a code change.
        """
        cached = self._settings.get("ai.model_cache", {}) or {}
        rows: list = []
        if isinstance(cached, dict):
            for value in cached.values():
                if isinstance(value, list):
                    rows.extend(value)
        if not rows:
            rows = self._settings.get("ai.openrouter_cache", []) or []
        result: dict[str, dict] = {}
        for row in rows:
            if isinstance(row, dict) and row.get("id"):
                result.setdefault(str(row["id"]), row)
        return result

    def _price(self, catalogue: dict[str, dict], model_id: str) -> tuple[float, float] | None:
        row = catalogue.get(model_id)
        if row is None or row.get("price_known") is False:
            return None
        prompt = float(row.get("prompt_price") or 0.0)
        completion = float(row.get("completion_price") or 0.0)
        if prompt <= 0 and completion <= 0:
            return None
        return prompt, completion

    # ------------------------------------------------------------------ report
    def report(self, days: int = DEFAULT_RANGE, *, today: date | None = None) -> UsageReport:
        window = int(days)
        if window not in RANGES:
            raise ValidationError("Unsupported range", message_key="error.settings")
        end = today or datetime.now(timezone.utc).date()
        start = end - timedelta(days=window - 1)
        since = datetime.combine(start, datetime.min.time())
        rows = self._messages.usage_since(since)
        catalogue = self.catalogue()

        per_day: dict[date, list[int]] = {
            start + timedelta(days=offset): [0, 0, 0, 0] for offset in range(window)
        }
        # [requests, input, output, cost]
        models: dict[str, list] = {}
        total_in = total_out = requests = unpriced_tokens = 0
        cost = 0.0
        unpriced_models: set[str] = set()

        for row in rows:
            day = _utc_day(row.get("day") or "")
            if day < start or day > end:
                continue
            model_id = str(row.get("model_id") or "")
            is_reply = (row.get("role") or "") == "assistant"
            count = int(row.get("messages") or 0) if is_reply else 0
            in_tokens = int(row.get("input_tokens") or 0)
            out_tokens = int(row.get("output_tokens") or 0)
            price = self._price(catalogue, model_id)
            if price is None:
                row_cost = 0.0
                if in_tokens or out_tokens:
                    unpriced_tokens += in_tokens + out_tokens
                    unpriced_models.add(model_id or "—")
            else:
                row_cost = (in_tokens * price[0] + out_tokens * price[1]) / 1_000_000
            bucket = per_day.setdefault(day, [0, 0, 0, 0])
            bucket[0] += count
            bucket[1] += in_tokens
            bucket[2] += out_tokens
            bucket[3] += row_cost
            entry = models.setdefault(model_id, [model_id, 0, 0, 0, 0.0, price is not None])
            entry[1] += count
            entry[2] += in_tokens
            entry[3] += out_tokens
            entry[4] += row_cost
            entry[5] = bool(entry[5]) and price is not None
            total_in += in_tokens
            total_out += out_tokens
            requests += count
            cost += row_cost

        slices = [
            DayUsage(
                day=day,
                requests=values[0],
                input_tokens=values[1],
                output_tokens=values[2],
                cost=round(values[3], 6),
            )
            for day, values in sorted(per_day.items())
        ]
        model_rows = []
        for model_id, values in models.items():
            # A row with no tokens carries no cost information; it would only
            # add a meaningless "—" line to the table.
            if values[2] == 0 and values[3] == 0:
                continue
            name = str(catalogue.get(model_id, {}).get("name") or model_id or "—")
            model_rows.append(
                ModelUsage(
                    model_id=model_id,
                    name=name,
                    requests=int(values[1]),
                    input_tokens=int(values[2]),
                    output_tokens=int(values[3]),
                    cost=round(float(values[4]), 6),
                    priced=bool(values[5]),
                )
            )
        model_rows.sort(key=lambda item: (-item.cost, -item.tokens, item.name))
        budget = float(self._settings.get("usage.monthly_budget", 0.0) or 0.0)
        return UsageReport(
            days=window,
            start=start,
            end=end,
            slices=slices,
            models=model_rows,
            requests=requests,
            input_tokens=total_in,
            output_tokens=total_out,
            cost=round(cost, 6),
            unpriced_tokens=unpriced_tokens,
            unpriced_models=len(unpriced_models),
            budget=max(0.0, budget),
        )

    # --------------------------------------------------------------- settings
    def set_budget(self, value: float) -> float:
        self._settings.update({"usage.monthly_budget": max(0.0, float(value or 0.0))})
        return max(0.0, float(value or 0.0))
