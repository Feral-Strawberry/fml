"""Tests für das Modul „Ausschnitt" (ADR 0105)."""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from feral.db import connect, store_extraction
from feral.extract.types import ContainerExtraction, RawMetadataItem
from feral.hashing import hash_file
from feral.web import clip, tasks

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None,
                                  reason="ffmpeg nicht installiert")


def _lavfi(dest: Path, *inputs: str, extra: list[str]) -> Path:
    args = ["ffmpeg", "-v", "error", "-y"]
    for source in inputs:
        args += ["-f", "lavfi", "-i", source]
    subprocess.run([*args, *extra, str(dest)], check=True, capture_output=True)
    return dest


def _item(conn, path: Path, *, container: str, raw: list[RawMetadataItem] | None = None) -> str:
    file_hash = hash_file(path)
    store_extraction(conn, file_hash=file_hash, file_size=path.stat().st_size, path=path,
                     extraction=ContainerExtraction(container=container, items=raw or []))
    conn.commit()
    return file_hash


def _probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        check=True, capture_output=True).stdout
    return json.loads(out)


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "feral.sqlite")
    yield connection
    connection.close()


# -- Namen und Aufruf ---------------------------------------------------------------


def test_time_label_shows_tenths_only_when_needed():
    assert clip.time_label(12) == "0m12s"
    assert clip.time_label(65.5) == "1m05.5s"
    assert clip.time_label(3723) == "1h02m03s"
    assert clip.time_label(9.96) == "0m10s"        # rundet auf Zehntel


def test_clip_name_is_source_plus_range_and_mute_for_video_only():
    assert clip.clip_name("song.flac", 12, 22, "audio") == "song 0m12s-0m22s.wav"
    assert clip.clip_name("take.3.webm", 0, 4.5, "av") == "take.3 0m00s-0m04.5s.mp4"
    assert clip.clip_name("take.webm", 0, 4, "video") == "take 0m00s-0m04s mute.mp4"


def test_allowed_outputs_follow_kind_and_sound():
    assert clip.allowed_outputs("audio", True) == ("audio",)
    assert clip.allowed_outputs("video", True) == ("av", "video", "audio")
    assert clip.allowed_outputs("video", False) == ("video",)
    assert clip.allowed_outputs("image", False) == ()


def test_ffmpeg_reads_local_files_only_and_seeks_before_the_input(tmp_path):
    args = clip.ffmpeg_args("ffmpeg", tmp_path / "-in.mp4", tmp_path / "out.part",
                            start=1.25, end=3.5, output="av")
    i = args.index("-i")
    assert args[i - 2:i] == ["-protocol_whitelist", "file"]
    assert args[i + 1].startswith("file:") and args[i + 1].endswith("-in.mp4")
    assert args.index("-ss") < i and args[args.index("-ss") + 1] == "1.250"
    assert args[args.index("-t") + 1] == "2.250"
    assert "libx264" in args and "aac" in args and args[-3:-1] == ["-f", "mp4"]
    assert args[-1] == "file:" + str(tmp_path / "out.part")
    mute = clip.ffmpeg_args("ffmpeg", "a.mp4", "o", start=0, end=1, output="video")
    assert "-an" in mute and "aac" not in mute
    wav = clip.ffmpeg_args("ffmpeg", "a.mp4", "o", start=0, end=1, output="audio")
    assert "pcm_s16le" in wav and "-vn" in wav and wav[-3:-1] == ["-f", "wav"]


def test_encoder_state_names_what_is_missing(monkeypatch):
    class Proc:
        stdout = b" V....D libx264              libx264 H.264\n A....D aac  AAC\n"

    clip._encoder_cache.clear()
    monkeypatch.setattr(clip, "find_binary", lambda name: None)
    assert clip.encoder_state() == "no-ffmpeg"
    monkeypatch.setattr(clip, "find_binary", lambda name: "/x/ffmpeg")
    monkeypatch.setattr(clip.subprocess, "run", lambda *a, **kw: Proc())
    assert clip.encoder_state() == "ok"
    clip._encoder_cache.clear()
    Proc.stdout = b" V....D mpeg4   MPEG-4 part 2\n A....D aac  AAC\n"
    assert clip.encoder_state() == "no-h264"
    clip._encoder_cache.clear()


