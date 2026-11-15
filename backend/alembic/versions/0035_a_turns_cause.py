"""A Turn's cause.

Slice 048, P1 (DB decision 79, assertions 351 and 352): Turn Cause, Pilot's
own closed list, an enum (DB §7.2), and `turns.cause_code`, required. Every
Turn there is takes the cause its writer gives one today, read from its rows:

- with an author, `person`;
- the first of its Session: `clarification` where the Session is a
  Clarification Run, `wait_run` where its Work's trigger is `wait_fired`,
  `continuation` where it is a work item with a trigger Item, else `brief`;
- past the first, with no author, by its text: `carry_on` where it opens with
  the restart's line, `follow_up` where it ends on the follow-up's last line,
  `nudge` where it ends on the nudges' last sentence;
- any other, "continue" and a message sent again among them: `resume` on a
  work item, the one kind of Session a person resumes, else `carry_on`.

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TURN_CAUSE = (
    "brief",
    "person",
    "continuation",
    "clarification",
    "resume",
    "nudge",
    "follow_up",
    "carry_on",
    "wait_run",
)

# The texts as the server wrote them up to this revision, none holding a LIKE
# wildcard: how a work item's re-create opens (`BriefService.restarted`), the
# follow-up's last line, and the sentence every nudge ends on.
RESTARTED = (
    "Your environment restarted under your last turn, and this conversation"
    " goes on in a new session."
)
FOLLOW_UP_END = "Fix it and end your turn."
NUDGED = "This is a nudge to allow you to complete any outstanding work, if any."

BACK_FILL = """
UPDATE turns t SET cause_code = CAST(
    CASE
        WHEN t.author_user_id IS NOT NULL THEN 'person'
        WHEN t.seq = 1 THEN
            CASE
                WHEN c.id IS NOT NULL THEN 'clarification'
                WHEN w.trigger_code = 'wait_fired' THEN 'wait_run'
                WHEN s.kind_code = 'work' AND w.trigger_item_id IS NOT NULL
                    THEN 'continuation'
                ELSE 'brief'
            END
        WHEN t.message LIKE :restarted THEN 'carry_on'
        WHEN t.message LIKE :follow_up THEN 'follow_up'
        WHEN t.message LIKE :nudged THEN 'nudge'
        WHEN s.kind_code = 'work' THEN 'resume'
        ELSE 'carry_on'
    END AS turn_cause)
FROM sessions s
LEFT JOIN work w ON w.id = s.id
LEFT JOIN clarification_runs c ON c.id = s.id
WHERE s.id = t.session_id
"""


def upgrade() -> None:
    """Upgrade database schema."""
    bind = op.get_bind()
    postgresql.ENUM(*TURN_CAUSE, name="turn_cause").create(bind)
    op.add_column(
        "turns",
        sa.Column(
            "cause_code",
            postgresql.ENUM(name="turn_cause", create_type=False),
            nullable=True,
        ),
    )
    bind.execute(
        sa.text(BACK_FILL),
        {
            "restarted": f"{RESTARTED}%",
            "follow_up": f"%{FOLLOW_UP_END}",
            "nudged": f"%{NUDGED}",
        },
    )
    op.alter_column("turns", "cause_code", nullable=False)
    op.create_check_constraint(
        "ck_turns_cause",
        "turns",
        "(cause_code = 'person') = (author_user_id IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade database schema: every Turn's cause is lost."""
    op.drop_constraint("ck_turns_cause", "turns", type_="check")
    op.drop_column("turns", "cause_code")
    postgresql.ENUM(name="turn_cause").drop(op.get_bind())
