"""Schicht-2-Parser: allgemeine Audio-Felder (ADR 0083).

Was jede Musikdatei hergeben kann, egal welcher Erzeuger — aus den Tags,
die der Audio-Walker (Schicht 1) byte-treu sichert, und den technischen
Fakten aus ffprobe:

- ``title``        Titel-Tag: ID3 ``TIT2``, Vorbis ``TITLE``, RIFF ``INAM``,
                   AIFF ``NAME``, CAF ``title``, APEv2, M4A/Matroska ``title``
- ``lyrics``       Songtext: ID3 ``USLT``, Vorbis ``LYRICS``/``UNSYNCEDLYRICS``,
                   APEv2 ``Lyrics``, M4A ``©lyr`` (ffprobe: ``lyrics``)
- ``bpm``, ``key`` ID3 ``TBPM``/``TKEY``, Vorbis ``BPM``/``KEY``/``INITIALKEY``
- ``audio_codec``, ``sample_rate``, ``channels``, ``bit_depth`` — erste
                   Tonspur, wie ffprobe sie nennt (``flac``, ``48000``, ``2``,
                   ``24``); ``bit_depth`` nur bei verlustfreien Formaten
- ``creator_tool`` eigene Aufnahmen: Logic-Pro-Bounce (RIFF-Chunk ``LGWV``,
                   ``bext``-Originator), Sprachmemos (M4A ``©too``)
- Musiksammlung (#224, ADR 0094): ``artist`` (ID3 ``TPE1``, Vorbis
                   ``ARTIST``, RIFF ``IART``), ``album_artist`` (``TPE2``,
                   ``ALBUMARTIST``), ``album`` (``TALB``, ``ALBUM``, RIFF
                   ``IPRD``), ``track``/``disc`` (nur die Nummer: ``3/12`` → 3),
                   ``year`` (vier Ziffern aus ``TDRC``/``TYER``/``DATE``/
                   ``©day``), ``genre`` (``TCON``; ID3v1-Nummern und die
                   ``(17)``-Schreibweise als Namen). ID3v1 füllt nur, was
                   ID3v2 nicht hat.
- Songtext mit Zeiten (#234): ``lyrics_synced`` (JSON ``[[start_ms,
                   end_ms|null, "Zeile"], …]``) und ``song_sections`` (JSON
                   ``[[start_ms, "Chorus"], …]``) aus der Untertitel-Spur
                   (Suno V6, ``…:streamN.subtitle``), sonst ID3 ``SYLT``,
                   sonst LRC im Songtext-Tag. LRC im Tag wird für ``lyrics``
                   von den Zeitstempeln befreit; fehlt ``lyrics``, kommt es
                   aus den getimten Zeilen.

M4A/Matroska-Tags zählen nur ohne echte Videospur — ein MP4-Video mit
``title``-Tag ist kein Song (das Cover einer M4A erscheint in ffprobe als
Bild-„Video"-Spur und zählt nicht).
"""

from __future__ import annotations

import json
import re
from typing import Sequence

from ..extract.types import RawMetadataItem
from . import lyrics_sync
from .types import InterpretedField, Interpretation

NAME = "audio"
VERSION = 4

# ID3-Frame (2.3/2.4 und 2.2) → Feld.
_ID3_FIELDS = {
    "TIT2": "title", "TT2": "title", "USLT": "lyrics", "ULT": "lyrics",
    "TBPM": "bpm", "TBP": "bpm", "TKEY": "key", "TKE": "key",
    "TPE1": "artist", "TP1": "artist", "TPE2": "album_artist", "TP2": "album_artist",
    "TALB": "album", "TAL": "album", "TRCK": "track", "TRK": "track",
    "TPOS": "disc", "TPA": "disc", "TDRC": "year", "TYER": "year", "TYE": "year",
    "TCON": "genre", "TCO": "genre",
}
# Vorbis/APEv2/CAF-Schlüssel (groß) → Feld.
_KEY_FIELDS = {
    "TITLE": "title", "LYRICS": "lyrics", "UNSYNCEDLYRICS": "lyrics",
    "UNSYNCED LYRICS": "lyrics", "BPM": "bpm", "TEMPO": "bpm",
    "KEY": "key", "INITIALKEY": "key", "KEY SIGNATURE": "key",
    "ARTIST": "artist", "ALBUMARTIST": "album_artist", "ALBUM ARTIST": "album_artist",
    "ALBUM_ARTIST": "album_artist", "ALBUM": "album", "TRACKNUMBER": "track",
    "TRACK": "track", "DISCNUMBER": "disc", "DISC": "disc", "DATE": "year",
    "YEAR": "year", "GENRE": "genre",
}
# RIFF-INFO (WAV) → Feld.
_RIFF_FIELDS = {"INAM": "title", "IART": "artist", "IPRD": "album",
                "ITRK": "track", "IPRT": "track", "ICRD": "year", "IGNR": "genre"}
