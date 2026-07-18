"""Tests für die Thumbnail-Pipeline (Stufe 2, ADR 0013)."""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest
from PIL import Image

from feral.db import connect, store_extraction
from feral.extract import png
from feral.thumbs import ensure_thumbnail, generate_thumbnail, render_preview, thumb_path

from .pngbuild import build_png, text_chunk
from .psdbuild import build_psd, version_info


def _save_image(path, size=(800, 600), **kwargs):
    Image.new("RGB", size, color=(255, 84, 112)).save(path, **kwargs)


def test_thumb_path_is_sharded(tmp_path):
    p = thumb_path(tmp_path, "abcd" + "0" * 60)
    assert p.parent.name == "ab"
    assert p.name == "abcd" + "0" * 60 + ".jpg"


def test_image_thumbnail_is_bounded_jpeg(tmp_path):
    src = tmp_path / "gross.png"
    _save_image(src, size=(800, 600))
    dest = tmp_path / "t.jpg"

    assert generate_thumbnail(src, dest, media_kind="image", size=320) is True
    with Image.open(dest) as t:
        assert t.format == "JPEG"
        assert max(t.size) <= 320


def test_small_image_is_not_upscaled(tmp_path):
    src = tmp_path / "klein.png"
    _save_image(src, size=(40, 30))
    dest = tmp_path / "t.jpg"

    generate_thumbnail(src, dest, media_kind="image", size=320)
    with Image.open(dest) as t:
        assert t.size == (40, 30)


def test_psd_thumbnail_uses_composite(tmp_path):
    # PSD läuft über Pillows Composite-Lesung mit (ADR 0052).
    src = tmp_path / "bild.psd"
    src.write_bytes(build_psd(width=8, height=8, color=(255, 0, 0)))
    dest = tmp_path / "t.jpg"

    assert generate_thumbnail(src, dest, media_kind="image") is True
    with Image.open(dest) as t:
        r, g, b = t.convert("RGB").getpixel((4, 4))
        assert r > 200 and g < 60 and b < 60


def test_render_preview_tiff_full_size(tmp_path):
    src = tmp_path / "bild.tiff"
    _save_image(src, size=(120, 90))

    data, reason = render_preview(src)
    assert reason == ""
    with Image.open(io.BytesIO(data)) as img:
        assert img.format == "JPEG"
        assert img.size == (120, 90)   # volle Größe, keine Verkleinerung


def test_psd_without_composite_fails_cleanly(tmp_path):
    # ADR 0052: ohne „Maximale Kompatibilität" läse Pillow nur Weiß —
    # ehrlicher Fehlschlag statt weißes Thumbnail.
    src = tmp_path / "ohne.psd"
    src.write_bytes(build_psd(version_info(False), width=8, height=8))
    dest = tmp_path / "t.jpg"

    ok = generate_thumbnail(src, dest, media_kind="image")
    assert ok is False
    assert not dest.exists()

    data, reason = render_preview(src)
    assert data is None
    assert "Composite" in reason


def test_psd_with_composite_flag_still_renders(tmp_path):
    src = tmp_path / "mit.psd"
    src.write_bytes(build_psd(version_info(True), width=8, height=8, color=(0, 0, 255)))

    data, reason = render_preview(src)
    assert reason == ""
    with Image.open(io.BytesIO(data)) as img:
        r, g, b = img.convert("RGB").getpixel((4, 4))
        assert b > 200 and r < 60


def test_render_preview_psd(tmp_path):
    src = tmp_path / "bild.psd"
    src.write_bytes(build_psd(width=6, height=4, color=(0, 255, 0)))

    data, reason = render_preview(src)
    assert reason == ""
    with Image.open(io.BytesIO(data)) as img:
        assert img.size == (6, 4)
        r, g, b = img.convert("RGB").getpixel((3, 2))
        assert g > 200 and r < 60


def test_render_preview_broken_file_returns_reason(tmp_path):
    src = tmp_path / "kaputt.tiff"
    src.write_bytes(b"kein bild")

    data, reason = render_preview(src)
    assert data is None
    assert "Pillow" in reason


