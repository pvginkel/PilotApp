"""The collector's walk (F152.2): the home compared with Pilot's inventory,
and each transcript the inventory lacks or holds differently published, one
call per transcript.

A walk takes Pilot's inventory, lists every transcript on the home with a
`stat`, and publishes in two turns:

- **New or changed**: a transcript the inventory lacks, or holds at another
  size or time than its file's. Every one is published, the most recently
  changed first.
- **Behind**: a transcript held at its file's size and time that differs
  otherwise: read under another version of the collector's, due its replay
  at rest (F152.16), which is one whose `replayed_size` is short of its
  `file_size`, appended publications having been taken since its last whole
  one, and whose file has not changed for the settling time, or, where a
  labeller answers, labelled under another major of the labeller's version
  than the one answering, or under another stamp than the one it would give
  now (F152.6, F152.7). The most recently changed first, until the walk's
  interval has passed since the walk began, the time the stamps and their
  declaration took not counted; the rest wait for the next walk.

A transcript Pilot holds and the home lacks is left alone, as is a symlink
(F119.2).

**Whole or appended** (F152.15). The walk keeps a carry of each transcript
it published (`carry.py`). A transcript whose file is new or changed, and
that the inventory holds at exactly what its carry was built on, the file's
size and time and the collector's version, is read from the carry's boundary
on and published appended. Where the labeller answers for it, the carry must
also hold the checkpoint the labeller handed back with its last labels,
built on the stamp and under the major of the labeller's version that Pilot
holds its labels under and that the labeller would give now: the labeller is
then handed the Calls from that boundary on with the checkpoint, and the
appended publication carries their labels. Every other is published whole,
and so is one, in the same walk and logged with the reason, whose carry the
file does not continue (F152.17), whose lines reach behind the boundary,
that the labeller answers `whole` for, or whose appended publication Pilot
refuses; those the labeller answers for are read and labelled whole once the
rest of their batch is published.

**The labeller** (F152.6, F152.7). After the listing a walk asks the
workflow's labeller, in one call, the stamp it would give now for every
transcript on the home (`labeller.py`). It declares the labeller's
vocabularies to Pilot once after the collector starts, and again whenever
the stamps come from another version of the labeller's, or name another
digest of its declarations, than those it last declared. A walk that no
labeller answers, or whose vocabularies Pilot refuses, publishes as it
would with none, and the reason is logged where it differs from the last
walk's. The walk's line says what the stamps took.

Where the labeller answers, each turn is published in batches, a batch
labelled in one call: each transcript it gives a stamp is read, whole or
appended, and handed with what the inventory gives for its conversation, and
published with the labels the labeller gives of it, under the version its
answer names, which is declared to Pilot first where it is another than the
last declared. A transcript it labels nothing of, an error in its answer or one
its answer was cut short of, is published as with no labeller where its file
is new or changed or the collector's version or the replay at rest makes it
differ, and is left for the next walk where only the labeller does. A call
that gives no answer, or is cut short, labels nothing further in the walk.

Pilot refusing a transcript's labels has the vocabularies declared again,
once a walk, and the labels published again; refused once more, the
transcript is published as with no labeller, and, where Pilot took that
declaration, its labels are not given again until its file, the labeller's
version or the stamp it would give now changes. What is refused is in the
collector's memory alone.

After its last publication the walk tells Pilot it ended, whether it
published or not. A walk Pilot does not admit, or cannot be reached by, ends
where it stands and tells no end; the next starts over from the inventory.

**The clones and the Files** (F152.11, F158.5). After it ended, the first
walk after the collector starts, and then the first once the settings'
`COLLECTOR_MIRROR_SECONDS` have passed since the last read began, reads the
clones of the mirror of every Repository Pilot holds (`mirror.py`) and gives
Pilot what each gave, a Repository's read in one call where it fits; a
walk that left transcripts of its behind turn for the next waits for one
that did not, so that a Repository is read after every transcript on the
home is published, since Pilot's tie settles a commit's hash before its
subject within one call alone. A Repository whose clone cannot be made, fetched or
read is logged where its reason is new, and read again at the next read.
Then, where the labeller answered the stamps, it has the labeller class the
Files Pilot holds with no class, or every File where the stamps' file rules
are other than those it last classed every File under, after a start among
them, and gives Pilot their classes (`labeller.md` § File classes): a walk
where nothing changed asks Pilot for no File beyond the knowledge that none
waits. A labeller that gives no classes is asked again at the next walk,
and logged where its reason is new. Classes Pilot refuses have the
vocabularies declared again and are given once more; refused again, no File
is classed until the labeller's version or its file rules change.

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
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pilot_collection.inventory import HeldTranscriptSchema, InventorySchema
from pilot_collection.publication import PublicationSchema, PublishedGroupSchema

from pilot_collector import VERSION
from pilot_collector.carry import Carries, Carry
from pilot_collector.home import PROJECTS, Listed, transcripts
from pilot_collector.labeller import (
    Classed,
    Labelled,
    Labeller,
    Labels,
    Stamps,
    Unanswered,
    labelled,
    major,
)
from pilot_collector.mirror import Clones, Unread
from pilot_collector.pilot import (
    NotAdmitted,
    NotAdoptable,
    NotAppendable,
    Pilot,
    Refused,
    Unreachable,
)
from pilot_collector.reader import NotContinuedError, Read, UnreadableError, read
from pilot_collector.settings import Settings

logger = logging.getLogger(__name__)

_UNASKED = 30.0
"""Seconds from a walk's start to the next one's while no inventory has
given the interval: the server's default for it."""