# ffprobe-Tagnamen (M4A/Matroska, klein) → Feld; ffprobe übersetzt die
# iTunes-Atome (©ART, aART, ©alb, trkn, disk, ©day, ©gen) schon in diese Namen.
_PROBE_FIELDS = {"title": "title", "artist": "artist", "album_artist": "album_artist",
                 "album": "album", "track": "track", "disc": "disc", "date": "year",
                 "genre": "genre"}
# ID3v1-Schlüssel (``id3v1``-Einträge des Tag-Walkers) → Feld.
_V1_FIELDS = {"title": "title", "artist": "artist", "album": "album",
              "track": "track", "year": "year", "genre": "genre"}
# Felder mit genau einem Wert (der erste gewinnt) — Interpret und Genre
# dürfen mehrere haben (ID3v2.4-Mehrfachwerte).
_SINGLE = frozenset({"album", "album_artist", "track", "disc", "year"})
# ID3v1-Genre-Nummern (ID3v1-Standard 0–79, Winamp-Erweiterung bis 147);
# ID3v2 ``TCON`` benutzt dieselben Nummern als ``(17)`` oder nackt ``17``.
_GENRES = (
    "Blues", "Classic Rock", "Country", "Dance", "Disco", "Funk", "Grunge", "Hip-Hop",
    "Jazz", "Metal", "New Age", "Oldies", "Other", "Pop", "R&B", "Rap", "Reggae", "Rock",
    "Techno", "Industrial", "Alternative", "Ska", "Death Metal", "Pranks", "Soundtrack",
    "Euro-Techno", "Ambient", "Trip-Hop", "Vocal", "Jazz+Funk", "Fusion", "Trance",
    "Classical", "Instrumental", "Acid", "House", "Game", "Sound Clip", "Gospel", "Noise",
    "AlternRock", "Bass", "Soul", "Punk", "Space", "Meditative", "Instrumental Pop",
    "Instrumental Rock", "Ethnic", "Gothic", "Darkwave", "Techno-Industrial", "Electronic",
    "Pop-Folk", "Eurodance", "Dream", "Southern Rock", "Comedy", "Cult", "Gangsta",
    "Top 40", "Christian Rap", "Pop/Funk", "Jungle", "Native American", "Cabaret",
    "New Wave", "Psychadelic", "Rave", "Showtunes", "Trailer", "Lo-Fi", "Tribal",
    "Acid Punk", "Acid Jazz", "Polka", "Retro", "Musical", "Rock & Roll", "Hard Rock",
    "Folk", "Folk-Rock", "National Folk", "Swing", "Fast Fusion", "Bebob", "Latin",
    "Revival", "Celtic", "Bluegrass", "Avantgarde", "Gothic Rock", "Progressive Rock",
    "Psychedelic Rock", "Symphonic Rock", "Slow Rock", "Big Band", "Chorus",
    "Easy Listening", "Acoustic", "Humour", "Speech", "Chanson", "Opera", "Chamber Music",
    "Sonata", "Symphony", "Booty Bass", "Primus", "Porn Groove", "Satire", "Slow Jam",
    "Club", "Tango", "Samba", "Folklore", "Ballad", "Power Ballad", "Rhythmic Soul",
    "Freestyle", "Duet", "Punk Rock", "Drum Solo", "A capella", "Euro-House",
    "Dance Hall", "Goa", "Drum & Bass", "Club-House", "Hardcore", "Terror", "Indie",
    "BritPop", "Negerpunk", "Polsk Punk", "Beat", "Christian Gangsta Rap", "Heavy Metal",
    "Black Metal", "Crossover", "Contemporary Christian", "Christian Rock", "Merengue",
    "Salsa", "Thrash Metal", "Anime", "JPop", "Synthpop",
)
_GENRE_REF = re.compile(r"^\((\d{1,3})\)(.*)$")
_KEY_SOURCES = ("flac:comment", "ogg:comment", "apev2", "caf:info")
_TAG_SOURCE = re.compile(r"^(?:isobmff|matroska):(?:format|stream\d+)\.tag$")
_STREAM_SOURCE = re.compile(r"^[a-z0-9]+:stream(\d+)$")
_SUBTITLE_SOURCE = re.compile(r"^(?:isobmff|matroska):stream\d+\.subtitle$")
# Bild-Codecs einer „Videospur" = Cover, keine echte Videospur.
_COVER_CODECS = frozenset({"mjpeg", "png", "bmp", "gif", "webp", "tiff"})
# Reihenfolge der Felder in der Ausgabe (stabil für Anzeige/ordinal).
_ORDER = ("title", "artist", "album_artist", "album", "track", "disc", "year", "genre",
          "lyrics", "lyrics_synced", "song_sections", "bpm", "key", "creator_tool",
          "audio_codec", "sample_rate", "channels", "bit_depth")


