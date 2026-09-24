"""Abgeleitete Audio-Daten (A4 #161): Lautheit, dreibandige Wellenform,
FLAC-Wiedergabe-Proxy, Vorwärmer und Endpunkte.

Reine Logik ohne ffmpeg; die Integration erzeugt ihre Testtöne mit ffmpeg
selbst (``lavfi``, kein Blob im Repo) und wird ohne ffmpeg übersprungen."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from array import array
from pathlib import Path

import pytest

from feral import audio_analysis as aa
from feral.db import connect, store_extraction
from feral.extract import container

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg nicht installiert")

SUMMARY = """[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -14.2 LUFS
    Threshold: -24.4 LUFS

  Loudness range:
    LRA:         5.3 LU
    Threshold: -34.4 LUFS

  True peak:
    Peak:       -0.1 dBFS
"""


def test_parse_ebur128_summary_and_silence():
    assert aa.parse_ebur128("noise\n" + SUMMARY) == {
        "integrated": -14.2, "lra": 5.3, "true_peak": -0.1}
    silent = SUMMARY.replace("-14.2 LUFS", "-70.0 LUFS").replace("-0.1 dBFS", "-inf dBFS")
    assert aa.parse_ebur128(silent)["true_peak"] is None
    assert aa.parse_ebur128(silent)["integrated"] == -70.0
    assert aa.parse_ebur128("Conversion failed!") is None


def test_buckets_stream_across_chunk_boundaries():
    """Min/Max je Band, egal wie ffmpeg die Bytes zerstückelt."""
    frames = aa._FINE * 3 + 10                  # drei volle + ein angebrochener Bucket
    samples = array("h")
    for i in range(frames):
        samples.extend((i % 100, -(i % 50), 7))   # low, mid, high interleavt
    raw = samples.tobytes() if __import__("sys").byteorder == "little" else None
    if raw is None:
        samples.byteswap()
        raw = samples.tobytes()
    b = aa._Buckets(3)
    for start in range(0, len(raw), 777):         # krumme Stückelung
        b.feed(raw[start:start + 777])
    b.close()
    assert b.frames == frames
    assert len(b.mins[0]) == 4
    assert list(b.maxs[0]) == [99, 99, 99, 9 + (aa._FINE * 3) % 100]
    assert list(b.mins[1])[:3] == [-49, -49, -49]
    assert set(b.maxs[2]) == {7}


def test_reduce_buckets_keeps_extremes():
    mins = array("h", [0, -5, 0, 0, -9, 0])
    maxs = array("h", [1, 1, 8, 1, 1, 3])
    assert aa.reduce_buckets(mins, maxs, 3) == ([-5, 0, -9], [1, 8, 3])
    assert aa.reduce_buckets(mins, maxs, 10) == (list(mins), list(maxs))


def test_needs_proxy():
    assert aa.needs_proxy("aiff", None) and aa.needs_proxy("caf", "pcm_s16le")
    assert aa.needs_proxy("isobmff", "alac") and aa.needs_proxy("isobmff", "ALAC")
    assert not aa.needs_proxy("isobmff", "aac")
    assert not any(aa.needs_proxy(c, None) for c in ("mp3", "flac", "wav", "ogg"))
    # Safari spielt AIFF/ALAC selbst: dann keine Kopie; CAF bleibt.
    safari = frozenset({"aiff", "alac"})
    assert not aa.needs_proxy("aiff", None, safari) and not aa.needs_proxy("isobmff", "alac", safari)
    assert aa.needs_proxy("caf", None, safari)


def test_read_analysis_rejects_old_versions(tmp_path):
    dest = tmp_path / "x.json"
    dest.write_text(json.dumps({"version": aa.ANALYSIS_VERSION, "loudness": {}}))
    assert aa.read_analysis(dest) is not None
    dest.write_text(json.dumps({"version": aa.ANALYSIS_VERSION - 1}))
    assert aa.read_analysis(dest) is None
    dest.write_text("{kaputt")
    assert aa.read_analysis(dest) is None
    assert aa.read_analysis(tmp_path / "fehlt.json") is None


def test_failure_leaves_marker_not_file(tmp_path):
    bad = tmp_path / "kaputt.aiff"
    bad.write_bytes(b"FORM\x00\x00\x00\x04AIFF")
    dest = aa.analysis_path(tmp_path / "cache", "ab" * 32)
    assert aa.generate_analysis(bad, dest) is False
    assert not dest.exists()
    assert aa.fail_reason(dest)
    assert not list(dest.parent.glob("*.tmp*"))


# -- Integration (ffmpeg) -----------------------------------------------------------

def _tone(path: Path, *, codec: str | None = None, fmt: str | None = None) -> Path:
    """Drei Sekunden: Bass, Mitte, Höhe nacheinander — je eine Sekunde."""
    cmd = ["ffmpeg", "-v", "error", "-y",
           "-f", "lavfi", "-i", "sine=f=80:d=1", "-f", "lavfi", "-i", "sine=f=800:d=1",
           "-f", "lavfi", "-i", "sine=f=6000:d=1",
           "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", "-ar", "44100"]
    if codec:
        cmd += ["-c:a", codec]
    if fmt:
        cmd += ["-f", fmt]
    subprocess.run(cmd + [str(path)], check=True)
    return path


@needs_ffmpeg
def test_analyze_separates_bands_and_measures_loudness(tmp_path):
    data, reason = aa.analyze(_tone(tmp_path / "t.aiff"))
    assert reason == "" and data["version"] == aa.ANALYSIS_VERSION
    assert data["duration"] == pytest.approx(3.0, abs=0.05)
    assert data["loudness"]["integrated"] < 0 and data["loudness"]["true_peak"] < 0
    w = data["waveform"]
    assert w["bands"] == ["low", "mid", "high"] and 0 < w["buckets"] <= aa.BUCKETS
    n = w["buckets"]

    def peak(band, third):   # Mitte jedes Drittels (die Nahtstellen klicken)
        mx = w[band]["max"]
        return max(mx[third * n // 3 + n // 12:(third + 1) * n // 3 - n // 12])

    for third, band in enumerate(("low", "mid", "high")):
        others = [b for b in ("low", "mid", "high") if b != band]
        assert all(peak(band, third) > 3 * peak(o, third) for o in others), (band, third)


@needs_ffmpeg
def test_proxy_is_lossless_flac(tmp_path):
    src = _tone(tmp_path / "t.aiff")
    dest = aa.proxy_path(tmp_path / "cache", "cd" * 32)
    assert aa.generate_proxy(src, dest) is True
    assert dest.read_bytes()[:4] == b"fLaC"
    # Verlustfrei: dekodierte Samples identisch.
    pcm = lambda p: subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "s16le", "-"],
                                   capture_output=True, check=True).stdout
    assert pcm(src) == pcm(dest)


def _catalog(db_path: Path, src: Path, *, codec: str | None = None) -> str:
    h = (src.stem.encode().hex() * 64)[:64]
    conn = connect(db_path)
    store_extraction(conn, file_hash=h, file_size=src.stat().st_size, path=src,
                     extraction=container.extract(src, audio_enabled=True))
    if codec:
        conn.execute(
            "INSERT INTO interpreted_metadata(file_hash, parser, parser_version, ordinal, field,"
            " value_text, interpreted_at) VALUES (?, 'audio', 1, 0, 'audio_codec', ?, '')", (h, codec))
    conn.commit()
    conn.close()
    return h


@needs_ffmpeg
def test_warm_audio_creates_missing_and_retries_failed(tmp_path):
    db = tmp_path / "t.sqlite"
    cache = tmp_path / "cache"
    h_aiff = _catalog(db, _tone(tmp_path / "a.aiff"))
    h_flac = _catalog(db, _tone(tmp_path / "b.flac"))
    conn = connect(db)
    try:
        first = aa.warm_audio(conn, cache)
        # Nur Analysen — Kopien entstehen erst beim Abspielen (ADR 0086).
        assert first == {"total": 2, "created": 2, "skipped": 0, "failed": 0}
        assert not aa.proxy_path(cache, h_aiff).exists()
        assert aa.warm_audio(conn, cache)["skipped"] == 2
        # Der Admin-Knopf gibt gescheiterte Kopien für den nächsten Abspielversuch frei.
        marker = aa.fail_marker(aa.proxy_path(cache, h_aiff))
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("ffmpeg fehlte")
        aa.warm_audio(conn, cache, retry_failed=True)
        assert not marker.exists()

        # Fehlschlag: Automatik lässt ihn liegen, der Admin-Knopf versucht neu.
        aa.analysis_path(cache, h_flac).unlink()
        aa.fail_marker(aa.analysis_path(cache, h_flac)).write_text("früher gescheitert")
        assert aa.warm_audio(conn, cache)["created"] == 0
        again = aa.warm_audio(conn, cache, retry_failed=True)
        assert again["created"] == 1 and not aa.fail_marker(aa.analysis_path(cache, h_flac)).exists()
    finally:
        conn.close()


@needs_ffmpeg
def test_warm_audio_records_issue_only_on_retry(tmp_path):
    db = tmp_path / "t.sqlite"
    src = _tone(tmp_path / "c.flac")
    h = _catalog(db, src)
    src.write_bytes(b"fLaC" + b"\x00" * (src.stat().st_size - 4))   # gleiche Größe, kaputter Inhalt
    conn = connect(db)
    try:
        assert aa.warm_audio(conn, tmp_path / "cache")["failed"] == 1
        assert conn.execute("SELECT COUNT(*) FROM scan_issues WHERE kind='audio'").fetchone()[0] == 0
        assert aa.warm_audio(conn, tmp_path / "cache", retry_failed=True)["failed"] == 1
        assert conn.execute("SELECT COUNT(*) FROM scan_issues WHERE kind='audio'").fetchone()[0] == 1
    finally:
        conn.close()
    assert h


# -- Endpunkte ---------------------------------------------------------------------

def _endpoint(app, path):
    return next(r for r in app.routes if getattr(r, "path", None) == path).endpoint


@needs_ffmpeg
def test_analysis_endpoint_202_then_200_and_preview_proxy(tmp_path):
    from fastapi import HTTPException

    from feral.web.app import create_app

    db = tmp_path / "t.sqlite"
    h_aiff = _catalog(db, _tone(tmp_path / "a.aiff"))
    h_m4a = _catalog(db, _tone(tmp_path / "b.m4a", codec="alac"), codec="alac")
    h_flac = _catalog(db, _tone(tmp_path / "c.flac"))
    app = create_app(db, thumb_cache=tmp_path / "thumbs", audio_cache=tmp_path / "audio")
    try:
        analysis = _endpoint(app, "/api/audio/analysis/{file_hash}")
        assert analysis(h_aiff).status_code == 202
        deadline = time.monotonic() + 60
        while (r := analysis(h_aiff)).status_code == 202:
            assert time.monotonic() < deadline, "Analyse wurde nie fertig"
            time.sleep(0.1)
        data = json.loads(r.body)
        assert data["loudness"]["integrated"] < 0 and len(data["waveform"]["low"]["max"]) > 0
        with pytest.raises(HTTPException) as exc:
            analysis("ff" * 32)                       # kein Audio-Item
        assert exc.value.status_code == 404

        preview = _endpoint(app, "/api/preview/{file_hash}")
        # Safari meldet AIFF/ALAC als „kann ich" → Original, keine Kopie.
        assert Path(preview(h_aiff, native="aiff").path) == tmp_path / "a.aiff"
        assert Path(preview(h_m4a, native="alac").path) == tmp_path / "b.m4a"
        assert not (tmp_path / "audio" / h_aiff[:2] / f"{h_aiff}.flac").exists()
        for h in (h_aiff, h_m4a):                     # Chrome: FLAC-Proxy beim ersten Abspielen
            r = preview(h, native=None)
            assert r.media_type == "audio/flac"
            assert Path(r.path).read_bytes()[:4] == b"fLaC"
        r = preview(h_flac, native=None)              # FLAC → Original
        assert r.media_type == "audio/flac" and Path(r.path) == tmp_path / "c.flac"
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


def test_analysis_endpoint_reports_failure(tmp_path):
    from fastapi import HTTPException

    from feral.web.app import create_app

    app = create_app(tmp_path / "t.sqlite", audio_cache=tmp_path / "audio")
    try:
        dest = aa.analysis_path(tmp_path / "audio", "ab" * 32)
        dest.parent.mkdir(parents=True)
        aa.fail_marker(dest).write_text("ffmpeg: kaputt")
        with pytest.raises(HTTPException) as exc:
            _endpoint(app, "/api/audio/analysis/{file_hash}")("ab" * 32)
        assert exc.value.status_code == 404
        assert exc.value.detail["key"] == "errAudioAnalysisFailed"
        # Ohne Modul kein Admin-Knopf.
        with pytest.raises(HTTPException):
            _endpoint(app, "/api/admin/audiowarm")()
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


# -- Eingabe an ffmpeg (#190) ---------------------------------------------------------

def test_media_input_allows_local_files_only():
    from feral.tools import media_input
    args = media_input("-lied.mp3")
    assert args[:3] == ["-protocol_whitelist", "file", "-i"]
    assert args[3] == "file:" + str(Path("-lied.mp3").absolute())   # nie als Option lesbar


@needs_ffmpeg
def test_analyze_file_name_with_leading_dash(tmp_path, monkeypatch):
    # Ein Dateiname wie eine Option: relativ übergeben, ffmpeg liest ihn trotzdem als Datei.
    _tone(tmp_path / "-lied.wav")
    monkeypatch.chdir(tmp_path)
    data, reason = aa.analyze("-lied.wav")
    assert reason == "" and data["duration"] > 2.5
