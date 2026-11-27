"""The workflow's labeller as the collector runs it (F152.6, F152.7): the
command the collector's settings name, by default the installed `dev`
plugin's copy, which the home's `plugins/installed_plugins.json` names, with
each call's verb appended; one JSON request on its stdin and one answer on
its stdout, under the labeller's contract 1 (the plugin's `docs/labeller.md`
§ Running it). Nothing of the workflow is the collector's: the labeller's
lists, its stamps, its index and its files' classes are taken as it hands
them.

Every request names the contract and the home as the collector sees it, its
`projects` and its `plugins`. Four verbs are called here:

- `stamps`, at every walk: the stamp the labeller would give now for every
  transcript on the home, each handed in its conversation with what Pilot's
  inventory gives for that conversation, a sub-agent's with its
  `agent_type`, and each with the stamp Pilot holds for it; with the index
  the last call handed back, which the collector keeps in its memory
  (§ The stamp).
- `vocabularies`: every list the labeller declares, its nestings and its
  groups, of which Pilot takes the version, the nestings and the lists its
  shape names, and a main thread's publication the group its labels name
  (§ The vocabularies).
- `label`, over a batch of transcripts: each handed as `stamps` hands it,
  with its file's path, its Launches and the Calls the labeller reads in it,
  labelled whole, or, read from a carry that holds the labeller's
  checkpoint, from that checkpoint's boundary on, with the checkpoint (F152.15);
  its answer one line per transcript, its labels, the answer `whole` or an
  error, of which a publication carries the labels of the rows it holds and
  the carry the checkpoint it hands back (§ The label request and answer;
  § Settled, the boundary and the checkpoint).
- `classes`: the class of each File Pilot holds that it is handed, by its
  Repository's name and its path, and the digest of the rules it classed
  them under (§ File classes).

A call that gives no answer the collector takes raises `Unanswered`: no copy
installed, a refusal (exit 2), a crash (exit 1), no answer within the time
the settings give, or an answer that is not the call's. A `label` call cut
short by a crash or by its time keeps the lines it gave before the cut.
"""

import json
import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pilot_collection.files import FileClassesSchema, FileClassSchema, HeldFileSchema
from pilot_collection.inventory import InventorySchema
from pilot_collection.publication import (
    PublicationSchema,
    PublishedGroupSchema,
    PublishedLabellingSchema,
)
from pilot_collection.vocabularies import DeclaredListsSchema, VocabulariesSchema
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pilot_collector.carry import Checkpoint
from pilot_collector.home import PROJECTS, Listed, record_of
from pilot_collector.reader import Read
from pilot_collector.settings import INSTALL_PATH, Settings

CONTRACT = 1
"""The labeller's contract the collector speaks."""

PLUGIN = "dev@aiworkflow"
"""The installed plugin whose copy holds the labeller."""

PLUGINS = "plugins"
"""The folder of the home that holds Claude Code's plugins."""

INSTALLED = "installed_plugins.json"
"""The file in it that names each installed plugin's copy."""

_CACHE = "cache"
"""The folder of `plugins` that holds each installed copy, as
`cache/<marketplace>/<plugin>/<version>`."""

_SAID = 2_000
"""The characters of what a failed call said that a message quotes."""

_UNKEPT = ("batchable_condition",)
"""What a Call's labels hold that Pilot's record keeps no place for."""

type Ids = tuple[str, str | None]
"""A transcript's two ids, its conversation's and its sub-agent's."""


def major(version: str) -> str:
    """The major of the labeller's version, which alone relabels a
    transcript whole where it differs (`labeller.md`, "Pilot relabels a
    conversation whole when the major differs")."""
    return version.split(".", 1)[0]


class Unanswered(Exception):
    """The labeller gave a call no answer the collector takes; the message
    says why."""


class _Install(BaseModel):
    install_path: str = Field(alias="installPath")


class _Installed(BaseModel):
    plugins: dict[str, list[_Install]]


class _Answer(BaseModel):
    contract: int
    version: str