def test_animated_webp_uses_first_frame(tmp_path):
    frames = [
        Image.new("RGB", (64, 64), color=c) for c in [(255, 0, 0), (0, 255, 0)]
    ]
    src = tmp_path / "anim.webp"
    frames[0].save(src, "WEBP", save_all=True, append_images=frames[1:], duration=100)
    dest = tmp_path / "t.jpg"

    assert generate_thumbnail(src, dest, media_kind="image") is True
    with Image.open(dest) as t:
        r, g, b = t.convert("RGB").getpixel((32, 32))
        assert r > 200 and g < 60  # erster (roter) Frame, nicht der grüne


def test_corrupt_file_writes_fail_marker(tmp_path):
    src = tmp_path / "kaputt.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\xff" * 16)
    dest = tmp_path / "sub" / "t.jpg"

    assert generate_thumbnail(src, dest, media_kind="image") is False
    assert not dest.exists()
    assert dest.with_suffix(".fail").is_file()


def test_document_kind_has_no_thumbnail(tmp_path):
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF-1.7")
    dest = tmp_path / "t.jpg"
    assert generate_thumbnail(src, dest, media_kind="document") is False


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg nicht installiert")
def test_video_thumbnail_via_ffmpeg(tmp_path):
    # Ein-Frame-Video programmatisch mit ffmpeg selbst erzeugen (kein Blob im Repo).
    import subprocess

    src = tmp_path / "clip.webm"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=64x64:d=0.2",
         str(src)],
        check=True, capture_output=True,
    )
    dest = tmp_path / "t.jpg"

    assert generate_thumbnail(src, dest, media_kind="video") is True
    with Image.open(dest) as t:
        assert t.format == "JPEG" and max(t.size) <= 320


# --- ensure_thumbnail (mit DB) -------------------------------------------------

@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    yield conn
    conn.close()


def _catalog_png(conn, tmp_path, file_hash, name="bild.png"):
    """Echte PNG-Datei anlegen und als Item katalogisieren."""
    path = tmp_path / name
    img_path = tmp_path / ("real_" + name)
    _save_image(img_path)  # echtes PNG mit Pixeln (pngbuild-PNGs haben kein IDAT)
    img_path.rename(path)
    extraction = png.extract(path)
    store_extraction(
        conn, file_hash=file_hash, file_size=path.stat().st_size,
        path=path, extraction=extraction,
    )
    return path


def test_ensure_thumbnail_generates_and_caches(db, tmp_path):
    file_hash = "a" * 64
    _catalog_png(db, tmp_path, file_hash)
    cache = tmp_path / "cache"

    first = ensure_thumbnail(db, file_hash, cache)
    assert first is not None and first.is_file()
    mtime = first.stat().st_mtime_ns

    second = ensure_thumbnail(db, file_hash, cache)
    assert second == first
    assert second.stat().st_mtime_ns == mtime  # Cache-Hit, nicht neu generiert


def test_ensure_thumbnail_unknown_hash(db, tmp_path):
    assert ensure_thumbnail(db, "f" * 64, tmp_path / "cache") is None


def test_ensure_thumbnail_missing_file(db, tmp_path):
    file_hash = "b" * 64
    path = _catalog_png(db, tmp_path, file_hash)
    path.unlink()  # Fundort existiert nicht mehr
    assert ensure_thumbnail(db, file_hash, tmp_path / "cache") is None


def test_ensure_thumbnail_respects_fail_marker(db, tmp_path):
    file_hash = "c" * 64
    path = _catalog_png(db, tmp_path, file_hash)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\xff" * 16)  # Datei kaputt machen
    cache = tmp_path / "cache"

    assert ensure_thumbnail(db, file_hash, cache) is None
    marker = thumb_path(cache, file_hash).with_suffix(".fail")
    assert marker.is_file()
    # Zweiter Aufruf probiert nicht erneut (Marker greift).
    assert ensure_thumbnail(db, file_hash, cache) is None


