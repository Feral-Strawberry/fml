"""Audio-Modul in der Bibliothek (ADR 0083, #158): Dauer-Spalte, Medienart
aus den Spuren, typ:/dauer:, Sortierung nach Dauer, Modul-Schalter in
Config und Scan."""

from __future__ import annotations

import pytest

from feral import config as cfg
from feral.db import connect, store_extraction
from feral.extract import video_ffprobe
from feral.extract.types import ContainerExtraction
from feral.scan import scan_directory
from feral.web import filters, library

from . import audiobuild as ab


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    yield conn
    conn.close()


def _put(db, h, container, *, kind=None, duration=None):
    store_extraction(db, file_hash=h, file_size=1, path=f"/{h[:4]}.{container}",
                     extraction=ContainerExtraction(container=container, media_kind=kind,
                                                    duration=duration))


def _seed(db):
    _put(db, "a" * 64, "png")
    _put(db, "b" * 64, "isobmff", duration=30.0)                   # Video
    _put(db, "c" * 64, "isobmff", kind="audio", duration=200.0)    # M4A
    _put(db, "d" * 64, "flac", duration=95.5)
    _put(db, "e" * 64, "mp3")                                      # Dauer unbekannt


def _hashes(db, expr):
    return {i["file_hash"][0] for i in library.list_items(db, filter_expr=expr)["items"]}


def test_store_duration_and_kind_from_tracks(db):
    _seed(db)
    rows = {r[0][0]: (r[1], r[2]) for r in db.execute(
        "SELECT file_hash, media_kind, duration FROM items")}
    assert rows == {"a": ("image", None), "b": ("video", 30.0), "c": ("audio", 200.0),
                    "d": ("audio", 95.5), "e": ("audio", None)}


def test_typ_predicate_and_english_alias(db):
    _seed(db)
    assert _hashes(db, "typ: audio") == {"c", "d", "e"}
    assert _hashes(db, "type: image | video") == {"a", "b"}
    assert _hashes(db, "-typ: audio") == {"a", "b"}
    assert filters.serialize(filters.parse("type: image")) == "typ: bild"
    with pytest.raises(ValueError):
        filters.parse("typ: ton")


def test_dauer_comparisons_ranges_and_time_notation(db):
    _seed(db)
    assert _hashes(db, "dauer: >120") == {"c"}
    assert _hashes(db, "typ: audio dauer: >120") == {"c"}
    assert _hashes(db, "dauer: <=1:36") == {"b", "d"}          # m:ss
    assert _hashes(db, "dauer: 1:00-3:00") == {"d"}
    assert _hashes(db, "duration: <60 | >=200") == {"b", "c"}
    # Negiert: nur Items MIT Dauer (Bilder/Unbekanntes bleiben draußen).
    assert _hashes(db, "-dauer: >120") == {"b", "d"}
    assert filters.serialize(filters.parse("duration: >=90")) == "dauer: >=90"
    for bad in ("dauer: lang", "dauer: >", "dauer: 1:75"):
        with pytest.raises(ValueError):
            filters.parse(bad)


def test_sort_by_duration_both_directions(db):
    _seed(db)
    down = [i["file_hash"][0] for i in library.list_items(db, sort="duration")["items"]]
    up = [i["file_hash"][0] for i in library.list_items(db, sort="duration-auf")["items"]]
    assert down[:3] == ["c", "d", "b"]
    assert up[:3] == ["b", "d", "c"]          # ohne Dauer in beiden Richtungen am Ende
    assert set(down[3:]) == set(up[3:]) == {"a", "e"}
    assert filters.parse("sort: duration")[0].value == "duration"
    assert library.list_items(db, limit=1)["items"][0].keys() >= {"duration"}


def test_config_switch_and_rules():
    assert cfg.audio_enabled({}) is False
    assert cfg.audio_enabled({"audio": {"enabled": True}}) is True
    assert cfg.import_rules({"audio": {"enabled": True}})["audio"] is True


def test_config_write_is_explicit(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("", encoding="utf-8")
    cfg.update_config_file(p, audio_enabled=True)
    assert cfg.audio_enabled(cfg.load_config(p)) is True
    assert "[audio]" in p.read_text(encoding="utf-8")


def test_scan_with_module_off_and_on(db, tmp_path, monkeypatch):
    monkeypatch.setattr(video_ffprobe, "probe", lambda path: (
        {"format": {"duration": "61.2"}, "streams": [{"codec_type": "audio"}]}, None))
    root = tmp_path / "musik"
    root.mkdir()
    (root / "song.mp3").write_bytes(ab.mp3(ab.id3_tag(
        ab.id3_frame("TXXX", ab.txxx("prompt", "{}")))))
    (root / "take.flac").write_bytes(ab.flac([(4, ab.vorbis_comment([b"TITLE=x"]))]))

    off = scan_directory(db, root, rules={"audio": False})
    assert off.skipped_unknown == 2 and off.new_items == 0

    on = scan_directory(db, root, rules={"audio": True})
    assert on.new_items == 2
    rows = db.execute("SELECT container, media_kind, duration FROM items ORDER BY container").fetchall()
    assert [tuple(r) for r in rows] == [("flac", "audio", 61.2), ("mp3", "audio", 61.2)]
    assert db.execute("SELECT COUNT(*) FROM raw_metadata WHERE source = 'id3v2:TXXX' "
                      "AND keyword = 'prompt'").fetchone()[0] == 1


def test_media_kind_facet_rows_context_and_own_group(db):
    """Sidebar-Gruppe „Medienart" (ADR 0084, #172): Zeilen nur für vorhandene
    Arten, Zähler im Kontext, eigene typ:-Chips klammern sich aus."""
    from feral.db import manual

    _put(db, "a" * 64, "png")
    _put(db, "b" * 64, "isobmff", duration=30.0)
    base = library.facets_payload(db)
    assert base["media_kinds"] == [{"typ": "bild", "count": 1}, {"typ": "video", "count": 1}]

    _put(db, "c" * 64, "flac", duration=95.5)
    manual.set_rating(db, "c" * 64, 5)
    base = library.facets_payload(db)
    ctx = library.facets_payload(db, filter_expr="rating>=4", base=base)
    assert ctx["media_kinds"] == [{"typ": "bild", "count": 0}, {"typ": "video", "count": 0},
                                  {"typ": "audio", "count": 1}]
    own = library.facets_payload(db, filter_expr="typ: audio", base=base)
    assert [m["count"] for m in own["media_kinds"]] == [1, 1, 1]
    # Die übrigen Gruppen zählen im typ:-Kontext mit.
    assert {c["container"]: c["count"] for c in own["containers"]}["flac"] == 1
    assert {c["container"]: c["count"] for c in own["containers"]}["png"] == 0
