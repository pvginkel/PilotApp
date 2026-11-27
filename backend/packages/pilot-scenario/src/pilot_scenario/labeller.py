"""The stub labeller (F122.5): the command a collector's configuration names in
a suite, in place of the workflow's labeller, which no suite reaches.

It speaks the labeller's contract 1, as the installed `dev` plugin's
`docs/labeller.md` has it: one JSON request on stdin, one answer on stdout
(JSON Lines for `label`); the verbs `info`, `vocabularies`, `stamps`, `label`
and `classes`; the refusals, exit 2 with `{"error": {"code", "detail"}}`, of a
request that is no JSON (`json`), of the wrong shape (`request`), of an unknown
verb (`verb`), with no home (`home`) or of another contract (`contract`); and in
a `label` answer an error line for a transcript it cannot label, `unreadable`,
`calls_mismatch` or `internal`, the batch going on. A crash is exit 1. Its
stamp is of all it read for a transcript besides the file, `stamps` answers it
without reading one, and both hand back an index of the run records they
parsed. A transcript that grew is labelled from the boundary and checkpoint its
last answer handed back, or answered `whole` with the contract's `why`.

Its lists, its units and its file classes are the invented scenario's (F122.2,
F122.4), with no word of the workflow, and so are its rules: each a few lines
over what a transcript's file, the run records and what Pilot handed say.

    python3 -B labeller.py [--version V] [--speaks N] [--pause S] <verb>

`--version` is the labeller's own version it answers under, `--speaks` the
contract it speaks, `--pause` the seconds it takes before each transcript's
line of a `label` answer.

It imports the standard library alone, so that it runs as a file of its own,
and writes nothing anywhere.

Its run records are one file, `records.json`, in the folder the request's
`home.data` names, else `<home.plugins>/data/scenario-labeller`; a home with
none holds no records. Every key is optional:

- `kinds`: the kinds of work, the widest first, each but the first a part of
  the one before;
- `units`: each Work Unit's row as a label answer gives it, its `key`, `kind`,
  `title` and `part_of` among them;
- `ran`: the key of the unit each conversation's main thread carried out, by
  its session id;
- `unit_runs` and `suites`: the units' Test Runs, as a label answer gives
  them, and the Test Suites they name;
- `groups`: each group's `key`, `name`, `summary` and `repository`, and the
  session ids of the `conversations` it adopts;
- `file_rules`: by a repository's name, its own file-class rules, each a
  `class` and its `paths`.
"""

import base64
import hashlib
import io
import json
import re
import sys
import time
import traceback
import zlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import IO, Any

CONTRACT = 1
"""The contract it speaks unless told another."""

VERSION = "1.0.0"
"""The labeller's own version it answers under unless told another."""

VERBS = ("info", "vocabularies", "stamps", "label", "classes")

DATA = "scenario-labeller"
"""The folder under `<home.plugins>/data` that holds its run records."""

RECORDS = "records.json"
"""The run records' file in that folder."""

SERVED = "served"
"""The Unit Outcome of a unit done as it should be."""

RECOOKED = "recooked"
"""The Rework Kind of work cooked again."""

_FORMAT = "1"
"""The format of a stamp, a checkpoint and an index: their text's first field."""

_OPEN = 1 << 62
"""Where a Call an open stretch holds is settled: past every byte of a file."""

_BOUND = 3
"""The counted Calls after a background command's own that close its stretch
where no notification names it."""

_SYNTHETIC = "<synthetic>"
"""The model of an assistant line Claude Code wrote itself: no counted Call."""

_SEND = frozenset({"Agent", "Task"})
_STIR = frozenset({"Edit", "Write", "NotebookEdit", "MultiEdit"})
_LOOK = frozenset({"Read", "Grep", "Glob", "LS"})

_PROGRAMS = {
    "python": "script",
    "python3": "script",
    "curl": "fetch",
    "wget": "fetch",
    "grep": "search",
    "rg": "search",
    "watch_oven": "oven",
}
"""A Bash command's Command Class, by its program."""

_SEGMENTS = {"look": "prep", "run": "simmer"}
"""A counted Call's Segment Kind, by its class; every other class's `cook`."""

_TOKEN = ".pantry/token"
"""What a command names that breaks the rule `no_pantry_token`."""

_BAKED = re.compile(r"^(\S+) #(\d+) (\S+)$", re.MULTILINE)
"""A build row of a `watch_oven` command's result: its job, number and result."""

_CARD = "# Recipe card"
"""The heading of a prompt's block whose `## ` sections are its Context Parts."""


def _value(code: str, name: str, description: str, **facts: Any) -> dict[str, Any]:
    return {"code": code, "name": name, "description": description, **facts}


