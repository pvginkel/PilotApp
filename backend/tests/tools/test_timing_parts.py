"""The timing's parts (`tools/timing/parts.py`, F154.9): every part reads
on a day of the history over each of its ranges, and a statement that went
to disk is named with the node that did."""

from datetime import UTC, datetime, timedelta

import pytest
from flask.testing import FlaskClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.models.call import Call
from app.services.container import ServiceContainer
from tools.timing.history import _Writer, draw
from tools.timing.parts import (
    EACH_ITEM,
    LONG_MS,
    PARTS,
    RUNS,
    Part,
    explained,
    timed_runs,
)

YESTERDAY = datetime.now(UTC).date() - timedelta(days=1)


@pytest.fixture
def written(session: DbSession, container: ServiceContainer) -> str:
    """A day of the history ending yesterday, with the each-item quick
    filter; the transcript with the most Calls."""
    _Writer(container, session).write(draw(YESTERDAY, 400))
    container.dashboard_store_service().add_quick_filter(
        "Costly conversations", EACH_ITEM, "cost", None
    )
    container.catalogue_service().drop()
    longest = session.scalars(
        select(Call.transcript_id)
        .group_by(Call.transcript_id)
        .order_by(func.count().desc())
        .limit(1)
    ).one()
    return str(longest)


@pytest.mark.parametrize("part", PARTS, ids=lambda part: part.key)
def test_every_part_reads_over_each_of_its_ranges(
    part: Part,
    written: str,
    client: FlaskClient,
    container: ServiceContainer,
) -> None:
    for range_ in part.ranges:
        state = part.state.format(t=range_, x="0")
        if part.route is None:
            view = container.address_service().view(state)
            counts = container.counts_service()
            found = (
                counts.attributes(view, datetime.now(UTC))
                if part.key == "attributes"
                else counts.quick_filters(view, datetime.now(UTC))
            )
            assert found
            continue
        answer = client.get(
            part.route.format(conversation=written),
            query_string=[("state", state), *part.query],
        )
        assert answer.status_code == 200, answer.get_json()


def test_the_parts_have_keys_of_their_own() -> None:
    keys = [part.key for part in PARTS]

    assert len(keys) == len(set(keys))


def test_a_part_whose_first_read_is_long_is_timed_once() -> None:
    assert timed_runs(LONG_MS) == RUNS
    assert timed_runs(LONG_MS + 1) == 1


class TestExplained:
    def test_a_sort_past_the_memory_is_named_as_gone_to_disk(
        self, session: DbSession
    ) -> None:
        session.execute(select(func.set_config("work_mem", "64kB", True)))

        found = explained(
            session.connection(),
            [("SELECT g FROM generate_series(1, 20000) AS g ORDER BY g DESC", {})],
        )

        assert len(found) == 1
        assert found[0].temp_blocks > 0
        assert [spill.split(",")[0] for spill in found[0].spills] == ["Sort to disk"]

    def test_a_statement_in_memory_names_none(self, session: DbSession) -> None:
        found = explained(
            session.connection(),
            [("SELECT g FROM generate_series(1, %(n)s) AS g ORDER BY g", {"n": 50})],
        )

        assert (found[0].temp_blocks, found[0].spills) == (0, [])

    def test_it_runs_read_only(self, session: DbSession) -> None:
        with pytest.raises(Exception, match="read-only transaction"):
            explained(
                session.connection(),
                [
                    (
                        "INSERT INTO environments (id, name, exempt) "
                        "VALUES ('gone', 'gone', false)",
                        {},
                    )
                ],
            )