def test_has_audio_stream_reads_the_raw_facts(conn, tmp_path):
    silent, loud = tmp_path / "a.mp4", tmp_path / "b.mp4"
    silent.write_bytes(b"a")
    loud.write_bytes(b"bb")
    fact = lambda i, kind: RawMetadataItem(  # noqa: E731
        f"isobmff:stream{i}", "codec_type", kind, None, "utf-8")
    a = _item(conn, silent, container="isobmff", raw=[fact(0, "video")])
    b = _item(conn, loud, container="isobmff", raw=[fact(0, "video"), fact(1, "audio")])
    assert clip.has_audio_stream(conn, a) is False
    assert clip.has_audio_stream(conn, b) is True


# -- Schneiden (echtes ffmpeg) ------------------------------------------------------


@needs_ffmpeg
def test_song_clip_is_wav_of_the_marked_length_and_the_source_stays(conn, tmp_path):
    song = _lavfi(tmp_path / "song.flac", "sine=frequency=440:duration=3",
                  extra=["-ar", "22050", "-ac", "1", "-metadata", "title=Geheim"])
    before = song.read_bytes()
    h = _item(conn, song, container="flac")
    target = tmp_path / "export" / "2026-10-11"

    report = clip.export_clip(conn, h, target=target, start=0.5, end=2.0, outputs=["audio"])

    out = target / "song 0m00.5s-0m02s.wav"
    assert report.geschrieben == [str(out)] and not report.fehler
    probe = _probe(out)
    stream = probe["streams"][0]
    assert stream["codec_name"] == "pcm_s16le"
    assert (stream["sample_rate"], stream["channels"]) == ("22050", 1)   # wie die Quelle
    assert float(probe["format"]["duration"]) == pytest.approx(1.5, abs=0.01)
    assert "title" not in {k.lower() for k in probe["format"].get("tags", {})}
    assert song.read_bytes() == before
    assert sorted(p.name for p in target.iterdir()) == [out.name]         # kein .part bleibt

    # Derselbe Ausschnitt noch einmal: schon da, keine zweite Datei.
    again = clip.export_clip(conn, h, target=target, start=0.5, end=2.0, outputs=["audio"])
    assert again.schon_da == [str(out)] and not again.geschrieben
    assert len(list(target.iterdir())) == 1


@needs_ffmpeg
def test_video_clip_writes_one_file_per_output(conn, tmp_path):
    if clip.encoder_state() != "ok":
        pytest.skip("ffmpeg ohne libx264")
    video = _lavfi(tmp_path / "take.mkv", "testsrc=size=65x48:rate=10:duration=2",
                   "sine=frequency=330:duration=2",
                   extra=["-c:v", "mpeg4", "-c:a", "pcm_s16le"])
    h = _item(conn, video, container="matroska")
    target = tmp_path / "export"

    report = clip.export_clip(conn, h, target=target, start=0.5, end=1.5,
                              outputs=["av", "video", "audio"])

    assert not report.fehler, report.erster_fehler
    names = sorted(Path(p).name for p in report.geschrieben)
    assert names == ["take 0m00.5s-0m01.5s mute.mp4", "take 0m00.5s-0m01.5s.mp4",
                     "take 0m00.5s-0m01.5s.wav"]
    kinds = lambda name: sorted(  # noqa: E731
        s["codec_type"] for s in _probe(target / name)["streams"])
    assert kinds("take 0m00.5s-0m01.5s.mp4") == ["audio", "video"]
    assert kinds("take 0m00.5s-0m01.5s mute.mp4") == ["video"]
    av = _probe(target / "take 0m00.5s-0m01.5s.mp4")
    picture = next(s for s in av["streams"] if s["codec_type"] == "video")
    assert picture["codec_name"] == "h264" and picture["pix_fmt"] == "yuv420p"
    assert (picture["width"], picture["height"]) == (64, 48)    # ungerade Kante: eine Zeile weg
    assert float(av["format"]["duration"]) == pytest.approx(1.0, abs=0.15)


@needs_ffmpeg
def test_one_failing_output_does_not_stop_the_others(conn, tmp_path):
    song = _lavfi(tmp_path / "song.wav", "sine=frequency=440:duration=1", extra=[])
    h = _item(conn, song, container="wav")

    report = clip.export_clip(conn, h, target=tmp_path / "export", start=0, end=0.5,
                              outputs=["video", "audio"])      # ein Song hat kein Bild

    assert report.fehler == 1 and "mute.mp4" in report.erster_fehler
    assert [Path(p).name for p in report.geschrieben] == ["song 0m00s-0m00.5s.wav"]
    assert [p.name for p in (tmp_path / "export").iterdir()] == ["song 0m00s-0m00.5s.wav"]


