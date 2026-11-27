"""The dimensions Pilot's code declares and those the record's rows give
(F154.4): each a join path, read on the record at the query."""

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.dashboard.catalogue import Catalogue, Path
from app.dashboard.dimensions import (
    SOURCES,
    WORK_TYPES,
    declared_keys,
    own_dimensions,
    reaches,
    version_dimension,
    version_keys,
)
from app.models import Component, Project, User, WorkUnitKindNesting
from app.models.reference import ChatKind, SessionState, TurnCause, WorkTrigger
from app.services.container import ServiceContainer
from tests.support.dashboard import (
    ZONE,
    Record,
    catalogue,
    labelled,
    named,
    read,
    record,
)
from tests.support.labels import COURSE, DISH, MENU, work_unit
from tests.support.transcripts import OPUS, STARTED
from tests.support.turns import turn_at
from tests.support.working_on import Camp

QUESTION = "# Where do we pitch?\n\n```question id=Q1\n```\n"


@pytest.fixture
def held(
    session: DbSession, person: User, project: Project, project_session: models.Session
) -> Record:
    return record(session, person, project, project_session)


def _calls(session: DbSession, *dimensions: str) -> list[tuple[object, ...]]:
    """The dimensions on the record's six rows of the Call fact, by their
    moment: the work item's two Calls, its sub-agent's, its third, the
    chat's Turn standing in, and the Call run by hand."""
    index = catalogue(session)
    return read(
        session, index, "call", *named(index, *dimensions), by=lambda row: row["at"]
    )


def _named_and_timed(index: Catalogue, *parts: str) -> tuple[list[Path], list[Path]]:
    """Each part's name and time, the paths a part of Pilot's work has."""
    names: list[Path] = []
    times: list[Path] = []
    for key in parts:
        part = index.dimension(key)
        assert part.name is not None and part.at is not None, key
        names.append(part.name)
        times.append(part.at)
    return names, times


class TestEveryDimension:
    def test_it_reads_on_every_fact_that_offers_it(
        self, session: DbSession, held: Record
    ) -> None:
        labelled(session, held)
        index = catalogue(session)

        for dimension in index.dimensions:
            offered = index.offered(dimension.key)
            assert offered, dimension.key
            for fact in offered:
                paths = [
                    path
                    for path in (
                        dimension.path,
                        dimension.name,
                        dimension.axis,
                        dimension.at,
                    )
                    if path is not None
                ]
                rows = read(session, index, fact, *paths, by=lambda row: row["at"])
                assert rows, (dimension.key, fact)

    def test_its_key_reads_as_a_part_of_a_state(self, session: DbSession) -> None:
        for dimension in own_dimensions(ZONE):
            assert dimension.key.replace("_", "").isalnum(), dimension.key
            assert dimension.key == dimension.key.lower()

    def test_a_part_has_its_nouns_and_an_order_its_part_and_axis(
        self, session: DbSession
    ) -> None:
        dimensions = {dimension.key: dimension for dimension in own_dimensions(ZONE)}

        for dimension in dimensions.values():
            assert (dimension.group == "part") == (dimension.one is not None)
            assert (dimension.group == "part") == (dimension.many is not None)
            assert (dimension.group == "order") == (dimension.base is not None)
            assert (dimension.group == "order") == (dimension.axis is not None)
            assert dimension.group == "part" or not dimension.figures
            for other in (dimension.next, dimension.next_null, dimension.base):
                assert other is None or other in dimensions
            for shown in dimension.shows:
                assert shown in dimensions
        assert dimensions["session_start"].base == "psession"
        assert dimensions["turn_seq"].base == "pturn"
        assert dimensions["session_start"].group == dimensions["turn_seq"].group

    def test_a_time_on_a_line_has_its_unit_one_that_comes_round_none(
        self, session: DbSession
    ) -> None:
        assert {
            dimension.key: dimension.unit
            for dimension in own_dimensions(ZONE)
            if dimension.group == "time"
        } == {"qweek": "quota_week", "day": "day", "weekday": None, "hod": None}
        assert {
            dimension.unit
            for dimension in own_dimensions(ZONE)
            if dimension.group != "time"
        } == {None}

    def test_what_a_fact_offers_is_what_its_rows_reach(
        self, session: DbSession
    ) -> None:
        index = catalogue(session)

        assert index.offered("project") == ("call", "turn", "event")
        assert index.offered("conversation") == ("call", "turn", "event")
        assert index.offered("qweek") == ("call", "turn", "event", "work_unit")
        assert index.offered("model") == ("call", "event")
        assert index.offered("call") == ("call", "event")
        assert index.offered("estimate") == ("call",)
        assert index.offered("event_kind") == ("event",)
        assert index.offered("event_error") == ("event",)
        assert index.offered("call_class") == ("call", "event")
        assert index.offered("segment_kind") == ("call", "event")
        assert index.offered("work_unit") == ("call", "event", "work_unit")
        assert index.offered("role") == ("call", "event", "work_unit")


