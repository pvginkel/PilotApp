"""The block DSL's writer: the record's own lines spliced into a document's
text, and an agent's save merged against the published text by ownership
(design 1 §6.4, TD §7.1.2).

Text in, text out, and every text one that parses with no fault: a line the
record does not own is left as written, its line ending included (TD
§7.1.4), and a line the record writes takes the text's own ending.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import yaml

from pilot_dsl.document import (
    AnswerChannel,
    Block,
    BlockKind,
    Fault,
    ParsedDocument,
    Span,
)
from pilot_dsl.reader import (
    AGENT,
    ANSWER_KEYS,
    YAML_LINE_BREAKS,
    DocumentKind,
    parse,
)

_STR = "tag:yaml.org,2002:str"
_MAP = "tag:yaml.org,2002:map"
_UNBOUNDED = 2**31
_FENCE_PROOF_INDENT = 4


class WriteRefused(Exception):
    """A splice the text cannot take: "Cannot <operation> because <cause>"."""

    def __init__(self, operation: str, cause: str) -> None:
        self.operation = operation
        self.cause = cause
        super().__init__(f"Cannot {operation} because {cause}")


@dataclass(frozen=True)
class Merge:
    """An agent's save merged against the published text: the text to
    publish, and a fault per line, block or body prose the merge put back or
    took out, at its line in `text` where it has one, for a `reverted` Save
    Error."""

    text: str
    reverted: tuple[Fault, ...]


def write_answer(
    text: str,
    local_id: str,
    *,
    answer: str,
    by: str,
    at: datetime,
    via: AnswerChannel,
    note: str | None = None,
    to: str | None = None,
) -> str:
    """A person's answer: the block's answer lines, a `by: agent` line's `to`
    and `note` among them, replaced by `answer`, `by`, `at`, and `note`, `via`,
    `to` where given, in that order, at the end of its mapping. `app` writes no
    `via` line."""
    entries = [("answer", answer), ("by", by), ("at", _time(at))]
    if note is not None:
        entries.append(("note", note))
    if via != AnswerChannel.APP:
        entries.append(("via", str(via)))
    if to is not None:
        entries.append(("to", to))
    return _rewrite(text, local_id, f"write an answer into block {local_id}", entries)


def write_done(
    text: str, local_id: str, *, by: str, at: datetime, note: str | None = None
) -> str:
    """Done on an action: its answer lines replaced by `done` and `by`, and
    `note` where given, what the operator pasted back (FM §4)."""
    entries = [("done", _time(at)), ("by", by)]
    if note is not None:
        entries.append(("note", note))
    return _rewrite(text, local_id, f"mark block {local_id} done", entries)


def clear_answer(text: str, local_id: str) -> str:
    """Undo: the block's answer lines removed, and none restored, an answer of
    the agent's it replaced included (decision 6)."""
    return _rewrite(text, local_id, f"undo the answer of block {local_id}", [])


def write_recommended(text: str, *, by: str, at: datetime) -> str:
    """Done with the recommendations (F32.5): every unanswered block that has
    a recommendation answered with it, `via: recommended`."""
    edit = _Edit(text)
    for block in parse(text).blocks:
        answer = recommendation(block)
        if answer is not None and not block.answered:
            edit.replace_answer(
                block,
                [
                    ("answer", answer),
                    ("by", by),
                    ("at", _time(at)),
                    ("via", str(AnswerChannel.RECOMMENDED)),
                ],
            )
    return edit.apply()[0]


def with_title(text: str, title: str) -> str:
    """`title` written in the text's front matter: in place of a `title` key
    that gives none, else first, one front matter opened at the top where the
    text has none; the text as it is where its front matter gives a title (DB
    decision 50)."""
    if parse(text).front_matter.title is not None:
        return text
    return _titled(text, title, ())[0]


