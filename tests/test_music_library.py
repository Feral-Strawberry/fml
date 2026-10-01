"""Musiksammlung (#224, ADR 0094): Interpret/Album/Genre in Grammatik,
Seitenleisten-Facetten und Sortierung „Album"."""

from __future__ import annotations

import pytest

from feral.db import connect, store_extraction
from feral.db.store import store_interpretations
from feral.extract.types import ContainerExtraction
from feral.interpret.types import InterpretedField, Interpretation
from feral.web import filters, library


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    yield conn
    conn.close()


def _song(db, h, **tags):
    store_extraction(db, file_hash=h, file_size=1, path=f"/m/{h[:4]}.mp3",
                     extraction=ContainerExtraction(container="mp3", media_kind="audio"))
    fields = []
    for field, value in tags.items():
        for v in value if isinstance(value, list) else [value]:
            fields.append(InterpretedField(field, v))
    if fields:
        store_interpretations(db, file_hash=h, interpretations=[
            Interpretation(parser="audio", parser_version=2, fields=fields)])


def _seed(db):
    # Album von Nena (Album-Interpret gesetzt), ein Sampler, ein Song ohne
    # Album-Interpret (Rückfall auf den Interpreten), ein Song ohne Tags.
    _song(db, "a" * 64, artist="Nena", album_artist="Nena", album="99 Luftballons",
          track="2", disc="1", genre="Pop")
    _song(db, "b" * 64, artist="Nena", album_artist="Nena", album="99 Luftballons",
          track="10", disc="1", genre="Pop")
    _song(db, "c" * 64, artist="Nena", album_artist="Various Artists", album="Bravo Hits",
          track="1", genre=["Pop", "NDW"])
    _song(db, "d" * 64, artist="Kim Wilde", album="Select", track="1")
    _song(db, "e" * 64)


def _hashes(db, expr):
    return {i["file_hash"][0] for i in library.list_items(db, filter_expr=expr)["items"]}


def test_interpret_is_album_artist_else_artist(db):
    _seed(db)
    assert _hashes(db, 'interpret: "Nena"') == {"a", "b"}
    assert _hashes(db, 'interpret: "Various Artists"') == {"c"}
    assert _hashes(db, 'albumartist: "Kim Wilde"') == {"d"}   # englischer Alias
    assert _hashes(db, "artist: nena") == {"a", "b", "c"}      # Titel-Interpret
    assert _hashes(db, 'album: "Bravo Hits" | Select') == {"c", "d"}
    assert _hashes(db, "genre: ndw") == {"c"}
    assert filters.serialize(filters.parse('albumartist: "X"')) == 'interpret: "X"'
    with pytest.raises(ValueError):
        filters.parse("album_artist: x")


def test_music_facets_base_and_context(db):
    _seed(db)
    base = library.facets_payload(db)
    assert base["interprets"] == [{"name": "Kim Wilde", "count": 1},
                                  {"name": "Nena", "count": 2},
                                  {"name": "Various Artists", "count": 1}]
    assert [a["name"] for a in base["albums"]] == ["99 Luftballons", "Bravo Hits", "Select"]
    assert {g["name"]: g["count"] for g in base["genres"]} == {"NDW": 1, "Pop": 3}
    ctx = library.facets_payload(db, filter_expr='interpret: "Nena"', base=base)
    # Eigene Gruppe klammert den eigenen Chip aus, die anderen zählen im Kontext.
    assert {a["name"]: a["count"] for a in ctx["interprets"]}["Kim Wilde"] == 1
    assert {a["name"]: a["count"] for a in ctx["albums"]} == {
        "99 Luftballons": 2, "Bravo Hits": 0, "Select": 0}


def test_sort_album_runs_in_album_order_untagged_last(db):
    _seed(db)
    order = [i["file_hash"][0] for i in library.list_items(db, sort="album")["items"]]
    # kim wilde < nena < various artists; Titel 2 vor 10 (vierstellig); ohne Tags hinten
    assert order == ["d", "a", "b", "c", "e"]
    back = [i["file_hash"][0] for i in library.list_items(db, sort="album-ab")["items"]]
    assert back == ["c", "b", "a", "d", "e"]
    assert filters.sort_directive(filters.parse("sort: album")) == "album"


def test_grid_rows_carry_artist_and_album(db):
    _seed(db)
    rows = {i["file_hash"][0]: i for i in library.list_items(db)["items"]}
    assert (rows["c"]["artist"], rows["c"]["album"]) == ("Nena", "Bravo Hits")
    assert "artist" not in rows["e"]


def test_album_without_track_numbers_runs_by_file_name(db):
    # Rips heißen „01 Titel.mp3": ohne TRCK ordnet der Dateiname das Album.
    for h, name in (("f" * 64, "02 Zwei"), ("g" * 64, "10 Zehn"), ("h" * 64, "01 Eins")):
        store_extraction(db, file_hash=h, file_size=1, path=f"/m/{name}.mp3",
                         extraction=ContainerExtraction(container="mp3", media_kind="audio"))
        store_interpretations(db, file_hash=h, interpretations=[Interpretation(
            parser="audio", parser_version=2,
            fields=[InterpretedField("artist", "Band"), InterpretedField("album", "Demo")])])
    order = [i["file_hash"][0] for i in library.list_items(db, sort="album")["items"]]
    assert order == ["h", "f", "g"]