class TestParts:
    def test_a_project_is_by_its_id_and_named(
        self, session: DbSession, held: Record
    ) -> None:
        index = catalogue(session)
        project = index.dimension("project")
        assert project.name is not None

        rows = read(
            session, index, "call", project.path, project.name, by=lambda row: row["at"]
        )

        assert rows[0] == rows[4] == (held.project.id, "Recipe box")
        assert rows[5] == (None, None)

    def test_the_parts_of_pilots_work(self, session: DbSession, held: Record) -> None:
        rows = _calls(session, "psession", "pturn", "conversation", "call")

        assert rows[0] == (
            held.work.id,
            held.work_turn.id,
            held.thread.id,
            held.calls[0].id,
        )
        assert rows[2] == (
            held.work.id,
            held.work_turn.id,
            held.sub_agent.id,
            held.calls[3].id,
        )
        assert rows[4] == (held.chat.id, held.chat_turn.id, None, None)
        assert rows[5] == (None, None, held.loose.id, held.calls[4].id)

    def test_pilots_parts_are_named_each_with_its_time(
        self, session: DbSession, held: Record
    ) -> None:
        held.work.started_at = STARTED - timedelta(minutes=2)
        held.chat.started_at = STARTED + timedelta(hours=2)
        held.sub_agent.description = "Find the scaling code"
        session.flush()
        index = catalogue(session)
        names, times = _named_and_timed(
            index, "psession", "pturn", "conversation", "call"
        )

        named_rows = read(session, index, "call", *names, by=lambda row: row["at"])
        timed_rows = read(session, index, "call", *times, by=lambda row: row["at"])

        assert named_rows[0] == ("Work", "Turn 1 · brief", "Main thread", "Call 1")
        assert named_rows[2] == (
            "Work",
            "Turn 1 · brief",
            "Explore · Find the scaling code",
            "Call 1",
        )
        assert named_rows[4] == ("Project chat", "Turn 1 · person", None, None)
        assert named_rows[5] == (None, None, "Main thread", "Call 1")
        assert timed_rows[0] == (
            held.work.started_at,
            held.work_turn.started_at,
            held.thread.first_call_at,
            held.calls[0].completed_at,
        )
        assert timed_rows[2][2:] == (
            held.sub_agent.first_call_at,
            held.calls[3].completed_at,
        )
        assert timed_rows[4][:3] == (
            held.chat.started_at,
            held.chat_turn.started_at,
            None,
        )
        assert timed_rows[5] == (
            None,
            None,
            held.loose.first_call_at,
            held.calls[4].completed_at,
        )

    def test_a_sub_agent_with_neither_type_nor_task_is_a_sub_agent(
        self, session: DbSession, held: Record
    ) -> None:
        held.sub_agent.agent_type = None
        session.flush()
        index = catalogue(session)
        names, _ = _named_and_timed(index, "conversation")

        assert read(session, index, "call", *names, by=lambda row: row["at"])[2] == (
            "Sub-agent",
        )

    @pytest.mark.usefixtures("person")
    def test_a_session_is_its_work_items_or_jobs_number_and_title_else_its_kind(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        camp = Camp(container, session)
        worker = camp.worker()
        job = camp.job_after(worker)
        defining, calling = (
            models.Session(
                project_id=camp.project.id,
                kind_code=kind,
                cwd="/work/PilotProjects",
                token_hash=hash_ * 64,
                state_code=SessionState.IDLE,
            )
            for kind, hash_ in (("chat", "5"), ("conversation", "4"))
        )
        session.add_all([defining, calling])
        session.flush()
        session.add(
            models.Chat(
                id=defining.id,
                project_id=camp.project.id,
                session_kind_code="chat",
                kind_code=ChatKind.DEFINITION,
            )
        )
        for minute, run in enumerate((worker, job, defining, calling)):
            turn_at(session, run, STARTED + timedelta(minutes=minute))
        turn_at(
            session, worker, STARTED + timedelta(minutes=9)
        ).cause_code = TurnCause.FOLLOW_UP
        session.flush()
        index = catalogue(session)
        names, _ = _named_and_timed(index, "psession", "pturn")

        rows = read(session, index, "turn", *names, by=lambda row: row["at"])

        working = f"#{camp.line(worker).seq} Building the camp"
        assert rows == [
            (working, "Turn 1 · brief"),
            (f"#{camp.line(job).seq} Pre-ruling", "Turn 1 · brief"),
            ("Definition chat", "Turn 1 · brief"),
            ("Conversation", "Turn 1 · brief"),
            (working, "Turn 2 · follow up"),
        ]

    def test_a_sitting_is_by_its_start(self, session: DbSession, held: Record) -> None:
        rows = _calls(session, "sitting")

        assert rows == [(None,)] * 5 + [(held.loose.first_call_at,)]

    def test_an_order_dimension_is_its_part_with_its_place(
        self, session: DbSession, held: Record
    ) -> None:
        index = catalogue(session)
        sessions = index.dimension("session_start")
        turns = index.dimension("turn_seq")
        assert sessions.axis is not None and turns.axis is not None

        rows = read(
            session,
            index,
            "turn",
            sessions.path,
            sessions.axis,
            turns.path,
            turns.axis,
            by=lambda row: row["at"],
        )

        assert rows == [
            (
                held.work.id,
                held.work.created_at,
                held.work_turn.id,
                held.work_turn.started_at,
            ),
            (
                held.chat.id,
                held.chat.created_at,
                held.chat_turn.id,
                held.chat_turn.started_at,
            ),
        ]


class TestPilotsAttributes:
    def test_the_source_and_the_work_type_of_a_work_items_run_and_a_chat(
        self, session: DbSession, held: Record
    ) -> None:
        rows = _calls(session, "source", "work_type", "session_kind")

        assert rows[0] == ("work", "work", "work")
        assert rows[4] == ("chat", "chat:project", "chat")
        assert rows[5] == (None, None, None)

    @pytest.mark.usefixtures("person")
    def test_pilots_sessions_by_what_each_is_for(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        camp = Camp(container, session)
        worker = camp.worker(conversation="camp-conversation")
        pass_ = camp.job_after(worker)
        clarifying = camp.clarification(pass_, worker)
        question = camp.registered(worker, QUESTION)
        researching = camp.worker()
        camp.research(question, "Q1", researching)
        doing = camp.worker()
        camp.claim(question, "Q1", doing)
        setup = camp.job_on(None, WorkTrigger.SETUP)
        calling = models.Session(
            project_id=camp.project.id,
            kind_code="conversation",
            cwd="/work/PilotProjects",
            token_hash="4" * 64,
            state_code=SessionState.IDLE,
        )
        session.add(calling)
        session.flush()
        runs = (worker, pass_, clarifying, researching, doing, setup, calling)
        for minute, run in enumerate(runs):
            turn_at(session, run, STARTED + timedelta(minutes=minute))
        index = catalogue(session)

        rows = read(
            session,
            index,
            "turn",
            *named(index, "source", "work_type", "session_kind"),
            by=lambda row: row["at"],
        )

        assert rows == [
            ("work", "work", "work"),
            ("pilot", "job:worker_turn_ended", "job"),
            ("pilot", "clarification", "work"),
            ("pilot", "research", "work"),
            ("work", "claimed", "work"),
            ("pilot", "job:setup", "job"),
            ("chat", "conversation", "conversation"),
        ]

    def test_the_source_and_work_type_values_are_pilots_closed_lists(self) -> None:
        assert [value.code for value in SOURCES] == ["work", "pilot", "chat"]
        assert [value.code for value in WORK_TYPES] == [
            *(f"chat:{kind.value}" for kind in ChatKind),
            "conversation",
            *(f"job:{trigger.value}" for trigger in WorkTrigger),
            "clarification",
            "research",
            "claimed",
            "work",
        ]

    def test_a_turns_cause_its_person_and_whether_it_failed(
        self, session: DbSession, held: Record, person: User
    ) -> None:
        index = catalogue(session)
        author = index.dimension("person")
        assert author.name is not None

        rows = read(
            session,
            index,
            "call",
            *named(index, "turn_cause", "failed"),
            author.path,
            author.name,
            by=lambda row: row["at"],
        )

        assert rows[0] == ("brief", 0, None, None)
        assert rows[4] == ("person", 1, person.id, "Ada Example")
        assert rows[5] == (None, 0, None, None)
        assert [value.code for value in index.dimension("turn_cause").values or ()] == [
            cause.value for cause in TurnCause
        ]

    def test_the_environment_is_the_threads_else_the_sessions(
        self, session: DbSession, held: Record
    ) -> None:
        index = catalogue(session)
        environment = index.dimension("environment")
        assert environment.name is not None
        held.chat.environment_id = held.work.environment_id
        session.flush()

        rows = read(
            session,
            index,
            "call",
            environment.path,
            environment.name,
            by=lambda row: row["at"],
        )

        assert rows[0] == rows[4] == (held.work.environment_id, "Example-1")
        assert rows[5] == (None, None)

    def test_the_repository_is_the_threads(
        self, session: DbSession, held: Record
    ) -> None:
        index = catalogue(session)
        repository = index.dimension("repository")
        assert repository.name is not None

        rows = read(session, index, "call", repository.name, by=lambda row: row["at"])

        assert [name for (name,) in rows] == [
            "RecipeBox",
            "RecipeBox",
            None,
            "RecipeBox",
            None,
            None,
        ]


class TestTheCollectorsAttributes:
    def test_a_threads_agent(self, session: DbSession, held: Record) -> None:
        rows = _calls(session, "agent_type", "sub")

        assert rows[0] == (None, 0)
        assert rows[2] == ("Explore", 1)
        assert rows[4] == (None, 0)

    def test_a_calls_own(self, session: DbSession, held: Record) -> None:
        rows = _calls(
            session,
            "model",
            "effort",
            "stop_reason",
            "miss",
            "miss_cause",
            "past_ttl",
            "rewind",
            "compaction",
            "compact_trigger",
            "estimate",
        )

        assert rows[0] == (OPUS, "high", None, 0, None, 0, 0, 0, None, 0)
        assert rows[1] == (OPUS, None, "max_tokens", 0, None, 1, 1, 0, None, 0)
        assert rows[3] == (OPUS, None, None, 1, "compaction", 0, 0, 1, "auto", 0)
        assert rows[4] == (None, None, None, 0, None, 0, 0, 0, None, 1)

    def test_an_events_kind_and_whether_it_is_an_error(
        self, session: DbSession, held: Record
    ) -> None:
        index = catalogue(session)

        rows = read(session, index, "event", *named(index, "event_kind", "event_error"))

        assert ("api_error", 1) in rows
        assert ("hook_error", 1) in rows
        assert ("cache_miss", 0) in rows
        assert len(rows) == 10


class TestTime:
    def test_the_quota_week_is_by_its_start(
        self, session: DbSession, held: Record
    ) -> None:
        rows = _calls(session, "qweek")
        week = session.scalar(
            select(models.QuotaWeek.starts_at).where(
                models.QuotaWeek.starts_at <= STARTED,
                STARTED < models.QuotaWeek.ends_at,
            )
        )

        assert rows[0] == (week,)

    def test_the_day_the_weekday_and_the_hour_are_the_zones(
        self, session: DbSession, held: Record
    ) -> None:
        # The Call run by hand completed at 09:30 UTC on Friday 13 November.
        held.calls[4].completed_at = held.calls[4].completed_at.replace(hour=23)
        session.flush()

        def local(zone: str) -> tuple[object, ...]:
            index = catalogue(session, zone)
            return read(
                session,
                index,
                "call",
                *named(index, "day", "weekday", "hod"),
                by=lambda row: row["at"],
            )[-1]

        assert local("Europe/Amsterdam") == (date(2026, 11, 14), 6, 0)
        assert local("UTC") == (date(2026, 11, 13), 5, 23)
        assert local("America/New_York") == (date(2026, 11, 13), 5, 18)

    def test_the_local_times_lines_name_the_zone(self) -> None:
        dimensions = {
            dimension.key: dimension for dimension in own_dimensions("Asia/Tokyo")
        }

        for key in ("day", "weekday", "hod"):
            assert "Asia/Tokyo" in dimensions[key].line
        assert [value.name for value in dimensions["weekday"].values or ()] == [
            "Mon",
            "Tue",
            "Wed",
            "Thu",
            "Fri",
            "Sat",
            "Sun",
        ]


class TestVersions:
    def test_a_component_is_a_dimension_of_the_version_a_launch_ran_with(
        self, session: DbSession, held: Record
    ) -> None:
        index = catalogue(session)

        assert index.dimension("claude_code_version").label == "claude-code version"
        assert index.offered("claude_code_version") == ("call", "event")
        assert _calls(session, "claude_code_version", "collector_version") == [
            ("2.1.317", None),
            ("2.1.317", None),
            ("2.1.317", None),
            ("2.1.317", None),
            (None, None),
            (None, None),
        ]

    def test_a_version_reads_once_the_session_lets_its_components_go(
        self, session: DbSession, held: Record
    ) -> None:
        index = catalogue(session)
        # As the app's session leaves the Components its assembly read once
        # it commits and closes, while the process keeps the catalogue.
        session.expire_all()
        session.expunge_all()

        assert read(
            session,
            index,
            "call",
            *named(index, "claude_code_version"),
            by=lambda row: row["at"],
        )[0] == ("2.1.317",)

    def test_a_components_key_is_its_code_in_a_states_letters(self) -> None:
        components = [
            Component(code=code, name=code)
            for code in ("plugin:dev", "claude-code", "plugin_dev", "Plugin.Dev")
        ]

        assert version_keys(components) == {
            "Plugin.Dev": "plugin_dev_version",
            "claude-code": "claude_code_version",
            "plugin:dev": "plugin_dev_version_2",
            "plugin_dev": "plugin_dev_version_3",
        }

    def test_a_version_dimension_names_its_component(self) -> None:
        dimension = version_dimension(
            Component(code="claude-code", name="Claude Code"), "claude_code_version"
        )

        assert (dimension.key, dimension.label, dimension.group) == (
            "claude_code_version",
            "Claude Code version",
            "attribute",
        )


class TestTheLabels:
    def test_a_kinds_part_is_a_rows_unit_of_it_its_own_or_one_it_sits_in(
        self, session: DbSession, held: Record
    ) -> None:
        units = labelled(session, held)
        menu, course = units.menu.id, units.course.id

        rows = _calls(session, "menu", "course", "dish", "work_unit")

        # The sub-agent's Call reaches its unit through its main thread's
        # Launch; the stand-in and the Call run by hand reach none.
        assert rows == [
            (menu, course, None, course),
            (menu, course, None, course),
            (menu, course, None, course),
            (menu, course, None, course),
            (None, None, None, None),
            (None, None, None, None),
        ]

    def test_a_kinds_part_is_named_by_its_units_title(
        self, session: DbSession, held: Record
    ) -> None:
        labelled(session, held)
        index = catalogue(session)
        names = [index.dimension(key).name for key in ("menu", "course", "work_unit")]

        rows = read(session, index, "call", *names, by=lambda row: row["at"])  # type: ignore[arg-type]

        assert rows[0] == ("Dinner", "Soup", "Soup")
        assert rows[-1] == (None, None, None)

    def test_a_kind_reads_the_nearest_unit_of_it_where_a_step_is_skipped(
        self, session: DbSession, held: Record
    ) -> None:
        units = labelled(session, held)
        session.add(WorkUnitKindNesting(inner_code=DISH, outer_code=MENU))
        session.flush()
        bread = work_unit(session, "kitchen|Dinner|Bread", DISH, part_of=units.menu)
        index = catalogue(session)

        rows = read(
            session,
            index,
            "work_unit",
            lambda row: row["work_unit_id"],
            *named(index, "menu", "course", "dish"),
        )

        menu, course = units.menu.id, units.course.id
        assert rows == [
            (menu, menu, None, None),
            (course, menu, course, None),
            (bread.id, menu, None, bread.id),
        ]

    def test_a_unit_carries_its_role_round_variant_outcome_and_rework_kind(
        self, session: DbSession, held: Record
    ) -> None:
        labelled(session, held)

        rows = _calls(session, "role", "round", "variant", "outcome", "rework_kind")

        assert rows[0] == ("cook", 2, "clear", "served", "recooked")
        assert rows[4] == (None, None, None, None, None)

    def test_a_calls_labels_are_the_labellers(
        self, session: DbSession, held: Record
    ) -> None:
        labelled(session, held)

        rows = _calls(
            session, "call_class", "wait_cause", "avoidable_kind", "segment_kind"
        )

        assert rows[:3] == [
            ("chop", "oven", None, "prep"),
            ("spill", None, "spilt", "prep"),
            (None, None, None, None),
        ]

    def test_with_none_declared_a_labels_list_is_empty(
        self, session: DbSession
    ) -> None:
        index = catalogue(session)

        for key in (
            "call_class",
            "avoidable_kind",
            "wait_cause",
            "segment_kind",
            "outcome",
            "rework_kind",
        ):
            assert index.dimension(key).values == (), key


class TestDeclaredKeys:
    def test_a_code_is_its_key_in_a_states_letters_where_it_is_free(self) -> None:
        assert declared_keys(["menu", "Side-Dish", "call"], {"call"}) == {
            "menu": "menu",
            "Side-Dish": "side_dish",
            "call": "call_2",
        }

    def test_two_codes_that_read_alike_take_a_number_after_the_first(self) -> None:
        assert declared_keys(["side-dish", "side_dish", "Side.Dish"], ()) == {
            "side-dish": "side_dish",
            "side_dish": "side_dish_2",
            "Side.Dish": "side_dish_3",
        }


class TestReaches:
    def test_a_kind_reaches_up_the_longest_chain_that_ends_at_it(self) -> None:
        nestings = [
            (COURSE, MENU),
            (DISH, COURSE),
            ("garnish", DISH),
            ("garnish", COURSE),
        ]

        assert reaches(nestings) == {MENU: 3, COURSE: 2, DISH: 1, "garnish": 0}

    def test_a_kind_is_on_a_chain_once(self) -> None:
        assert reaches([(COURSE, MENU), (MENU, COURSE)]) == {MENU: 1, COURSE: 1}

    def test_none_reach_nothing(self) -> None:
        assert reaches([]) == {}