def _titled(
    text: str, title: str, faults: Sequence[Fault]
) -> tuple[str, tuple[Fault, ...]]:
    """`title` written in the front matter of `text`: in place of a `title`
    key there that gives none, else first, one front matter opened at the top
    where it has none; each of `faults` kept at its line."""
    front = parse(text).front_matter
    lines = _render([("title", title)])
    key = front.lines.get("title")
    edit = _Edit(text)
    if front.span is None:
        at, gone, lines = 0, 0, ["---", *lines, "---"]
    elif key is None:
        at, gone = front.span.first, 0
    else:
        at, gone = key.first - 1, key.last - key.first + 1
        edit.drop(key)
    edit.insert(at, lines)
    return edit.apply()[0], tuple(
        fault
        if fault.line is None or fault.line <= at
        else Fault(
            at + 1 if fault.line <= at + gone else fault.line + len(lines) - gone,
            fault.message,
        )
        for fault in faults
    )


def recommendation(block: Block) -> str | None:
    """The answer Done records for a block left unanswered (F32.5): a
    question's `default`; `Yes` to a confirmation and `Agree` to another
    proposal; a decision's recommended option. An action has none."""
    if block.kind is BlockKind.ACTION:
        return None
    if block.kind is BlockKind.QUESTION:
        return block.default
    if block.confirmation:
        return "Yes"
    if block.proposal is not None:
        return "Agree"
    return next((option.label for option in block.options if option.recommended), None)


def merge(published: str, save: str, document: DocumentKind) -> Merge:
    """An agent's save merged against the published text by ownership (§6.4,
    §5.3 step 4): the agent's prose, front matter, definitions and own answer
    lines from the save, every record-owned line from the published text.

    A block a person has answered is the record's whole (F32.7): where the
    save's fence differs, the published one replaces it. A person's lines the
    record does not hold are taken out of any other block. In a registered
    document a person has answered in, the body prose is the record's too,
    the front matter staying the agent's. A block the save dropped is
    restored whole. The draft is exempt (F47.4): there a person's answer
    lines alone are the record's, put back at the end of the block's mapping
    where changed or dropped, and a block the save dropped goes with its
    answers. Every line of the opening is the record's (DB 162).
    """
    if document is DocumentKind.OPENING:
        return _merge_opening(published, save)
    source = _Edit(published)
    edit = _Edit(save)
    published_blocks = parse(published).blocks
    held = {block.local_id: block for block in published_blocks}
    saved = {block.local_id: block for block in parse(save).blocks}
    draft = document is DocumentKind.DRAFT
    for block in saved.values():
        answered = held.get(block.local_id)
        if answered is not None and _a_persons(answered):
            if draft:
                _carry_answer(edit, block, answered, source)
            else:
                _carry_fence(edit, block, answered, source)
        elif _a_persons(block):
            _drop_unheld(edit, block)
    if not draft:
        _place_blocks(edit, published_blocks, saved, source, _restored)
    text, reverted = edit.apply()
    if document is DocumentKind.REGISTERED_ITEM and any(
        map(_a_persons, published_blocks)
    ):
        return _carry_prose(published, text, reverted)
    return Merge(text, reverted)


def _merge_opening(published: str, save: str) -> Merge:
    if save == published:
        return Merge(published, ())
    held, saved = _Edit(published).lines, _Edit(save).lines
    line = next(
        (
            number
            for number in range(1, len(held) + 1)
            if number > len(saved) or held[number - 1] != saved[number - 1]
        ),
        None,
    )
    return Merge(
        published, (Fault(line, "the opening is the record's: the save is reverted"),)
    )


def _carry_fence(
    edit: "_Edit", block: Block, published: Block, source: "_Edit"
) -> None:
    fence = [source.content(number) for number in _numbers(published.fence)]
    if [edit.content(number) for number in _numbers(block.fence)] == fence:
        return
    edit.drop(block.fence)
    edit.insert(
        block.fence.last,
        fence,
        [(0, f"block {block.local_id} reverted: answered by a person")],
    )


