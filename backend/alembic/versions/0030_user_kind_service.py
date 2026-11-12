"""User Kind's `service`.

Slice 045, P1 (DB decision 77; 338): a service user, the party a session
outside Pilot calls Pilot's projects surface as, is a User of kind `service`:
its subject the service account of the client whose credential it calls
with, and no email, no palette slot and no showing of the alarms. Its row is
its command's, `create-service-user`; the revision writes none.

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-12

"""

from collections.abc import Sequence

from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USER_KIND = ("person", "agent")

_USERS_SERVICE = (
    "kind_code <> 'service' OR (subject IS NOT NULL AND email IS NULL"
    " AND avatar_slot IS NULL AND alarm_seen_at IS NULL)"
)
# The checks of `users` that name a kind: PostgreSQL holds each literal as a
# value of the enum type it was written against, so the downgrade's new type
# takes them written again.
_KIND_CHECKS = {
    "ck_users_agent_handle": "(kind_code = 'agent') = (handle = 'agent')",
    "ck_users_agent": (
        "kind_code <> 'agent' OR (subject IS NULL AND email IS NULL"
        " AND avatar_slot IS NULL AND alarm_seen_at IS NULL)"
    ),
    "ck_users_person": (
        "kind_code <> 'person' OR (subject IS NOT NULL AND avatar_slot IS NOT NULL)"
    ),
}


def upgrade() -> None:
    """Upgrade database schema."""
    # PostgreSQL refuses a new enum value in the transaction that added it,
    # and the check on a service user's row reads `service`.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE user_kind ADD VALUE 'service'")

    op.create_check_constraint("ck_users_service", "users", _USERS_SERVICE)


def downgrade() -> None:
    """Downgrade database schema: the enum rebuilt without `service`, which
    PostgreSQL drops no value of in place; a service user's row fails the
    cast."""
    op.drop_constraint("ck_users_service", "users")
    for name in _KIND_CHECKS:
        op.drop_constraint(name, "users")
    op.execute("ALTER TYPE user_kind RENAME TO user_kind_0030")
    postgresql.ENUM(*USER_KIND, name="user_kind").create(op.get_bind())
    op.execute(
        "ALTER TABLE users ALTER COLUMN kind_code"
        " TYPE user_kind USING kind_code::text::user_kind"
    )
    op.execute("DROP TYPE user_kind_0030")
    for name, condition in _KIND_CHECKS.items():
        op.create_check_constraint(name, "users", condition)
