"""The block DSL's reader: a document's text parsed, then validated against the
record (FM §4, design 1 §6.1).

The grammar is strict inside a fence and lenient around it. A block body and
the front matter are YAML read with no implicit typing, so every scalar stays
the string written: `answer: Yes` matches the option `- Yes`, and `at` and
`done` are parsed here. A save with any fault is held (design 1 §6).
"""

import re
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

import yaml

from app.engine.dsl.document import (
    AnswerChannel,
    Block,
    BlockKind,
    Fault,
    FrontMatter,
    Option,
    ParsedDocument,
    Span,
)

AGENT = "agent"
"""Pilot's handle (decision 18): a `by: agent` line is the agent's own."""

PLAN = "plan"
"""`to: plan` defers a block to the plan itself (decision 47)."""

DEFERRED = "deferred"

ANSWER_KEYS = ("answer", "by", "at", "note", "via", "to", "done")

_DEFINITION_KEYS = {
    BlockKind.DECISION: (
        "options",
        "recommend",
        "proposal",
        "type",
        "because",
        "check",
    ),
    BlockKind.QUESTION: ("default",),
    BlockKind.ACTION: ("options", "check"),
}
_ARTICLE = {BlockKind.DECISION: "a", BlockKind.QUESTION: "a", BlockKind.ACTION: "an"}

# An explicit `via: app` reads as the line's absence.
_CHANNELS = frozenset(AnswerChannel)

YAML_LINE_BREAKS = {
    "\r": ("a carriage return", "\\r"),
    "\x85": ("U+0085", "\\x85"),
    "\u2028": ("U+2028", "\\u2028"),
    "\u2029": ("U+2029", "\\u2029"),
}
"""The characters YAML breaks a line at and the file does not, each with its
name and its escape in a double-quoted value. A body or a front matter that
holds one raw is held, so every line YAML counts is a line of the file."""

_UNSTORABLE = re.compile(r"[\x00\ud800-\udfff]")
"""What a double-quoted YAML escape can write and no PostgreSQL `text` holds."""

_FENCE = re.compile(r"(?P<indent> {0,3})(?P<marker>`{3,}|~{3,})(?P<info>.*)")
_HEADING = re.compile(r" {0,3}#{1,6}(?:[ \t]+(?P<text>.*?))?(?:[ \t]+#+)?[ \t]*")
_LOCAL_ID = re.compile(r"id\s*=\s*(?P<id>\S+)")
_CARRIES_ID = re.compile(r"(?:^|\s)id\s*=")
_TIME = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?"
)
_SLUG = re.compile(r"[a-z0-9-]+")
_BLOCK_SCALAR_HEADER = re.compile(r"[|>][-+0-9]*")


class DocumentKind(StrEnum):
    """What a document is, which decides the rules that are not every
    document's: the draft's slug, the title of Pilot's own one-block item."""

    DRAFT = "draft"
    HANDBOOK = "handbook"
    OPENING = "opening"
    OWN_ITEM = "own_item"
    REGISTERED_ITEM = "registered_item"


@dataclass(frozen=True)
class Facts:
    """What the record holds at the save, which a document is validated
    against.

    `step` may name a task removed from the plan, which is still the
    project's (decision 19); a `to` the save writes or changes must name a
    task in the plan (DB 203). `published_to` is each `to` of the published
    text by block id: one the save carries unchanged is not checked again.
    """

    document: DocumentKind
    handles: AbstractSet[str]
    plan_task_ids: AbstractSet[str]
    removed_task_ids: AbstractSet[str]
    confirmation_reasons: Sequence[str]
    taken_slugs: AbstractSet[str]
    published_to: Mapping[str, str]


