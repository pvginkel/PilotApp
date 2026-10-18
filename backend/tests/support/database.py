"""Helpers for tests of what the database refuses."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def violated_constraint(session: Session) -> str:
    """Flush, and return the name of the constraint the flush violates."""
    with pytest.raises(IntegrityError) as raised:
        session.flush()
    return raised.value.orig.diag.constraint_name
