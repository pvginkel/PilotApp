"""A conversation in the reader (F165.4, F165.7): its blocks from its reading
(F152.13), as the backend keeps it (`readings`), joined to the calls' facts
by the id the facts carry, under the size rule, the server's (F154.7).

- **The calls are the chart's**: the Calls of the thread in the order a
  conversation's calls are (`items.ItemsService.calls`), at most
  `items.CALLS`; past it the answer stops and says so. Each takes its blocks
  from the reading's Call of its `message_id`; a Call the reading does not
  hold has none, and what follows the reading's last Call stands on that
  Call where the reader holds it.
- **Blocks cut at `CUT` characters, in batches of `BATCH` calls**: each text
  a block holds, its words, its result's or what its tool call was given,
  cut to its first `CUT` characters, those a tool call was given taken
  together in their order; a cut block carries its full length. The batches
  are taken in their order, the one holding the selected call first.
- **The full texts in one answer** where every block's texts add up to
  `WHOLE` characters or less; otherwise one block's whole as it opens.
- **A reading refused or gone** is an answer of its own, with why.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, assert_never

from pilot_collection.reading import (
    AttachmentBlockSchema,
    ImageBlockSchema,
    ReadCallSchema,
    ReadingSchema,
    SyntheticBlockSchema,
    SystemBlockSchema,
    TextBlockSchema,
    ThinkingBlockSchema,
    ToolCallBlockSchema,
    ToolResultBlockSchema,
    UserBlockSchema,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.dashboard.address import Address, AddressService
from app.dashboard.bounds import Bounds
from app.dashboard.items import CALLS
from app.dashboard.readings import Gone, ReadingsService, Refused, Served
from app.exceptions import RecordNotFoundException
from app.models import Call, Transcript

CUT = 1_500
"""The characters of a block's text before it is cut."""

BATCH = 200
"""The calls a batch holds."""

WHOLE = 2_000_000
"""The characters a conversation's full texts add up to at most, for them to
come in one answer (F154.7's 2 MB)."""

type Block = (
    UserBlockSchema
    | ImageBlockSchema
    | SyntheticBlockSchema
    | AttachmentBlockSchema
    | SystemBlockSchema
    | ToolResultBlockSchema
    | TextBlockSchema
    | ThinkingBlockSchema
    | ToolCallBlockSchema
)
"""A block of a reading, of what came in or of what a Call put out."""

type Part = Literal["received", "sent", "after"]
"""Where a block stands on its call: in what came in before it, in what it
put out, or in what follows the conversation's last call."""

PARTS: tuple[Part, ...] = ("received", "sent", "after")

type Status = Literal["served", "gone", "refused"]
"""What the read of the reading gave: the reading, a transcript gone from
the collector's home, or the collector's refusal, with why."""


@dataclass(frozen=True)
class BlockShown:
    """A block as the reader answers it: cut, `length` its texts' full
    characters where it was, none where it is whole."""

    block: Block
    length: int | None


@dataclass(frozen=True)
class CallBlocks:
    """A call's blocks: none, and `held` false, where the reading holds no
    such Call; `after` on the reading's last Call alone."""

    call: int
    held: bool
    received: tuple[BlockShown, ...]
    sent: tuple[BlockShown, ...]
    after: tuple[BlockShown, ...]


@dataclass(frozen=True)
class Head:
    """What every answer of the reader says: the view's address, the read's
    status and why, where it is refused; and, where the reading is served,
    the calls the reader holds of the thread's `total`, whether it stopped
    at `items.CALLS`, the batches in the order to take them, the selected
    call's first, the characters the full texts add up to and whether they
    come in one answer."""

    address: Address
    conversation: uuid.UUID
    status: Status
    why: str | None
    total: int
    held: int
    stopped: bool
    batches: tuple[int, ...]
    characters: int | None
    whole: bool | None


@dataclass(frozen=True)
class Batch:
    """One batch of a conversation's calls, each with its blocks cut; none
    where the reading is not served."""

    head: Head
    batch: int | None
    calls: tuple[CallBlocks, ...]


@dataclass(frozen=True)
class Placed:
    """A block whole, at its place: its call, its part and its index in it."""

    call: int
    part: Part
    index: int
    block: Block


@dataclass(frozen=True)
class Texts:
    """Every block cut, whole, where the full texts come in one answer."""

    head: Head
    texts: tuple[Placed, ...]


@dataclass(frozen=True)
class Opened:
    """One block whole, none where the reading is not served."""

    head: Head
    block: Placed | None


@dataclass(frozen=True)
class _Thread:
    """The thread's Calls the reader holds, in their order, by id and
    `message_id`, and the count of all of them."""

    transcript: Transcript
    calls: tuple[tuple[int, str], ...]
    total: int


