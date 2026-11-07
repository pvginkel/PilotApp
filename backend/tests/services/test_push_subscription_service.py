"""A browser's subscription, written and deleted by its person (F146; DB 302,
311)."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import PushSubscription, User
from app.models.reference import UserKind
from app.services.push_subscription_service import PushSubscriptionService

PHONE = "https://push.example.com/send/phone-of-ada"
DESKTOP = "https://push.example.org/wpush/desktop-of-ada"


def _bea(session: Session) -> User:
    bea = User(
        kind_code=UserKind.PERSON,
        subject="subject-bea",
        handle="bea",
        name="Bea Example",
        avatar_slot=2,
    )
    session.add(bea)
    session.flush()
    return bea


def _rows(session: Session) -> list[tuple[str, uuid.UUID, str, str]]:
    session.expire_all()
    return [
        (row.endpoint, row.user_id, row.p256dh, row.auth)
        for row in session.scalars(
            select(PushSubscription).order_by(PushSubscription.endpoint)
        )
    ]


class TestPushSubscriptionService:
    def test_a_subscription_is_written_for_the_person(
        self, session: Session, person: User
    ) -> None:
        service = PushSubscriptionService(session)

        service.subscribe(person, PHONE, "p256dh-1", "auth-1")
        service.subscribe(person, DESKTOP, "p256dh-2", "auth-2")

        assert _rows(session) == [
            (PHONE, person.id, "p256dh-1", "auth-1"),
            (DESKTOP, person.id, "p256dh-2", "auth-2"),
        ]
        row = session.scalars(
            select(PushSubscription).where(PushSubscription.endpoint == PHONE)
        ).one()
        assert row.created_at is not None

    def test_the_same_endpoint_again_is_one_row_with_the_keys_given_last(
        self, session: Session, person: User
    ) -> None:
        service = PushSubscriptionService(session)

        service.subscribe(person, PHONE, "p256dh-1", "auth-1")
        service.subscribe(person, PHONE, "p256dh-2", "auth-2")

        assert _rows(session) == [(PHONE, person.id, "p256dh-2", "auth-2")]

    def test_an_endpoint_another_person_held_becomes_theirs(
        self, session: Session, person: User
    ) -> None:
        bea = _bea(session)
        service = PushSubscriptionService(session)
        service.subscribe(person, PHONE, "p256dh-1", "auth-1")

        service.subscribe(bea, PHONE, "p256dh-2", "auth-2")

        assert _rows(session) == [(PHONE, bea.id, "p256dh-2", "auth-2")]

    def test_unsubscribe_deletes_the_persons_subscription_of_the_endpoint(
        self, session: Session, person: User
    ) -> None:
        service = PushSubscriptionService(session)
        service.subscribe(person, PHONE, "p256dh-1", "auth-1")
        service.subscribe(person, DESKTOP, "p256dh-2", "auth-2")

        service.unsubscribe(person, PHONE)

        assert _rows(session) == [(DESKTOP, person.id, "p256dh-2", "auth-2")]

    def test_another_persons_subscription_of_the_endpoint_stays(
        self, session: Session, person: User
    ) -> None:
        bea = _bea(session)
        service = PushSubscriptionService(session)
        service.subscribe(bea, PHONE, "p256dh-1", "auth-1")

        service.unsubscribe(person, PHONE)

        assert _rows(session) == [(PHONE, bea.id, "p256dh-1", "auth-1")]

    def test_an_endpoint_nobody_holds_is_nothing_to_delete(
        self, session: Session, person: User
    ) -> None:
        PushSubscriptionService(session).unsubscribe(person, PHONE)

        assert _rows(session) == []

    def test_a_subscription_is_a_users(self, session: Session) -> None:
        session.add(
            PushSubscription(user_id=uuid.uuid4(), endpoint=PHONE, p256dh="p", auth="a")
        )

        with pytest.raises(IntegrityError, match="push_subscriptions_user_id_fkey"):
            session.flush()
