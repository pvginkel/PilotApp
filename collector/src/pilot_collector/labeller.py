"""The workflow's labeller as the collector runs it (F152.6, F152.7): the
command the collector's settings name, by default the installed `dev`
plugin's copy, which the home's `plugins/installed_plugins.json` names, with
each call's verb appended; one JSON request on its stdin and one answer on
its stdout, under the labeller's contract 1 (the plugin's `docs/labeller.md`
§ Running it). Nothing of the workflow is the collector's: the labeller's
lists, its stamps and its index are taken as it hands them.

Every request names the contract and the home as the collector sees it, its
`projects` and its `plugins`. Two verbs are called here:

- `stamps`, at every walk: the stamp the labeller would give now for every
  transcript on the home, each handed in its conversation with what Pilot's
  inventory gives for that conversation, a sub-agent's with its
  `agent_type`, and each with the stamp Pilot holds for it; with the index
  the last call handed back, which the collector keeps in its memory
  (§ The stamp).
- `vocabularies`: every list the labeller declares, its nestings and its
  groups, of which Pilot takes the version, the nestings and the lists its
  shape names (§ The vocabularies).

A call that gives no answer the collector takes raises `Unanswered`: no copy
installed, a refusal (exit 2), a crash (exit 1), no answer within the time
the settings give, or an answer that is not the call's.
"""

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from pilot_collection.inventory import InventorySchema
from pilot_collection.vocabularies import DeclaredListsSchema, VocabulariesSchema
from pydantic import BaseModel, Field, ValidationError

from pilot_collector.home import PROJECTS, Listed, record_of
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

type Ids = tuple[str, str | None]
"""A transcript's two ids, its conversation's and its sub-agent's."""


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


class _Vocabularies(_Answer):
    lists: dict[str, Any]
    nesting: list[Any]


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
        conversations = self._conversations(listed, inventory)
        answer = self._answer(
            "stamps",
            _Stamps,
            {
                "pilot": {
                    "conversations": [
                        each.session_id for each in inventory.conversations
                    ]
                },
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

    def vocabularies(self) -> VocabulariesSchema:
        """The labeller's vocabularies as Pilot takes them: its version, its
        nestings and the lists Pilot's shape names, its groups and every
        other list left out.

        Raises:
            Unanswered: The labeller gave no answer the collector takes, or
                one that lacks a list Pilot's shape names or is not its
                shape.
        """
        answer = self._answer("vocabularies", _Vocabularies, {"index": self._index})
        try:
            return VocabulariesSchema.model_validate(
                {
                    "version": answer.version,
                    "lists": {
                        name: answer.lists[name]
                        for name in DeclaredListsSchema.model_fields
                        if name in answer.lists
                    },
                    "nesting": answer.nesting,
                }
            )
        except ValidationError as error:
            raise Unanswered(
                f"its vocabularies are not the shape Pilot takes: {error}"[:_SAID]
            ) from error

    def _conversations(
        self, listed: list[Listed], inventory: InventorySchema
    ) -> list[dict[str, Any]]:
        """`listed` as the labeller is handed it: by conversation, each with
        its Sessions and Documents as `inventory` gives them, both empty
        where it holds none, and its main thread before its sub-agents; each
        transcript with the stamp `inventory` holds for it."""
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
        types: dict[Path, tuple[tuple[int, int, int], str | None]] = {}
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
                transcripts.append(transcript)
            handed = given.get(session_id, {})
            conversations.append(
                {
                    "session_id": session_id,
                    "sessions": handed.get("sessions", []),
                    "documents": handed.get("documents", []),
                    "transcripts": transcripts,
                }
            )
        self._types = types
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
        except subprocess.TimeoutExpired:
            raise Unanswered(
                f"its `{verb}` gave no answer within {self._seconds:g} s"
            ) from None
        except OSError as error:
            raise Unanswered(f"its command cannot be run: {error}") from error
        refusal = _refusal(done.stdout) if done.returncode == 2 else None
        if refusal is not None:
            raise Unanswered(f"it refused the `{verb}` call: {refusal}")
        if done.returncode != 0:
            said = done.stderr.decode(errors="replace").strip().splitlines()
            raise Unanswered(
                f"its `{verb}` call exited {done.returncode}:"
                f" {said[-1] if said else 'it wrote nothing to its stderr'}"[:_SAID]
            )
        return done.stdout

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


def _refusal(said: bytes) -> str | None:
    """A refusal as the labeller writes one, `{"error": {"code", "detail"}}`:
    its code and its detail; none where `said` is no refusal, as Python's
    own exit 2 for a script it cannot open."""
    try:
        error = json.loads(said)["error"]
        return f"{error['code']}: {error['detail']}"[:_SAID]
    except (ValueError, KeyError, TypeError):
        return None
