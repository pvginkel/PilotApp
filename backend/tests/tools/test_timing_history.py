"""The timing's history (`tools/timing/history.py`, F154.9): the package's
days (`pilot_scenario.history`) at the fleet's size, a Wednesday opening on
the long conversation, each work session carrying out a leg of its
project's errand under kinds nested as the labeller's are, written as a
collector's publication and Pilot's own record write it."""

from collections import Counter
from dataclasses import replace
from datetime import date, timedelta

from pilot_scenario import labeller
from pilot_scenario.history import WEEKEND, billed, models
from pilot_scenario.script import Call, Session, Unit
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.dashboard.dimensions import reaches
from app.models import Launch, TokenCount, Transcript, Turn
from app.models import Session as AgentSession
from app.models.call import Call as CallRow
from app.models.label import WorkUnit
from app.services.container import ServiceContainer
from tests.support.workflow_words import workflow_words
from tools.timing.history import (
    CONFIGURED_DAYS,
    HISTORY,
    KINDS,
    LONG_CALLS,
    NESTING,
    PLACES,
    PORTER,
    ROLES,
    _Writer,
    configured,
    draw,
    errand,
    in_lock_order,
)

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
        assert workflow_words(draw(TUESDAY, 3_000).scenario) == set()

    def test_a_day_is_the_packages_but_for_its_units_and_its_legs_models(
        self,
    ) -> None:
        drawn, package = draw(TUESDAY, 3_000), HISTORY.draw(TUESDAY, 3_000)

        assert (drawn.calls, drawn.standing) == (package.calls, package.standing)
        assert [s.name for s in drawn.scenario.sessions] == [
            s.name for s in package.scenario.sessions
        ]
        for mine, theirs in zip(
            drawn.scenario.sessions, package.scenario.sessions, strict=True
        ):
            if mine.unit is None:
                assert mine == theirs
            else:
                assert replace(mine, unit=None, launches=theirs.launches) == theirs


def _up(units: dict[str, Unit], unit: Unit) -> list[str]:
    """The kinds of a unit and of every unit above it, its own first."""
    kinds = [unit.kind]
    while unit.within is not None:
        unit = units[unit.within]
        kinds.append(unit.kind)
    return kinds


def _work(session: Session) -> bool:
    return session.ran is not None and session.ran.kind == "work"


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
        places = {place.slug: place for place in PLACES}

        assert any(_work(session) for session in day.scenario.sessions)
        chains = set()
        for session in day.scenario.sessions:
            if not _work(session):
                assert session.unit is None
                continue
            assert session.ran is not None and session.unit == session.ran.title
            leg = units[session.unit]
            place = places[session.ran.project]
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
            assert {
                step.model
                for launch in session.launches
                for prompt in launch.prompts
                for step in prompt.steps
                if isinstance(step, Call)
            } == {configured(role, TUESDAY)}

    def test_a_roles_configuration_changes_between_its_stretches(self) -> None:
        """Whether a role runs on the day's largest model or its middle one
        is drawn again for each stretch: a new generation of the models
        changes the model without a draw, so the draw is what is compared."""
        for role, _ in ROLES:
            days = [TUESDAY - timedelta(days=CONFIGURED_DAYS * n) for n in range(12)]
            drawn = [configured(role, day) for day in days]

            largest = {
                model == models(day)[0] for model, day in zip(drawn, days, strict=True)
            }
            assert len(largest) > 1
            assert all(
                configured(role, TUESDAY - timedelta(days=n)) in drawn
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
        day = draw(TUESDAY, 400)
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
        legs = {
            unit.title: unit
            for unit in session.scalars(
                select(WorkUnit).where(WorkUnit.kind_code == "leg")
            )
        }
        drawn = {unit.name: unit for unit in day.scenario.units if unit.kind == "leg"}
        collected = {
            s.unit
            for s in day.scenario.sessions
            if s.unit is not None and s.name not in day.standing
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
