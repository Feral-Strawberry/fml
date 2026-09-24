"""Tests für den ffprobe-Video-Extraktor (Schicht 1, ADR 0008).

Die JSON→Roh-Einträge-Abbildung wird rein getestet (bekanntes JSON → erwartete
Einträge); der echte ffprobe-Aufruf wird nur auf sein Fehlverhalten geprüft
(fehlendes Binary darf nicht werfen) bzw. läuft als Integrationstest, wenn
ffprobe installiert ist.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from feral.extract import video_ffprobe

FFPROBE_JSON = {
    "format": {
        "filename": "clip.webm",
        "tags": {"ENCODER": "Lavf60.3.100", "COMMENT": "made with comfyui"},
    },
    "streams": [
        {"index": 0, "codec_type": "video", "tags": {"DURATION": "00:00:05.000"}},
        {"index": 1, "codec_type": "audio"},  # ohne Tags
    ],
}

# Topaz-Export als ProRes im MOV (Issue #71): Ton vorn, Video als Stream 1.
PRORES_JSON = {
    "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
    "streams": [
        {"index": 0, "codec_type": "audio", "codec_name": "aac", "profile": "LC",
         "bit_rate": "128000", "tags": {"language": "und"}},
        {"index": 1, "codec_type": "video", "codec_name": "prores",
         "codec_tag_string": "apch", "profile": "HQ", "pix_fmt": "yuv422p10le",
         "width": 3840, "height": 2160, "bit_rate": "734003200",
         "avg_frame_rate": "24000/1001", "tags": {"encoder": "Apple ProRes 422 HQ"}},
    ],
}


def test_items_from_ffprobe_maps_format_and_stream_tags():
    items = video_ffprobe.items_from_ffprobe(FFPROBE_JSON, container="matroska")

    by_source_keyword = {(i.source, i.keyword): i.text for i in items}
    assert by_source_keyword[("matroska:format.tag", "COMMENT")] == "made with comfyui"
    assert by_source_keyword[("matroska:format.tag", "ENCODER")] == "Lavf60.3.100"
    assert by_source_keyword[("matroska:stream0.tag", "DURATION")] == "00:00:05.000"
    # Stream-Eckwerte (#71): nur die vorhandenen Felder, hier je einmal codec_type.
    assert by_source_keyword[("matroska:stream0", "codec_type")] == "video"
    assert by_source_keyword[("matroska:stream1", "codec_type")] == "audio"
    assert len(items) == 5  # 2 Format-Tags + 1 Stream-Tag + 2× codec_type


def test_stream_facts_are_stored_verbatim_per_stream():
    items = video_ffprobe.items_from_ffprobe(PRORES_JSON, container="isobmff")
    video = {i.keyword: i.text for i in items if i.source == "isobmff:stream1"}
    assert video == {
        "codec_type": "video", "codec_name": "prores", "codec_tag_string": "apch",
        "profile": "HQ", "pix_fmt": "yuv422p10le", "width": "3840", "height": "2160",
        "bit_rate": "734003200",
    }
    audio = {i.keyword: i.text for i in items if i.source == "isobmff:stream0"}
    assert audio == {"codec_type": "audio", "codec_name": "aac", "profile": "LC", "bit_rate": "128000"}
    # Tags bleiben unter ihrem eigenen Label, unverändert.
    assert {(i.source, i.keyword) for i in items if i.source.endswith(".tag")} == {
        ("isobmff:stream0.tag", "language"), ("isobmff:stream1.tag", "encoder"),
    }
    # Eckwerte stehen VOR den Tags desselben Streams (deterministischer Blob).
    sources = [i.source for i in items]
    assert sources.index("isobmff:stream1") < sources.index("isobmff:stream1.tag")


def test_video_stream_facts_picks_first_video_stream():
    facts = video_ffprobe.video_stream_facts(PRORES_JSON)
    assert facts["codec_name"] == "prores" and facts["pix_fmt"] == "yuv422p10le"
    assert video_ffprobe.video_stream_facts({"streams": [{"codec_type": "audio"}]}) is None
    assert video_ffprobe.video_stream_facts({}) is None


def test_items_from_ffprobe_empty_json():
    assert video_ffprobe.items_from_ffprobe({}, container="isobmff") == []


def test_missing_ffprobe_warns_instead_of_raising(tmp_path, monkeypatch):
    def raise_not_found(*args, **kwargs):
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr(subprocess, "run", raise_not_found)
    path = tmp_path / "clip.webm"
    path.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 16)

    result = video_ffprobe.extract(path, container="matroska")

    assert result.container == "matroska"
    assert result.items == []
    assert any("ffprobe" in w for w in result.warnings)


def test_ffprobe_receives_the_full_path(tmp_path, monkeypatch):
    # Regression: ein Path-Objekt hat ein `.name`-Attribut (nur der Dateiname!) —
    # ffprobe muss trotzdem den vollen Pfad bekommen.
    seen_paths = []

    def fake_run(cmd, **kwargs):
        seen_paths.append(cmd[-1])
        assert cmd[-4:-2] == ["-protocol_whitelist", "file"]   # nur lokale Dateien (#190)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"{}", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    path = tmp_path / "clip.webm"
    path.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 16)

    video_ffprobe.extract(path, container="matroska")          # als Path
    video_ffprobe.extract(str(path), container="matroska")     # als String
    with open(path, "rb") as fh:
        video_ffprobe.extract(fh, container="matroska")        # als offener Strom

    assert seen_paths == ["file:" + str(path.absolute())] * 3


def test_ffprobe_error_output_becomes_warning(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=1, stdout=b"", stderr=b"Invalid data found"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    path = tmp_path / "clip.webm"
    path.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 16)

    result = video_ffprobe.extract(path, container="matroska")

    assert result.items == []
    assert any("Invalid data found" in w for w in result.warnings)


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe nicht installiert")
def test_real_ffprobe_on_garbage_file_warns(tmp_path):
    path = tmp_path / "kaputt.webm"
    path.write_bytes(b"\x1a\x45\xdf\xa3" + b"\xff" * 16)

    result = video_ffprobe.extract(path, container="matroska")

    assert result.items == []
    assert result.warnings
