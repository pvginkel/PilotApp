"""The page a request names in `X-Sender`, as the frontend's mutation hooks
send it."""

import pytest
from flask import Flask

from app.utils.sender import SENDER_HEADER, current_sender

PAGE = "k3v9q2m7x1c8b4n6z0p5r2t8w1y7u3e9"


class TestCurrentSender:
    def test_a_request_names_its_page(self, app: Flask) -> None:
        with app.test_request_context(headers={SENDER_HEADER: PAGE}):
            assert current_sender() == PAGE

    @pytest.mark.parametrize(
        "named",
        ["", "K3V9", "page-1", "a" * 65, "a b", '"><script>'],
    )
    def test_any_other_value_names_no_page(self, app: Flask, named: str) -> None:
        with app.test_request_context(headers={SENDER_HEADER: named}):
            assert current_sender() is None

    def test_a_request_that_names_none_has_none(self, app: Flask) -> None:
        with app.test_request_context():
            assert current_sender() is None

    def test_there_is_none_off_a_request(self) -> None:
        assert current_sender() is None
