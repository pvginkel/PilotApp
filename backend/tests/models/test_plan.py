"""Plan Task and Plan Note: what a row must hold."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import PlanNote, PlanTask, Project, User
from app.models.reference import TaskStatus
from tests.support.database import violated_constraint


def _task(project: Project, task_id: str = "fix", **overrides: object) -> PlanTask:
    values: dict[str, object] = {
        "project_id": project.id,
        "task_id": task_id,
        "position": 1,
        "title": "Fix the client",
        "status_code": TaskStatus.IN_PROGRESS,
    }
    values.update(overrides)
    return PlanTask(**values)


def _note(project: Project, **overrides: object) -> PlanNote:
    values: dict[str, object] = {
        "project_id": project.id,
        "note_id": "n1",
        "summary": "Sweep before the finish",
        "content": "The fallback and its key.",
    }
    values.update(overrides)
    return PlanNote(**values)


class TestPlanTask:
    def test_a_task_is_written(self, session: Session, project: Project) -> None:
        task = _task(project)
        session.add(task)
        session.flush()
        session.refresh(task)

        assert task.updated_at is not None

    def test_a_removed_task_has_no_position(
        self, session: Session, project: Project
    ) -> None:
        session.add(_task(project, removed_at=datetime.now(UTC)))

        assert violated_constraint(session) == "ck_plan_tasks_position"

    def test_a_task_in_the_plan_has_a_position(
        self, session: Session, project: Project
    ) -> None:
        session.add(_task(project, position=None))

        assert violated_constraint(session) == "ck_plan_tasks_position"

    def test_a_removed_task_keeps_its_row(
        self, session: Session, project: Project
    ) -> None:
        task = _task(project)
        session.add(task)
        session.flush()
        task.position = None
        task.removed_at = datetime.now(UTC)
        session.flush()

        assert task.status_code == TaskStatus.IN_PROGRESS


class TestPlanNote:
    def test_a_global_note_is_on_no_task(
        self, session: Session, project: Project
    ) -> None:
        note = _note(project)
        session.add(note)
        session.flush()
        session.refresh(note)

        assert note.plan_task_id is None
        assert note.created_at is not None

    def test_a_note_is_on_a_task_of_its_own_project(
        self, session: Session, project: Project, person: User
    ) -> None:
        other = Project(created_by_user_id=person.id)
        session.add(other)
        session.flush()
        session.add(_task(other))
        session.flush()
        session.add(_note(project, plan_task_id="fix"))

        assert violated_constraint(session) == "plan_notes_project_id_plan_task_id_fkey"

    def test_a_note_id_is_unique_among_the_open_notes(
        self, session: Session, project: Project
    ) -> None:
        session.add_all([_note(project), _note(project)])

        assert violated_constraint(session) == "uq_plan_notes_open_note_id"

    def test_a_struck_note_id_is_saved_again_as_a_new_note(
        self, session: Session, project: Project
    ) -> None:
        struck = _note(project, deleted_at=datetime.now(UTC))
        again = _note(project)
        session.add_all([struck, again])
        session.flush()

        assert struck.id != again.id