_LISTS: dict[str, list[dict[str, Any]]] = {
    "unit_outcome": [
        _value(SERVED, "Served", "Done as it should be."),
        _value("sent_back", "Sent back", "Done, and sent back to be done again."),
    ],
    "rework_kind": [_value(RECOOKED, "Recooked", "Work cooked again.")],
    "unit_measure": [
        _value("parts", "Parts", "The units it was cut into.", unit="parts"),
    ],
    "segment_kind": [
        _value("prep", "Prep", "Looking things over."),
        _value("cook", "Cook", "The cooking itself."),
        _value("simmer", "Simmer", "Running a command."),
    ],
    "wait_cause": [
        _value("lighting", "Lighting", "Its process was starting."),
        _value("return", "Return", "A later process of it was started."),
        _value("guest", "Guest", "It waited for a person's message."),
        _value("timer", "Timer", "It waited for a background command to end."),
        _value("helper", "Helper", "A helper it sent off ran."),
        _value("stove", "Stove", "Its own command ran."),
    ],
    "call_class": [
        _value("look", "Look", "Read a recipe or a note."),
        _value("stir", "Stir", "Changed a recipe or a note."),
        _value("run", "Run", "Ran a command."),
        _value("send", "Send", "Sent a helper off."),
        _value("spill", "Spill", "A tool call that failed."),
        _value("muse", "Muse", "No tool."),
        _value("other", "Other", "Anything else."),
    ],
    "avoidable_kind": [_value("spilt", "Spilt", "A call that failed.")],
    "batchable_condition": [
        _value("lone", "Lone", "A look at one thing alone."),
        _value("several", "Several", "A look at several things at once."),
    ],
    "command_class": [
        _value("script", "Script", "Runs a script of the kitchen's."),
        _value("fetch", "Fetch", "Fetches from the network."),
        _value("search", "Search", "Searches the files."),
        _value("oven", "Oven", "Waits on the oven's bakes."),
    ],
    "build_result": [
        _value("RISEN", "RISEN", "The bake rose."),
        _value("FLAT", "FLAT", "The bake fell flat."),
    ],
    "file_class": [
        _value(
            "recipe", "Recipe", "What is cooked from, its settings too.", counted=True
        ),
        _value("tasting", "Tasting", "Tastings and what they need.", counted=True),
        _value("note", "Note", "Notes on the recipes.", counted=True),
        _value("menu", "Menu", "What the household means to cook.", counted=True),
        _value("printout", "Printout", "What a tool printed.", counted=False),
        _value("logbook", "Logbook", "What a session wrote of itself.", counted=False),
    ],
    "tool_effect_kind": [
        _value("order_placed", "Order placed", "Placed an order with the pantry."),
    ],
    "rule": [
        _value(
            "no_pantry_token",
            "No pantry token",
            "The pantry's token is never read.",
            home="/work/RecipeBox/CLAUDE.md",
        ),
    ],
    "ask_category": [
        _value("menu_question", "Menu question", "A question put on a page."),
        _value("house_note", "House note", "A note Pilot itself put."),
    ],
    "event_kind": [
        _value("burnt", "Burnt", "A script of the kitchen's failed.", is_error=False),
    ],
    "context_part_kind": [
        _value("recipe_card", "Recipe card", "One section of a prompt's recipe card."),
    ],
}
"""Every list but the Work Unit Kinds, which are the run records', each in its
order."""

_STARTING = (
    ("printout", ("*.lock", "**/printed/**")),
    ("tasting", ("**/tests/**", "test_*.py", "*_test.py")),
    ("note", ("*.md", "README*")),
    ("recipe", ("**",)),
)
"""The file-class rules after a repository's own, the first that names a file
having it."""

_CLASSES = frozenset(value["code"] for value in _LISTS["file_class"])


class Refusal(Exception):
    """A request refused: exit 2 with `{"error": {"code", "detail", ...}}`."""

    def __init__(self, code: str, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.extra = extra

    def answer(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "detail": self.detail, **self.extra}}


class _Unlabelled(Exception):
    """A transcript it cannot label: its error line's code and detail."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class _Whole(Exception):
    """An appended request it cannot go on with: the answer `whole`'s `why`."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


def major(version: str) -> str:
    """A version's major, its first field."""
    return version.split(".", 1)[0]


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    """22 characters of url-safe base64 of the sha256 over the value's
    canonical JSON."""
    digest = hashlib.sha256(_canonical(value).encode()).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")[:22]


def _packed(version: str, body: Any) -> str:
    """`<format>:<version>:<base64 of zlib-compressed JSON>`."""
    raw = zlib.compress(_canonical(body).encode(), 6)
    return f"{_FORMAT}:{version}:{base64.b64encode(raw).decode('ascii')}"


def _unpacked(text: Any, version: str) -> Any:
    """What `_packed` packed under a version of `version`'s major, else none."""
    if not isinstance(text, str):
        return None
    parts = text.split(":", 2)
    if len(parts) != 3 or parts[0] != _FORMAT or major(parts[1]) != major(version):
        return None
    try:
        return json.loads(zlib.decompress(base64.b64decode(parts[2], validate=True)))
    except (ValueError, zlib.error):
        return None


# ---------------------------------------------------------------------------
# The run records


def _data(home: Mapping[str, Any]) -> Path:
    """The run records' folder: `home.data`, else the stub's own under the
    home's plugins."""
    if home.get("data"):
        return Path(home["data"])
    return Path(home["plugins"]) / "data" / DATA


def load(data: Path, index: Any, version: str) -> tuple[dict[str, Any], str]:
    """The run records in `data`, and the index to hand back: the parsed
    records keyed by their file's size, time and inode, taken from `index`
    where that still matches the file, else read again."""
    file = data / RECORDS
    try:
        stat = file.stat()
    except FileNotFoundError:
        key: list[int] | None = None
    else:
        key = [stat.st_size, stat.st_mtime_ns, stat.st_ino]
    held = _unpacked(index, version)
    if isinstance(held, dict) and held.get("file") == key and "records" in held:
        records: dict[str, Any] = held["records"]
    else:
        records = {} if key is None else json.loads(file.read_text())
    return records, _packed(version, {"file": key, "records": records})


