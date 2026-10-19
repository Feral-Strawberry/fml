"""Songtext von Hand (#285, ADR 0106): Eingabeprüfung, Projektion in
Schicht 2, Vorlage aus der Datei, Überdeckung samt Volltext, Neu-
Interpretieren, Wiederherstellen und Schnittstelle."""

from __future__ import annotations

import json

import pytest

from feral.db import connect, manual_fields, manual_lyrics, store_extraction
from feral.db.store import store_interpretations
from feral.extract.types import ContainerExtraction, RawMetadataItem
from feral.interpret import interpret_items, reparse_database
from feral.interpret.reparse import raw_items_for, reinterpret
from feral.messages import UserError

SUNO = "a" * 64
PLAIN = "b" * 64
IMAGE = "c" * 64

# Suno-artige Untertitel-Spur: [Guitar Solo] trägt die Zeit des nächsten
# gesungenen Worts und wird beim Lesen ans Ende der Zeile davor geschätzt.
SRT = """1
00:00:10,000 --> 00:00:12,000
[Verse]

2
00:00:10,000 --> 00:00:13,000
Erste Zeile

3
00:00:14,000 --> 00:00:30,000
Zweite Zile

4
00:00:30,000 --> 00:00:33,000
[Guitar Solo]

5
00:00:30,000 --> 00:00:33,000
[Chorus]

6
00:00:30,000 --> 00:00:34,000
Altrefrain hier
"""


def _put(db, tmp_path, h, name, items=(), *, kind="audio", container="mp4"):
    path = tmp_path / name
    path.write_bytes(b"x")
    store_extraction(db, file_hash=h, file_size=1, path=str(path),
                     extraction=ContainerExtraction(container=container, media_kind=kind,
                                                    items=list(items)))
    store_interpretations(db, file_hash=h, interpretations=interpret_items(raw_items_for(db, h)))


def _songs(db, tmp_path):
    _put(db, tmp_path, SUNO, "suno.m4a",
         [RawMetadataItem("isobmff:stream2.subtitle", "srt", SRT, None, "utf-8")])
    _put(db, tmp_path, PLAIN, "eigen.mp3",
         [RawMetadataItem("id3v2:USLT", "eng:", "Strophe eins\n\n\n  Strophe   zwei \n", None,
                          "utf-8")], container="mp3")
    _put(db, tmp_path, IMAGE, "bild.png", kind="image", container="png")


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    _songs(conn, tmp_path)
    yield conn
    conn.close()


def _rows(db, h, field):
    return [(r[0], r[1]) for r in db.execute(
        """SELECT parser, value_text FROM interpreted_metadata
            WHERE file_hash = ? AND field = ? ORDER BY parser, ordinal""", (h, field))]


def _save(db, h, lines):
    with db:
        assert manual_lyrics.set_lyrics(db, h, manual_lyrics.check_lines(lines))
        reinterpret(db, [h])


def _found(db, word):
    return [r[0] for r in db.execute(
        "SELECT file_hash FROM search_index WHERE search_index MATCH ?",
        (f"{{interp names manuell}} : {word}",))]


def test_check_lines_tidies_and_keeps_order():
    lines = manual_lyrics.check_lines([
        [None, None, "  "], [1000, 900, "  eins \t zwei "], [None, None, ""],
        [None, None, ""], [2000, 2500, "drei"], [2500.0, None, "[Chorus]"], [None, None, ""],
    ])
    assert lines == [[1000, None, "eins zwei"], [None, None, ""], [2000, 2500, "drei"],
                     [2500, None, "[Chorus]"]]
    assert manual_lyrics.check_lines([[None, None, " "]]) == []
    # Endzeit hinter dem Song fällt weg, die Startzeit nicht.
    assert manual_lyrics.check_lines([[0, 999_999, "a"]], duration=10) == [[0, None, "a"]]


@pytest.mark.parametrize("raw, key", [
    ("text", "lyricsInvalid"),
    ([[0, None]], "lyricsInvalid"),
    ([["1", None, "a"]], "lyricsInvalid"),
    ([[True, None, "a"]], "lyricsInvalid"),
    ([[1.5, None, "a"]], "lyricsInvalid"),
    ([[-1, None, "a"]], "lyricsInvalid"),
    ([[None, None, "a\x07b"]], "lyricsInvalid"),
    ([[None, None, "x" * 501]], "lyricsInvalid"),
    ([[2000, None, "a"], [None, None, "b"], [1000, None, "c"]], "lyricsOrder"),
    ([[None, None, "a"]] * 2001, "lyricsTooLong"),
])
def test_check_lines_rejects(raw, key):
    with pytest.raises(UserError) as err:
        manual_lyrics.check_lines(raw)
    assert err.value.message["key"] == key


def test_start_beyond_the_song_is_rejected():
    with pytest.raises(UserError):
        manual_lyrics.check_lines([[12_000, None, "a"]], duration=10)


def test_projection_times_only_when_every_line_has_one():
    timed = [[1000, 2000, "[Verse]"], [1000, None, "eins"], [None, None, ""], [3000, None, "zwei"]]
    out = manual_lyrics.projection(timed)
    assert out["lyrics"] == ["[Verse]\neins\n\nzwei"]
    assert json.loads(out["lyrics_synced"][0]) == [[1000, 2000, "[Verse]"], [1000, None, "eins"],
                                                    [3000, None, "zwei"]]
    assert json.loads(out["song_sections"][0]) == [[1000, "Verse"]]
    partly = [[1000, None, "eins"], [None, None, "zwei"]]
    assert set(manual_lyrics.projection(partly)) == {"lyrics"}
    assert manual_lyrics.projection([]) == {}