class _Stamp(BaseModel):
    session_id: str
    agent_id: str | None
    stamp: str | None


class _Stamps(_Answer):
    declarations: str
    file_rules: str
    index: str | None
    stamps: list[_Stamp]


class _Classes(_Answer):
    file_rules: str
    classes: list[str]


class _Group(BaseModel):
    key: str
    name: str
    summary: str | None


class _Vocabularies(_Answer):
    lists: dict[str, Any]
    nesting: list[Any]
    groups: list[_Group]


class _Line(BaseModel):
    """A transcript's line of a `label` answer."""

    session_id: str
    agent_id: str | None
    answer: str


class _Done(BaseModel):
    done: Literal[True]
    index: str | None


class _LabelsLine(_Line):
    model_config = ConfigDict(extra="ignore")

    answer: Literal["labels"]
    stamp: str
    labels: dict[str, list[dict[str, Any]]]
    units: list[Any]
    test_suites: list[dict[str, Any]]
    ci_builds: list[dict[str, Any]]


@dataclass(frozen=True)
class Stamps:
    """The labeller's `stamps` answer of a walk."""

    version: str
    """The labeller's own version that answered."""
    declarations: str
    """The digest of what its `vocabularies` would answer now."""
    file_rules: str
    """The digest of the file-class rules it would class files under now."""
    stamps: dict[Ids, str | None]
    """The stamp each transcript handed would get now; none where it cannot
    be computed."""
    seconds: float
    """How long the stamps took, the request's making and the call."""


@dataclass(frozen=True)
class Declared:
    """The labeller's `vocabularies` answer as the collector takes it."""

    vocabularies: VocabulariesSchema
    """What Pilot is declared."""
    groups: dict[str, PublishedGroupSchema]
    """Each group it declares, by its key, as a publication names one."""


@dataclass(frozen=True)
class Classed:
    """The labeller's `classes` answer as Pilot takes it."""

    version: str
    """The labeller's own version that answered."""
    file_rules: str
    """The digest of the file-class rules it classed the files under."""
    classes: FileClassesSchema
    """Each file's class, as Pilot is given them."""


@dataclass(frozen=True)
class Labelled:
    """A transcript's publication with the labeller's labels, and what its
    carry keeps of them."""

    publication: PublicationSchema
    checkpoint: Checkpoint | None
    """The checkpoint the labeller handed back with them; none where it
    handed back none, or its boundary's Call is none the publication
    holds."""


@dataclass(frozen=True)
class Labels:
    """The labeller's `label` answer of one batch."""

    version: str
    """The labeller's own version that answered."""
    lines: dict[Ids, dict[str, Any]]
    """Each transcript's line, its labels or its error, by its ids; none
    for one the answer was cut short of."""
    cut: str | None
    """Why the answer was cut short, none where it gave every line."""


