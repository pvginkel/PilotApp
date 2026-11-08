"""A closed chat's paragraphs in `chat.md`, kept per chat with the id of the
last record they were read from, so that a chat's paragraphs are read again
only once a record is added to it (`ViewService.chat`)."""

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass

_KEPT = 4_000_000
"""How many characters the paragraphs kept hold at most."""


@dataclass(frozen=True)
class _Kept:
    last: int | None
    paragraphs: tuple[str, ...]
    characters: int


class ClosedChats:
    """The paragraphs of the closed chats read last, safe across threads. They
    hold `limit` characters at most, the chat read least recently dropped
    first, and a chat's longer than `limit` are not kept."""

    def __init__(self, limit: int = _KEPT) -> None:
        self._limit = limit
        self._lock = threading.Lock()
        self._kept: OrderedDict[uuid.UUID, _Kept] = OrderedDict()
        self._characters = 0

    def get(self, chat_id: uuid.UUID, last: int | None) -> tuple[str, ...] | None:
        """The chat's paragraphs, where they were kept with its last record
        `last`."""
        with self._lock:
            kept = self._kept.get(chat_id)
            if kept is None or kept.last != last:
                return None
            self._kept.move_to_end(chat_id)
            return kept.paragraphs

    def keep(
        self, chat_id: uuid.UUID, last: int | None, paragraphs: tuple[str, ...]
    ) -> None:
        """Keep the chat's paragraphs, read up to its last record `last`, in
        place of any kept before."""
        characters = sum(len(paragraph) for paragraph in paragraphs)
        with self._lock:
            replaced = self._kept.pop(chat_id, None)
            if replaced is not None:
                self._characters -= replaced.characters
            if characters > self._limit:
                return
            self._kept[chat_id] = _Kept(last, paragraphs, characters)
            self._characters += characters
            while self._characters > self._limit:
                _, dropped = self._kept.popitem(last=False)
                self._characters -= dropped.characters
