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


def test_items_from_ffprobe_maps_format_and_stream_tags():
    items = video_ffprobe.items_from_ffprobe(FFPROBE_JSON, container="matroska")

    by_source_keyword = {(i.source, i.keyword): i.text for i in items}
    assert by_source_keyword[("matroska:format.tag", "COMMENT")] == "made with comfyui"
    assert by_source_keyword[("matroska:format.tag", "ENCODER")] == "Lavf60.3.100"
    assert by_source_keyword[("matroska:stream0.tag", "DURATION")] == "00:00:05.000"
    assert len(items) == 3  # Stream 1 hat keine Tags, format.filename ist kein Tag


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
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"{}", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    path = tmp_path / "clip.webm"
    path.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 16)

    video_ffprobe.extract(path, container="matroska")          # als Path
    video_ffprobe.extract(str(path), container="matroska")     # als String
    with open(path, "rb") as fh:
        video_ffprobe.extract(fh, container="matroska")        # als offener Strom

    assert seen_paths == [str(path)] * 3


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
