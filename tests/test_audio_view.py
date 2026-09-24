"""Audioansicht (ADR 0084/0085, #159): Grundbereich je Ansicht als internes
Prädikat — Galerie ohne Audio, Audioansicht nur Audio; Sidebar-Basis,
„Alle Medien", gespeicherte Suchen und Sammel-Aktion zählen je Ansicht."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from feral.db import connect, store_extraction, store_interpretations
from feral.extract.types import ContainerExtraction
from feral.interpret import Interpretation, InterpretedField
from feral.web import bulk, filters, library

GAL = (filters.view_predicate("galerie"),)
AUD = (filters.view_predicate("audio"),)


def _put(db, h, container, *, kind=None, duration=None, fields=()):
    store_extraction(db, file_hash=h, file_size=1, path=f"/lib/{h[:4]}.{container}",
                     extraction=ContainerExtraction(container=container, media_kind=kind,
                                                    duration=duration))
    if fields:
        store_interpretations(db, file_hash=h, interpretations=[Interpretation(
            parser="test", parser_version=1,
            fields=[InterpretedField(f, v) for f, v in fields])])


def _seed(db):
    _put(db, "a" * 64, "png", fields=[("tool", "comfyui"), ("lora", "detail")])
    _put(db, "b" * 64, "isobmff", duration=30.0)                                  # Video
    _put(db, "c" * 64, "mp3", duration=200.0, fields=[("tool", "suno"), ("lyrics", "la la")])
    _put(db, "d" * 64, "flac", duration=95.0, fields=[("tool", "comfyui")])       # instrumental


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    _seed(conn)
    yield conn
    conn.close()


def _hashes(db, *, view=(), expr=None):
    return [i["file_hash"][0] for i in
            library.list_items(db, filter_expr=expr, view_preds=view)["items"]]


def test_view_predicate_is_internal():
    assert filters.build_where(list(GAL)) == ("i.media_kind IS NOT 'audio'", [])
    assert filters.build_where(list(AUD)) == ("i.media_kind = 'audio'", [])
    with pytest.raises(ValueError):
        filters.view_predicate("liste")
    with pytest.raises(ValueError):          # kein Grammatik-Schlüssel
        filters.parse("view: audio")


def test_grid_base_per_view_plain_and_filtered(db):
    assert sorted(_hashes(db, view=GAL)) == ["a", "b"]
    assert sorted(_hashes(db, view=AUD)) == ["c", "d"]
    assert library.list_items(db, view_preds=AUD)["total"] == 2
    # Chips filtern innerhalb des Grundbereichs; typ: audio in der Galerie ist leer.
    assert _hashes(db, view=AUD, expr="tool: comfyui") == ["d"]
    assert _hashes(db, view=GAL, expr="tool: comfyui") == ["a"]
    assert _hashes(db, view=GAL, expr="typ: audio") == []
    # Ohne Ansicht (Admin, Arena, Altaufrufer): alles wie bisher.
    assert sorted(_hashes(db)) == ["a", "b", "c", "d"]


def test_grundbereich_is_not_a_filter_for_the_hits_cache(db, tmp_path):
    """Ungefiltert bleibt der Index-Spaziergang (kein Materialisieren der
    ganzen Galerie); gefiltert laufen Ansicht + Chips durch den Cache."""
    from feral.web.cache import EpochCache
    cache = EpochCache(tmp_path / "feral.sqlite")
    try:
        library.list_items(db, view_preds=GAL, cache=cache)
        assert not cache._entries
        library.list_items(db, view_preds=AUD, filter_expr="tool: suno", cache=cache)
        assert len(cache._entries) == 1
        assert library.item_position(db, "d" * 64, view_preds=AUD, cache=cache) == 0
        assert library.item_position(db, "a" * 64, view_preds=AUD, cache=cache) is None
    finally:
        cache.close()


def test_count_items_per_view(db):
    assert library.count_items(db, "tool: comfyui") == 2
    assert library.count_items(db, "tool: comfyui", view_preds=GAL) == 1
    assert library.count_items(db, None, view_preds=AUD) == 2


def test_sort_index_keeps_covering_the_view_condition(db):
    """Migration 0026: die Plain-Sortierung läuft auch MIT Grundbedingung
    über ihren Index (kein Sortier-Schritt, keine Tabellen-Probe je Zeile)."""
    plan = " ".join(r[3] for r in db.execute(
        "EXPLAIN QUERY PLAN SELECT i.file_hash FROM items i "
        f"WHERE {filters.VIEWS['galerie']} ORDER BY {library._PLAIN_SORTS['added']}"))
    assert "idx_items_first_seen" in plan and "TEMP B-TREE" not in plan


def test_view_base_lists_only_rows_of_the_view(db):
    base_facets = library.facets_payload(db)
    base_models, base_unknown = library.model_base(db)
    base_ratings = library.ratings_facet(db)
    kw = dict(base_models=base_models, base_unknown=base_unknown,
              base_facets=base_facets, base_ratings=base_ratings)
    gal = library.view_base(db, GAL, **kw)
    aud = library.view_base(db, AUD, **kw)
    assert [m["typ"] for m in gal["facets"]["media_kinds"]] == ["bild", "video"]
    assert {c["container"] for c in gal["facets"]["containers"]} == {"png", "isobmff"}
    assert {c["container"] for c in aud["facets"]["containers"]} == {"mp3", "flac"}
    assert [t["tool"] for t in aud["facets"]["tools"]] == ["comfyui", "suno"]
    assert aud["facets"]["loras"] == [] and gal["facets"]["loras"][0]["lora"] == "detail"
    assert aud["facets"]["lyrics"] == {"mit": 1, "ohne": 1}
    # Gefiltert über der Ansichts-Basis: Zähler im Kontext, Zeilen bleiben.
    side = library.sidebar_payload(
        db, filter_expr="has: lyrics", view_preds=AUD,
        base_models=aud["models"]["models"], base_unknown=aud["models"]["unknown_total"],
        base_facets=aud["facets"], base_ratings=aud["ratings"])
    assert {t["tool"]: t["count"] for t in side["facets"]["tools"]} == {"comfyui": 0, "suno": 1}
    assert side["facets"]["lyrics"] == {"mit": 1, "ohne": 1}     # eigene Gruppe klammert sich aus


def test_has_audio(db, tmp_path):
    assert library.has_audio(db)
    empty = connect(tmp_path / "leer.sqlite")
    try:
        assert not library.has_audio(empty)
    finally:
        empty.close()


def test_bulk_on_search_result_respects_the_view(db):
    summary = bulk.apply_bulk(db, filter_expr="tool: comfyui", rating=3, view_preds=AUD)
    assert summary["matched"] == 1
    rated = {r[0][0] for r in db.execute(
        "SELECT file_hash FROM annotations WHERE rating = 3")}
    assert rated == {"d"}


def _route(app, path):
    return next(r for r in app.routes if getattr(r, "path", None) == path).endpoint


def test_endpoints_take_the_view(tmp_path):
    from feral.web.app import create_app
    from fastapi import HTTPException

    app = create_app(tmp_path / "t.sqlite")
    try:
        conn = connect(tmp_path / "t.sqlite")
        _seed(conn)
        conn.close()
        req = SimpleNamespace(scope={})
        items = _route(app, "/api/items")
        page = items(req, limit=200, offset=0, sort="added", model=None, rating=None,
                     filter=None, dupes=False, total=True, view="audio")
        assert page["total"] == 2
        side = _route(app, "/api/sidebar")(req, filter=None, view="galerie")
        assert side["total"] == 2
        assert [m["typ"] for m in side["facets"]["media_kinds"]] == ["bild", "video"]
        assert _route(app, "/api/sidebar")(req, filter=None, view=None)["total"] is None
        with pytest.raises(HTTPException):
            _route(app, "/api/sidebar")(req, filter=None, view="liste")
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


def test_gallery_without_audio_keeps_the_unfiltered_paths(tmp_path):
    """Kein Audio im Bestand: die Galerie hat keinen Grundbereich — dieselben
    ungefilterten Wege und Basen wie vor der Audioansicht."""
    from feral.web.app import create_app

    app = create_app(tmp_path / "t.sqlite")
    try:
        conn = connect(tmp_path / "t.sqlite")
        _put(conn, "a" * 64, "png")
        conn.close()
        side = _route(app, "/api/sidebar")(SimpleNamespace(scope={}), filter=None,
                                            view="galerie")
        assert side["total"] is None
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


def test_max_duration_is_the_common_time_axis(db, tmp_path):
    """Gemeinsame Zeitachse der Audioliste (ADR 0087): längste Dauer der
    Treffermenge — ungefiltert per Index-Weg, gefiltert über den Cache."""
    assert "max_duration" not in library.list_items(db, view_preds=AUD)
    assert library.list_items(db, view_preds=AUD, with_max_duration=True)["max_duration"] == 200.0
    from feral.web.cache import EpochCache
    cache = EpochCache(tmp_path / "feral.sqlite")
    try:
        got = library.list_items(db, view_preds=AUD, filter_expr="tool: comfyui",
                                 cache=cache, with_max_duration=True)
        assert got["max_duration"] == 95.0 and got["total"] == 1
        none = library.list_items(db, view_preds=AUD, filter_expr="tool: nirgends",
                                  cache=cache, with_max_duration=True)
        assert none["max_duration"] is None and none["total"] == 0
    finally:
        cache.close()
