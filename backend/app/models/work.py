"""Work (DB §2.2), the subtype of Item and of Session, Claim Assignment,
Progress Step and Debrief Entry, characteristics of Work, Research Assignment,
and Clarification Run, a role of a Work (DB §2.3).

`work` is the extension table keyed by the id a Work's Item and Session share
(DB §7.3).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.reference import (
    PROGRESS_STATE,
    WORK_TRIGGER,
    ProgressState,
    WorkTrigger,
)


class Work(db.Model):  # type: ignore[name-defined]
    """One run of a session Pilot started or resumed, shown on the timeline.

    `project_id` and `session_kind_code` are its Item's and its Session's,
    carried so that the keys reach one Project by both paths (DB assertion
    166) and the checks read the Session Kind (DB 149, 167).

    `trigger_note_id` is the Pilot Note whose offer's taking placed the job,
    set exactly for Work Trigger `offer_taken`, which names no trigger Item:
    the Item it follows from is the note's Prose Item (DB 630). That the
    note is on an Item of the Work's Project is the server's: no key reaches
    the note's Project from this row.

    `retried_by_id` is the job a person's Retry of this failed or stopped
    job placed, set once and never changed: a recursive list, a job retried
    at most once and a retry retrying one job.

    `done_note` is Pilot's reason for closing the Work for good, the words
    `stop_work` gave, none for a Work a person closed, for one done any other
    way and for an open one (DB 346): a rule across `items` and `work` the
    server keeps.

    `debrief` is the stage session's own words on how its run went, set once
    with the Work's Debrief Entries by its Session's call and never changed
    (DB 323, 324); that a Work has entries exactly when it has a debrief is
    the server's.

    `debrief_subject` and `debrief_completes` are given with the debrief and
    never changed (DB 608); a debrief given before they were taken has
    neither, so no Debrief Notice carries it (DB 609). `debrief_notice_id`
    names the notice that carries the debrief, set once at its placement;
    `debrief_notice_kind_code` is that Item's kind, carried so that the key
    reaches a Debrief Notice. That the notice is of the Work's Project and
    carries one subject (DB 610) is the server's.

    `debrief_figures` is the loop's figures as the workflow gives them, given
    with the debrief and never changed (DB 635). `debrief_notable` is Pilot's
    lines on the debrief, written by the pass after the Work's turn, a later
    pass replacing them (DB 636).
    """

    __tablename__ = "work"
    __table_args__ = (
        ForeignKeyConstraint(["project_id", "id"], ["items.project_id", "items.id"]),
        ForeignKeyConstraint(
            ["project_id", "id", "session_kind_code"],
            ["sessions.project_id", "sessions.id", "sessions.kind_code"],
        ),
        # The trigger Item is of the Work's Project (DB assertion 166).
        ForeignKeyConstraint(
            ["project_id", "trigger_item_id"], ["items.project_id", "items.id"]
        ),
        # A Work is a `work` or `job` Session; a Chat's never is (DB 149).
        CheckConstraint(
            "session_kind_code IN ('work', 'job')", name="ck_work_session_kind"
        ),
        # A job has a Work Trigger, a worker's run none (DB assertion 167).
        CheckConstraint(
            "(session_kind_code = 'job') = (trigger_code IS NOT NULL)",
            name="ck_work_trigger",
        ),
        CheckConstraint("trigger_item_id <> id", name="ck_work_trigger_item"),
        # An offer's job names its Pilot Note and no trigger Item (DB 630).
        CheckConstraint(
            "(trigger_note_id IS NOT NULL)"
            " = (trigger_code IS NOT DISTINCT FROM 'offer_taken')"
            " AND (trigger_note_id IS NULL OR trigger_item_id IS NULL)",
            name="ck_work_trigger_note",
        ),
        # A job runs in the store, placed in no repository (DB §2.2).
        CheckConstraint(
            "session_kind_code = 'work' OR repo IS NULL", name="ck_work_repo"
        ),
        # What a retry's key references, so the job it retries is of its
        # Project and its Session Kind.
        UniqueConstraint("project_id", "id", "session_kind_code"),
        ForeignKeyConstraint(
            ["project_id", "retried_by_id", "session_kind_code"],
            ["work.project_id", "work.id", "work.session_kind_code"],
        ),
        # Only a job is retried, by another job.
        CheckConstraint(
            "retried_by_id IS NULL"
            " OR (session_kind_code = 'job' AND retried_by_id <> id)",
            name="ck_work_retried_by",
        ),
        # A retry retries one job.
        Index("uq_work_retried_by_id", "retried_by_id", unique=True),
        # Only a worker's run has a debrief (DB 323).
        CheckConstraint(
            "session_kind_code = 'work' OR debrief IS NULL", name="ck_work_debrief"
        ),
        # A subject, a completion, figures and Pilot's lines only with a
        # debrief, and a debrief that leaves its subject to a later one names
        # it (DB 608, 635, 636).
        CheckConstraint(
            "(debrief IS NOT NULL"
            " OR (debrief_subject IS NULL AND debrief_completes IS NULL"
            " AND debrief_figures IS NULL AND debrief_notable IS NULL))"
            " AND (debrief_completes IS NOT FALSE OR debrief_subject IS NOT NULL)",
            name="ck_work_debrief_fields",
        ),
        ForeignKeyConstraint(
            ["debrief_notice_id", "debrief_notice_kind_code"],
            ["items.id", "items.kind_code"],
        ),
        # The notice is a Debrief Notice, and it carries only a debrief given
        # with its completion (DB 607, 609).
        CheckConstraint(
            "(debrief_notice_id IS NULL) = (debrief_notice_kind_code IS NULL)"
            " AND (debrief_notice_kind_code IS NULL"
            " OR (debrief_notice_kind_code = 'debrief_notice'"
            " AND debrief_completes IS NOT NULL))",
            name="ck_work_debrief_notice",
        ),
        # A completing Work's done reads its subject's uncarried debriefs (DB
        # §7.6).
        Index(
            "ix_work_debrief_uncarried",
            "project_id",
            "debrief_subject",
            postgresql_where=text(
                "debrief_notice_id IS NULL AND debrief_subject IS NOT NULL"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    project_id: Mapped[uuid.UUID]
    session_kind_code: Mapped[str] = mapped_column(Text)
    trigger_code: Mapped[WorkTrigger | None] = mapped_column(WORK_TRIGGER)
    trigger_item_id: Mapped[uuid.UUID | None]
    trigger_note_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("pilot_notes.id")
    )
    repo: Mapped[str | None] = mapped_column(Text)
    autopilot: Mapped[bool] = mapped_column(Boolean)
    retried_by_id: Mapped[uuid.UUID | None]
    done_note: Mapped[str | None] = mapped_column(Text)
    debrief: Mapped[str | None] = mapped_column(Text)
    debrief_subject: Mapped[str | None] = mapped_column(Text)
    debrief_completes: Mapped[bool | None] = mapped_column(Boolean)
    debrief_notice_id: Mapped[uuid.UUID | None]
    debrief_notice_kind_code: Mapped[str | None] = mapped_column(Text)
    debrief_figures: Mapped[str | None] = mapped_column(Text)
    debrief_notable: Mapped[str | None] = mapped_column(Text)


class ClaimAssignment(db.Model):  # type: ignore[name-defined]
    """One naming of a claimed action Block by the Work that does it, written
    when `add_item` adds the Work and never changed (DB decision 64). Of a
    Block's namings, the one whose Work's Item has the highest `seq` stands
    (DB 260).

    That the Work is a worker's run of the Block's Project, and the Block an
    open action of a registered document of it or of an item of Pilot's own
    of it (DB 261, widened by D224), is the server's check at the `add_item`:
    no key reaches the Block's Project from this row.
    """

    __tablename__ = "claim_assignments"
    __table_args__ = (
        # A claimed Block's latest naming (DB 260).
        Index("ix_claim_assignments_block_id", "block_id"),
    )

    work_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work.id"), primary_key=True)
    block_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("blocks.id"), primary_key=True
    )


class ProgressStep(db.Model):  # type: ignore[name-defined]
    """One step of a Work's run, as the run's `set_progress` lists it (DB
    decision 69): its code the run's name for it, its position its place in
    the list, from 1 without a gap (DB 285), which no constraint holds.

    `started_at` is the server's clock when the step first went `active`, or
    went straight to `done`, never changed once written; `ended_at` when it
    last went `done` (DB 287). `why` is the short line the run gives with
    the step, standing as the last list gave it (DB 327).

    `kind_code` is the kind the workflow gives the step and `marked` its
    word that the step is in trouble, each as the step's last publication
    had it, none where it gave none. `listed_ahead` is the server's: whether
    the step stood on its Work's list as pending before it began, none where
    that is unknown (DB decision 79).

    That the Work is a worker's run whose own Session writes it (DB 286) is
    the server's check at the call: no key reaches the Session Kind from this
    row.
    """

    __tablename__ = "progress_steps"
    __table_args__ = (
        # Checked at the commit, so a replace reorders a whole list in its
        # transaction.
        UniqueConstraint(
            "work_id",
            "position",
            name="uq_progress_steps_work_id_position",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("position >= 1", name="ck_progress_steps_position"),
        CheckConstraint(
            "state_code = 'pending' OR started_at IS NOT NULL",
            name="ck_progress_steps_started",
        ),
        # A step has an end exactly while it is done (DB 287).
        CheckConstraint(
            "(state_code = 'done') = (ended_at IS NOT NULL)",
            name="ck_progress_steps_ended",
        ),
    )

    work_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work.id"), primary_key=True)
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    state_code: Mapped[ProgressState] = mapped_column(PROGRESS_STATE)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    why: Mapped[str | None] = mapped_column(Text)
    kind_code: Mapped[str | None] = mapped_column(ForeignKey("step_kinds.code"))
    listed_ahead: Mapped[bool | None] = mapped_column(Boolean)
    marked: Mapped[bool | None] = mapped_column(Boolean)


class DebriefEntry(db.Model):  # type: ignore[name-defined]
    """One account in a Work's debrief, as the workflow gives it, written
    with the Work's `debrief` at its one call and never changed (DB decision
    76, 322 to 325): its position its place in the order given, from 1
    without a gap, which no constraint holds. Every value is the workflow's,
    stored and shown as given and read for nothing else (DB 326).
    """

    __tablename__ = "debrief_entries"
    __table_args__ = (
        CheckConstraint("position >= 1", name="ck_debrief_entries_position"),
        CheckConstraint('"round" >= 1', name="ck_debrief_entries_round"),
        CheckConstraint("duration >= 0", name="ck_debrief_entries_duration"),
        # Words, or a pass or a fail in their place, or neither (DB 325).
        CheckConstraint(
            "words IS NULL OR passed IS NULL", name="ck_debrief_entries_result"
        ),
    )

    work_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    section: Mapped[str] = mapped_column(Text)
    round: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(Text)
    duration: Mapped[int] = mapped_column(Integer)
    words: Mapped[str | None] = mapped_column(Text)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    why: Mapped[str | None] = mapped_column(Text)


class ResearchAssignment(db.Model):  # type: ignore[name-defined]
    """One naming of a Block by the Work that checks a fact its answer rests
    on, written when `add_item` adds the Work and never changed (DB decision
    71). Of a Block's namings, the one whose Work's Item has the highest `seq`
    stands (DB 292).

    That the Work is a worker's run of the Block's Project, and the Block
    unanswered in an open registered document of it (DB 293), is the
    server's check at the `add_item`: no key reaches the Block's Project from
    this row.
    """

    __tablename__ = "research_assignments"
    __table_args__ = (
        # A researched Block's latest naming (DB 292).
        Index("ix_research_assignments_block_id", "block_id"),
    )

    work_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work.id"), primary_key=True)
    block_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("blocks.id"), primary_key=True
    )


class ClarificationRun(db.Model):  # type: ignore[name-defined]
    """The role of a Work that puts one pre-ruling pass's Writer Questions to
    the writer, resuming the worker's conversation (DB decision 63).
    `pass_id` is the pass, the job whose Turns asked them, clarified once (DB
    253); `reply` the run's turn's final text and `replied_at` its end,
    written together once, at the end of the turn that brought one (DB 255).

    That the run is a worker's run of the pass's Project and the pass a job
    after a worker's turn (DB 254) is the server's at the placement: no key
    reaches either Session Kind from this row.
    """

    __tablename__ = "clarification_runs"
    __table_args__ = (
        # A pass's one run (DB 253).
        Index("uq_clarification_runs_pass_id", "pass_id", unique=True),
        CheckConstraint("pass_id <> id", name="ck_clarification_runs_pass"),
        CheckConstraint(
            "(reply IS NULL) = (replied_at IS NULL)", name="ck_clarification_runs_reply"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work.id"), primary_key=True)
    pass_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work.id"))
    reply: Mapped[str | None] = mapped_column(Text)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
