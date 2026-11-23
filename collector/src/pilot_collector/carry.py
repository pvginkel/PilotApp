"""What the collector carries between walks of a transcript it published
(F152.1, F152.15): where its reading of the file stands, and the file that
reading was built on.

A carry is in the collector's memory alone, and is used only where Pilot's
inventory names exactly what it was built on. With it a file that grew and
nothing else is read from its boundary on and published appended; without
it, or wherever it does not fit, the file is read and published whole.

**The boundary** is the transcript's first Call that is not settled. A
Call's facts are settled once the next Call has begun, so the boundary is
the file's last Call, and the place its next would take in a file with none.
The carry holds the byte the boundary's first line starts at and what the
lines from there on continue: how many Calls, published Launches, Prompts and
Compactions lie before it, the last line before it that lines link to and
where the chain leads from that line, with what the Call it leads to left
the next, the lines named before it that the file holds no line of there,
the request lines written since the last one a Call named, the Events before
the transcript's first Call, the directory and the environment the file
named first, the Launch open there and the latest Prompt it received, with
the Hook Runs taken for that Prompt, what the lines before it record of the
Context Parts of the boundary's Call where it is its Launch's first, the
Context Parts injected before the boundary's Call, the prompts waiting in the
queue, and those a `remove` took out of it that no message taken in the
middle of a run has claimed. No id of any other line before the boundary is
held, and of no Call but the one the chain leads to; no request shape but
those the boundary's Call's requests name.

**The bound.** The carries are kept up to a number of transcripts and a size,
both settings. Past either, the transcript whose file changed longest ago is
forgotten first, and its next growth is one whole publication.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_DIGEST = 16
"""The bytes of a digest."""

_HELD = 1_280
"""The bytes a carry is counted at beside its words and its queue."""

_LEFT = 560
"""The bytes what the Call the chain leads to left is counted at beside its
words."""

_AWAITED = 64
"""The bytes a line awaited is counted at beside its id."""

_REQUESTED = 280
"""The bytes a request line held is counted at beside its id and its
shape."""

_OCCURRED = 224
"""The bytes an Event held is counted at beside its detail."""

_QUEUED = 176
"""The bytes a prompt waiting in the queue, or held once a `remove` took it
out, is counted at."""

_PROMPTED = 280
"""The bytes the latest Prompt held is counted at beside its source."""

_RAN = 200
"""The bytes a Hook Run held is counted at beside its command."""

_OPENING = 160
"""The bytes what a Launch's first Call carries is counted at beside its
instruction files and its snapshot."""

_FILE = 120
"""The bytes an instruction file loaded is counted at beside its path."""

_SHAPE = 160
"""The bytes what a line records of a system prompt and its tools is
counted at."""

_PART = 320
"""The bytes a Context Part injected is counted at beside its name."""


def digest(content: bytes) -> bytes:
    """What the collector remembers of bytes it read, to tell them from
    others."""
    return hashlib.blake2b(content, digest_size=_DIGEST).digest()


@dataclass(frozen=True)
class Open:
    """A Launch that has not exited where a reading stands."""

    started_at: datetime
    version: str | None
    """The version of Claude Code its lines so far name, none where none
    does."""
    received: int
    """How many Prompts it received so far."""


@dataclass(frozen=True)
class Left:
    """What a Call left the next on its chain: what that one's cache miss
    and its cause read of it."""

    place: int
    """Its place among the transcript's Calls, from 0."""
    completed_at: datetime
    model: str
    effort: str | None
    version: str | None
    """Claude Code's version its first line names."""
    cached: int
    """The tokens it left in the cache: those it read from it and those it
    wrote to it."""
    hour: bool
    """Whether it wrote to the cache that lasts an hour: what it left lasts
    five minutes where it did not."""
    shape: str | None
    """Its request's `shapeHash`."""
    sent: int | None
    """The messages its request sent."""


