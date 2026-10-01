"""Songtext mit Zeiten (#234): Untertitel-Spur (Suno V6, ``mov_text``),
ID3 ``SYLT`` und LRC im Songtext-Tag → ``lyrics_synced`` / ``song_sections``.

Reine Parser ohne ffmpeg; die Integration baut ihre M4A mit Untertitel-Spur
selbst (``lavfi`` + SRT-Text, kein Blob im Repo) und wird ohne ffmpeg
übersprungen."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from feral.db import connect, store_extraction
from feral.extract import container
from feral.extract.types import RawMetadataItem
from feral.hashing import hash_file
from feral.interpret import audio as audio_parser
from feral.interpret import lyrics_sync as ls

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg nicht installiert")

# So sieht die Spur eines Suno-V6-Songs als SRT aus (Abschnittsmarke mit
# gleicher Start- und Endzeit).
SRT = """1
00:00:00,500 --> 00:00:01,400
[Verse]

2
00:00:01,500 --> 00:00:02,200
Grey skies <i>above</i>

3
00:00:02,400 --> 00:00:02,400
[Chorus]

4
00:00:02,500 --> 00:00:03,500
Sing it
loud
"""


def _items(**extra) -> list[RawMetadataItem]:
    items = [RawMetadataItem(source="isobmff:stream0", keyword="codec_type", text="audio",
                             data=None, encoding="utf-8")]
    for source, (keyword, text, data) in extra.items():
        items.append(RawMetadataItem(source=source.replace("__", ":").replace("_", "."),
                                     keyword=keyword, text=text, data=data,
                                     encoding="binary" if data else "utf-8"))
    return items


def _fields(items) -> dict[str, list[str]]:
    interp = audio_parser.parse(items)
    out: dict[str, list[str]] = {}
    for f in interp.fields if interp else ():
        out.setdefault(f.field, []).append(f.value)
    return out


# -- reine Parser --------------------------------------------------------------------

def test_srt_lines_markup_and_multiline():
    lines = ls.parse_srt(SRT)
    assert lines == [(500, 1400, "[Verse]"), (1500, 2200, "Grey skies above"),
                     (2400, None, "[Chorus]"), (2500, 3500, "Sing it loud")]
    assert ls.sections(lines) == [(500, "Verse"), (2400, "Chorus")]


def test_instrumental_sections_move_to_where_the_singing_stopped():
    """Suno gibt einer Solo-Marke die Zeit des nächsten gesungenen Worts: sie
    stünde am ENDE des Solos, auf derselben Stelle wie der nächste Abschnitt."""
    lines = [(0, 0, "[Guitar Intro]"), (8000, 0, "[Verse 1]"), (8000, 11000, "Line one here"),
             (11000, 40000, "Last line before solo"),          # Ende reicht bis zur nächsten Zeile
             (40000, 40000, "[Guitar Solo]"), (40000, 40000, "[Verse 2]"),
             (40000, 43000, "Back again"),
             (43000, 60000, "End of verse"), (60000, 60000, "[Solo]"), (60000, 60000, "[Bridge]"),
             (60000, 60000, "[Chorus]"), (60000, 62000, "Sing it loud")]
    lines = [(s, e or None, t) for s, e, t in lines]
    secs = dict((name, ms) for ms, name in ls.sections(lines))
    assert secs["Guitar Intro"] == 0                     # vor jedem Gesang: bei 0
    assert secs["Verse 1"] == 8000
    assert secs["Guitar Solo"] == 11000 + 2500 + 700 * 4 # Singdauer der letzten Zeile
    assert secs["Verse 2"] == 40000                      # gesungene Abschnitte bleiben
    # zwei instrumentale Marken hintereinander teilen sich die Lücke
    start = 43000 + 2500 + 700 * 3
    assert secs["Solo"] == start
    assert secs["Bridge"] == start + (60000 - start) // 2
    assert secs["Chorus"] == 60000


def test_lrc_needs_two_timed_lines_and_strips_cleanly():
    lrc = "[ar:Band]\n[00:01.50]First\n[00:03.25][00:09.00]Twice\n"
    assert ls.parse_lrc(lrc) == [(1500, None, "First"), (3250, None, "Twice"), (9000, None, "Twice")]
    assert ls.strip_lrc(lrc) == "First\nTwice"
    assert ls.parse_lrc("[Chorus]\nJust a normal text") == []


def _sylt(entries, *, enc=3, fmt=2) -> bytes:
    term = b"\x00\x00" if enc in (1, 2) else b"\x00"
    codec = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}[enc]
    body = b"".join(t.encode(codec) + term + struct.pack(">I", ms) for t, ms in entries)
    return bytes([enc]) + b"eng" + bytes([fmt, 1]) + "desc".encode(codec) + term + body


def test_sylt_milliseconds_utf8_and_utf16_mpeg_frames_skipped():
    assert ls.parse_sylt(_sylt([("Hello", 1000), ("World", 2500)])) == [
        (1000, None, "Hello"), (2500, None, "World")]
    assert [t for _s, _e, t in ls.parse_sylt(_sylt([("Hallö", 10), ("Welt", 20)], enc=1))] == ["Hallö", "Welt"]
    assert ls.parse_sylt(_sylt([("x", 1)], fmt=1)) == []          # MPEG-Frames: übergangen
    assert ls.parse_sylt(b"\x03eng") == []                         # abgeschnitten: nichts, kein Absturz


# -- Audio-Parser ------------------------------------------------------------------------

def test_parser_prefers_subtitle_and_derives_plain_lyrics():
    f = _fields(_items(isobmff__stream2_subtitle=("srt", SRT, None)))
    lines = json.loads(f["lyrics_synced"][0])
    assert lines[1] == [1500, 2200, "Grey skies above"]
    assert json.loads(f["song_sections"][0]) == [[500, "Verse"], [2400, "Chorus"]]
    assert f["lyrics"] == ["[Verse]\nGrey skies above\n[Chorus]\nSing it loud"]


def test_parser_lrc_in_lyrics_tag_becomes_clean_lyrics_plus_timing():
    items = [RawMetadataItem(source="id3v2:USLT", keyword="eng:", text="[00:01.00]One\n[00:02.00]Two",
                             data=None, encoding="utf-8")]
    f = _fields(items)
    assert f["lyrics"] == ["One\nTwo"]
    assert json.loads(f["lyrics_synced"][0]) == [[1000, None, "One"], [2000, None, "Two"]]
    assert "song_sections" not in f


def test_parser_sylt_and_plain_tag_side_by_side():
    items = [RawMetadataItem(source="id3v2:USLT", keyword="eng:", text="One\nTwo", data=None, encoding="utf-8"),
             RawMetadataItem(source="id3v2:SYLT", keyword=None, text=None,
                             data=_sylt([("One", 100), ("Two", 900)]), encoding="binary")]
    f = _fields(items)
    assert f["lyrics"] == ["One\nTwo"]
    assert json.loads(f["lyrics_synced"][0])[1] == [900, None, "Two"]


def test_parser_without_timing_adds_nothing():
    f = _fields([RawMetadataItem(source="id3v2:USLT", keyword="eng:", text="Just [Chorus] text",
                                 data=None, encoding="utf-8")])
    assert "lyrics_synced" not in f and f["lyrics"] == ["Just [Chorus] text"]


# -- Integration mit ffmpeg ------------------------------------------------------------

def _song(tmp_path: Path, name: str = "song.m4a", *, subtitle: bool = True) -> Path:
    srt = tmp_path / "lyrics.srt"
    srt.write_text(SRT, encoding="utf-8")
    out = tmp_path / name
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=4"]
    if subtitle:
        cmd += ["-i", str(srt), "-map", "0", "-map", "1", "-c:s", "mov_text"]
    subprocess.run(cmd + ["-c:a", "aac", str(out)], check=True)
    return out


@needs_ffmpeg
def test_m4a_subtitle_track_lands_in_layer1_as_srt(tmp_path):
    ex = container.extract(_song(tmp_path), audio_enabled=True)
    assert ex.media_kind == "audio"
    subs = [i for i in ex.items if i.source.endswith(".subtitle")]
    assert len(subs) == 1 and subs[0].keyword == "srt" and "Grey skies <i>above</i>" in subs[0].text   # byte-treu
    f = _fields(ex.items)
    assert json.loads(f["song_sections"][0])[1][1] == "Chorus"


@needs_ffmpeg
def test_video_subtitles_are_not_extracted(tmp_path):
    srt = tmp_path / "s.srt"
    srt.write_text(SRT, encoding="utf-8")
    out = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=d=2:s=64x64",
                    "-i", str(srt), "-map", "0", "-map", "1", "-c:s", "mov_text",
                    "-c:v", "mpeg4", str(out)], check=True)
    ex = container.extract(out, audio_enabled=True)
    assert ex.media_kind == "video"
    assert not [i for i in ex.items if i.source.endswith(".subtitle")]


@needs_ffmpeg
def test_backfill_task_fetches_missing_subtitles_and_endpoint_serves_lines(tmp_path):
    """Stand vor dem Update: ffprobe kannte die Spur, Schicht 1 hatte ihren
    Text nicht. Die Nachhol-Aufgabe holt ihn, der Endpunkt liefert Zeilen."""
    from feral.web.app import create_app
    from feral.web.tasks import audio_subtitles_task

    db = tmp_path / "t.sqlite"
    song = _song(tmp_path)
    plain = _song(tmp_path, "plain.m4a", subtitle=False)
    conn = connect(db)
    for path in (song, plain):
        ex = container.extract(path, audio_enabled=True)
        ex.items[:] = [i for i in ex.items if not i.source.endswith(".subtitle")]   # alter Stand
        store_extraction(conn, file_hash=hash_file(path), file_size=path.stat().st_size,
                         path=path, extraction=ex)
    conn.commit()
    try:
        result = audio_subtitles_task(conn, {"rules": {"audio": True}}, lambda **_k: None, None)
        assert "summary" in result
        h = hash_file(song)
        assert conn.execute("SELECT COUNT(*) FROM raw_metadata WHERE file_hash = ? AND source LIKE '%.subtitle'",
                            (h,)).fetchone()[0] == 1
        # Nur der Song mit Spur ging durch den Scan, nichts sonst.
        assert conn.execute("SELECT COUNT(*) FROM raw_metadata WHERE source LIKE '%.subtitle'").fetchone()[0] == 1
    finally:
        conn.close()

    app = create_app(db, thumb_cache=tmp_path / "thumbs", audio_cache=tmp_path / "audio")
    try:
        lyrics = next(r for r in app.routes if getattr(r, "path", None) == "/api/audio/lyrics/{file_hash}").endpoint
        assert lyrics(h)["lines"][1] == [1500, 2200, "Grey skies above"]
        assert lyrics(h)["sections"] == [[500, "Verse"], [2400, "Chorus"]]
        assert lyrics(hash_file(plain)) == {"lines": [], "sections": []}
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


# -- fremde Eingabe: gedeckelt und linear ---------------------------------------------


def test_hostile_lyrics_end_quickly_and_stay_small():
    """Tags sind fremde Eingabe: präparierte Zeilen dürfen weder Minuten
    rechnen noch die Ausgabe aufblähen (Obergrenzen in lyrics_sync)."""
    import time

    started = time.monotonic()
    angle = "[00:01.00]" + "<" * 400_000 + "\n[00:02.00]zwei"
    assert ls.parse_lrc(angle)[-1][2] == "zwei"
    # viele Zeitstempel × langer Text: früher k Kopien des ganzen Texts
    burst = "[00:01.00]" * 5000 + "x" * 100_000 + "\n[00:02.00]zwei"
    lines = ls.parse_lrc(burst)
    assert len(lines) <= ls.MAX_STAMPS + 1 and all(len(t) <= ls.MAX_ROW for _s, _e, t in lines)
    many = "\n".join(f"[{i // 60:02d}:{i % 60:02d}.00][A]" for i in range(20_000))
    assert len(ls.parse_lrc(many)) == ls.MAX_LINES
    # Abschnitts-Schätzung: lauter Marken ohne Gesang, früher quadratisch
    marks = [(i * 10, None, "[A]" if i % 3 else "la") for i in range(ls.MAX_LINES)]
    assert len(ls.sections(marks)) > 1000
    # SRT: absurde Stundenzahl und eine Ziffernwüste werfen nicht
    srt = "1\n" + "9" * 5000 + ":00:01,000 --> 00:00:02,000\nText\n\n2\n" + "7" * 200_000 + "\n"
    assert all(isinstance(s, int) for s, _e, _t in ls.parse_srt(srt))
    sylt = _sylt([("x" * 10_000, i) for i in range(5000)])
    out = ls.parse_sylt(sylt)
    assert len(out) == ls.MAX_LINES and len(out[0][2]) == ls.MAX_ROW
    assert time.monotonic() - started < 5
