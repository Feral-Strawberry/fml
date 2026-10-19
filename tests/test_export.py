"""Tests für den Kopie-Export (ADR 0103)."""

from __future__ import annotations

import io
import json
import shutil
from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from feral.db import connect, manual_fields, manual_lyrics, store_extraction
from feral.extract import id3
from feral.extract.types import ContainerExtraction
from feral.hashing import hash_file
from feral.interpret import audio as audio_parser
from feral.web import export, tasks

from .audiobuild import id3_frame, id3_tag, mp3, text_frame


@pytest.fixture
def env(tmp_path):
    source = tmp_path / "quelle"
    target = tmp_path / "export" / "2026-10-09 Paket"
    source.mkdir()
    conn = connect(tmp_path / "feral.sqlite")
    yield conn, source, target
    conn.close()


def _item(conn, path: Path, content: bytes, *, media_date: str | None = None,
          container: str = "png") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    file_hash = hash_file(path)
    store_extraction(conn, file_hash=file_hash, file_size=len(content), path=path,
                     extraction=ContainerExtraction(container=container))
    conn.execute("UPDATE items SET media_date = ? WHERE file_hash = ?", (media_date, file_hash))
    conn.commit()
    return file_hash


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


# -- Paketname und Export-Ordner ---------------------------------------------------


def test_package_name_keeps_only_what_every_filesystem_allows():
    assert export.safe_package_name('  Clip: "Feuer" / Take<2>?  ') == "Clip Feuer Take 2"
    assert export.safe_package_name("..\\..\\weg") == "weg"
    assert export.safe_package_name("Ende. ") == "Ende"
    assert export.safe_package_name(None) == ""
    assert len(export.safe_package_name("x" * 300)) == 80


def test_package_dir_is_export_day_plus_optional_name(tmp_path):
    day = date(2026, 10, 9)
    assert export.package_dir(tmp_path, "", day) == tmp_path / "2026-10-09"
    assert export.package_dir(tmp_path, "Video: A", day) == tmp_path / "2026-10-09 Video A"


def test_root_conflict_in_both_directions(tmp_path):
    lib, watch, cache = tmp_path / "lib", tmp_path / "eingang", tmp_path / "daten" / "cache"
    kw = dict(library_root=str(lib), watch_roots=[str(watch)], cache_dirs=[str(cache)])
    assert export.root_conflict(tmp_path / "export", **kw) is None
    assert export.root_conflict(lib / "export", **kw) == "library"      # in der Library
    assert export.root_conflict(tmp_path, **kw) == "library"            # Library in ihm
    assert export.root_conflict(lib, **kw) == "library"
    assert export.root_conflict(watch / "raus", **kw) == "watch"
    assert export.root_conflict(tmp_path / "daten", **kw) == "cache"
    assert export.root_conflict(str(lib).upper() + "/x", **kw) == "library"   # Groß/Klein egal
    # Namens-Präfix ist kein Ordner-Präfix
    assert export.root_conflict(tmp_path / "lib-export", **kw) is None


# -- Kopieren ----------------------------------------------------------------------


def test_flat_export_copies_bit_identical_and_leaves_the_source(env):
    conn, source, target = env
    a = _item(conn, source / "a.png", b"aaa")
    b = _item(conn, source / "tief" / "b.mp4", b"bbbb", container="isobmff")

    report = export.export_items(conn, [a, b], target=target)

    assert export.counts(report) == {"kopiert": 2, "schon_da": 0, "nicht_erreichbar": 0,
                                     "fehler": 0, "mit_angaben": 0, "ohne_angaben": 0,
                                "erster_fehler": "", "erster_offline": None}
    assert _files(target) == ["a.png", "b.mp4"]
    assert hash_file(target / "a.png") == a and hash_file(target / "b.mp4") == b
    assert (source / "a.png").is_file() and (source / "tief" / "b.mp4").is_file()
    # Am Katalog ändert der Export nichts.
    assert conn.execute("SELECT COUNT(*) FROM file_locations").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM import_log").fetchone()[0] == 0


def test_same_export_twice_makes_no_duplicates(env):
    conn, source, target = env
    a = _item(conn, source / "a.png", b"aaa")
    export.export_items(conn, [a], target=target)

    report = export.export_items(conn, [a], target=target)

    assert report.schon_da == 1 and report.kopiert == 0
    assert _files(target) == ["a.png"]


