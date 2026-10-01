"""Musik-Angaben von Hand (#256, ADR 0101): Ablage, Überdeckung beim
Schreiben, Neu-Interpretieren, Jahr in der Datums-Kaskade, Listenzeile, API."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from feral import importer
from feral.db import connect, manual, manual_fields, store_extraction
from feral.db.store import store_interpretations
from feral.extract.types import ContainerExtraction, RawMetadataItem
from feral.interpret import interpret_items, reparse_database
from feral.interpret.reparse import raw_items_for, reinterpret
from feral.messages import UserError
from feral.web import library

UTC = timezone.utc
SONG = "a" * 64
BARE = "b" * 64
IMAGE = "c" * 64


def _tag(frame, text):
    return RawMetadataItem(f"id3v2:{frame}", None, text, None, "utf-8")


def _put(db, tmp_path, h, name, items=(), *, kind="audio", container="mp3", mtime=None):
    path = tmp_path / name
    path.write_bytes(b"x")
    if mtime is not None:
        os.utime(path, (mtime.timestamp(), mtime.timestamp()))
    store_extraction(db, file_hash=h, file_size=1, path=str(path),
                     extraction=ContainerExtraction(container=container, media_kind=kind,
                                                    items=list(items)))
    store_interpretations(db, file_hash=h, interpretations=interpret_items(raw_items_for(db, h)))


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    _put(conn, tmp_path, SONG, "01 regen.mp3", [
        _tag("TIT2", "Regenzeit"), _tag("TPE1", "Alte Band"), _tag("TALB", "Erstes Album"),
        _tag("TRCK", "3/12"), _tag("TYER", "2019"), _tag("TCON", "Rock"),
    ], mtime=datetime(2024, 3, 1, 12, tzinfo=UTC))
    _put(conn, tmp_path, BARE, "song_v3_final.mp3", mtime=datetime(2025, 6, 1, 12, tzinfo=UTC))
    _put(conn, tmp_path, IMAGE, "bild.png", kind="image", container="png")
    yield conn
    conn.close()


def _rows(db, h, field):
    return [(r[0], r[1]) for r in db.execute(
        """SELECT parser, value_text FROM interpreted_metadata
            WHERE file_hash = ? AND field = ? ORDER BY parser, ordinal""", (h, field))]


def _apply(db, hashes, **changes):
    parsed = manual_fields.parse_changes(changes)
    with db:
        touched = manual_fields.set_fields(db, hashes, parsed)
        reinterpret(db, touched, dates="year" in parsed)
    return touched


def _hits(db, expr):
    return [i["file_hash"] for i in library.list_items(db, filter_expr=expr)["items"]]


def _date(db, h):
    return db.execute("SELECT media_date FROM items WHERE file_hash = ?", (h,)).fetchone()[0]


@pytest.mark.parametrize("field, text, values", [
    ("title", "  Neuer   Titel ", ["Neuer Titel"]),
    ("artist", "Anna; Bert ;Anna", ["Anna", "Bert"]),
    ("album", "A; B", ["A; B"]),                 # einwertig: das Semikolon bleibt Text
    ("track", "07", ["7"]), ("year", "1994", ["1994"]), ("genre", "", []),
])
def test_parse_input(field, text, values):
    assert manual_fields.parse_input(field, text) == values


@pytest.mark.parametrize("field, text", [
    ("track", "0"), ("track", "drei"), ("disc", "10000"), ("year", "94"), ("year", "2999"),
    ("title", "x" * 301), ("title", "a\x07b"), ("bpm", "120"),
    ("genre", ";".join(f"g{n}" for n in range(21))),
    ("year", "１９９６"), ("track", "²"), ("track", "0000001"),   # nur ASCII-Ziffern, kurz
])
def test_parse_input_rejects(field, text):
    with pytest.raises(UserError):
        manual_fields.parse_input(field, text)


def test_manual_value_covers_the_tag_and_clearing_restores_it(db):
    assert _rows(db, SONG, "artist") == [("audio", "Alte Band")]
    _apply(db, [SONG], artist="Neue Band; Gast")
    assert _rows(db, SONG, "artist") == [("manual", "Neue Band"), ("manual", "Gast")]
    assert _rows(db, SONG, "album") == [("audio", "Erstes Album")]     # unberührt
    # Lesestellen sehen den geltenden Wert: Grammatik und Volltext.
    assert _hits(db, "artist:gast") == [SONG] and _hits(db, "text:gast") == [SONG]
    assert _hits(db, 'artist:"Alte Band"') == []
    _apply(db, [SONG], artist="")
    assert _rows(db, SONG, "artist") == [("audio", "Alte Band")]
    assert db.execute("SELECT COUNT(*) FROM manual_fields").fetchone()[0] == 0


def test_song_without_tags_gets_fields_and_other_kinds_are_skipped(db):
    assert _apply(db, [BARE, IMAGE, "f" * 64], artist="Wir", album="Demos") == [BARE]
    assert _rows(db, BARE, "album") == [("manual", "Demos")]
    assert db.execute("SELECT COUNT(*) FROM manual_fields WHERE file_hash = ?",
                      (IMAGE,)).fetchone()[0] == 0


def test_reparse_keeps_manual_rows_and_sees_them_as_unchanged(db):
    _apply(db, [SONG, BARE], album="Zweites Album")
    report = reparse_database(db)
    assert report.items_unchanged == report.items_total     # Vergleich NACH der Überdeckung
    assert _rows(db, SONG, "album") == [("manual", "Zweites Album")]
    # BARE hat keine Roh-Metadaten: der Lauf fasst die Zeile nicht an.
    assert _rows(db, BARE, "album") == [("manual", "Zweites Album")]


def test_overlay_is_idempotent(db):
    _apply(db, [SONG], genre="Pop")
    once = manual_fields.overlay(db, SONG, interpret_items(raw_items_for(db, SONG)))
    assert manual_fields.overlay(db, SONG, once) == once
    assert [i.parser for i in once] == ["audio", "manual"]


def test_year_by_hand_sits_at_the_tag_year_without_lower_bound(db):
    importer.set_media_date(db, SONG, datetime(2019, 1, 1, tzinfo=UTC), importer.TAG_YEAR)
    assert _date(db, SONG) == "2019"
    _apply(db, [SONG], year="1994")                # vor min_date (2015): trotzdem gültig
    assert _date(db, SONG) == "1994"
    # Scan und Neu-Interpretieren bringen das Tag-Jahr nicht zurück.
    importer.set_media_date(db, SONG, datetime(2019, 1, 1, tzinfo=UTC), importer.TAG_YEAR)
    reparse_database(db)
    assert _date(db, SONG) == "1994"
    # Ein eingebettetes Datum gewinnt wie gegen das Tag-Jahr.
    importer.set_media_date(db, SONG, datetime(2021, 5, 4, 3, 2, 1, tzinfo=UTC), "metadaten")
    assert _date(db, SONG) == "2021-05-04 03:02:01"
    _apply(db, [SONG], year="")                    # Leeren: zurück zum Tag-Jahr
    assert _date(db, SONG) == "2019"


def test_year_by_hand_loses_to_a_date_by_hand(db):
    manual.set_media_date(db, BARE, "2001-02")
    _apply(db, [BARE], year="1994")
    assert _date(db, BARE) == "2001-02"
    assert manual.set_media_date(db, BARE, "") == "1994"   # Datum geleert: das Jahr gilt


def test_state_for_one_and_many(db):
    _apply(db, [SONG], album="Zweites Album")
    one = manual_fields.state(db, [SONG])
    assert one["album"] == {"value": "Zweites Album", "mixed": False, "manual": True, "source": None}
    assert one["artist"] == {"value": "Alte Band", "mixed": False, "manual": False, "source": None}
    assert one["track"]["value"] == "3"
    both = manual_fields.state(db, [SONG, BARE])
    assert both["album"]["mixed"] and both["album"]["value"] == "" and both["album"]["manual"]
    assert both["disc"] == {"value": "", "mixed": False, "manual": False, "source": None}


def test_list_rows_carry_the_columns(db):
    _apply(db, [SONG], genre="Rock; Pop")
    rows = {i["file_hash"]: i for i in library.list_items(db)["items"]}
    song = rows[SONG]
    assert (song["title"], song["track"], song["year"], song["genre"]) == (
        "Regenzeit", "3", "2019", "Rock; Pop")
    assert "title" not in rows[BARE] and "title" not in rows[IMAGE]


def test_rejecting_a_song_drops_its_fields(db):
    _apply(db, [SONG], album="Zweites Album")
    db.execute("DELETE FROM items WHERE file_hash = ?", (SONG,))
    assert db.execute("SELECT COUNT(*) FROM manual_fields").fetchone()[0] == 0


def _route(app, path):
    return next(r for r in app.routes if getattr(r, "path", None) == path).endpoint


def test_api_sets_inline_and_queues_large_selections(tmp_path):
    from fastapi import HTTPException
    from feral.web import app as app_module

    app = app_module.create_app(tmp_path / "t.sqlite")
    try:
        conn = connect(tmp_path / "t.sqlite")
        _put(conn, tmp_path, SONG, "01 regen.mp3", [_tag("TPE1", "Alte Band")])
        conn.close()
        update, state = _route(app, "/api/fields"), _route(app, "/api/fields/state")
        done = update(app_module.MusicFieldsUpdate(hashes=[SONG], fields={"artist": "Neu"}))
        assert done["updated"] == 1 and done["fields"]["artist"]["manual"]
        assert [(i["file_hash"], i["artist"]) for i in done["items"]] == [(SONG, "Neu")]
        assert state(app_module.MusicFieldsState(hashes=[SONG]))["fields"]["artist"]["value"] == "Neu"
        for bad in ({"year": "94"}, {"bpm": "1"}, {}):
            with pytest.raises(HTTPException):
                update(app_module.MusicFieldsUpdate(hashes=[SONG], fields=bad))
        many = [f"{n:064x}" for n in range(app_module.MUSIC_FIELDS_INLINE + 1)]
        queued = update(app_module.MusicFieldsUpdate(hashes=many, fields={"album": "X"}))
        assert queued == {"queued": True, "count": len(many)}
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


def test_task_sets_fields_in_chunks(db):
    from feral.web.tasks import TASKS

    seen = []
    result = TASKS["music_fields"](
        db, {"hashes": [SONG, BARE], "changes": {"album": ["Sammlung"]}, "rules": None},
        lambda **kw: seen.append(kw), None)
    assert result["summary"]["params"] == {"n": 2}
    assert _rows(db, BARE, "album") == [("manual", "Sammlung")] and seen


# -- Befunde der Release-QA 2026.10.1 --------------------------------------------------


def test_too_many_values_fail_fast():
    """Eine präparierte Liste mit hunderttausenden Werten darf nicht
    quadratisch laufen: die Grenze greift beim 21. Wert."""
    import time
    start = time.perf_counter()
    with pytest.raises(UserError):
        manual_fields.check_values("genre", [f"g{n}" for n in range(300_000)])
    assert time.perf_counter() - start < 1.0


def test_state_counts_only_songs_in_a_mixed_selection(db):
    _apply(db, [SONG, IMAGE], album="Zweites Album")
    both = manual_fields.state(db, [SONG, IMAGE])
    assert both["album"] == {"value": "Zweites Album", "mixed": False, "manual": True, "source": None}
    assert manual_fields.state(db, [IMAGE])["album"]["value"] == ""


def test_year_that_has_not_begun_is_no_date_yet(db):
    future = str(datetime.now(UTC).year + 1)
    importer.set_media_date(db, BARE, datetime(2025, 6, 1, 12, tzinfo=UTC), "dateisystem")
    _apply(db, [BARE], year=future)
    assert _date(db, BARE) != future                   # Angabe ja, Datum noch nicht
    importer.set_media_date(db, BARE, datetime(2025, 6, 1, 12, tzinfo=UTC), "dateisystem")
    reparse_database(db)
    assert _date(db, BARE) != future                   # auch Scan und Reparse nicht


def test_items_by_hash_returns_fresh_rows(db):
    _apply(db, [SONG], title="Neuer Titel")
    (row,) = library.items_by_hash(db, [SONG, "f" * 64])
    assert (row["file_hash"], row["title"], row["artist"]) == (SONG, "Neuer Titel", "Alte Band")


def test_maintenance_lists_manual_as_its_own_parser(db):
    from feral.web import admin

    _apply(db, [SONG], album="Zweites Album")
    by_name = {p["parser"]: p for p in admin.maintenance_stats(db)["parsers"]}
    assert by_name["manual"] == {"parser": "manual", "version": manual_fields.PARSER_VERSION, "items": 1}
