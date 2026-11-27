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

A whole publication of the file Pilot holds, read by the collector's version
Pilot holds it under, while part of it was taken appended, is the replay at
rest (DB decision 81 point 2; F152.16). It writes a row only where what the
appended calls left is not what the file read whole gives, and those rows
are logged with the Transcript.

Publications of one conversation, its main thread's and its sub-agents',
take turns, so that a sub-agent's thread finds its main thread and its
spawning Tool Call whichever comes first.

A main thread's Launches that a Turn of Pilot's started, or a driver under
a Session whose step names the thread, are placed under their Session and
Turn as the write ends (`launch_placement`; DB decision 79 point 7), and a
Launch the call names again keeps what it was placed under.

A Call is written with its cost, at the Prices in force (`price_service`; DB
548), and a Model the call is the first to name with the Model it is priced
as. A publication writes under the Prices' turn, so that a load of the price
file prices every Call written before it.

A Call is written with its other caches too, its wait, whether it is a
rewind, a cache miss or past the cache's lifetime, and the Launch it was
made in, and its Transcript with its first and its last Call's time
(`call_caches`; DB §7.4). A main thread's publication leaves each Call of
its sub-agents' threads in the Launch that holds it.

A call's labelling replaces every label Pilot holds of the Transcript, in the
same transaction as its facts (`label_write`; DB decision 81, assertion 561),
under the labeller's version and stamp it names; an appended call's replaces
the labels from its boundary on, and is taken only where it continues the
labels Pilot holds, under their stamp and their version's major. The facts
are the Events and Context Parts the collector read and the labels those the
labeller gave, so that a publication's facts never remove or overwrite a
label, nor its labels a fact, but for the carve: a Call's labelled Context
Parts are carved out of its opening prompt's, stored as what the collector
counted less them. A call
with no labelling, made while no labeller answered for the Transcript, writes
its facts and leaves every label Pilot holds of it as it stands, its adoption
included, and its stamp none, so that the labeller's next answer differs from
it (F152.2, F152.6).

A Tool Call is written with the commits it made, each held at once with its
Repository, its subject and its hash as the call showed it and no lines, and
with its file edits (`commit_write`; DB §2.9): facts of the Tool Call, which
go with it, but for what a read of its Repository gave a Commit, which stays.

A main thread whose labelling names a group is adopted by the group's adopted
Project, which the call makes where Pilot has none (`adoption_service`;
F152.8), and by none where its labelling names none: the label is the
labeller's. A Transcript a Session of Pilot's ran is adopted by no Project (DB
539), so a group named for one is refused.
"""

import hmac
import logging
import re
import uuid
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, get_args

from pilot_collection.inventory import HeldTranscriptSchema, InventorySchema
from pilot_collection.publication import (
    CallTokenKind,
    PublicationSchema,
    PublishedAppendedSchema,
    PublishedBoundarySchema,
    PublishedCallSchema,
    PublishedCompactionSchema,
    PublishedLaunchSchema,
)
from sqlalchemy import (
    BigInteger,
    Select,
    any_,
    delete,
    exists,
    func,
    inspect,
    literal,
    select,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Row
from sqlalchemy.event import listen, remove
from sqlalchemy.orm import Session, aliased
from sqlalchemy.orm.session import UOWTransaction

from app.app_config import AppSettings
from app.dashboard.assembly import CatalogueService
from app.exceptions import (
    AuthenticationException,
    CollectorProtocolUnsupportedException,
    PublicationInvalidException,
    PublicationNotAppendableException,
    TranscriptNotAdoptableException,
)
from app.models import (
    Call,
    Commit,
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
    FileEdit,
    HookRun,
    Launch,
    LaunchComponent,
    MissCause,
    Model,
    Prompt,
    PromptSource,
    StepTranscript,
    StopReason,
    Tool,
    ToolCall,
    Transcript,
)
from app.models import Session as AgentSession
from app.models.call import RECORDED_ELSEWHERE
from app.services import labeller_context
from app.services.adoption_service import AdoptionService, group_faults
from app.services.call_caches import caches, hold_sub_agents_calls
from app.services.commit_write import CommitWrite, commits_turn, made_faults
from app.services.environment_service import reported_columns
from app.services.fleet_consumer import FleetConsumer
from app.services.label_write import (
    LABEL_COLUMNS,
    LABELLER,
    PROMPT,
    LabelWrite,
    carve,
    carve_faults,
    labelled,
    labelling_faults,
)
from app.services.launch_placement import conversation_turn, place_launches
from app.services.price_service import costs, price_as_family, prices_turn
from app.utils.after_commit import after_commit

logger = logging.getLogger(__name__)

COLLECTOR_PROTOCOL_MIN = 1
"""The oldest protocol version the server takes of a collector."""

COLLECTOR_PROTOCOL_MAX = 2
"""The newest protocol version the server takes of a collector. A change to a
request or response shape of the collector's routes bumps it, and
`COLLECTOR_PROTOCOL_MIN` with it when the server cannot serve the old
collector."""

_VERSION = re.compile(r"[0-9]+")

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

type _Held = Row[uuid.UUID, int, datetime, int, str, str | None, str | None]
"""A Transcript as Pilot holds it (`PublicationService._held`): its id, its
`file_size`, `file_modified_at` and `replayed_size`, the collector's `version`
it was read under, and the labeller's version it was `labelled_under` and its
`records_stamp`."""

_FACTS: tuple[type[Any], ...] = (
    Launch,
    LaunchComponent,
    Prompt,
    HookRun,
    Compaction,
    Call,
    ToolCall,
    Event,
    ContextPart,
    Commit,
    FileEdit,
)
"""The entities whose rows a publication writes under its Transcript, its
Tool Calls' Commits and File Edits among them."""