def _units(records: Mapping[str, Any], session_id: str) -> list[dict[str, Any]]:
    """The unit the main thread of that session id carried out and every unit
    above it, each after the units it sits in and is occasioned by."""
    key = records.get("ran", {}).get(session_id)
    if key is None:
        return []
    rows = {unit["key"]: unit for unit in records.get("units", [])}
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(at: str) -> None:
        if at in seen:
            return
        seen.add(at)
        unit = rows[at]
        for above in (unit.get("part_of"), unit.get("occasioned_by")):
            if above is not None:
                visit(above)
        ordered.append(unit)

    visit(key)
    return ordered


def _runs(
    records: Mapping[str, Any], units: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The units' Test Runs, and the Test Suites they name."""
    keys = {unit["key"] for unit in units}
    runs = [run for run in records.get("unit_runs", []) if run["work_unit"] in keys]
    suites = {suite["code"]: suite for suite in records.get("suites", [])}
    named = dict.fromkeys(run["suite"] for run in runs)
    return runs, [suites[code] for code in named]


def _group(
    records: Mapping[str, Any], session_id: str, pilot: frozenset[str]
) -> dict[str, Any] | None:
    """The group that adopts the conversation of that session id, none where
    a session of Pilot's ran it."""
    if session_id in pilot:
        return None
    for group in records.get("groups", []):
        if session_id in group.get("conversations", []):
            return {key: group[key] for key in ("key", "name", "summary")}
    return None


def _stamp(
    records: Mapping[str, Any],
    conversation: Mapping[str, Any],
    transcript: Mapping[str, Any],
    pilot: frozenset[str],
) -> str:
    """The stamp of all it reads for a transcript besides its file: what
    Pilot handed with its conversation, its `agent_type`, whether a session
    of Pilot's ran it, and of a main thread the rows of its units, their Test
    Runs and Suites, and its group."""
    session_id = conversation["session_id"]
    inputs: dict[str, Any] = {
        "context": [
            conversation.get("sessions", []),
            conversation.get("documents", []),
        ],
        "agent_type": transcript.get("agent_type"),
        "pilot": session_id in pilot,
    }
    if transcript.get("agent_id") is None:
        units = _units(records, session_id)
        runs, suites = _runs(records, units)
        inputs |= {
            "units": units,
            "runs": runs,
            "suites": suites,
            "group": _group(records, session_id, pilot),
        }
    return f"{_FORMAT}:{_digest(inputs)}"


# ---------------------------------------------------------------------------
# The vocabularies and the file classes


def vocabularies(records: Mapping[str, Any], version: str = VERSION) -> dict[str, Any]:
    """The `vocabularies` answer: every list, the Work Unit Kinds the run
    records', the nestings, each kind but the widest in the one before it,
    and the groups."""
    kinds: list[str] = records.get("kinds", [])
    declared = {
        "work_unit_kind": [
            _value(
                kind,
                kind.replace("_", " ").capitalize(),
                "The widest kind of work."
                if place == 0
                else f"A part of one {kinds[place - 1].replace('_', ' ')}.",
            )
            for place, kind in enumerate(kinds)
        ],
        **_LISTS,
    }
    ran = records.get("ran", {})
    return {
        "contract": CONTRACT,
        "version": version,
        "lists": {
            name: [
                value | {"position": place}
                for place, value in enumerate(values, start=1)
            ]
            for name, values in declared.items()
        },
        "nesting": [
            {"inner": inner, "outer": outer}
            for outer, inner in zip(kinds, kinds[1:], strict=False)
        ],
        "groups": [
            {
                "key": group["key"],
                "spec_repo": group.get("repository"),
                "name": group["name"],
                "summary": group["summary"],
                "slices": sorted(
                    {
                        ran[each]
                        for each in group.get("conversations", [])
                        if each in ran
                    }
                ),
            }
            for group in records.get("groups", [])
        ],
    }


def _declarations(records: Mapping[str, Any], version: str) -> str:
    """The digest of what `vocabularies` answers now."""
    return _digest(vocabularies(records, version))


def _rules_digest(records: Mapping[str, Any], version: str) -> str:
    """The digest of the file-class rules in effect."""
    return _digest({"major": major(version), "rules": records.get("file_rules", {})})


def _pattern(glob: str) -> re.Pattern[str]:
    """A path pattern as a regular expression over a path from the
    repository's root: `**/` any folders, none included, `**` anything, `*`
    and `?` within a name; one with no `/` matches a name in any folder."""
    glob = glob.lstrip("/")
    out = [] if "/" in glob else ["(?:.*/)?"]
    at = 0
    while at < len(glob):
        if glob.startswith("**/", at):
            out.append("(?:[^/]*/)*")
            at += 3
        elif glob.startswith("**", at):
            out.append(".*")
            at += 2
        elif glob[at] == "*":
            out.append("[^/]*")
            at += 1
        elif glob[at] == "?":
            out.append("[^/]")
            at += 1
        else:
            out.append(re.escape(glob[at]))
            at += 1
    return re.compile("".join(out))


def classes(records: Mapping[str, Any], files: Sequence[Sequence[str]]) -> list[str]:
    """The class of each file, by its repository and its path: the first rule
    that names it, the repository's own ahead of the starting list; a rule of
    a class not declared, or with no paths, skipped."""
    compiled: dict[str, list[tuple[str, list[re.Pattern[str]]]]] = {}
    own: Mapping[str, Any] = records.get("file_rules", {})
    found: list[str] = []
    for repository, path in files:
        rules = compiled.get(repository)
        if rules is None:
            given = [
                (rule["class"], rule["paths"])
                for rule in own.get(repository, [])
                if rule.get("class") in _CLASSES and rule.get("paths")
            ]
            rules = compiled[repository] = [
                (code, [_pattern(glob) for glob in globs])
                for code, globs in (*given, *_STARTING)
            ]
        found.append(
            next(
                code
                for code, patterns in rules
                if any(p.fullmatch(path) for p in patterns)
            )
        )
    return found


# ---------------------------------------------------------------------------
# A transcript's labels


def _text(content: Any) -> str:
    """A tool result's text, its text blocks joined."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block["text"]
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    return ""


def _card(prompt: str) -> list[dict[str, Any]]:
    """The sections of a prompt's recipe card, each its heading up to its
    first ` (` and its length with its heading."""
    start = prompt.find(_CARD)
    if start < 0 or (start > 0 and prompt[start - 1] != "\n"):
        return []
    block = prompt[start:]
    ends = [match.start() for match in re.finditer(r"^# ", block, re.MULTILINE)]
    block = block[: ends[1]] if len(ends) > 1 else block
    heads = [match.start() for match in re.finditer(r"^## ", block, re.MULTILINE)]
    sections = []
    for place, head in enumerate(heads):
        section = block[head : heads[place + 1] if place + 1 < len(heads) else None]
        title = section[3:].split("\n", 1)[0].split(" (", 1)[0].strip()
        sections.append({"name": title, "characters": len(section)})
    return sections


def _words(command: str) -> list[str]:
    """The words of a command's last part, past what sets its environment and
    a `timeout`."""
    parts = [part for part in re.split(r"&&|\|\||;", command) if part.strip()]
    words = parts[-1].split() if parts else []
    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=\S*", words[0]):
        words.pop(0)
    if words[:1] == ["timeout"]:
        words = words[2:]
    return words


class _Call:
    """A Call as its lines are read: its first line's byte, whether it is
    counted, its Launch, its tools and their results, the byte by which every
    line touching it was read, and the stretches it holds open."""

    def __init__(self, message_id: str, first: int, counted: bool, launch: Any) -> None:
        self.id = message_id
        self.first = first
        self.counted = counted
        self.launch = launch
        self.tools: list[dict[str, Any]] = []
        self.results: dict[str, dict[str, Any]] = {}
        self.touched = first
        self.open = 0
        self.closed = 0
        self.wake: str | None = None
        self.card: list[dict[str, Any]] = []

    def settled(self) -> int:
        return _OPEN if self.open else max(self.touched, self.closed)

    def kind(self) -> str:
        names = [tool["name"] for tool in self.tools]
        if any(result["error"] for result in self.results.values()):
            return "spill"
        for tools, kind in ((_SEND, "send"), (_STIR, "stir"), ({"Bash"}, "run")):
            if any(name in tools for name in names):
                return kind
        if any(name in _LOOK for name in names):
            return "look"
        return "other" if names else "muse"


def _woken() -> dict[str, Any]:
    return {"person": False, "notified": False, "card": None}


class _Part:
    """A transcript's lines from a byte, read on from a checkpoint's state or
    from none."""

    def __init__(
        self, transcript: Mapping[str, Any], checkpoint: Mapping[str, Any] | None
    ) -> None:
        held = checkpoint or {}
        self.main = transcript.get("agent_id") is None
        self.launch_of = {
            call["id"]: call.get("launch") for call in transcript["calls"]
        }
        self.calls: list[_Call] = []
        self.by_id: dict[str, _Call] = {}
        self.tool_of: dict[str, _Call] = {}
        self.pending: set[str] = set()
        self.owed: set[str] = set(held.get("owed", []))
        self.counted: int = held.get("counted", 0)
        self.wake: dict[str, Any] = dict(held.get("wake") or _woken())
        self.prev: dict[str, Any] = dict(
            held.get("prev") or {"tools": [], "launch": None}
        )
        self.segment: list[Any] | None = held.get("segment")
        self.resumed = checkpoint is not None
        self.last: _Call | None = None
        self.stretches: list[dict[str, Any]] = []
        self.snaps: dict[str, dict[str, Any]] = {}

    def read(self, lines: IO[bytes], start: int) -> None:
        lines.seek(start)
        byte = start
        for raw in lines:
            at = byte
            byte += len(raw)
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(line, dict):
                continue
            message = line.get("message")
            if not isinstance(message, dict):
                continue
            if line.get("type") == "assistant":
                self._assistant(message, at)
            elif line.get("type") == "user":
                self._user(line, message, at)

    def _previous(self) -> tuple[list[str], Any]:
        if self.last is not None:
            return [tool["name"] for tool in self.last.tools], self.last.launch
        return list(self.prev["tools"]), self.prev["launch"]

    def _assistant(self, message: Mapping[str, Any], at: int) -> None:
        message_id = message.get("id")
        if not isinstance(message_id, str) or not message_id:
            return
        call = self.by_id.get(message_id)
        if call is None:
            call = self._began(message_id, at, message.get("model") != _SYNTHETIC)
        elif call is not self.calls[-1]:
            call.touched = max(call.touched, at + 1)
        content = message.get("content")
        for block in content if isinstance(content, list) else ():
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and isinstance(block.get("id"), str)
            ):
                self._asked(call, block)

    def _began(self, message_id: str, at: int, counted: bool) -> _Call:
        call = _Call(message_id, at, counted, self.launch_of.get(message_id))
        if counted:
            tools, launch = self._previous()
            self.snaps[message_id] = {
                "counted": self.counted,
                "wake": dict(self.wake),
                "prev": {"tools": tools, "launch": launch},
                "owed": sorted(self.owed | self.pending),
            }
            first = self.counted == 0
            later = (
                self.main
                and not first
                and call.launch is not None
                and launch is not None
                and call.launch != launch
            )
            call.wake = self._cause(first, later, tools)
            if self.main and (first or later) and self.wake["card"]:
                call.card = self.wake["card"]
            for stretch in self.stretches:
                if stretch["open"]:
                    stretch["count"] += 1
                    if later or stretch["count"] >= _BOUND:
                        self._close(stretch, at)
            self.counted += 1
            self.wake = _woken()
            self.last = call
        self.by_id[message_id] = call
        self.calls.append(call)
        return call

    def _cause(self, first: bool, later: bool, tools: list[str]) -> str | None:
        """What woke the transcript before a counted Call."""
        if first:
            return "lighting"
        if later:
            return "return"
        if self.wake["person"]:
            return "guest"
        if self.wake["notified"]:
            return "timer"
        if tools:
            return "helper" if any(name in _SEND for name in tools) else "stove"
        return None

    def _asked(self, call: _Call, block: Mapping[str, Any]) -> None:
        given = block.get("input")
        tool = {
            "id": block["id"],
            "name": block.get("name"),
            "input": given if isinstance(given, dict) else {},
        }
        call.tools.append(tool)
        self.tool_of[tool["id"]] = call
        self.pending.add(tool["id"])
        if tool["name"] == "Bash" and tool["input"].get("run_in_background") is True:
            self.stretches.append(
                {"call": call, "tool": tool["id"], "count": 0, "open": True}
            )
            call.open += 1

    def _close(self, stretch: dict[str, Any], at: int) -> None:
        stretch["open"] = False
        call: _Call = stretch["call"]
        call.open -= 1
        call.closed = max(call.closed, at)

    def _user(
        self, line: Mapping[str, Any], message: Mapping[str, Any], at: int
    ) -> None:
        content = message.get("content")
        if isinstance(content, str):
            if line.get("isMeta") or line.get("isCompactSummary"):
                return
            if content.lstrip().startswith("<task-notification>"):
                self.wake["notified"] = True
                for stretch in self.stretches:
                    if stretch["open"] and stretch["tool"] in content:
                        self._close(stretch, at + 1)
            else:
                self.wake["person"] = True
                if self.wake["card"] is None:
                    self.wake["card"] = _card(content)
            return
        for block in content if isinstance(content, list) else ():
            if isinstance(block, dict) and block.get("type") == "tool_result":
                self._returned(block, line, at)

    def _returned(
        self, block: Mapping[str, Any], line: Mapping[str, Any], at: int
    ) -> None:
        tool_use_id = block.get("tool_use_id")
        if not isinstance(tool_use_id, str):
            return
        call = self.tool_of.get(tool_use_id)
        if call is None:
            if tool_use_id in self.owed:
                raise _Whole("behind")
            return
        call.touched = max(call.touched, at + 1)
        self.pending.discard(tool_use_id)
        call.results[tool_use_id] = {
            "error": block.get("is_error") is True,
            "at": line.get("timestamp"),
            "text": _text(block.get("content")),
        }

    def boundary(self) -> _Call | None:
        """The latest counted Call before whose first line every earlier Call
        was settled."""
        found = None
        settled = 0
        for call in self.calls:
            if call.counted and settled <= call.first:
                found = call
            settled = max(settled, call.settled())
        return found

    def segments(
        self, kinds: Mapping[str, str], boundary: str | None
    ) -> tuple[list[dict[str, Any]], dict[str, int], list[Any] | None]:
        """Every Segment from the part's first, each Call's, and the Segment
        the Call before the boundary fell in: a run of counted Calls of one
        kind is one; a Call not counted takes the one before it, or after it
        where it leads."""
        place, kind = self.segment or (0, None)
        segments: list[dict[str, Any]] = []
        of: dict[str, int] = {}
        leading: list[str] = []
        before: list[Any] | None = None
        for call in self.calls:
            if call.id == boundary:
                before = [place, kind] if place else None
            if not call.counted:
                if place:
                    of[call.id] = place
                else:
                    leading.append(call.id)
                continue
            now = _SEGMENTS.get(kinds[call.id], "cook")
            if now != kind:
                place, kind = place + 1, now
                segments.append({"position": place, "kind": now})
            elif self.resumed and not segments:
                segments.append({"position": place, "kind": now})
            of[call.id] = place
            for each in leading:
                of[each] = place
            leading = []
        if leading:
            place += 1
            segments.append({"position": place, "kind": "cook"})
            for each in leading:
                of[each] = place
        return segments, of, before


def _tool_labels(
    tool: Mapping[str, Any], result: Mapping[str, Any] | None, call: str
) -> dict[str, Any]:
    """One Tool Call's labels, the Events it marks and the CI Builds it
    waited on."""
    name, given = tool["name"], tool["input"]
    labels: dict[str, Any] = {
        "command_class": None,
        "effect_kind": None,
        "effect_subject": None,
        "rules": [],
    }
    events: list[dict[str, Any]] = []
    builds: list[dict[str, Any]] = []
    failed = result is not None and result["error"]
    if name == "Bash" and isinstance(given.get("command"), str):
        command: str = given["command"]
        words = _words(command)
        labels["command_class"] = _PROGRAMS.get(words[0]) if words else None
        if _TOKEN in command:
            labels["rules"].append("no_pantry_token")
        if labels["command_class"] == "script" and failed and result is not None:
            if isinstance(result["at"], str):
                events.append(
                    {
                        "call": call,
                        "kind": "burnt",
                        "at": result["at"],
                        "detail": words[1] if len(words) > 1 else None,
                    }
                )
        if labels["command_class"] == "oven" and result is not None and not failed:
            job = words[1] if len(words) > 1 else None
            commit = (
                words[words.index("--hash") + 1] if "--hash" in words[:-1] else None
            )
            for row in _BAKED.finditer(result["text"]):
                builds.append(
                    {
                        "job": row[1],
                        "number": int(row[2]),
                        "result": row[3],
                        "queued_at": None,
                        "started_at": None,
                        "ended_at": None,
                        "commit": commit if row[1] == job else None,
                        "deployed_at": None,
                    }
                )
    elif (
        isinstance(name, str)
        and name.startswith("mcp__")
        and name.rsplit("__", 1)[-1] == "place_order"
        and result is not None
        and not failed
    ):
        labels["effect_kind"] = "order_placed"
        order = given.get("order")
        labels["effect_subject"] = order if isinstance(order, str) else None
    return {"labels": labels, "events": events, "builds": builds}


def _line_call(lines: IO[bytes], byte: int) -> str | None:
    """The message id of the counted Call whose assistant line starts at
    `byte`, if one does."""
    if byte > 0:
        lines.seek(byte - 1)
        if lines.read(1) != b"\n":
            return None
    lines.seek(byte)
    try:
        line = json.loads(lines.readline())
    except ValueError:
        return None
    message = line.get("message") if isinstance(line, dict) else None
    if (
        not isinstance(message, dict)
        or line.get("type") != "assistant"
        or message.get("model") == _SYNTHETIC
    ):
        return None
    message_id = message.get("id")
    return message_id if isinstance(message_id, str) else None


def _checkpoint(
    lines: IO[bytes],
    transcript: Mapping[str, Any],
    ids: tuple[str, Any],
    stamp: str,
    version: str,
) -> dict[str, Any]:
    """The handed checkpoint, checked against the request and the file."""
    held = _unpacked(transcript.get("checkpoint"), version)
    given = transcript.get("from") or {}
    if (
        not isinstance(held, dict)
        or held.get("contract") != CONTRACT
        or [held.get("session_id"), held.get("agent_id")] != list(ids)
        or held.get("boundary")
        != {"call": given.get("call"), "byte": given.get("byte")}
    ):
        raise _Whole("checkpoint")
    if held.get("stamp") != stamp:
        raise _Whole("stamp")
    byte = held["boundary"]["byte"]
    if (
        not isinstance(byte, int)
        or byte < 0
        or _line_call(lines, byte) != held["boundary"]["call"]
    ):
        raise _Whole("boundary")
    calls = transcript["calls"]
    if not calls or calls[0].get("id") != held["boundary"]["call"]:
        raise _Whole("calls")
    return held


def _labelled(
    lines: IO[bytes],
    transcript: Mapping[str, Any],
    conversation: Mapping[str, Any],
    pilot: frozenset[str],
    records: Mapping[str, Any],
    version: str,
) -> dict[str, Any]:
    """A transcript's answer line, its labels or the answer `whole`."""
    session_id = conversation["session_id"]
    agent_id = transcript.get("agent_id")
    main = agent_id is None
    stamp = _stamp(records, conversation, transcript, pilot)
    whole = {"session_id": session_id, "agent_id": agent_id, "answer": "whole"}
    held = None
    try:
        if transcript["mode"] == "appended":
            held = _checkpoint(
                lines, transcript, (session_id, agent_id), stamp, version
            )
        part = _Part(transcript, held)
        part.read(lines, 0 if held is None else held["boundary"]["byte"])
    except _Whole as answer:
        return whole | {"why": answer.why}
    read = [call.id for call in part.calls]
    handed = [call["id"] for call in transcript["calls"]]
    if read != handed:
        if held is not None:
            return whole | {"why": "calls"}
        at = next(
            (
                k
                for k, pair in enumerate(zip(read, handed, strict=False))
                if pair[0] != pair[1]
            ),
            min(len(read), len(handed)),
        )
        raise _Unlabelled(
            "calls_mismatch",
            f"Call {at + 1}: handed {handed[at] if at < len(handed) else None!r},"
            f" the file has {read[at] if at < len(read) else None!r}",
        )

    kinds = {call.id: call.kind() for call in part.calls if call.counted}
    boundary = part.boundary()
    segments, segment_of, before = part.segments(
        kinds, None if boundary is None else boundary.id
    )
    rows: list[dict[str, Any]] = []
    tool_rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    parts: list[dict[str, Any]] = []
    waits: list[dict[str, Any]] = []
    builds: dict[tuple[str, int], dict[str, Any]] = {}
    for call in part.calls:
        row: dict[str, Any] = {
            "id": call.id,
            "segment": segment_of.get(call.id),
            "call_class": None,
            "avoidable_kind": None,
            "batchable_condition": None,
            "wait_cause": None,
        }
        if call.counted:
            kind = kinds[call.id]
            row |= {
                "call_class": kind,
                "avoidable_kind": "spilt" if kind == "spill" else None,
                "batchable_condition": (
                    ("lone" if len(call.tools) == 1 else "several")
                    if kind == "look"
                    else None
                ),
                "wait_cause": call.wake,
            }
            parts += [
                {"call": call.id, "kind": "recipe_card", **section}
                for section in call.card
            ]
            for tool in call.tools:
                found = _tool_labels(tool, call.results.get(tool["id"]), call.id)
                labels = found["labels"]
                if labels["command_class"] or labels["effect_kind"] or labels["rules"]:
                    tool_rows.append({"tool_use_id": tool["id"], **labels})
                events += found["events"]
                for build in found["builds"]:
                    waits.append(
                        {
                            "tool_use_id": tool["id"],
                            "job": build["job"],
                            "number": build["number"],
                        }
                    )
                    builds[build["job"], build["number"]] = build
        rows.append(row)

    units = _units(records, session_id) if main else []
    runs, suites = _runs(records, units)
    work_unit = records.get("ran", {}).get(session_id) if main else None
    documents = conversation.get("documents", []) if main else []
    checkpoint = None
    if boundary is not None:
        checkpoint = _packed(
            version,
            {
                "contract": CONTRACT,
                "session_id": session_id,
                "agent_id": agent_id,
                "stamp": stamp,
                "boundary": {"call": boundary.id, "byte": boundary.first},
                "segment": before,
                **part.snaps[boundary.id],
            },
        )
    group = _group(records, session_id, pilot) if main else None
    return {
        "session_id": session_id,
        "agent_id": agent_id,
        "answer": "labels",
        "stamp": stamp,
        "boundary": None
        if boundary is None
        else {"call": boundary.id, "byte": boundary.first},
        "checkpoint": checkpoint,
        "labels": {
            "transcript": (
                [{"adopted_group": None if group is None else group["key"]}]
                if main
                else []
            ),
            "launches": [
                {"n": launch["n"], "work_unit": work_unit}
                for launch in transcript.get("launches", [])
            ]
            if main
            else [],
            "calls": rows,
            "segments": segments,
            "tool_calls": tool_rows,
            "events": events,
            "context_parts": parts,
            "test_runs": runs,
            "ci_waits": waits,
            "documents": [
                {
                    "id": document["id"],
                    "ask_category": "menu_question"
                    if document.get("source_path")
                    else "house_note",
                }
                for document in documents
            ],
        },
        "units": units,
        "test_suites": suites,
        "ci_builds": list(builds.values()),
    }


def label(
    content: bytes,
    transcript: Mapping[str, Any],
    conversation: Mapping[str, Any],
    pilot: frozenset[str],
    records: Mapping[str, Any],
    version: str = VERSION,
) -> dict[str, Any]:
    """The answer line of a transcript whose file holds `content`, handed as
    a `label` request hands it, in its conversation, as the `label` verb
    gives it."""
    return _labelled(
        io.BytesIO(content), transcript, conversation, pilot, records, version
    )


def _error(session_id: str, agent_id: Any, code: str, detail: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "agent_id": agent_id,
        "answer": "error",
        "error": {"code": code, "detail": detail},
    }


def _label_one(
    projects: Path,
    transcript: Mapping[str, Any],
    conversation: Mapping[str, Any],
    pilot: frozenset[str],
    records: Mapping[str, Any],
    version: str,
) -> dict[str, Any]:
    """One transcript's line of the `label` answer, or its error line."""
    session_id, agent_id = conversation["session_id"], transcript.get("agent_id")
    path = Path(transcript["path"])
    if path.is_absolute() or ".." in path.parts:
        return _error(
            session_id, agent_id, "unreadable", f"{path} is not under home.projects"
        )
    try:
        with (projects / path).open("rb") as lines:
            return _labelled(lines, transcript, conversation, pilot, records, version)
    except _Unlabelled as error:
        return _error(session_id, agent_id, error.code, error.detail)
    except OSError as error:
        return _error(session_id, agent_id, "unreadable", f"{path}: {error}")
    except Exception as error:  # one transcript it cannot label fails only itself
        frame = traceback.extract_tb(error.__traceback__)[-1]
        return _error(
            session_id,
            agent_id,
            "internal",
            f"{type(error).__name__}: {error} at {Path(frame.filename).name}:"
            f"{frame.lineno} in {frame.name}",
        )


# ---------------------------------------------------------------------------
# The command


def _conversations(request: Mapping[str, Any], verb: str) -> list[dict[str, Any]]:
    conversations = request.get("conversations")
    if not isinstance(conversations, list):
        raise Refusal("request", f"`{verb}` needs `conversations`, a list")
    for n, conversation in enumerate(conversations, start=1):
        where = f"conversation {n}"
        if not isinstance(conversation, dict) or not isinstance(
            conversation.get("session_id"), str
        ):
            raise Refusal("request", f"{where} has no `session_id`")
        for key in ("sessions", "documents"):
            if not isinstance(conversation.get(key, []), list):
                raise Refusal("request", f"{where}'s `{key}` is not a list")
        transcripts = conversation.get("transcripts")
        if not isinstance(transcripts, list) or not all(
            isinstance(transcript, dict) for transcript in transcripts
        ):
            raise Refusal(
                "request", f"{where}'s `transcripts` is not a list of objects"
            )
        if verb == "label":
            for m, transcript in enumerate(transcripts, start=1):
                _check_item(transcript, f"{where}, transcript {m}")
    return conversations


def _check_item(transcript: Mapping[str, Any], where: str) -> None:
    if not isinstance(transcript.get("path"), str) or not transcript["path"]:
        raise Refusal("request", f"{where} has no `path`")
    if transcript.get("mode") not in ("whole", "appended"):
        raise Refusal("request", f"{where}'s `mode` is neither whole nor appended")
    calls = transcript.get("calls")
    if not isinstance(calls, list) or not all(
        isinstance(call, dict) and isinstance(call.get("id"), str) for call in calls
    ):
        raise Refusal("request", f"{where} has no `calls` list of Calls with an `id`")
    if not isinstance(transcript.get("launches", []), list):
        raise Refusal("request", f"{where}'s `launches` is not a list")
    if transcript["mode"] == "appended" and not isinstance(
        transcript.get("from"), dict
    ):
        raise Refusal("request", f"{where} is appended and has no `from`")


def _home(request: Mapping[str, Any]) -> dict[str, Any]:
    home = request.get("home")
    if not isinstance(home, dict):
        raise Refusal("home", "the request names no `home`")
    for key in ("projects", "plugins"):
        if not isinstance(home.get(key), str) or not home[key]:
            raise Refusal("home", f"`home.{key}` is missing")
    if "data" in home and (not isinstance(home["data"], str) or not home["data"]):
        raise Refusal("home", "`home.data` is not a path")
    return home


def _pilot(request: Mapping[str, Any]) -> frozenset[str]:
    """The conversations any session of Pilot's ran, from the `pilot` header."""
    pilot = request.get("pilot")
    conversations = pilot.get("conversations") if isinstance(pilot, dict) else None
    return frozenset(each for each in conversations or [] if isinstance(each, str))


def _answered(
    verb: str,
    request: Mapping[str, Any],
    version: str,
    pause: float,
    answer: Callable[[Any], None],
) -> None:
    home = _home(request)
    if verb == "classes":
        files = request.get("files")
        if not isinstance(files, list) or not all(
            isinstance(file, list)
            and len(file) == 2
            and all(isinstance(part, str) for part in file)
            for file in files
        ):
            raise Refusal(
                "request", "`classes` needs `files`, a list of [repo, path] pairs"
            )
        records, _ = load(_data(home), None, version)
        answer(
            {
                "contract": CONTRACT,
                "version": version,
                "file_rules": _rules_digest(records, version),
                "classes": classes(records, files),
            }
        )
        return
    if verb == "vocabularies":
        answer(
            vocabularies(load(_data(home), request.get("index"), version)[0], version)
        )
        return
    conversations = _conversations(request, verb)
    records, index = load(_data(home), request.get("index"), version)
    pilot = _pilot(request)
    if verb == "stamps":
        stamps = []
        for conversation in conversations:
            for transcript in conversation["transcripts"]:
                try:
                    stamp: str | None = _stamp(records, conversation, transcript, pilot)
                except Exception:  # one transcript it cannot stamp fails only itself
                    stamp = None
                stamps.append(
                    {
                        "session_id": conversation["session_id"],
                        "agent_id": transcript.get("agent_id"),
                        "stamp": stamp,
                    }
                )
        answer(
            {
                "contract": CONTRACT,
                "version": version,
                "declarations": _declarations(records, version),
                "file_rules": _rules_digest(records, version),
                "index": index,
                "stamps": stamps,
            }
        )
        return
    answer({"contract": CONTRACT, "version": version})
    projects = Path(home["projects"])
    count = 0
    for conversation in conversations:
        for transcript in _main_first(conversation["transcripts"]):
            time.sleep(pause)
            answer(
                _label_one(projects, transcript, conversation, pilot, records, version)
            )
            count += 1
    answer({"done": True, "count": count, "index": index})


def _main_first(transcripts: Sequence[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    yield from (t for t in transcripts if t.get("agent_id") is None)
    yield from (t for t in transcripts if t.get("agent_id") is not None)


def main(
    argv: Sequence[str] | None = None,
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
) -> int:
    """Answer one request: exit 0 when answered, 2 when it was refused."""
    given = list(sys.argv[1:] if argv is None else argv)
    read = sys.stdin if stdin is None else stdin
    write = sys.stdout if stdout is None else stdout
    options = {"--version": VERSION, "--speaks": str(CONTRACT), "--pause": "0"}
    while len(given) > 1 and given[0] in options:
        options[given[0]] = given[1]
        given = given[2:]
    version, speaks = options["--version"], int(options["--speaks"])

    def answer(value: Any) -> None:
        write.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        write.flush()

    verb = given[0] if given else None
    try:
        if verb not in VERBS:
            raise Refusal(
                "verb", f"unknown verb {verb!r}; the verbs are {', '.join(VERBS)}"
            )
        text = read.read()
        if verb == "info":
            answer({"contract": speaks, "version": version, "verbs": list(VERBS)})
            return 0
        try:
            request = json.loads(text)
        except ValueError as error:
            raise Refusal("json", f"the request is not JSON: {error}") from None
        if not isinstance(request, dict):
            raise Refusal("request", "the request is not a JSON object")
        contract = request.get("contract")
        if type(contract) is not int or contract != speaks:
            raise Refusal(
                "contract", f"contract {contract!r} is not spoken here", speaks=[speaks]
            )
        _answered(verb, request, version, float(options["--pause"]), answer)
    except Refusal as refusal:
        answer(refusal.answer())
        return 2
    return 0


def command(*options: str) -> list[str]:
    """The command that runs this stub, its `options` before the verb a
    caller appends."""
    return [sys.executable, "-B", str(Path(__file__).resolve()), *options]


if __name__ == "__main__":
    sys.exit(main())
