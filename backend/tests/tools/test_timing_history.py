"""The timing's history (`tools/timing/history.py`, F154.9): the package's
days (`pilot_scenario.history`) at the fleet's size, a Wednesday opening on
the long conversation, written as a collector's publication and Pilot's own
record write it."""

from dataclasses import replace
from datetime import date, timedelta

from pilot_scenario.history import WEEKEND, billed
from pilot_scenario.script import Call, Session
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.models import Launch, TokenCount, Transcript, Turn
from app.models import Session as AgentSession
from app.models.call import Call as CallRow
from app.services.container import ServiceContainer
from tests.support.workflow_words import workflow_words
from tools.timing.history import HISTORY, LONG_CALLS, _Writer, in_lock_order

TUESDAY = date(2026, 11, 17)


def _calls(session: Session) -> int:
    threads = [
        *(prompt.steps for launch in session.launches for prompt in launch.prompts),
        *(agent.steps for agent in session.sub_agents),
    ]
    return sum(isinstance(step, Call) for steps in threads for step in steps)


def _session(day_sessions: tuple[Session, ...], name: str) -> Session:
    return next(session for session in day_sessions if session.name == name)


class TestTheDays:
    def test_a_weekday_holds_its_share_of_the_fleets_nine_thousand(self) -> None:
        share = 9_000 * (7 - 2 * WEEKEND) / 5

        assert 0.75 <= HISTORY.target(TUESDAY) / share <= 1.25

    def test_a_wednesday_opens_on_the_long_conversation_by_hand(self) -> None:
        day = HISTORY.draw(TUESDAY + timedelta(days=1), 600)
        first = day.scenario.sessions[0]

        assert first.person is not None
        assert first.ran is None
        assert (
            _calls(first)
            - sum(
                isinstance(step, Call)
                for agent in first.sub_agents
                for step in agent.steps
            )
            == LONG_CALLS
        )

    def test_its_places_and_a_day_have_no_word_of_the_workflow(self) -> None:
        assert workflow_words(HISTORY) == set()
        assert workflow_words(HISTORY.draw(TUESDAY, 3_000).scenario) == set()


class TestTheLockOrder:
    def test_the_conversations_that_name_a_group_go_last_by_its_key(self) -> None:
        recipes = {"key": "recipe-box-first-batches"}
        rides = {"key": "bike-log-first-rides"}
        published = [
            {"session_id": "a", "group": recipes},
            {"session_id": "a", "agent_id": "a0"},
            {"session_id": "b"},
            {"session_id": "c", "group": rides},
            {"session_id": "d"},
            {"session_id": "d", "agent_id": "d0"},
        ]

        assert in_lock_order(published) == [
            published[2],
            published[4],
            published[5],
            published[3],
            published[0],
            published[1],
        ]


class TestTheWrite:
    def test_a_day_whose_first_conversation_stands_in_is_written_once(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        day = HISTORY.draw(date(2026, 10, 27), 400)
        first = day.scenario.sessions[0]
        assert first.ran is not None
        day = replace(day, standing={first.name: billed(first)})
        writer = _Writer(container, session)

        writer.write(day)

        assert writer.written(day)

    def test_a_day_is_written_as_a_collector_and_pilot_write_it(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        day = HISTORY.draw(TUESDAY, 400)
        pilots = [s.name for s in day.scenario.sessions if s.ran is not None]
        assert pilots
        name = pilots[0]
        day = replace(
            day, standing={name: billed(_session(day.scenario.sessions, name))}
        )
        writer = _Writer(container, session)

        assert not writer.written(day)
        writer.write(day)

        assert writer.written(day)
        builder = day.builder()
        calls = session.scalars(select(CallRow)).all()
        assert len(calls) == day.calls - _calls(_session(day.scenario.sessions, name))
        assert all(
            call.cost is not None and call.launch_id is not None for call in calls
        )
        rows = session.scalars(select(AgentSession)).all()
        assert sorted(s.conversation_id for s in rows if s.conversation_id) == sorted(
            builder.conversation(_session(day.scenario.sessions, n)) for n in pilots
        )
        placed = session.scalar(
            select(func.count())
            .select_from(Launch)
            .join(Transcript, Transcript.id == Launch.transcript_id)
            .join(AgentSession, AgentSession.conversation_id == Transcript.session_id)
            .where(Transcript.agent_id.is_(None), Launch.session_id.is_(None))
        )
        assert placed == 0
        conversation = builder.conversation(_session(day.scenario.sessions, name))
        stood_in = next(s for s in rows if s.conversation_id == conversation)
        assert (
            session.scalar(
                select(func.count())
                .select_from(Transcript)
                .where(Transcript.session_id == stood_in.conversation_id)
            )
            == 0
        )
        turns = session.scalars(
            select(Turn).where(Turn.session_id == stood_in.id)
        ).all()
        assert turns and all(turn.cost is not None and turn.cost > 0 for turn in turns)
        assert session.scalar(
            select(func.count())
            .select_from(TokenCount)
            .where(TokenCount.turn_id.in_([turn.id for turn in turns]))
        ) == 4 * len(turns)
        reported = session.scalars(
            select(Turn.cost).join(AgentSession).where(AgentSession.id != stood_in.id)
        ).all()
        assert all(cost is not None for cost in reported)
