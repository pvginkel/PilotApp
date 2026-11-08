"""A closed chat's paragraphs kept with its last record, within a bound."""

import uuid

from app.engine.closed_chats import ClosedChats


class TestClosedChats:
    def test_a_chats_paragraphs_are_handed_back_for_the_last_record_alone(
        self,
    ) -> None:
        chats = ClosedChats()
        chat = uuid.uuid4()

        chats.keep(chat, 7, ("Hi.", "Done."))

        assert chats.get(chat, 7) == ("Hi.", "Done.")
        assert chats.get(chat, 8) is None
        assert chats.get(chat, None) is None
        assert chats.get(uuid.uuid4(), 7) is None

    def test_a_chat_without_a_record_is_kept_under_none(self) -> None:
        chats = ClosedChats()
        chat = uuid.uuid4()

        chats.keep(chat, None, ())

        assert chats.get(chat, None) == ()

    def test_a_chats_paragraphs_replace_those_kept_before(self) -> None:
        chats = ClosedChats(limit=10)
        chat, other = uuid.uuid4(), uuid.uuid4()
        chats.keep(chat, 1, ("abcdef",))
        chats.keep(other, 1, ("abcd",))

        chats.keep(chat, 2, ("abcdef",))

        assert chats.get(chat, 1) is None
        assert chats.get(chat, 2) == ("abcdef",)
        assert chats.get(other, 1) == ("abcd",)

    def test_past_the_bound_the_chat_read_least_recently_is_dropped(self) -> None:
        chats = ClosedChats(limit=10)
        first, second, third = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        chats.keep(first, 1, ("ab", "cd"))
        chats.keep(second, 1, ("abcd",))
        chats.get(first, 1)

        chats.keep(third, 1, ("abcd",))

        assert chats.get(second, 1) is None
        assert chats.get(first, 1) == ("ab", "cd")
        assert chats.get(third, 1) == ("abcd",)

    def test_a_chat_longer_than_the_bound_is_not_kept(self) -> None:
        chats = ClosedChats(limit=10)
        chat = uuid.uuid4()
        chats.keep(chat, 1, ("abcd",))

        chats.keep(chat, 2, ("abcdef", "ghijk"))

        assert chats.get(chat, 1) is None
        assert chats.get(chat, 2) is None
