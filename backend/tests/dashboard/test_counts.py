"""The two counts of a view (F154.6) and an attribute's values: By's count of
each dimension's values in scope, under every chip, its own included
(F163.2), before a threshold on the By's rows (D5); the quick filters' counts
and amounts under the quick filters that are on (F162.6), one statement a
fact, an each-item one coarser than the call among them (R24); and an
attribute's values for a filter's pane, without its own chips.

The record is `tests.support.dashboard.record`'s: on the project Recipe box,
a work item's thread of three Calls, 0.50, 0.25 and 1.00, the second past the
cache's lifetime and the third a miss after a compaction, with its
sub-agent's Call of 0.10, and a chat's Turn of 0.75 standing in, its
conversation never collected; and on no project a thread of one Call of
0.05, a day later.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, text
from sqlalchemy.orm import Session as DbSession

from app import models
from app.dashboard.address import View
from app.dashboard.counts import (
    VALUES,
    AttributeValue,
    Count,
    CountsService,
    QuickFilterCount,
)
from app.exceptions import (
    QueryRefusedException,
    StateRefusedException,
    ValidationException,
)
from app.models import Project, User
from app.services.container import ServiceContainer
from tests.support.dashboard import Record, record, sent

NOW = datetime(2026, 11, 20, tzinfo=UTC)


@pytest.fixture
def worked(
    session: DbSession, person: User, project: Project, project_session: models.Session
) -> Record:
    return record(session, person, project, project_session)


@pytest.fixture
def service(container: ServiceContainer) -> CountsService:
    return container.counts_service()


def _view(container: ServiceContainer, written: str) -> View:
    return container.address_service().view(written)


def _counts(
    container: ServiceContainer, service: CountsService, written: str
) -> dict[str, int]:
    return {
        count.dimension: count.count
        for count in service.attributes(_view(container, written), NOW)
    }


def _quick_filters(
    container: ServiceContainer, service: CountsService, written: str
) -> dict[str, QuickFilterCount]:
    return {
        count.key: count
        for count in service.quick_filters(_view(container, written), NOW)
    }


def _quick_filter(
    session: DbSession,
    code: str,
    condition: str,
    amount: str | None = None,
    marks: bool = False,
) -> None:
    session.add(
        models.QuickFilter(
            code=code,
            label=code.capitalize(),
            condition=condition,
            marks=marks,
            amount_figure=amount,
            saved_at=NOW,
        )
    )
    session.flush()


@pytest.mark.usefixtures("worked")
class TestAttributes:
    def test_each_dimension_counts_its_values_in_scope_none_counting_as_one(
        self, container: ServiceContainer, service: CountsService
    ) -> None:
        counts = _counts(container, service, "t=all")

        assert {
            key: counts[key]
            for key in ("project", "psession", "conversation", "model", "source")
        } == {"project": 2, "psession": 3, "conversation": 4, "model": 2, "source": 3}

    def test_every_dimension_is_counted_in_the_catalogues_order(
        self, container: ServiceContainer, service: CountsService
    ) -> None:
        found = service.attributes(_view(container, "t=all"), NOW)

        assert [count.dimension for count in found] == [
            dimension.key
            for dimension in container.catalogue_service()
            .catalogue(container.db_session())
            .dimensions
        ]

    def test_the_facts_own_row_counts_its_rows_and_one_for_those_with_none(
        self, container: ServiceContainer, service: CountsService
    ) -> None:
        assert _counts(container, service, "t=all")["call"] == 6

    def test_an_order_dimension_is_its_parts(
        self, container: ServiceContainer, service: CountsService
    ) -> None:
        counts = _counts(container, service, "t=all")

        assert (counts["session_start"], counts["turn_seq"]) == (
            counts["psession"],
            counts["pturn"],
        )

    def test_a_dimension_only_another_fact_offers_is_counted_on_it(
        self, container: ServiceContainer, service: CountsService
    ) -> None:
        counts = _counts(container, service, "t=all")

        assert (counts["event_kind"], counts["event_error"]) == (10, 2)

    def test_a_drilled_project_reads_one(
        self, container: ServiceContainer, service: CountsService, worked: Record
    ) -> None:
        counts = _counts(
            container,
            service,
            f"t=all&by=psession&dr=project:{worked.project.id}@project",
        )

        assert (counts["project"], counts["psession"]) == (1, 2)

    def test_a_chip_narrows_its_own_dimension(
        self, container: ServiceContainer, service: CountsService, worked: Record
    ) -> None:
        counts = _counts(container, service, f"t=all&c=project:{worked.project.id}")

        assert (counts["project"], counts["conversation"]) == (1, 3)

    def test_a_threshold_on_the_bys_rows_and_the_outlier_rows_chip_narrow_nothing(
        self, container: ServiceContainer, service: CountsService
    ) -> None:
        assert _counts(
            container, service, "t=all&c=@rows,gt,1,cost.sum&c=@outliers"
        ) == _counts(container, service, "t=all")

    def test_a_quick_filter_that_is_on_narrows_them(
        self, container: ServiceContainer, service: CountsService
    ) -> None:
        counts = _counts(container, service, "t=all&b=misses")

        assert (counts["project"], counts["conversation"], counts["call"]) == (1, 1, 1)

    def test_the_time_narrows_them(
        self, container: ServiceContainer, service: CountsService
    ) -> None:
        counts = _counts(container, service, "t=c,2026-11-13,2026-11-13")

        assert (counts["project"], counts["conversation"], counts["call"]) == (1, 1, 1)

    def test_a_scope_that_keeps_nothing_counts_none(
        self, container: ServiceContainer, service: CountsService
    ) -> None:
        counts = _counts(container, service, "t=c,2026-10-01,2026-10-02")

        assert set(counts.values()) == {0}

    def test_each_facts_counts_are_handed_on_as_they_come(
        self, container: ServiceContainer, service: CountsService
    ) -> None:
        handed: list[tuple[tuple[Count, ...], int, int]] = []

        found = service.attributes(
            _view(container, "t=all"),
            NOW,
            lambda part, done, facts: handed.append((part, done, facts)),
        )

        assert [(done, facts) for _, done, facts in handed] == [(1, 2), (2, 2)]
        assert {count.dimension for count in handed[1][0]} == {
            "event_kind",
            "event_error",
        }
        assert sorted(
            (count for part, _, _ in handed for count in part),
            key=lambda count: count.dimension,
        ) == sorted(found, key=lambda count: count.dimension)

    def test_each_facts_count_is_a_read_of_its_own(
        self, container: ServiceContainer, service: CountsService, session: DbSession
    ) -> None:
        view = _view(container, "t=all")

        with sent(session) as statements:
            service.attributes(view, NOW)

        reads = [
            statement
            for statement in statements
            if statement == "SET TRANSACTION READ ONLY" or "GROUPING SETS" in statement
        ]
        assert [one == "SET TRANSACTION READ ONLY" for one in reads] == [
            True,
            False,
            True,
            False,
        ]

    def test_one_statement_a_fact_counts_by_grouping_and_never_by_a_distinct_sort(
        self, container: ServiceContainer, service: CountsService, session: DbSession
    ) -> None:
        view = _view(container, "t=all")

        with sent(session) as statements:
            service.attributes(view, NOW)

        counting = [
            statement for statement in statements if "GROUPING SETS" in statement
        ]
        assert len(counting) == 2
        assert not any("count(DISTINCT" in statement for statement in counting)


@pytest.mark.usefixtures("worked")
class TestQuickFilters:
    def test_each_counts_what_it_keeps_and_sums_its_figure_over_it(
        self, container: ServiceContainer, service: CountsService
    ) -> None:
        found = service.quick_filters(_view(container, "t=all"), NOW)

        assert found == (
            QuickFilterCount("compactions", 1, None),
            QuickFilterCount("expensive", 0, 0.0),
            QuickFilterCount("misses", 1, 1.0),
            QuickFilterCount("outliers", 0, None),
            QuickFilterCount("past_ttl", 1, 0.0),
        )

    def test_one_that_is_on_narrows_the_others(
        self, container: ServiceContainer, service: CountsService
    ) -> None:
        counts = _quick_filters(container, service, "t=all&b=past_ttl")

        assert (counts["past_ttl"].count, counts["misses"].count) == (1, 0)
        assert counts["compactions"].count == 0

    def test_a_chip_of_the_view_narrows_them_and_a_threshold_on_its_rows_does_not(
        self, container: ServiceContainer, service: CountsService, worked: Record
    ) -> None:
        loose = _quick_filters(
            container, service, "t=all&c=!project:" + str(worked.project.id)
        )
        thresholded = _quick_filters(container, service, "t=all&c=@rows,gt,1,cost.sum")

        assert loose["misses"].count == 0
        assert thresholded["misses"].count == 1

    def test_an_each_item_one_coarser_than_the_call_counts_its_items(
        self, container: ServiceContainer, service: CountsService, session: DbSession
    ) -> None:
        _quick_filter(
            session, "costly", "@items,gt,1,cost.sum.conversation", amount="cost"
        )

        counts = _quick_filters(container, service, "t=all")

        assert counts["costly"] == QuickFilterCount("costly", 1, 1.75)

    def test_an_each_item_one_negated_counts_the_items_that_fail(
        self, container: ServiceContainer, service: CountsService, session: DbSession
    ) -> None:
        _quick_filter(
            session, "cheap", "!@items,gt,1,cost.sum.conversation", amount="cost"
        )
        kept = container.rows_service().rows("t=all&by=conversation&b=cheap", NOW)

        counts = _quick_filters(container, service, "t=all")

        assert counts["cheap"].count == kept.total_rows == 3
        assert counts["cheap"].amount == pytest.approx(0.90)

    def test_all_are_counted_one_statement_a_fact(
        self, container: ServiceContainer, service: CountsService, session: DbSession
    ) -> None:
        _quick_filter(
            session, "costly", "@items,gt,1,cost.sum.conversation", amount="cost"
        )
        _quick_filter(session, "errors", "event_error:1")
        session.execute(
            delete(models.QuickFilter).where(models.QuickFilter.code == "outliers")
        )
        view = _view(container, "t=all")

        with sent(session) as statements:
            service.quick_filters(view, NOW)

        tallies = [
            statement for statement in statements if "GROUPING SETS" in statement
        ]
        assert len(tallies) == 2
        assert not any("count(DISTINCT" in statement for statement in tallies)

    def test_the_judging_of_the_bys_rows_and_the_tallies_are_reads_of_their_own(
        self, container: ServiceContainer, service: CountsService, session: DbSession
    ) -> None:
        view = _view(container, "t=all")

        with sent(session) as statements:
            service.quick_filters(view, NOW)

        reads = [
            statement
            for statement in statements
            if statement == "SET TRANSACTION READ ONLY" or "GROUPING SETS" in statement
        ]
        assert reads[0] == "SET TRANSACTION READ ONLY"
        assert reads.count("SET TRANSACTION READ ONLY") == 2
        tallies = reads.index("SET TRANSACTION READ ONLY", 1)
        assert all("GROUPING SETS" in one for one in reads[tallies + 1 :])

    def test_one_on_the_bys_rows_counts_the_rows_it_keeps(
        self, container: ServiceContainer, service: CountsService, session: DbSession
    ) -> None:
        _quick_filter(session, "big", "@rows,gt,1,cost.sum", amount="cost")

        counts = _quick_filters(container, service, "t=all&by=conversation")

        assert counts["big"] == QuickFilterCount("big", 1, 1.75)

    def test_one_on_the_bys_rows_that_is_on_narrows_the_others_to_its_rows(
        self, container: ServiceContainer, service: CountsService, session: DbSession
    ) -> None:
        _quick_filter(session, "big", "@rows,gt,1,cost.sum", amount="cost")

        counts = _quick_filters(container, service, "t=all&by=psession&b=big")

        assert counts["big"] == QuickFilterCount("big", 1, 1.85)
        assert (counts["misses"].count, counts["past_ttl"].count) == (1, 1)
        assert counts["expensive"] == QuickFilterCount("expensive", 0, 0.0)

    def test_one_on_the_bys_rows_that_marks_narrows_none_of_the_others(
        self, container: ServiceContainer, service: CountsService, session: DbSession
    ) -> None:
        _quick_filter(
            session, "small", "@rows,lt,1,cost.sum", amount="cost", marks=True
        )

        on = _quick_filters(container, service, "t=all&by=psession&b=small")
        off = _quick_filters(container, service, "t=all&by=psession")

        assert on == off

    def test_the_outlier_rows_count_the_outliers_among_the_bys_rows(
        self, container: ServiceContainer, service: CountsService, session: DbSession
    ) -> None:
        session.execute(
            text(
                """
                INSERT INTO calls (transcript_id, message_id, position, completed_at,
                    model_code, input_tokens, cache_write_5m_tokens,
                    cache_write_1h_tokens, cache_read_tokens, output_tokens, cost)
                SELECT transcript_id, 'msg_costly', 2, completed_at, model_code,
                    1, 0, 0, 0, 1, 10
                FROM calls ORDER BY completed_at DESC LIMIT 1
                """
            )
        )

        counts = _quick_filters(container, service, "t=all&by=call")

        assert counts["outliers"] == QuickFilterCount("outliers", 1, None)


@pytest.mark.usefixtures("worked")
class TestValues:
    def test_each_value_in_scope_with_its_rows_and_cost_the_largest_first(
        self, service: CountsService, worked: Record
    ) -> None:
        found = service.values("t=all", "project", now=NOW)

        assert found.address.address == "#dash/t=all&by=project&m=cost.sum&col=none"
        assert found.zone == "Europe/Amsterdam"
        assert found.dimension.key == "project"
        assert found.values == (
            AttributeValue(worked.project.id, "Recipe box", 5, 2.6),
            AttributeValue(None, "(No project)", 1, 0.05),
        )
        assert found.total == 2

    def test_its_own_chips_are_left_out_and_the_others_kept(
        self, service: CountsService, worked: Record
    ) -> None:
        found = service.values(
            f"t=all&c=project:{worked.project.id}&c=model:claude-opus-4-5",
            "project",
            now=NOW,
        )

        assert [(value.key, value.count) for value in found.values] == [
            (worked.project.id, 4),
            (None, 1),
        ]

    def test_a_search_keeps_those_whose_label_or_key_holds_it(
        self, service: CountsService, worked: Record
    ) -> None:
        by_label = service.values("t=all", "project", "RECIPE", NOW)
        by_key = service.values("t=all", "project", str(worked.project.id)[:8], NOW)

        assert [value.key for value in by_label.values] == [worked.project.id]
        assert by_label.total == 1
        assert [value.key for value in by_key.values] == [worked.project.id]

    def test_a_closed_lists_values_are_searched_by_their_names(
        self, service: CountsService
    ) -> None:
        found = service.values("t=all", "event_kind", "tool", NOW)

        assert [(value.key, value.label) for value in found.values] == [
            ("denied", "Tool use denied"),
            ("output_saved", "Tool output saved to disk"),
        ]
        assert found.total == 2

    def test_a_dimension_of_a_fact_with_no_cost_has_none(
        self, service: CountsService
    ) -> None:
        found = service.values("t=all", "event_error", now=NOW)

        assert {(value.key, value.cost) for value in found.values} == {
            (0, None),
            (1, None),
        }

    def test_a_times_values_are_in_their_order(self, service: CountsService) -> None:
        found = service.values("t=all", "day", now=NOW)

        assert [(str(value.key), value.count) for value in found.values] == [
            ("2026-11-12", 5),
            ("2026-11-13", 1),
        ]

    def test_at_most_so_many_with_the_count_of_all(
        self, service: CountsService, session: DbSession, worked: Record
    ) -> None:
        session.execute(
            text(
                """
                INSERT INTO calls (transcript_id, message_id, position, completed_at,
                    model_code, input_tokens, cache_write_5m_tokens,
                    cache_write_1h_tokens, cache_read_tokens, output_tokens, cost)
                SELECT :thread, 'msg_many_' || n, 100 + n, :at, 'claude-opus-4-5', 1,
                    0, 0, 0, 1, n * 0.001
                FROM generate_series(1, :many) AS n
                """
            ),
            {
                "thread": worked.loose.id,
                "at": worked.calls[4].completed_at,
                "many": VALUES,
            },
        )

        found = service.values("t=all", "call", now=NOW)

        assert len(found.values) == VALUES
        assert found.total == VALUES + 6

    def test_a_read_past_the_databases_limit_on_temporary_files_is_refused(
        self, service: CountsService, session: DbSession
    ) -> None:
        session.execute(
            text(
                """
                INSERT INTO calls (transcript_id, message_id, position, completed_at,
                    model_code, input_tokens, cache_write_5m_tokens,
                    cache_write_1h_tokens, cache_read_tokens, output_tokens, cost)
                SELECT t.transcript_id, 'msg_many_' || n, 100 + n, t.completed_at,
                    t.model_code, 1, 0, 0, 0, 1, n * 0.001
                FROM generate_series(1, 20000) AS n,
                    (SELECT transcript_id, completed_at, model_code FROM calls
                     ORDER BY id LIMIT 1) AS t
                """
            )
        )

        session.execute(text("SET LOCAL temp_file_limit = '64kB'"))
        session.execute(text("SET LOCAL work_mem = '64kB'"))

        with pytest.raises(QueryRefusedException) as refused:
            service.values("t=all", "call", now=NOW)

        assert refused.value.reason == "temp_file_limit"

    def test_no_such_dimension_is_refused_with_the_nearest(
        self, service: CountsService
    ) -> None:
        with pytest.raises(ValidationException) as refused:
            service.values("t=all", "projct", now=NOW)

        assert str(refused.value) == (
            'Cannot list the values of "projct" because it is no dimension of the '
            'catalogue\'s. Did you mean "project"?'
        )

    def test_a_state_with_faults_is_refused(self, service: CountsService) -> None:
        with pytest.raises(StateRefusedException):
            service.values("by=phases", "project", now=NOW)
