"""An adopted Project, and the Transcripts it adopts.

Project State's and Transition Kind's `adopted`: a Project that stands for a
group of slices run before Pilot, born archived by its one `adopted` Project
Transition and never opened (DB decision 79; assertions 170 and 584).
`projects.adopted_group` is the key of its group, an adopted Project's alone
and unique (582), and an adopted Project, never opened, has no slug (177).
`transcripts.adopted_project_id` is the adopted Project of the group a main
thread's labels name (DB §2.6; 539).

Revision ID: 0039
Revises: 0038
Create Date: 2026-11-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROJECT_STATE = ("draft", "open", "finished")
TRANSITION_KIND = (
    "opened",
    "finished",
    "reopened",
    "archived",
    "brought_back",
    "autopilot_on",
    "autopilot_off",
    "paused",
    "resumed",
)

_DRAFT_SLUG = "(state_code = 'draft') = (slug IS NULL)"
_UNOPENED_SLUG = "(state_code IN ('draft', 'adopted')) = (slug IS NULL)"


def upgrade() -> None:
    """Upgrade database schema."""
    # PostgreSQL refuses a new enum value in the transaction that added it,
    # and the checks on an adopted Project's row read `adopted`.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE project_state ADD VALUE 'adopted'")
        op.execute("ALTER TYPE transition_kind ADD VALUE 'adopted'")

    op.add_column("projects", sa.Column("adopted_group", sa.Text(), nullable=True))
    op.create_unique_constraint(None, "projects", ["adopted_group"])
    op.drop_constraint("ck_projects_draft_slug", "projects", type_="check")
    op.create_check_constraint("ck_projects_unopened_slug", "projects", _UNOPENED_SLUG)
    op.create_check_constraint(
        "ck_projects_adopted_group",
        "projects",
        "(state_code = 'adopted') = (adopted_group IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_projects_adopted_archived",
        "projects",
        "state_code <> 'adopted' OR archived",
    )

    op.add_column(
        "transcripts", sa.Column("adopted_project_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        None, "transcripts", "projects", ["adopted_project_id"], ["id"]
    )
    op.create_check_constraint(
        "ck_transcripts_adopted_project",
        "transcripts",
        "agent_id IS NULL OR adopted_project_id IS NULL",
    )


def downgrade() -> None:
    """Downgrade database schema: the two enums rebuilt without `adopted`,
    which PostgreSQL drops no value of in place; an adopted Project's row
    fails the cast."""
    op.drop_column("transcripts", "adopted_project_id")
    op.drop_constraint("ck_projects_adopted_archived", "projects", type_="check")
    op.drop_constraint("ck_projects_adopted_group", "projects", type_="check")
    op.drop_constraint("ck_projects_unopened_slug", "projects", type_="check")
    op.drop_column("projects", "adopted_group")
    # The column's default is a value of the type it was written against.
    op.execute("ALTER TABLE projects ALTER COLUMN state_code DROP DEFAULT")
    _without_adopted("project_state", PROJECT_STATE, "projects", "state_code")
    op.execute("ALTER TABLE projects ALTER COLUMN state_code SET DEFAULT 'draft'")
    _without_adopted(
        "transition_kind", TRANSITION_KIND, "project_transitions", "kind_code"
    )
    op.create_check_constraint("ck_projects_draft_slug", "projects", _DRAFT_SLUG)


def _without_adopted(
    name: str, values: tuple[str, ...], table: str, column: str
) -> None:
    """The enum rebuilt with `values` alone."""
    op.execute(f"ALTER TYPE {name} RENAME TO {name}_0039")
    postgresql.ENUM(*values, name=name).create(op.get_bind())
    op.execute(
        f"ALTER TABLE {table} ALTER COLUMN {column}"
        f" TYPE {name} USING {column}::text::{name}"
    )
    op.execute(f"DROP TYPE {name}_0039")