def test_template_from_file_writes_the_solo_estimate_once(db):
    state = manual_lyrics.editable(db, SUNO)
    assert not state["manual"]
    starts = {text: start for start, _end, text in state["lines"]}
    # Ende von „Zweite Zile": 14 s + 2,5 s + 2 × 0,7 s (Singdauer-Regel).
    assert starts["[Guitar Solo]"] == 17_900 and starts["[Chorus]"] == 30_000
    plain = manual_lyrics.editable(db, PLAIN)["lines"]
    assert plain == [[None, None, "Strophe eins"], [None, None, ""], [None, None, "Strophe zwei"]]


def test_manual_lyrics_cover_all_three_fields_and_the_search(db):
    lines = manual_lyrics.editable(db, SUNO)["lines"]
    lines[-1][2] = "Neurefrain hier"
    _save(db, SUNO, lines)
    assert [p for p, _ in _rows(db, SUNO, "lyrics")] == ["manual"]
    synced = _rows(db, SUNO, "lyrics_synced")
    assert [p for p, _ in synced] == ["manual"] and "Neurefrain" in synced[0][1]
    sections = json.loads(_rows(db, SUNO, "song_sections")[0][1])
    assert sections == [[10_000, "Verse"], [17_900, "Guitar Solo"], [30_000, "Chorus"]]
    assert _found(db, "Neurefrain") == [SUNO] and _found(db, "Altrefrain") == []
    assert manual_lyrics.editable(db, SUNO)["manual"]


def test_untimed_text_drops_the_synced_rows(db):
    _save(db, SUNO, [[None, None, "nur Text"]])
    assert _rows(db, SUNO, "lyrics") == [("manual", "nur Text")]
    assert _rows(db, SUNO, "lyrics_synced") == [] and _rows(db, SUNO, "song_sections") == []


def test_song_without_lyrics_gets_them_and_other_kinds_are_skipped(db, tmp_path):
    bare = "d" * 64
    _put(db, tmp_path, bare, "leer.mp3", container="mp3")
    assert manual_lyrics.editable(db, bare)["lines"] == []
    _save(db, bare, [[None, None, "Eigener Text"]])
    assert _rows(db, bare, "lyrics") == [("manual", "Eigener Text")]
    assert not manual_lyrics.set_lyrics(db, IMAGE, [[None, None, "x"]])


def test_reparse_keeps_the_manual_text_and_sees_it_unchanged(db):
    _save(db, PLAIN, [[None, None, "korrigiert"]])
    report = reparse_database(db)
    assert report.items_unchanged == report.items_total
    assert _rows(db, PLAIN, "lyrics") == [("manual", "korrigiert")]


def test_overlay_is_idempotent_with_fields_and_lyrics(db):
    with db:
        manual_fields.set_fields(db, [PLAIN], {"album": ["Album"]})
    _save(db, PLAIN, [[None, None, "korrigiert"]])
    once = manual_fields.overlay(db, PLAIN, interpret_items(raw_items_for(db, PLAIN)))
    twice = manual_fields.overlay(db, PLAIN, once)
    assert once == twice
    manual = next(i for i in once if i.parser == "manual")
    assert [f.field for f in manual.fields] == ["album", "lyrics"]


def test_empty_text_restores_the_file(db):
    _save(db, PLAIN, [[None, None, "korrigiert"]])
    _save(db, PLAIN, [])
    assert [p for p, _ in _rows(db, PLAIN, "lyrics")] == ["audio"]
    assert not manual_lyrics.editable(db, PLAIN)["manual"]


def test_rejecting_a_song_drops_its_lyrics(db):
    _save(db, PLAIN, [[None, None, "korrigiert"]])
    db.execute("DELETE FROM items WHERE file_hash = ?", (PLAIN,))
    assert db.execute("SELECT COUNT(*) FROM manual_lyrics").fetchone()[0] == 0


def _route(app, path, method):
    return next(r for r in app.routes
                if getattr(r, "path", None) == path and method in r.methods).endpoint


def test_api_reads_saves_and_rejects(tmp_path):
    from fastapi import HTTPException
    from feral.web import app as app_module

    app = app_module.create_app(tmp_path / "t.sqlite")
    try:
        conn = connect(tmp_path / "t.sqlite")
        _songs(conn, tmp_path)
        conn.close()
        get = _route(app, "/api/lyrics/{file_hash}", "GET")
        post = _route(app, "/api/lyrics/{file_hash}", "POST")
        lines = get(SUNO)["lines"]
        lines.insert(2, [11_500, None, "Neue Zeile"])
        done = post(SUNO, app_module.LyricsUpdate(lines=lines))
        assert done["state"]["manual"] and done["state"]["lines"][2][2] == "Neue Zeile"
        [row] = done["items"]
        assert row["file_hash"] == SUNO and [17_900, "Guitar Solo"] in row["sections"]
        for bad in ([[None, None, "a\x00"]], [[5000, None, "a"], [1000, None, "b"]]):
            with pytest.raises(HTTPException) as err:
                post(SUNO, app_module.LyricsUpdate(lines=bad))
            assert err.value.status_code == 400
        with pytest.raises(HTTPException) as err:
            get(IMAGE)
        assert err.value.status_code == 404
        restored = post(SUNO, app_module.LyricsUpdate(lines=[]))
        assert not restored["state"]["manual"]
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()