def test_unreachable_source_is_reported_not_raised(conn, tmp_path):
    song = tmp_path / "song.wav"
    song.write_bytes(b"x")
    h = _item(conn, song, container="wav")
    song.unlink()
    assert clip.export_clip(conn, h, target=tmp_path / "export", start=0, end=1,
                            outputs=["audio"]) is None
    assert not (tmp_path / "export").exists()


# -- Aufgabe ------------------------------------------------------------------------


def _params(root: Path, file_hash: str, **extra):
    return {"hash": file_hash, "name": "song.wav", "root": str(root),
            "target": str(root / "2026-10-11"), "start": 0, "end": 1,
            "outputs": ["audio"], "token": "t-1", **extra}


def test_task_summary_carries_token_and_files(conn, tmp_path, monkeypatch):
    root = tmp_path / "export"
    root.mkdir()
    out = root / "2026-10-11" / "song 0m00s-0m01s.wav"
    monkeypatch.setattr(clip, "export_clip", lambda *a, **kw: clip.ClipReport(
        geschrieben=[str(out)], fehler=1, erster_fehler="x mute.mp4: boom"))

    result = tasks.TASKS["clip"](conn, _params(root, "a" * 64), lambda **_kw: None, None)

    summary = result["summary"]
    assert summary["key"] == "sumClip"
    assert summary["params"]["token"] == "t-1" and summary["params"]["files"] == [str(out)]
    assert summary["params"]["parts"] == [
        {"key": "sumClipWritten", "params": {"n": 1}},
        {"key": "sumExportErrors", "params": {"n": 1, "first": "x mute.mp4: boom"}}]


def test_task_never_recreates_a_missing_export_root_and_names_offline(conn, tmp_path, monkeypatch):
    root = tmp_path / "export"            # fehlt (Platte ausgehängt)
    result = tasks.TASKS["clip"](conn, _params(root, "a" * 64), lambda **_kw: None, None)
    assert result["summary"]["key"] == "sumExportNoRoot"
    assert result["summary"]["params"]["token"] == "t-1" and not root.exists()

    root.mkdir()
    monkeypatch.setattr(clip, "export_clip", lambda *a, **kw: None)
    result = tasks.TASKS["clip"](conn, _params(root, "a" * 64), lambda **_kw: None, None)
    assert result["summary"] == {"key": "sumClipOffline",
                                 "params": {"name": "song.wav", "token": "t-1"}}


def test_clip_task_is_not_resumable():
    # Mittendrin anhalten hieße: beim Fortsetzen doppelt kodieren.
    assert "clip" in tasks.TASKS and "clip" not in tasks.RESUMABLE


# -- Endpunkte ----------------------------------------------------------------------


