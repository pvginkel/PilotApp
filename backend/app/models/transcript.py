"""Transcript, Launch, Prompt, Hook Run, Compaction and Walk (DB §2.6), with
Repository (§2.9) and the reference entities that classify them (§2.11): a
conversation's facts as a collector's publication gives them (DB decisions 79
and 81), and the end of the collector's pass that published them.

The reference entities here are the collector's: a row is written when a
publication first names its code, and no revision writes one (DB §7.2).
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
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class Repository(db.Model):  # type: ignore[name-defined]
    """A git repository the fleet works in, by the name of its checkout."""

    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)


class Component(db.Model):  # type: ignore[name-defined]
    """A kind of software a Launch runs with or a Transcript is read by."""

    __tablename__ = "components"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class ComponentVersion(db.Model):  # type: ignore[name-defined]
    """A released version of one Component."""

    __tablename__ = "component_versions"
    __table_args__ = (
        UniqueConstraint("component_code", "version"),
        # What a Launch Component's key references, so its Component is its
        # Component Version's.
        UniqueConstraint("id", "component_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    component_code: Mapped[str] = mapped_column(ForeignKey("components.code"))
    version: Mapped[str] = mapped_column(Text)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Transcript(db.Model):  # type: ignore[name-defined]
    """A Claude Code conversation as one file on the fleet's home records it:
    a main thread, or one sub-agent's thread, which has an `agent_id`.

    `file_size`, `file_modified_at`, `collected_at` and `read_under_id` are
    its last publication's; `replayed_size` the file's size at its last whole
    one (DB 605). A sub-agent's thread is held with no `main_id` until its
    main thread is published. `spawned_by_tool_use_id` is the `tool_use_id`
    its record names its spawning call by, and `spawned_by_id` the Tool Call
    of that name once a thread of its conversation holds it (DB decision
    79.16). `adopted_project_id` is a label of a main thread's: the adopted
    Project of the group its last publication named for it, none where it
    named none. That a thread's main has no `agent_id` (DB 534), that its
    spawning call lies under that main (DB 535), and that an adopted
    Transcript's Project is `adopted` and no Launch of it is run by a Session
    (DB 539) are the publication's and the placement's to keep: no key
    reaches them.
    """

    __tablename__ = "transcripts"
    __table_args__ = (
        # One main thread per `session_id`, and one thread per sub-agent of it.
        Index(
            "uq_transcripts_session_id_agent_id",
            "session_id",
            "agent_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        # Read when a Tool Call goes, to clear what it spawned.
        Index(
            "ix_transcripts_spawned_by_id",
            "spawned_by_id",
            postgresql_where=text("spawned_by_id IS NOT NULL"),
        ),
        # A main thread has no main thread and no spawning call (DB 534).
        CheckConstraint(
            "agent_id IS NOT NULL OR (main_id IS NULL AND spawned_by_id IS NULL"
            " AND spawned_by_tool_use_id IS NULL)",
            name="ck_transcripts_main_thread",
        ),
        # Only a main thread is hosted by an Environment (DB 536).
        CheckConstraint(
            "agent_id IS NULL OR environment_id IS NULL",
            name="ck_transcripts_environment",
        ),
        CheckConstraint("file_size >= 0", name="ck_transcripts_file_size"),
        # DB 605.
        CheckConstraint(
            "replayed_size >= 0 AND replayed_size <= file_size",
            name="ck_transcripts_replayed_size",
        ),
        # The group is named on a main thread (DB §2.6).
        CheckConstraint(
            "agent_id IS NULL OR adopted_project_id IS NULL",
            name="ck_transcripts_adopted_project",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str] = mapped_column(Text)
    agent_id: Mapped[str | None] = mapped_column(Text)
    main_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("transcripts.id"))
    # Added once both tables stand: a Tool Call's key reaches back here
    # through its Call.
    spawned_by_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "tool_calls.id",
            ondelete="SET NULL",
            use_alter=True,
            name="transcripts_spawned_by_id_fkey",
        )
    )
    spawned_by_tool_use_id: Mapped[str | None] = mapped_column(Text)
    agent_type: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    working_directory: Mapped[str] = mapped_column(Text)
    repository_id: Mapped[int | None] = mapped_column(ForeignKey("repositories.id"))
    environment_id: Mapped[str | None] = mapped_column(ForeignKey("environments.id"))
    adopted_project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id")
    )
    file_size: Mapped[int] = mapped_column(BigInteger)
    file_modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    replayed_size: Mapped[int] = mapped_column(BigInteger)
    read_under_id: Mapped[int] = mapped_column(ForeignKey("component_versions.id"))


class Launch(db.Model):  # type: ignore[name-defined]
    """A start of a Claude Code process on a main-thread Transcript, with its
    life until the process exits: `started_at` the time of the first line it
    wrote, `ended_at` of the last that carries one, none while it runs (DB
    586).

    `session_id` and `turn_seq` are Pilot's: the Session that ran it and,
    of that Session, the Turn that started it, none for a Launch started
    between two Turns (DB decision 79 point 7). `launch_placement` sets
    them, once.

    That its Transcript is a main thread (DB 536), that it runs with a
    Component Version (DB 389) and that its Session's `conversation_id` is
    its Transcript's `session_id` (DB 538) are the writers' to keep.
    """

    __tablename__ = "launches"
    __table_args__ = (
        # What a Prompt's key references, so the Prompt is of its Launch's
        # Transcript.
        UniqueConstraint("transcript_id", "id"),
        # Its Turn is a Turn of its Session, held once (DB 537).
        ForeignKeyConstraint(
            ["session_id", "turn_seq"], ["turns.session_id", "turns.seq"]
        ),
        CheckConstraint(
            "turn_seq IS NULL OR session_id IS NOT NULL", name="ck_launches_turn"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    transcript_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transcripts.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sessions.id"))
    turn_seq: Mapped[int | None] = mapped_column(Integer)


class LaunchComponent(db.Model):  # type: ignore[name-defined]
    """One Launch's use of one Component Version. It carries the version's
    Component, so that a Launch runs with one version of each (DB 541)."""

    __tablename__ = "launch_components"
    __table_args__ = (
        ForeignKeyConstraint(
            ["component_version_id", "component_code"],
            ["component_versions.id", "component_versions.component_code"],
        ),
        UniqueConstraint("launch_id", "component_code"),
    )

    launch_id: Mapped[int] = mapped_column(
        ForeignKey("launches.id", ondelete="CASCADE"), primary_key=True
    )
    component_version_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    component_code: Mapped[str] = mapped_column(Text)


class PromptSource(db.Model):  # type: ignore[name-defined]
    """A kind of sender of a Prompt, in Claude Code's words."""

    __tablename__ = "prompt_sources"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class Prompt(db.Model):  # type: ignore[name-defined]
    """An input a Launch received into its Transcript. It carries its
    Launch's Transcript, which a Call that follows it shares (DB 542)."""

    __tablename__ = "prompts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["transcript_id", "launch_id"],
            ["launches.transcript_id", "launches.id"],
            ondelete="CASCADE",
        ),
        # What a Call's key references.
        UniqueConstraint("transcript_id", "id"),
        Index("ix_prompts_launch_id", "launch_id"),
        CheckConstraint("characters >= 0", name="ck_prompts_characters"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    transcript_id: Mapped[uuid.UUID] = mapped_column()
    launch_id: Mapped[int] = mapped_column(BigInteger)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_code: Mapped[str] = mapped_column(ForeignKey("prompt_sources.code"))
    characters: Mapped[int] = mapped_column(Integer)


class HookRun(db.Model):  # type: ignore[name-defined]
    """A run of one hook command at the end of a Prompt's run."""

    __tablename__ = "hook_runs"
    __table_args__ = (
        Index("ix_hook_runs_prompt_id", "prompt_id"),
        CheckConstraint("duration_ms >= 0", name="ck_hook_runs_duration_ms"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id", ondelete="CASCADE"))
    command: Mapped[str] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(Integer)
    failed: Mapped[bool] = mapped_column(Boolean)
    prevented_end: Mapped[bool] = mapped_column(Boolean)


class CompactionTrigger(db.Model):  # type: ignore[name-defined]
    """A kind of occasion a Compaction is made on."""

    __tablename__ = "compaction_triggers"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class Compaction(db.Model):  # type: ignore[name-defined]
    """A compaction of a Transcript's context, automatic or asked for."""

    __tablename__ = "compactions"
    __table_args__ = (
        # What a Call's key references.
        UniqueConstraint("transcript_id", "id"),
        CheckConstraint(
            "tokens_before >= 0 AND tokens_after >= 0", name="ck_compactions_tokens"
        ),
        CheckConstraint("duration_ms >= 0", name="ck_compactions_duration_ms"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    transcript_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("transcripts.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trigger_code: Mapped[str] = mapped_column(ForeignKey("compaction_triggers.code"))
    tokens_before: Mapped[int] = mapped_column(Integer)
    tokens_after: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class Walk(db.Model):  # type: ignore[name-defined]
    """A pass of the collector over the fleet's home, which the server stamps
    when the collector tells it that the pass ended (DB decision 79.28)."""

    __tablename__ = "walks"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
