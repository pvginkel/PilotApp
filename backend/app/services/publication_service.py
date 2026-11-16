"""A collector's publication of one transcript, written into the record (DB
decisions 79 and 81; F152.3, F152.4).

A whole publication leaves Pilot holding what the call says of the
Transcript, in the caller's transaction, and writes only the rows that
differ. A row keeps its identity, and whatever Pilot set on it, wherever the
call names the same fact again: a Call by its `message_id`, a Tool Call by
its `tool_use_id`, a Launch by its place among its Transcript's Launches, a
Prompt, a Hook Run, a Compaction, an Event and a Context Part by their place
under their parent. A row's place is its rank by `id` among its parent's
rows: a row is only ever added after the last and removed from the end.

What Pilot holds of the Transcript that the call no longer names goes, with
what hangs on it: Pilot follows the file (DB decision 81 point 4; F152.17).
The Transcript itself never goes (F119.2).

An appended publication, of a file that grew and nothing else, is the same
write from its boundary on (DB decision 81 point 1; F152.15): what Pilot
holds before the boundary's places is neither read as the call's nor
written. It is taken only where it continues what Pilot holds (`_continued`),
so it removes no Launch, Prompt, Compaction or Call; any other is refused,
for the collector to publish the transcript whole.

Publications of one conversation, its main thread's and its sub-agents',
take turns, so that a sub-agent's thread finds its main thread and its
spawning Tool Call whichever comes first.
"""

import hmac
import logging
import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, get_args