def test_endpoints_gate_validate_and_queue_with_priority(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from feral.web import filters
    from feral.web.app import ClipRequest, ConfigUpdate, RevealPathRequest, create_app

    out, source = tmp_path / "export", tmp_path / "quelle"
    out.mkdir()
    source.mkdir()
    cfg = tmp_path / "config.toml"
    cfg.write_text("[library]\nverwaltung = false\n", encoding="utf-8")
    db = tmp_path / "daten" / "t.sqlite"
    db.parent.mkdir()
    conn = connect(db)
    (source / "song.wav").write_bytes(b"song")
    (source / "bild.png").write_bytes(b"bild")
    (source / "stumm.mp4").write_bytes(b"stumm")
    song = _item(conn, source / "song.wav", container="wav")
    image = _item(conn, source / "bild.png", container="png")
    silent = _item(conn, source / "stumm.mp4", container="isobmff")
    conn.execute("UPDATE items SET media_kind = 'audio', duration = 30 WHERE file_hash = ?",
                 (song,))
    conn.execute("UPDATE items SET media_kind = 'video', duration = 8 WHERE file_hash = ?",
                 (silent,))
    conn.commit()
    conn.close()
    monkeypatch.setattr(clip, "encoder_state", lambda: "no-h264")
    app = create_app(db, config_path=cfg)
    try:
        ep = {(r.path, m): r.endpoint for r in app.routes if hasattr(r, "endpoint")
              for m in r.methods}
        state, start = ep["/api/clip/{file_hash}", "GET"], ep["/api/clip/{file_hash}", "POST"]
        save, reveal = ep["/api/admin/config", "POST"], ep["/api/export/reveal", "POST"]
        ok = ClipRequest(start=12, end=22, outputs=["audio"], token="abc")

        # Modul aus: keine Auskunft, kein Lauf
        with pytest.raises(HTTPException) as exc:
            state(song)
        assert exc.value.status_code == 404 and exc.value.detail == {"key": "errClipOff"}

        save(ConfigUpdate(thumbnail_size=320, clip_enabled=True))
        got = ep["/api/admin/config", "GET"]()
        assert got["clip_enabled"] is True and got["clip_encoder"] == "no-h264"

        # ohne Export-Ordner gesperrt, mit Grund
        got = state(song)
        assert got["available"] is False and got["reason"] == {"key": "errExportNoRoot"}
        with pytest.raises(HTTPException) as exc:
            start(song, ok)
        assert exc.value.detail == {"key": "errExportNoRoot"}

        save(ConfigUpdate(thumbnail_size=320, export_root=str(out)))
        got = state(song)
        assert got["available"] is True and got["outputs"] == ["audio"]
        assert (got["kind"], got["duration"], got["name"]) == ("audio", 30, "song.wav")
        assert Path(got["target"]).parent == out
        assert state(silent)["outputs"] == ["video"]         # keine Tonspur
        with pytest.raises(HTTPException) as exc:            # Bilder haben keinen Ausschnitt
            state(image)
        assert exc.value.detail == {"key": "errClipKind"}

        queued = []
        monkeypatch.setattr(app.state.engine, "enqueue",
                            lambda name, params, label, **kw: queued.append(
                                (name, params, label, kw)))
        result = start(song, ok)
        assert result["queued"] is True and result["files"] == ["song 0m12s-0m22s.wav"]
        name, params, label, kw = queued[0]
        assert name == "clip" and kw == {"priority": True}
        assert (params["hash"], params["start"], params["end"]) == (song, 12, 22)
        assert params["outputs"] == ["audio"] and params["token"] == "abc"
        assert params["root"] == str(out) and params["target"] == result["target"]
        assert label == {"key": "taskClip", "params": {"name": "song.wav"}}

        def refused(file_hash, **change):
            with pytest.raises(HTTPException) as exc:
                start(file_hash, ok.model_copy(update=change))
            assert exc.value.status_code == 400
            return exc.value.detail["key"]

        assert refused(song, end=31) == "errClipRange"       # über das Ende hinaus
        assert refused(song, start=22, end=12) == "errClipRange"
        assert refused(song, end=12.05) == "errClipRange"    # kürzer als 0,1 s
        assert refused(song, end=float("inf")) == "errClipRange"   # JSON erlaubt Infinity
        assert refused(song, start=float("nan")) == "errClipRange"
        assert refused(song, outputs=["av"]) == "errClipOutputs"
        assert refused(song, outputs=[]) == "errClipOutputs"
        assert refused(song, token="a b") == "errNoAction"
        assert refused(silent, start=0, end=2, outputs=["video"]) == "errClipNoH264"
        assert len(queued) == 1
        # ohne bekannte Dauer kein Ausschnitt (die Oberfläche sperrt dann auch)
        with sqlite3.connect(db) as raw:
            raw.execute("UPDATE items SET duration = NULL WHERE file_hash = ?", (song,))
        assert refused(song) == "errClipRange"
        assert len(queued) == 1

        # Quelle weg: gesperrt mit Grund
        (source / "song.wav").unlink()
        assert state(song)["reason"] == {"key": "errNoLocation"}

        # Zeigen nur IM Export-Ordner
        inside = out / "2026-10-11" / "song.wav"
        inside.parent.mkdir()
        inside.write_bytes(b"x")
        shown = []
        monkeypatch.setattr("feral.web.app.reveal.show_in_file_manager",
                            lambda path: (shown.append(path), (True, "test"))[1])
        assert reveal(RevealPathRequest(path=str(inside)))["selected"] is True
        assert shown == [inside]
        for foreign in (source / "bild.png", out / ".." / "quelle" / "bild.png",
                        out / "2026-10-11" / "fehlt.wav"):
            with pytest.raises(HTTPException) as exc:
                reveal(RevealPathRequest(path=str(foreign)))
            assert exc.value.status_code == 404
        assert len(shown) == 1
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()
        filters.library_root_provider = lambda: None