def parse(items: Sequence[RawMetadataItem]) -> Interpretation | None:
    streams = _streams(items)
    has_video = any(s.get("codec_type") == "video"
                    and s.get("codec_name", "").lower() not in _COVER_CODECS
                    for s in streams.values())
    found: dict[str, list[str]] = {}
    v1: list[tuple[str, str]] = []

    def add(field: str, value: str | None) -> None:
        text = _normalize(field, (value or "").strip().strip("\x00").strip())
        if not text:
            return
        values = found.setdefault(field, [])
        if text not in values and not (field in _SINGLE and values):
            values.append(text)

    for item in items:
        if item.text is None:
            if item.source == "riff:bext" and item.data:
                add("creator_tool", _bext_originator(item.data))
            elif item.source == "riff:LGWV":
                found.setdefault("_logic", ["Logic Pro"])
            continue
        source, key = item.source, (item.keyword or "")
        if source.startswith("id3v2:"):
            field = _ID3_FIELDS.get(source[6:])
            if field:
                add(field, item.text)
        elif source in _KEY_SOURCES:
            field = _KEY_FIELDS.get(key.upper())
            if field:
                add(field, item.text)
        elif source == "riff:INFO" and key in _RIFF_FIELDS:
            add(_RIFF_FIELDS[key], item.text)
        elif source == "aiff:NAME":
            add("title", item.text)
        elif source == "id3v1" and key in _V1_FIELDS:
            v1.append((_V1_FIELDS[key], item.text))
        elif _TAG_SOURCE.match(source) and not has_video:
            low = key.lower()
            if low in _PROBE_FIELDS:
                add(_PROBE_FIELDS[low], item.text)
            elif low == "lyrics" or low.startswith("lyrics-"):
                add("lyrics", item.text)
            elif low == "encoder" and "voicememos" in item.text.lower().replace(" ", ""):
                add("creator_tool", "Voice Memos")

    # ID3v1 (30 Zeichen, Dateiende) nur als Rückfall: was ID3v2 kennt, gewinnt.
    for field, text in v1:
        if field not in found:
            add(field, text)

    # LGWV = „written by Logic Pro" — nur, wenn der bext-Originator Logic
    # nicht schon (mit Version) nennt.
    if "_logic" in found:
        found.pop("_logic")
        if not any("logic" in v.lower() for v in found.get("creator_tool", [])):
            add("creator_tool", "Logic Pro")

    if not has_video:
        _synced(items, found)

    audio = next((s for _, s in sorted(streams.items()) if s.get("codec_type") == "audio"), None)
    if audio is not None and not has_video:
        add("audio_codec", audio.get("codec_name", "").lower())
        add("sample_rate", audio.get("sample_rate"))
        add("channels", audio.get("channels"))
        add("bit_depth", audio.get("bits_per_raw_sample") or audio.get("bits_per_sample"))

    fields = [InterpretedField(f, v) for f in _ORDER for v in found.get(f, [])]
    if not fields:
        return None
    return Interpretation(parser=NAME, parser_version=VERSION, fields=fields)