class ReaderService:
    """A conversation in the reader, from its state as the URL writes it."""

    def __init__(
        self,
        db: Session,
        address_service: AddressService,
        bounds: Bounds,
        readings_service: ReadingsService,
    ) -> None:
        self.db = db
        self.address_service = address_service
        self.bounds = bounds
        self.readings_service = readings_service

    def batch(
        self, written: str, conversation: uuid.UUID, batch: int | None = None
    ) -> Batch:
        """The batch `batch` of the thread `conversation`'s calls, else the
        one holding the call the state `written` selects, each call with its
        blocks cut.

        Raises:
            StateRefusedException: the state has a fault
            RecordNotFoundException: the record holds no such thread
            QueryRefusedException: a statement passed the engine's bounds
        """
        view = self.address_service.view(written)
        address = view.address
        thread = self._thread(conversation, view.deadline)
        head, blocks = self._head(address, conversation, thread)
        taken = head.batches[0] if batch is None and head.batches else batch
        if blocks is None or taken is None:
            return Batch(head, None, ())
        return Batch(
            head,
            taken,
            tuple(
                _cut_call(call, blocks.get(call))
                for call, _ in thread.calls[taken * BATCH : (taken + 1) * BATCH]
            ),
        )

    def texts(self, written: str, conversation: uuid.UUID) -> Texts:
        """Every block of the thread `conversation` that a batch cuts,
        whole, where the full texts come in one answer; none where they do
        not.

        Raises:
            StateRefusedException: the state has a fault
            RecordNotFoundException: the record holds no such thread
            QueryRefusedException: a statement passed the engine's bounds
        """
        view = self.address_service.view(written)
        address = view.address
        thread = self._thread(conversation, view.deadline)
        head, blocks = self._head(address, conversation, thread)
        if blocks is None or not head.whole:
            return Texts(head, ())
        return Texts(
            head,
            tuple(
                Placed(call, part, index, block)
                for call, _ in thread.calls
                for part, index, block in _placed(blocks.get(call))
                if _cut(block).length is not None
            ),
        )

    def block(
        self,
        written: str,
        conversation: uuid.UUID,
        call: int,
        part: Part,
        index: int,
    ) -> Opened:
        """The block at `index` of the part `part` of the call `call` of the
        thread `conversation`, whole.

        Raises:
            StateRefusedException: the state has a fault
            RecordNotFoundException: the record holds no such thread, or the
                reading no such block on a call the reader holds
            QueryRefusedException: a statement passed the engine's bounds
        """
        view = self.address_service.view(written)
        address = view.address
        thread = self._thread(conversation, view.deadline)
        head, blocks = self._head(address, conversation, thread)
        if blocks is None:
            return Opened(head, None)
        held = _part(blocks.get(call), part)
        if index >= len(held):
            raise RecordNotFoundException(
                "Block", f"{index} of the {part} of call {call} of {conversation}"
            )
        return Opened(head, Placed(call, part, index, held[index]))

    def _thread(self, conversation: uuid.UUID, deadline: float) -> _Thread:
        with self.bounds.read(self.db, deadline) as db:
            found = db.execute(
                select(Transcript.id, Transcript.session_id, Transcript.agent_id).where(
                    Transcript.id == conversation
                )
            ).one_or_none()
            if found is None:
                raise RecordNotFoundException("Conversation", str(conversation))
            calls = db.execute(
                select(Call.id, Call.message_id)
                .where(Call.transcript_id == conversation)
                .order_by(Call.position, Call.id)
                .limit(CALLS)
            ).all()
            total = db.scalar(
                select(func.count())
                .select_from(Call)
                .where(Call.transcript_id == conversation)
            )
        assert total is not None
        return _Thread(
            Transcript(
                id=found.id, session_id=found.session_id, agent_id=found.agent_id
            ),
            tuple((one.id, one.message_id) for one in calls),
            total,
        )

    def _head(
        self, address: Address, conversation: uuid.UUID, thread: _Thread
    ) -> tuple[Head, dict[int, _Found] | None]:
        """The head of an answer, with the blocks of each Call the reading
        holds where it is served; the reading asked of the collector at
        every answer, outside the engine's bounds."""
        read = self.readings_service.read(thread.transcript)
        if isinstance(read, Gone):
            return _unread(address, conversation, thread, "gone", None), None
        if isinstance(read, Refused):
            return _unread(address, conversation, thread, "refused", read.why), None
        if not isinstance(read, Served):
            assert_never(read)
        blocks = _blocks(read.reading, thread)
        characters = sum(
            _characters(block)
            for call, _ in thread.calls
            for _, _, block in _placed(blocks.get(call))
        )
        return (
            Head(
                address=address,
                conversation=conversation,
                status="served",
                why=None,
                total=thread.total,
                held=len(thread.calls),
                stopped=thread.total > len(thread.calls),
                batches=_batches(address, thread),
                characters=characters,
                whole=characters <= WHOLE,
            ),
            blocks,
        )


