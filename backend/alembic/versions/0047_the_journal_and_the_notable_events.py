"""The journal, the loop's figures and Pilot's lines on a debrief.

DB decision 85, assertions 150 and 634 to 636: Document Role's `journal`,
the Project's third Project Document, `journal.md`, born empty here for
every Project past Create, an archived one included, as Create project
bears it from now on; a draft has none, and an adopted Project the draft
alone. `work.debrief_figures` and `work.debrief_notable`, each null without
a debrief. Nothing is backfilled: no journal takes an earlier debrief, and
no debrief had figures or lines.

Revision ID: 0047
Revises: 0046
Create Date: 2026-11-19

"""

import hashlib
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DOCUMENT_ROLE = ("draft", "handbook")

_DEBRIEF_FIELDS = (
    "(debrief IS NOT NULL"
    " OR (debrief_subject IS NULL AND debrief_completes IS NULL{}))"
    " AND (debrief_completes IS NOT FALSE OR debrief_subject IS NOT NULL)"
)
_EMPTY_HASH = hashlib.sha256(b"").hexdigest()


def bear_journals() -> None:
    """An empty journal, published, with its `born` Version, for every
    Project past Create that has none: what `DocumentService.bear_journal`
    writes."""
    bind = op.get_bind()
    projects: list[uuid.UUID] = list(
        bind.execute(
            sa.text(
                "SELECT p.id FROM projects p"
                " WHERE p.state_code IN ('open', 'finished')"
                " AND NOT EXISTS (SELECT 1 FROM documents d"
                " WHERE d.project_id = p.id AND d.role_code = 'journal')"
                " ORDER BY p.number"
            )
        ).scalars()
    )
    for project_id in projects:
        journal = {"id": uuid.uuid4(), "project": project_id, "hash": _EMPTY_HASH}
        bind.execute(
            sa.text(
                "INSERT INTO documents (id, path, project_id, role_code,"
                " published_text, published_hash, published_at)"
                " VALUES (:id, 'journal.md', :project, 'journal', '', :hash, now())"
            ),
            journal,
        )
        bind.execute(
            sa.text(
                "INSERT INTO document_versions"
                " (document_id, number, cause_code, text, hash, created_at)"
                " VALUES (:id, 1, 'born', '', :hash, now())"
            ),
            journal,
        )


def upgrade() -> None:
    """Upgrade database schema."""
    # PostgreSQL refuses a new enum value in the transaction that added it,
    # and the journals born below are of the role `journal`.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE document_role ADD VALUE 'journal'")

    bear_journals()

    op.add_column("work", sa.Column("debrief_figures", sa.Text(), nullable=True))
    op.add_column("work", sa.Column("debrief_notable", sa.Text(), nullable=True))
    op.drop_constraint("ck_work_debrief_fields", "work", type_="check")
    op.create_check_constraint(
        "ck_work_debrief_fields",
        "work",
        _DEBRIEF_FIELDS.format(
            " AND debrief_figures IS NULL AND debrief_notable IS NULL"
        ),
    )


def downgrade() -> None:
    """Downgrade database schema: every debrief's figures and Pilot's lines
    on it are lost, and every journal with its Versions; Document Role is
    rebuilt without `journal`, which PostgreSQL drops no value of in place. A
    journal that holds a block fails it."""
    op.drop_constraint("ck_work_debrief_fields", "work", type_="check")
    op.create_check_constraint(
        "ck_work_debrief_fields", "work", _DEBRIEF_FIELDS.format("")
    )
    op.drop_column("work", "debrief_notable")
    op.drop_column("work", "debrief_figures")

    op.execute(
        "DELETE FROM document_versions v USING documents d"
        " WHERE v.document_id = d.id AND d.role_code = 'journal'"
    )
    op.execute("DELETE FROM documents WHERE role_code = 'journal'")
    op.execute("ALTER TYPE document_role RENAME TO document_role_0046")
    postgresql.ENUM(*DOCUMENT_ROLE, name="document_role").create(op.get_bind())
    op.execute(
        "ALTER TABLE documents ALTER COLUMN role_code"
        " TYPE document_role USING role_code::text::document_role"
    )
    op.execute("DROP TYPE document_role_0046")
