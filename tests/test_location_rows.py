"""Fundort-Zeilen und Ordnergruppen der Audioliste (ADR 0108, #295):
Eintragsliste aus Köpfen und Zeilen, Gruppen-Reihenfolge, Zeilenfilter
durch ordner:/fundort:, Position, Cache-Schlüssel."""

from __future__ import annotations

import pytest

from feral.db import connect, store_extraction
from feral.extract.types import ContainerExtraction
from feral.web import filters, library
from feral.web.cache import EpochCache

LIB = "/fml/bestand"
WATCH = "/Volumes/Musik"
AUDIO = (filters.view_predicate("audio"),)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(filters, "library_root_provider", lambda: LIB)
    monkeypatch.setattr(library, "watch_roots_provider", lambda: [WATCH])
    conn = connect(tmp_path / "feral.sqlite")
    yield conn
    conn.close()


def _song(db, h, path, *extra, at="2026-01-01T00:00:00Z"):
    store_extraction(db, file_hash=h * 64, file_size=1, path=path,
                     extraction=ContainerExtraction(container="mp3", media_kind="audio",
                                                    duration=60.0))
    db.execute("UPDATE items SET first_seen_at = ? WHERE file_hash = ?", (at, h * 64))
    for p in extra:
        db.execute("INSERT INTO file_locations(file_hash, path, first_seen_at, last_seen_at)"
                   " VALUES (?, ?, 'x', 'x')", (h * 64, p))
    db.commit()


def _seed(db):
    # Sortierung „added" = neueste zuerst: a, b, c, d
    _song(db, "a", f"{WATCH}/Kiss-Tribute/Demos/a.mp3", f"{LIB}/2026/01/01/a.mp3",
          at="2026-01-04T00:00:00Z")
    _song(db, "b", f"{WATCH}/Kiss-Tribute/b.mp3", at="2026-01-03T00:00:00Z")
    _song(db, "c", "/Backup/alt/c.mp3", f"{WATCH}/Kiss-Tribute Live/c.mp3",
          at="2026-01-02T00:00:00Z")
    _song(db, "d", f"{WATCH}/Kiss-Tribute/Demos/d (Kopie).mp3", at="2026-01-01T00:00:00Z")


def _page(db, rows, expr=None, **kw):
    return library.list_items(db, rows=rows, filter_expr=expr, view_preds=AUDIO, **kw)


def _shape(items):
    """Köpfe als ('#', Anzeigepfad, Zahl), Zeilen als (Song, Dateiname)."""
    out = []
    for it in items:
        if "group" in it:
            g = it["group"]
            out.append(("#", g["kind"], g["path"][g["skip"]:], g["count"]))
        else:
            out.append((it["file_hash"][0], it["name"]))
    return out


def test_fundorte_ungrouped_one_row_per_location_in_hit_order(db):
    _seed(db)
    page = _page(db, "fundorte")
    assert _shape(page["items"]) == [
        ("a", "a.mp3"), ("a", "a.mp3"), ("b", "b.mp3"),
        ("c", "c.mp3"), ("c", "c.mp3"), ("d", "d (Kopie).mp3")]
    # je Song Library vor Quelle vor extern (Fundort-Rangfolge, ADR 0062)
    assert [it["loc"]["kind"] for it in page["items"]] == [
        "library", "watch", "watch", "watch", "extern", "watch"]
    assert page["items"][0]["loc"]["count"] == 2
    assert (page["total"], page["songs"], page["locations"]) == (6, 4, 6)


def test_ordner_groups_library_first_children_after_parent(db):
    _seed(db)
    page = _page(db, "ordner")
    assert _shape(page["items"]) == [
        ("#", "library", LIB, 1), ("a", "a.mp3"),
        # Wurzelname der Quelle bleibt sichtbar; Unterordner direkt unter
        # dem Elternordner, auch vor „Kiss-Tribute Live" (Komponenten-Sortierung).
        ("#", "watch", "Musik/Kiss-Tribute", 1), ("b", "b.mp3"),
        ("#", "watch", "Musik/Kiss-Tribute/Demos", 2), ("a", "a.mp3"), ("d", "d (Kopie).mp3"),
        ("#", "watch", "Musik/Kiss-Tribute Live", 1), ("c", "c.mp3"),
        ("#", "extern", "/Backup/alt", 1), ("c", "c.mp3"),
    ]
    assert (page["total"], page["songs"], page["locations"]) == (11, 4, 6)


def test_single_folder_gets_no_head(db):
    _song(db, "a", f"{LIB}/2026/01/01/a.mp3")
    _song(db, "b", f"{LIB}/2026/01/02/b.mp3")
    page = _page(db, "ordner")
    assert [("group" in it) for it in page["items"]] == [False, False]
    assert (page["total"], page["songs"], page["locations"]) == (2, 2, 2)


def test_group_keeps_chosen_sort_inside(db):
    _seed(db)
    page = _page(db, "ordner", sort="added-auf")
    demos = _shape(page["items"])[4:7]
    assert demos == [("#", "watch", "Musik/Kiss-Tribute/Demos", 2),
                     ("d", "d (Kopie).mp3"), ("a", "a.mp3")]


def test_positive_ordner_and_fundort_chips_filter_rows(db):
    _seed(db)
    shape = _shape(_page(db, "ordner", 'ordner: "/Volumes/Musik/Kiss-Tribute"')["items"])
    assert [s for s in shape if s[0] == "#"] == [
        ("#", "watch", "Musik/Kiss-Tribute", 1), ("#", "watch", "Musik/Kiss-Tribute/Demos", 2)]
    # fundort: library zeigt nur die Library-Zeile, der Song bleibt mit ⧉2 erkennbar
    page = _page(db, "fundorte", "fundort: library")
    assert _shape(page["items"]) == [("a", "a.mp3")]
    assert page["items"][0]["loc"]["count"] == 2
    # Negierte Fundort-Chips wählen weiter Songs, nicht Zeilen
    shape = _shape(_page(db, "fundorte", "-ordner: Demos")["items"])
    assert shape == [("b", "b.mp3"), ("c", "c.mp3"), ("c", "c.mp3")]


def test_position_is_first_row_of_song_and_cache_keeps_modes_apart(db, tmp_path):
    _seed(db)
    cache = EpochCache(tmp_path / "feral.sqlite")
    assert library.item_position(db, "c" * 64, rows="ordner", view_preds=AUDIO,
                                 cache=cache) == 8
    assert library.item_position(db, "c" * 64, rows="fundorte", view_preds=AUDIO,
                                 cache=cache) == 3
    grouped = _page(db, "ordner", cache=cache)
    flat = _page(db, "fundorte", cache=cache)
    assert grouped["total"] == 11 and flat["total"] == 6
    # Seiten sind Ausschnitte der Eintragsliste
    assert _shape(_page(db, "ordner", cache=cache, offset=2, limit=2)["items"]) == \
        _shape(grouped["items"][2:4])


def test_without_rows_list_stays_one_row_per_song(db):
    _seed(db)
    page = library.list_items(db, view_preds=AUDIO)
    assert len(page["items"]) == 4 and "loc" not in page["items"][0]
