"""Item: what a row must hold."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session as DbSession

from app.models import Item, PlanTask, Project, Session, User
from app.models.reference import TaskStatus
from tests.support.database import violated_constraint


def _item(project: Project, run: Session, **overrides: object) -> Item:
    values: dict[str, object] = {
        "project_id": project.id,
        "seq": 2,
        "kind_code": "action",
        "title": "Put the key into the vault",
        "created_by_session_id": run.id,
    }
    values.update(overrides)
    return Item(**values)


class TestItem:
    def test_an_item_is_written(self, session: DbSession, item: Item) -> None:
        session.refresh(item)

        assert item.urgent is False
        assert item.plan_task_id is None
        assert item.done_at is None
        assert item.created_at is not None

    def test_an_item_may_have_no_title(
        self, session: DbSession, project: Project, project_session: Session
    ) -> None:
        item = _item(project, project_session, title=None)
        session.add(item)
        session.flush()
        session.refresh(item)

        assert item.title is None

    def test_the_opening_is_a_persons_words(
        self, session: DbSession, project: Project, person: User
    ) -> None:
        opening = Item(
            project_id=project.id,
            seq=1,
            kind_code="opening",
            title="Fix the client",
            created_by_user_id=person.id,
        )
        session.add(opening)
        session.flush()

        assert opening.created_by_session_id is None

    def test_only_the_opening_is_a_persons(
        self, session: DbSession, project: Project, person: User
    ) -> None:
        session.add(
            Item(
                project_id=project.id,
                seq=1,
                kind_code="decision",
                title="Which colour for the badge?",
                created_by_user_id=person.id,
            )
        )

        assert violated_constraint(session) == "ck_items_created_by"

    def test_an_item_has_a_creator(self, session: DbSession, project: Project) -> None:
        session.add(
            Item(project_id=project.id, seq=1, kind_code="notice", title="Deployed")
        )

        assert violated_constraint(session) == "ck_items_created_by"

    def test_an_item_has_one_creator(
        self,
        session: DbSession,
        project: Project,
        project_session: Session,
        person: User,
    ) -> None:
        session.add(
            _item(
                project,
                project_session,
                kind_code="opening",
                created_by_user_id=person.id,
            )
        )

        assert violated_constraint(session) == "ck_items_created_by"

    def test_its_kind_is_an_item_kind(
        self, session: DbSession, project: Project, project_session: Session
    ) -> None:
        session.add(_item(project, project_session, kind_code="ask"))

        assert violated_constraint(session) == "items_kind_code_fkey"

    def test_a_seq_places_one_item(
        self, session: DbSession, item: Item, project: Project, project_session: Session
    ) -> None:
        session.add(_item(project, project_session, seq=item.seq))

        assert violated_constraint(session) == "items_project_id_seq_key"

    def test_another_project_counts_from_1(
        self,
        session: DbSession,
        item: Item,
        person: User,
        project_session: Session,
    ) -> None:
        other = Project(created_by_user_id=person.id)
        session.add(other)
        session.flush()
        first = _item(other, project_session, seq=item.seq)
        session.add(first)
        session.flush()

        assert first.seq == item.seq

    def test_seq_counts_from_1(
        self, session: DbSession, project: Project, project_session: Session
    ) -> None:
        session.add(_item(project, project_session, seq=0))

        assert violated_constraint(session) == "ck_items_seq"

    def test_an_item_serves_a_task_of_its_project(
        self,
        session: DbSession,
        project: Project,
        project_session: Session,
        person: User,
    ) -> None:
        other = Project(created_by_user_id=person.id)
        session.add(other)
        session.flush()
        session.add(
            PlanTask(
                project_id=other.id,
                task_id="fix",
                position=1,
                title="Fix the client",
                status_code=TaskStatus.PENDING,
            )
        )
        session.flush()
        session.add(_item(project, project_session, plan_task_id="fix"))

        assert violated_constraint(session) == "items_project_id_plan_task_id_fkey"

    def test_a_done_item_has_a_cause(self, session: DbSession, item: Item) -> None:
        item.done_at = datetime.now(UTC)

        assert violated_constraint(session) == "ck_items_done"

    def test_an_open_item_is_marked_by_no_one(
        self, session: DbSession, item: Item, person: User
    ) -> None:
        item.done_by_user_id = person.id

        assert violated_constraint(session) == "ck_items_done"

    def test_its_done_cause_is_a_done_cause(
        self, session: DbSession, item: Item
    ) -> None:
        item.done_at = datetime.now(UTC)
        item.done_cause_code = "closed"

        assert violated_constraint(session) == "items_done_cause_code_fkey"

    def test_undo_clears_the_done_state(
        self, session: DbSession, item: Item, person: User
    ) -> None:
        item.done_at = datetime.now(UTC)
        item.done_cause_code = "answered"
        item.done_by_user_id = person.id
        session.flush()
        item.done_at = None
        item.done_cause_code = None
        item.done_by_user_id = None
        session.flush()

        assert item.done_at is None

    def test_a_consumed_item_names_the_session(
        self, session: DbSession, item: Item
    ) -> None:
        item.consumed_at = datetime.now(UTC)

        assert violated_constraint(session) == "ck_items_consumed"
