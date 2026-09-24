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

M4A/Matroska-Tags zählen nur ohne echte Videospur — ein MP4-Video mit
``title``-Tag ist kein Song (das Cover einer M4A erscheint in ffprobe als
Bild-„Video"-Spur und zählt nicht).
"""

from __future__ import annotations

import re
from typing import Sequence

from ..extract.types import RawMetadataItem
from .types import InterpretedField, Interpretation

NAME = "audio"
VERSION = 1

# ID3-Frame (2.3/2.4 und 2.2) → Feld.
_ID3_FIELDS = {
    "TIT2": "title", "TT2": "title", "USLT": "lyrics", "ULT": "lyrics",
    "TBPM": "bpm", "TBP": "bpm", "TKEY": "key", "TKE": "key",
}
# Vorbis/APEv2/CAF-Schlüssel (groß) → Feld.
_KEY_FIELDS = {
    "TITLE": "title", "LYRICS": "lyrics", "UNSYNCEDLYRICS": "lyrics",
    "UNSYNCED LYRICS": "lyrics", "BPM": "bpm", "TEMPO": "bpm",
    "KEY": "key", "INITIALKEY": "key", "KEY SIGNATURE": "key",
}
_KEY_SOURCES = ("flac:comment", "ogg:comment", "apev2", "caf:info")
_TAG_SOURCE = re.compile(r"^(?:isobmff|matroska):(?:format|stream\d+)\.tag$")
_STREAM_SOURCE = re.compile(r"^[a-z0-9]+:stream(\d+)$")
# Bild-Codecs einer „Videospur" = Cover, keine echte Videospur.
_COVER_CODECS = frozenset({"mjpeg", "png", "bmp", "gif", "webp", "tiff"})
# Reihenfolge der Felder in der Ausgabe (stabil für Anzeige/ordinal).
_ORDER = ("title", "lyrics", "bpm", "key", "creator_tool",
          "audio_codec", "sample_rate", "channels", "bit_depth")


def parse(items: Sequence[RawMetadataItem]) -> Interpretation | None:
    streams = _streams(items)
    has_video = any(s.get("codec_type") == "video"
                    and s.get("codec_name", "").lower() not in _COVER_CODECS
                    for s in streams.values())
    found: dict[str, list[str]] = {}

    def add(field: str, value: str | None) -> None:
        text = (value or "").strip().strip("\x00").strip()
        if text and text not in found.setdefault(field, []):
            found[field].append(text)

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
        elif source == "riff:INFO" and key == "INAM":
            add("title", item.text)
        elif source == "aiff:NAME":
            add("title", item.text)
        elif _TAG_SOURCE.match(source) and not has_video:
            low = key.lower()
            if low == "title":
                add("title", item.text)
            elif low == "lyrics" or low.startswith("lyrics-"):
                add("lyrics", item.text)
            elif low == "encoder" and "voicememos" in item.text.lower().replace(" ", ""):
                add("creator_tool", "Voice Memos")

    # LGWV = „written by Logic Pro" — nur, wenn der bext-Originator Logic
    # nicht schon (mit Version) nennt.
    if "_logic" in found:
        found.pop("_logic")
        if not any("logic" in v.lower() for v in found.get("creator_tool", [])):
            add("creator_tool", "Logic Pro")

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
