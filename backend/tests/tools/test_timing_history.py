"""The timing's history (`tools/timing/history.py`, F154.9): a day drawn the
same from its seed every time, in the scenario's words, and written as a
collector's publication and Pilot's own record write it."""

from collections import Counter
from dataclasses import fields, is_dataclass
from datetime import date, timedelta
from typing import Any

from pilot_scenario import Builder, labeller
from pilot_scenario.script import Call, Session, Unit
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.dashboard.dimensions import reaches
from app.models import Launch, TokenCount, Transcript, Turn
from app.models import Session as AgentSession
from app.models.call import Call as CallRow
from app.models.label import WorkUnit
from app.services.container import ServiceContainer
from tools.timing.history import (
    CONFIGURED_DAYS,
    KINDS,
    LONG_CALLS,
    NESTING,
    PLACES,
    PORTER,
    ROLES,
    Day,
    _tokens,
    _Writer,
    configured,
    days,
    draw,
    errand,
    in_lock_order,
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


def _up(units: dict[str, Unit], unit: Unit) -> list[str]:
    """The kinds of a unit and of every unit above it, its own first."""
    kinds = [unit.kind]
    while unit.within is not None:
        unit = units[unit.within]
        kinds.append(unit.kind)
    return kinds


class TestTheUnits:
    def test_the_kinds_nest_as_the_labellers_with_an_errand_three_steps_up(
        self,
    ) -> None:
        day = draw(TUESDAY)

        assert (day.scenario.kinds, day.scenario.nesting) == (KINDS, NESTING)
        assert reaches(NESTING)["errand"] == 3
        assert len(KINDS) == 6 and len(NESTING) == 7
        assert {kind for pair in NESTING for kind in pair} == set(KINDS)

    def test_each_work_session_carries_out_a_leg_of_its_projects_errand(
        self,
    ) -> None:
        day = draw(TUESDAY)
        units = {unit.name: unit for unit in day.scenario.units}
        work = {name for name, plan in day.pilots.items() if plan.kind == "work"}

        assert work
        chains = set()
        for session in day.scenario.sessions:
            if session.name not in work:
                assert session.unit is None
                continue
            assert session.unit is not None
            leg = units[session.unit]
            place = day.pilots[session.name].place
            chain = _up(units, leg)
            chains.add(tuple(chain))
            assert chain == (
                ["leg", "trip", "errand"]
                if leg.role == PORTER
                else ["leg", "stop", "trip", "errand"]
            )
            top = leg
            while top.within is not None:
                top = units[top.within]
            assert (top.name, top.project) == (errand(place, day.day), place.slug)
            assert leg.role in dict(ROLES)
        assert len(chains) == 2

    def test_every_unit_sits_where_a_nesting_pairs_its_kind(self) -> None:
        units = draw(TUESDAY).scenario.units
        named = {unit.name: unit for unit in units}

        assert all(
            (unit.kind, named[unit.within].kind) in NESTING
            for unit in units
            if unit.within is not None
        )
        assert all(
            named[unit.within] in units[:at]
            for at, unit in enumerate(units)
            if unit.within is not None
        )
        stops = Counter(unit.within for unit in units if unit.kind == "leg")
        assert (
            max(count for name, count in stops.items() if named[name].kind == "stop")
            == 3
        )

    def test_a_legs_round_counts_its_role_in_the_errand_and_a_later_one_may_be_redone(
        self,
    ) -> None:
        seen: Counter[tuple[str | None, str | None]] = Counter()
        redone = 0
        for day in (TUESDAY, TUESDAY + timedelta(days=1)):
            units = draw(day).scenario.units
            named = {unit.name: unit for unit in units}
            for unit in units:
                if unit.kind != "leg":
                    assert (unit.role, unit.round, unit.rework_kind) == (None,) * 3
                    continue
                top = unit
                while top.within is not None:
                    top = named[top.within]
                seen[(top.name, unit.role)] += 1
                assert unit.round == seen[(top.name, unit.role)]
                if unit.rework_kind is not None:
                    assert unit.rework_kind == labeller.RECOOKED
                    assert unit.round > 1
                    redone += 1

        assert redone

    def test_a_roles_legs_run_on_its_configuration(self) -> None:
        day = draw(TUESDAY)
        units = {unit.name: unit for unit in day.scenario.units}

        for session in day.scenario.sessions:
            if session.unit is None:
                continue
            role = units[session.unit].role
            assert role is not None
            first = next(
                step
                for step in session.launches[0].prompts[0].steps
                if isinstance(step, Call)
            )
            assert first.model == configured(role, TUESDAY)

    def test_a_roles_configuration_changes_between_its_stretches(self) -> None:
        for role, _ in ROLES:
            models = [
                configured(role, TUESDAY - timedelta(days=CONFIGURED_DAYS * n))
                for n in range(12)
            ]

            assert len(set(models)) > 1
            assert all(
                configured(role, TUESDAY - timedelta(days=n)) in models
                for n in range(CONFIGURED_DAYS)
            )


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
        day = draw(date(2026, 10, 27), 400)
        first = day.scenario.sessions[0].name
        day.pilots[first].standing_in = True
        day.pilots[first].tokens = _tokens(_session(day, first))
        writer = _Writer(container, session)

        writer.write(day)

        assert writer.written(day)

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
        legs = {
            unit.title: unit
            for unit in session.scalars(
                select(WorkUnit).where(WorkUnit.kind_code == "leg")
            )
        }
        drawn = {unit.name: unit for unit in day.scenario.units if unit.kind == "leg"}
        collected = {
            day.pilots[n].title
            for n in day.pilots
            if day.pilots[n].kind == "work" and not day.pilots[n].standing_in
        }
        assert collected and set(legs) == collected
        assert all(
            (legs[title].role, legs[title].round, legs[title].rework_kind_code)
            == (drawn[title].role, drawn[title].round, drawn[title].rework_kind)
            for title in legs
        )
        written = {unit.id: unit for unit in session.scalars(select(WorkUnit))}
        named = {unit.name: unit for unit in day.scenario.units}
        assert all(
            written[unit.part_of_id].title == named[unit.title].within
            for unit in written.values()
            if unit.part_of_id is not None
        )
        assert {unit.kind_code for unit in written.values()} >= {
            "errand",
            "trip",
            "stop",
            "leg",
        }