from sqlalchemy import (
    BigInteger,
    Integer,
    Select,
    any_,
    cast,
    delete,
    func,
    literal,
    select,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, aliased

from app.app_config import AppSettings
from app.exceptions import (
    AuthenticationException,
    CollectorProtocolUnsupportedException,
    PublicationInvalidException,
    PublicationNotAppendableException,
)
from app.models import (
    Call,
    Compaction,
    CompactionTrigger,
    Component,
    ComponentVersion,
    ContextPart,
    ContextPartKind,
    DenialKind,
    Environment,
    Event,
    EventKind,
    HookRun,
    Launch,
    LaunchComponent,
    MissCause,
    Model,
    Prompt,
    PromptSource,
    Repository,
    StopReason,
    Tool,
    ToolCall,
    Transcript,
)
from app.models.call import RECORDED_ELSEWHERE
from app.schemas.publication import (
    CallTokenKind,
    PublicationSchema,
    PublishedAppendedSchema,
    PublishedBoundarySchema,
    PublishedCallSchema,
    PublishedCompactionSchema,
    PublishedLaunchSchema,
)
from app.services.advisory_turn import turn_key

logger = logging.getLogger(__name__)

COLLECTOR_PROTOCOL_MIN = 1
"""The oldest protocol version the server takes of a collector."""

COLLECTOR_PROTOCOL_MAX = 1
"""The newest protocol version the server takes of a collector. A change to a
request or response shape of the collector's routes bumps it, and
`COLLECTOR_PROTOCOL_MIN` with it when the server cannot serve the old
collector."""

_VERSION = re.compile(r"[0-9]+")

PUBLICATION_LOCK = 247
"""The first key of a conversation's turn (`advisory_turn`); the second is
drawn from Claude Code's id of its main thread."""

COLLECTOR = "collector"
"""The Component a Transcript is read by."""

HOOK = "hook"
"""The Denial Kind of a Tool Call a hook blocked."""

_TOKEN_KINDS: tuple[CallTokenKind, ...] = get_args(CallTokenKind)

_WHOLE = PublishedBoundarySchema(call=1, launch=1, prompt=1, compaction=1)
"""Where a whole call starts: at the file's first of each."""

type _Version = tuple[str, str]
"""A Component Version as a call names it: its Component's code and its
version."""

type _Surplus = dict[type[Any], list[Any]]
"""The held rows past the last the call names under their parent, by
entity."""


def _name(publication: PublicationSchema) -> str:
    """The Transcript as a message names it: its conversation, and its
    sub-agent where it is one's thread."""
    if publication.agent_id is None:
        return publication.session_id
    return f"{publication.session_id}/{publication.agent_id}"


def _faults(publication: PublicationSchema) -> list[str]:
    """What in the call contradicts the call itself or the record's rules for
    a Transcript (DB 534, 536, 541, 542, 545, 560, 587), each in a line. A
    predecessor an appended call does not carry is left to `_continued`."""
    found: list[str] = []
    appended = publication.appended
    boundary = _WHOLE if appended is None else appended.boundary
    if appended is not None and publication.file_size <= appended.builds_on.file_size:
        found.append("an appended call's file is no larger than the one it builds on")
    if publication.agent_id is None:
        found.extend(
            f"a main thread has no `{fact}`"
            for fact in ("agent_type", "description", "spawned_by")
            if getattr(publication, fact) is not None
        )
    else:
        if publication.environment is not None:
            found.append("a sub-agent's thread is hosted by no environment")
        if publication.launches:
            found.append("a sub-agent's thread has no launches")

    released: dict[_Version, datetime] = {}
    for place, launch in enumerate(publication.launches, start=1):
        components: set[str] = set()
        for used in launch.components:
            if used.component in components:
                found.append(
                    f"launch {place}: two versions of the component `{used.component}`"
                )
            components.add(used.component)
            if used.released_at is None:
                continue
            version = (used.component, used.version)
            if released.setdefault(version, used.released_at) != used.released_at:
                found.append(
                    f"version `{used.version}` of the component"
                    f" `{used.component}` is given two release times"
                )

    prompts = boundary.prompt - 1
    prompts += sum(len(launch.prompts) for launch in publication.launches)
    compactions = boundary.compaction - 1 + len(publication.compactions)
    carried = {call.message_id for call in publication.calls}
    earlier: set[str] = set()
    requested: set[str] = set()
    servers: dict[str, str | None] = {}
    errors: dict[str, bool] = {}
    for call in publication.calls:
        named = f"call `{call.message_id}`"
        if call.message_id in earlier:
            found.append(f"{named}: named twice")
        if call.prompt is not None and call.prompt > prompts:
            found.append(
                f"{named}: `prompt` {call.prompt} is past the transcript's"
                f" {prompts} prompts"
            )
        if call.compaction is not None and call.compaction > compactions:
            found.append(
                f"{named}: `compaction` {call.compaction} is past the transcript's"
                f" {compactions} compactions"
            )
        if (
            call.predecessor is not None
            and call.predecessor not in earlier
            and (appended is None or call.predecessor in carried)
        ):
            found.append(
                f"{named}: `predecessor` `{call.predecessor}` is no earlier call"
            )
        if call.requested_model == call.model:
            found.append(f"{named}: `requested_model` is its `model`")
        earlier.add(call.message_id)
        for tool_call in call.tool_calls:
            asked = f"{named}: tool call `{tool_call.tool_use_id}`"
            if tool_call.tool_use_id in requested:
                found.append(f"{asked}: named twice")
            requested.add(tool_call.tool_use_id)
            if tool_call.exit_code == 0:
                found.append(f"{asked}: `exit_code` is 0")
            if tool_call.denial_kind == HOOK and not tool_call.failed:
                found.append(f"{asked}: denied by a hook and not `failed`")
            server = servers.setdefault(tool_call.tool, tool_call.mcp_server)
            if server != tool_call.mcp_server:
                found.append(
                    f"{asked}: the tool `{tool_call.tool}` is given two `mcp_server`s"
                )
        for place, event in enumerate(call.events, start=1):
            marked = f"{named}: event {place}"
            if event.kind in RECORDED_ELSEWHERE:
                found.append(
                    f"{marked}: an occurrence of the kind `{event.kind}` is no event"
                )
            if errors.setdefault(event.kind, event.is_error) != event.is_error:
                found.append(
                    f"{marked}: the kind `{event.kind}` is given as an error and"
                    " as none"
                )
    return found


class PublicationService:
    """Admits a collector's call, and writes its publication into the record
    on the caller's transaction."""

    def __init__(self, db: Session, app_settings: AppSettings) -> None:
        self.db = db
        self.app_settings = app_settings

    def admit(self, authorization: str | None, protocol: str | None) -> None:
        """Let a collector's call through, its two headers' values given.

        Refused, in this order: without the collector's bearer, and always
        while `COLLECTOR_TOKEN` is empty; in a protocol version outside the
        accepted range. A refused call touches nothing.

        Raises:
            AuthenticationException: the call does not carry the bearer.
            CollectorProtocolUnsupportedException: the version is outside
                the range, or the call names none.
        """
        token = self.app_settings.collector_token
        if not token or not hmac.compare_digest(
            (authorization or "").encode(), f"Bearer {token}".encode()
        ):
            raise AuthenticationException(
                "Cannot take the collector's call because the request does not"
                " carry the collector's bearer"
            )
        if (
            protocol is None
            or not _VERSION.fullmatch(protocol)
            or not COLLECTOR_PROTOCOL_MIN <= int(protocol) <= COLLECTOR_PROTOCOL_MAX
        ):
            raise CollectorProtocolUnsupportedException(
                protocol, COLLECTOR_PROTOCOL_MIN, COLLECTOR_PROTOCOL_MAX
            )

    def publish(self, publication: PublicationSchema) -> Transcript:
        """Take a publication of one Transcript, whole or appended, and
        return its row.

        After a whole one its `replayed_size` is its `file_size` (DB 605). A
        Call Pilot held of it that the call no longer names is removed with
        what hangs on it, and their number logged. After an appended one
        Pilot holds what the call carries from its boundary on, what lies
        before it as it was, and `replayed_size` as it stood.

        An Environment, a Repository, a Component Version and a reference
        code the call names that Pilot has no row for are written, the code
        as its own name and with what the call says of its category; one
        Pilot has met stands as it is.

        Raises:
            PublicationInvalidException: the call has faults; nothing is
                written.
            PublicationNotAppendableException: an appended call does not
                continue what Pilot holds of the Transcript; nothing is
                written.
        """
        found = _faults(publication)
        if found:
            raise PublicationInvalidException(_name(publication), found)
        self.db.execute(
            select(
                func.pg_advisory_xact_lock(
                    cast(literal(PUBLICATION_LOCK), Integer),
                    cast(literal(turn_key(publication.session_id.encode())), Integer),
                )
            )
        )
        boundary = _WHOLE
        ids: dict[str, int] = {}
        if publication.appended is not None:
            boundary = publication.appended.boundary
            ids = self._continued(publication, publication.appended)
        self._meet_references(publication)
        versions = self._versions(publication)
        thread = self._thread(
            publication, versions[COLLECTOR, publication.collector.version]
        )
        surplus: _Surplus = {}
        prompts = self._launches(
            thread, publication.launches, versions, surplus, boundary
        )
        compactions = self._compactions(
            thread, publication.compactions, surplus, boundary
        )
        calls = publication.calls
        stale = self._calls(thread, calls, prompts, compactions, boundary, ids)
        self._tool_calls(thread, calls, ids, boundary)
        # Must follow `_tool_calls`, which moves a Tool Call the call names
        # off a Call that goes here, and `_calls`, after which no Call the
        # call names points at a Call, a Prompt or a Compaction that goes.
        self._lose_calls(publication, stale)
        for entity, gone in surplus.items():
            self._remove(entity, [row.id for row in gone])
        self._hung(
            Event,
            thread,
            ids,
            boundary,
            {
                call.message_id: [
                    {"kind_code": event.kind, "at": event.at, "detail": event.detail}
                    for event in call.events
                ]
                for call in calls
            },
        )
        self._hung(
            ContextPart,
            thread,
            ids,
            boundary,
            {
                call.message_id: [
                    {
                        "kind_code": part.kind,
                        "name": part.name,
                        "characters": part.characters,
                    }
                    for part in call.context_parts
                ]
                for call in calls
            },
        )
        self._join(publication.session_id)
        return thread

    def _continued(
        self, publication: PublicationSchema, appended: PublishedAppendedSchema
    ) -> dict[str, int]:
        """Check that an appended call continues what Pilot holds of its
        Transcript, and return the id of each Call before its boundary that
        one of its Calls names as its predecessor, by `message_id`.

        It does where Pilot holds the Transcript as the call builds on it,
        at that size and time and read under that collector's version; where
        Pilot holds a row at every place before the boundary's; and where
        the call carries every Launch, Prompt, Compaction and Call Pilot
        holds from there on, and no Call or Tool Call Pilot holds before.
        The write that follows then removes none of those and touches
        nothing before the boundary.

        Raises:
            PublicationNotAppendableException: it does not; nothing is
                written.
        """
        name = _name(publication)
        base = appended.builds_on
        held = self.db.execute(
            select(
                Transcript.id,
                Transcript.file_size,
                Transcript.file_modified_at,
                ComponentVersion.version,
            )
            .join(ComponentVersion, ComponentVersion.id == Transcript.read_under_id)
            .where(
                Transcript.session_id == publication.session_id,
                Transcript.agent_id.is_not_distinct_from(publication.agent_id),
            )
        ).one_or_none()
        if held is None:
            raise PublicationNotAppendableException(name, ["Pilot does not hold it"])
        if (held.file_size, held.file_modified_at, held.version) != (
            base.file_size,
            base.file_modified_at,
            base.collector,
        ):
            raise PublicationNotAppendableException(
                name,
                [
                    "Pilot holds it at another size, time or collector's version"
                    " than the call builds on"
                ],
            )

        boundary = appended.boundary
        causes = self._launch_gaps(held.id, publication.launches, boundary)
        causes += self._compaction_gaps(held.id, publication.compactions, boundary)
        earlier = self._call_gaps(held.id, publication.calls, boundary, causes)
        if causes:
            raise PublicationNotAppendableException(name, causes)
        return earlier

    def _launch_gaps(
        self,
        thread_id: uuid.UUID,
        launches: list[PublishedLaunchSchema],
        boundary: PublishedBoundarySchema,
    ) -> list[str]:
        """Why an appended call's Launches and their Prompts do not continue
        the Transcript's as Pilot holds them, each in a line."""
        held = self.db.scalars(
            select(Launch.id)
            .where(Launch.transcript_id == thread_id)
            .order_by(Launch.id)
        ).all()
        received: dict[int, int] = dict(
            self.db.execute(
                select(Prompt.launch_id, func.count())
                .where(Prompt.transcript_id == thread_id)
                .group_by(Prompt.launch_id)
            ).all()
        )
        before = held[: boundary.launch - 1]
        since = held[boundary.launch - 1 :]
        if len(before) < boundary.launch - 1:
            return [
                f"the boundary's `launch` is {boundary.launch}, and Pilot holds"
                f" {len(held)} launches"
            ]
        if len(launches) < len(since):
            return [
                f"the call carries {len(launches)} launches from its boundary on,"
                f" and Pilot holds {len(since)}"
            ]
        # The Prompts the boundary's Launch keeps: those before the
        # boundary's that lie under no Launch before it.
        kept = boundary.prompt - 1 - sum(received.get(row, 0) for row in before)
        if not 0 <= kept <= (received.get(since[0], 0) if since else 0):
            return [
                f"the boundary's `prompt` is {boundary.prompt}, which is neither"
                " a prompt Pilot holds under the boundary's launch nor the next"
                " under it"
            ]
        return [
            f"launch {boundary.launch + place}: the call carries fewer prompts"
            " than Pilot holds under it"
            for place, launch_id in enumerate(since)
            if len(launches[place].prompts) + (0 if place else kept)
            < received.get(launch_id, 0)
        ]

    def _compaction_gaps(
        self,
        thread_id: uuid.UUID,
        compactions: list[PublishedCompactionSchema],
        boundary: PublishedBoundarySchema,
    ) -> list[str]:
        """Why an appended call's Compactions do not continue the
        Transcript's as Pilot holds them, each in a line."""
        held = self.db.scalars(
            select(func.count())
            .select_from(Compaction)
            .where(Compaction.transcript_id == thread_id)
        ).one()
        since = held - (boundary.compaction - 1)
        if since < 0:
            return [
                f"the boundary's `compaction` is {boundary.compaction}, and Pilot"
                f" holds {held} compactions"
            ]
        if len(compactions) < since:
            return [
                f"the call carries {len(compactions)} compactions from its"
                f" boundary on, and Pilot holds {since}"
            ]
        return []

    def _call_gaps(
        self,
        thread_id: uuid.UUID,
        calls: list[PublishedCallSchema],
        boundary: PublishedBoundarySchema,
        causes: list[str],
    ) -> dict[str, int]:
        """Add to `causes` why an appended call's Calls and their Tool Calls
        do not continue the Transcript's as Pilot holds them, each in a line;
        the id of each Call before the boundary that one of them names as
        its predecessor, by `message_id`."""
        carried = {call.message_id for call in calls}
        outside = {
            call.predecessor for call in calls if call.predecessor is not None
        } - carried
        held = self.db.execute(
            select(Call.message_id, Call.id, Call.position).where(
                Call.transcript_id == thread_id,
                (Call.position >= boundary.call)
                | Call.message_id.in_(sorted(carried | outside)),
            )
        ).all()
        before = self.db.scalars(
            select(func.count())
            .select_from(Call)
            .where(Call.transcript_id == thread_id, Call.position < boundary.call)
        ).one()
        if before < boundary.call - 1:
            causes.append(
                f"the boundary's `call` is {boundary.call}, and Pilot holds"
                f" {before} calls"
            )
        lacking = sum(
            row.position >= boundary.call and row.message_id not in carried
            for row in held
        )
        if lacking:
            causes.append(
                f"the call lacks {lacking} of the calls Pilot holds from its"
                " boundary on"
            )
        earlier: dict[str, int] = {
            row.message_id: row.id for row in held if row.position < boundary.call
        }
        for call in calls:
            if call.message_id in earlier:
                causes.append(
                    f"call `{call.message_id}`: Pilot holds it before the boundary"
                )
            if call.predecessor in outside and call.predecessor not in earlier:
                causes.append(
                    f"call `{call.message_id}`: `predecessor` `{call.predecessor}`"
                    " is no call Pilot holds before the boundary"
                )

        requested = [
            tool_call.tool_use_id for call in calls for tool_call in call.tool_calls
        ]
        if requested:
            causes.extend(
                f"tool call `{tool_use_id}`: Pilot holds it under a call before"
                " the boundary"
                for tool_use_id in self.db.scalars(
                    select(ToolCall.tool_use_id)
                    .join(Call, Call.id == ToolCall.call_id)
                    .where(
                        ToolCall.transcript_id == thread_id,
                        Call.position < boundary.call,
                        ToolCall.tool_use_id.in_(requested),
                    )
                    .order_by(ToolCall.id)
                )
            )
        return {
            message_id: earlier[message_id] for message_id in outside & earlier.keys()
        }

    def _meet_references(self, publication: PublicationSchema) -> None:
        """A row for each reference code the call names that Pilot has not
        met. The entities in one order and each one's codes in theirs, so
        that two publications wait on each other one way round only."""
        launches = publication.launches
        calls = publication.calls
        requested = [tool_call for call in calls for tool_call in call.tool_calls]
        events = [event for call in calls for event in call.events]
        self._meet(
            Component,
            [COLLECTOR]
            + [used.component for launch in launches for used in launch.components],
        )
        self._meet(
            CompactionTrigger,
            [compaction.trigger for compaction in publication.compactions],
        )
        self._meet(MissCause, [call.miss_cause for call in calls])
        self._meet(
            Model,
            [call.model for call in calls] + [call.requested_model for call in calls],
        )
        self._meet(
            PromptSource,
            [prompt.source for launch in launches for prompt in launch.prompts],
        )
        self._meet(StopReason, [call.stop_reason for call in calls])
        self._meet(
            ContextPartKind,
            [part.kind for call in calls for part in call.context_parts],
        )
        self._meet(DenialKind, [tool_call.denial_kind for tool_call in requested])
        self._meet(
            EventKind,
            [event.kind for event in events],
            {event.kind: {"is_error": event.is_error} for event in events},
        )
        self._meet(
            Tool,
            [tool_call.tool for tool_call in requested],
            {
                tool_call.tool: {"mcp_server": tool_call.mcp_server}
                for tool_call in requested
            },
        )

    def _meet(
        self,
        entity: type[Any],
        codes: Sequence[str | None],
        facts: Mapping[str, dict[str, Any]] | None = None,
    ) -> None:
        """Write the reference entity's row of each code Pilot has not met,
        named by its code, with the `facts` the call gives of its category."""
        named = {code for code in codes if code is not None}
        if not named:
            return
        met: set[str] = set(
            self.db.scalars(select(entity.code).where(entity.code.in_(named)))
        )
        unmet = sorted(named - met)
        if unmet:
            self.db.execute(
                pg_insert(entity).on_conflict_do_nothing(),
                [
                    {"code": code, "name": code} | (facts[code] if facts else {})
                    for code in unmet
                ],
            )

    def _versions(self, publication: PublicationSchema) -> dict[_Version, int]:
        """The id of each Component Version the call names. One Pilot has not
        met is written, and one it has takes the release time the call gives."""
        collector = publication.collector
        named: dict[_Version, datetime | None] = {
            (COLLECTOR, collector.version): collector.released_at
        }
        for launch in publication.launches:
            for used in launch.components:
                version = (used.component, used.version)
                named[version] = used.released_at or named.get(version)
        held = self._held_versions(named)
        unmet = sorted(named.keys() - held.keys())
        if unmet:
            self.db.execute(
                pg_insert(ComponentVersion).on_conflict_do_nothing(
                    index_elements=["component_code", "version"]
                ),
                [
                    {
                        "component_code": component,
                        "version": version,
                        "released_at": named[component, version],
                    }
                    for component, version in unmet
                ],
            )
            held = self._held_versions(named)
        for version, released_at in named.items():
            if released_at is not None:
                held[version].released_at = released_at
        return {version: row.id for version, row in held.items()}

    def _held_versions(
        self, named: dict[_Version, datetime | None]
    ) -> dict[_Version, ComponentVersion]:
        rows = self.db.scalars(
            select(ComponentVersion).where(
                tuple_(ComponentVersion.component_code, ComponentVersion.version).in_(
                    list(named)
                )
            )
        )
        return {(row.component_code, row.version): row for row in rows}

    def _repository(self, name: str) -> int:
        """The id of the Repository of that checkout's name, written where
        Pilot has none."""
        held = select(Repository.id).where(Repository.name == name)
        repository_id = self.db.scalar(held)
        if repository_id is None:
            self.db.execute(
                pg_insert(Repository)
                .values(name=name)
                .on_conflict_do_nothing(index_elements=["name"])
            )
            repository_id = self.db.scalars(held).one()
        return repository_id

    def _environment(self, env_id: str) -> None:
        """Write the Environment of that id where Pilot has none: named by
        its id, as the controller's report names one with no name
        (`environment_service.reported_columns`), until the fleet consumer
        updates it."""
        held = self.db.scalar(select(Environment.id).where(Environment.id == env_id))
        if held is None:
            self.db.execute(
                pg_insert(Environment)
                .values(id=env_id, name=env_id, exempt=False)
                .on_conflict_do_nothing(index_elements=["id"])
            )

    def _thread(self, publication: PublicationSchema, read_under_id: int) -> Transcript:
        """The Transcript's row as the call has it, its `replayed_size` its
        file's size after a whole call alone (DB 605). A sub-agent's thread
        is under its main thread where Pilot holds that one, and a main
        thread first held takes the sub-agents' threads that came before it."""
        facts: dict[str, Any] = {
            "working_directory": publication.working_directory,
            "repository_id": None,
            "environment_id": None,
            "spawned_by_tool_use_id": publication.spawned_by,
            "agent_type": publication.agent_type,
            "description": publication.description,
            "file_size": publication.file_size,
            "file_modified_at": publication.file_modified_at,
            "collected_at": datetime.now(UTC),
            "read_under_id": read_under_id,
        }
        if publication.appended is None:
            facts["replayed_size"] = publication.file_size
        if publication.repository is not None:
            facts["repository_id"] = self._repository(publication.repository)
        if publication.environment is not None:
            self._environment(publication.environment)
            facts["environment_id"] = publication.environment
        if publication.agent_id is not None:
            facts["main_id"] = self.db.scalar(
                select(Transcript.id).where(
                    Transcript.session_id == publication.session_id,
                    Transcript.agent_id.is_(None),
                )
            )

        thread = self.db.scalars(
            select(Transcript).where(
                Transcript.session_id == publication.session_id,
                Transcript.agent_id.is_not_distinct_from(publication.agent_id),
            )
        ).one_or_none()
        if thread is not None:
            _set(thread, facts)
            self.db.flush()
            return thread
        thread = Transcript(
            session_id=publication.session_id, agent_id=publication.agent_id, **facts
        )
        self.db.add(thread)
        self.db.flush()
        if publication.agent_id is None:
            self.db.execute(
                update(Transcript)
                .where(
                    Transcript.session_id == publication.session_id,
                    Transcript.agent_id.is_not(None),
                    Transcript.main_id.is_(None),
                )
                .values(main_id=thread.id)
            )
        return thread

    def _launches(
        self,
        thread: Transcript,
        launches: list[PublishedLaunchSchema],
        versions: dict[_Version, int],
        surplus: _Surplus,
        boundary: PublishedBoundarySchema,
    ) -> list[Prompt]:
        """The Transcript's Launches from the boundary's on as the call has
        them, each with its versions, its Prompts and their Hook Runs, the
        first with its Prompts from the boundary's on; the rows of all the
        Transcript's Prompts in the file's order. A held Launch, Prompt or
        Hook Run past the call's last is left to `surplus`."""
        started = self.db.scalars(
            select(Launch).where(Launch.transcript_id == thread.id).order_by(Launch.id)
        ).all()
        before = started[: boundary.launch - 1]
        rows = self._placed(
            started[boundary.launch - 1 :],
            [
                {"started_at": launch.started_at, "ended_at": launch.ended_at}
                for launch in launches
            ],
            Launch,
            surplus,
            transcript_id=thread.id,
        )
        self.db.flush()

        used_by: dict[int, dict[str, LaunchComponent]] = {}
        for component in self.db.scalars(
            select(LaunchComponent).where(
                LaunchComponent.launch_id.in_([row.id for row in rows])
            )
        ):
            used_by.setdefault(component.launch_id, {})[component.component_code] = (
                component
            )
        for row, launch in zip(rows, launches, strict=True):
            ran_with = used_by.get(row.id, {})
            named = {used.component for used in launch.components}
            for code in ran_with.keys() - named:
                self.db.delete(ran_with[code])
            for used in launch.components:
                version_id = versions[used.component, used.version]
                held = ran_with.get(used.component)
                if held is None:
                    self.db.add(
                        LaunchComponent(
                            launch_id=row.id,
                            component_version_id=version_id,
                            component_code=used.component,
                        )
                    )
                else:
                    held.component_version_id = version_id

        received = self._grouped(
            select(Prompt).where(Prompt.transcript_id == thread.id).order_by(Prompt.id),
            "launch_id",
        )
        prompts = [prompt for row in before for prompt in received.get(row.id, [])]
        # The Prompts the boundary's Launch keeps: those before the
        # boundary's that lie under no Launch before it.
        kept = boundary.prompt - 1 - len(prompts)
        carried: list[Prompt] = []
        for row, launch in zip(rows, launches, strict=True):
            under = received.get(row.id, [])
            if row is rows[0]:
                prompts += under[:kept]
                under = under[kept:]
            carried += self._placed(
                under,
                [
                    {
                        "received_at": prompt.received_at,
                        "source_code": prompt.source,
                        "characters": prompt.characters,
                    }
                    for prompt in launch.prompts
                ],
                Prompt,
                surplus,
                transcript_id=thread.id,
                launch_id=row.id,
            )
        self.db.flush()

        ran = self._grouped(
            select(HookRun)
            .where(HookRun.prompt_id.in_([row.id for row in carried]))
            .order_by(HookRun.id),
            "prompt_id",
        )
        published = [prompt for launch in launches for prompt in launch.prompts]
        for prompt_row, prompt in zip(carried, published, strict=True):
            self._placed(
                ran.get(prompt_row.id, []),
                [run.model_dump() for run in prompt.hook_runs],
                HookRun,
                surplus,
                prompt_id=prompt_row.id,
            )
        self.db.flush()
        return prompts + carried

    def _compactions(
        self,
        thread: Transcript,
        compactions: list[PublishedCompactionSchema],
        surplus: _Surplus,
        boundary: PublishedBoundarySchema,
    ) -> list[Compaction]:
        """The Transcript's Compactions from the boundary's on as the call
        has them; the rows of all its Compactions in the file's order. A held
        one past the call's last is left to `surplus`."""
        held = self.db.scalars(
            select(Compaction)
            .where(Compaction.transcript_id == thread.id)
            .order_by(Compaction.id)
        ).all()
        rows = self._placed(
            held[boundary.compaction - 1 :],
            [
                {
                    "at": compaction.at,
                    "trigger_code": compaction.trigger,
                    "tokens_before": compaction.tokens_before,
                    "tokens_after": compaction.tokens_after,
                    "duration_ms": compaction.duration_ms,
                }
                for compaction in compactions
            ],
            Compaction,
            surplus,
            transcript_id=thread.id,
        )
        self.db.flush()
        return [*held[: boundary.compaction - 1], *rows]

    def _calls(
        self,
        thread: Transcript,
        calls: list[PublishedCallSchema],
        prompts: list[Prompt],
        compactions: list[Compaction],
        boundary: PublishedBoundarySchema,
        ids: dict[str, int],
    ) -> list[int]:
        """The Transcript's Calls from the boundary on as the call has them,
        their `position` their place in the file. `ids`, which comes with
        the Calls before the boundary that they name, gains the id of each
        Call the call names, by its `message_id`; returned are the ids of
        the Calls Pilot held from the boundary on that it no longer names. A
        Call Pilot has not met takes an id before it is written, so that one
        written beside it names it as its predecessor."""
        held = {
            row.message_id: row
            for row in self.db.scalars(
                select(Call).where(
                    Call.transcript_id == thread.id, Call.position >= boundary.call
                )
            )
        }
        named = {call.message_id for call in calls}
        unmet = [call.message_id for call in calls if call.message_id not in held]
        ids.update(
            (message_id, row.id)
            for message_id, row in held.items()
            if message_id in named
        )
        if unmet:
            ids.update(
                zip(
                    unmet,
                    self.db.scalars(
                        select(
                            func.nextval(func.pg_get_serial_sequence("calls", "id"))
                        ).select_from(func.generate_series(1, len(unmet)))
                    ),
                    strict=True,
                )
            )

        met: list[tuple[Call, dict[str, Any]]] = []
        for position, call in enumerate(calls, start=boundary.call):
            facts: dict[str, Any] = {
                "position": position,
                "prompt_id": prompts[call.prompt - 1].id if call.prompt else None,
                "predecessor_id": ids[call.predecessor] if call.predecessor else None,
                "compaction_id": (
                    compactions[call.compaction - 1].id if call.compaction else None
                ),
                "sent_at": call.sent_at,
                "completed_at": call.completed_at,
                "model_code": call.model,
                "requested_model_code": call.requested_model,
                "effort": call.effort,
                "stop_reason_code": call.stop_reason,
                "thinking_tokens": call.thinking_tokens,
                "attributed_skill": call.attributed_skill,
                "attributed_plugin": call.attributed_plugin,
                "miss_cause_code": call.miss_cause,
            }
            for kind in _TOKEN_KINDS:
                facts[f"{kind}_tokens"] = call.tokens.get(kind, 0)
            row = held.get(call.message_id)
            if row is None:
                self.db.add(
                    Call(
                        id=ids[call.message_id],
                        transcript_id=thread.id,
                        message_id=call.message_id,
                        **facts,
                    )
                )
            else:
                met.append((row, facts))
        # A held Call's predecessor may be one written here: the new rows
        # stand before a held one names them.
        self.db.flush()
        for row, facts in met:
            _set(row, facts)
        self.db.flush()
        return [row.id for message_id, row in held.items() if message_id not in named]

    def _lose_calls(self, publication: PublicationSchema, lost: list[int]) -> None:
        """Remove the Calls the call no longer names, with what hangs on
        them, and log their number (DB decision 81 point 4)."""
        if lost:
            self._remove(Call, lost)
            logger.warning(
                "Transcript %s no longer has %d of the calls Pilot held",
                _name(publication),
                len(lost),
            )

    def _tool_calls(
        self,
        thread: Transcript,
        calls: list[PublishedCallSchema],
        ids: dict[str, int],
        boundary: PublishedBoundarySchema,
    ) -> None:
        """The Tool Calls the call names, each under the Call that requested
        it; one held under a Call from the boundary on that it no longer
        names is removed."""
        held = {
            row.tool_use_id: row
            for row in self.db.scalars(
                select(ToolCall)
                .join(Call, Call.id == ToolCall.call_id)
                .where(
                    ToolCall.transcript_id == thread.id,
                    Call.position >= boundary.call,
                )
            )
        }
        for call in calls:
            for requested in call.tool_calls:
                facts: dict[str, Any] = {
                    "call_id": ids[call.message_id],
                    "tool_code": requested.tool,
                    "first_argument": requested.first_argument,
                    "requested_at": requested.requested_at,
                    "returned_at": requested.returned_at,
                    "failed": requested.failed,
                    "exit_code": requested.exit_code,
                    "interrupted": requested.interrupted,
                    "denial_kind_code": requested.denial_kind,
                    "result_characters": requested.result_characters,
                    "saved_characters": requested.saved_characters,
                }
                row = held.get(requested.tool_use_id)
                if row is None:
                    self.db.add(
                        ToolCall(
                            transcript_id=thread.id,
                            tool_use_id=requested.tool_use_id,
                            **facts,
                        )
                    )
                else:
                    _set(row, facts)
        self.db.flush()
        named = {
            requested.tool_use_id for call in calls for requested in call.tool_calls
        }
        self._remove(
            ToolCall,
            [row.id for tool_use_id, row in held.items() if tool_use_id not in named],
        )

    def _hung(
        self,
        entity: type[Any],
        thread: Transcript,
        ids: dict[str, int],
        boundary: PublishedBoundarySchema,
        facts: dict[str, list[dict[str, Any]]],
    ) -> None:
        """The rows of `entity`, an Event's or a Context Part's, under each
        Call as `facts` has them by the Call's `message_id`, in the file's
        order; a held one past the last its Call has is removed."""
        held: dict[int, list[Any]] = self._grouped(
            select(entity)
            .join(Call, Call.id == entity.call_id)
            .where(Call.transcript_id == thread.id, Call.position >= boundary.call)
            .order_by(entity.id),
            "call_id",
        )
        surplus: _Surplus = {}
        for message_id, rows in facts.items():
            call_id = ids[message_id]
            self._placed(held.get(call_id, []), rows, entity, surplus, call_id=call_id)
        self.db.flush()
        self._remove(entity, [row.id for row in surplus.get(entity, [])])

    def _join(self, session_id: str) -> None:
        """Join each sub-agent's thread of the conversation to the Tool Call
        it names as its spawning call: the one of that `tool_use_id` in
        another thread of the conversation, and none where no thread or more
        than one holds it. A thread joined to that Tool Call already is not
        written."""
        holder = aliased(Transcript)
        spawning = (
            select(func.min(ToolCall.id))
            .join(holder, holder.id == ToolCall.transcript_id)
            .where(
                holder.session_id == Transcript.session_id,
                holder.id != Transcript.id,
                ToolCall.tool_use_id == Transcript.spawned_by_tool_use_id,
            )
            .having(func.count() == 1)
            .correlate(Transcript)
            .scalar_subquery()
        )
        self.db.execute(
            update(Transcript)
            .where(
                Transcript.session_id == session_id,
                Transcript.agent_id.is_not(None),
                Transcript.spawned_by_id.is_distinct_from(spawning),
            )
            .values(spawned_by_id=spawning)
        )

    def _placed[Row](
        self,
        held: Sequence[Row],
        facts: list[dict[str, Any]],
        entity: type[Row],
        surplus: _Surplus,
        **parent: Any,
    ) -> list[Row]:
        """The rows of `facts`, each the held row at its place with those
        facts, else a new row of `parent`'s. The held rows past the last of
        `facts` are left to `surplus`, for `_remove`."""
        rows: list[Row] = []
        for place, values in enumerate(facts):
            if place < len(held):
                row = held[place]
                _set(row, values)
            else:
                row = entity(**parent, **values)
                self.db.add(row)
            rows.append(row)
        if len(held) > len(facts):
            surplus.setdefault(entity, []).extend(held[len(facts) :])
        return rows

    def _remove(self, entity: type[Any], ids: Sequence[int]) -> None:
        """Delete the entity's rows of those ids, in one statement, so that
        rows that name each other go together. Its keys take what hangs on
        each: a Launch's versions and Prompts, a Prompt's Hook Runs, a Call's
        Tool Calls, Events and Context Parts; a Tool Call that goes leaves
        the sub-agent's thread it started with no spawning call."""
        if ids:
            self.db.execute(
                delete(entity).where(
                    entity.id == any_(literal(list(ids), ARRAY(BigInteger)))
                )
            )

    def _grouped[Row](self, rows: Select[Row], parent: str) -> dict[int, list[Row]]:
        """The rows in their order, under each one's `parent` column."""
        grouped: dict[int, list[Row]] = {}
        for row in self.db.scalars(rows):
            grouped.setdefault(getattr(row, parent), []).append(row)
        return grouped


def _set(row: Any, facts: dict[str, Any]) -> None:
    """Give the row its facts. The flush writes a row only where one of them
    differs from what it held."""
    for column, value in facts.items():
        setattr(row, column, value)
