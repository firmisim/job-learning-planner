from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Callable, Generic, Sequence, TypeVar


T = TypeVar("T")
DEFAULT_PAGE_SIZE = 10


@dataclass(frozen=True)
class PageSlice(Generic[T]):
    items: tuple[T, ...]
    query: str
    page: int
    page_count: int
    total: int
    unfiltered_total: int

    @property
    def has_previous(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.page_count


def paginate(
    items: Sequence[T],
    *,
    query: str | None,
    page: str | int | None,
    searchable_text: Callable[[T], str] | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> PageSlice[T]:
    """Filter and clamp one in-memory UI list without creating persisted state."""

    normalized_query = " ".join((query or "").split())
    filtered = tuple(items)
    if normalized_query and searchable_text is not None:
        needle = normalized_query.casefold()
        filtered = tuple(
            item for item in items if needle in searchable_text(item).casefold()
        )
    try:
        requested_page = int(page or 1)
    except (TypeError, ValueError):
        requested_page = 1
    page_count = max(1, ceil(len(filtered) / page_size))
    current_page = min(max(requested_page, 1), page_count)
    start = (current_page - 1) * page_size
    return PageSlice(
        filtered[start : start + page_size],
        normalized_query,
        current_page,
        page_count,
        len(filtered),
        len(items),
    )