def parse(text: str) -> ParsedDocument:
    """Read a document's text, with the faults it holds on its own."""
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    if lines[-1] == "":
        lines.pop()
    faults: list[Fault] = []
    front_matter, index = _front_matter(lines, faults)
    blocks: list[Block] = []
    seen: set[str] = set()
    heading: tuple[int, str] | None = None
    while index < len(lines):
        opening = _FENCE.fullmatch(lines[index])
        if opening is None or (
            opening["marker"].startswith("`") and "`" in opening["info"]
        ):
            if heading is None:
                heading = _heading(lines[index], index + 1)
            index += 1
            continue
        close = _closing_fence(lines, index, opening["marker"])
        if close is None:
            faults.append(
                Fault(
                    index + 1, f"a fence opened with {opening['marker']} is not closed"
                )
            )
            break
        block = _fenced(
            opening["info"].strip(),
            lines[index + 1 : close],
            len(opening["indent"]),
            Span(index + 1, close + 1),
            faults,
        )
        if block is not None:
            if block.local_id in seen:
                faults.append(Fault(index + 1, f"duplicate block id {block.local_id}"))
            seen.add(block.local_id)
            blocks.append(block)
        index = close + 1

    title, title_heading_line = front_matter.title, None
    if title is None and heading is not None:
        title_heading_line, title = heading
    return ParsedDocument(
        front_matter=front_matter,
        title=title,
        title_heading_line=title_heading_line,
        blocks=tuple(blocks),
        faults=tuple(sorted(faults, key=_by_line)),
    )


def validate(document: ParsedDocument, facts: Facts) -> list[Fault]:
    """Every fault of a save, in line order: the text's own and those against
    the record. A save with any is held."""
    faults = list(document.faults)
    front_matter = document.front_matter
    lines = front_matter.lines
    step = front_matter.step
    if (
        step is not None
        and step not in facts.plan_task_ids
        and step not in facts.removed_task_ids
    ):
        faults.append(
            Fault(
                lines["step"].first,
                f"front matter: `step: {step}` names no task of the project",
            )
        )
    addressee = front_matter.addressee
    if addressee is not None and addressee not in facts.handles:
        faults.append(
            Fault(
                lines["for"].first, f"front matter: `for: {addressee}` names no handle"
            )
        )
    slug = front_matter.slug
    if facts.document is DocumentKind.DRAFT and slug is not None:
        problem = _slug_problem(slug, facts.taken_slugs)
        if problem is not None:
            faults.append(
                Fault(lines["slug"].first, f"front matter: `slug: {slug}` {problem}")
            )
    if (
        facts.document is DocumentKind.OWN_ITEM
        and len(document.blocks) == 1
        and document.title is None
    ):
        faults.append(
            Fault(
                None,
                "the item has no title: give it `title` in the front matter"
                " or a first heading",
            )
        )
    for block in document.blocks:
        faults.extend(_record_faults(block, facts))
    return sorted(faults, key=_by_line)


def _by_line(fault: Fault) -> tuple[bool, int]:
    """File order, the faults of the document as a whole last."""
    return fault.line is None, fault.line or 0


def _record_faults(block: Block, facts: Facts) -> list[Fault]:
    prefix = f"block {block.local_id}: "
    faults: list[Fault] = []
    if block.because is not None and block.because not in facts.confirmation_reasons:
        reasons = ", ".join(facts.confirmation_reasons)
        faults.append(
            Fault(
                block.lines["because"].first,
                f"{prefix}`because: {block.because}` is not a confirmation reason"
                f" ({reasons}); the reasons are in `reference.json`",
            )
        )
    if block.by is not None and block.by not in facts.handles:
        faults.append(
            Fault(block.lines["by"].first, f"{prefix}`by: {block.by}` names no handle")
        )
    to = block.to
    if (
        to is not None
        and block.answer == DEFERRED
        and to != PLAN
        and to not in facts.plan_task_ids
        and facts.published_to.get(block.local_id) != to
    ):
        faults.append(
            Fault(
                block.lines["to"].first,
                f"{prefix}`to: {to}` names neither `plan` nor a task in the plan",
            )
        )
    return faults


def _slug_problem(slug: str, taken: AbstractSet[str]) -> str | None:
    if _SLUG.fullmatch(slug) is None:
        return "is not lower-case letters, digits and hyphens"
    if slug.startswith("draft-"):
        return "starts with `draft-`"
    if slug in taken:
        return "is taken by another project"
    return None


def _heading(line: str, number: int) -> tuple[int, str] | None:
    match = _HEADING.fullmatch(line)
    if match is None or not match["text"] or not match["text"].strip():
        return None
    return number, match["text"].strip()


