"""Tests für den Schreib-Epochen-Cache (ADR 0048).

Die Korrektheitsregel: kein Cache-Treffer ohne aktuelle ``data_version`` —
ein Schreibvorgang IRGENDEINER Verbindung (Engine, CLI) macht den nächsten
Zugriff zu einer Neuberechnung; Cache-Ergebnis == ungecachtes Ergebnis.
Datei-DB statt ``:memory:``: das Sentinel ist eine eigene Verbindung.
"""

from __future__ import annotations

import io

import pytest

from feral.db import connect, store_extraction, store_interpretations
from feral.extract import png
from feral.interpret import interpret_items
from feral.web import library
from feral.web.cache import EpochCache

from .pngbuild import build_png, text_chunk


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "feral.sqlite"


@pytest.fixture
def db(db_path):
    conn = connect(db_path)
    yield conn
    conn.close()


@pytest.fixture
def cache(db_path, db):
    # db zuerst: die DB muss existieren, bevor das Sentinel sie öffnet.
    c = EpochCache(db_path)
    yield c
    c.close()


def _add_item(conn, file_hash, path, when):
    extraction = png.extract(
        io.BytesIO(build_png(text_chunk("parameters", "x\nSteps: 1, Seed: 1")))
    )
    store_extraction(
        conn, file_hash=file_hash, file_size=7, path=path,
        extraction=extraction, now=when,
    )
    store_interpretations(
        conn, file_hash=file_hash, interpretations=interpret_items(extraction.items)
    )


# --- EpochCache-Baustein -------------------------------------------------------


def test_get_computes_once_per_epoch(db, cache):
    calls = []
    for _ in range(3):
        got = cache.get("k", lambda: calls.append(1) or "wert")
    assert got == "wert"
    assert len(calls) == 1


def test_write_by_any_connection_invalidates(db_path, db, cache):
    calls = []
    cache.get("k", lambda: calls.append(1))
    # Schreiber an der Engine vorbei (wie python -m feral.interpret):
    # eigene Verbindung, commit — die Epoche des Sentinels muss kippen.
    other = connect(db_path)
    with other:
        other.execute(
            "INSERT INTO tags (name, created_at) VALUES ('epoche', '2026-01-01')"
        )
    other.close()
    cache.get("k", lambda: calls.append(1))
    cache.get("k", lambda: calls.append(1))
    assert len(calls) == 2  # genau EINE Neuberechnung nach dem Commit


def test_lru_evicts_oldest(db_path, db):
    cache = EpochCache(db_path, maxsize=2)
    try:
        calls = []
        cache.get("a", lambda: calls.append("a"))
        cache.get("b", lambda: calls.append("b"))
        cache.get("c", lambda: calls.append("c"))  # verdrängt a
        cache.get("b", lambda: calls.append("b!"))  # noch da
        cache.get("a", lambda: calls.append("a!"))  # muss neu rechnen
        assert calls == ["a", "b", "c", "a!"]
    finally:
        cache.close()


# --- Trefferlisten-Cache in list_items ------------------------------------------


@pytest.fixture
def filled(db):
    for k in range(6):
        _add_item(db, f"h{k}", f"/m/bild_{k}.png", f"2026-01-0{k + 1}T00:00:00+00:00")
    return db


EXPR = "container: png"


@pytest.mark.parametrize("sort", ["added", "size-auf", "name", "rating", "created-auf"])
def test_cached_equals_uncached_all_sort_bauformen(filled, cache, sort):
    for offset in (0, 2, 5, 99):
        plain = library.list_items(filled, limit=2, offset=offset,
                                   sort=sort, filter_expr=EXPR)
        cached = library.list_items(filled, limit=2, offset=offset,
                                    sort=sort, filter_expr=EXPR, cache=cache)
        assert cached["items"] == plain["items"]
        assert cached["total"] == 6


def test_cached_total_replaces_count_query(filled, cache):
    # total kommt aus der Listenlänge — auch ohne with_total ehrlich.
    out = library.list_items(filled, limit=2, offset=2, filter_expr=EXPR,
                             with_total=False, cache=cache)
    assert out["total"] == 6


def test_write_invalidates_hit_list(filled, cache):
    before = library.list_items(filled, filter_expr=EXPR, cache=cache)
    assert before["total"] == 6
    _add_item(filled, "h9", "/m/bild_9.png", "2026-02-01T00:00:00+00:00")
    after = library.list_items(filled, filter_expr=EXPR, cache=cache)
    assert after["total"] == 7
    assert after["items"][0]["file_hash"] == "h9"  # neueste zuerst


def test_unfiltered_path_bypasses_cache(filled, cache):
    out = library.list_items(filled, cache=cache)
    assert out["total"] == 6
    assert len(cache._entries) == 0  # Index-Spaziergang, nichts gemerkt


def test_item_position_shares_hit_list_with_list_items(filled, cache):
    """item_position (ADR 0060) nutzt DENSELBEN Cache-Schlüssel wie
    list_items — eine Trefferliste für beide, und cached == uncached."""
    plain = library.item_position(filled, "h2", sort="name", filter_expr=EXPR)
    cached = library.item_position(filled, "h2", sort="name", filter_expr=EXPR,
                                   cache=cache)
    assert cached == plain == 2
    assert len(cache._entries) == 1
    library.list_items(filled, sort="name", filter_expr=EXPR, cache=cache)
    assert len(cache._entries) == 1  # kein zweiter Eintrag: identischer Schlüssel


# --- Modell-Basisliste in models_facet -------------------------------------------


def test_models_facet_cached_equals_uncached_and_invalidates(filled, cache):
    filled.execute(
        "INSERT INTO interpreted_metadata (file_hash, parser, parser_version,"
        " ordinal, field, value_text, interpreted_at)"
        " VALUES ('h0', 't', 1, 9, 'model', 'Modell X', '2026-01-01T00:00:00Z')"
    )
    filled.commit()
    plain = library.models_facet(filled)
    cached = library.models_facet(filled, cache=cache)
    assert cached == plain
    assert library.models_facet(filled, cache=cache) == plain  # aus dem Cache

    filled.execute(
        "INSERT INTO interpreted_metadata (file_hash, parser, parser_version,"
        " ordinal, field, value_text, interpreted_at)"
        " VALUES ('h1', 't', 1, 9, 'model', 'Modell Y', '2026-01-02T00:00:00Z')"
    )
    filled.commit()
    fresh = library.models_facet(filled, cache=cache)
    assert {m["model"] for m in fresh["models"]} == {"Modell X", "Modell Y"}


def test_models_facet_context_counts_stay_uncached(filled, cache):
    # Kontext-Zähler (Filter) rechnen weiter je Ausdruck — nur die
    # Basisliste kommt aus dem Cache (ein Eintrag je Sortier-Reihenfolge).
    filled.execute(
        "INSERT INTO interpreted_metadata (file_hash, parser, parser_version,"
        " ordinal, field, value_text, interpreted_at)"
        " VALUES ('h0', 't', 1, 9, 'model', 'Modell X', '2026-01-01T00:00:00Z')"
    )
    filled.commit()
    plain = library.models_facet(filled, filter_expr="container: jpeg")
    cached = library.models_facet(filled, filter_expr="container: jpeg", cache=cache)
    assert cached == plain
    assert cached["models"][0]["count"] == 0  # kein jpeg im Bestand
