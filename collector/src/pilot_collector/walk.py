"""The collector's walk (F152.2): the home compared with Pilot's inventory,
and each transcript the inventory lacks or holds differently published, one
call per transcript.

A walk takes Pilot's inventory, lists every transcript on the home with a
`stat`, and publishes in two turns:

- **New or changed**: a transcript the inventory lacks, or holds at another
  size or time than its file's. Every one is published, the most recently
  changed first.
- **Behind**: a transcript held at its file's size and time that differs
  otherwise: read under another version of the collector's, or due its replay
  at rest (F152.16), which is one whose `replayed_size` is short of its
  `file_size`, appended publications having been taken since its last whole
  one, and whose file has not changed for the settling time. The most
  recently changed first, until the walk's interval has passed since the walk
  began; the rest wait for the next walk.

Every publication is whole. A transcript Pilot holds and the home lacks is
left alone, as is a symlink (F119.2).

After its last publication the walk tells Pilot it ended, whether it
published or not. A walk Pilot does not admit, or cannot be reached by, ends
where it stands and tells no end; the next starts over from the inventory.

A transcript the collector cannot read, and one Pilot refuses for good, is
logged with its file and the reason and set aside: no walk takes it again
until its file's size or time changes. What is set aside is in the
collector's memory alone, so a restart logs each once more.

Walks run one after another on one thread, a walk's start the interval after
the start of the one before, or at once where that one took longer. The
interval and the settling time are Pilot's, which each inventory hands over.
"""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pilot_collection.inventory import InventorySchema

from pilot_collector import VERSION
from pilot_collector.home import Listed, transcripts
from pilot_collector.pilot import NotAdmitted, Pilot, Refused, Unreachable
from pilot_collector.reader import UnreadableError, read
from pilot_collector.settings import Settings

logger = logging.getLogger(__name__)

_PROJECTS = "projects"
"""The folder of the home that holds the transcripts."""

_UNASKED = 30.0
"""Seconds from a walk's start to the next one's while no inventory has
given the interval: the server's default for it."""


@dataclass(frozen=True)
class Work:
    """What a walk publishes, each turn in the order it is taken."""

    changed: list[Listed]
    behind: list[Listed]


@dataclass
class Walked:
    """How a walk went."""

    listed: int = 0
    published: int = 0
    set_aside: int = 0
    waiting: int = 0
    """The transcripts left for the next walk, the interval having passed."""
    ended: bool = False
    """Whether Pilot was told the walk ended."""


def _newest_first(found: list[Listed]) -> list[Listed]:
    return sorted(
        found,
        key=lambda each: (each.file_modified_at, each.transcript.name),
        reverse=True,
    )


def plan(listed: list[Listed], inventory: InventorySchema, now: datetime) -> Work:
    """The transcripts of `listed` that `inventory` lacks or holds
    differently at the moment `now`, in the walk's two turns."""
    held = {(each.session_id, each.agent_id): each for each in inventory.transcripts}
    settling = timedelta(seconds=inventory.settling_seconds)
    changed: list[Listed] = []
    behind: list[Listed] = []
    for each in listed:
        holds = held.get((each.transcript.session_id, each.transcript.agent_id))
        if (
            holds is None
            or holds.file_size != each.file_size
            or holds.file_modified_at != each.file_modified_at
        ):
            changed.append(each)
        elif holds.collector != VERSION or (
            holds.replayed_size < holds.file_size
            and now - each.file_modified_at >= settling
        ):
            behind.append(each)
    return Work(_newest_first(changed), _newest_first(behind))


class Walker:
    """Walks one home for one Pilot, a walk at a time, until `stop` is
    set."""

    def __init__(self, pilot: Pilot, settings: Settings, stop: threading.Event) -> None:
        self.interval = _UNASKED
        self._pilot = pilot
        self._settings = settings
        self._stop = stop
        self._projects = settings.COLLECTOR_HOME / _PROJECTS
        self._aside: dict[Path, tuple[int, datetime]] = {}
        """The transcripts set aside, by their file: its size and time as
        the walk that set it aside listed it."""

    def run(self) -> None:
        """Walk every interval until `stop` is set."""
        while not self._stop.is_set():
            began = time.perf_counter()
            self.walk()
            self._stop.wait(max(0.0, began + self.interval - time.perf_counter()))

    def walk(self) -> Walked:
        """One walk, to its end or to where Pilot stops answering."""
        began = time.perf_counter()
        walked = Walked()
        try:
            self._walk(walked, began)
        except NotAdmitted as error:
            logger.error("The walk ended early: %s", error)
        except Unreachable as error:
            logger.warning("The walk ended early: %s", error)
        logger.log(
            logging.INFO
            if walked.published or walked.set_aside or walked.waiting
            else logging.DEBUG,
            "A walk over %d transcripts: %d published, %d set aside, %d left"
            " for the next walk, in %.1f s%s",
            walked.listed,
            walked.published,
            walked.set_aside,
            walked.waiting,
            time.perf_counter() - began,
            "" if walked.ended else "; Pilot was not told it ended",
        )
        return walked

    def _walk(self, walked: Walked, began: float) -> None:
        inventory = self._pilot.inventory()
        self.interval = inventory.walk_interval_seconds
        listed = transcripts(self._projects)
        walked.listed = len(listed)
        stands = {
            each.transcript.path: (each.file_size, each.file_modified_at)
            for each in listed
        }
        self._aside = {
            path: stood
            for path, stood in self._aside.items()
            if stands.get(path) == stood
        }
        work = plan(
            [each for each in listed if each.transcript.path not in self._aside],
            inventory,
            datetime.now(UTC),
        )
        for each in work.changed:
            if self._stop.is_set():
                return
            self._publish(each, walked)
        for place, each in enumerate(work.behind):
            if self._stop.is_set():
                return
            if time.perf_counter() - began >= self.interval:
                walked.waiting = len(work.behind) - place
                break
            self._publish(each, walked)
        self._pilot.end_walk()
        walked.ended = True

    def _publish(self, listed: Listed, walked: Walked) -> None:
        try:
            publication = read(listed.transcript, self._settings)
        except FileNotFoundError as error:
            if error.filename != str(listed.transcript.path):
                self._set_aside(listed, walked, f"it cannot be read: {error}")
            return
        except (UnreadableError, OSError) as error:
            self._set_aside(listed, walked, f"it cannot be read: {error}")
            return
        except Exception as error:
            # A file's lines can make the reader raise what it does not turn
            # into an UnreadableError.
            self._set_aside(
                listed, walked, f"reading it raised {type(error).__name__}: {error}"
            )
            return
        try:
            self._pilot.publish(publication)
        except Refused as error:
            self._set_aside(listed, walked, f"Pilot refused it with {error}")
            return
        walked.published += 1

    def _set_aside(self, listed: Listed, walked: Walked, reason: str) -> None:
        self._aside[listed.transcript.path] = (
            listed.file_size,
            listed.file_modified_at,
        )
        walked.set_aside += 1
        logger.warning(
            "The transcript %s, %s, is set aside until its file changes: %s",
            listed.transcript.name,
            listed.transcript.path,
            reason,
        )
