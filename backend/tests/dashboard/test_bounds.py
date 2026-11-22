"""The bounds every statement of the dashboard's engine runs under (F154.5):
a read-only transaction of its own under the timeout, `work_mem` never
raised, a statement past the timeout or the limit on temporary files refused
with a reason told apart by PostgreSQL's code, and the statements at once
bounded below the app's pool."""

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session as DbSession

from app.dashboard.bounds import Bounds
from app.exceptions import ConfigurationError, QueryRefusedException
from app.models import Project, User
from app.services.container import ServiceContainer
from tests.support.dashboard import sent


def _setting(session: DbSession, name: str) -> str:
    return str(session.execute(text(f"SHOW {name}")).scalar_one())


@pytest.fixture
def bounds() -> Bounds:
    return Bounds(timeout_seconds=0.2, at_once=1, pool=5)


@pytest.fixture
def other(session: DbSession) -> Iterator[DbSession]:
    """A session on a connection of its own, beside the test's."""
    bind = session.get_bind()
    assert not isinstance(bind, Engine)
    opened = DbSession(bind=bind.engine)
    try:
        yield opened
    finally:
        opened.close()


class TestBounds:
    def test_a_read_is_read_only_under_the_timeout(
        self, session: DbSession, bounds: Bounds
    ) -> None:
        with bounds.read(session) as db:
            assert _setting(db, "transaction_read_only") == "on"
            assert _setting(db, "statement_timeout") == "200ms"

    def test_a_write_in_it_is_refused_as_the_database_refuses_it(
        self, session: DbSession, bounds: Bounds, person: User
    ) -> None:
        with pytest.raises(DBAPIError) as refused, bounds.read(session) as db:
            db.execute(text("UPDATE users SET name = 'Someone else'"))

        assert getattr(refused.value.orig, "sqlstate", None) == "25006"

    def test_it_leaves_the_callers_settings_as_they_were(
        self, session: DbSession, bounds: Bounds, person: User
    ) -> None:
        before = _setting(session, "statement_timeout")

        with bounds.read(session):
            pass

        assert _setting(session, "transaction_read_only") == "off"
        assert _setting(session, "statement_timeout") == before
        session.add(Project(created_by_user_id=person.id))
        session.flush()

    def test_it_reads_what_the_caller_wrote_before_it(
        self, session: DbSession, bounds: Bounds, project: Project
    ) -> None:
        with bounds.read(session) as db:
            found = db.execute(
                text("SELECT count(*) FROM projects WHERE id = :id"),
                {"id": project.id},
            ).scalar_one()

        assert found == 1

    def test_it_never_raises_work_mem(self, session: DbSession, bounds: Bounds) -> None:
        cluster = _setting(session, "work_mem")

        with sent(session) as statements, bounds.read(session) as db:
            assert _setting(db, "work_mem") == cluster

        assert [one for one in statements if "work_mem" in one.lower()] == [
            "SHOW work_mem"
        ]

    def test_a_statement_past_the_timeout_is_refused_as_one(
        self, session: DbSession, bounds: Bounds
    ) -> None:
        with (
            pytest.raises(QueryRefusedException) as refused,
            bounds.read(session) as db,
        ):
            db.execute(text("SELECT pg_sleep(2)"))

        assert refused.value.reason == "timeout"
        assert refused.value.error_code == "QUERY_TIMEOUT"
        assert refused.value.message == (
            "Cannot answer the dashboard's view because a statement ran past the "
            "engine's timeout of 0.2 s: a shorter time range or a narrower scope "
            "reads less"
        )
        assert _setting(session, "transaction_read_only") == "off"

    def test_one_past_the_limit_on_temporary_files_is_refused_as_one(
        self, session: DbSession, bounds: Bounds
    ) -> None:
        session.execute(text("SET LOCAL work_mem = '64kB'"))
        session.execute(text("SET LOCAL temp_file_limit = '64kB'"))

        with (
            pytest.raises(QueryRefusedException) as refused,
            bounds.read(session) as db,
        ):
            db.execute(
                text(
                    "SELECT count(*) FROM (SELECT g FROM generate_series(1, 100000) "
                    "AS g ORDER BY g DESC) AS sorted"
                )
            )

        assert refused.value.reason == "temp_file_limit"
        assert refused.value.error_code == "QUERY_TEMP_FILE_LIMIT"
        assert refused.value.message == (
            "Cannot answer the dashboard's view because a statement needed more "
            "temporary disk than the database allows one: a shorter time range or "
            "a narrower scope reads less"
        )

    def test_another_error_of_the_database_is_raised_as_it_is(
        self, session: DbSession, bounds: Bounds
    ) -> None:
        with pytest.raises(DBAPIError) as raised, bounds.read(session) as db:
            db.execute(text("SELECT 1 / 0"))

        assert getattr(raised.value.orig, "sqlstate", None) == "22012"

    def test_a_read_waits_no_longer_than_the_timeout_for_a_slot(
        self, session: DbSession, other: DbSession, bounds: Bounds
    ) -> None:
        with bounds.read(other):
            with pytest.raises(QueryRefusedException) as refused:
                with bounds.read(session):
                    pass

        assert refused.value.reason == "busy"
        assert refused.value.error_code == "QUERY_BUSY"
        assert refused.value.message == (
            "Cannot answer the dashboard's view because the engine already runs "
            "its 1 statements at once and none ended within 0.2 s"
        )

    def test_a_read_ended_frees_its_slot_refused_or_not(
        self, session: DbSession, bounds: Bounds
    ) -> None:
        with pytest.raises(QueryRefusedException), bounds.read(session) as db:
            db.execute(text("SELECT pg_sleep(2)"))

        with bounds.read(session) as db:
            assert db.execute(text("SELECT 1")).scalar_one() == 1

    @pytest.mark.parametrize("at_once", [5, 6])
    def test_as_many_at_once_as_the_pool_holds_is_refused(self, at_once: int) -> None:
        with pytest.raises(ConfigurationError, match="must leave the pool some"):
            Bounds(timeout_seconds=1, at_once=at_once, pool=5)

    def test_the_processs_are_the_settings_below_the_pool(
        self, container: ServiceContainer
    ) -> None:
        held = container.dashboard_bounds()
        config = container.config()

        assert held is container.dashboard_bounds()
        assert held.timeout_seconds == 30
        assert held.at_once == 4
        assert held.at_once < config.db_pool_size + config.db_pool_max_overflow
