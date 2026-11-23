"""The timing's history (`tools/timing/history.py`, F154.9): a day drawn the
same from its seed every time, in the scenario's words, and written as a
collector's publication and Pilot's own record write it."""

from dataclasses import fields, is_dataclass
from datetime import date, timedelta
from typing import Any

from pilot_scenario import Builder
from pilot_scenario.script import Call, Session
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.models import Launch, TokenCount, Transcript, Turn
from app.models import Session as AgentSession
from app.models.call import Call as CallRow
from app.services.container import ServiceContainer
from tools.timing.history import (
    LONG_CALLS,
    PLACES,
    Day,
    _tokens,
    _Writer,
    days,
    draw,
    target,
)

TUESDAY = date(2026, 11, 17)

WORKFLOW = {"slice", "stage", "phase"}


def _words(part: Any) -> set[str]:
    if isinstance(part, str):
        return {
            word.lower() for word in part.replace("/", " ").replace("-", " ").split()
        }
    if isinstance(part, tuple | list):
        return {word for one in part for word in _words(one)}
    if is_dataclass(part) and not isinstance(part, type):
        return {
            word for one in fields(part) for word in _words(getattr(part, one.name))
        }
    return set()


def _calls(session: Session) -> int:
    threads = [
        *(prompt.steps for launch in session.launches for prompt in launch.prompts),
        *(agent.steps for agent in session.sub_agents),
    ]
    return sum(isinstance(step, Call) for steps in threads for step in steps)


def _session(day: Day, name: str) -> Session:
    return next(session for session in day.scenario.sessions if session.name == name)


def _conversation(day: Day, name: str) -> str:
    return Builder(day.scenario, day.start).conversation(_session(day, name))


class TestTheDays:
    def test_a_day_is_drawn_the_same_every_time(self) -> None:
        assert draw(TUESDAY, 600) == draw(TUESDAY, 600)
        assert draw(TUESDAY, 600) != draw(TUESDAY + timedelta(days=7), 600)

    def test_a_day_holds_its_target_in_its_conversations_calls(self) -> None:
        day = draw(TUESDAY)

        assert day.calls >= target(TUESDAY)
        assert day.calls == sum(_calls(session) for session in day.scenario.sessions)

    def test_a_weekend_day_holds_fewer_than_a_weekday(self) -> None:
        saturday = TUESDAY + timedelta(days=4)

        for week in range(8):
            later = timedelta(days=7 * week)
            assert target(saturday + later) < target(TUESDAY + later)

    def test_a_wednesday_opens_on_the_long_conversation_by_hand(self) -> None:
        day = draw(TUESDAY + timedelta(days=1), 600)
        first = day.scenario.sessions[0]

        assert first.person is not None
        assert first.name not in day.pilots
        assert (
            _calls(first)
            - sum(
                isinstance(step, Call)
                for agent in first.sub_agents
                for step in agent.steps
            )
            == LONG_CALLS
        )

    def test_the_days_run_back_from_the_last_until_their_targets_reach_the_calls(
        self,
    ) -> None:
        held = days(50_000, TUESDAY)

        assert held == [TUESDAY - timedelta(days=n) for n in range(len(held))]
        assert sum(map(target, held)) >= 50_000 > sum(map(target, held[:-1]))

    def test_a_day_has_no_word_of_the_workflow(self) -> None:
        day = draw(TUESDAY, 3_000)

        assert _words(day.scenario) & WORKFLOW == set()
        assert _words(list(day.pilots.values())) & WORKFLOW == set()
        assert _words(list(PLACES)) & WORKFLOW == set()


class TestTheWrite:
    def test_a_day_is_written_as_a_collector_and_pilot_write_it(
        self, session: DbSession, container: ServiceContainer
    ) -> None:
        day = draw(TUESDAY, 400)
        assert day.pilots
        name = next(iter(day.pilots))
        standing = day.pilots[name]
        standing.standing_in = True
        standing.tokens = _tokens(_session(day, name))
        writer = _Writer(container, session)

        assert not writer.written(day)
        writer.write(day)

        assert writer.written(day)
        calls = session.scalars(select(CallRow)).all()
        assert len(calls) == day.calls - _calls(_session(day, name))
        assert all(
            call.cost is not None and call.launch_id is not None for call in calls
        )
        pilots = session.scalars(select(AgentSession)).all()
        assert sorted(s.conversation_id for s in pilots if s.conversation_id) == sorted(
            _conversation(day, n) for n in day.pilots
        )
        placed = session.scalar(
            select(func.count())
            .select_from(Launch)
            .join(Transcript, Transcript.id == Launch.transcript_id)
            .join(AgentSession, AgentSession.conversation_id == Transcript.session_id)
            .where(Transcript.agent_id.is_(None), Launch.session_id.is_(None))
        )
        assert placed == 0
        stood_in = next(
            s for s in pilots if s.conversation_id == _conversation(day, name)
        )
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
