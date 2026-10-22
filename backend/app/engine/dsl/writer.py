"""The block DSL's writer: the record's own lines spliced into a document's
text, and an agent's save merged against the published text by ownership
(design 1 §6.4, TD §7.1.2).

Text in, text out, and every text one that parses with no fault: a line the
record does not own is left as written, its line ending included (TD
§7.1.4), and a line the record writes takes the text's own ending.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import yaml

from app.engine.dsl.document import AnswerChannel, Block, BlockKind, Fault, Span
from app.engine.dsl.reader import (
    AGENT,
    ANSWER_KEYS,
    YAML_LINE_BREAKS,
    DocumentKind,
    parse,
)
from app.exceptions import InvalidOperationException

_STR = "tag:yaml.org,2002:str"
_MAP = "tag:yaml.org,2002:map"
_UNBOUNDED = 2**31
_FENCE_PROOF_INDENT = 4


@dataclass(frozen=True)
class Merge:
    """An agent's save merged against the published text: the text to
    publish, and a fault per line the merge put back or took out, at its line
    in `text`, for a `reverted` Save Error."""

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
    """`title` written first in the text's front matter, one opened at the
    top where the text has none; the text as it is where its front matter
    gives a title (DB decision 50)."""
    front_matter = parse(text).front_matter
    if front_matter.title is not None:
        return text
    edit = _Edit(text)
    lines = _render([("title", title)])
    if front_matter.span is None:
        edit.insert(0, ["---", *lines, "---"])
    else:
        edit.insert(front_matter.span.first, lines)
    return edit.apply()[0]


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

    A block's answer lines are the record's when its `by` names a person. The
    record's lines changed or dropped are put back at the end of the block's
    mapping, and a person's lines the record does not hold are taken out. A
    block the save dropped is restored whole, except in the draft, where it
    goes with its answers (F47.4). Every line of the opening is the
    record's (DB 162).
    """
    if document is DocumentKind.OPENING:
        return _merge_opening(published, save)
    source = _Edit(published)
    edit = _Edit(save)
    published_blocks = parse(published).blocks
    held = {block.local_id: block for block in published_blocks}
    saved = {block.local_id: block for block in parse(save).blocks}
    for block in saved.values():
        _merge_block(edit, block, held.get(block.local_id), source)
    if document is not DocumentKind.DRAFT:
        _restore_dropped_blocks(edit, published_blocks, saved, source)
    text, reverted = edit.apply()
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


def _merge_block(
    edit: "_Edit", block: Block, published: Block | None, source: "_Edit"
) -> None:
    prefix = f"block {block.local_id}: "
    if published is not None and _a_persons(published):
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
    elif _a_persons(block):
        for key, span in _answer_spans(block).items():
            edit.drop(
                span,
                f"{prefix}`{key}:` is {block.by}'s answer, which the record does"
                " not hold; dropped",
            )


def _restore_dropped_blocks(
    edit: "_Edit",
    published: Sequence[Block],
    saved: Mapping[str, Block],
    source: "_Edit",
) -> None:
    """Each published block the save dropped, its fence as published, after
    the nearest block before it that the save keeps, else before the nearest
    after it, else at the end."""
    appended = False
    for index, block in enumerate(published):
        if block.local_id in saved:
            continue
        fence = [source.content(number) for number in _numbers(block.fence)]
        message = (
            f"block {block.local_id}: only the draft's blocks may be removed; restored"
        )
        before = next(
            (
                saved[b.local_id]
                for b in reversed(published[:index])
                if b.local_id in saved
            ),
            None,
        )
        after = next(
            (saved[b.local_id] for b in published[index + 1 :] if b.local_id in saved),
            None,
        )
        if before is not None:
            edit.insert(before.fence.last, ["", *fence], [(1, message)])
        elif after is not None:
            edit.insert(after.fence.first - 1, [*fence, ""], [(0, message)])
        else:
            lead = [""] if edit.lines or appended else []
            edit.insert(len(edit.lines), [*lead, *fence], [(len(lead), message)])
            appended = True


def _rewrite(
    text: str, local_id: str, operation: str, entries: list[tuple[str, str]]
) -> str:
    block = next((b for b in parse(text).blocks if b.local_id == local_id), None)
    if block is None:
        raise InvalidOperationException(operation, f"the text has no block {local_id}")
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
        self._ending = "\r\n" if first > 0 and text[first - 1] == "\r" else "\n"
        self._dropped: dict[int, list[str]] = {}
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
                    out[-1] += self._ending
                start = len(out) + 1
                out.extend(line + self._ending for line in lines)
                faults.extend(
                    Fault(start + offset, message) for offset, message in marks
                )

        emit(0)
        for number, line in enumerate(self.lines, start=1):
            if number in self._dropped:
                faults.extend(Fault(len(out) + 1, m) for m in self._dropped[number])
            else:
                out.append(line)
            emit(number)
        return "".join(out), tuple(sorted(faults, key=lambda fault: fault.line or 0))


def _outdented(line: str, width: int) -> str:
    return line[min(width, len(line) - len(line.lstrip(" "))) :]
