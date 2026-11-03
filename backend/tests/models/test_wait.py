"""Wait, Wait Firing and Card Transition: what a row must hold (DB decision 46,
assertions 184 to 198)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session as DbSession

from app.models import CardTransition, Item, Project, Session, User, Wait, WaitFiring
from app.models.reference import FiringCause
from tests.support.database import violated_constraint

_DUE = datetime(2026, 10, 25, 18, 30, tzinfo=UTC)


def _wait_item(
    session: DbSession, project: Project, creator: Session, kind: str, seq: int = 1
) -> Item:
    item = Item(
        project_id=project.id,
        seq=seq,
        kind_code=kind,
        title="Slice 058 completes",
        created_by_session_id=creator.id,
    )
    session.add(item)
    session.flush()
    return item


def _card_wait(
    session: DbSession, project: Project, creator: Session, seq: int = 1
) -> Wait:
    item = _wait_item(session, project, creator, "card_wait", seq)
    wait = Wait(id=item.id, kind_code="card_wait", cards=["ANS-312"], states=["Done"])
    session.add(wait)
    session.flush()
    return wait


def _timed_wait(session: DbSession, project: Project, creator: Session) -> Wait:
    item = _wait_item(session, project, creator, "timed_wait")
    wait = Wait(id=item.id, kind_code="timed_wait", due_at=_DUE)
    session.add(wait)
    session.flush()
    return wait


def _transition(session: DbSession) -> CardTransition:
    transition = CardTransition(
        card="ANS-312",
        from_state="In Progress",
        to_state="Done",
        at=_DUE,
        by="pieter",
        received_at=_DUE + timedelta(seconds=1),
    )
    session.add(transition)
    session.flush()
    return transition


def _firing(wait: Wait, seq: int = 1, **values: Any) -> WaitFiring:
    return WaitFiring(
        wait_id=wait.id,
        wait_kind_code=wait.kind_code,
        seq=seq,
        fired_at=_DUE,
        **values,
    )


class TestWait:
    def test_a_card_wait_holds_its_two_lists_and_a_timed_wait_its_due_time(
        self, session: DbSession, project: Project, project_session: Session
    ) -> None:
        card = _card_wait(session, project, project_session)
        timed = Wait(
            id=_wait_item(session, project, project_session, "timed_wait", 2).id,
            kind_code="timed_wait",
            due_at=_DUE,
        )
        session.add(timed)
        session.flush()

        session.expire_all()
        assert (card.cards, card.states, card.due_at) == (["ANS-312"], ["Done"], None)
        assert (timed.cards, timed.states, timed.due_at) == (None, None, _DUE)
        assert card.done_note is None

    def test_its_item_is_of_its_kind(
        self, session: DbSession, project: Project, project_session: Session
    ) -> None:
        item = _wait_item(session, project, project_session, "timed_wait")
        session.add(
            Wait(id=item.id, kind_code="card_wait", cards=["SR-4"], states=["Done"])
        )

        assert violated_constraint(session) == "waits_id_kind_code_fkey"

    def test_an_item_of_another_form_is_no_wait(
        self, session: DbSession, project: Project, item: Item
    ) -> None:
        session.add(Wait(id=item.id, kind_code="decision"))

        assert violated_constraint(session) == "ck_waits_kind"

    @pytest.mark.parametrize(
        ("kind", "values"),
        [
            pytest.param("timed_wait", {}, id="timed-without-due"),
            pytest.param(
                "timed_wait",
                {"due_at": _DUE, "cards": ["SR-4"], "states": ["Done"]},
                id="timed-with-lists",
            ),
            pytest.param("card_wait", {"states": ["Done"]}, id="card-without-cards"),
            pytest.param("card_wait", {"cards": ["SR-4"]}, id="card-without-states"),
            pytest.param(
                "card_wait",
                {"cards": ["SR-4"], "states": ["Done"], "due_at": _DUE},
                id="card-with-due",
            ),
            pytest.param("card_wait", {"cards": [], "states": ["Done"]}, id="no-card"),
            pytest.param("card_wait", {"cards": ["SR-4"], "states": []}, id="no-state"),
        ],
    )
    def test_each_kind_holds_its_own_half_and_one_name_or_more(
        self,
        session: DbSession,
        project: Project,
        project_session: Session,
        kind: str,
        values: dict[str, Any],
    ) -> None:
        item = _wait_item(session, project, project_session, kind)
        session.add(Wait(id=item.id, kind_code=kind, **values))

        assert violated_constraint(session) == "ck_waits_halves"


class TestWaitFiring:
    def test_each_cause_holds_what_fired_it(
        self,
        session: DbSession,
        project: Project,
        project_session: Session,
        person: User,
    ) -> None:
        card = _card_wait(session, project, project_session)
        transition = _transition(session)
        session.add_all(
            [
                _firing(
                    card,
                    cause_code=FiringCause.TRANSITION,
                    transition_id=transition.id,
                ),
                _firing(
                    card,
                    2,
                    cause_code=FiringCause.REQUESTED,
                    requested_by_user_id=person.id,
                ),
            ]
        )

        session.flush()

    @pytest.mark.parametrize(
        ("cause", "transition", "requested"),
        [
            pytest.param(FiringCause.TRANSITION, False, False, id="no-transition"),
            pytest.param(FiringCause.REQUESTED, False, False, id="no-requester"),
            pytest.param(FiringCause.DUE, True, False, id="due-with-transition"),
            pytest.param(FiringCause.TRANSITION, True, True, id="both"),
        ],
    )
    def test_only_a_transitions_names_one_and_only_a_requests_its_person(
        self,
        session: DbSession,
        project: Project,
        project_session: Session,
        person: User,
        cause: FiringCause,
        transition: bool,
        requested: bool,
    ) -> None:
        wait = _card_wait(session, project, project_session)
        session.add(
            _firing(
                wait,
                cause_code=cause,
                transition_id=_transition(session).id if transition else None,
                requested_by_user_id=person.id if requested else None,
            )
        )

        assert violated_constraint(session) == "ck_wait_firings_cause"

    def test_the_due_time_fires_no_card_wait(
        self, session: DbSession, project: Project, project_session: Session
    ) -> None:
        wait = _card_wait(session, project, project_session)
        session.add(_firing(wait, cause_code=FiringCause.DUE))

        assert violated_constraint(session) == "ck_wait_firings_kind"

    def test_a_transition_fires_no_timed_wait(
        self, session: DbSession, project: Project, project_session: Session
    ) -> None:
        wait = _timed_wait(session, project, project_session)
        session.add(
            _firing(
                wait,
                cause_code=FiringCause.TRANSITION,
                transition_id=_transition(session).id,
            )
        )

        assert violated_constraint(session) == "ck_wait_firings_kind"

    def test_its_kind_is_its_waits(
        self,
        session: DbSession,
        project: Project,
        project_session: Session,
        person: User,
    ) -> None:
        wait = _timed_wait(session, project, project_session)
        session.add(
            WaitFiring(
                wait_id=wait.id,
                wait_kind_code="card_wait",
                seq=1,
                cause_code=FiringCause.REQUESTED,
                requested_by_user_id=person.id,
                fired_at=_DUE,
            )
        )

        assert (
            violated_constraint(session) == "wait_firings_wait_id_wait_kind_code_fkey"
        )

    def test_a_timed_wait_fires_due_once(
        self,
        session: DbSession,
        project: Project,
        project_session: Session,
        person: User,
    ) -> None:
        wait = _timed_wait(session, project, project_session)
        session.add_all(
            [
                _firing(wait, cause_code=FiringCause.DUE),
                _firing(
                    wait,
                    2,
                    cause_code=FiringCause.REQUESTED,
                    requested_by_user_id=person.id,
                ),
            ]
        )
        session.flush()
        session.add(_firing(wait, 3, cause_code=FiringCause.DUE))

        assert violated_constraint(session) == "uq_wait_firings_due"

    def test_a_transition_fires_a_wait_once(
        self, session: DbSession, project: Project, project_session: Session
    ) -> None:
        wait = _card_wait(session, project, project_session)
        transition = _transition(session)
        session.add(
            _firing(
                wait, cause_code=FiringCause.TRANSITION, transition_id=transition.id
            )
        )
        session.flush()
        session.add(
            _firing(
                wait,
                2,
                cause_code=FiringCause.TRANSITION,
                transition_id=transition.id,
            )
        )

        assert violated_constraint(session) == "uq_wait_firings_transition_id_wait_id"

    def test_its_seq_counts_from_1(
        self, session: DbSession, project: Project, project_session: Session
    ) -> None:
        wait = _timed_wait(session, project, project_session)
        session.add(_firing(wait, 0, cause_code=FiringCause.DUE))

        assert violated_constraint(session) == "ck_wait_firings_seq"

    def test_the_job_that_takes_it_is_a_work(
        self, session: DbSession, project: Project, project_session: Session
    ) -> None:
        wait = _timed_wait(session, project, project_session)
        session.add(_firing(wait, cause_code=FiringCause.DUE, job_id=uuid.uuid4()))

        assert violated_constraint(session) == "wait_firings_job_id_fkey"
