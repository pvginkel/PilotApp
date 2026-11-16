"""An adopted Project's rows, for tests of what reads one: the Project as
the adoption bears it, with its one `adopted` Project Transition and no
draft."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session as DbSession

from app.models import Project, ProjectTransition, User
from app.models.reference import ProjectState, TransitionKind

FIRST_MENUS = "recipe-box-first-menus"
"""The key of an invented group of work done before Pilot."""

ADOPTED_AT = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


def adopted_project(
    db: DbSession, service_user: User, key: str = FIRST_MENUS, **overrides: object
) -> Project:
    """The adopted Project of the group `key`, by `service_user`."""
    values: dict[str, object] = {
        "state_code": ProjectState.ADOPTED,
        "archived": True,
        "adopted_group": key,
        "name": "Recipe box: the first menus",
        "created_by_user_id": service_user.id,
        "created_at": ADOPTED_AT,
    }
    project = Project(**(values | overrides))
    db.add(project)
    db.flush()
    db.add(
        ProjectTransition(
            project_id=project.id,
            kind_code=TransitionKind.ADOPTED,
            at=ADOPTED_AT,
            by_user_id=service_user.id,
        )
    )
    db.flush()
    return project
