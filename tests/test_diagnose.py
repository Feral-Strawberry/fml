"""Tests für das Diagnose-Kommando ``python -m feral.diagnose video-codecs``
(Issue #71): Codec-Überblick per ffprobe-Header-Lauf (hier mit Attrappe)
oder aus den Schicht-2-Feldern, ohne die DB zu verändern.
"""

from __future__ import annotations

import argparse
import subprocess

import pytest

from feral import diagnose
from feral.db import connect, store_extraction, store_interpretations
from feral.extract.types import ContainerExtraction, RawMetadataItem
from feral.interpret import interpret_items


def _fact(stream: int, keyword: str, text: str) -> RawMetadataItem:
    return RawMetadataItem(source=f"isobmff:stream{stream}", keyword=keyword,
                           text=text, data=None, encoding="utf-8")


PRORES = [_fact(0, "codec_type", "video"), _fact(0, "codec_name", "prores"),
          _fact(0, "profile", "HQ"), _fact(0, "pix_fmt", "yuv422p10le")]
H264 = [_fact(0, "codec_type", "video"), _fact(0, "codec_name", "h264"),
        _fact(0, "profile", "High"), _fact(0, "pix_fmt", "yuv420p")]


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    yield conn
    conn.close()


def _video(conn, tmp_path, name: str, items, *, size: int = 10, on_disk: bool = True):
    path = tmp_path / name
    if on_disk:
        path.write_bytes(b"\x00" * size)
    extraction = ContainerExtraction(container="isobmff", items=list(items))
    file_hash = name.encode().hex().ljust(64, "0")[:64]
    store_extraction(conn, file_hash=file_hash, file_size=size, path=path, extraction=extraction)
    store_interpretations(conn, file_hash=file_hash, interpretations=interpret_items(list(items)))
    conn.commit()
    return path


def test_parse_size():
    assert diagnose.parse_size("1G") == 1024**3
    assert diagnose.parse_size("500m") == 500 * 1024**2
    assert diagnose.parse_size("2048") == 2048
    assert diagnose.parse_size("1.5GB") == int(1.5 * 1024**3)
    with pytest.raises(argparse.ArgumentTypeError):
        diagnose.parse_size("viel")


def test_report_groups_by_codec_with_example_and_browser_column(db, tmp_path):
    a = _video(db, tmp_path, "a.mov", PRORES, size=4000)
    b = _video(db, tmp_path, "b.mov", PRORES, size=3000)
    c = _video(db, tmp_path, "c.mp4", H264, size=100)
    _video(db, tmp_path, "weg.mov", PRORES, size=5000, on_disk=False)   # kein Fundort

    probed: list[str] = []

    def fake_probe(path: str):
        probed.append(path)
        if path.endswith("c.mp4"):
            return {"codec_name": "h264", "profile": "High", "pix_fmt": "yuv420p"}
        return {"codec_name": "prores", "profile": "HQ", "pix_fmt": "yuv422p10le"}

    report = diagnose.video_codec_report(db, probe=fake_probe)

    assert report.videos_total == 4 and report.probed == 3 and report.missing == 1
    assert sorted(probed) == sorted(str(p) for p in (a, b, c))
    groups = report.sorted_groups()
    assert [(g.codec, g.count, g.browser) for g in groups] == [("prores", 2, "none"), ("h264", 1, "ok")]
    assert groups[0].example == str(a), "größte Datei zuerst geprüft → Beispiel"
    table = report.table()
    assert "prores" in table and "NO" in table and str(a) in table
    assert "without reachable location: 1" in report.summary()


def test_report_respects_min_size_and_collects_ffprobe_errors(db, tmp_path):
    _video(db, tmp_path, "gross.mov", PRORES, size=5000)
    _video(db, tmp_path, "klein.mp4", H264, size=10)

    def failing_probe(path: str):
        raise RuntimeError("Invalid data found")

    report = diagnose.video_codec_report(db, min_size=1000, probe=failing_probe)
    assert report.videos_total == 1 and report.probed == 0
    assert report.failed == [(str(tmp_path / "gross.mov"), "Invalid data found")]


def test_missing_ffprobe_stops_after_first_file(db, tmp_path):
    _video(db, tmp_path, "a.mov", PRORES)
    _video(db, tmp_path, "b.mov", PRORES)
    calls: list[str] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd[-1])
        raise FileNotFoundError("ffprobe")

    report = diagnose.video_codec_report(
        db, probe=lambda p: diagnose.probe_video_stream(p, run=fake_run))
    assert len(calls) == 1 and len(report.failed) == 1
    assert "ffprobe nicht gefunden" in report.failed[0][1]


def test_probe_video_stream_calls_ffprobe_header_only(tmp_path):
    seen: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stderr=b"",
            stdout=b'{"streams":[{"codec_type":"video","codec_name":"hevc","pix_fmt":"yuv420p10le"}]}')

    facts = diagnose.probe_video_stream("/x/clip.mov", run=fake_run)
    assert facts == {"codec_type": "video", "codec_name": "hevc", "pix_fmt": "yuv420p10le"}
    cmd = seen[0]
    assert "-select_streams" in cmd and cmd[cmd.index("-select_streams") + 1] == "v:0"
    assert "-show_format" not in cmd and cmd[-1] == "/x/clip.mov"


def test_report_from_db_uses_layer2_fields_without_ffprobe(db, tmp_path):
    _video(db, tmp_path, "a.mov", PRORES)
    _video(db, tmp_path, "b.mp4", H264)
    _video(db, tmp_path, "alt.mov", [], size=20)   # Bestand vor der Erweiterung: kein Feld

    report = diagnose.video_codec_report_from_db(db)
    by_codec = {g.codec: g for g in report.groups.values()}
    assert by_codec["prores"].count == 1 and by_codec["prores"].browser == "none"
    assert by_codec["h264"].count == 1
    assert any(c.startswith("(unbekannt") for c in by_codec)
    assert report.videos_total == 3


def test_main_prints_table_and_writes_nothing(db, tmp_path, capsys, monkeypatch):
    _video(db, tmp_path, "a.mov", PRORES)
    db.close()
    dbfile = tmp_path / "feral.sqlite"
    before = dbfile.read_bytes()
    monkeypatch.setattr(diagnose, "probe_video_stream",
                        lambda p: {"codec_name": "prores", "profile": "HQ", "pix_fmt": "yuv422p10le"})

    assert diagnose.main(["video-codecs", "--db", str(dbfile), "--quiet"]) == 0
    out = capsys.readouterr().out
    assert "prores" in out and "NO" in out and "videos in the catalog: 1" in out
    assert dbfile.read_bytes() == before, "Diagnose schreibt nichts"

    assert diagnose.main(["video-codecs", "--db", str(dbfile), "--from-db"]) == 0
    assert "prores" in capsys.readouterr().out