def test_same_name_other_content_gets_numbered_like_a_file_manager(env):
    conn, source, target = env
    one = _item(conn, source / "eins" / "bild.png", b"eins")
    two = _item(conn, source / "zwei" / "bild.png", b"zwei!")
    three = _item(conn, source / "drei" / "bild.png", b"drei")   # gleiche Größe wie eins

    report = export.export_items(conn, [one, two, three], target=target)

    assert report.kopiert == 3
    assert _files(target) == ["bild (1).png", "bild (2).png", "bild.png"]
    assert hash_file(target / "bild (1).png") == two
    assert hash_file(target / "bild (2).png") == three
    # zweiter Lauf: alle drei werden unter ihren Namen wiedergefunden
    assert export.export_items(conn, [one, two, three], target=target).schon_da == 3
    assert len(_files(target)) == 3


def test_date_layout_follows_the_item_date(env):
    conn, source, target = env
    full = _item(conn, source / "a.png", b"a", media_date="2024-05-01 10:00:00")
    year = _item(conn, source / "b.png", b"bb", media_date="1997")
    none = _item(conn, source / "c.png", b"ccc")

    export.export_items(conn, [full, year, none], target=target, layout="date")

    assert _files(target) == ["1997/b.png", "2024/05/01/a.png", "ohne-datum/c.png"]


def test_unreachable_location_is_counted_not_fatal(env):
    conn, source, target = env
    gone = _item(conn, source / "weg.png", b"weg")
    here = _item(conn, source / "da.png", b"da")
    (source / "weg.png").unlink()

    report = export.export_items(conn, [gone, here], target=target)

    assert report.nicht_erreichbar == 1 and report.kopiert == 1
    assert _files(target) == ["da.png"]
    # das Ergebnis sagt, warum: hier fehlt die Datei
    assert report.erster_offline == {"key": "exportWhyMissing",
                                     "params": {"path": str(source / "weg.png")}}
    part = tasks.export_summary(report, str(target))["params"]["parts"][1]
    assert part["key"] == "sumExportOffline" and part["params"]["first"] == report.erster_offline


def test_unreachable_names_a_foreign_file_at_the_location(env):
    """Größen-Wächter (ADR 0049): liegt am Fundort inzwischen etwas anderes,
    wird nicht kopiert, und das Ergebnis nennt beide Größen."""
    conn, source, target = env
    a = _item(conn, source / "a.png", b"aaa")
    (source / "a.png").write_bytes(b"ganz anders")

    report = export.export_items(conn, [a], target=target)

    assert report.nicht_erreichbar == 1 and _files(target) == []
    assert report.erster_offline == {"key": "exportWhyForeign", "params": {
        "path": str(source / "a.png"), "size": 11, "expected": 3}}


def test_copy_that_does_not_match_the_hash_is_an_error_and_leaves_nothing(env, monkeypatch):
    conn, source, target = env
    a = _item(conn, source / "a.png", b"aaa")
    real = shutil.copy2

    def corrupt(src, dst, **kw):
        real(src, dst, **kw)
        Path(dst).write_bytes(b"xxx")      # gleiche Größe, anderer Inhalt

    monkeypatch.setattr(export.shutil, "copy2", corrupt)

    report = export.export_items(conn, [a], target=target)

    assert report.fehler == 1 and report.kopiert == 0
    assert report.erster_fehler.startswith("a.png: OSError: ")
    assert _files(target) == []
    # das Ergebnis nennt den ersten Fehler, nicht nur die Zahl
    part = tasks.export_summary(report, str(target))["params"]["parts"][-1]
    assert part == {"key": "sumExportErrors",
                    "params": {"n": 1, "first": report.erster_fehler}}


def test_write_protected_source_gives_a_writable_copy(env):
    """Von CD kopierte Dateien sind schreibgeschützt; die Kopie nicht."""
    import os
    import stat

    conn, source, target = env
    a = _item(conn, source / "IMG0001.PCD", b"aaa", container="isobmff")
    os.chmod(source / "IMG0001.PCD", stat.S_IREAD)
    try:
        report = export.export_items(conn, [a], target=target)
        assert report.kopiert == 1
        assert os.access(target / "IMG0001.PCD", os.W_OK)
        assert hash_file(target / "IMG0001.PCD") == a
    finally:
        os.chmod(source / "IMG0001.PCD", stat.S_IREAD | stat.S_IWRITE)