def _closing_fence(lines: list[str], opening: int, marker: str) -> int | None:
    closing = re.compile(rf" {{0,3}}{re.escape(marker[0])}{{{len(marker)},}}[ \t]*")
    for index in range(opening + 1, len(lines)):
        if closing.fullmatch(lines[index]):
            return index
    return None


def _fenced(
    info: str, body: list[str], indent: int, fence: Span, faults: list[Fault]
) -> Block | None:
    """The block a fence holds, or none for a code block."""
    word = info.split(maxsplit=1)[0] if info else ""
    if word not in _DEFINITION_KEYS:
        if word.lower() in _DEFINITION_KEYS:
            faults.append(
                Fault(
                    fence.first, f"`{word}` is not a block kind: write `{word.lower()}`"
                )
            )
        elif _CARRIES_ID.search(info):
            faults.append(
                Fault(
                    fence.first,
                    f"a fence with `id=` is not a block: `{word}` is not decision,"
                    " question or action",
                )
            )
        return None
    kind = BlockKind(word)
    local_id = _LOCAL_ID.fullmatch(info[len(word) :].strip())
    if local_id is None:
        faults.append(
            Fault(fence.first, f"{_ARTICLE[kind]} {kind} block without `id=<id>`")
        )
        return None
    return _block(kind, local_id["id"], body, indent, fence, faults)


def _block(
    kind: BlockKind,
    local_id: str,
    body: list[str],
    indent: int,
    fence: Span,
    faults: list[Fault],
) -> Block:
    prefix = f"block {local_id}: "
    text = "\n".join(_dedent(line, indent) for line in body)
    entries = _mapping(
        text, fence.first + 1, f"{prefix}the body", faults, block_style=True
    )
    if entries is None:
        return Block(local_id=local_id, kind=kind, fence=fence, lines={})
    taken = _DEFINITION_KEYS[kind] + ANSWER_KEYS
    for key, (_, span) in entries.items():
        if key not in taken:
            faults.append(
                Fault(span.first, f"{prefix}{_ARTICLE[kind]} {kind} takes no `{key}`")
            )
    values = _Values(
        {key: entry for key, entry in entries.items() if key in taken},
        fence.first + 1,
        prefix,
        faults,
    )

    proposal = values.text("proposal")
    recommend = values.text("recommend")
    options = values.options(recommend)
    if values.has("proposal") and values.has("options"):
        values.fault("options", "`options` beside `proposal`")
    if recommend is not None:
        if values.has("proposal"):
            values.fault("recommend", "`recommend` beside `proposal`")
        elif options is not None and recommend not in {o.label for o in options}:
            values.fault("recommend", f"`recommend: {recommend}` names no option")

    kind_type = values.text("type")
    confirmation = kind_type == "confirmation"
    if kind_type is not None and not confirmation:
        values.fault("type", f"`type: {kind_type}` is not `confirmation`")
    if confirmation and not values.has("proposal"):
        values.fault("type", "a confirmation without `proposal`")
    if confirmation and not values.has("because"):
        values.fault("type", "a confirmation without `because`")

    answer = values.text("answer")
    if answer == DEFERRED and not values.has("to"):
        values.fault("answer", "`answer: deferred` without `to`")
    if values.has("to") and answer != DEFERRED:
        values.fault("to", "`to` without `answer: deferred`")
    by = values.text("by")
    via = values.text("via")
    if via is not None and via not in _CHANNELS:
        values.fault("via", f"`via: {via}` is not chat, recommended or autopilot")
        via = None
    if via is None and by is not None and by != AGENT:
        via = "app"

    return Block(
        local_id=local_id,
        kind=kind,
        fence=fence,
        lines={key: span for key, (_, span) in entries.items()},
        confirmation=confirmation,
        because=values.text("because"),
        proposal=proposal,
        default=values.text("default"),
        check=values.text("check"),
        options=options or (),
        answer=answer,
        by=by,
        at=values.time("at"),
        note=values.text("note"),
        via=via,
        to=values.text("to"),
        done=values.time("done"),
    )


