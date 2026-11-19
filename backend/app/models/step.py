"""Step Transcript and Step Timing (DB §2.5), with Step Kind (§2.11): what a
run's published steps leave beside its list (DB decision 79).

Step Kind is the workflow's: a row is written when a publication first names
its code, and no revision writes one (DB §7.2).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ColumnElement,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Select,
    SQLColumnExpression,
    Text,
    UniqueConstraint,
    and_,
    func,
    select,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.environment import Environment
from app.models.session import Session
from app.models.transcript import Transcript
from app.models.work import Work


class StepKind(db.Model):  # type: ignore[name-defined]
    """A kind of step of a run, as the workflow publishes it, stored and
    shown as given."""

    __tablename__ = "step_kinds"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class StepTranscript(db.Model):  # type: ignore[name-defined]
    """One Progress Step's naming of one main thread, by Claude Code's
    session id: the workflow's word that this thread did that step's work,
    deleted with its step (DB 355, 356).

    Its Transcript is not held: `names_main_thread()` finds it, none until a
    collector publishes it (DB 358, 574).
    """

    __tablename__ = "step_transcripts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["work_id", "code"],
            ["progress_steps.work_id", "progress_steps.code"],
            ondelete="CASCADE",
        ),
    )

    work_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    session_id: Mapped[str] = mapped_column(Text, primary_key=True)


class StepTiming(db.Model):  # type: ignore[name-defined]
    """One finished step of a Work's run, as the run published it: its kind
    and the seconds its work took, kept whatever becomes of the run's list
    (DB 562 to 565, 573). One written live holds its step's `code`, a seeded
    one the plugin's `key`, and no key reaches a Progress Step from this row:
    the step may be gone.

    `repo` is the repo of its Work as `repo_of_work()` gave it when the row
    was written, none where the Work had none: stored once, so that the
    database holds one `key` per repo (DB 572).
    """

    __tablename__ = "step_timings"
    __table_args__ = (
        # A step of a Work is timed once (DB 572); a seeded one has no code.
        UniqueConstraint("work_id", "code", name="uq_step_timings_work_id_code"),
        # One key per repo (DB 572), whichever Work ran the seed.
        Index(
            "uq_step_timings_repo_key",
            "repo",
            "key",
            unique=True,
            postgresql_where=text("key IS NOT NULL"),
        ),
        # A kind's last timings by their end, those listed ahead and those
        # not each a range of their own: in all repos, and in one.
        Index(
            "ix_step_timings_kind_code_listed_ahead_ended_at",
            "kind_code",
            "listed_ahead",
            "ended_at",
            "id",
        ),
        Index(
            "ix_step_timings_repo_kind_code_listed_ahead_ended_at",
            "repo",
            "kind_code",
            "listed_ahead",
            "ended_at",
            "id",
        ),
        # Written live or seeded, never both (DB 572).
        CheckConstraint(
            "(code IS NULL) <> (key IS NULL)", name="ck_step_timings_code_or_key"
        ),
        # A key is unique within a repo, so a seeded timing has one.
        CheckConstraint(
            "key IS NULL OR repo IS NOT NULL", name="ck_step_timings_seeded_repo"
        ),
        # A seeded timing's run set no mark (DB 572).
        CheckConstraint(
            "key IS NULL OR marked IS NULL", name="ck_step_timings_seeded_marked"
        ),
        CheckConstraint("duration >= 0", name="ck_step_timings_duration"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    work_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work.id"))
    kind_code: Mapped[str] = mapped_column(ForeignKey("step_kinds.code"))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration: Mapped[int] = mapped_column(Integer)
    listed_ahead: Mapped[bool | None] = mapped_column(Boolean)
    marked: Mapped[bool | None] = mapped_column(Boolean)
    code: Mapped[str | None] = mapped_column(Text)
    key: Mapped[str | None] = mapped_column(Text)
    repo: Mapped[str | None] = mapped_column(Text)


def names_main_thread() -> ColumnElement[bool]:
    """What joins a Step Transcript to the Transcript it names: the main
    thread of its `session_id`, the Transcript with no `agent_id` (DB 574).

    A sub-agent's thread stands with no `main_id` until its main thread is
    published, so a null `main_id` does not tell the main thread.
    """
    return and_(
        Transcript.session_id == StepTranscript.session_id,
        Transcript.agent_id.is_(None),
    )


def repo_of_work(
    work_id: uuid.UUID | SQLColumnExpression[uuid.UUID],
) -> Select[str | None]:
    """The repo of a Work, which a Step Timing of it is written with: its
    `repo` label, else the `repo` of the Environment its Session runs in,
    none with neither (DB 572). `work_id` is an id, or a column of an
    enclosing statement the select then reads as a subquery."""
    return (
        select(func.coalesce(Work.repo, Environment.repo))
        .select_from(Work)
        .join(Session, Session.id == Work.id)
        .outerjoin(Environment, Environment.id == Session.environment_id)
        .where(Work.id == work_id)
    )