def _carry_answer(
    edit: "_Edit", block: Block, published: Block, source: "_Edit"
) -> None:
    prefix = f"block {block.local_id}: "
    record = source.answer_lines(published)
    written = edit.answer_lines(block)
    if written == record:
        return
    indent = edit.indent(block)
    restored: list[str] = []
    marks: list[tuple[int, str]] = []
    for key, lines in record.items():
        if written.get(key) != lines:
            marks.append(
                (
                    len(restored),
                    f"{prefix}`{key}:` is the record's,"
                    f" {published.by}'s answer; reverted",
                )
            )
        restored.extend(_indented(lines, indent))
    marks.extend(
        (
            0,
            f"{prefix}`{key}:` beside {published.by}'s answer is the"
            " record's to write; dropped",
        )
        for key in written
        if key not in record
    )
    after = _mapping_end(block)
    for span in _answer_spans(block).values():
        edit.drop(span)
    edit.insert(after, restored, marks)


def _drop_unheld(edit: "_Edit", block: Block) -> None:
    for key, span in _answer_spans(block).items():
        edit.drop(
            span,
            f"block {block.local_id}: `{key}:` is {block.by}'s answer, which the"
            " record does not hold; dropped",
        )


def _restored(block: Block) -> list[tuple[int, str]]:
    return [
        (0, f"block {block.local_id}: only the draft's blocks may be removed; restored")
    ]


def _place_blocks(
    edit: "_Edit",
    blocks: Sequence[Block],
    present: Mapping[str, Block],
    source: "_Edit",
    marks: Callable[[Block], list[tuple[int, str]]],
) -> None:
    """Each of `blocks` that `present` lacks, its fence as `source` has it,
    after the nearest block before it that `present` has, else before the
    nearest after it, else at the end; each of its marks at its line of the
    fence."""
    appended = False
    for index, block in enumerate(blocks):
        if block.local_id in present:
            continue
        fence = [source.content(number) for number in _numbers(block.fence)]
        before = next(
            (
                present[b.local_id]
                for b in reversed(blocks[:index])
                if b.local_id in present
            ),
            None,
        )
        after = next(
            (present[b.local_id] for b in blocks[index + 1 :] if b.local_id in present),
            None,
        )
        if before is not None:
            edit.insert(before.fence.last, ["", *fence], _shifted(marks(block), 1))
        elif after is not None:
            edit.insert(after.fence.first - 1, [*fence, ""], marks(block))
        else:
            lead = [""] if edit.lines or appended else []
            edit.insert(
                len(edit.lines), [*lead, *fence], _shifted(marks(block), len(lead))
            )
            appended = True


def _carry_prose(published: str, merged: str, reverted: tuple[Fault, ...]) -> Merge:
    """A registered document a person has answered in (F32.7): where the
    merged save's body prose differs from the published one, the published
    body under the save's front matter, each block as the merge left it, and
    each block the save added placed beside its neighbours; the save's title
    written into that front matter where it stood in a first heading of the
    body reverted."""
    ours, theirs = parse(published), parse(merged)
    source = _Edit(merged)
    known = {block.local_id for block in ours.blocks}
    held = _body(ours, _Edit(published), known)
    saved = _body(theirs, source, known)
    if [token for token, _ in held] == [token for token, _ in saved]:
        return Merge(merged, reverted)
    differs = next(
        (
            index
            for index, (one, other) in enumerate(zip(held, saved, strict=False))
            if one[0] != other[0]
        ),
        min(len(held), len(saved)),
    )

    def marks(block: Block) -> list[tuple[int, str]]:
        return [
            (fault.line - block.fence.first, fault.message)
            for fault in reverted
            if fault.line is not None and fault.line in _numbers(block.fence)
        ]

    edit = _Edit(_with_ending(published, source.ending))
    front = ours.front_matter.span
    if front is not None:
        edit.drop(front)
    if theirs.front_matter.span is not None:
        edit.insert(
            0 if front is None else front.last,
            [source.content(n) for n in _numbers(theirs.front_matter.span)],
        )
    carried = {block.local_id: block for block in theirs.blocks}
    for block in ours.blocks:
        kept = carried[block.local_id]
        edit.drop(block.fence)
        edit.insert(
            block.fence.last,
            [source.content(number) for number in _numbers(kept.fence)],
            marks(kept),
        )
    _place_blocks(
        edit, theirs.blocks, {b.local_id: b for b in ours.blocks}, source, marks
    )
    if differs < len(held):
        edit.mark(held[differs][1], _PROSE_REVERTED)
    text, faults = edit.apply()
    if parse(text).title is None and theirs.title is not None:
        text, faults = _titled(text, theirs.title, faults)
    if differs == len(held):
        faults = (*faults, Fault(None, _PROSE_REVERTED))
    return Merge(text, faults)


