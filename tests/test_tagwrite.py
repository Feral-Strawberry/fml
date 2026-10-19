"""Tests: Angaben von Hand in die Kopie schreiben (ADR 0107, #279).

MP3 rein programmatisch (ID3-Tag + Füll-Frames aus ``audiobuild``), gelesen
mit fmls eigenem Leser und Parser. M4A mit ffmpeg gebaut (``lavfi`` + SRT,
kein Blob im Repo), ohne ffmpeg übersprungen.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from .audiobuild import apic, comm, id3_frame, id3_tag, id3v1, mp3, text_frame
from feral.extract import container, id3
from feral.hashing import hash_file
from feral.interpret import audio as audio_parser
from feral.tagwrite import Tags, Unsupported, srt, write_m4a, write_mp3

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg nicht installiert")

LINES = [[500, None, "[Verse]"], [2000, 3900, "Erste Zeile"], [None, None, ""],
         [4000, None, "Zweite Zeile"]]


def _sylt(entries: list[tuple[str, int]]) -> bytes:
    body = b"\x03eng\x02\x01\x00"
    for text, ms in entries:
        body += text.encode() + b"\x00" + struct.pack(">I", ms)
    return body


def _source(tmp_path: Path, frames: bytes, *, major: int = 4, tail: bytes = b"") -> Path:
    path = tmp_path / "song.mp3"
    path.write_bytes(mp3(id3_tag(frames, major=major) if frames else b"", tail=tail))
    return path


def _suno_frames(major: int = 4) -> bytes:
    f = lambda fid, p: id3_frame(fid, p, major=major)  # noqa: E731
    return b"".join([
        f("TIT2", text_frame("Alt")), f("TPE1", text_frame("Suno")),
        f("COMM", comm("eng", "", "made with suno; id=1")),
        f("USLT", comm("eng", "", "alter Text")),
        f("SYLT", _sylt([("alter Text", 100)])),
        f("GEOB", b"\x00application/c2pa\x00\x00c2pa\x00" + b"\x01" * 40),
        f("WOAS", b"https://suno.com/song/1"),
        f("PRIV", b"owner\x00" + b"\x02" * 8),
        f("APIC", apic("image/jpeg", 3, "", b"OLDFRONT")),
        f("APIC", apic("image/jpeg", 4, "back", b"BACK")),
    ])


def _read(path: Path) -> tuple[list, bytes]:
    data = path.read_bytes()
    size = id3.id3v2_size(data[:10])
    warnings: list[str] = []
    items = id3.parse_id3v2(data[:size], warnings)
    assert warnings == []
    return items, data[size:]


def _fields(items) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f in audio_parser.parse(items).fields:
        out.setdefault(f.field, []).append(f.value)
    return out


def _after_tag(path: Path) -> bytes:
    data = path.read_bytes()
    return data[id3.id3v2_size(data[:10]) or 0:]


# -- MP3 ---------------------------------------------------------------------------

def test_mp3_replaces_only_what_is_set_and_keeps_every_other_frame(tmp_path):
    src = _source(tmp_path, _suno_frames(), tail=id3v1(title="v1"))
    dest = tmp_path / "out.mp3"
    tags = Tags(fields={"title": ["Neu"], "artist": ["Feral Strawberry", "Gast"],
                        "year": ["2026"], "genre": ["Rock"]},
                lyrics=LINES, cover=b"\xff\xd8NEWCOVER")
    write_mp3(src, dest, tags, hash_file(src))

    items, audio = _read(dest)
    assert audio == _after_tag(src)                    # Ton (und ID3v1) Byte für Byte
    f = _fields(items)
    assert f["title"] == ["Neu"] and f["artist"] == ["Feral Strawberry", "Gast"]
    assert f["year"] == ["2026"] and f["genre"] == ["Rock"]
    assert f["lyrics"] == ["[Verse]\nErste Zeile\n\nZweite Zeile"]
    assert json.loads(f["lyrics_synced"][0]) == [
        [500, None, "[Verse]"], [2000, None, "Erste Zeile"], [4000, None, "Zweite Zeile"]]
    by_source = {}
    for item in items:
        by_source.setdefault(item.source, []).append(item)
    # Unberührtes reist mit, auch die C2PA-Daten
    old_items, _ = _read(src)
    for fid in ("COMM", "GEOB", "WOAS", "PRIV"):
        assert [(i.keyword, i.text, i.data) for i in by_source[f"id3v2:{fid}"]] == [
            (i.keyword, i.text, i.data) for i in old_items if i.source == f"id3v2:{fid}"]
    pictures = [json.loads(i.text) for i in by_source["id3v2:APIC"]]
    assert [p["type"] for p in pictures] == [3, 4]      # neues Titelbild vorn, Rückseite bleibt
    assert pictures[0]["fml"] is True and "fml" not in pictures[1]   # Kennung (ADR 0107)
    assert pictures[0]["size"] == len(id3.mark_fml_cover(b"\xff\xd8NEWCOVER"))
    assert len(by_source["id3v2:USLT"]) == len(by_source["id3v2:SYLT"]) == 1
    assert dest.read_bytes()[3] == 4                                # Version bleibt


def test_mp3_without_manual_lyrics_keeps_the_lyrics_of_the_file(tmp_path):
    src = _source(tmp_path, _suno_frames())
    dest = tmp_path / "out.mp3"
    write_mp3(src, dest, Tags(fields={"album": ["Release"]}), hash_file(src))
    f = _fields(_read(dest)[0])
    assert f["album"] == ["Release"] and f["title"] == ["Alt"]
    assert f["lyrics"] == ["alter Text"] and "lyrics_synced" in f


def test_mp3_lyrics_without_times_drop_the_old_sylt(tmp_path):
    src = _source(tmp_path, _suno_frames())
    dest = tmp_path / "out.mp3"
    write_mp3(src, dest, Tags(lyrics=[[None, None, "Nur Text"]]), hash_file(src))
    items, _ = _read(dest)
    assert not [i for i in items if i.source == "id3v2:SYLT"]
    assert _fields(items)["lyrics"] == ["Nur Text"]


def test_mp3_id3v23_joins_values_and_uses_tyer(tmp_path):
    src = _source(tmp_path, _suno_frames(major=3), major=3)
    dest = tmp_path / "out.mp3"
    write_mp3(src, dest, Tags(fields={"artist": ["Ä", "Ωmega"], "year": ["2025"]},
                              lyrics=[[0, None, "Ωδή"]]), hash_file(src))
    items, _ = _read(dest)
    assert dest.read_bytes()[3] == 3
    f = _fields(items)
    assert f["artist"] == ["Ä; Ωmega"] and f["year"] == ["2025"]
    assert [i.source for i in items if i.source in ("id3v2:TYER", "id3v2:TDRC")] == ["id3v2:TYER"]
    assert json.loads(f["lyrics_synced"][0]) == [[0, None, "Ωδή"]]   # UTF-16 in 2.3


def test_mp3_without_tag_gets_an_id3v23_tag(tmp_path):
    src = _source(tmp_path, b"")
    dest = tmp_path / "out.mp3"
    write_mp3(src, dest, Tags(fields={"title": ["Neu"]}), hash_file(src))
    assert dest.read_bytes()[:4] == b"ID3\x03"
    items, audio = _read(dest)
    assert audio == src.read_bytes() and _fields(items)["title"] == ["Neu"]


def test_mp3_refuses_id3v22_and_stacked_tags(tmp_path):
    old = tmp_path / "old.mp3"
    old.write_bytes(mp3(id3_tag(id3_frame("TT2", text_frame("x", 0), major=2), major=2)))
    with pytest.raises(Unsupported):
        write_mp3(old, tmp_path / "a.mp3", Tags(fields={"title": ["n"]}), hash_file(old))
    stacked = tmp_path / "stacked.mp3"
    tag = id3_tag(id3_frame("TIT2", text_frame("x")))
    stacked.write_bytes(mp3(tag + tag))
    with pytest.raises(Unsupported):
        write_mp3(stacked, tmp_path / "b.mp3", Tags(fields={"title": ["n"]}), hash_file(stacked))


def test_mp3_checks_the_source_against_the_item_hash(tmp_path):
    src = _source(tmp_path, _suno_frames())
    with pytest.raises(OSError, match="item hash"):
        write_mp3(src, tmp_path / "out.mp3", Tags(fields={"title": ["n"]}), "0" * 64)


def test_fml_cover_mark_is_a_jpeg_comment():
    jpeg = b"\xff\xd8\xff\xe0\x00\x04ab\xff\xda\x00\x02DATA"
    marked = id3.mark_fml_cover(jpeg)
    assert id3.is_fml_cover(marked) and not id3.is_fml_cover(jpeg)
    assert id3.mark_fml_cover(marked) == marked                  # nur einmal
    assert marked.endswith(jpeg[2:])                             # Bild unverändert
    assert not id3.is_fml_cover(b"\x89PNG" + id3.FML_COVER)       # kein JPEG


def test_srt_fills_missing_ends_like_suno():
    text = srt([[500, None, "[Verse]"], [2000, 3900, "Eins"], [4000, None, "Zwei"]], 6000)
    assert "00:00:00,500 --> 00:00:02,000\n[Verse]" in text
    assert "00:00:02,000 --> 00:00:03,900\nEins" in text
    assert "00:00:04,000 --> 00:00:06,000\nZwei" in text


# -- M4A über ffmpeg ---------------------------------------------------------------

def _m4a(tmp_path: Path, *, codec: str = "aac") -> Path:
    cover = tmp_path / "c.jpg"
    Image.new("RGB", (64, 64), "red").save(cover)
    lyr = tmp_path / "orig.srt"
    lyr.write_text("1\n00:00:00,500 --> 00:00:02,000\nAlte Zeile\n", encoding="utf-8")
    out = tmp_path / "song.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=4",
                    "-i", str(cover), "-i", str(lyr), "-map", "0", "-map", "1", "-map", "2",
                    "-c:a", codec, "-c:v", "copy", "-c:s", "mov_text",
                    "-disposition:v", "attached_pic", "-metadata", "title=Alt",
                    "-metadata", "comment=made with suno", "-metadata", "lyrics=Alte Zeile",
                    "-f", "ipod" if codec == "aac" else "mp4", str(out)], check=True)
    return out


def _brand(path: Path) -> bytes:
    return path.read_bytes()[8:12]


def _has_libopus() -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True)
    return " libopus " in out.stdout


def _probe(path: Path) -> tuple[dict[str, list[str]], list]:
    ex = container.extract(path, audio_enabled=True)
    return _fields(ex.items), ex.items


@needs_ffmpeg
def test_m4a_writes_fields_cover_and_a_new_subtitle_track(tmp_path):
    src = _m4a(tmp_path)
    dest = tmp_path / "out.m4a"
    jpeg = tmp_path / "neu.jpg"
    Image.new("RGB", (32, 20), "blue").save(jpeg)
    dropped = write_m4a(src, dest, Tags(fields={"title": ["Neu"], "artist": ["A", "B"]},
                                        lyrics=LINES, cover=jpeg.read_bytes(),
                                        duration_ms=4000), hash_file(src))
    assert dropped == []
    f, items = _probe(dest)
    assert f["title"] == ["Neu"] and f["artist"] == ["A; B"]
    assert f["lyrics"] == ["[Verse]\nErste Zeile\n\nZweite Zeile"]
    synced = json.loads(f["lyrics_synced"][0])
    assert [line[0] for line in synced] == [500, 2000, 4000]
    assert synced[1] == [2000, 3900, "Erste Zeile"]      # Ende von Hand bleibt
    widths = [i.text for i in items if i.keyword == "width"]
    assert "32" in widths                                            # neues Cover
    covers = [json.loads(i.text) for i in items if i.source == "isobmff:covr"]
    assert len(covers) == 1 and covers[0]["fml"] is True and covers[0]["mime"] == "image/jpeg"
    assert _brand(dest) == _brand(src) == b"M4A "                   # Kennung bleibt


@pytest.mark.skipif(not _has_libopus(), reason="ffmpeg ohne libopus")
def test_m4a_with_opus_audio_like_suno(tmp_path):
    """Suno liefert M4A mit Opus-Ton; den kennt der ``ipod``-Muxer nicht."""
    src = _m4a(tmp_path, codec="libopus")
    dest = tmp_path / "out.m4a"
    write_m4a(src, dest, Tags(fields={"title": ["Neu"]}, lyrics=[[300, None, "Neu"]],
                              duration_ms=4000), hash_file(src))
    f, _items = _probe(dest)
    assert f["title"] == ["Neu"] and f["audio_codec"] == ["opus"]
    assert json.loads(f["lyrics_synced"][0]) == [[300, 4000, "Neu"]]


@needs_ffmpeg
def test_m4a_without_manual_lyrics_keeps_track_and_cover(tmp_path):
    src = _m4a(tmp_path)
    dest = tmp_path / "out.m4a"
    write_m4a(src, dest, Tags(fields={"album": ["Release"]}), hash_file(src))
    f, items = _probe(dest)
    assert f["album"] == ["Release"] and f["title"] == ["Alt"]
    assert json.loads(f["lyrics_synced"][0])[0][2] == "Alte Zeile"
    assert "64" in [i.text for i in items if i.keyword == "width"]
    covers = [json.loads(i.text) for i in items if i.source == "isobmff:covr"]
    assert len(covers) == 1 and "fml" not in covers[0]     # fremdes Cover: ohne Kennung


@needs_ffmpeg
def test_m4a_lyrics_without_times_drop_the_track(tmp_path):
    src = _m4a(tmp_path)
    dest = tmp_path / "out.m4a"
    write_m4a(src, dest, Tags(lyrics=[[None, None, "Nur Text"]]), hash_file(src))
    f, items = _probe(dest)
    assert f["lyrics"] == ["Nur Text"] and "lyrics_synced" not in f
    assert not [i for i in items if i.source.endswith(".subtitle")]