_BATCH = 64
"""The most transcripts a batch holds."""

_BATCH_BYTES = 32_000_000
"""The bytes of its files past which a batch takes no further transcript."""

type Refusal = tuple[int, datetime, str, str]
"""What labels Pilot refused were given under: the file's size and time,
the labeller's version and the stamp."""

type Turn = Literal["changed", "behind"]


@dataclass(frozen=True)
class Work:
    """What a walk publishes, each turn in the order it is taken."""

    changed: list[Listed]
    behind: list[Listed]
    labels_alone: frozenset[Path] = frozenset()
    """The files of those behind that the labeller alone makes differ."""


@dataclass
class Walked:
    """How a walk went."""

    listed: int = 0
    published: int = 0
    appended: int = 0
    """Those of the published that were published appended."""
    labelled: int = 0
    """Those of the published that carried the labeller's labels."""
    set_aside: int = 0
    waiting: int = 0
    """The transcripts left for the next walk: the interval had passed, or
    only the labeller made them differ and it gave them no labels."""
    ended: bool = False
    """Whether Pilot was told the walk ended."""
    stamps: Stamps | None = None
    """The labeller's stamps of the walk; none where no labeller answered,
    or Pilot refused its vocabularies."""
    commits: int = 0
    """The commits the clones gave Pilot."""
    classed: int = 0
    """The Files whose classes Pilot was given."""


def _newest_first(found: list[Listed]) -> list[Listed]:
    return sorted(
        found,
        key=lambda each: (each.file_modified_at, each.transcript.name),
        reverse=True,
    )


def _held(
    inventory: InventorySchema,
) -> dict[tuple[str, str | None], HeldTranscriptSchema]:
    """What the inventory holds, by a transcript's two ids."""
    return {(each.session_id, each.agent_id): each for each in inventory.transcripts}


def labelled_under(
    listed: Listed, stamps: Stamps | None, refused: Mapping[Path, Refusal]
) -> str | None:
    """The stamp the labeller's labels of the transcript would be given
    under now; none where no labeller answers, it gives the transcript no
    stamp, or Pilot refused its labels under that stamp, the labeller's
    version and its file as it stands."""
    if stamps is None:
        return None
    stamp = stamps.stamps.get(
        (listed.transcript.session_id, listed.transcript.agent_id)
    )
    given = (listed.file_size, listed.file_modified_at, stamps.version, stamp)
    if stamp is None or refused.get(listed.transcript.path) == given:
        return None
    return stamp