def test_converted_formats_leave_as_png_or_as_original(env, monkeypatch, tmp_path):
    conn, source, target = env
    path = source / "scan.pcd"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (200, 40, 60)).save(path, "BMP")   # Stellvertreter: Pillow liest es
    file_hash = hash_file(path)
    store_extraction(conn, file_hash=file_hash, file_size=path.stat().st_size, path=path,
                     extraction=ContainerExtraction(container="pcd"))
    conn.commit()

    report = export.export_items(conn, [file_hash], target=target)

    assert report.kopiert == 1 and _files(target) == ["scan.png"]
    with Image.open(target / "scan.png") as img:
        assert img.format == "PNG" and img.size == (8, 8)
    # derselbe Export noch einmal: das gerechnete Bild ist schon da
    assert export.export_items(conn, [file_hash], target=target).schon_da == 1
    assert _files(target) == ["scan.png"]

    # liegt das Anzeigebild im Vorschau-Cache, geht genau dieses raus
    cache = tmp_path / "preview"
    cached = export.preview_cache_file(cache, file_hash)
    cached.parent.mkdir(parents=True)
    Image.new("RGB", (4, 4), (1, 2, 3)).save(cached, "PNG")
    other = tmp_path / "aus-cache"
    export.export_items(conn, [file_hash], target=other, preview_cache=cache)
    assert (other / "scan.png").read_bytes() == cached.read_bytes()

    # „Original": die Rohdatei, bitgleich
    raw = tmp_path / "roh"
    export.export_items(conn, [file_hash], target=raw, converted="original")
    assert _files(raw) == ["scan.pcd"] and hash_file(raw / "scan.pcd") == file_hash

    # Quelle weg, gerechnetes Bild noch im Cache: der PNG-Export geht
    # trotzdem, unter dem Namen des letzten Fundorts. Die Rohdatei nicht.
    path.unlink()
    late = tmp_path / "ohne-quelle"
    report = export.export_items(conn, [file_hash], target=late, preview_cache=cache)
    assert report.kopiert == 1 and report.nicht_erreichbar == 0
    assert (late / "scan.png").read_bytes() == cached.read_bytes()
    report = export.export_items(conn, [file_hash], target=late, preview_cache=cache,
                                 converted="original")
    assert report.nicht_erreichbar == 1 and _files(late) == ["scan.png"]
    # ohne Bild im Cache bleibt es bei „nicht erreichbar"
    report = export.export_items(conn, [file_hash], target=tmp_path / "leer")
    assert report.nicht_erreichbar == 1 and report.kopiert == 0


def test_free_space_is_checked_before_the_first_copy(env, monkeypatch):
    conn, source, target = env
    a = _item(conn, source / "a.png", b"a" * 100)
    monkeypatch.setattr(export.shutil, "disk_usage",
                        lambda _p: shutil._ntuple_diskusage(1000, 950, 50))

    with pytest.raises(export.NoSpace) as exc:
        export.export_items(conn, [a], target=target)

    assert (exc.value.need, exc.value.free) == (100, 50)
    assert _files(target) == []


# -- Umfang ------------------------------------------------------------------------


def test_scope_selection_keeps_order_and_drops_unknown(env):
    conn, source, _ = env
    a = _item(conn, source / "a.png", b"a")
    b = _item(conn, source / "b.png", b"bb")
    assert export.scope_hashes(conn, hashes=[b, "f" * 64, a, b]) == [b, a]
    assert sorted(export.scope_hashes(conn, filter_expr="")) == sorted([a, b])
    assert export.plan(conn, [a, b]) == {"count": 2, "bytes": 3, "converted": 0,
                                       "tagged": 0}


# -- Aufgabe -----------------------------------------------------------------------


def _params(source: Path, target: Path, hashes: list[str], **extra):
    return {"hashes": hashes, "root": str(target.parent), "target": str(target), **extra}


def test_task_summary_names_counts_and_folder(env):
    conn, source, target = env
    a = _item(conn, source / "a.png", b"a")
    target.parent.mkdir()

    result = tasks.TASKS["export"](conn, _params(source, target, [a]),
                                   lambda **_kw: None, None)

    summary = result["summary"]
    assert summary["key"] == "sumExport" and summary["params"]["target"] == str(target)
    assert summary["params"]["parts"] == [{"key": "sumExportCopied", "params": {"n": 1}}]