def _unread(
    address: Address,
    conversation: uuid.UUID,
    thread: _Thread,
    status: Status,
    why: str | None,
) -> Head:
    return Head(
        address=address,
        conversation=conversation,
        status=status,
        why=why,
        total=thread.total,
        held=len(thread.calls),
        stopped=thread.total > len(thread.calls),
        batches=(),
        characters=None,
        whole=None,
    )


def _batches(address: Address, thread: _Thread) -> tuple[int, ...]:
    """The batches of the thread's calls, the one holding the selected call
    first, then the others in their order."""
    ids = [call for call, _ in thread.calls]
    batches = range(-(-len(ids) // BATCH))
    selected = address.state.call
    first = ids.index(selected) // BATCH if selected in ids else 0
    return tuple(sorted(batches, key=lambda batch: batch != first))


@dataclass(frozen=True)
class _Found:
    """A Call's blocks in the reading, with what follows the last Call where
    it is the reading's last."""

    received: Sequence[Block]
    sent: Sequence[Block]
    after: Sequence[Block]


def _blocks(reading: ReadingSchema, thread: _Thread) -> dict[int, _Found]:
    """The blocks of each of the thread's Calls the reading holds, by the
    Call's id."""
    by_message: dict[str, ReadCallSchema] = {
        call.message_id: call for call in reading.calls
    }
    last = reading.calls[-1].message_id if reading.calls else None
    found: dict[int, _Found] = {}
    for call, message_id in thread.calls:
        read = by_message.get(message_id)
        if read is not None:
            found[call] = _Found(
                read.received,
                read.sent,
                reading.after if message_id == last else (),
            )
    return found


def _part(found: _Found | None, part: Part) -> Sequence[Block]:
    if found is None:
        return ()
    if part == "received":
        return found.received
    if part == "sent":
        return found.sent
    return found.after


def _placed(found: _Found | None) -> list[tuple[Part, int, Block]]:
    return [
        (part, index, block)
        for part in PARTS
        for index, block in enumerate(_part(found, part))
    ]


def _cut_call(call: int, found: _Found | None) -> CallBlocks:
    return CallBlocks(
        call=call,
        held=found is not None,
        received=tuple(_cut(block) for block in _part(found, "received")),
        sent=tuple(_cut(block) for block in _part(found, "sent")),
        after=tuple(_cut(block) for block in _part(found, "after")),
    )


def _characters(block: Block) -> int:
    """The characters of a block's texts: its words, its result's and the
    strings its tool call was given."""
    if isinstance(block, ToolCallBlockSchema):
        result = 0 if block.result is None else len(block.result.text)
        return _strings(block.input) + result
    if isinstance(block, ImageBlockSchema):
        return 0
    return len(block.text or "")


def _strings(value: Any) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(_strings(one) for one in value.values())
    if isinstance(value, list):
        return sum(_strings(one) for one in value)
    return 0


def _cut(block: Block) -> BlockShown:
    """The block with each of its texts cut to its first `CUT` characters,
    the strings a tool call was given taken together in their order."""
    if isinstance(block, ToolCallBlockSchema):
        given, left = _cut_given(block.input, CUT)
        result = block.result
        cut_result = (
            None
            if result is None or len(result.text) <= CUT
            else result.model_copy(update={"text": result.text[:CUT]})
        )
        if left >= 0 and cut_result is None:
            return BlockShown(block, None)
        update: dict[str, Any] = {"input": given}
        if cut_result is not None:
            update["result"] = cut_result
        return BlockShown(block.model_copy(update=update), _characters(block))
    if isinstance(block, ImageBlockSchema):
        return BlockShown(block, None)
    text = block.text
    if text is None or len(text) <= CUT:
        return BlockShown(block, None)
    return BlockShown(block.model_copy(update={"text": text[:CUT]}), len(text))


def _cut_given(value: Any, left: int) -> tuple[Any, int]:
    """A tool call's input with its strings cut to `left` characters
    together, in their order, and the characters left after them, below zero
    where some was cut."""
    if isinstance(value, str):
        if len(value) <= max(left, 0):
            return value, left - len(value)
        return value[: max(left, 0)], -1
    if isinstance(value, dict):
        cut: dict[str, Any] = {}
        for key, one in value.items():
            cut[key], left = _cut_given(one, left)
        return cut, left
    if isinstance(value, list):
        items = []
        for one in value:
            taken, left = _cut_given(one, left)
            items.append(taken)
        return items, left
    return value, left
