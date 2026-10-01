"""Austausch: Zeitkommentare (#228, ADR 0098) und Musik-Angaben von Hand
(#256, ADR 0101). Export, Prüfung, Vorschau, Import."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException, Request

from feral.db import connect, manual, manual_fields, store_extraction, store_interpretations
from feral.extract.types import ContainerExtraction, RawMetadataItem
from feral.interpret import interpret_items
from feral.interpret.reparse import raw_items_for, reinterpret
from feral.interpret.types import InterpretedField, Interpretation
from feral.messages import UserError
from feral.web import exchange, library

SONG = "a" * 64
WAV = "b" * 64       # dieselbe Suno-Song-ID wie das MP3 auf der anderen Seite
PLAIN = "c" * 64
SUNO = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
T0 = "2026-09-24T10:00:00+00:00"


def _put(db, h, name, suno=None):
    store_extraction(db, file_hash=h, file_size=1, path=f"/lib/{name}",
                     extraction=ContainerExtraction(container="mp3", duration=200.0))
    if suno:
        store_interpretations(db, file_hash=h, interpretations=[Interpretation(
            parser="suno", parser_version=1, fields=(InterpretedField("song_id", suno),))])


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    _put(conn, SONG, "regen.mp3", SUNO)
    _put(conn, PLAIN, "ohne.mp3")
    manual.add_comment(conn, SONG, 12_000, "Einsatz Stimme", now=T0)
    manual.add_comment(conn, SONG, 95_000, "Chorus", now=T0)
    yield conn
    conn.close()


def _other(tmp_path, name="drueben.sqlite"):
    """Die andere Instanz: dieselbe Datei (SONG), eine WAV-Fassung mit gleicher Song-ID."""
    conn = connect(tmp_path / name)
    _put(conn, SONG, "regen_kopie.mp3", SUNO)
    _put(conn, WAV, "regen.wav", SUNO)
    return conn


def _counts(bucket):
    return bucket["items"], bucket["new"], bucket["known"]


# -- Export ---------------------------------------------------------------------------


def test_export_only_items_with_comments(db):
    data = exchange.export_exchange(db, now=T0)
    assert (data["format"], data["version"], data["exported_at"]) == ("fml-exchange", 1, T0)
    (item,) = data["items"]
    assert (item["file_hash"], item["name"], item["duration"], item["suno_ids"]) == (
        SONG, "regen.mp3", 200.0, [SUNO])
    assert [(c["at_ms"], c["text"], c["created_at"]) for c in item["comments"]] == [
        (12_000, "Einsatz Stimme", T0), (95_000, "Chorus", T0)]
    # Scope wie bei den Sammel-Aktionen: Auswahl bzw. Suchergebnis.
    assert exchange.export_exchange(db, hashes=[PLAIN])["items"] == []
    assert len(exchange.export_exchange(db, filter_expr="text:chorus")["items"]) == 1


# -- Rundreise ----------------------------------------------------------------------------


def test_roundtrip_by_hash_is_repeatable_and_labelled(db, tmp_path):
    other = _other(tmp_path)
    items = exchange.parse_exchange(json.loads(json.dumps(exchange.export_exchange(db))))
    preview = exchange.preview_import(other, items)
    assert _counts(preview["by_hash"]) == (1, 2, 0) and preview["missing"] == 0

    assert exchange.apply_import(other, items, source="  Feral   Strawberry ", now=T0)["added"] == 2
    rows = manual.list_comments(other, SONG)
    assert [(c["text"], c["source"], c["created_at"]) for c in rows] == [
        ("Einsatz Stimme", "Feral Strawberry", T0), ("Chorus", "Feral Strawberry", T0)]
    # zweimal derselbe Import ändert nichts; Rückweg verdoppelt nichts
    again = exchange.apply_import(other, items, source="X")
    assert (again["added"], again["known"]) == (0, 2)
    back = exchange.parse_exchange(exchange.export_exchange(other))
    assert exchange.apply_import(db, back, source="Y")["added"] == 0
    # Herkunft auch in der Listenzeile, sofort findbar
    row = library.list_items(other, filter_expr="text:chorus")["items"][0]
    assert {c["source"] for c in row["comments"]} == {"Feral Strawberry"}
    other.close()


def test_song_id_fallback_needs_confirmation(db, tmp_path):
    other = connect(tmp_path / "nur_wav.sqlite")
    _put(other, WAV, "regen.wav", SUNO)
    _put(other, PLAIN, "ohne.mp3")
    data = exchange.export_exchange(db)
    data["items"].append({"file_hash": "d" * 64, "name": "fehlt.mp3", "comments": [
        {"at_ms": 1, "text": "weg"}]})
    items = exchange.parse_exchange(data)

    preview = exchange.preview_import(other, items)
    assert _counts(preview["by_song_id"]) == (1, 2, 0)
    assert preview["song_id_items"] == [{"name": "regen.mp3", "here": ["regen.wav"]}]
    assert (preview["missing"], preview["missing_names"]) == (1, ["fehlt.mp3"])

    skipped = exchange.apply_import(other, items, source="A")
    assert (skipped["added"], skipped["skipped_song_id"], skipped["missing"]) == (0, 1, 1)
    assert exchange.apply_import(other, items, source="A", include_song_id=True)["added"] == 2
    assert len(manual.list_comments(other, WAV)) == 2
    other.close()


# -- Fremde Eingabe --------------------------------------------------------------------


def _file(**item):
    base = {"file_hash": SONG, "comments": [{"at_ms": 0, "text": "x"}]}
    return {"format": "fml-time-comments", "version": 1, "items": [{**base, **item}]}


@pytest.mark.parametrize("data, key", [
    ([], "exchangeWrongFormat"),
    ({"format": "etwas anderes"}, "exchangeWrongFormat"),
    ({"format": "fml-time-comments", "version": 2, "items": []}, "exchangeWrongVersion"),
    ({"format": "fml-time-comments", "version": 1}, "exchangeInvalid"),
    (_file(file_hash="../../etc/passwd"), "exchangeInvalid"),
    (_file(comments=[{"at_ms": -1, "text": "x"}]), "exchangeInvalid"),
    (_file(comments=[{"at_ms": True, "text": "x"}]), "exchangeInvalid"),
    (_file(comments=[{"at_ms": 0, "text": "   "}]), "exchangeInvalid"),
    (_file(comments=[{"at_ms": 0, "text": "x" * 2001}]), "exchangeInvalid"),
    (_file(suno_ids="nope"), "exchangeInvalid"),
])
def test_parse_rejects_broken_files(data, key):
    with pytest.raises(UserError) as exc:
        exchange.parse_exchange(data)
    assert exc.value.message["key"] == key


def test_parse_drops_only_decoration():
    (item,) = exchange.parse_exchange(_file(name=5, suno_ids=["kaputt", SUNO.upper()],
                                           comments=[{"at_ms": 0, "text": " x ",
                                                      "created_at": "<script>"}]))
    assert (item.name, item.suno_ids) == (None, [SUNO])
    assert (item.comments[0].text, item.comments[0].created_at) == ("x", None)


def test_source_is_required():
    with pytest.raises(UserError):
        exchange.clean_source("   ")
    assert exchange.clean_source("x" * 99) == "x" * exchange.MAX_SOURCE


# -- API ---------------------------------------------------------------------------------


def _route(app, path, method):
    return next(r for r in app.routes
                if getattr(r, "path", None) == path and method in r.methods).endpoint


def _request(payload, ctype="application/json"):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return Request({"type": "http", "method": "POST", "headers": [
        (b"content-type", ctype.encode()), (b"content-length", str(len(body)).encode())]},
        receive)


def test_endpoints(tmp_path, db):
    from feral.web.app import ExchangeExportRequest, create_app

    other = _other(tmp_path, "t.sqlite")
    other.close()
    app = create_app(tmp_path / "t.sqlite")
    try:
        data = exchange.export_exchange(db)
        preview = _route(app, "/api/admin/exchange/preview", "POST")
        run = _route(app, "/api/admin/exchange/import", "POST")
        assert asyncio.run(preview(_request({"data": data})))["by_hash"]["new"] == 2
        result = asyncio.run(run(_request({"data": data, "source": "B",
                                           "include_song_id": False})))
        assert result["added"] == 2
        _route_export = _route(app, "/api/exchange/export", "POST")
        out = _route_export(ExchangeExportRequest(hashes=[SONG]))
        assert [c["text"] for c in out["items"][0]["comments"]] == ["Einsatz Stimme", "Chorus"]
        for req, status in ((_request({"data": data}, "text/plain"), 415),
                            (_request(b"{kaputt"), 400),
                            (_request({"data": {"format": "x"}}), 400),
                            (_request({"data": data, "source": " "}), 400)):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(run(req) if status != 415 else preview(req))
            assert exc.value.status_code == status
        huge = b'{"data": "' + b"x" * (exchange.MAX_BYTES + 8192) + b'"}'
        with pytest.raises(HTTPException) as exc:
            asyncio.run(preview(_request(huge)))
        assert exc.value.status_code == 413
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


def test_parse_caps_comments_per_song():
    """Jede Listenzeile trägt die Kommentare ihres Songs: eine fremde Datei
    darf einem Song nicht zehntausende anhängen."""
    many = [{"at_ms": i, "text": "x"} for i in range(exchange.MAX_ITEM_COMMENTS + 1)]
    with pytest.raises(UserError):
        exchange.parse_exchange(_file(comments=many))
    assert len(exchange.parse_exchange(_file(comments=many[:-1]))[0].comments) == exchange.MAX_ITEM_COMMENTS


# -- Musik-Angaben von Hand (ADR 0101) ----------------------------------------------------

TAGGED = "e" * 64    # Song mit Tags in den Roh-Blobs (Interpret „Alte Band")
BARE = "f" * 64      # Song ganz ohne Tags


def _music(tmp_path, name):
    """Eine Instanz mit einem getaggten und einem ungetaggten Song."""
    conn = connect(tmp_path / name)
    for h, file_name, items in (
        (TAGGED, "01 regen.mp3", [RawMetadataItem("id3v2:TPE1", None, "Alte Band", None, "utf-8"),
                                  RawMetadataItem("id3v2:TALB", None, "Erstes Album", None, "utf-8")]),
        (BARE, "demo.mp3", []),
    ):
        store_extraction(conn, file_hash=h, file_size=1, path=f"/lib/{file_name}",
                         extraction=ContainerExtraction(container="mp3", media_kind="audio",
                                                        duration=100.0, items=items))
        store_interpretations(conn, file_hash=h,
                              interpretations=interpret_items(raw_items_for(conn, h)))
    return conn


def _by_hand(conn, h, **changes):
    with conn:
        reinterpret(conn, manual_fields.set_fields(conn, [h], manual_fields.parse_changes(changes)))


def _value(conn, h, field):
    return [(r[0], r[1]) for r in conn.execute(
        """SELECT parser, value_text FROM interpreted_metadata
            WHERE file_hash = ? AND field = ? ORDER BY ordinal""", (h, field))]


def test_export_carries_only_values_by_hand(tmp_path):
    here = _music(tmp_path, "hier.sqlite")
    assert exchange.export_exchange(here)["items"] == []          # Tag-Werte reisen nie
    _by_hand(here, TAGGED, artist="Neue Band; Gast", year="1996")
    manual.add_comment(here, BARE, 5_000, "Einsatz", now=T0)
    both = {i["file_hash"]: i for i in exchange.export_exchange(here)["items"]}
    assert both[TAGGED]["fields"] == {"artist": ["Neue Band", "Gast"], "year": ["1996"]}
    assert "comments" not in both[TAGGED] and "fields" not in both[BARE]
    # Die beiden Häkchen: nur Kommentare bzw. nur Angaben.
    assert [i["file_hash"] for i in exchange.export_exchange(here, fields=False)["items"]] == [BARE]
    only = exchange.export_exchange(here, comments=False)["items"]
    assert [i["file_hash"] for i in only] == [TAGGED] and "comments" not in only[0]
    assert exchange.export_exchange(here, comments=False, fields=False)["items"] == []
    here.close()


def test_fields_roundtrip_new_same_differing(tmp_path):
    here, there = _music(tmp_path, "hier.sqlite"), _music(tmp_path, "dort.sqlite")
    _by_hand(here, TAGGED, artist="Neue Band", album="Zweites Album")
    _by_hand(here, BARE, artist="Wir", year="1996")
    _by_hand(there, BARE, artist="Ihr")              # eigener, anderer Wert von Hand
    items = exchange.parse_exchange(json.loads(json.dumps(exchange.export_exchange(here))))

    preview = exchange.preview_import(there, items)
    assert preview["fields"] == 4
    # Der Tag-Wert „Alte Band" ist keine Abweichung: ihn zu überdecken ist der Zweck.
    assert (preview["by_hash"]["fields_new"], preview["by_hash"]["fields_same"],
            preview["by_hash"]["fields_differing"]) == (3, 0, 1)
    assert preview["differing"] == [{"name": "demo.mp3", "field": "artist", "here": "Ihr",
                                     "file": "Wir", "song_id": False}]

    done = exchange.apply_import(there, items, source="Feral Strawberry", now=T0)
    assert (done["fields_set"], done["fields_same"], done["fields_kept"]) == (3, 0, 1)
    assert _value(there, TAGGED, "artist") == [("manual", "Neue Band")]
    assert _value(there, BARE, "artist") == [("manual", "Ihr")]          # der eigene Wert bleibt
    assert there.execute("SELECT media_date FROM items WHERE file_hash = ?",
                         (BARE,)).fetchone()[0] == "1996"                # Jahr von Hand wird Datum
    state = manual_fields.state(there, [TAGGED])
    assert (state["album"]["manual"], state["album"]["source"]) == (True, "Feral Strawberry")

    # Zweimal derselbe Import ändert nichts; nur auf Ansage gewinnt die Datei.
    again = exchange.apply_import(there, items, source="X")
    assert (again["fields_set"], again["fields_same"], again["fields_kept"]) == (0, 3, 1)
    forced = exchange.apply_import(there, items, source="X", overwrite_fields=True)
    assert (forced["fields_set"], forced["fields_kept"]) == (1, 0)
    assert _value(there, BARE, "artist") == [("manual", "Wir")]
    here.close()
    there.close()


def _new_file(**item):
    return {"format": "fml-exchange", "version": 1, "items": [{"file_hash": SONG, **item}]}


def test_new_format_sections_are_optional_and_legacy_ignores_fields():
    (item,) = exchange.parse_exchange(_new_file(fields={"artist": [" Anna ", "Anna"], "genre": []}))
    assert (item.comments, item.fields) == ([], {"artist": ["Anna"]})
    assert exchange.parse_exchange(_new_file())[0].fields == {}
    (old,) = exchange.parse_exchange(_file(fields={"artist": ["Anna"]}))
    assert old.fields == {}                  # das alte Format kennt nur Kommentare
    with pytest.raises(UserError):           # und dort ist ``comments`` Pflicht
        exchange.parse_exchange({"format": "fml-time-comments", "version": 1,
                                 "items": [{"file_hash": SONG}]})


@pytest.mark.parametrize("fields", [
    "artist", {"artist": "Anna"}, {"artist": [5]}, {"bpm": ["120"]}, {"year": ["96"]},
    {"track": ["0"]}, {"album": ["A", "B"]}, {"title": ["x" * 301]},
    {"genre": [f"g{n}" for n in range(21)]}, {"title": ["a\x07b"]},
])
def test_parse_rejects_broken_fields(fields):
    with pytest.raises(UserError) as exc:
        exchange.parse_exchange(_new_file(fields=fields))
    assert exc.value.message["key"] == "exchangeInvalid"


def test_fields_only_land_on_songs(tmp_path):
    there = connect(tmp_path / "bild.sqlite")
    store_extraction(there, file_hash=SONG, file_size=1, path="/lib/bild.png",
                     extraction=ContainerExtraction(container="png", media_kind="image"))
    items = exchange.parse_exchange(_new_file(fields={"artist": ["Anna"]}))
    assert exchange.preview_import(there, items)["by_hash"]["fields_new"] == 0
    assert exchange.apply_import(there, items, source="X")["fields_set"] == 0
    there.close()