def test_task_pause_continues_with_the_rest_and_the_counts(env):
    conn, source, target = env
    hashes = [_item(conn, source / f"{i}.png", bytes([65 + i]) * (i + 1)) for i in range(3)]
    target.parent.mkdir()
    calls = 0

    def progress(*, report=None, current=None):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise tasks.TaskPaused()

    params = _params(source, target, hashes)
    with pytest.raises(tasks.TaskPaused) as exc:
        tasks.TASKS["export"](conn, params, progress, None)

    rest = exc.value.params
    assert rest["hashes"] == hashes[1:] and rest["target"] == str(target)
    assert rest["done"] == {"kopiert": 1, "schon_da": 0, "nicht_erreichbar": 0,
                            "fehler": 0, "mit_angaben": 0, "ohne_angaben": 0,
                                "erster_fehler": "", "erster_offline": None}
    result = tasks.TASKS["export"](conn, rest, lambda **_kw: None, None)
    assert result["summary"]["params"]["parts"][0] == {"key": "sumExportCopied",
                                                       "params": {"n": 3}}
    assert _files(target) == ["0.png", "1.png", "2.png"]


def test_task_never_recreates_a_missing_export_root(env):
    conn, source, target = env
    a = _item(conn, source / "a.png", b"a")     # target.parent fehlt (Platte ausgehängt)

    result = tasks.TASKS["export"](conn, _params(source, target, [a]),
                                   lambda **_kw: None, None)

    assert result["summary"]["key"] == "sumExportNoRoot"
    assert not target.parent.exists()


# -- Endpunkte ---------------------------------------------------------------------