def _front_matter(lines: list[str], faults: list[Fault]) -> tuple[FrontMatter, int]:
    """The front matter, and the index of the first line after it. A `---`
    first line with no closing one opens no front matter."""
    if not lines or lines[0].rstrip() != "---":
        return FrontMatter(), 0
    close = next(
        (index for index in range(1, len(lines)) if lines[index].rstrip() == "---"),
        None,
    )
    if close is None:
        return FrontMatter(), 0
    span = Span(1, close + 1)
    entries = _mapping("\n".join(lines[1:close]), 2, "the front matter", faults)
    if entries is None:
        return FrontMatter(span=span), close + 1
    values = _Values(entries, 2, "front matter: ", faults)
    urgent = values.text("urgent")
    if urgent is not None and urgent.lower() not in ("true", "false"):
        values.fault("urgent", f"`urgent: {urgent}` is not true or false")
    return (
        FrontMatter(
            span=span,
            lines={key: span for key, (_, span) in entries.items()},
            title=values.text("title"),
            summary=values.text("summary"),
            step=values.text("step"),
            urgent=urgent is not None and urgent.lower() == "true",
            addressee=values.text("for"),
            slug=values.text("slug"),
        ),
        close + 1,
    )


_Entries = dict[str, tuple[yaml.Node, Span]]


def _mapping(
    text: str,
    first_line: int,
    subject: str,
    faults: list[Fault],
    *,
    block_style: bool = False,
) -> _Entries | None:
    """The YAML mapping `text` holds, each key with its value and the file
    lines it covers; none, with a fault, when it holds no mapping, or, with
    `block_style`, a flow mapping, whose keys share lines. An empty text is an
    empty mapping."""
    try:
        return _read_mapping(text, first_line, subject, faults, block_style)
    except RecursionError:
        # PyYAML composes, and `_last_line` reads, a level per call: a value
        # nested thousands deep, or holding an alias of itself, has no end.
        faults.append(Fault(first_line, f"{subject} is nested too deep to read"))
        return None


def _read_mapping(
    text: str, first_line: int, subject: str, faults: list[Fault], block_style: bool
) -> _Entries | None:
    lines = text.split("\n")
    for index, content in enumerate(lines):
        brk = next((char for char in content if char in YAML_LINE_BREAKS), None)
        if brk is not None:
            name, escape = YAML_LINE_BREAKS[brk]
            faults.append(
                Fault(
                    first_line + index,
                    f"{subject} holds {name}, which YAML reads as a line break:"
                    f" write it as `{escape}` in a double-quoted value",
                )
            )
            return None
    try:
        node = yaml.compose(text, Loader=yaml.BaseLoader)
    except yaml.MarkedYAMLError as error:
        mark = error.problem_mark or error.context_mark
        line = first_line + mark.line if mark is not None else first_line
        problem = ", ".join(part for part in (error.context, error.problem) if part)
        faults.append(Fault(line, f"{subject} is not a YAML mapping: {problem}"))
        return None
    except yaml.reader.ReaderError as error:
        faults.append(
            Fault(first_line, f"{subject} is not a YAML mapping: {error.reason}")
        )
        return None
    if node is None:
        return {}
    if not isinstance(node, yaml.MappingNode):
        faults.append(
            Fault(first_line + node.start_mark.line, f"{subject} is not a YAML mapping")
        )
        return None
    if block_style and node.flow_style:
        faults.append(
            Fault(
                first_line + node.start_mark.line,
                f"{subject} is a flow mapping: write each key on a line of its own",
            )
        )
        return None
    unstorable = _unstorable(node)
    if unstorable is not None:
        faults.append(
            Fault(
                first_line + unstorable.start_mark.line,
                f"{subject} is not text: a key or value holds NUL or an unpaired"
                " surrogate",
            )
        )
        return None
    entries: _Entries = {}
    for key, value in node.value:
        line = first_line + key.start_mark.line
        if not isinstance(key, yaml.ScalarNode):
            faults.append(Fault(line, f"{subject} has a key that is not a name"))
            return None
        if key.value in entries:
            faults.append(Fault(line, f"{subject} has `{key.value}` twice"))
            return None
        last = first_line + _last_line(value, lines)
        entries[key.value] = (value, Span(line, max(line, last)))
    return entries