def plan(
    listed: list[Listed],
    inventory: InventorySchema,
    now: datetime,
    stamps: Stamps | None = None,
    refused: Mapping[Path, Refusal] | None = None,
) -> Work:
    """The transcripts of `listed` that `inventory` lacks or holds
    differently at the moment `now`, in the walk's two turns, where the
    labeller answered `stamps` and Pilot refused the labels `refused`
    names."""
    held = _held(inventory)
    settling = timedelta(seconds=inventory.settling_seconds)
    changed: list[Listed] = []
    behind: list[Listed] = []
    alone: set[Path] = set()
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
        elif (
            stamps is not None
            and (stamp := labelled_under(each, stamps, refused or {})) is not None
            and (
                holds.labeller is None
                or major(holds.labeller) != major(stamps.version)
                or holds.stamp != stamp
            )
        ):
            behind.append(each)
            alone.add(each.transcript.path)
    return Work(_newest_first(changed), _newest_first(behind), frozenset(alone))


def _batches(listed: list[Listed]) -> Iterator[list[Listed]]:
    """`listed` in its order, in batches: each of at most `_BATCH`
    transcripts, and past `_BATCH_BYTES` of files only its first."""
    batch: list[Listed] = []
    size = 0
    for each in listed:
        if batch and (len(batch) == _BATCH or size + each.file_size > _BATCH_BYTES):
            yield batch
            batch, size = [], 0
        batch.append(each)
        size += each.file_size
    if batch:
        yield batch


def _grew(line: Mapping[str, Any]) -> bool:
    """Whether a `label` answer's line is an error a file that changed since
    its reading gives: one whose Calls are not those handed, or one gone."""
    error = line.get("error")
    return (
        line.get("answer") == "error"
        and isinstance(error, dict)
        and error.get("code") in ("calls_mismatch", "unreadable")
    )


@dataclass
class _Labelling:
    """The labeller in one walk that it answered the stamps of."""

    stamps: Stamps
    inventory: InventorySchema
    answers: bool = True
    """Whether it labels further in the walk."""
    redeclared: bool | None = None
    """Whether the vocabularies a refusal of labels had declared again were
    taken by Pilot; none before a refusal had them declared."""


