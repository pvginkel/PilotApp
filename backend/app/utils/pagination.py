"""Sorting and paging for list endpoints.

A paged list must order stably. When the sort column holds duplicates, the
database may return the tied rows in a different order for each query, so rows
repeat or vanish between pages. ``apply_sorting()`` therefore always adds the
model's ``id`` as a tiebreaker, in the same direction.

An endpoint's query schema subclasses ``PaginationQuerySchema``
(``app/schemas/common.py``) and adds ``sort_by`` as a ``Literal`` of the
columns it sorts by, so ``sort_by`` is whitelisted before it reaches here.
"""

import math
from typing import Any

from sqlalchemy import Select

from app.schemas.common import PaginationMetaSchema, SortDirection


def apply_sorting[TP: tuple[Any, ...]](
    query: Select[TP], model: type[Any], sort_by: str, sort_dir: SortDirection
) -> Select[TP]:
    """Order ``query`` by ``model.<sort_by>``, then by ``model.id`` as a tiebreaker.

    Raises:
        ValueError: ``sort_dir`` is not ``asc`` or ``desc``, or ``model`` has no
            attribute ``sort_by``.
    """
    if sort_dir not in ("asc", "desc"):
        raise ValueError(f"sort_dir must be 'asc' or 'desc', not {sort_dir!r}")
    column = getattr(model, sort_by, None)
    if column is None:
        raise ValueError(f"{model.__name__} has no column {sort_by!r} to sort by")

    columns = [column] if sort_by == "id" else [column, model.id]
    if sort_dir == "asc":
        return query.order_by(*(c.asc() for c in columns))
    return query.order_by(*(c.desc() for c in columns))


def build_pagination_meta(
    total: int,
    page: int,
    per_page: int,
    sort_by: str | None = None,
    sort_dir: SortDirection | None = None,
) -> PaginationMetaSchema:
    """Describe one page of ``total`` items; an empty list still has one page."""
    return PaginationMetaSchema(
        page=page,
        per_page=per_page,
        total=total,
        total_pages=max(1, math.ceil(total / per_page)),
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
