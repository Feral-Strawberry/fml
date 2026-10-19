"""Angaben von Hand in die Kopie eines Songs schreiben (ADR 0107, Issue #279).

Nur für den Kopie-Export (ADR 0103): Geschrieben wird ausschließlich in eine
neue Datei im Export-Ordner, nie ins Original (ADR 0041). Was es von Hand
gibt (Angaben, Songtext, Cover), ersetzt den Tag der Datei; alles andere
bleibt, wie es ist.

- **MP3** über einen eigenen ID3v2-Schreiber (Standardbibliothek): ffmpeg
  verlöre beim Umpacken ``SYLT``, ``GEOB`` (C2PA) und ``WOAS`` und machte
  aus ``USLT``/``COMM`` ``TXXX``-Frames (Messung im ADR). Ersetzt werden nur
  die betroffenen Frames, alle anderen reisen Byte für Byte mit; hinter dem
  Tag stehen die Bytes des Originals.
- **M4A** über ffmpeg ohne Neukodierung (``-c copy``); Songtext mit Zeiten
  als neue Untertitel-Spur aus einer erzeugten SRT (wie Suno V6).

Geprüft wird statt gegen den Item-Hash (ADR 0107 Punkt 9): die Quelle vorher
gegen den Item-Hash, die Kopie danach über den Ton (MP3: Bytes hinter dem
Tag, M4A: MD5 der Tonpakete). Erst dann ist die Kopie fertig.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .extract import id3
from .processes import ffmpeg_quiet_args
from .tools import NO_WINDOW, find_binary, media_input

log = logging.getLogger(__name__)

# Container, in die fml schreiben kann (Namen wie in ``items.container``).
WRITABLE = frozenset({"mp3", "isobmff"})

_SEP = "; "                    # mehrere Werte in ID3v2.3 und M4A (ADR 0107 Punkt 8)
_LANG = b"XXX"                 # Sprache unbekannt (ID3v2 §4.10/§4.11)
_PADDING = 1024
_BLOCK = 1024 * 1024

# Angabe von Hand → ID3-Frames, die sie ersetzt. Beim Jahr fallen auch die
# Teil-Datumsframes von ID3v2.3 weg, sonst bliebe ein altes Datum stehen.
_ID3_FRAMES = {
    "title": ("TIT2",), "artist": ("TPE1",), "album_artist": ("TPE2",),
    "album": ("TALB",), "track": ("TRCK",), "disc": ("TPOS",),
    "year": ("TDRC", "TYER", "TDAT", "TIME", "TRDA"), "genre": ("TCON",),
}
_LYRICS_FRAMES = ("USLT", "SYLT")
_COVER_TYPES = (0, 3)          # „anderes" und „Titelbild" (APIC-Bildtyp)

# Angabe von Hand → ffmpeg-Schlüssel im MP4-Muxer.
_MP4_KEYS = {
    "title": "title", "artist": "artist", "album_artist": "album_artist",
    "album": "album", "track": "track", "disc": "disc", "year": "date",
    "genre": "genre",
}
# Diese Schlüssel setzt ffmpeg selbst oder sie sind Technik, kein Verlust.
_MP4_IGNORED = frozenset({"encoder", "major_brand", "minor_version", "compatible_brands",
                          "creation_time"})


# Eine Markenkennung sind vier druckbare ASCII-Zeichen (``M4A `` endet auf
# ein Leerzeichen); alles andere reicht fml nicht an ffmpeg weiter.
_BRAND = re.compile(r"[\x20-\x7e]{4}")


class Unsupported(Exception):
    """Diese Datei kann fml nicht beschriften (etwa ID3v2.2): Sie geht
    bitgleich raus und zählt wie ein anderes Format."""


@dataclass(frozen=True)
class Tags:
    """Was in die Kopie soll. ``fields`` wie ``manual_fields.fields_of``,
    ``lyrics`` die Zeilen aus ``manual_lyrics`` (``None`` = Songtext der
    Datei bleibt), ``cover`` ein fertiges JPEG, ``duration_ms`` die Länge
    des Songs (Ende der letzten Untertitel-Zeile)."""

    fields: dict[str, list[str]] = field(default_factory=dict)
    lyrics: list[list[Any]] | None = None
    cover: bytes | None = None
    duration_ms: int | None = None

    def __bool__(self) -> bool:
        return bool(self.fields or self.lyrics or self.cover)


# -- Songtext ---------------------------------------------------------------------

def lyrics_text(lines: Sequence[Sequence[Any]]) -> str:
    """Der Songtext als Text, eine Zeile je Zeile (Leerzeilen trennen Strophen)."""
    return "\n".join(str(line[2]) for line in lines)


def timed_lines(lines: Sequence[Sequence[Any]]) -> list[list[Any]] | None:
    """Die gesungenen Zeilen mit Zeiten, wenn JEDE Textzeile eine Startzeit
    hat (wie ``manual_lyrics.projection``), sonst ``None``."""
    sung = [list(line) for line in lines if line[2]]
    if not sung or any(line[0] is None for line in sung):
        return None
    return sung


def srt(lines: Sequence[Sequence[Any]], duration_ms: int | None) -> str:
    """Zeilen mit Zeiten → SRT. Fehlt ein Ende, gilt der Start der nächsten
    Zeile (wie bei Suno), bei der letzten das Songende (sonst +3 s)."""
    def stamp(ms: int) -> str:
        h, rest = divmod(ms, 3_600_000)
        m, rest = divmod(rest, 60_000)
        s, ms = divmod(rest, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    out = []
    for n, (start, end, text) in enumerate(lines, start=1):
        if end is None or end <= start:
            nxt = lines[n][0] if n < len(lines) else None
            end = nxt if nxt is not None and nxt > start else (
                duration_ms if duration_ms and duration_ms > start else start + 3000)
        out.append(f"{n}\n{stamp(start)} --> {stamp(end)}\n{text}\n")
    return "\n".join(out)


# -- ID3v2 ------------------------------------------------------------------------

def _syncsafe(n: int) -> bytes:
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def _frame(fid: str, payload: bytes, major: int, flags: bytes = b"\x00\x00") -> bytes:
    size = _syncsafe(len(payload)) if major == 4 else struct.pack(">I", len(payload))
    return fid.encode("ascii") + size + flags + payload


def _encoding(texts: Sequence[str], major: int) -> int:
    """ID3-Textkodierung: 2.4 UTF-8; 2.3 Latin-1, wo es reicht (lesen auch
    alte Geräte), sonst UTF-16 mit BOM."""
    if major == 4:
        return 3
    try:
        for text in texts:
            text.encode("latin-1")
    except UnicodeEncodeError:
        return 1
    return 0


def _enc(text: str, enc: int) -> bytes:
    return text.encode({0: "latin-1", 1: "utf-16", 3: "utf-8"}[enc])


def _term(enc: int) -> bytes:
    return b"\x00\x00" if enc == 1 else b"\x00"


def _text_frame(fid: str, values: Sequence[str], major: int) -> bytes:
    if major == 4:     # 2.4: mehrere Werte \0-getrennt (so liest fml sie)
        return _frame(fid, b"\x03" + "\x00".join(values).encode("utf-8"), major)
    text = _SEP.join(values)
    enc = _encoding([text], major)
    return _frame(fid, bytes([enc]) + _enc(text, enc), major)


def _uslt(text: str, major: int) -> bytes:
    enc = _encoding([text], major)
    return _frame("USLT", bytes([enc]) + _LANG + _enc("", enc) + _term(enc)
                  + _enc(text, enc), major)


def _sylt(lines: Sequence[Sequence[Any]], major: int) -> bytes:
    """``SYLT`` in Millisekunden (Zeitformat 2), Inhalt Songtext (Typ 1)."""
    texts = [str(line[2]) for line in lines]
    enc = _encoding(texts, major)
    body = bytes([enc]) + _LANG + b"\x02\x01" + _enc("", enc) + _term(enc)
    for (start, _end, _text), text in zip(lines, texts):
        body += _enc(text, enc) + _term(enc) + struct.pack(">I", int(start))
    return _frame("SYLT", body, major)


def _apic(jpeg: bytes, major: int) -> bytes:
    return _frame("APIC", b"\x00image/jpeg\x00\x03\x00" + jpeg, major)


def _marked(tags: Tags) -> bytes | None:
    """Das Cover mit fml-Kennung: Ein anderes fml zeigt es dann auch bei
    erkanntem KI-Erzeuger (ADR 0107, Nachtrag)."""
    return id3.mark_fml_cover(tags.cover) if tags.cover else None


def _apic_type(payload: bytes | None) -> int | None:
    """Bildtyp eines ``APIC``-Frames (nach Frame-Flags) oder ``None``."""
    if not payload:
        return None
    end = payload.find(b"\x00", 1)
    return payload[end + 1] if 0 < end < len(payload) - 1 else None


@dataclass
class _Tag:
    major: int
    frames: list[tuple[str, bytes, bytes]]   # (ID, Flags, Nutzlast roh)
    end: int                                 # Ende des Tags in der Datei (0 = keiner)


def _read_tag(head: bytes, rest: bytes) -> _Tag:
    """Den ID3v2-Tag am Dateianfang in Frames zerlegen (Nutzlast roh, wie
    sie in der Datei steht). ``rest`` beginnt nach dem 10-Byte-Kopf."""
    size = id3.id3v2_size(head)
    if size is None:
        return _Tag(3, [], 0)                 # kein Tag: fml schreibt ID3v2.3
    major, flags = head[3], head[5]
    if major not in (3, 4):
        raise Unsupported(f"ID3v2.{major}")
    body = rest[:id3._syncsafe(head[6:10])]
    if flags & 0x80 and major == 3:           # 2.3: ganzer Tag unsynchronisiert
        body = id3._unsync(body)
    pos = 0
    if flags & 0x40:                          # erweiterter Kopf fällt weg
        pos = (4 + struct.unpack(">I", body[:4])[0] if major == 3
               else id3._syncsafe(body[:4]))
    frames: list[tuple[str, bytes, bytes]] = []
    while pos + 10 <= len(body):
        fid_raw = body[pos:pos + 4]
        if fid_raw[0] == 0:
            break                             # Padding
        if not id3._is_frame_id(fid_raw):
            raise Unsupported("unreadable ID3v2 frame")
        size_bytes = body[pos + 4:pos + 8]
        fsize = (id3._syncsafe(size_bytes) if major == 4
                 else struct.unpack(">I", size_bytes)[0])
        if major == 4:
            fsize = id3._itunes_size(body, pos, fsize, size_bytes)
        payload = body[pos + 10:pos + 10 + fsize]
        if len(payload) < fsize:
            raise Unsupported("truncated ID3v2 frame")
        frames.append((fid_raw.decode("ascii"), body[pos + 8:pos + 10], payload))
        pos += 10 + fsize
    return _Tag(major, frames, size)


def build_id3(tag: _Tag, tags: Tags) -> bytes:
    """Neuer ID3v2-Tag: die neuen Frames, dann alle nicht ersetzten Frames
    des alten Tags unverändert (Kopf mit richtiger Größe neu gesetzt)."""
    major = tag.major
    drop = {fid for name in tags.fields for fid in _ID3_FRAMES[name]}
    if tags.lyrics:
        drop.update(_LYRICS_FRAMES)
    new = [_text_frame(_ID3_FRAMES[name][0] if not (name == "year" and major == 3)
                       else "TYER", values, major)
           for name, values in tags.fields.items() if values]
    cover = _marked(tags)
    if cover:   # vorn: Player und ffmpeg nehmen das erste Bild
        new.append(_apic(cover, major))
    kept = []
    for fid, flags, payload in tag.frames:
        if fid in drop:
            continue
        if fid == "APIC" and tags.cover:
            decoded = id3._frame_payload(fid, payload, struct.unpack(">H", flags)[0],
                                         major, [])
            kind = _apic_type(decoded)
            if kind is None or kind in _COVER_TYPES:
                continue
        kept.append(_frame(fid, payload, major, flags))
    tail = []
    if tags.lyrics:
        tail.append(_uslt(lyrics_text(tags.lyrics), major))
        timed = timed_lines(tags.lyrics)
        if timed:
            tail.append(_sylt(timed, major))
    body = b"".join(new + kept + tail) + b"\x00" * _PADDING
    return b"ID3" + bytes([major, 0, 0]) + _syncsafe(len(body)) + body


def _warnings(tag: bytes) -> set[str]:
    """Warnungen des fml-Lesers zu einem Tag, ohne Zahlen (Offsets)."""
    found: list[str] = []
    id3.parse_id3v2(tag, found)
    return {"".join(c for c in w if not c.isdigit()) for w in found}


def _hash_from(path: Path, offset: int) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        fh.seek(offset)
        while block := fh.read(_BLOCK):
            digest.update(block)
    return digest.hexdigest()


def write_mp3(source: Path, dest: Path, tags: Tags, file_hash: str) -> None:
    """``source`` mit neuem ID3v2-Tag nach ``dest`` schreiben und prüfen.
    ``Unsupported`` kommt, bevor etwas geschrieben ist; ``OSError``, wenn
    Quelle oder Kopie die Prüfung nicht bestehen (``dest`` bleibt dann dem
    Aufrufer zum Wegräumen)."""
    full, audio = hashlib.sha256(), hashlib.sha256()
    with source.open("rb") as fh:
        head = fh.read(10)
        size = id3.id3v2_size(head)
        if size is not None and size > id3.MAX_TAG:
            raise Unsupported("ID3v2 tag too large")
        rest = fh.read(size - 10) if size is not None else b""
        old = _read_tag(head, rest)
        if old.end:
            nxt = fh.read(10)
            if id3.id3v2_size(nxt) is not None:
                raise Unsupported("stacked ID3v2 tags")   # alte Angaben lägen dahinter
            fh.seek(old.end)
            full.update(head + rest)
        else:
            fh.seek(0)
        old_warnings = _warnings(head + rest) if old.end else set()
        new_tag = build_id3(old, tags)
        with dest.open("wb") as out:
            out.write(new_tag)
            while block := fh.read(_BLOCK):
                full.update(block)
                audio.update(block)
                out.write(block)
    if full.hexdigest() != file_hash:
        raise OSError("source does not match the item hash")
    if _hash_from(dest, len(new_tag)) != audio.hexdigest():
        raise OSError("audio of the copy differs from the original")
    if _warnings(new_tag) - old_warnings:
        raise OSError("the new ID3 tag does not read back cleanly")


# -- M4A über ffmpeg ---------------------------------------------------------------

def _run(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(args, capture_output=True, timeout=timeout, **NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise OSError(f"{Path(args[0]).name} timed out") from None
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise OSError(f"{Path(args[0]).name}: {stderr[-400:] or 'failed'}")
    return proc


def audio_md5(path: Path) -> str:
    """MD5 der Tonpakete (``-map 0:a -c copy -f md5``): gleich, wenn der Ton
    unverändert ist, egal was in der Verpackung steht."""
    ffmpeg = find_binary("ffmpeg")
    if ffmpeg is None:
        raise OSError("ffmpeg not found")
    proc = _run([ffmpeg, "-hide_banner", "-loglevel", "error", *media_input(path),
                 "-map", "0:a", "-c", "copy", "-f", "md5", "-"])
    return proc.stdout.decode("ascii", errors="replace").strip()


def _format_tags(path: Path) -> dict[str, str]:
    """Die Format-Tags, wie ffprobe sie nennt (Schlüssel klein)."""
    ffprobe = find_binary("ffprobe")
    if ffprobe is None:
        return {}
    try:
        proc = _run([ffprobe, "-v", "error", "-show_entries", "format_tags", "-of", "json",
                     *media_input(path)], timeout=60)
        tags = json.loads(proc.stdout or b"{}").get("format", {}).get("tags", {})
    except (OSError, ValueError):
        return {}
    return {str(key).lower(): str(value) for key, value in tags.items()}


def m4a_args(ffmpeg: str, source: Path, dest: Path, tags: Tags, *,
             cover: Path | None, subtitles: Path | None, brand: str = "") -> list[str]:
    """Die ffmpeg-Befehlszeile: Ton (und was bleibt) kopieren, Angaben setzen,
    Cover und Untertitel-Spur bei Bedarf ersetzen.

    Geschrieben wird immer mit dem allgemeinen MP4-Muxer: Der ``ipod``-Muxer
    kennt kein Opus, und Suno liefert M4A mit Opus-Ton. Die Markenkennung des
    Originals (``M4A ``, ``isom`` …) bleibt über ``-brand`` erhalten; Apple-
    Programme erkennen eine Musikdatei daran."""
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *ffmpeg_quiet_args(),
            *media_input(source)]
    extra = []
    if cover is not None:
        args += media_input(cover)
        extra.append(("cover", len(extra) + 1))
    if subtitles is not None:
        args += media_input(subtitles)
        extra.append(("subtitles", len(extra) + 1))
    args += ["-map", "0:a"]
    if cover is None:
        args += ["-map", "0:v?"]
    if not tags.lyrics:
        args += ["-map", "0:s?"]
    for kind, index in extra:
        args += ["-map", f"{index}:0"]
    args += ["-c", "copy"]
    if subtitles is not None:
        args += ["-c:s", "mov_text"]
    if cover is not None:
        args += ["-disposition:v:0", "attached_pic"]
    for name, values in tags.fields.items():
        if values:
            args += ["-metadata", f"{_MP4_KEYS[name]}={_SEP.join(values)}"]
    if tags.lyrics:
        args += ["-metadata", f"lyrics={lyrics_text(tags.lyrics)}"]
    if brand:
        args += ["-brand", brand]
    return args + ["-f", "mp4", "file:" + str(dest.absolute())]


def write_m4a(source: Path, dest: Path, tags: Tags, file_hash: str) -> list[str]:
    """``source`` mit neuen Angaben nach ``dest`` umpacken und prüfen. Gibt
    die Tags zurück, die ffmpeg nicht übernommen hat (fürs Serverlog)."""
    from .hashing import hash_file

    ffmpeg = find_binary("ffmpeg")
    if ffmpeg is None:
        raise OSError("ffmpeg not found")
    if hash_file(source) != file_hash:
        raise OSError("source does not match the item hash")
    before = _format_tags(source)
    brand = before.get("major_brand", "")
    with tempfile.TemporaryDirectory(prefix="fml-tags-") as tmp:
        cover = subtitles = None
        if tags.cover:
            cover = Path(tmp) / "cover.jpg"
            cover.write_bytes(_marked(tags))
        timed = timed_lines(tags.lyrics) if tags.lyrics else None
        if timed:
            subtitles = Path(tmp) / "lyrics.srt"
            subtitles.write_text(srt(timed, tags.duration_ms), encoding="utf-8")
        _run(m4a_args(ffmpeg, source, dest, tags, cover=cover, subtitles=subtitles,
                      brand=brand if _BRAND.fullmatch(brand) else ""))
    if not dest.is_file() or dest.stat().st_size == 0:
        raise OSError("ffmpeg wrote nothing")
    if audio_md5(dest) != audio_md5(source):
        raise OSError("audio of the copy differs from the original")
    dropped = set(before) - set(_format_tags(dest)) - _MP4_IGNORED
    return sorted(dropped)


def write(container: str, source: Path, dest: Path, tags: Tags, file_hash: str) -> list[str]:
    """Kopie mit Angaben schreiben (``container`` aus ``WRITABLE``); Rückgabe
    wie ``write_m4a`` (bei MP3 leer)."""
    if container == "mp3":
        write_mp3(source, dest, tags, file_hash)
        return []
    if container == "isobmff":
        return write_m4a(source, dest, tags, file_hash)
    raise Unsupported(container)