class Labeller:
    """The labeller the settings name, called on one home."""

    def __init__(self, settings: Settings) -> None:
        self._named = settings.COLLECTOR_LABELLER
        self._seconds = settings.COLLECTOR_LABELLER_SECONDS
        self._plugins = settings.COLLECTOR_HOME / PLUGINS
        self._home = {
            "projects": str(settings.COLLECTOR_HOME / PROJECTS),
            "plugins": str(self._plugins),
        }
        self._index: str | None = None
        """The index the labeller handed back last, which it is handed at
        its next call."""
        self._types: dict[Path, tuple[tuple[int, int, int], str | None]] = {}
        """Each sub-agent's `agent_type` by its record: the record's size,
        time and inode when it was read, and what it named."""

    def stamps(self, listed: list[Listed], inventory: InventorySchema) -> Stamps:
        """The stamp the labeller would give now for every transcript of
        `listed`, each handed with what `inventory` gives for its
        conversation and the stamp it holds for it.

        Raises:
            Unanswered: The labeller gave no answer the collector takes.
        """
        began = time.perf_counter()
        types: dict[Path, tuple[tuple[int, int, int], str | None]] = {}
        conversations = self._conversations(listed, inventory, types)
        self._types = types
        answer = self._answer(
            "stamps",
            _Stamps,
            {
                "pilot": _pilot(inventory),
                "index": self._index,
                "conversations": conversations,
            },
        )
        handed = [
            (conversation["session_id"], transcript["agent_id"])
            for conversation in conversations
            for transcript in conversation["transcripts"]
        ]
        if [(each.session_id, each.agent_id) for each in answer.stamps] != handed:
            raise Unanswered(
                "its stamps are not those of the transcripts it was handed, in"
                " their order"
            )
        self._index = answer.index
        return Stamps(
            version=answer.version,
            declarations=answer.declarations,
            file_rules=answer.file_rules,
            stamps={
                (each.session_id, each.agent_id): each.stamp for each in answer.stamps
            },
            seconds=time.perf_counter() - began,
        )

    def vocabularies(self) -> Declared:
        """The labeller's vocabularies as Pilot takes them, its version, its
        nestings and the lists Pilot's shape names, every other list left
        out; and its groups as a publication names one, a group the labeller
        gives no summary of with an empty one.

        Raises:
            Unanswered: The labeller gave no answer the collector takes, or
                one that lacks a list Pilot's shape names or is not its
                shape.
        """
        answer = self._answer("vocabularies", _Vocabularies, {"index": self._index})
        try:
            return Declared(
                VocabulariesSchema.model_validate(
                    {
                        "version": answer.version,
                        "lists": {
                            name: answer.lists[name]
                            for name in DeclaredListsSchema.model_fields
                            if name in answer.lists
                        },
                        "nesting": answer.nesting,
                    }
                ),
                {
                    group.key: PublishedGroupSchema(
                        key=group.key, name=group.name, summary=group.summary or ""
                    )
                    for group in answer.groups
                },
            )
        except ValidationError as error:
            raise Unanswered(
                f"its vocabularies are not the shape Pilot takes: {error}"[:_SAID]
            ) from error

    def classes(self, files: Sequence[HeldFileSchema]) -> Classed:
        """The labeller's class of each of `files`, in one call.

        Raises:
            Unanswered: The labeller gave no answer the collector takes, or
                not one class for each file, each a code.
        """
        answer = self._answer(
            "classes",
            _Classes,
            {"files": [[file.repository, file.path] for file in files]},
        )
        if len(answer.classes) != len(files):
            raise Unanswered(
                f"its classes are {len(answer.classes)}, and it was handed"
                f" {len(files)} files"
            )
        try:
            classes = FileClassesSchema(
                classes=[
                    FileClassSchema(
                        repository=file.repository, path=file.path, file_class=code
                    )
                    for file, code in zip(files, answer.classes, strict=True)
                ]
            )
        except ValidationError as error:
            raise Unanswered(
                f"its classes are not the shape Pilot takes: {error}"[:_SAID]
            ) from error
        return Classed(answer.version, answer.file_rules, classes)

    def label(
        self, batch: Sequence[tuple[Listed, Read]], inventory: InventorySchema
    ) -> Labels:
        """The labeller's labels of each transcript of `batch`, in one call,
        each handed in its conversation as `stamps` hands it and labelled as
        its reading took it: whole, or from the boundary on of the
        checkpoint the carry it continues holds.

        Raises:
            Unanswered: The labeller gave no answer the collector takes, not
                even the first line of one.
        """
        handed = {
            (listed.transcript.session_id, listed.transcript.agent_id): {
                "path": str(
                    listed.transcript.path.relative_to(listed.transcript.projects)
                )
            }
            | _handed(taken)
            for listed, taken in batch
        }
        said, failed = self._run(
            "label",
            {
                "pilot": _pilot(inventory),
                "index": self._index,
                "conversations": self._conversations(
                    [listed for listed, _ in batch], inventory, self._types, handed
                ),
            },
        )
        written = said.split(b"\n")[:-1]
        try:
            answer = _Answer.model_validate_json(written[0] if written else b"")
        except ValidationError as error:
            raise Unanswered(
                failed or f"its `label` answer is not the call's: {error}"[:_SAID]
            ) from error
        if answer.contract != CONTRACT:
            raise Unanswered(
                f"its `label` answer is of contract {answer.contract}, and the"
                f" collector speaks {CONTRACT}"
            )
        lines: dict[Ids, dict[str, Any]] = {}
        cut: str | None = failed or "its `label` answer ends before its `done` line"
        for raw in written[1:]:
            try:
                line = json.loads(raw)
                if isinstance(line, dict) and "done" in line:
                    self._index = _Done.model_validate(line).index
                    cut = failed
                    break
                each = _Line.model_validate(line)
            except (ValueError, ValidationError) as error:
                cut = f"its `label` answer has a line that is not the call's: {error}"
                break
            lines[each.session_id, each.agent_id] = line
        return Labels(answer.version, lines, None if cut is None else cut[:_SAID])

    def _conversations(
        self,
        listed: list[Listed],
        inventory: InventorySchema,
        types: dict[Path, tuple[tuple[int, int, int], str | None]],
        handed: Mapping[Ids, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """`listed` as the labeller is handed it: by conversation, each with
        its Sessions and Documents as `inventory` gives them, both empty
        where it holds none, and its main thread before its sub-agents; each
        transcript with the stamp `inventory` holds for it, and what
        `handed` holds for it besides. `types` gains each sub-agent's
        `agent_type` as its record was read."""
        held = {
            (each.session_id, each.agent_id): each.stamp
            for each in inventory.transcripts
        }
        given = {
            each.session_id: each.model_dump(mode="json")
            for each in inventory.conversations
        }
        threads: dict[str, list[Listed]] = {}
        for each in listed:
            threads.setdefault(each.transcript.session_id, []).append(each)
        conversations = []
        for session_id in sorted(threads):
            transcripts = []
            for each in sorted(
                threads[session_id],
                key=lambda each: (
                    each.transcript.agent_id is not None,
                    each.transcript.agent_id or "",
                ),
            ):
                agent_id = each.transcript.agent_id
                transcript: dict[str, Any] = {"agent_id": agent_id}
                record = record_of(each.transcript)
                if record is not None:
                    transcript["agent_type"] = self._agent_type(record, types)
                transcript["held"] = held.get((session_id, agent_id))
                if handed is not None:
                    transcript |= handed[session_id, agent_id]
                transcripts.append(transcript)
            context = given.get(session_id, {})
            conversations.append(
                {
                    "session_id": session_id,
                    "sessions": context.get("sessions", []),
                    "documents": context.get("documents", []),
                    "transcripts": transcripts,
                }
            )
        return conversations

    def _agent_type(
        self, path: Path, types: dict[Path, tuple[tuple[int, int, int], str | None]]
    ) -> str | None:
        """A sub-agent's `agent_type`, as its record at `path` names it,
        read again only where the record changed since; none where it names
        none. `types` gains what was read."""
        try:
            status = os.stat(path)
        except OSError:
            return None
        stood = (status.st_size, status.st_mtime_ns, status.st_ino)
        kept = self._types.get(path)
        if kept is not None and kept[0] == stood:
            types[path] = kept
            return kept[1]
        try:
            recorded = json.loads(path.read_bytes())
        except (OSError, ValueError):
            return None
        named = recorded.get("agentType") if isinstance(recorded, dict) else None
        agent_type = named if isinstance(named, str) else None
        types[path] = (stood, agent_type)
        return agent_type

    def _answer[T: _Answer](
        self, verb: str, shape: type[T], request: dict[str, Any]
    ) -> T:
        said = self._call(verb, request)
        try:
            answer = shape.model_validate_json(said)
        except ValidationError as error:
            raise Unanswered(
                f"its `{verb}` answer is not the call's: {error}"[:_SAID]
            ) from error
        if answer.contract != CONTRACT:
            raise Unanswered(
                f"its `{verb}` answer is of contract {answer.contract}, and the"
                f" collector speaks {CONTRACT}"
            )
        return answer

    def _call(self, verb: str, request: dict[str, Any]) -> bytes:
        """What the labeller wrote to its stdout for one call."""
        said, failed = self._run(verb, request)
        if failed is not None:
            raise Unanswered(failed)
        return said

    def _run(self, verb: str, request: dict[str, Any]) -> tuple[bytes, str | None]:
        """What the labeller wrote to its stdout for one call, and why the
        call failed: none where it exited 0.

        Raises:
            Unanswered: Its command cannot be run, or it refused the call.
        """
        command = [*self._command(), verb]
        sent = json.dumps({"contract": CONTRACT, "home": self._home} | request)
        try:
            done = subprocess.run(
                command,
                input=sent.encode(),
                capture_output=True,
                timeout=self._seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as cut:
            return (
                cut.stdout or b"",
                f"its `{verb}` gave no answer within {self._seconds:g} s",
            )
        except OSError as error:
            raise Unanswered(f"its command cannot be run: {error}") from error
        refusal = _refusal(done.stdout) if done.returncode == 2 else None
        if refusal is not None:
            raise Unanswered(f"it refused the `{verb}` call: {refusal}")
        if done.returncode != 0:
            said = done.stderr.decode(errors="replace").strip().splitlines()
            return (
                done.stdout,
                f"its `{verb}` call exited {done.returncode}:"
                f" {said[-1] if said else 'it wrote nothing to its stderr'}"[:_SAID],
            )
        return done.stdout, None

    def _command(self) -> list[str]:
        """The command the settings name, the installed copy's folder in it
        where it names one."""
        if not any(INSTALL_PATH in part for part in self._named):
            return self._named
        installed = str(self._installed())
        return [part.replace(INSTALL_PATH, installed) for part in self._named]

    def _installed(self) -> Path:
        """The folder of the installed copy of `PLUGIN`, as the collector
        sees it: the first the home's `installed_plugins.json` names, its
        path on the fleet's home taken from its `cache` folder on and found
        under the home's `plugins`.

        Raises:
            Unanswered: The home names no copy the collector can see.
        """
        file = self._plugins / INSTALLED
        try:
            installed = _Installed.model_validate_json(file.read_bytes())
        except FileNotFoundError:
            raise Unanswered(
                f"no copy is installed: the home has no {PLUGINS}/{INSTALLED}"
            ) from None
        except (OSError, ValidationError) as error:
            raise Unanswered(
                f"the home's {PLUGINS}/{INSTALLED} cannot be read: {error}"[:_SAID]
            ) from error
        copies = installed.plugins.get(PLUGIN)
        if not copies:
            raise Unanswered(
                f"no copy is installed: the home's {PLUGINS}/{INSTALLED} names no"
                f" {PLUGIN}"
            )
        named = copies[0].install_path
        parts = PurePosixPath(named).parts[-4:]
        if len(parts) != 4 or parts[0] != _CACHE or ".." in parts:
            raise Unanswered(
                f"the installed copy's path {named} is no copy in the home's"
                f" {PLUGINS}/{_CACHE}"
            )
        return self._plugins.joinpath(*parts)


def _pilot(inventory: InventorySchema) -> dict[str, Any]:
    """The request's `pilot` header: the conversations a Session of Pilot's
    ran."""
    return {"conversations": [each.session_id for each in inventory.conversations]}


def _handed(taken: Read) -> dict[str, Any]:
    """What a `label` request hands of a transcript as `taken` read it:
    whole, or, read from a carry that holds the labeller's checkpoint, from
    that checkpoint's boundary on, with the checkpoint and its boundary as
    the labeller handed them back. With them a main thread's Launches, the
    first the one open at the reading's boundary, and the Calls the labeller
    reads in what the reading took, each with its place among the file's
    and, on a main thread, its Launch: the one holding its Prompt, as Pilot
    places it (DB 543), else, as for a Call Pilot holds none of, the Launch
    of the Call before it, the first Launch for the first."""
    publication = taken.publication
    carried = taken.checkpoint
    mode: dict[str, Any] = (
        {"mode": "whole"}
        if carried is None
        else {
            "mode": "appended",
            "from": {"call": carried.call, "byte": carried.byte},
            "checkpoint": carried.text,
        }
    )
    first = 1 if carried is None else carried.position
    if publication.agent_id is not None or not publication.launches:
        return mode | {
            "calls": [
                {"id": named, "position": position}
                for position, named in enumerate(taken.calls, start=first)
            ]
        }
    boundary = None if publication.appended is None else publication.appended.boundary
    launch = 1 if boundary is None else boundary.launch
    prompt = 1 if boundary is None else boundary.prompt
    prompted: dict[int, int] = {}
    for n, launched in enumerate(publication.launches, start=launch):
        place = prompt + len(prompted)
        prompted |= dict.fromkeys(range(place, place + len(launched.prompts)), n)
    prompts = {call.message_id: call.prompt for call in publication.calls}
    calls = []
    within = launch
    for position, named in enumerate(taken.calls, start=first):
        received = prompts.get(named)
        within = within if received is None else prompted.get(received, within)
        calls.append({"id": named, "position": position, "launch": within})
    return mode | {
        "launches": [
            {"n": n, "started_at": launched.started_at.isoformat()}
            for n, launched in enumerate(publication.launches, start=launch)
        ],
        "calls": calls,
    }


def labelled(
    taken: Read,
    line: Mapping[str, Any],
    version: str,
    groups: Mapping[str, PublishedGroupSchema],
) -> Labelled:
    """The publication of what `taken` read with the labels a `label`
    answer's `line` gives of it, under the labeller's `version`, as
    `with_labels` makes it: of an appended reading the labels from its
    boundary on, its Segments placed by the carry's checkpoint; and the
    checkpoint the line hands back, as the carry keeps it.

    Raises:
        Unanswered: As `with_labels`.
    """
    carried = taken.checkpoint
    publication = with_labels(
        taken.publication,
        line,
        version,
        groups,
        None if carried is None else carried.shift,
    )
    return Labelled(publication, _checkpoint(taken, line, publication))


def _checkpoint(
    taken: Read, line: Mapping[str, Any], publication: PublicationSchema
) -> Checkpoint | None:
    """The checkpoint `line` hands back for what `taken` read, which
    `publication` labels: with the place of its boundary's Call among the
    Calls the labeller reads, and how far the labeller's place of that
    Call's Segment runs ahead of the publication's; none where it hands back
    no checkpoint, or that Call is none the publication labels."""
    boundary, text = line.get("boundary"), line.get("checkpoint")
    labelling = publication.labelling
    if not isinstance(boundary, dict) or not isinstance(text, str) or labelling is None:
        return None
    call, byte = boundary.get("call"), boundary.get("byte")
    if (
        not isinstance(call, str)
        or not isinstance(byte, int)
        or call not in taken.calls
    ):
        return None
    given = next(
        (
            row.get("segment")
            for row in line["labels"].get("calls", [])
            if row.get("id") == call
        ),
        None,
    )
    held = next((row.segment for row in labelling.labels.calls if row.id == call), None)
    if not isinstance(given, int) or held is None:
        return None
    first = 1 if taken.checkpoint is None else taken.checkpoint.position
    return Checkpoint(
        version=labelling.version,
        stamp=labelling.stamp,
        call=call,
        byte=byte,
        text=text,
        position=first + taken.calls.index(call),
        shift=given - held,
    )


def with_labels(
    publication: PublicationSchema,
    line: Mapping[str, Any],
    version: str,
    groups: Mapping[str, PublishedGroupSchema],
    shift: int | None = None,
) -> PublicationSchema:
    """`publication` with the labels a `label` answer's `line` gives of its
    transcript, under the labeller's `version`: those of the rows it holds,
    the Calls of its own and their Tool Calls, and the Segments they fall
    in, renumbered where a Segment of none of them falls out: from 1, since
    Pilot holds a whole call's Segments at 1 to their number, or, where the
    line labels an appended reading from its boundary on, from the place
    Pilot holds the first at, `shift` behind the labeller's; a main thread's
    adopted group as its `group`, from `groups`; and of a Call's labels what
    Pilot's record keeps.

    Raises:
        Unanswered: The line is no labels of the call's shape, or names a
            group the labeller does not declare.
    """
    try:
        answer = _LabelsLine.model_validate(line)
    except ValidationError as error:
        raise Unanswered(
            f"its labels are not the shape of the call's: {error}"[:_SAID]
        ) from error
    labels = answer.labels
    held = {call.message_id for call in publication.calls}
    requested = {
        tool_call.tool_use_id
        for call in publication.calls
        for tool_call in call.tool_calls
    }
    calls = [row for row in labels.get("calls", []) if row.get("id") in held]
    named = {row.get("segment") for row in calls}
    kept = [row for row in labels.get("segments", []) if row.get("position") in named]
    first = (
        1
        if shift is None or not kept or not isinstance(kept[0].get("position"), int)
        else kept[0]["position"] - shift
    )
    renumbered = {row.get("position"): place for place, row in enumerate(kept, first)}
    waits = [
        row for row in labels.get("ci_waits", []) if row.get("tool_use_id") in requested
    ]
    runs = [
        row
        for row in labels.get("test_runs", [])
        if row.get("tool_use_id") is None or row.get("tool_use_id") in requested
    ]
    built = {(row.get("job"), row.get("number")) for row in waits}
    suites = {row.get("suite") for row in runs}
    adopted = [row.get("adopted_group") for row in labels.get("transcript", [])]
    key = adopted[0] if adopted else None
    if key is not None and key not in groups:
        raise Unanswered(
            f"its labels name the group `{key}`, which it does not declare"
        )
    try:
        labelling = PublishedLabellingSchema.model_validate(
            {
                "version": version,
                "stamp": answer.stamp,
                "labels": {
                    "launches": labels.get("launches", []),
                    "calls": [
                        {
                            name: renumbered.get(label, label)
                            if name == "segment"
                            else label
                            for name, label in row.items()
                            if name not in _UNKEPT
                        }
                        for row in calls
                    ],
                    "segments": [
                        row | {"position": renumbered[row.get("position")]}
                        for row in kept
                    ],
                    "tool_calls": [
                        row
                        for row in labels.get("tool_calls", [])
                        if row.get("tool_use_id") in requested
                    ],
                    "events": [
                        row
                        for row in labels.get("events", [])
                        if row.get("call") in held
                    ],
                    "context_parts": [
                        row
                        for row in labels.get("context_parts", [])
                        if row.get("call") in held
                    ],
                    "test_runs": runs,
                    "ci_waits": waits,
                    "documents": labels.get("documents", []),
                },
                "units": answer.units,
                "test_suites": [
                    row for row in answer.test_suites if row.get("code") in suites
                ],
                "ci_builds": [
                    row
                    for row in answer.ci_builds
                    if (row.get("job"), row.get("number")) in built
                ],
            }
        )
    except ValidationError as error:
        raise Unanswered(
            f"its labels are not the shape Pilot takes: {error}"[:_SAID]
        ) from error
    return publication.model_copy(
        update={
            "labelling": labelling,
            "group": None if key is None else groups[key],
        }
    )


def _refusal(said: bytes) -> str | None:
    """A refusal as the labeller writes one, `{"error": {"code", "detail"}}`:
    its code and its detail; none where `said` is no refusal, as Python's
    own exit 2 for a script it cannot open."""
    try:
        error = json.loads(said)["error"]
        return f"{error['code']}: {error['detail']}"[:_SAID]
    except (ValueError, KeyError, TypeError):
        return None
