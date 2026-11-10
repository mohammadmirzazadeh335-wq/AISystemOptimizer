"""Shared service-layer value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Sequence, TypeVar

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200


@dataclass(frozen=True)
class Page(Generic[T]):
    items: Sequence[T]
    total: int
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    @property
    def pages(self) -> int:
        if self.page_size <= 0:
            return 1
        return max(1, (self.total + self.page_size - 1) // self.page_size)

    @property
    def has_next(self) -> bool:
        return self.page < self.pages

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    def range_fa(self) -> str:
        if self.total == 0:
            return "بدون نتیجه"
        start = (self.page - 1) * self.page_size + 1
        end = min(self.page * self.page_size, self.total)
        return f"{start:,} تا {end:,} از {self.total:,}"


def normalize_page(page: int | None, page_size: int | None) -> tuple[int, int]:
    p = max(1, int(page or 1))
    size = int(page_size or DEFAULT_PAGE_SIZE)
    if size <= 0:
        size = DEFAULT_PAGE_SIZE
    return p, min(size, MAX_PAGE_SIZE)


def clamp_page(page: int, page_size: int, total: int) -> int:
    if total <= 0:
        return 1
    pages = max(1, (total + page_size - 1) // page_size)
    return min(max(1, page), pages)


@dataclass(frozen=True)
class OperationResult:
    """Generic result of a mutating operation, suitable for the status bar."""

    ok: bool
    message_fa: str
    data: dict = field(default_factory=dict)