def test_thumbpool_generates_in_worker_processes(tmp_path):
    """ADR 0020: der Prozess-Pool erzeugt Thumbnails parallel und
    dedupliziert laufende Aufträge je Hash."""
    from feral.thumbs import ThumbPool

    pool = ThumbPool(workers=2)
    try:
        sources = []
        for i in range(3):
            src = tmp_path / f"bild{i}.png"
            _save_image(src, size=(64, 64))
            sources.append(src)
        futures = [
            pool.submit(f"{i:064x}", src, tmp_path / "cache" / f"t{i}.jpg", media_kind="image")
            for i, src in enumerate(sources)
        ]
        # Gleicher Hash nochmal, solange die Future ggf. noch läuft → dieselbe
        # oder eine schon fertige Future, aber nie ein Fehler.
        again = pool.submit("0" * 64, sources[0], tmp_path / "cache" / "t0.jpg", media_kind="image")
        assert all(f.result(timeout=60) is True for f in futures)
        assert again.result(timeout=60) is True
        assert (tmp_path / "cache" / "t1.jpg").is_file()
    finally:
        pool.shutdown()


def test_warm_retries_fail_markers_and_records_issues(tmp_path):
    """Feral Strawberrys LTX2-Fall: .fail-Marker aus der Zeit ohne ffmpeg blockieren für
    immer — „Thumbnails erstellen" versucht sie erneut; dauerhafte Fehler
    landen mit Grund als Scan-Problem, Erfolge quittieren es."""
    import io

    from feral.db import connect, store_extraction
    from feral.extract import png
    from feral.thumbs import thumb_path, warm_thumbnails

    from .pngbuild import build_png, text_chunk

    conn = connect(tmp_path / "t.sqlite")
    cache = tmp_path / "cache"

    # Item A: echtes PNG (Thumb möglich), aber mit altem .fail-Marker
    from PIL import Image

    good = tmp_path / "gut.png"
    Image.new("RGB", (16, 16), (200, 40, 60)).save(good, "PNG")
    extraction = png.extract(io.BytesIO(good.read_bytes()))
    store_extraction(conn, file_hash="aa" * 32, file_size=1, path=good, extraction=extraction)
    marker_a = thumb_path(cache, "aa" * 32).with_suffix(".fail")
    marker_a.parent.mkdir(parents=True)
    marker_a.write_text("ffmpeg nicht gefunden (siehe DEPENDENCIES.md)")

    # Item B: Fundort existiert nicht mehr → dauerhaft kein Thumb möglich
    store_extraction(conn, file_hash="bb" * 32, file_size=1,
                     path=tmp_path / "weg.png", extraction=extraction)

    result = warm_thumbnails(conn, cache, retry_failed=True)   # = Admin-Knopf

    assert result == {"total": 2, "created": 1, "skipped": 0, "failed": 1}
    assert thumb_path(cache, "aa" * 32).is_file()      # Retry hat funktioniert
    assert not marker_a.is_file()
    issues = conn.execute(
        "SELECT path, kind, message, resolved FROM scan_issues"
    ).fetchall()
    assert len(issues) == 1
    assert issues[0]["kind"] == "thumbnail" and issues[0]["resolved"] == 0
    assert "weg.png" in issues[0]["path"]

    # Zweiter Lauf: A wird übersprungen, B bleibt EIN offenes Problem (dedupliziert)
    result2 = warm_thumbnails(conn, cache, retry_failed=True)
    assert result2["skipped"] == 1 and result2["failed"] == 1
    assert conn.execute("SELECT COUNT(*) FROM scan_issues").fetchone()[0] == 1
    conn.close()


