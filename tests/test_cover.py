"""Cover eines Songs (Audio A8, #165, ADR 0090): Verweis Song → Bild in der
manuellen Schicht; Songs mit Cover gehören zur Galerie (nur Modul an),
Ablehnen des Bildes nimmt sie per CASCADE wieder heraus; eingebettete
Bilder zählen nicht und werden nur fürs Panel zum Vorschaubild."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from feral.config import update_config_file
from feral.db import connect, manual, store_extraction
from feral.extract.id3 import picture_descriptor
from feral.extract.types import ContainerExtraction, RawMetadataItem
from feral.messages import UserError
from feral.web import filters, library

SONG, TAKE, IMG, IMG2, VID = "5" * 64, "6" * 64, "1" * 64, "2" * 64, "3" * 64
GAL = (filters.view_predicate("galerie"),)
GAL_COVER = (filters.view_predicate("galerie+cover"),)


def _put(db, h, container, kind=None, items=()):
    store_extraction(db, file_hash=h, file_size=1, path=f"/lib/{h[:4]}.{container}",
                     extraction=ContainerExtraction(container=container, media_kind=kind,
                                                    items=list(items)))


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    _put(conn, SONG, "mp3", "audio", items=[RawMetadataItem(
        source="id3v2:APIC", keyword=None, encoding="utf-8", data=None,
        text=picture_descriptor("image/jpeg", 3, "", b"\xff\xd8jpeg"))])
    _put(conn, TAKE, "flac", "audio")
    _put(conn, IMG, "png")
    _put(conn, IMG2, "png")
    _put(conn, VID, "isobmff", "video")
    yield conn
    conn.close()


def _hashes(db, view):
    return sorted(i["file_hash"][0] for i in library.list_items(db, view_preds=view)["items"])


def test_set_replace_remove(db):
    assert manual.cover_of(db, SONG) is None and not library.has_covers(db)
    manual.set_cover(db, SONG, IMG)
    assert manual.annotations_for(db, SONG)["cover"] == IMG and library.has_covers(db)
    manual.set_cover(db, SONG, IMG2)                       # ersetzt, keine zweite Zeile
    assert manual.cover_of(db, SONG) == IMG2
    assert db.execute("SELECT COUNT(*) FROM covers").fetchone()[0] == 1
    assert manual.remove_cover(db, SONG) and not manual.remove_cover(db, SONG)
    assert manual.cover_of(db, SONG) is None


def test_validation(db):
    for song, cover, key in ((IMG, IMG2, "coverNotSong"), (SONG, TAKE, "coverNotImage"),
                             (SONG, VID, "coverNotImage"), (SONG, "9" * 64, "itemUnknown")):
        with pytest.raises(UserError) as exc:
            manual.set_cover(db, song, cover)
        assert str(exc.value).startswith(key)


def test_gallery_takes_songs_with_cover_only(db):
    assert _hashes(db, GAL) == ["1", "2", "3"]
    assert _hashes(db, GAL_COVER) == ["1", "2", "3"]          # noch kein Cover
    manual.set_cover(db, SONG, IMG)
    assert _hashes(db, GAL) == ["1", "2", "3"]                # Modul aus: bleibt ohne Audio
    assert _hashes(db, GAL_COVER) == ["1", "2", "3", "5"]     # der Take ohne Cover nicht
    row = next(i for i in library.list_items(db, view_preds=GAL_COVER)["items"]
               if i["file_hash"] == SONG)
    assert row["cover"] == IMG
    assert "cover" not in library.list_items(db, filter_expr="typ: bild")["items"][0]


def test_rejecting_the_image_or_song_drops_the_cover(db):
    manual.set_cover(db, SONG, IMG)
    with db:
        db.execute("DELETE FROM items WHERE file_hash = ?", (IMG,))   # Ablehnen (ADR 0041)
    assert manual.cover_of(db, SONG) is None and not library.has_covers(db)
    assert _hashes(db, GAL_COVER) == ["2", "3"]
    manual.set_cover(db, SONG, IMG2)
    with db:
        db.execute("DELETE FROM items WHERE file_hash = ?", (SONG,))
    assert db.execute("SELECT COUNT(*) FROM covers").fetchone()[0] == 0


def test_embedded_picture_does_not_count(db):
    assert manual.has_embedded_picture(db, SONG)
    assert not manual.has_embedded_picture(db, TAKE)
    assert library.item_detail(db, SONG)["embedded_picture"] is True
    assert library.item_detail(db, IMG)["embedded_picture"] is False
    assert _hashes(db, GAL_COVER) == ["1", "2", "3"]          # eingebettet ≠ Cover
    # M4A: ffprobe führt das Cover als „Video"-Spur.
    _put(db, "7" * 64, "isobmff", "audio", items=[RawMetadataItem(
        source="isobmff:stream1", keyword="codec_type", text="video", data=None,
        encoding="utf-8")])
    assert manual.has_embedded_picture(db, "7" * 64)


def test_cover_index_keeps_the_sort_index(db):
    """Die Galerie-Bedingung mit Covern prüft SQLite im Sortier-Index
    (``file_hash`` steckt darin) — kein Sortier-Schritt."""
    plan = " ".join(r[3] for r in db.execute(
        "EXPLAIN QUERY PLAN SELECT i.file_hash FROM items i "
        f"WHERE {filters.VIEWS['galerie+cover']} ORDER BY {library._PLAIN_SORTS['added']}"))
    assert "idx_items_first_seen" in plan and "TEMP B-TREE" not in plan


def _route(app, path, method):
    return next(r for r in app.routes
                if getattr(r, "path", None) == path and method in r.methods).endpoint


def test_endpoints_and_module_switch(tmp_path):
    from fastapi import HTTPException

    from feral.web.app import CoverRequest, create_app

    conn = connect(tmp_path / "t.sqlite")
    _put(conn, SONG, "mp3", "audio")
    _put(conn, IMG, "png")
    conn.close()
    cfg = tmp_path / "config.toml"
    cfg.write_text("", encoding="utf-8")
    app = create_app(tmp_path / "t.sqlite", thumb_cache=tmp_path / "thumbs",
                     config_path=cfg)
    items = _route(app, "/api/items", "GET")

    def gallery():
        page = items(SimpleNamespace(scope={}), limit=200, offset=0, sort="added", model=None,
                     rating=None, filter=None, dupes=False, total=True, view="galerie")
        return [i["file_hash"] for i in page["items"]]

    try:
        path = "/api/item/{file_hash}/cover"
        r = _route(app, path, "POST")(SONG, CoverRequest(cover=IMG))
        assert r["manual"]["cover"] == IMG
        for call, status in ((lambda: _route(app, path, "POST")(IMG, CoverRequest(cover=IMG)), 400),
                             (lambda: _route(app, path, "POST")(SONG, CoverRequest(cover=SONG)), 400),
                             (lambda: _route(app, path, "POST")(SONG, CoverRequest(cover="9" * 64)), 404)):
            with pytest.raises(HTTPException) as exc:
                call()
            assert exc.value.status_code == status
        assert gallery() == [IMG]                              # Modul aus: kein Song
        update_config_file(cfg, audio_enabled=True)
        assert sorted(gallery()) == sorted([IMG, SONG])
        assert _route(app, path, "DELETE")(SONG)["manual"]["cover"] is None
        assert gallery() == [IMG]
        # Kein eingebettetes Bild: /api/thumb fragt gar nicht erst (kein Fail-Marker).
        with pytest.raises(HTTPException) as exc:
            _route(app, "/api/thumb/{file_hash}", "GET")(SONG)
        assert exc.value.status_code == 404
        assert not list((tmp_path / "thumbs").rglob("*.fail"))
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


# -- Anzeigebild normaler Musik (#198) ---------------------------------------------

def _artwork(db):
    audio = (filters.view_predicate("audio"),)
    return {i["file_hash"][0]: i.get("artwork", False)
            for i in library.list_items(db, view_preds=audio)["items"]}


def test_embedded_picture_is_artwork_only_without_cover_and_ai_tool(db):
    # Normale Musik mit eingebettetem Bild: Anzeigebild; ohne Bild: keins.
    assert _artwork(db) == {"5": True, "6": False}
    # Mit Cover zeigt die Zeile das Cover, nicht das eingebettete Bild.
    manual.set_cover(db, SONG, IMG)
    assert _artwork(db)["5"] is False
    manual.remove_cover(db, SONG)
    # Erkannter KI-Erzeuger (Suno & Co.): dessen Standardbild bleibt draußen.
    db.execute("INSERT INTO interpreted_metadata(file_hash, parser, parser_version, ordinal,"
               " field, value_text, interpreted_at) VALUES (?, 'suno', 1, 0, 'tool', 'suno', '')",
               (SONG,))
    db.commit()
    assert _artwork(db)["5"] is False
    # Nie in die Galerie: ein Anzeigebild ist kein Cover.
    assert "5" not in _hashes(db, GAL_COVER)