class _Replay:
    """The rows under a Transcript that a write changes, adds and removes,
    counted by table from its making to its `end`: its facts', and its
    labels' where `labels`. A row that goes with the one it hangs on is not
    counted, and neither is a prompt's Context Part whose carve alone moved
    (`carved`)."""

    def __init__(self, session: Session, labels: bool) -> None:
        self._session = session
        self._labels = labels
        self._facts: set[Any] = set()
        self._labelled: set[Any] = set()
        self._carved: set[Any] = set()
        self._removed: Counter[str] = Counter()
        listen(session, "before_flush", self._flushing)

    def removed(self, entity: type[Any], rows: int) -> None:
        """Count the entity's rows a statement removes, which no flush
        shows."""
        if entity in _FACTS:
            self._removed[entity.__tablename__] += rows

    def carved(self, row: ContextPart) -> None:
        """Count no change of the prompt's part's `characters`: what the
        collector counted of it is what Pilot held."""
        self._carved.add(row)

    def end(self) -> tuple[dict[str, int], dict[str, int]]:
        """Stop counting; the number of rows written, by table, of the facts
        and of the labels."""
        remove(self._session, "before_flush", self._flushing)
        facts = Counter(row.__tablename__ for row in self._facts) + self._removed
        labels: Counter[str] = Counter()
        if self._labels:
            labels.update(row.__tablename__ for row in self._labelled)
        return dict(sorted(facts.items())), dict(sorted(labels.items()))

    def _flushing(
        self, session: Session, _flush_context: UOWTransaction, _instances: Any
    ) -> None:
        for row in (*session.new, *session.deleted):
            if labelled(row):
                self._labelled.add(row)
            elif isinstance(row, _FACTS):
                self._facts.add(row)
        for row in session.dirty:
            if not session.is_modified(row):
                continue
            if labelled(row):
                self._labelled.add(row)
            elif isinstance(row, _FACTS):
                changed = {
                    attribute.key
                    for attribute in inspect(row).attrs
                    if attribute.history.has_changes()
                }
                columns = LABEL_COLUMNS.get(type(row), frozenset())
                if changed & columns:
                    self._labelled.add(row)
                if row in self._carved:
                    changed.discard("characters")
                if changed - columns:
                    self._facts.add(row)


