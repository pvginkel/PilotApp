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
lines from there on continue: how many Calls, published Launches and Prompts
lie before it, the last line before it that lines link to, the directory and
the environment the file named first, the Launch open there, and the prompts
waiting in the queue. No id of any other line before the boundary is held.

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

_HELD = 1_024
"""The bytes a carry is counted at beside its words and its queue."""

_QUEUED = 176
"""The bytes a prompt waiting in the queue is counted at."""


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
    link: str | None = None
    """The `uuid` of the last line before it that carries one."""
    directory: str | None = None
    environment: str | None = None
    launch: Open | None = None
    """The Launch open there; none on a sub-agent's thread, before a main
    thread's first Launch and after an exit."""
    queue: tuple[tuple[bytes, datetime], ...] = ()
    """The prompts waiting in the process's queue there, in the order they
    arrived: a digest of each one's text and the time of its `enqueue`
    line."""


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
        words = (stands.link, stands.directory, stands.environment, self.collector)
        return (
            _HELD
            + sum(len(word) for word in words if word is not None)
            + _QUEUED * len(stands.queue)
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