_BLANK = ("line", "")
_PROSE_REVERTED = "the body prose reverted: a person has answered in the document"


def _body(
    parsed: ParsedDocument, edit: "_Edit", known: set[str]
) -> list[tuple[tuple[str, str], int]]:
    """The text after its front matter, each token with its line: a line of
    prose by its content, every blank one alike, and a block `known` by its
    id. Another block is left out with one blank line beside it, the one
    before it else the one after it: the separator a block added brings."""
    fences = {block.fence.first: block for block in parsed.blocks}
    span = parsed.front_matter.span
    number = 1 if span is None else span.last + 1
    tokens: list[tuple[tuple[str, str], int]] = []
    separator = False
    while number <= len(edit.lines):
        block = fences.get(number)
        if block is None:
            content = edit.content(number)
            token = ("line", content) if content.strip() else _BLANK
            if not (separator and token == _BLANK):
                tokens.append((token, number))
            separator = False
            number += 1
            continue
        number = block.fence.last + 1
        if block.local_id in known:
            tokens.append((("block", block.local_id), block.fence.first))
            separator = False
        elif tokens and tokens[-1][0] == _BLANK:
            tokens.pop()
        else:
            separator = True
    return tokens


def _rewrite(
    text: str, local_id: str, operation: str, entries: list[tuple[str, str]]
) -> str:
    block = next((b for b in parse(text).blocks if b.local_id == local_id), None)
    if block is None:
        raise WriteRefused(operation, f"the text has no block {local_id}")
    edit = _Edit(text)
    edit.replace_answer(block, entries)
    return edit.apply()[0]


def _a_persons(block: Block) -> bool:
    return block.by is not None and block.by != AGENT


def _answer_spans(block: Block) -> dict[str, Span]:
    """The block's answer keys with their spans, in file order."""
    return dict(
        sorted(
            ((key, span) for key, span in block.lines.items() if key in ANSWER_KEYS),
            key=lambda entry: entry[1].first,
        )
    )


def _mapping_end(block: Block) -> int:
    """The line after which the end of the block's mapping lies: its last
    key's last line, or the line before the closing fence in a block with no
    key."""
    return max(
        (span.last for span in block.lines.values()), default=block.fence.last - 1
    )


def _numbers(span: Span) -> range:
    return range(span.first, span.last + 1)


def _shifted(marks: list[tuple[int, str]], by: int) -> list[tuple[int, str]]:
    return [(offset + by, message) for offset, message in marks]


def _with_ending(text: str, ending: str) -> str:
    """Every line of `text` ended with `ending`."""
    return ending.join(line.removesuffix("\r") for line in text.split("\n"))


def _indented(lines: Sequence[str], indent: str) -> list[str]:
    return [indent + line if line else line for line in lines]