def _synced(items: Sequence[RawMetadataItem], found: dict[str, list[str]]) -> None:
    """Songtext mit Zeiten (#234) in ``found`` eintragen — Rangfolge
    Untertitel-Spur, ``SYLT``, LRC im Songtext-Tag."""
    lines: list[lyrics_sync.Line] = []
    for item in items:
        if item.text is not None and _SUBTITLE_SOURCE.match(item.source):
            lines = lyrics_sync.parse_srt(item.text)
            if lines:
                break
    if not lines:
        for item in items:
            if item.source == "id3v2:SYLT" and item.data:
                lines = lyrics_sync.parse_sylt(item.data)
                if lines:
                    break
    plain = found.get("lyrics", [])
    for i, text in enumerate(plain):
        lrc = lyrics_sync.parse_lrc(text)
        if lrc:
            lines = lines or lrc
            plain[i] = lyrics_sync.strip_lrc(text)
    if not lines:
        return
    if not plain:
        found["lyrics"] = [lyrics_sync.plain_text(lines)]
    found["lyrics_synced"] = [json.dumps([list(line) for line in lines], ensure_ascii=False,
                                         separators=(",", ":"))]
    marks = lyrics_sync.sections(lines)
    if marks:
        found["song_sections"] = [json.dumps([list(m) for m in marks], ensure_ascii=False,
                                             separators=(",", ":"))]


def _normalize(field: str, text: str) -> str:
    """Tag-Schreibweisen auf den Feldwert bringen: Nummer aus ``3/12``,
    Jahr aus ``1987-05-12``, Genre-Nummer als Name; sonst unverändert."""
    if not text:
        return ""
    if field in ("track", "disc"):
        m = re.match(r"^\s*0*(\d{1,6})", text)   # fremde Tags: Länge gedeckelt
        return m.group(1) if m and int(m.group(1)) > 0 else ""
    if field == "year":
        m = re.match(r"^\s*(\d{4})", text)
        return m.group(1) if m and int(m.group(1)) > 0 else ""
    if field == "genre":
        m = _GENRE_REF.match(text)
        if m:   # "(17)" oder "(17)Rock" — ein Klartext hinter der Nummer gewinnt
            text = m.group(2).strip() or _genre_name(int(m.group(1)))
        elif text.isascii() and text.isdigit() and len(text) <= 3:
            # isascii: "²" zählt für isdigit(), ist für int() aber keine Zahl
            text = _genre_name(int(text))
        return {"RX": "Remix", "CR": "Cover"}.get(text.strip("()"), text)
    return text


def _genre_name(number: int) -> str:
    return _GENRES[number] if number < len(_GENRES) else ""


def tag_year(items: Sequence[RawMetadataItem]) -> int | None:
    """Jahr aus den Musik-Tags (für die Datums-Kaskade, #220) — dasselbe
    ``year``-Feld wie im Parser, oder ``None``."""
    try:
        interp = parse(items)
    except Exception:   # fremde Tags: ein Parserfehler datiert nur nicht
        return None
    for f in interp.fields if interp else ():
        if f.field == "year":
            return int(f.value)
    return None


def _streams(items: Sequence[RawMetadataItem]) -> dict[int, dict[str, str]]:
    """Eckwerte je Stream (``<container>:streamN``, Keyword = ffprobe-Feld)."""
    streams: dict[int, dict[str, str]] = {}
    for item in items:
        m = _STREAM_SOURCE.match(item.source)
        if m and item.keyword and item.text is not None:
            streams.setdefault(int(m.group(1)), {})[item.keyword] = item.text
    return streams


def _bext_originator(data: bytes) -> str | None:
    """``Originator`` des Broadcast-Wave-Chunks (EBU 3285: Bytes 256–287,
    ASCII, mit Nullen aufgefüllt) — das aufnehmende Programm."""
    raw = data[256:288].split(b"\x00", 1)[0]
    text = raw.decode("latin-1").strip()
    return text or None
