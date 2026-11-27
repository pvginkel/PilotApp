"""The facts Pilot's code declares, read from the record at the query
(F154.3; DB decision 79.42), and the joins their rows reach it through."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import models
from app.dashboard.facts import (
    CALL,
    DETAIL,
    EVENT,
    FACTS,
    OCCURRENCES,
    TURN,
    WORK_UNIT,
    event_key,
    measure_join,
    own_joins,
    read_event_key,
    unit_join,
)
from app.models import Project, QuotaWeek, User
from app.models.call import RECORDED_ELSEWHERE
from tests.support import transcripts
from tests.support.dashboard import GAP, Record, catalogue, labelled, read, record
from tests.support.transcripts import OTHER, STARTED


@pytest.fixture
def held(
    session: DbSession, person: User, project: Project, project_session: models.Session
) -> Record:
    return record(session, person, project, project_session)


class TestCall:
    def test_one_row_is_a_call_or_a_turn_standing_in(
        self, session: DbSession, held: Record
    ) -> None:
        rows = read(
            session,
            catalogue(session),
            "call",
            lambda row: row["call_id"],
            lambda row: row["estimate"],
            lambda row: row["session_id"],
            lambda row: row["turn_seq"],
            by=lambda row: row["at"],
        )

        first, second, explored, third, stand_in, by_hand = rows
        assert [row[0] for row in rows] == [
            held.calls[0].id,
            held.calls[1].id,
            held.calls[3].id,
            held.calls[2].id,
            None,
            held.calls[4].id,
        ]
        assert [row[1] for row in rows] == [False, False, False, False, True, False]
        # A Call is its Launch's Session's and Turn's; a sub-agent's too.
        assert first[2:] == second[2:] == explored[2:] == (held.work.id, 1)
        assert stand_in[2:] == (held.chat.id, 1)
        assert by_hand[2:] == (None, None)

    def test_a_call_carries_its_place_in_its_file_and_a_stand_in_none(
        self, session: DbSession, held: Record
    ) -> None:
        source = CALL.source

        places = session.execute(
            select(source.c.call_id, source.c.position).order_by(source.c.at)
        ).all()

        assert [tuple(row) for row in places] == [
            (held.calls[0].id, 1),
            (held.calls[1].id, 2),
            (held.calls[3].id, 1),
            (held.calls[2].id, 3),
            (None, None),
            (held.calls[4].id, 1),
        ]

    def test_a_turn_whose_thread_is_collected_does_not_stand_in(
        self, session: DbSession, held: Record
    ) -> None:
        stand_ins = read(
            session,
            catalogue(session),
            "call",
            lambda row: row["session_id"],
            lambda row: row["estimate"],
        )

        assert (held.work.id, True) not in stand_ins
        assert (held.chat.id, True) in stand_ins

    def test_a_stand_in_carries_its_turns_cost_and_tokens(
        self, session: DbSession, held: Record
    ) -> None:
        source = CALL.source
        stand_in = session.execute(
            select(
                source.c.cost,
                source.c.input_tokens,
                source.c.cache_write_tokens,
                source.c.cache_read_tokens,
                source.c.output_tokens,
                source.c.context_tokens,
                source.c.transcript_id,
                source.c.model_code,
                source.c.at,
            ).where(source.c.estimate)
        ).one()

        assert tuple(stand_in) == (
            Decimal("0.75"),
            100,
            2_000,
            30_000,
            400,
            None,
            None,
            None,
            held.chat_turn.ended_at,
        )

    def test_a_turn_in_flight_stands_in_at_its_start_with_no_tokens(
        self, session: DbSession, held: Record
    ) -> None:
        held.chat_turn.ended_at = None
        held.chat_turn.cost = None
        session.execute(
            models.TokenCount.__table__.delete().where(
                models.TokenCount.turn_id == held.chat_turn.id
            )
        )
        session.flush()
        source = CALL.source

        stand_in = session.execute(
            select(source.c.at, source.c.cost, source.c.input_tokens).where(
                source.c.estimate
            )
        ).one()

        assert tuple(stand_in) == (held.chat_turn.started_at, None, 0)

    def test_a_call_carries_its_own_facts(
        self, session: DbSession, held: Record
    ) -> None:
        source = CALL.source
        second = session.execute(
            select(
                source.c.transcript_id,
                source.c.launch_id,
                source.c.model_code,
                source.c.stop_reason_code,
                source.c.rewind,
                source.c.cache_miss,
                source.c.past_ttl,
                source.c.waited_seconds,
                source.c.cache_write_tokens,
                source.c.context_tokens,
                source.c.cost,
                source.c.at,
            ).where(source.c.call_id == held.calls[1].id)
        ).one()

        assert tuple(second) == (
            held.thread.id,
            held.calls[1].launch_id,
            transcripts.OPUS,
            "max_tokens",
            True,
            False,
            True,
            30.0,
            3_310,
            1_204 + 3_310 + 48_112,
            Decimal("0.25"),
            held.calls[1].completed_at,
        )

    def test_a_call_with_no_caches_reads_no_rewind_miss_or_wait(
        self, session: DbSession, held: Record
    ) -> None:
        underived = transcripts.call(session, held.loose, 2)
        source = CALL.source

        flags = session.execute(
            select(source.c.rewind, source.c.cache_miss, source.c.past_ttl).where(
                source.c.call_id == underived.id
            )
        ).one()

        assert tuple(flags) == (False, False, False)


class TestTurn:
    def test_one_row_is_a_turn(self, session: DbSession, held: Record) -> None:
        source = TURN.source
        rows = session.execute(
            select(
                source.c.turn_id,
                source.c.session_id,
                source.c.turn_seq,
                source.c.transcript_id,
                source.c.at,
                source.c.failed,
                source.c.reported_cost,
                source.c.seconds,
            ).order_by(source.c.at)
        ).all()

        assert [tuple(row) for row in rows] == [
            (
                held.work_turn.id,
                held.work.id,
                1,
                held.thread.id,
                held.work_turn.started_at,
                False,
                Decimal("2.50"),
                600.0,
            ),
            (
                held.chat_turn.id,
                held.chat.id,
                1,
                None,
                held.chat_turn.started_at,
                True,
                Decimal("0.75"),
                180.0,
            ),
        ]


class TestEvent:
    def test_the_occurrences_are_the_kinds_other_entities_record(self) -> None:
        assert tuple(kind.code for kind in OCCURRENCES) == RECORDED_ELSEWHERE

    def test_one_row_is_an_event_or_an_occurrence_another_entity_records(
        self, session: DbSession, held: Record
    ) -> None:
        source = EVENT.source
        rows = session.execute(
            select(
                source.c.kind_code, source.c.call_id, source.c.is_error, source.c.at
            ).order_by(source.c.kind_code)
        ).all()
        first, second, third = held.calls[:3]

        assert [tuple(row) for row in rows] == [
            ("api_error", first.id, True, STARTED + timedelta(seconds=90)),
            ("cache_miss", third.id, False, third.completed_at),
            ("compaction", third.id, False, STARTED + timedelta(minutes=8)),
            ("denied", second.id, False, second.completed_at),
            # A failed hook is held on the last Call of its Prompt's run.
            ("hook_error", third.id, True, third.completed_at),
            ("max_tokens", second.id, True, second.completed_at),
            ("model_fallback", second.id, True, second.completed_at),
            ("output_saved", first.id, False, STARTED + timedelta(minutes=2)),
            ("past_ttl", second.id, False, second.completed_at),
            ("rewind", second.id, False, second.completed_at),
        ]

    def test_a_stored_event_has_its_id_and_an_occurrence_none(
        self, session: DbSession, held: Record
    ) -> None:
        source = EVENT.source

        stored = session.scalars(
            select(source.c.kind_code).where(source.c.event_id.is_not(None))
        ).all()

        assert stored == ["api_error"]

    def test_a_refusal_is_an_occurrence(self, session: DbSession, held: Record) -> None:
        transcripts.reference(session, models.StopReason, "refusal")
        held.calls[0].stop_reason_code = "refusal"
        session.flush()
        source = EVENT.source

        refused = session.execute(
            select(source.c.call_id, source.c.is_error).where(
                source.c.kind_code == "refusal"
            )
        ).all()

        assert [tuple(row) for row in refused] == [(held.calls[0].id, True)]

    def test_an_event_carries_its_calls_facts(
        self, session: DbSession, held: Record
    ) -> None:
        source = EVENT.source

        error = session.execute(
            select(
                source.c.transcript_id,
                source.c.session_id,
                source.c.turn_seq,
                source.c.model_code,
                source.c.effort,
            ).where(source.c.kind_code == "api_error")
        ).one()

        assert tuple(error) == (
            held.thread.id,
            held.work.id,
            1,
            transcripts.OPUS,
            "high",
        )

    def test_each_carries_the_id_of_the_row_that_records_it(
        self, session: DbSession, held: Record
    ) -> None:
        source = EVENT.source
        first, second, third = held.calls[:3]
        tool_calls = {
            row.call_id: row.id for row in session.scalars(select(models.ToolCall))
        }
        event = session.scalar(select(models.Event.id))
        hook = session.scalar(select(models.HookRun.id))

        found = dict(
            session.execute(select(source.c.kind_code, source.c.source_id)).all()
        )

        assert found == {
            "api_error": event,
            "cache_miss": third.id,
            "compaction": third.id,
            "denied": tool_calls[second.id],
            "hook_error": hook,
            "max_tokens": second.id,
            "model_fallback": second.id,
            "output_saved": tool_calls[first.id],
            "past_ttl": second.id,
            "rewind": second.id,
        }

    def test_each_carries_its_detail_from_the_fact_behind_it(
        self, session: DbSession, held: Record
    ) -> None:
        source = EVENT.source
        details = [source.c[column] for column, _ in DETAIL]

        found = {
            row[0]: tuple(row[1:])
            for row in session.execute(select(source.c.kind_code, *details))
        }

        assert found == {
            "api_error": ("529", None, None, None, None, None, None),
            "cache_miss": (None,) * 7,
            "compaction": (None, None, None, None, None, "auto", None),
            "denied": (None, "Bash", None, "rule", None, None, None),
            "hook_error": (None, None, None, None, "signal_activity.sh", None, None),
            "max_tokens": (None,) * 7,
            "model_fallback": (None, None, None, None, None, None, transcripts.OPUS),
            "output_saved": (None, "Bash", 90_000, None, None, None, None),
            "past_ttl": (None,) * 7,
            "rewind": (None,) * 7,
        }

    def test_an_events_key_reads_back(self) -> None:
        assert read_event_key(event_key("cache_miss", 42)) == ("cache_miss", 42)
        assert [
            read_event_key(written)
            for written in ("cache_miss", "cache_miss:0", "Cache:1", "a:1:2", "a:x")
        ] == [None] * 5

    def test_a_hook_that_did_not_fail_is_no_event(
        self, session: DbSession, held: Record
    ) -> None:
        session.execute(models.HookRun.__table__.update().values(failed=False))
        source = EVENT.source

        hooks = session.scalar(
            select(func.count()).where(source.c.kind_code == "hook_error")
        )

        assert hooks == 0


class TestSources:
    def test_every_fact_carries_the_columns_the_joins_start_from(self) -> None:
        for fact in FACTS:
            if fact is WORK_UNIT:
                continue
            assert {"transcript_id", "session_id", "turn_seq", "at"} <= set(
                fact.source.c.keys()
            ), fact.key

    def test_a_work_unit_lies_in_no_thread_and_no_session(self) -> None:
        assert set(WORK_UNIT.source.c.keys()) == {"work_unit_id", "at"}


_REACHED = {"call": 13, "turn": 13, "event": 13, "work_unit": 5}
"""The fewest joins each fact's rows start: a Work Unit's reach only its
units, its measures and its quota week."""


class TestJoins:
    def test_no_join_loses_or_doubles_a_row(
        self, session: DbSession, held: Record
    ) -> None:
        labelled(session, held)
        index = catalogue(session)
        for fact in index.facts:
            alone = session.scalar(select(func.count()).select_from(fact.source))
            row = index.row(fact)
            for join in index.joins:
                if _starts(index, fact.key, join.key):
                    row.to(join.key)
            joined = session.scalar(select(func.count()).select_from(row.source()))

            assert joined == alone, fact.key
            assert len(row.taken) >= _REACHED[fact.key], fact.key

    def test_a_row_reaches_pilots_record(
        self, session: DbSession, held: Record
    ) -> None:
        index = catalogue(session)

        rows = read(
            session,
            index,
            "call",
            lambda row: row.to("session").c.kind_code,
            lambda row: row.to("turn").c.id,
            lambda row: row.to("author").c.handle,
            lambda row: row.to("work").c.id,
            lambda row: row.to("chat").c.id,
            lambda row: row.to("project").c.id,
            by=lambda row: row["at"],
        )

        assert rows[0] == ("work", held.work_turn.id, None, None, None, held.project.id)
        assert rows[4] == (
            "chat",
            held.chat_turn.id,
            "ada",
            None,
            held.chat.id,
            held.project.id,
        )
        assert rows[5] == (None, None, None, None, None, None)

    def test_a_row_reaches_its_thread_and_the_main_thread(
        self, session: DbSession, held: Record
    ) -> None:
        rows = read(
            session,
            catalogue(session),
            "call",
            lambda row: row.to("thread").c.id,
            lambda row: row.to("main").c.id,
            lambda row: row.to("repository").c.name,
            lambda row: row.to("environment").c.id,
            by=lambda row: row["at"],
        )

        environment = held.work.environment_id
        assert rows[0] == (held.thread.id, held.thread.id, "RecipeBox", environment)
        # A sub-agent's thread works in no repository of its own here, and
        # runs where its main thread does.
        assert rows[2] == (held.sub_agent.id, held.thread.id, None, environment)
        assert rows[4] == (None, None, None, None)

    def test_an_adopted_threads_project_is_the_one_that_adopted_it(
        self, session: DbSession, held: Record, person: User
    ) -> None:
        adopted = Project(created_by_user_id=person.id, name="Before Pilot")
        session.add(adopted)
        session.flush()
        held.loose.adopted_project_id = adopted.id
        session.flush()

        projects = read(
            session,
            catalogue(session),
            "call",
            lambda row: row.to("project").c.name,
            by=lambda row: row["at"],
        )

        assert projects[-1] == ("Before Pilot",)

    def test_a_row_falls_in_the_quota_week_that_holds_its_moment(
        self, session: DbSession, held: Record
    ) -> None:
        weeks = read(
            session,
            catalogue(session),
            "call",
            lambda row: row.to("quota_week").c.id,
            by=lambda row: row["at"],
        )
        holding = session.scalar(
            select(QuotaWeek.id).where(
                QuotaWeek.starts_at <= STARTED, STARTED < QuotaWeek.ends_at
            )
        )

        assert holding is not None
        assert weeks[0] == (holding,)

    def test_a_row_before_the_first_quota_week_keeps_its_row(
        self, session: DbSession, held: Record
    ) -> None:
        held.calls[4].completed_at = STARTED.replace(year=2024)
        session.flush()

        weeks = read(
            session,
            catalogue(session),
            "call",
            lambda row: row.to("quota_week").c.id,
            by=lambda row: row["at"],
        )

        assert weeks[0] == (None,)
        assert len(weeks) == 6

    def test_a_row_reaches_the_compaction_it_follows(
        self, session: DbSession, held: Record
    ) -> None:
        triggers = read(
            session,
            catalogue(session),
            "call",
            lambda row: row.to("compaction").c.trigger_code,
            by=lambda row: row["at"],
        )

        assert [trigger for (trigger,) in triggers] == [
            None,
            None,
            None,
            "auto",
            None,
            None,
        ]

    def test_a_turn_reaches_no_compaction(self, session: DbSession) -> None:
        index = catalogue(session)

        assert not _starts(index, "turn", "compaction")
        assert _starts(index, "event", "compaction")


class TestSitting:
    def _loose(
        self, session: DbSession, conversation: str, first: timedelta, last: timedelta
    ) -> models.Transcript:
        read_under = session.scalars(select(models.ComponentVersion)).first()
        assert read_under is not None
        return transcripts.transcript(
            session,
            read_under,
            session_id=conversation,
            first_call_at=STARTED + first,
            last_call_at=STARTED + last,
        )

    def _sittings(
        self, session: DbSession, gap: timedelta = GAP
    ) -> dict[object, object]:
        sitting = {join.key: join for join in own_joins(gap)}["sitting"].table
        return dict(session.execute(select(sitting.c.id, sitting.c.started_at)).all())

    def test_only_a_main_thread_on_no_project_has_a_sitting(
        self, session: DbSession, held: Record
    ) -> None:
        assert self._sittings(session) == {held.loose.id: held.loose.first_call_at}

    def test_threads_within_the_gap_are_one_sitting_by_its_first_call(
        self, session: DbSession, held: Record
    ) -> None:
        day = timedelta(days=1)
        near = self._loose(
            session, "near", day + timedelta(hours=3), day + timedelta(hours=5)
        )
        # Within the gap of the sitting's latest last Call, not of the
        # thread before it by its first.
        short = self._loose(
            session, "short", day + timedelta(hours=4), day + timedelta(hours=4)
        )
        chained = self._loose(
            session, "chained", day + timedelta(hours=8), day + timedelta(hours=8)
        )
        apart = self._loose(
            session, "apart", day + timedelta(hours=12), day + timedelta(hours=13)
        )

        sittings = self._sittings(session)

        opened = held.loose.first_call_at
        assert sittings == {
            held.loose.id: opened,
            near.id: opened,
            short.id: opened,
            chained.id: opened,
            apart.id: apart.first_call_at,
        }

    def test_a_gap_of_the_settings_length_ends_a_sitting(
        self, session: DbSession, held: Record
    ) -> None:
        later = self._loose(
            session,
            "later",
            timedelta(days=1, hours=1),
            timedelta(days=1, hours=1),
        )

        assert (
            self._sittings(session, timedelta(hours=1))[later.id] == later.first_call_at
        )
        assert (
            self._sittings(session, timedelta(hours=1, seconds=1))[later.id]
            == held.loose.first_call_at
        )

    def test_a_thread_a_session_ran_or_a_project_adopted_has_none(
        self, session: DbSession, held: Record, person: User
    ) -> None:
        adopted = Project(created_by_user_id=person.id)
        session.add(adopted)
        session.flush()
        held.loose.adopted_project_id = adopted.id
        session.flush()

        assert self._sittings(session) == {}

    def test_a_thread_with_no_call_has_none(
        self, session: DbSession, held: Record
    ) -> None:
        read_under = session.scalars(select(models.ComponentVersion)).first()
        assert read_under is not None
        transcripts.transcript(session, read_under, session_id="empty")

        assert set(self._sittings(session)) == {held.loose.id}

    def test_a_row_reaches_its_main_threads_sitting(
        self, session: DbSession, held: Record
    ) -> None:
        started = read(
            session,
            catalogue(session),
            "call",
            lambda row: row.to("sitting").c.started_at,
            by=lambda row: row["at"],
        )

        assert [at for (at,) in started] == [None] * 5 + [held.loose.first_call_at]
        assert held.loose.session_id == OTHER


def _starts(index: object, fact: str, join: str) -> bool:
    from app.dashboard.catalogue import Catalogue, Unreachable

    assert isinstance(index, Catalogue)
    try:
        index.row(index.fact(fact)).to(join)
    except Unreachable:
        return False
    return True


class TestWorkUnit:
    def test_one_row_is_a_work_unit_at_the_start_of_its_work(
        self, session: DbSession, held: Record
    ) -> None:
        units = labelled(session, held)

        rows = read(
            session,
            catalogue(session),
            "work_unit",
            lambda row: row["work_unit_id"],
            lambda row: row["at"],
        )

        assert rows == [(units.menu.id, STARTED), (units.course.id, STARTED)]

    def test_a_measures_join_reaches_its_units_figure_of_it(
        self, session: DbSession, held: Record
    ) -> None:
        units = labelled(session, held)

        rows = read(
            session,
            catalogue(session),
            "work_unit",
            lambda row: row["work_unit_id"],
            lambda row: row.to(measure_join("planned_dishes")).c.amount,
        )

        assert rows == [(units.menu.id, Decimal(3)), (units.course.id, None)]

    def test_a_unit_steps_up_to_the_one_it_sits_in(
        self, session: DbSession, held: Record
    ) -> None:
        units = labelled(session, held)

        rows = read(
            session,
            catalogue(session),
            "work_unit",
            lambda row: row.to(unit_join(0)).c.title,
            lambda row: row.to(unit_join(1)).c.title,
            lambda row: row.to(unit_join(2)).c.title,
            by=lambda row: row["work_unit_id"],
        )

        assert units.menu.title == "Dinner"
        assert rows == [("Dinner", None, None), ("Soup", "Dinner", None)]


class TestTheCallsLabels:
    def test_a_call_carries_its_launchs_unit_and_its_labels_a_stand_in_none(
        self, session: DbSession, held: Record
    ) -> None:
        units = labelled(session, held)

        rows = read(
            session,
            catalogue(session),
            "call",
            *(
                (lambda row, name=name: row[name])
                for name in (
                    "work_unit_id",
                    "segment_position",
                    "call_class_code",
                    "wait_cause_code",
                    "avoidable_kind_code",
                    "estimate",
                )
            ),
            by=lambda row: row["at"],
        )

        course = units.course.id
        assert rows == [
            (course, 1, "chop", "oven", None, False),
            (course, 1, "spill", None, "spilt", False),
            (course, None, None, None, None, False),
            (course, None, None, None, None, False),
            (None, None, None, None, None, True),
            (None, None, None, None, None, False),
        ]

    def test_an_event_carries_its_calls(self, session: DbSession, held: Record) -> None:
        labelled(session, held)

        rows = read(
            session,
            catalogue(session),
            "event",
            lambda row: row["kind_code"],
            lambda row: row["call_class_code"],
            lambda row: row.to("segment").c.kind_code,
        )

        assert ("api_error", "chop", "prep") in rows