def test_endpoints_lock_plan_and_queue(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from feral.web import filters
    from feral.web.app import ConfigUpdate, ExportRequest, create_app

    lib, out, source = tmp_path / "lib", tmp_path / "export", tmp_path / "quelle"
    for d in (lib, out):
        d.mkdir()
    cfg = tmp_path / "config.toml"
    # Übersichtsmodus: der Export ist trotzdem erlaubt (ADR 0103 Punkt 4).
    cfg.write_text(f'[library]\nroot = "{lib.as_posix()}"\nverwaltung = false\n',
                   encoding="utf-8")
    db = tmp_path / "daten" / "t.sqlite"
    db.parent.mkdir()
    conn = connect(db)
    a = _item(conn, source / "a.png", b"aaa")
    conn.close()
    app = create_app(db, config_path=cfg)
    try:
        ep = {(r.path, m): r.endpoint for r in app.routes if hasattr(r, "endpoint")
              for m in r.methods}
        state, plan, start = (ep["/api/export", "GET"], ep["/api/export/plan", "POST"],
                              ep["/api/export", "POST"])
        save = ep["/api/admin/config", "POST"]

        # ohne Export-Ordner gesperrt, mit Grund
        assert state() == {"available": False, "root": None,
                           "reason": {"key": "errExportNoRoot"}}
        with pytest.raises(HTTPException) as exc:
            start(ExportRequest(hashes=[a]))
        assert exc.value.status_code == 400 and exc.value.detail == {"key": "errExportNoRoot"}

        # Ordner in der Library wird beim Speichern abgewiesen
        with pytest.raises(HTTPException) as exc:
            save(ConfigUpdate(thumbnail_size=320, export_root=str(lib / "raus")))
        assert exc.value.detail == {"key": "errExportRootLibrary"}
        with pytest.raises(HTTPException) as exc:      # Cache läge im Export-Ordner
            save(ConfigUpdate(thumbnail_size=320, export_root=str(tmp_path / "daten")))
        assert exc.value.detail == {"key": "errExportRootCache"}
        # katalogisierte Originale im Ordner (Übersichtsmodus-Scan, Punkt 4)
        with pytest.raises(HTTPException) as exc:
            save(ConfigUpdate(thumbnail_size=320, export_root=str(source)))
        assert exc.value.detail == {"key": "errExportRootOriginals"}

        save(ConfigUpdate(thumbnail_size=320, export_root=str(out)))
        assert ep["/api/admin/config", "GET"]()["export_root"] == str(out)
        assert state()["available"] is True

        got = plan(ExportRequest(hashes=[a], name="Clip: A"))
        assert (got["count"], got["bytes"], got["converted"]) == (1, 3, 0)
        assert got["free"] > 0
        assert Path(got["target"]).parent == out
        assert Path(got["target"]).name.endswith(" Clip A")

        queued = []
        monkeypatch.setattr(app.state.engine, "enqueue",
                            lambda name, params, label, **kw: queued.append((name, params, label)))
        result = start(ExportRequest(hashes=[a], name="Clip: A", layout="date"))
        assert result["queued"] is True and result["count"] == 1
        name, params, label = queued[0]
        assert name == "export" and params["hashes"] == [a] and params["layout"] == "date"
        assert params["target"] == result["target"] and params["root"] == str(out)
        assert params["library_root"] == lib.as_posix()
        assert label == {"key": "taskExport", "params": {"n": 1}}

        with pytest.raises(HTTPException) as exc:
            start(ExportRequest(hashes=[a], layout="zip"))
        assert exc.value.status_code == 400
        with pytest.raises(HTTPException) as exc:      # Filter ohne Treffer
            start(ExportRequest(filter="tag: gibtsnicht"))
        assert exc.value.detail == {"key": "errExportNothing"}

        # Ordner verschwunden (Platte ausgehängt): gesperrt mit Grund
        out.rmdir()
        assert state()["reason"]["key"] == "errExportRootMissing"
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()
        filters.library_root_provider = lambda: None


# -- Angaben von Hand in die Kopie (ADR 0107) -----------------------------------------

def _song(conn, path: Path, *, container: str = "mp3") -> str:
    # Füll-Frames je Name: gleiche Bytes wären dasselbe Item
    content = (mp3(id3_tag(id3_frame("TIT2", text_frame("Alt"))), frames=len(path.name))
               if container == "mp3" else b"fLaC" + b"\x00" * 64)
    return _item(conn, path, content, container=container)


def _title(path: Path) -> list[str]:
    data = path.read_bytes()
    items = id3.parse_id3v2(data[:id3.id3v2_size(data[:10])], [])
    return [f.value for f in audio_parser.parse(items).fields if f.field == "title"]


def test_plan_counts_songs_with_manual_data(env):
    conn, source, _target = env
    plain = _song(conn, source / "a.mp3")
    named = _song(conn, source / "bb.mp3")
    lyric = _song(conn, source / "ccc.mp3")
    manual_fields.set_fields(conn, [named], {"title": ["Neu"]})
    manual_lyrics.set_lyrics(conn, lyric, [[None, None, "Text"]])
    conn.commit()
    assert export.plan(conn, [plain, named, lyric])["tagged"] == 2


def test_tagged_export_writes_manual_data_and_leaves_the_source(env):
    conn, source, target = env
    song = _song(conn, source / "song.mp3")
    picture = source / "cover.png"
    Image.new("RGB", (2400, 1200), "red").save(picture)
    cover = _item(conn, picture, picture.read_bytes())
    manual_fields.set_fields(conn, [song], {"title": ["Neu"]})
    conn.execute("INSERT INTO covers VALUES (?, ?, '2026', '2026')", (song, cover))
    conn.commit()
    before = (source / "song.mp3").read_bytes()

    report = export.export_items(conn, [song], target=target, tags=True)
    assert (report.kopiert, report.mit_angaben, report.ohne_angaben) == (1, 1, 0)
    copy = target / "song.mp3"
    assert _title(copy) == ["Neu"] and (source / "song.mp3").read_bytes() == before
    data = copy.read_bytes()
    pictures = [json.loads(i.text) for i in id3.parse_id3v2(data[:id3.id3v2_size(data[:10])], [])
                if i.source == "id3v2:APIC"]
    assert len(pictures) == 1 and pictures[0]["mime"] == "image/jpeg"
    start = data.index(b"\xff\xd8")
    with Image.open(io.BytesIO(data[start:start + pictures[0]["size"]])) as img:
        assert img.size == (1200, 600)                       # heruntergerechnet

    # kein „schon da": eine zweite Kopie bekommt den nächsten freien Namen
    export.export_items(conn, [song], target=target, tags=True)
    assert _files(target) == ["song (1).mp3", "song.mp3"]


def test_without_the_checkbox_songs_stay_bit_identical(env):
    conn, source, target = env
    song = _song(conn, source / "song.mp3")
    manual_fields.set_fields(conn, [song], {"title": ["Neu"]})
    conn.commit()
    report = export.export_items(conn, [song], target=target)
    assert report.mit_angaben == 0
    assert hash_file(target / "song.mp3") == song


def test_other_formats_go_out_bit_identical_and_are_counted(env):
    conn, source, target = env
    song = _song(conn, source / "song.flac", container="flac")
    manual_fields.set_fields(conn, [song], {"title": ["Neu"]})
    conn.commit()
    report = export.export_items(conn, [song], target=target, tags=True)
    assert (report.kopiert, report.mit_angaben, report.ohne_angaben) == (1, 0, 1)
    assert hash_file(target / "song.flac") == song
    summary = tasks.export_summary(report, str(target))
    assert {"key": "sumExportUntagged", "params": {"n": 1}} in summary["params"]["parts"]
