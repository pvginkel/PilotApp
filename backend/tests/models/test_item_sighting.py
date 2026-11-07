"""Item Sighting: what a row must hold (DB 307 to 310)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Item, ItemSighting, Project, ProjectMember, User
from tests.support.database import violated_constraint


def _member(session: Session, project: Project, person: User) -> ProjectMember:
    member = ProjectMember(
        project_id=project.id, user_id=person.id, joined_at=datetime.now(UTC)
    )
    session.add(member)
    session.flush()
    return member


class TestItemSighting:
    def test_a_member_is_shown_an_item(
        self, session: Session, project: Project, person: User, item: Item
    ) -> None:
        member = _member(session, project, person)
        session.add(ItemSighting(member_id=member.id, item_id=item.id))
        session.flush()

        assert session.execute(
            select(ItemSighting.member_id, ItemSighting.item_id)
        ).all() == [(member.id, item.id)]

    def test_a_member_is_shown_an_item_once(
        self, session: Session, project: Project, person: User, item: Item
    ) -> None:
        member = _member(session, project, person)
        session.add(ItemSighting(member_id=member.id, item_id=item.id))
        session.flush()
        session.expunge_all()
        session.add(ItemSighting(member_id=member.id, item_id=item.id))

        assert violated_constraint(session) == "item_sightings_pkey"

    def test_its_member_is_a_membership_that_is(
        self, session: Session, item: Item
    ) -> None:
        session.add(ItemSighting(member_id=999_999, item_id=item.id))

        assert violated_constraint(session) == "item_sightings_member_id_fkey"

    def test_its_item_is_one_that_is(
        self, session: Session, project: Project, person: User
    ) -> None:
        member = _member(session, project, person)
        session.add(ItemSighting(member_id=member.id, item_id=uuid.uuid4()))

        assert violated_constraint(session) == "item_sightings_item_id_fkey"