def _not_held(fact: str, place: int, did: str, held: datetime, first: datetime) -> str:
    """Why an appended call is refused whose first `fact` is another than
    the row Pilot holds at the boundary's place, told by its time."""
    return (
        f"the boundary's `{fact}` is {place}, where Pilot holds a {fact} {did} at"
        f" {held.astimezone(UTC).isoformat()}, and the call's first was {did} at"
        f" {first.astimezone(UTC).isoformat()}"
    )


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
        if publication.group is not None:
            found.append("a sub-agent's thread names no `group`")
    if publication.group is not None:
        found.extend(group_faults(publication.group.name, publication.group.summary))
    found.extend(labelling_faults(publication))
    found.extend(made_faults(publication))

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
    """Admits a collector's call, hands a walk Pilot's inventory, and writes
    a publication into the record on the caller's transaction."""

    def __init__(
        self,
        db: Session,
        app_settings: AppSettings,
        adoption_service: AdoptionService,
        fleet_consumer: FleetConsumer,
        catalogue_service: CatalogueService,
    ) -> None:
        """
        Args:
            fleet_consumer: The fleet stream's latest report of each
                environment, for the row of one a call names first
            catalogue_service: The dashboard's catalogue, which holds the
                reference entities' rows and is dropped where a call adds one
        """
        self.db = db
        self.app_settings = app_settings
        self.adoption_service = adoption_service
        self.fleet_consumer = fleet_consumer
        self.catalogue_service = catalogue_service
        self._labels = LabelWrite(db)
        self._commits = CommitWrite(db)
        self._replay: _Replay | None = None

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

    def inventory(self) -> InventorySchema:
        """What Pilot holds, for a walk to compare the home against and to
        hand the labeller (F152.2): every Transcript with its collection
        record and the labeller's version and stamp its labels were written
        under, in one read, by `session_id`, a main thread before its
        sub-agents'; every conversation a Session of Pilot's ran, with what
        the labeller is handed with it (`labeller_context`); and the walk's
        two settings."""
        labeller = aliased(ComponentVersion)
        held = self.db.execute(
            select(
                Transcript.session_id,
                Transcript.agent_id,
                Transcript.file_size,
                Transcript.file_modified_at,
                Transcript.replayed_size,
                ComponentVersion.version.label("collector"),
                labeller.version.label("labeller"),
                Transcript.records_stamp.label("stamp"),
            )
            .join(ComponentVersion, ComponentVersion.id == Transcript.read_under_id)
            .outerjoin(labeller, labeller.id == Transcript.labelled_under_id)
            .order_by(Transcript.session_id, Transcript.agent_id.nulls_first())
        )
        return InventorySchema(
            walk_interval_seconds=self.app_settings.collector_walk_interval_seconds,
            settling_seconds=self.app_settings.collector_settling_seconds,
            transcripts=[
                HeldTranscriptSchema.model_validate(row, from_attributes=True)
                for row in held
            ],
            conversations=labeller_context.conversations(self.db),
        )

    def publish(self, publication: PublicationSchema) -> Transcript:
        """Take a publication of one Transcript, whole or appended, and
        return its row.

        After a whole one its `replayed_size` is its `file_size` (DB 605). A
        Call Pilot held of it that the call no longer names is removed with
        what hangs on it, and their number logged. The rows its replay at
        rest writes are logged with it (`_replayed`). After an appended one
        Pilot holds what the call carries from its boundary on, its labels
        among it, what lies before it as it was, and `replayed_size` as it
        stood. After either,
        each Launch of a main thread that a Turn of Pilot's started, or a
        driver under a Session whose step names the thread, stands under
        its Session and Turn (DB 538). After one with a labelling the
        Transcript holds its labels and no other, under the labeller's
        version and stamp it names, and a main thread is adopted by the
        adopted Project of the `group` the call names, made where no Project
        holds the group and renamed where the group was, and by none where
        the call names none; after one with none it holds the labels it held
        and no stamp. After either, each Call's opening prompt's Context
        Part is what the collector counted less the Call's labelled Context
        Parts. After either, each Tool Call it carries holds the commits it
        made and its file edits as the call names them, a Commit read from
        its Repository keeping what the read gave it, and a commit whose hash
        Pilot holds as another's not held again. After either, each Call
        it carries holds its cost at the Prices in force, none where a kind
        it counts tokens of has no Price, and its other caches
        (`call_caches`); the Transcript holds its first and its last Call's
        time; and each Call of a main thread's sub-agents' threads is in
        the Launch that holds it (DB 543).

        An Environment, a Repository, a Component Version and a reference
        code the call names that Pilot has no row for are written, the
        Environment as the fleet stream reports it (`_environment`), the code
        as its own name and with what the call says of its category, a Model
        with the Model it is priced as; one Pilot has met stands as it is.

        Raises:
            PublicationInvalidException: the call has faults, its labelling
                names a value no list of the labeller's declares or a row
                Pilot does not hold, or the labelled Context Parts it keeps
                do not fit in their Call's opening prompt; nothing is
                written.
            PublicationNotAppendableException: an appended call does not
                continue what Pilot holds of the Transcript, its facts or its
                labels; nothing is written.
            TranscriptNotAdoptableException: the call names a group for a
                Transcript a Session of Pilot's ran; nothing is written.
            NoServiceUserException: the call names a group no Project
                holds, and the stage has no service user to make its
                Project; nothing is written.
        """
        found = _faults(publication)
        if found:
            raise PublicationInvalidException(_name(publication), found)
        conversation_turn(self.db, publication.session_id)
        prices_turn(self.db)
        commits_turn(self.db)
        boundary = _WHOLE
        ids: dict[str, int] = {}
        held = self._held(publication)
        labelling = publication.labelling
        kept = self._kept_carve(held)
        if labelling is None:
            carved = kept
            found = carve_faults(
                publication.calls, kept, "the labelled context parts Pilot holds"
            )
        else:
            carved = carve(labelling)
            found = self._labels.faults(labelling)
        if found:
            raise PublicationInvalidException(_name(publication), found)
        if publication.appended is not None:
            boundary = publication.appended.boundary
            ids = self._continued(publication, publication.appended, held)
        adopted_by = self._adopted_by(publication)
        self._meet_references(publication)
        versions = self._versions(publication)
        repositories = self._commits.repositories(publication)
        thread = self._thread(publication, versions, repositories, adopted_by)
        with self._replayed(publication, held):
            self._facts(
                thread,
                publication,
                (versions, repositories),
                boundary,
                ids,
                (kept, carved),
            )
            if labelling is not None:
                self._labels.write(thread, labelling, ids, boundary)
        self._join(publication.session_id)
        if publication.agent_id is None:
            hold_sub_agents_calls(self.db, publication.session_id)
            place_launches(self.db, publication.session_id)
        return thread

    def _held(self, publication: PublicationSchema) -> _Held | None:
        """The Transcript as Pilot holds it; None where it does not."""
        labeller = aliased(ComponentVersion)
        return self.db.execute(
            select(
                Transcript.id,
                Transcript.file_size,
                Transcript.file_modified_at,
                Transcript.replayed_size,
                ComponentVersion.version,
                labeller.version.label("labelled_under"),
                Transcript.records_stamp,
            )
            .join(ComponentVersion, ComponentVersion.id == Transcript.read_under_id)
            .outerjoin(labeller, labeller.id == Transcript.labelled_under_id)
            .where(
                Transcript.session_id == publication.session_id,
                Transcript.agent_id.is_not_distinct_from(publication.agent_id),
            )
        ).one_or_none()

    def _kept_carve(self, held: _Held | None) -> dict[str, int]:
        """The characters the labelled Context Parts Pilot holds of the
        Transcript carve out of each Call's opening prompt, by the Call's
        `message_id`."""
        if held is None:
            return {}
        return {
            message_id: int(characters)
            for message_id, characters in self.db.execute(
                select(Call.message_id, func.sum(ContextPart.characters))
                .join(Call, Call.id == ContextPart.call_id)
                .where(Call.transcript_id == held.id, ContextPart.labelled.is_(True))
                .group_by(Call.message_id)
            )
        }

    @contextmanager
    def _replayed(
        self, publication: PublicationSchema, held: _Held | None
    ) -> Iterator[None]:
        """Log the rows the block writes under the Transcript where the call
        is its replay at rest (DB decision 81 point 2; F152.16): a whole one
        of the file Pilot holds, at that size and time and read under that
        collector's version, part of it taken in appended calls since the
        last whole one. `held` is the Transcript as Pilot held it before the
        call. Pilot holds no boundary, so each row written is logged, by its
        table, with how much of the file was taken in parts; a whole call of
        a file that changed, or read under another version, writes rows that
        say nothing of the appended calls, and is not logged. The labels'
        rows are logged beside the facts' where the call's labelling is under
        the labeller's version and stamp Pilot held: under another, what the
        labels improve is no replay's difference."""
        if (
            publication.appended is not None
            or held is None
            or held.replayed_size == held.file_size
            or (held.file_size, held.file_modified_at, held.version)
            != (
                publication.file_size,
                publication.file_modified_at,
                publication.collector.version,
            )
        ):
            yield
            return
        labelling = publication.labelling
        self._replay = _Replay(
            self.db,
            labelling is not None
            and (held.labelled_under, held.records_stamp)
            == (labelling.version, labelling.stamp),
        )
        try:
            yield
            self.db.flush()
        finally:
            facts, labels = self._replay.end()
            self._replay = None
        wrote: list[str] = []
        if facts:
            wrote.append(f"rows that differ from what Pilot held: {_tables(facts)}")
        if labels:
            differ = "labels that differ" + ("" if facts else " from what Pilot held")
            wrote.append(f"{differ}: {_tables(labels)}")
        if wrote:
            logger.warning(
                "The replay at rest of transcript %s, %d of its %d bytes taken in"
                " parts, wrote %s",
                _name(publication),
                held.file_size - held.replayed_size,
                held.file_size,
                ", and ".join(wrote),
            )

    def _facts(
        self,
        thread: Transcript,
        publication: PublicationSchema,
        named: tuple[dict[_Version, int], dict[str, int]],
        boundary: PublishedBoundarySchema,
        ids: dict[str, int],
        carves: tuple[dict[str, int], dict[str, int]],
    ) -> None:
        """The rows under the Transcript from the boundary on as the call
        has them, the Events and Context Parts the collector's alone, and
        its Tool Calls' Commits and File Edits. `named` is the id of each
        Component Version and of each Repository the call names. `ids`
        comes with the Calls before the boundary that the call's name as
        their predecessor. `carves` are the characters the labelled Context
        Parts carve out of each Call's opening prompt, by its `message_id`:
        those Pilot held, and those it holds after the call."""
        versions, repositories = named
        surplus: _Surplus = {}
        prompts = self._launches(
            thread, publication.launches, versions, surplus, boundary
        )
        compactions = self._compactions(
            thread, publication.compactions, surplus, boundary
        )
        calls = publication.calls
        stale = self._calls(thread, calls, prompts, compactions, boundary, ids)
        made = self._tool_calls(thread, calls, ids, boundary)
        # Must follow `_tool_calls`, which moves a Tool Call the call names
        # off a Call that goes here, and `_calls`, after which no Call the
        # call names points at a Call, a Prompt or a Compaction that goes.
        self._lose_calls(publication, stale)
        for entity, gone in surplus.items():
            self._remove(entity, [row.id for row in gone])
        self._commits.write(calls, made, repositories, _name(publication))
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
        parts: dict[str, list[dict[str, Any]]] = {}
        for call in calls:
            rows = parts[call.message_id] = [
                {
                    "kind_code": part.kind,
                    "name": part.name,
                    "characters": part.characters,
                }
                for part in call.context_parts
            ]
            opening = _opening(rows)
            if opening is not None:
                rows[opening]["characters"] -= carves[1].get(call.message_id, 0)
        self._hung(ContextPart, thread, ids, boundary, parts, carves)

    def _continued(
        self,
        publication: PublicationSchema,
        appended: PublishedAppendedSchema,
        held: _Held | None,
    ) -> dict[str, int]:
        """Check that an appended call continues what Pilot holds of its
        Transcript, `held` (`_held`), and return the id of each Call before
        its boundary that one of its Calls names as its predecessor, by
        `message_id`.

        It does where Pilot holds the Transcript as the call builds on it,
        at that size and time and read under that collector's version; where
        Pilot holds a row at every place before the boundary's; where the
        call carries every Launch, Prompt, Compaction and Call Pilot holds
        from there on, and no Call or Tool Call Pilot holds before; and
        where the call's first Launch, its first Prompt and its first
        Compaction are each the row Pilot holds at the boundary's place, if
        it holds one there, told by its time. The write that follows then
        removes none of those, touches nothing before the boundary, and
        gives no held row another's facts. Its labelling, where it carries
        one, continues the labels Pilot holds (`LabelWrite.gaps`).

        Raises:
            PublicationNotAppendableException: it does not; nothing is
                written.
        """
        name = _name(publication)
        base = appended.builds_on
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
        if publication.labelling is not None:
            causes += self._labels.gaps(
                held.id,
                (held.labelled_under, held.records_stamp),
                publication.labelling,
                boundary,
            )
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
        began: dict[int, datetime] = dict(
            self.db.execute(
                select(Launch.id, Launch.started_at)
                .where(Launch.transcript_id == thread_id)
                .order_by(Launch.id)
            ).all()
        )
        held = list(began)
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
        # The boundary's `prompt` is a place under the boundary's Launch, so
        # it is read only once that Launch is the one Pilot holds there.
        if since and launches[0].started_at != began[since[0]]:
            return [
                _not_held(
                    "launch",
                    boundary.launch,
                    "begun",
                    began[since[0]],
                    launches[0].started_at,
                )
            ]
        # The Prompts the boundary's Launch keeps: those before the
        # boundary's that lie under no Launch before it.
        kept = boundary.prompt - 1 - sum(received.get(row, 0) for row in before)
        under = received.get(since[0], 0) if since else 0
        if not 0 <= kept <= under:
            return [
                f"the boundary's `prompt` is {boundary.prompt}, which is neither"
                " a prompt Pilot holds under the boundary's launch nor the next"
                " under it"
            ]
        causes = [
            f"launch {boundary.launch + place}: the call carries fewer prompts"
            " than Pilot holds under it"
            for place, launch_id in enumerate(since)
            if len(launches[place].prompts) + (0 if place else kept)
            < received.get(launch_id, 0)
        ]
        if kept < under and launches[0].prompts:
            received_at = self.db.scalars(
                select(Prompt.received_at)
                .where(Prompt.launch_id == since[0])
                .order_by(Prompt.id)
                .offset(kept)
                .limit(1)
            ).one()
            first = launches[0].prompts[0].received_at
            if first != received_at:
                causes.append(
                    _not_held("prompt", boundary.prompt, "received", received_at, first)
                )
        return causes

    def _compaction_gaps(
        self,
        thread_id: uuid.UUID,
        compactions: list[PublishedCompactionSchema],
        boundary: PublishedBoundarySchema,
    ) -> list[str]:
        """Why an appended call's Compactions do not continue the
        Transcript's as Pilot holds them, each in a line."""
        held = self.db.scalars(
            select(Compaction.at)
            .where(Compaction.transcript_id == thread_id)
            .order_by(Compaction.id)
        ).all()
        since = held[boundary.compaction - 1 :]
        if len(held) < boundary.compaction - 1:
            return [
                f"the boundary's `compaction` is {boundary.compaction}, and Pilot"
                f" holds {len(held)} compactions"
            ]
        if len(compactions) < len(since):
            return [
                f"the call carries {len(compactions)} compactions from its"
                f" boundary on, and Pilot holds {len(since)}"
            ]
        if since and compactions[0].at != since[0]:
            return [
                _not_held(
                    "compaction",
                    boundary.compaction,
                    "made",
                    since[0],
                    compactions[0].at,
                )
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

    def _adopted_by(self, publication: PublicationSchema) -> uuid.UUID | None:
        """The id of the adopted Project of the group the call names, none
        where it names none. A Session of Pilot's ran the Transcript where
        one runs a Launch of it, or names its conversation, itself or by a
        step, while no Project has adopted it: one adopted before a Session
        named it stays adopted, its Launches off that Session
        (`launch_placement.place_launches`).

        Raises:
            TranscriptNotAdoptableException: a Session of Pilot's ran the
                Transcript (DB 539); nothing is written.
            NoServiceUserException: no Project holds the group, and the
                stage has no service user; nothing is written.
        """
        group = publication.group
        if group is None:
            return None
        conversation = publication.session_id
        ran = self.db.scalar(
            select(
                exists().where(
                    Launch.transcript_id == Transcript.id,
                    Transcript.session_id == conversation,
                    Launch.session_id.is_not(None),
                )
                | (
                    (
                        exists().where(AgentSession.conversation_id == conversation)
                        | exists().where(StepTranscript.session_id == conversation)
                    )
                    & ~exists().where(
                        Transcript.session_id == conversation,
                        Transcript.adopted_project_id.is_not(None),
                    )
                )
            )
        )
        if ran:
            raise TranscriptNotAdoptableException(_name(publication), group.key)
        return self.adoption_service.adopt(group.key, group.name, group.summary)

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
            [COLLECTOR, LABELLER if publication.labelling is not None else None]
            + [used.component for launch in launches for used in launch.components],
        )
        self._meet(
            CompactionTrigger,
            [compaction.trigger for compaction in publication.compactions],
        )
        self._meet(MissCause, [call.miss_cause for call in calls])
        price_as_family(
            self.db,
            self._meet(
                Model,
                [call.model for call in calls]
                + [call.requested_model for call in calls],
            ),
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
    ) -> list[str]:
        """Write the reference entity's row of each code Pilot has not met,
        named by its code, with the `facts` the call gives of its category;
        returned are those codes."""
        named = {code for code in codes if code is not None}
        if not named:
            return []
        met: set[str] = set(
            self.db.scalars(select(entity.code).where(entity.code.in_(named)))
        )
        unmet = sorted(named - met)
        if unmet:
            after_commit(self.catalogue_service.drop)
            # The code is the arbiter: Event Kind's and Context Part Kind's
            # place in the labeller's list is unique and deferrable, which no
            # ON CONFLICT takes as one.
            self.db.execute(
                pg_insert(entity).on_conflict_do_nothing(index_elements=["code"]),
                [
                    {"code": code, "name": code} | (facts[code] if facts else {})
                    for code in unmet
                ],
            )
        return unmet

    def _versions(self, publication: PublicationSchema) -> dict[_Version, int]:
        """The id of each Component Version the call names. One Pilot has not
        met is written, and one it has takes the release time the call gives."""
        collector = publication.collector
        named: dict[_Version, datetime | None] = {
            (COLLECTOR, collector.version): collector.released_at
        }
        if publication.labelling is not None:
            named[LABELLER, publication.labelling.version] = None
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

    def _environment(self, env_id: str) -> None:
        """Write the Environment of that id where Pilot has none: as the
        fleet stream reports it, its name and exemption with it. One the
        stream has not given, and any while it is down, is named by its id
        and not exempt, with no `last_seen_at`: a row no report of the
        controller's has reached, which Pilot's first touch of the
        environment asks the controller about
        (`EnvironmentService.ensure_environment`)."""
        held = self.db.scalar(select(Environment.id).where(Environment.id == env_id))
        if held is None:
            report = self.fleet_consumer.environment(env_id)
            columns = (
                {"name": env_id, "exempt": False}
                if report is None
                else reported_columns(report, datetime.now(UTC))
            )
            self.db.execute(
                pg_insert(Environment)
                .values(id=env_id, **columns)
                .on_conflict_do_nothing(index_elements=["id"])
            )

    def _thread(
        self,
        publication: PublicationSchema,
        versions: dict[_Version, int],
        repositories: dict[str, int],
        adopted_by: uuid.UUID | None,
    ) -> Transcript:
        """The Transcript's row as the call has it, its `replayed_size` its
        file's size after a whole call alone (DB 605), with its first and its
        last Call's time as the call leaves them. One with a labelling is
        adopted by the Project `adopted_by`, under the labeller's version
        and stamp it names; one with none keeps its adoption and its
        labeller's version, and holds no stamp. A sub-agent's thread
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
            "read_under_id": versions[COLLECTOR, publication.collector.version],
            "records_stamp": None,
        }
        labelling = publication.labelling
        if labelling is not None:
            facts |= {
                "adopted_project_id": adopted_by,
                "labelled_under_id": versions[LABELLER, labelling.version],
                "records_stamp": labelling.stamp,
            }
        if publication.appended is None:
            facts["replayed_size"] = publication.file_size
        if publication.repository is not None:
            facts["repository_id"] = repositories[publication.repository]
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
        facts |= self._call_times(publication, thread)
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

    def _call_times(
        self, publication: PublicationSchema, thread: Transcript | None
    ) -> dict[str, datetime | None]:
        """The Transcript's `first_call_at` and `last_call_at` once the call
        is written, where it moves them; `thread` is its row as Pilot holds
        it, None where it does not. The Calls before an appended call's
        boundary stand, so its first Call's time does: read from that Call
        where the row has none, a server from before these times having
        written it."""
        calls = publication.calls
        last = calls[-1].completed_at if calls else None
        appended = publication.appended
        if thread is None or appended is None or appended.boundary.call == 1:
            return {
                "first_call_at": calls[0].completed_at if calls else None,
                "last_call_at": last,
            }
        if not calls:
            return {}
        first = (
            thread.first_call_at
            or self.db.scalars(
                select(Call.completed_at).where(
                    Call.transcript_id == thread.id, Call.position == 1
                )
            ).one()
        )
        return {"first_call_at": first, "last_call_at": last}

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
        written beside it names it as its predecessor. Each is written with
        its cost and its other caches."""
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

        written: list[dict[str, Any]] = []
        for position, call in enumerate(calls, start=boundary.call):
            facts: dict[str, Any] = {
                "id": ids[call.message_id],
                "transcript_id": thread.id,
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
            written.append(facts)
        priced = costs(self.db, written)
        derived = caches(self.db, written)
        met: list[tuple[Call, dict[str, Any]]] = []
        for call, facts in zip(calls, written, strict=True):
            facts["cost"] = priced[facts["id"]]
            facts |= derived[facts["id"]]
            row = held.get(call.message_id)
            if row is None:
                self.db.add(Call(message_id=call.message_id, **facts))
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
    ) -> dict[str, int]:
        """The Tool Calls the call names, each under the Call that requested
        it; one held under a Call from the boundary on that it no longer
        names is removed. Returned is the id of each, by its
        `tool_use_id`."""
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
        named: dict[str, ToolCall] = {}
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
                    row = ToolCall(
                        transcript_id=thread.id,
                        tool_use_id=requested.tool_use_id,
                        **facts,
                    )
                    self.db.add(row)
                else:
                    _set(row, facts)
                named[requested.tool_use_id] = row
        self.db.flush()
        self._remove(
            ToolCall,
            [row.id for tool_use_id, row in held.items() if tool_use_id not in named],
        )
        return {tool_use_id: row.id for tool_use_id, row in named.items()}

    def _hung(
        self,
        entity: type[Any],
        thread: Transcript,
        ids: dict[str, int],
        boundary: PublishedBoundarySchema,
        facts: dict[str, list[dict[str, Any]]],
        carves: tuple[dict[str, int], dict[str, int]] | None = None,
    ) -> None:
        """The collector's rows of `entity`, an Event's or a Context Part's,
        under each Call as `facts` has them by the Call's `message_id`, in
        the file's order; a held one past the last its Call has is removed.
        The labelled rows stand. `carves`, for the Context Parts, are what
        `_facts` takes them as."""
        held: dict[int, list[Any]] = self._grouped(
            select(entity)
            .join(Call, Call.id == entity.call_id)
            .where(
                Call.transcript_id == thread.id,
                Call.position >= boundary.call,
                entity.labelled.is_(False),
            )
            .order_by(entity.id),
            "call_id",
        )
        surplus: _Surplus = {}
        for message_id, rows in facts.items():
            call_id = ids[message_id]
            under = held.get(call_id, [])
            if carves is not None and self._replay is not None:
                self._carve_moved(
                    under, rows, *(carve.get(message_id, 0) for carve in carves)
                )
            self._placed(under, rows, entity, surplus, call_id=call_id)
        self.db.flush()
        self._remove(entity, [row.id for row in surplus.get(entity, [])])

    def _carve_moved(
        self,
        held: list[ContextPart],
        rows: list[dict[str, Any]],
        before: int,
        after: int,
    ) -> None:
        """Tell the replay where the held opening prompt's part, carved by
        `before` characters, is what the collector counted again, `rows`'
        own carved by `after`: a change of its characters is its labels'."""
        assert self._replay is not None
        opening = _opening(rows)
        if opening is None or opening >= len(held):
            return
        row = held[opening]
        if (
            row.kind_code == PROMPT
            and row.characters + before == rows[opening]["characters"] + after
        ):
            self._replay.carved(row)

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
        Tool Calls, Events and Context Parts, a Tool Call's File Edits; a Tool
        Call that goes leaves the sub-agent's thread it started with no
        spawning call, and a Commit read from its Repository with no Tool
        Call. A Tool Call's Commit no read completed goes with it first."""
        if ids:
            if entity is Call or entity is ToolCall:
                self._commits.unmade(entity, ids)
            self.db.execute(
                delete(entity).where(
                    entity.id == any_(literal(list(ids), ARRAY(BigInteger)))
                )
            )
            if self._replay is not None:
                self._replay.removed(entity, len(ids))

    def _grouped[Row](self, rows: Select[Row], parent: str) -> dict[int, list[Row]]:
        """The rows in their order, under each one's `parent` column."""
        grouped: dict[int, list[Row]] = {}
        for row in self.db.scalars(rows):
            grouped.setdefault(getattr(row, parent), []).append(row)
        return grouped


def _opening(parts: list[dict[str, Any]]) -> int | None:
    """The place of a Call's opening prompt among its Context Parts' facts,
    none where it carries no prompt."""
    return next(
        (place for place, part in enumerate(parts) if part["kind_code"] == PROMPT),
        None,
    )


def _tables(rows: dict[str, int]) -> str:
    return ", ".join(f"{table} {count}" for table, count in rows.items())


def _set(row: Any, facts: dict[str, Any]) -> None:
    """Give the row its facts. The flush writes a row only where one of them
    differs from what it held."""
    for column, value in facts.items():
        setattr(row, column, value)
