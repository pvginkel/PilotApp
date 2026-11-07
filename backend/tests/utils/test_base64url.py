"""base64url without padding (RFC 4648 §5)."""

import binascii

import pytest

from app.utils.base64url import b64, unb64


class TestBase64Url:
    @pytest.mark.parametrize(
        ("value", "encoded"),
        [(b"", ""), (b"\xfb", "-w"), (b"\xfb\xff", "-_8"), (b"\xfb\xff\xfe", "-__-")],
    )
    def test_it_writes_the_url_alphabet_with_no_padding(
        self, value: bytes, encoded: str
    ) -> None:
        assert b64(value) == encoded
        assert unb64(encoded) == value

    def test_it_reads_a_value_with_its_padding(self) -> None:
        assert unb64("-w==") == b"\xfb"

    def test_a_value_out_of_the_alphabet_is_refused(self) -> None:
        with pytest.raises(binascii.Error):
            unb64("a")