@dataclass(frozen=True)
class Lead:
    """Where the chain leads from one line, up its `parentUuid`s and, at a
    compaction's boundary, its `logicalParentUuid`."""

    call: str | None = None
    """The `message_id` of the nearest Call at or above the line, none
    where the chain reaches none."""
    compaction: int | None = None
    """The Compaction crossed on the way there, the nearest to the line, by
    its place among the transcript's; none where the chain crosses none."""
    left: Left | None = None
    """What that Call left the next, none where the chain reaches none."""


ROOT = Lead()
"""Where the chain leads from no line: a chain's first line follows none."""


@dataclass(frozen=True)
class Shape:
    """What a line records of the system prompt and the tools a request
    sent, or a process started with: the characters of each, none where it
    records none."""

    system: int | None = None
    tools: int | None = None
    """The characters of the tools' schemas, as JSON."""


@dataclass(frozen=True)
class Requested:
    """A request line: what the Call whose lines name it reads of it."""

    id: str
    at: datetime
    """When it was written: when the request was sent."""
    shape: str | None = None
    """`shapeHash`, a digest of the system prompt and the tools it sent."""
    kept: int | None = None
    """`keep`: the messages it kept of those the request before it sent."""
    sent: int | None = None
    """The messages it sent: those it kept and those of its `tail`."""
    sends: Shape | None = None
    """What the line of its shape records it sent, on a request of a
    Launch's first Call: none where no such line stood before it, and on
    any other request."""


@dataclass(frozen=True)
class Opening:
    """What lines record of the Context Parts of a Launch's first Call, as
    they stand before that Call begins: on a sub-agent's thread, of its
    first Call."""

    snapshot: Shape | None = None
    """The system prompt and the tools a snapshot of them records, written
    as the process started."""
    files: tuple[tuple[str, int], ...] = ()
    """The instruction files loaded: each one's path and characters."""
    prompts: tuple[int, ...] = ()
    """The characters of each Prompt received: on a sub-agent's thread, of
    its task."""


@dataclass(frozen=True)
class Part:
    """A Context Part a line injected before a Call."""

    kind: str
    """The Context Part Kind's code."""
    characters: int
    name: str | None = None
    """Which one of its kind: the file, the skill, the attachment's type."""


@dataclass(frozen=True)
class Occurred:
    """An Event: what occurred at one moment in the transcript that no other
    fact records."""

    kind: str
    """The Event Kind's code."""
    at: datetime
    detail: str | None = None
    """Its one qualifier: an API error's status."""


@dataclass(frozen=True)
class Ran:
    """A Hook Run: a run of one hook command at the end of a Prompt's
    run."""

    command: str
    duration_ms: int
    failed: bool
    prevented_end: bool


@dataclass(frozen=True)
class Prompted:
    """A Prompt as its publication gives it, with the Hook Runs taken for
    it."""

    received_at: datetime
    source: str
    characters: int
    runs: tuple[Ran, ...] = ()


@dataclass(frozen=True)
class Standing:
    """Where a reading stands before one line of the file: what the lines
    from that line on continue. A file's first line continues nothing."""

    byte: int = 0
    """Where the line starts in the file."""
    calls: int = 0
    """The Calls before it."""
    launches: int = 0
    """The Launches that exited before it and are published."""
    prompts: int = 0
    """The Prompts before it."""
    compactions: int = 0
    """The Compactions before it."""
    link: str | None = None
    """The `uuid` of the last line before it that carries one."""
    leads: Lead = ROOT
    """Where the chain leads from the line `link` names, as the lines
    before it stand."""
    awaited: tuple[str, ...] = ()
    """The `uuid`s the lines before it name as the line they follow, or a
    compaction's boundary as the one it continues, that no line before it
    carries, in the order they were named: a line of another file, or one
    written later."""
    requests: tuple[Requested, ...] = ()
    """The request lines before it written since the last one a Call named,
    in the file's order. A Call's first line names its request among them,
    and that one and those before it are no later Call's."""
    events: tuple[Occurred, ...] = ()
    """The Events before it where no Call is: the transcript's first Call
    marks them."""
    directory: str | None = None
    environment: str | None = None
    launch: Open | None = None
    """The Launch open there; none on a sub-agent's thread, before a main
    thread's first Launch and after an exit."""
    prompt: Prompted | None = None
    """The latest Prompt before it, where the Launch open there received
    it: a Stop hook's summary from it on, before the next Prompt, lies on
    that one."""
    opening: Opening | None = None
    """What the lines before it record of the Context Parts of the Launch
    open there's first Call, where that Call has not begun: on a sub-agent's
    thread, before its first Call."""
    injected: tuple[Part, ...] = ()
    """The Context Parts the lines before it injected since the last Call's
    first line, or the start of the Launch open there, in the file's order:
    the next Call carries them."""
    queue: tuple[tuple[bytes, datetime], ...] = ()
    """The prompts waiting in the process's queue there, in the order they
    arrived: a digest of each one's text and the time of its `enqueue`
    line."""
    removed: tuple[tuple[bytes, datetime], ...] = ()
    """The prompts a `remove` took out of the queue before it that no
    message taken in the middle of a run has claimed, in the order they were
    taken out, as the queue holds them."""