class Walker:
    """Walks one home for one Pilot, a walk at a time, until `stop` is
    set."""

    def __init__(self, pilot: Pilot, settings: Settings, stop: threading.Event) -> None:
        self.interval = _UNASKED
        self._pilot = pilot
        self._settings = settings
        self._stop = stop
        self._projects = settings.COLLECTOR_HOME / PROJECTS
        self._aside: dict[Path, tuple[int, datetime]] = {}
        """The transcripts set aside, by their file: its size and time as
        the walk that set it aside listed it."""
        self._carries = Carries(
            settings.COLLECTOR_CARRY_TRANSCRIPTS, settings.COLLECTOR_CARRY_BYTES
        )
        self._labeller = Labeller(settings)
        self._declared: tuple[str, str] | None = None
        """The labeller's version and the digest of its declarations that
        Pilot was last declared the vocabularies of."""
        self._groups: dict[str, PublishedGroupSchema] = {}
        """The groups the labeller declared then, by their key."""
        self._refused: dict[Path, Refusal] = {}
        """The transcripts Pilot refused the labels of, by their file: what
        the labels were given under, the file as the walk listed it."""
        self._unlabelled: str | None = None
        """Why the last walk had no labeller's stamps; none where it had."""
        self._clones = Clones(settings)
        self._mirror_seconds = settings.COLLECTOR_MIRROR_SECONDS
        self._mirrored: float | None = None
        """When the last read of the clones began; none before the first."""
        self._unread: dict[str, str] = {}
        """Each Repository whose clone was not read at the last read, by its
        name: why."""
        self._classed_under: str | None = None
        """The labeller's file rules the collector last classed every File
        Pilot holds under; none after a start."""
        self._unclassable: tuple[str, str] | None = None
        """The labeller's version and file rules whose classes Pilot refused
        twice; none where it took the last."""
        self._unclassed: str | None = None
        """Why the labeller gave no classes at the last walk that asked;
        none where it gave them."""

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
            "A walk over %d transcripts: %d published, %d of them appended and %d"
            " labelled, %d set aside, %d left for the next walk, in %.1f s; %s%s",
            walked.listed,
            walked.published,
            walked.appended,
            walked.labelled,
            walked.set_aside,
            walked.waiting,
            time.perf_counter() - began,
            "no labeller's stamps"
            if walked.stamps is None
            else f"the labeller {walked.stamps.version}'s stamps took"
            f" {walked.stamps.seconds:.2f} s",
            "" if walked.ended else "; Pilot was not told it ended",
        )
        return walked

    def _walk(self, walked: Walked, began: float) -> None:
        inventory = self._pilot.inventory()
        self.interval = inventory.walk_interval_seconds
        listed = transcripts(self._projects)
        walked.listed = len(listed)
        asked = time.perf_counter()
        walked.stamps = self._stamped(listed, inventory)
        began += time.perf_counter() - asked
        stands = {
            each.transcript.path: (each.file_size, each.file_modified_at)
            for each in listed
        }
        self._aside = {
            path: stood
            for path, stood in self._aside.items()
            if stands.get(path) == stood
        }
        self._refused = {
            path: given
            for path, given in self._refused.items()
            if stands.get(path) == given[:2]
        }
        work = plan(
            [each for each in listed if each.transcript.path not in self._aside],
            inventory,
            datetime.now(UTC),
            walked.stamps,
            self._refused,
        )
        held = _held(inventory)
        labelling = (
            None if walked.stamps is None else _Labelling(walked.stamps, inventory)
        )
        for batch in _batches(work.changed):
            if not self._batch(batch, "changed", held, labelling, work, walked):
                return
        taken = 0
        left = False
        for batch in _batches(work.behind):
            if time.perf_counter() - began >= self.interval:
                walked.waiting += len(work.behind) - taken
                left = True
                break
            if not self._batch(batch, "behind", held, labelling, work, walked):
                return
            taken += len(batch)
        self._pilot.end_walk()
        walked.ended = True
        if not left and not self._stop.is_set():
            self._read_clones(walked)
        if walked.stamps is not None and not self._stop.is_set():
            self._classify(walked.stamps, walked)

    def _stamped(
        self, listed: list[Listed], inventory: InventorySchema
    ) -> Stamps | None:
        """The labeller's stamps of every transcript of `listed`, its
        vocabularies declared to Pilot first where they are other than those
        last declared; none where no labeller answers, or Pilot refuses its
        vocabularies, which is logged where the reason is new."""
        try:
            stamps = self._labeller.stamps(listed, inventory)
            if (stamps.version, stamps.declarations) != self._declared:
                self._declare(stamps.declarations)
        except Unanswered as error:
            why = f"the labeller did not answer: {error}"
        except Refused as error:
            why = f"Pilot refused the labeller's vocabularies with {error}"
        else:
            if self._unlabelled is not None:
                logger.info("The labeller %s answers again", stamps.version)
            self._unlabelled = None
            return stamps
        if why != self._unlabelled:
            logger.warning(
                "The walk has no labeller's stamps, and publishes no label: %s",
                why,
            )
        self._unlabelled = why
        return None

    def _read_clones(self, walked: Walked) -> None:
        """Read the clone of every Repository Pilot holds and give Pilot what
        each gave, where no read was made since the collector started or
        `_mirror_seconds` have passed since the last began."""
        now = time.monotonic()
        if self._mirrored is not None and now - self._mirrored < self._mirror_seconds:
            return
        self._mirrored = now
        began = time.perf_counter()
        given = 0
        for held in self._pilot.repositories().repositories:
            if self._stop.is_set():
                return
            try:
                reads = self._clones.read(held)
            except Unread as error:
                if self._unread.get(held.name) != str(error):
                    logger.warning(
                        "The clone of the Repository %s is not read: %s",
                        held.name,
                        error,
                    )
                self._unread[held.name] = str(error)
                continue
            if self._unread.pop(held.name, None) is not None:
                logger.info("The clone of the Repository %s is read again", held.name)
            for part in reads:
                try:
                    self._pilot.read(part)
                except Refused as error:
                    logger.warning(
                        "Pilot refused the read of the Repository %s with %s",
                        held.name,
                        error,
                    )
                    break
                walked.commits += len(part.commits)
                given += 1
        logger.log(
            logging.INFO if given else logging.DEBUG,
            "The clones gave Pilot %d commits in %d calls, in %.1f s",
            walked.commits,
            given,
            time.perf_counter() - began,
        )

    def _classify(self, stamps: Stamps, walked: Walked) -> None:
        """Have the labeller class the Files Pilot holds with no class, or
        every File where the file rules of `stamps` are other than those
        every File was last classed under, and give Pilot their classes;
        none while Pilot refuses those of the labeller's version and file
        rules as they stand. Where it gives none the reason is logged where
        it differs from the last, and where Pilot refuses them it is
        logged."""
        if (stamps.version, stamps.file_rules) == self._unclassable:
            return
        every = stamps.file_rules != self._classed_under
        files = self._pilot.files(unclassed=not every).files
        if not files:
            if every:
                self._classed_under = stamps.file_rules
            return
        try:
            classed = self._labeller.classes(files)
            self._classes_given(classed, stamps)
        except Unanswered as error:
            if str(error) != self._unclassed:
                logger.warning(
                    "No File is classed in this walk: the labeller did not answer: %s",
                    error,
                )
            self._unclassed = str(error)
            return
        except Refused as error:
            self._unclassed = None
            self._unclassable = (classed.version, classed.file_rules)
            logger.warning(
                "No File is classed until the labeller's version or its file rules"
                " change: %s",
                error,
            )
            return
        if every:
            self._classed_under = classed.file_rules
        self._unclassed = None
        self._unclassable = None
        walked.classed = len(files)
        logger.info(
            "%d Files are classed under the labeller %s's file rules",
            len(files),
            classed.version,
        )

    def _classes_given(self, classed: Classed, stamps: Stamps) -> None:
        """Give Pilot the classes `classed`, the vocabularies of its version
        declared first where Pilot was last declared another's, and declared
        again and given once more where Pilot refuses them.

        Raises:
            Unanswered: The labeller gave its vocabularies no answer.
            Refused: Pilot refused the vocabularies, or the classes twice.
        """
        if self._declared is None or classed.version != self._declared[0]:
            self._declare(stamps.declarations)
        try:
            self._pilot.classify(classed.classes)
        except Refused:
            self._declare(stamps.declarations)
            self._pilot.classify(classed.classes)

    def _declare(self, declarations: str) -> None:
        """Declare the labeller's vocabularies to Pilot, and keep its
        groups, as those of the digest `declarations`.

        Raises:
            Unanswered: The labeller gave its vocabularies no answer.
            Refused: Pilot refused them.
        """
        declared = self._labeller.vocabularies()
        self._pilot.declare(declared.vocabularies)
        self._declared = (declared.vocabularies.version, declarations)
        self._groups = declared.groups
        logger.info(
            "The vocabularies of the labeller %s are declared to Pilot",
            declared.vocabularies.version,
        )

    def _batch(
        self,
        batch: list[Listed],
        turn: Turn,
        held: dict[tuple[str, str | None], HeldTranscriptSchema],
        labelling: _Labelling | None,
        work: Work,
        walked: Walked,
    ) -> bool:
        """Publish a batch of one turn, those the labeller answers for with
        its labels, and then, read and labelled whole, those of them to be
        published whole instead. False where the walk was told to stop."""
        asked: dict[Path, Read | None] = {}
        if labelling is not None and labelling.answers:
            for each in batch:
                if labelled_under(each, labelling.stamps, self._refused) is not None:
                    if self._stop.is_set():
                        return False
                    ids = (each.transcript.session_id, each.transcript.agent_id)
                    asked[each.transcript.path] = self._taken(
                        each, turn, held.get(ids), labelling, walked
                    )
        taken = [
            (each, reading)
            for each in batch
            if (reading := asked.get(each.transcript.path)) is not None
        ]
        labels = (
            None if not taken or labelling is None else self._labels(taken, labelling)
        )
        again: list[Listed] = []
        for each in batch:
            if self._stop.is_set():
                return False
            path = each.transcript.path
            if path in asked:
                reading = asked[path]
                if reading is not None and not self._publish_labelled(
                    each,
                    reading,
                    labels,
                    labelling,
                    path in work.labels_alone,
                    walked,
                ):
                    again.append(each)
            elif path in work.labels_alone:
                walked.waiting += 1
            elif turn == "changed":
                ids = (each.transcript.session_id, each.transcript.agent_id)
                self._publish_changed(each, held.get(ids), walked)
            else:
                self._publish(each, walked)
        return not again or self._whole_instead(again, labelling, walked)

    def _whole_instead(
        self, again: list[Listed], labelling: _Labelling | None, walked: Walked
    ) -> bool:
        """Read the transcripts of `again` whole, label them in one call and
        publish them, their labels with each where the labeller gives them.
        False where the walk was told to stop."""
        readings: list[tuple[Listed, Read]] = []
        for each in again:
            if self._stop.is_set():
                return False
            reading = self._read(each, walked)
            if reading is not None:
                readings.append((each, reading))
        labels = (
            self._labels(readings, labelling)
            if readings and labelling is not None and labelling.answers
            else None
        )
        for each, reading in readings:
            if self._stop.is_set():
                return False
            self._publish_labelled(each, reading, labels, labelling, False, walked)
        return True

    def _taken(
        self,
        listed: Listed,
        turn: Turn,
        holds: HeldTranscriptSchema | None,
        labelling: _Labelling,
        walked: Walked,
    ) -> Read | None:
        """The transcript read for the labeller: from the boundary of its
        carry on where its file is new or changed and the carry allows,
        else whole. None where it cannot be read, which sets it aside, or
        its file is gone."""
        carry = self._carries.get(listed.transcript.path) if turn == "changed" else None
        taken = (
            None if carry is None else self._continued(listed, holds, carry, labelling)
        )
        return self._read(listed, walked) if taken is None else taken

    def _continued(
        self,
        listed: Listed,
        holds: HeldTranscriptSchema | None,
        carry: Carry,
        labelling: _Labelling | None = None,
    ) -> Read | None:
        """The transcript, which the inventory holds as `holds`, read from
        the boundary of `carry` on, to be labelled from there on where
        `labelling` is given; none, with the reason logged, where it is to be
        read whole instead."""
        why = self._unappendable(listed, holds, carry, labelling)
        if why is None:
            try:
                return read(listed.transcript, self._settings, carry)
            except NotContinuedError as error:
                why = str(error)
            except Exception as error:
                # A file's lines can make the reader raise anything, as in
                # `_read`, where the whole reading meets the same lines.
                why = (
                    f"reading it from its boundary on raised {type(error).__name__}:"
                    f" {error}"
                )
        self._whole(listed, why)
        return None

    def _unappendable(
        self,
        listed: Listed,
        holds: HeldTranscriptSchema | None,
        carry: Carry,
        labelling: _Labelling | None,
    ) -> str | None:
        """Why the transcript is not read from the boundary of `carry` on,
        and labelled from there on where `labelling` is given; none where it
        is."""
        if holds is None or (
            holds.file_size,
            holds.file_modified_at,
            holds.collector,
        ) != (carry.file_size, carry.file_modified_at, carry.collector):
            return "Pilot does not hold it as it was last read"
        if labelling is None:
            return None
        checkpoint = carry.checkpoint
        if checkpoint is None:
            return "the labeller handed back no checkpoint of its last reading"
        if (
            holds.labeller is None
            or major(holds.labeller) != major(checkpoint.version)
            or holds.stamp != checkpoint.stamp
        ):
            return "Pilot does not hold its labels as the labeller last gave them"
        if major(labelling.stamps.version) != major(checkpoint.version) or (
            labelled_under(listed, labelling.stamps, self._refused) != checkpoint.stamp
        ):
            return (
                "the labeller would label it under another stamp or major now,"
                " which relabels it whole"
            )
        return None

    def _labels(
        self, taken: list[tuple[Listed, Read]], labelling: _Labelling
    ) -> Labels | None:
        """The labeller's labels of the transcripts `taken` read, under a
        version Pilot was declared the vocabularies of; none where it gives
        none, and it then labels nothing further in the walk."""
        try:
            labels = self._labeller.label(taken, labelling.inventory)
        except Unanswered as error:
            self._labels_no_further(labelling, f"it did not answer: {error}")
            return None
        if labels.cut is not None:
            self._labels_no_further(
                labelling, f"its answer was cut short: {labels.cut}"
            )
        if self._declared is None or labels.version != self._declared[0]:
            if not self._declared_again(labelling):
                return None
            if self._declared is None or labels.version != self._declared[0]:
                self._labels_no_further(
                    labelling,
                    f"it labelled under {labels.version} and declares the"
                    " vocabularies of another version",
                )
                return None
        return labels

    def _declared_again(self, labelling: _Labelling) -> bool:
        """Declare the labeller's vocabularies to Pilot once more; false
        where that fails, and it then labels nothing further in the walk."""
        try:
            self._declare(labelling.stamps.declarations)
        except Unanswered as error:
            self._labels_no_further(
                labelling, f"its vocabularies gave no answer: {error}"
            )
            return False
        except Refused as error:
            self._labels_no_further(
                labelling, f"Pilot refused its vocabularies with {error}"
            )
            return False
        return True

    def _labels_no_further(self, labelling: _Labelling, why: str) -> None:
        labelling.answers = False
        logger.warning("The labeller labels nothing further in this walk: %s", why)

    def _publish_labelled(
        self,
        listed: Listed,
        taken: Read,
        labels: Labels | None,
        labelling: _Labelling | None,
        alone: bool,
        walked: Walked,
    ) -> bool:
        """Publish a transcript read for the labeller, with the labels
        `labels` give of it; with its facts alone where they give none or
        Pilot refuses them, unless only the labeller made it differ. False,
        with the reason logged, where it was read appended and is to be read
        and labelled whole instead."""
        ids = (listed.transcript.session_id, listed.transcript.agent_id)
        line = None if labels is None else labels.lines.get(ids)
        appended = taken.publication.appended is not None
        given: Labelled | None = None
        if line is not None and labels is not None:
            if appended and line.get("answer") == "whole":
                return self._whole(
                    listed, f"the labeller answered whole: {line.get('why')}"
                )
            try:
                given = self._labelled(taken, line, labels)
            except Unanswered as error:
                logger.log(
                    logging.INFO if _grew(line) else logging.WARNING,
                    "The labeller gave the transcript %s, %s, no labels: %s",
                    listed.transcript.name,
                    listed.transcript.path,
                    error,
                )
        if given is not None and labelling is not None:
            try:
                refused = self._refusal(given.publication)
                if refused is not None and labelling.redeclared is None:
                    labelling.redeclared = self._declared_again(labelling)
                    if labelling.redeclared:
                        refused = self._refusal(given.publication)
            except NotAppendable as error:
                return self._whole(listed, f"Pilot refused it appended: {error}")
            if refused is None:
                self._carries.keep(
                    listed.transcript.path, taken.carried(given.checkpoint)
                )
                walked.published += 1
                walked.appended += appended
                walked.labelled += 1
                return True
            declared = bool(labelling.redeclared)
            stamp = labelling.stamps.stamps.get(ids)
            if declared and stamp is not None:
                self._refused[listed.transcript.path] = (
                    listed.file_size,
                    listed.file_modified_at,
                    labelling.stamps.version,
                    stamp,
                )
            logger.warning(
                "Pilot refused the labels of the transcript %s, %s%s: %s",
                listed.transcript.name,
                listed.transcript.path,
                ", which are not given again until its file, the labeller's version"
                " or its stamp changes"
                if declared
                else "",
                refused,
            )
        if alone:
            walked.waiting += 1
        elif appended:
            return self._sent_appended(listed, taken, walked)
        else:
            self._send(listed, taken, walked)
        return True

    def _labelled(self, taken: Read, line: dict[str, Any], labels: Labels) -> Labelled:
        """The transcript's publication with the labels its `line` gives,
        and the checkpoint it hands back.

        Raises:
            Unanswered: The line gives it no labels the collector takes.
        """
        if line.get("answer") == "error":
            error = line.get("error")
            said = (
                f"{error.get('code')}: {error.get('detail')}"
                if isinstance(error, dict)
                else repr(error)
            )
            raise Unanswered(f"it answered an error, {said}")
        return labelled(taken, line, labels.version, self._groups)

    def _refusal(self, publication: PublicationSchema) -> Refused | None:
        """Pilot's refusal of the publication, published without its
        `group` where Pilot refuses that alone; none where it took it."""
        try:
            try:
                self._pilot.publish(publication)
            except NotAdoptable as error:
                logger.warning(
                    "The main thread %s is published with no group: %s",
                    publication.session_id,
                    error,
                )
                self._pilot.publish(publication.model_copy(update={"group": None}))
        except Refused as error:
            return error
        return None

    def _publish_changed(
        self, listed: Listed, holds: HeldTranscriptSchema | None, walked: Walked
    ) -> None:
        """Publish a transcript whose file is new or changed, which the
        inventory holds as `holds`: appended where its carry allows, else
        whole."""
        carry = self._carries.get(listed.transcript.path)
        if carry is None or not self._appended(listed, holds, carry, walked):
            self._publish(listed, walked)

    def _publish(self, listed: Listed, walked: Walked) -> None:
        """Publish one transcript whole."""
        taken = self._read(listed, walked)
        if taken is not None:
            self._send(listed, taken, walked)

    def _read(self, listed: Listed, walked: Walked) -> Read | None:
        """The transcript read whole; none where it cannot be, which sets it
        aside, or its file is gone."""
        try:
            return read(listed.transcript, self._settings)
        except FileNotFoundError as error:
            if error.filename != str(listed.transcript.path):
                self._set_aside(listed, walked, f"it cannot be read: {error}")
        except (UnreadableError, OSError) as error:
            self._set_aside(listed, walked, f"it cannot be read: {error}")
        except Exception as error:
            # A file's lines can make the reader raise what it does not turn
            # into an UnreadableError.
            self._set_aside(
                listed, walked, f"reading it raised {type(error).__name__}: {error}"
            )
        return None

    def _sent_appended(self, listed: Listed, taken: Read, walked: Walked) -> bool:
        """Publish what an appended reading took of the transcript, its facts
        alone. False, with the reason logged, where Pilot refuses it."""
        try:
            self._pilot.publish(taken.publication)
        except NotAppendable as error:
            return self._whole(listed, f"Pilot refused it appended: {error}")
        except Refused as error:
            return self._whole(listed, f"Pilot refused it appended with {error}")
        self._carries.keep(listed.transcript.path, taken.carry)
        walked.published += 1
        walked.appended += 1
        return True

    def _send(self, listed: Listed, taken: Read, walked: Walked) -> None:
        """Publish what a whole reading took of the transcript, its facts
        alone."""
        try:
            self._pilot.publish(taken.publication)
        except Refused as error:
            self._set_aside(listed, walked, f"Pilot refused it with {error}")
            return
        self._carries.keep(listed.transcript.path, taken.carry)
        walked.published += 1

    def _appended(
        self,
        listed: Listed,
        holds: HeldTranscriptSchema | None,
        carry: Carry,
        walked: Walked,
    ) -> bool:
        """Publish the transcript appended, read from the boundary of
        `carry` on, its facts alone. False, with the reason logged, where it
        is to be published whole instead."""
        taken = self._continued(listed, holds, carry)
        return taken is not None and self._sent_appended(listed, taken, walked)

    def _whole(self, listed: Listed, reason: str) -> bool:
        logger.info(
            "The transcript %s, %s, is published whole, not from its boundary on: %s",
            listed.transcript.name,
            listed.transcript.path,
            reason,
        )
        return False

    def _set_aside(self, listed: Listed, walked: Walked, reason: str) -> None:
        self._carries.forget(listed.transcript.path)
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
