"""Tests für die Wertobjekte der Extraktion (Invarianten)."""

from __future__ import annotations

import pytest

from feral.extract.types import RawMetadataItem


def test_text_item_is_valid():
    item = RawMetadataItem(
        source="png:tEXt", keyword="parameters", text="hallo", data=None, encoding="latin-1"
    )
    assert item.text == "hallo"
    assert item.data is None


def test_binary_item_is_valid():
    item = RawMetadataItem(
        source="png:eXIf", keyword=None, text=None, data=b"\x00\x01", encoding="binary"
    )
    assert item.data == b"\x00\x01"


def test_item_requires_exactly_one_of_text_or_data():
    # Beides gesetzt -> ungültig.
    with pytest.raises(ValueError):
        RawMetadataItem(
            source="x", keyword=None, text="a", data=b"a", encoding="latin-1"
        )
    # Keines gesetzt -> ungültig.
    with pytest.raises(ValueError):
        RawMetadataItem(source="x", keyword=None, text=None, data=None, encoding="latin-1")
