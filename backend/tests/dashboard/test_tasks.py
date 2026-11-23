"""The two counts as tasks (F154.6): By's counts handed on a fact at a time as
the task's progress, then whole as its result; the quick filters' counts and
amounts as its result. The record is `tests.support.dashboard.record`'s."""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.orm import Session as DbSession

from app import models
from app.dashboard.tasks import AttributeCountsTask, QuickFilterCountsTask
from app.models import Project, User
from app.schemas.dashboard import AttributeCountsSchema, QuickFilterCountsSchema
from app.services.container import ServiceContainer
from tests.support.dashboard import Record, record

NOW = datetime(2026, 11, 20, tzinfo=UTC)


class _Recorded:
    """A progress handle that keeps what the task sends."""

    def __init__(self) -> None:
        self.updates: list[tuple[str, float, dict[str, Any] | None]] = []

    def send_progress_text(self, text: str) -> None:
        self.send_progress(text, 0.0)

    def send_progress_value(self, value: float) -> None:
        self.send_progress("", value)

    def send_progress(
        self, text: str, value: float, data: dict[str, Any] | None = None
    ) -> None:
        self.updates.append((text, value, data))


@pytest.fixture
def worked(
    session: DbSession, person: User, project: Project, project_session: models.Session
) -> Record:
    return record(session, person, project, project_session)


@pytest.mark.usefixtures("worked")
class TestAttributeCountsTask:
    def test_each_facts_counts_come_as_its_progress_and_all_as_its_result(
        self, container: ServiceContainer
    ) -> None:
        view = container.address_service().view("t=all")
        handle = _Recorded()

        result = container.attribute_counts_task().execute(handle, view=view, now=NOW)

        assert isinstance(result, AttributeCountsSchema)
        counts = {count.dimension: count.count for count in result.counts}
        assert (counts["project"], counts["event_kind"]) == (2, 10)
        assert [(text, value) for text, value, _ in handle.updates] == [
            ("Counted the attributes of 1 of 2 facts", 0.5),
            ("Counted the attributes of 2 of 2 facts", 1.0),
        ]
        event = handle.updates[1][2]
        assert event == {
            "counts": [
                {"dimension": "event_kind", "count": 10},
                {"dimension": "event_error", "count": 2},
            ]
        }
        assert {
            count["dimension"]: count["count"]
            for _, _, data in handle.updates
            for count in (data or {})["counts"]
        } == counts


@pytest.mark.usefixtures("worked")
class TestQuickFilterCountsTask:
    def test_its_result_is_each_quick_filters_count_and_amount(
        self, container: ServiceContainer
    ) -> None:
        view = container.address_service().view("t=all")
        handle = _Recorded()

        result = container.quick_filter_counts_task().execute(
            handle, view=view, now=NOW
        )

        assert isinstance(result, QuickFilterCountsSchema)
        assert [
            (count.key, count.count, count.amount) for count in result.quick_filters
        ] == [
            ("compactions", 1, None),
            ("expensive", 0, 0.0),
            ("misses", 1, 1.0),
            ("outliers", 0, None),
            ("past_ttl", 1, 0.0),
        ]
        assert handle.updates == []

    def test_a_task_is_made_anew_for_each_start(
        self, container: ServiceContainer
    ) -> None:
        assert container.quick_filter_counts_task() is not (
            container.quick_filter_counts_task()
        )
        assert isinstance(container.attribute_counts_task(), AttributeCountsTask)
        assert isinstance(container.quick_filter_counts_task(), QuickFilterCountsTask)