@dataclass(frozen=True)
class Carry:
    """One transcript's carry: the file a reading was built on, and where
    that reading stands at its boundary."""

    file_size: int
    file_modified_at: datetime
    collector: str
    """The collector's version that read it."""
    stands: Standing
    end: bytes
    """A digest of the file's bytes from the boundary's on, as they were
    read."""

    @property
    def size(self) -> int:
        """The bytes of memory the carry is counted at."""
        stands = self.stands
        left = stands.leads.left
        prompt = stands.prompt
        runs = () if prompt is None else prompt.runs
        opening = stands.opening
        files = () if opening is None else opening.files
        shapes = [asked.sends for asked in stands.requests if asked.sends is not None]
        if opening is not None and opening.snapshot is not None:
            shapes.append(opening.snapshot)
        words = (
            stands.link,
            stands.leads.call,
            stands.directory,
            stands.environment,
            self.collector,
            *stands.awaited,
            *(word for asked in stands.requests for word in (asked.id, asked.shape)),
            *(event.detail for event in stands.events),
            *(
                ()
                if left is None
                else (left.model, left.effort, left.version, left.shape)
            ),
            *(() if prompt is None else (prompt.source,)),
            *(run.command for run in runs),
            *(path for path, _ in files),
            *(part.name for part in stands.injected),
        )
        return (
            _HELD
            + sum(len(word) for word in words if word is not None)
            + (0 if left is None else _LEFT)
            + (0 if prompt is None else _PROMPTED)
            + _RAN * len(runs)
            + (0 if opening is None else _OPENING)
            + _FILE * len(files)
            + _PART * len(stands.injected)
            + _SHAPE * len(shapes)
            + _AWAITED * len(stands.awaited)
            + _REQUESTED * len(stands.requests)
            + _OCCURRED * len(stands.events)
            + _QUEUED * (len(stands.queue) + len(stands.removed))
        )


class Carries:
    """The carries of the transcripts a collector published, by their file,
    within the bound."""

    def __init__(self, transcripts: int, size: int) -> None:
        self._transcripts = transcripts
        self._size = size
        self._held: dict[Path, Carry] = {}
        self._counted = 0

    def __len__(self) -> int:
        return len(self._held)

    @property
    def size(self) -> int:
        """The bytes the carries held are counted at."""
        return self._counted

    def get(self, path: Path) -> Carry | None:
        return self._held.get(path)

    def keep(self, path: Path, carry: Carry) -> None:
        """Hold `carry` for the transcript filed at `path`, in place of the
        one held for it, and for as long as the bound is passed forget the
        carry whose file changed longest ago, `carry` itself where it is
        that one."""
        self.forget(path)
        self._held[path] = carry
        self._counted += carry.size
        while len(self._held) > self._transcripts or self._counted > self._size:
            self.forget(min(self._held, key=self._changed))

    def _changed(self, path: Path) -> datetime:
        return self._held[path].file_modified_at

    def forget(self, path: Path) -> None:
        carry = self._held.pop(path, None)
        if carry is not None:
            self._counted -= carry.size
