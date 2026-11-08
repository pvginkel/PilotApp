"""The statement cap (app/utils/statement_cap.py), watching this file's code
on the session app's engine: a statement longer than its bound, measured
before SQLAlchemy expands it, is kept with its text, its length and where it
was sent; the suite's cap lets a test's own be, and a backend's keeps every
one."""

from collections.abc import Iterator
from typing import Any

import pytest
from flask import Flask
from sqlalchemy import Connection, Engine, Executable, event, literal, select, text

from app.extensions import db
from app.utils.statement_cap import CAP, StatementCap

_HERE = "tests/utils/test_statement_cap.py"


@pytest.fixture
def engine(app: Flask) -> Engine:
    with app.app_context():
        return db.engine


@pytest.fixture
def cap() -> Iterator[StatementCap]:
    cap = StatementCap(watched=(_HERE,))
    cap.install()
    try:
        yield cap
    finally:
        cap.uninstall()


def _of_length(length: int) -> str:
    """A statement of `length` characters, as text."""
    head = "SELECT 1 -- "
    return head + "-" * (length - len(head))


def _send(engine: Engine, statement: Executable) -> None:
    with engine.connect() as connection:
        connection.execute(statement).all()


def _sent_lengths(connection: Connection) -> list[int]:
    """The length of each statement `connection` sends from now on, as
    sent."""
    lengths: list[int] = []

    def measure(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _many: bool,
    ) -> None:
        lengths.append(len(statement))

    event.listen(connection, "before_cursor_execute", measure)
    return lengths


class TestStatementCap:
    def test_a_statement_over_the_cap_is_kept_with_its_text_length_and_stack(
        self, cap: StatementCap, engine: Engine
    ) -> None:
        statement = _of_length(CAP + 1)

        _send(engine, text(statement))

        [long] = cap.drain()
        assert long.text == statement
        assert long.bound == CAP
        assert long.sent[-1][::2] == (_HERE, "_send")
        described = long.describe()
        assert described.startswith(
            f"A statement of {CAP + 1:,} characters, over its bound of {CAP:,}"
        )
        assert f"{_HERE}:{long.sent[-1][1]} in _send" in described
        assert described.endswith(statement)
        assert cap.drain() == []

    def test_a_statement_at_the_cap_is_none(
        self, cap: StatementCap, engine: Engine
    ) -> None:
        _send(engine, text(_of_length(CAP)))

        assert cap.drain() == []

    def test_an_in_lists_ids_do_not_count(
        self, cap: StatementCap, engine: Engine
    ) -> None:
        with engine.connect() as connection:
            lengths = _sent_lengths(connection)
            connection.execute(
                select(literal(1)).where(literal(1).in_(list(range(1_000))))
            ).all()

        assert lengths[-1] > CAP
        assert cap.drain() == []

    def test_a_statement_sent_as_text_is_measured_as_sent(
        self, cap: StatementCap, engine: Engine
    ) -> None:
        with engine.connect() as connection:
            connection.exec_driver_sql(_of_length(CAP + 1)).all()

        [long] = cap.drain()
        assert len(long.text) == CAP + 1

    def test_a_statement_with_its_own_bound_is_held_to_that_bound(
        self, cap: StatementCap, engine: Engine
    ) -> None:
        bound = CAP + 1_000

        _send(
            engine,
            text(_of_length(bound)).execution_options(max_statement_length=bound),
        )
        assert cap.drain() == []

        statement = _of_length(bound + 1)
        _send(engine, text(statement).execution_options(max_statement_length=bound))
        [long] = cap.drain()
        assert long.bound == bound
        assert f"over its bound of {bound:,}" in long.describe()

    def test_to_the_suites_cap_a_tests_own_statement_is_none(
        self, engine: Engine
    ) -> None:
        cap = StatementCap()
        cap.install()
        try:
            _send(engine, text(_of_length(CAP + 1)))
        finally:
            cap.uninstall()

        assert cap.drain() == []

    def test_to_a_backends_cap_a_statement_anywhere_is_one(
        self, engine: Engine
    ) -> None:
        cap = StatementCap(watched=None)
        cap.install()
        try:
            _send(engine, text(_of_length(CAP + 1)))
        finally:
            cap.uninstall()

        assert len(cap.drain()) == 1

    def test_uninstalled_it_keeps_none(self, engine: Engine) -> None:
        cap = StatementCap(watched=None)
        cap.install()
        cap.uninstall()

        _send(engine, text(_of_length(CAP + 1)))

        assert cap.drain() == []