def _time(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _render(entries: Sequence[tuple[str, str]]) -> list[str]:
    """`key: value` lines a reader with no implicit typing reads back as the
    strings written, each value trimmed as the reader trims it: plain where
    YAML allows it, a literal block over several lines, double-quoted and
    escaped where a value holds a character YAML breaks a line at and the file
    does not. A literal block's lines stand four spaces in from its key, past
    the three a closing fence may have."""
    lines: list[str] = []
    for key, value in entries:
        trimmed = value.strip()
        style = (
            '"'
            if any(char in YAML_LINE_BREAKS for char in trimmed)
            else "|"
            if "\n" in trimmed
            else None
        )
        node = yaml.MappingNode(
            _MAP,
            [(yaml.ScalarNode(_STR, key), yaml.ScalarNode(_STR, trimmed, style=style))],
        )
        written = yaml.serialize(
            node,
            Dumper=yaml.BaseDumper,
            width=_UNBOUNDED,
            allow_unicode=True,
            indent=_FENCE_PROOF_INDENT,
        )
        lines.extend(written.split("\n")[:-1])
    return lines


class _Edit:
    """Line edits on one text, applied together by the line numbers its parse
    gives; a fault placed on an inserted or a dropped line lands on its line
    in the result."""

    def __init__(self, text: str) -> None:
        parts = text.split("\n")
        self.lines = [part + "\n" for part in parts[:-1]]
        if parts[-1]:
            self.lines.append(parts[-1])
        first = text.find("\n")
        self.ending = "\r\n" if first > 0 and text[first - 1] == "\r" else "\n"
        self._dropped: dict[int, list[str]] = {}
        self._marked: dict[int, list[str]] = {}
        self._inserted: dict[int, list[tuple[list[str], list[tuple[int, str]]]]] = {}

    def content(self, number: int) -> str:
        """Line `number` without its ending, as the reader reads it."""
        return self.lines[number - 1].removesuffix("\n").removesuffix("\r")

    def indent(self, block: Block) -> str:
        """The indentation of the block's mapping: its first key's, else its
        opening fence's."""
        first = min(
            (span.first for span in block.lines.values()), default=block.fence.first
        )
        line = self.content(first)
        return line[: len(line) - len(line.lstrip(" "))]

    def answer_lines(self, block: Block) -> dict[str, tuple[str, ...]]:
        """The block's answer keys, each with its lines out of the mapping's
        indentation."""
        width = len(self.indent(block))
        return {
            key: tuple(
                _outdented(self.content(number), width) for number in _numbers(span)
            )
            for key, span in _answer_spans(block).items()
        }

    def replace_answer(self, block: Block, entries: Sequence[tuple[str, str]]) -> None:
        after = _mapping_end(block)
        for span in _answer_spans(block).values():
            self.drop(span)
        if entries:
            self.insert(after, _indented(_render(entries), self.indent(block)))

    def drop(self, span: Span, fault: str | None = None) -> None:
        for number in _numbers(span):
            self._dropped.setdefault(number, [])
        if fault is not None:
            self._dropped[span.first].append(fault)

    def mark(self, number: int, fault: str) -> None:
        """A fault at line `number`, kept or dropped."""
        self._marked.setdefault(number, []).append(fault)

    def insert(
        self, after: int, lines: list[str], faults: Sequence[tuple[int, str]] = ()
    ) -> None:
        """`lines` after line `after` (0 for the top), each fault at its
        offset among them."""
        self._inserted.setdefault(after, []).append((lines, list(faults)))

    def apply(self) -> tuple[str, tuple[Fault, ...]]:
        out: list[str] = []
        faults: list[Fault] = []

        def emit(after: int) -> None:
            for lines, marks in self._inserted.get(after, ()):
                if out and not out[-1].endswith("\n"):
                    out[-1] += self.ending
                start = len(out) + 1
                out.extend(line + self.ending for line in lines)
                faults.extend(
                    Fault(start + offset, message) for offset, message in marks
                )

        emit(0)
        for number, line in enumerate(self.lines, start=1):
            faults.extend(Fault(len(out) + 1, m) for m in self._marked.get(number, ()))
            if number in self._dropped:
                faults.extend(Fault(len(out) + 1, m) for m in self._dropped[number])
            else:
                out.append(line)
            emit(number)
        return "".join(out), tuple(sorted(faults, key=lambda fault: fault.line or 0))


def _outdented(line: str, width: int) -> str:
    return line[min(width, len(line) - len(line.lstrip(" "))) :]
