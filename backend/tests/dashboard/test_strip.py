"""A series' events strip (F164.6): the events in each of a series' points by
their kind, the errors by the Event fact's `is_error`, Event Kind's for a
stored Event and the catalogue's for an occurrence another entity records.

The record is `tests.support.dashboard.record`'s: on 12 November 2026 in
Amsterdam a stored API error, an error by its Event Kind, and one occurrence
of each kind its Calls, its Tool Calls and its Hook Run record.
"""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.dashboard.planner import plan
from app.dashboard.state import State
from app.dashboard.strip import Strip, StripService, strip_read
from app.exceptions import StateRefusedException
from app.models import EventKind, Project, User
from app.services.container import ServiceContainer
from tests.support.dashboard import Record, catalogue, record
from tests.support.transcripts import STARTED

NOW = datetime(2026, 11, 20, tzinfo=UTC)

ERRORS = ["api_error", "hook_error", "max_tokens", "model_fallback"]
"""The record's kinds that count as errors, in the strip's order: each once,
so by their keys."""

OTHERS = ["cache_miss", "compaction", "denied", "output_saved", "past_ttl", "rewind"]


@pytest.fixture
def worked(
    session: DbSession, person: User, project: Project, project_session: models.Session
) -> Record:
    return record(session, person, project, project_session)


@pytest.fixture
def service(container: ServiceContainer) -> StripService:
    return container.strip_service()


def _strip(service: StripService, written: str) -> Strip:
    return service.strip(written, now=NOW)


@pytest.mark.usefixtures("worked")
class TestStrip:
    def test_each_points_events_by_kind_the_errors_first(
        self, service: StripService
    ) -> None:
        found = _strip(service, "t=all&p=time,day")

        assert found.by.key == "day"
        assert [kind.key for kind in found.kinds] == ERRORS + OTHERS
        assert [kind.is_error for kind in found.kinds] == [True] * 4 + [False] * 6
        assert [(bucket.key, bucket.errors) for bucket in found.buckets] == [
            (date(2026, 11, 12), 4)
        ]
        assert found.buckets[0].counts == (1,) * 10
        assert found.refused is None

    def test_a_kinds_label_is_the_catalogues(self, service: StripService) -> None:
        found = _strip(service, "t=all&p=time,day")

        labels = {kind.key: kind.label for kind in found.kinds}
        assert labels["compaction"] == "Compaction"
        assert labels["api_error"] == "api_error"

    def test_an_error_is_its_event_kinds(
        self, service: StripService, session: DbSession
    ) -> None:
        kind = session.get(EventKind, "api_error")
        assert kind is not None
        kind.is_error = False
        session.flush()

        found = _strip(service, "t=all&p=time,day")

        assert [kind.key for kind in found.kinds if kind.is_error] == ERRORS[1:]
        assert found.buckets[0].errors == 3

    def test_the_kinds_by_their_count_within_their_group(
        self, service: StripService, session: DbSession, worked: Record
    ) -> None:
        session.add(
            models.Event(
                call_id=worked.calls[1].id,
                kind_code="api_error",
                at=STARTED,
                detail="529",
            )
        )
        session.flush()

        found = _strip(service, "t=all&p=time,day")

        assert [(kind.key, kind.total) for kind in found.kinds][:2] == [
            ("api_error", 2),
            ("hook_error", 1),
        ]

    def test_in_order_by_its_members(
        self, service: StripService, worked: Record
    ) -> None:
        found = _strip(service, "t=all&by=psession&p=order")

        assert found.by.key == "session_start"
        assert [bucket.key for bucket in found.buckets] == [worked.work.id]

    def test_the_scope_keeps_its_events(self, service: StripService) -> None:
        found = _strip(service, "t=all&p=time,day&c=miss:1")

        # The third Call's: its miss, its compaction, and the failed Hook Run
        # of its Prompt, whose last Call it is.
        assert {kind.key for kind in found.kinds} == {
            "cache_miss",
            "compaction",
            "hook_error",
        }

    def test_a_window_with_none_holds_no_bucket(self, service: StripService) -> None:
        found = _strip(service, "t=c,2026-11-14,2026-11-15&p=time,day")

        assert (found.kinds, found.buckets) == ((), ())

    def test_a_view_in_rows_has_no_strip(self, service: StripService) -> None:
        with pytest.raises(StateRefusedException) as refused:
            _strip(service, "t=all&p=table")

        assert refused.value.message.splitlines()[1] == (
            "- p=table: the view draws a table, and only a view in order or over "
            "time has a series. A series takes p=order[,<order dimension>] or "
            "p=time,<grain>."
        )


class TestStripRead:
    def test_a_dimension_the_events_lack_says_why(self, session: DbSession) -> None:
        held = catalogue(session)
        found = plan(replace(State(), by="estimate"), held, (), NOW)

        assert strip_read(found, held) == (
            "The strip counts events, which have no estimate"
        )
