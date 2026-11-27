"""The reference entities (DB §2.4).

A reference entity with a fact about the category is a table: Item Kind, Done
Cause, Confirmation Reason, Session Kind and Token Kind. The other twenty are
PostgreSQL enums (DB §7.2), as are Turn Cause, Hold Kind, Favourite Menu and
Origin, Pilot's own of the analysis dashboard's (DB §2.11). The revisions are the one place a value is added, a
table's rows included.
"""

from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, Enum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class UserKind(StrEnum):
    """A kind of party that acts in Pilot: a person who signs in, Pilot
    itself, or a service user, the party a session outside Pilot calls as
    (DB decision 77)."""

    PERSON = "person"
    AGENT = "agent"
    SERVICE = "service"


class OverruleKind(StrEnum):
    """A kind of way a person lifts the week's usage halt (DB §2.4; decision
    66): the allowance, a target under the second limit; run-out, at it, the
    target the wall."""

    ALLOWANCE = "allowance"
    RUN_OUT = "run_out"


class ProjectState(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    FINISHED = "finished"
    ADOPTED = "adopted"


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
    ADOPTED = "adopted"


class DocumentRole(StrEnum):
    DRAFT = "draft"
    HANDBOOK = "handbook"
    JOURNAL = "journal"


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
    OFFER_TAKEN = "offer_taken"


class FiringCause(StrEnum):
    TRANSITION = "transition"
    DUE = "due"
    REQUESTED = "requested"


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
    """A kind of way a Chat or a Conversation closed: `created` a Chat's
    alone, `ended`, its caller's end, a Conversation's alone (DB decision
    77)."""

    TIMEOUT = "timeout"
    CREATED = "created"
    FINISHED = "finished"
    REOPENED = "reopened"
    ARCHIVED = "archived"
    ENDED = "ended"


class EffectKind(StrEnum):
    ADDED = "added"
    ANSWERED = "answered"
    MARKED = "marked"
    STOPPED = "stopped"
    FINISHED = "finished"
    ATTACHED = "attached"
    REGISTERED = "registered"


class Surface(StrEnum):
    """A Session Kind's `surface`: the tools of Pilot's MCP server its
    sessions are handed (TD §4.5)."""

    WORK = "pilot-work"
    STORE = "pilot-store"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class UsageWindow(StrEnum):
    """A span over which the subscription's quota is counted, KubeCoder's code."""

    FIVE_HOUR = "five_hour"
    SEVEN_DAY = "seven_day"


class ProgressState(StrEnum):
    """Where a step of a run's list stands; not Task Status, the plan's own."""

    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"


class TurnCause(StrEnum):
    """A kind of reason Pilot sends a Turn (DB §2.11), given at the write and
    never changed (DB 352). It says why the Turn was sent, not what it
    carries: a Resume that sends a start's brief again is `resume`."""

    BRIEF = "brief"
    """The first Turn of a work item's run placed fresh, or of a job's run."""
    PERSON = "person"
    """A Turn with an author: a chat's message, the chat's brief before a
    person's words among them, and a service user's call."""
    CONTINUATION = "continuation"
    """The first Turn of a new run on a conversation whose run's documents
    all closed (F26.7)."""
    CLARIFICATION = "clarification"
    """The first Turn of a clarification run, the pass's questions to the
    writer (DB decision 63)."""
    RESUME = "resume"
    """The Turn a person's Resume of a stopped or failed work item sends."""
    NUDGE = "nudge"
    """The owed nudge (DB 232)."""
    FOLLOW_UP = "follow_up"
    """The server's follow-up for saves still held at a turn's end (F79)."""
    CARRY_ON = "carry_on"
    """The Turn the relay sends after it re-created a controller session
    that was gone (§9.6)."""
    WAIT_RUN = "wait_run"
    """The first Turn of a wait's run, a follow-up on the previous run's
    conversation or the full brief."""


class HoldKind(StrEnum):
    """A kind of reason Pilot keeps a Session waiting (DB §2.11): the gate's
    reasons, one to one (`start_gate.held_reason`), in the gate's order."""

    WEEK_HALT = "week_halt"
    """The week's usage halt, which itself stays computed and unstored."""
    FIVE_HOUR_HALT = "five_hour_halt"
    """The five-hour usage halt."""
    PAUSE = "pause"
    """The Session's project is paused."""
    STORE_UPDATE = "store_update"
    """A Store Update is unlifted."""
    OUTAGE = "outage"
    """The controller is unreachable, as the process that held the Session
    met it."""
    SLOT = "slot"
    """No slot is free for a work item."""
    QUEUE = "queue"
    """A job waits behind another job of its project."""
    CONVERSATION = "conversation"
    """A work item waits while another run on its conversation, in its
    environment, is running or starting."""


class FavouriteMenu(StrEnum):
    """A kind of list a dimension is a favourite in (DB §2.11): the
    dashboard's By or its Color."""

    BY = "by"
    COLOR = "color"


class Origin(StrEnum):
    """A kind of place a stored view or ratio of the dashboard comes from
    (DB §2.11; decision 80). Pilot's own and the workflow's are managed: no
    User changes a row of them (DB 601), which a row's `system` carries."""

    PILOT = "pilot"
    """Shipped with Pilot and changed by its release."""
    WORKFLOW = "workflow"
    """Loaded from the workflow plugin's file and changed by a load."""
    PERSON = "person"
    """Made by a person and changed by anyone."""


class NumberFormat(StrEnum):
    """A kind of way a measure's numbers are written (DB §2.11; decision
    86): the catalogue gives each of its figures and ratios one, and a
    person picks one for a Custom Ratio they make. How each is written is
    the screen's."""

    USD = "usd"
    """A dollar amount."""
    TOKENS = "tokens"
    COUNT = "count"
    SECONDS = "seconds"
    """A duration."""
    SHARE = "share"
    """A percentage."""


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
ATTACHMENT_SOURCE = _enum_type(AttachmentSource, "attachment_source")
SESSION_STATE = _enum_type(SessionState, "session_state")
RECORD_KIND = _enum_type(RecordKind, "record_kind")
CHAT_KIND = _enum_type(ChatKind, "chat_kind")
CLOSE_CAUSE = _enum_type(CloseCause, "close_cause")
EFFECT_KIND = _enum_type(EffectKind, "effect_kind")
TASK_STATUS = _enum_type(TaskStatus, "task_status")
USAGE_WINDOW = _enum_type(UsageWindow, "usage_window")
PROGRESS_STATE = _enum_type(ProgressState, "progress_state")
TURN_CAUSE = _enum_type(TurnCause, "turn_cause")
HOLD_KIND = _enum_type(HoldKind, "hold_kind")
FAVOURITE_MENU = _enum_type(FavouriteMenu, "favourite_menu")
ORIGIN = _enum_type(Origin, "origin")
NUMBER_FORMAT = _enum_type(NumberFormat, "number_format")

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
    ATTACHMENT_SOURCE,
    SESSION_STATE,
    RECORD_KIND,
    CHAT_KIND,
    CLOSE_CAUSE,
    EFFECT_KIND,
    TASK_STATUS,
    USAGE_WINDOW,
    PROGRESS_STATE,
    TURN_CAUSE,
    HOLD_KIND,
    FAVOURITE_MENU,
    ORIGIN,
    NUMBER_FORMAT,
)


class ItemKind(db.Model):  # type: ignore[name-defined]
    """A kind of timeline entry; `form` says which subtype its Item is."""

    __tablename__ = "item_kinds"
    __table_args__ = (
        CheckConstraint(
            "form IN ('prose', 'work', 'wait', 'debrief_notice')",
            name="ck_item_kinds_form",
        ),
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


class TokenKind(db.Model):  # type: ignore[name-defined]
    """A kind of token a model call counts: read fresh, written to the prompt
    cache, read from it, written by the model, and a cache write by its
    lifetime, five minutes or an hour.

    `within_code` is the coarser kind a finer one is part of. A Turn's Token
    Counts take the kinds within none; a Call's tokens, a column each on its
    row, the kinds nothing is within (DB 547).
    """

    __tablename__ = "token_kinds"
    __table_args__ = (
        CheckConstraint("within_code <> code", name="ck_token_kinds_within"),
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    within_code: Mapped[str | None] = mapped_column(ForeignKey("token_kinds.code"))
