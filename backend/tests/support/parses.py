"""Each text the block DSL parses in a test, with no reading kept from
before it (`pilot_dsl.reader`)."""

import pytest
from pilot_dsl import ParsedDocument, reader


def parses(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Each text the block DSL parses from here on, in order."""
    texts: list[str] = []
    parse = reader._parse

    def counted(text: str) -> ParsedDocument:
        texts.append(text)
        return parse(text)

    monkeypatch.setattr(reader, "_parse", counted)
    monkeypatch.setattr(reader, "_readings", reader._Readings(reader._KEPT))
    return texts