def _unstorable(node: yaml.Node) -> yaml.ScalarNode | None:
    """The first scalar, key or value, that holds what no row holds; each node
    is read once, so an alias is not followed again."""
    pending: list[yaml.Node] = [node]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, yaml.ScalarNode):
            if _UNSTORABLE.search(current.value):
                return current
        elif isinstance(current, yaml.SequenceNode):
            pending.extend(reversed(current.value))
        elif isinstance(current, yaml.MappingNode):
            for key, value in reversed(current.value):
                pending.extend((value, key))
    return None


def _last_line(node: yaml.Node, lines: list[str]) -> int:
    """The index in `lines` of a value's last line: a block list or mapping
    ends with its last entry, and a `|` or `>` scalar with its last line that
    is not blank, unless it keeps its trailing blank lines (`+`). YAML's end
    mark lies past the blank and comment lines that follow."""
    if (
        isinstance(node, yaml.SequenceNode | yaml.MappingNode)
        and not node.flow_style
        and node.value
    ):
        last = node.value[-1]
        return _last_line(last[1] if isinstance(last, tuple) else last, lines)
    end = node.end_mark
    index = end.line if end.column > 0 else end.line - 1
    if isinstance(node, yaml.ScalarNode) and node.style in ("|", ">"):
        start = node.start_mark
        header = _BLOCK_SCALAR_HEADER.match(lines[start.line], start.column)
        if header is None or "+" not in header[0]:
            while index > start.line and not lines[index].strip():
                index -= 1
    return index


def _dedent(line: str, indent: int) -> str:
    """A fenced line with up to the opening fence's indentation removed."""
    return line[min(indent, len(line) - len(line.lstrip(" "))) :]


class _Values:
    """The scalar values of one mapping, trimmed, with the faults of reading
    them. A key with an empty value reads as absent."""

    def __init__(
        self, entries: _Entries, first_line: int, prefix: str, faults: list[Fault]
    ) -> None:
        self._entries = entries
        self._first_line = first_line
        self._prefix = prefix
        self._faults = faults

    def has(self, key: str) -> bool:
        entry = self._entries.get(key)
        return entry is not None and not (
            isinstance(entry[0], yaml.ScalarNode) and not entry[0].value.strip()
        )

    def fault(self, key: str, message: str) -> None:
        self._faults.append(Fault(self._entries[key][1].first, self._prefix + message))

    def text(self, key: str) -> str | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if not isinstance(entry[0], yaml.ScalarNode):
            self.fault(key, f"`{key}` is not a single value")
            return None
        return entry[0].value.strip() or None

    def time(self, key: str) -> datetime | None:
        """An ISO 8601 date and time; one without a zone is UTC."""
        value = self.text(key)
        if value is None:
            return None
        moment = None
        if _TIME.fullmatch(value):
            try:
                moment = datetime.fromisoformat(value)
            except ValueError:
                moment = None
        if moment is None:
            self.fault(key, f"`{key}: {value}` is not a time")
            return None
        return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)

    def options(self, recommend: str | None) -> tuple[Option, ...] | None:
        """The options as written; none when `options` itself is faulted."""
        if not self.has("options"):
            return ()
        node, _ = self._entries["options"]
        if not isinstance(node, yaml.SequenceNode):
            self.fault("options", "`options` is not a list")
            return None
        options: list[Option] = []
        for position, item in enumerate(node.value, start=1):
            line = self._first_line + item.start_mark.line
            read = _option(item)
            if read is None:
                self._faults.append(
                    Fault(
                        line,
                        f"{self._prefix}option {position} is not a label"
                        " with at most one line",
                    )
                )
                continue
            label, text = read
            if any(option.label == label for option in options):
                self._faults.append(
                    Fault(line, f"{self._prefix}duplicate option label {label}")
                )
            options.append(Option(label, text, label == recommend, line))
        return tuple(options)


def _option(node: yaml.Node) -> tuple[str, str | None] | None:
    """A bare label, or `Label: one line`; none for anything else."""
    if isinstance(node, yaml.ScalarNode):
        label, text = node.value, ""
    elif (
        isinstance(node, yaml.MappingNode)
        and len(node.value) == 1
        and all(isinstance(part, yaml.ScalarNode) for part in node.value[0])
    ):
        label, text = node.value[0][0].value, node.value[0][1].value
    else:
        return None
    label, text = label.strip(), text.strip()
    if not label or "\n" in label or "\n" in text:
        return None
    return label, text or None