def test_warm_auto_leaves_failed_and_acknowledged_alone(tmp_path):
    """Automatik-Lauf (retry_failed=False, ADR-0042-Ergänzung — Feral Strawberrys 2600er:
    jeder Import-/Watch-Schub machte alle quittierten thumbnail-Probleme
    wieder auf): .fail-Marker bleiben liegen, quittierte Probleme bleiben
    quittiert, „kein Fundort" wird gezählt statt protokolliert."""
    import io

    from PIL import Image

    from feral.db import connect, store_extraction
    from feral.extract import png
    from feral.scan import _record_issue
    from feral.thumbs import thumb_path, warm_thumbnails

    conn = connect(tmp_path / "t.sqlite")
    cache = tmp_path / "cache"

    good = tmp_path / "gut.png"
    Image.new("RGB", (16, 16), (200, 40, 60)).save(good, "PNG")
    extraction = png.extract(io.BytesIO(good.read_bytes()))

    # Item A: bekannter Fehlschlag mit Marker + QUITTIERTEM Problem.
    kaputt = tmp_path / "kaputt.png"
    kaputt.write_bytes(b"kein echtes png")
    store_extraction(conn, file_hash="aa" * 32, file_size=1, path=kaputt, extraction=extraction)
    marker_a = thumb_path(cache, "aa" * 32).with_suffix(".fail")
    marker_a.parent.mkdir(parents=True)
    marker_a.write_text("kaputte Datei")
    _record_issue(conn, kaputt, "thumbnail", "kaputte Datei")
    conn.execute("UPDATE scan_issues SET resolved = 1")
    conn.commit()

    # Item B: Fundort weg — Automatik zählt nur, schreibt KEIN Problem.
    store_extraction(conn, file_hash="bb" * 32, file_size=1,
                     path=tmp_path / "weg.png", extraction=extraction)

    # Item C: neu und machbar — die Automatik erzeugt es normal.
    store_extraction(conn, file_hash="cc" * 32, file_size=1, path=good, extraction=extraction)

    result = warm_thumbnails(conn, cache)   # Automatik: retry_failed=False

    assert result == {"total": 3, "created": 1, "skipped": 1, "failed": 1}
    assert marker_a.is_file()                              # Marker blieb liegen
    assert thumb_path(cache, "cc" * 32).is_file()          # Neues entstand trotzdem
    rows = conn.execute("SELECT path, resolved FROM scan_issues").fetchall()
    assert len(rows) == 1                                  # kein weg.png-Problem dazu
    assert rows[0]["resolved"] == 1                        # Quittiert BLIEB quittiert
    conn.close()


def test_warm_with_pool_matches_sequential(tmp_path):
    """Der Warmer über den Prozess-Pool (ADR 0020) liefert dieselben
    Ergebnisse und dieselbe Scan-Problem-Buchführung wie der sequenzielle."""
    import io

    from PIL import Image

    from feral.db import connect, store_extraction
    from feral.extract import png
    from feral.thumbs import ThumbPool, thumb_path, warm_thumbnails

    conn = connect(tmp_path / "t.sqlite")
    cache = tmp_path / "cache"

    good = tmp_path / "gut.png"
    Image.new("RGB", (16, 16), (200, 40, 60)).save(good, "PNG")
    extraction = png.extract(io.BytesIO(good.read_bytes()))
    store_extraction(conn, file_hash="aa" * 32, file_size=1, path=good, extraction=extraction)
    store_extraction(conn, file_hash="bb" * 32, file_size=1,
                     path=tmp_path / "weg.png", extraction=extraction)  # Fundort fehlt
    broken = tmp_path / "kaputt.png"
    broken.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\xff" * 16)
    store_extraction(conn, file_hash="cc" * 32, file_size=1, path=broken, extraction=extraction)

    pool = ThumbPool(workers=2)
    try:
        result = warm_thumbnails(conn, cache, pool=pool, retry_failed=True)
    finally:
        pool.shutdown()

    assert result == {"total": 3, "created": 1, "skipped": 0, "failed": 2}
    assert thumb_path(cache, "aa" * 32).is_file()
    issues = conn.execute(
        "SELECT path, message FROM scan_issues WHERE kind = 'thumbnail' AND resolved = 0"
    ).fetchall()
    assert len(issues) == 2
    by_path = {Path(r["path"]).name: r["message"] for r in issues}
    assert "weg.png" in by_path and "thumbNoLocation" in by_path["weg.png"]
    assert "kaputt.png" in by_path and "Pillow" in by_path["kaputt.png"]
    conn.close()
