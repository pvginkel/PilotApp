"""Helpers for tests of what the database refuses."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def violated_constraint(session: Session) -> str:
    """Flush, and return the name of the constraint the flush violates."""
    with pytest.raises(IntegrityError) as raised:
        session.flush()
    return raised.value.orig.diag.constraint_name


@dataclass(frozen=True)
class Written:
    """The rows of one table a block wrote."""

    inserted: int = 0
    updated: int = 0
    deleted: int = 0


def _written(session: Session) -> dict[str, Written]:
    """Each table's rows written so far in the session's transaction, its
    savepoints' included."""
    session.flush()
    return {
        table: Written(inserted, updated, deleted)
        for table, inserted, updated, deleted in session.execute(
            text(
                "SELECT relname, n_tup_ins, n_tup_upd, n_tup_del"
                " FROM pg_stat_xact_user_tables"
            )
        )
    }


@contextmanager
def writes(session: Session) -> Iterator[dict[str, Written]]:
    """The rows the block writes on `session`, by table, filled in as the
    block ends; a table it writes no row of is left out."""
    before = _written(session)
    wrote: dict[str, Written] = {}
    yield wrote
    for table, after in _written(session).items():
        earlier = before.get(table, Written())
        written = Written(
            after.inserted - earlier.inserted,
            after.updated - earlier.updated,
            after.deleted - earlier.deleted,
        )
        if written != Written():
            wrote[table] = written
