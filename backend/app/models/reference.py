"""The reference entities (DB §2.4).

A reference entity with a fact about the category is a table: Item Kind, Done
Cause, Confirmation Reason and Session Kind. The other nineteen are PostgreSQL
enums (DB §7.2). The revisions are the one place a value is added, a table's
rows included.
"""

from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, Enum, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class UserKind(StrEnum):
    PERSON = "person"
    AGENT = "agent"


class OverruleKind(StrEnum):
    ADD_FIVE = "add_five"
    TO_THE_END = "to_the_end"


class ProjectState(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    FINISHED = "finished"


class TransitionKind(StrEnum):
    OPENED = "opened"
    FINISHED = "finished"
    REOPENED = "reopened"
    ARCHIVED = "archived"
    BROUGHT_BACK = "brought_back"
    AUTOPILOT_ON = "autopilot_on"
    AUTOPILOT_OFF = "autopilot_off"
    PAUSED = "paused"
    RESUMED = "resumed"


class DocumentRole(StrEnum):
    DRAFT = "draft"
    HANDBOOK = "handbook"


class VersionCause(StrEnum):
    BORN = "born"
    REGISTERED = "registered"
    TURN = "turn"
    DONE = "done"


class ErrorKind(StrEnum):
    PARSE = "parse"
    REVERTED = "reverted"


class BlockKind(StrEnum):
    DECISION = "decision"
    QUESTION = "question"
    ACTION = "action"


class AnswerChannel(StrEnum):
    APP = "app"
    CHAT = "chat"
    RECOMMENDED = "recommended"
    AUTOPILOT = "autopilot"


class WorkTrigger(StrEnum):
    SETUP = "setup"
    WORKER_TURN_ENDED = "worker_turn_ended"
    ITEM_DONE = "item_done"
    WAIT_FIRED = "wait_fired"


class FiringCause(StrEnum):
    TRANSITION = "transition"
    DUE = "due"
    REQUESTED = "requested"


class SyncOutcome(StrEnum):
    PULLED = "pulled"
    REBASED = "rebased"
    SKIPPED = "skipped"


class AttachmentSource(StrEnum):
    FILE = "file"
    DRAFT = "draft"


class SessionState(StrEnum):
    HELD = "held"
    STARTING = "starting"
    RUNNING = "running"
    IDLE = "idle"
    STOPPED = "stopped"
    ENDED = "ended"
    FAILED = "failed"


class RecordKind(StrEnum):
    CLAUDE = "claude"
    SEND = "send"
    SERVER = "server"
    RESULT = "result"


class ChatKind(StrEnum):
    DEFINITION = "definition"
    PROJECT = "project"


class CloseCause(StrEnum):
    TIMEOUT = "timeout"
    CREATED = "created"


class EffectKind(StrEnum):
    ADDED = "added"
    ANSWERED = "answered"
    MARKED = "marked"
    STOPPED = "stopped"
    FINISHED = "finished"
    ATTACHED = "attached"
    REGISTERED = "registered"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


def _enum_type(enum_class: type[StrEnum], name: str) -> Enum:
    # The database holds the values, not the member names.
    return Enum(
        enum_class,
        name=name,
        values_callable=lambda members: [member.value for member in members],
        metadata=db.metadata,
    )


USER_KIND = _enum_type(UserKind, "user_kind")
OVERRULE_KIND = _enum_type(OverruleKind, "overrule_kind")
PROJECT_STATE = _enum_type(ProjectState, "project_state")
TRANSITION_KIND = _enum_type(TransitionKind, "transition_kind")
DOCUMENT_ROLE = _enum_type(DocumentRole, "document_role")
VERSION_CAUSE = _enum_type(VersionCause, "version_cause")
ERROR_KIND = _enum_type(ErrorKind, "error_kind")
BLOCK_KIND = _enum_type(BlockKind, "block_kind")
ANSWER_CHANNEL = _enum_type(AnswerChannel, "answer_channel")
WORK_TRIGGER = _enum_type(WorkTrigger, "work_trigger")
FIRING_CAUSE = _enum_type(FiringCause, "firing_cause")
SYNC_OUTCOME = _enum_type(SyncOutcome, "sync_outcome")
ATTACHMENT_SOURCE = _enum_type(AttachmentSource, "attachment_source")
SESSION_STATE = _enum_type(SessionState, "session_state")
RECORD_KIND = _enum_type(RecordKind, "record_kind")
CHAT_KIND = _enum_type(ChatKind, "chat_kind")
CLOSE_CAUSE = _enum_type(CloseCause, "close_cause")
EFFECT_KIND = _enum_type(EffectKind, "effect_kind")
TASK_STATUS = _enum_type(TaskStatus, "task_status")

# Autogenerate compares no enum type, so the schema tests check these against
# the database's.
ENUM_TYPES = (
    USER_KIND,
    OVERRULE_KIND,
    PROJECT_STATE,
    TRANSITION_KIND,
    DOCUMENT_ROLE,
    VERSION_CAUSE,
    ERROR_KIND,
    BLOCK_KIND,
    ANSWER_CHANNEL,
    WORK_TRIGGER,
    FIRING_CAUSE,
    SYNC_OUTCOME,
    ATTACHMENT_SOURCE,
    SESSION_STATE,
    RECORD_KIND,
    CHAT_KIND,
    CLOSE_CAUSE,
    EFFECT_KIND,
    TASK_STATUS,
)


class ItemKind(db.Model):  # type: ignore[name-defined]
    """A kind of timeline entry; `form` says which subtype its Item is."""

    __tablename__ = "item_kinds"
    __table_args__ = (
        CheckConstraint("form IN ('prose', 'work', 'wait')", name="ck_item_kinds_form"),
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    form: Mapped[str] = mapped_column(Text)
    icon: Mapped[str] = mapped_column(Text)


class DoneCause(db.Model):  # type: ignore[name-defined]
    """A kind of way an Item came to be done."""

    __tablename__ = "done_causes"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    undo_offered: Mapped[bool] = mapped_column(Boolean)


class ConfirmationReason(db.Model):  # type: ignore[name-defined]
    """A kind of ground on which Pilot asks the operator's go.

    `description` is the one line `reference.json` carries for the agent.
    """

    __tablename__ = "confirmation_reasons"

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    asks_under_autopilot: Mapped[bool] = mapped_column(Boolean)
    description: Mapped[str] = mapped_column(Text)


class SessionKind(db.Model):  # type: ignore[name-defined]
    """A kind of Session: the MCP surface it gets, and whether it is a Work."""

    __tablename__ = "session_kinds"
    __table_args__ = (
        CheckConstraint(
            "surface IN ('pilot-store', 'pilot-work')", name="ck_session_kinds_surface"
        ),
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    surface: Mapped[str] = mapped_column(Text)
    on_timeline: Mapped[bool] = mapped_column(Boolean)
