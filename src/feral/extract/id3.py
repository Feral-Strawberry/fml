"""Tag-Walker für ID3v2, ID3v1 und APEv2 (Schicht 1, reine Standardbibliothek).

Diese drei Tag-Formate hängen nicht an EINEM Container: ID3v2 steht vor MP3
und vor FLAC (dort trägt es C2PA), als ``id3 ``-Chunk in WAV und AIFF;
ID3v1 und APEv2 stehen am Dateiende. Darum ein eigenes Modul, das
``audio.py`` für jeden Container benutzt (ADR 0083, Recherche §8).

Grundsätze wie beim PNG (ADR 0004/0008): jeder Frame wird ein
``RawMetadataItem`` mit Quell-Label, Reihenfolge und doppelte Frames
bleiben erhalten, interpretiert wird nichts. Beschriftung:

- ``id3v2:<FrameID>`` — die Frame-ID so, wie sie in der Datei steht (2.2
  hat dreistellige IDs: ``TT2``, ``TXX``, ``COM``, ``PIC`` …).
- ``keyword``: die Beschreibung bei ``TXXX``/``WXXX``/``GEOB``-artigen
  Frames (ComfyUI schreibt ``TXXX:prompt``), ``<sprache>:<beschreibung>``
  bei ``COMM``/``USLT``, der Besitzer bei ``PRIV``; sonst ``None``.
- Textwerte werden so dekodiert, dass ``text.encode(encoding)`` die Bytes
  des Werts exakt wiederherstellt (Roh-Blob-Garantie). ID3v2.4-Mehrfachwerte
  (``\\0``-getrennt) werden je ein Eintrag.
- **Bilder** (``APIC``/``PIC``, APEv2 ``Cover Art``) nur als Deskriptor
  (MIME, Typ, Größe, SHA-256) — die Bytes liegen in der Datei.
- Alles andere Binäre (``GEOB``, ``PRIV``, ``UFID``, ``POPM`` …) byte-treu.

Defensiv: Kaputtes wird Warnung, nie Ausnahme.
"""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from typing import BinaryIO

from .types import RawMetadataItem

# Deckel für einen einzelnen Tag bzw. entpackten Frame (Schutz vor absurden
# Längen und zlib-Bomben, vgl. png._MAX_DECOMPRESSED). ID3v2 kann höchstens
# 256 MiB groß sein (28 Bit syncsafe); echte Tags sind Kilobytes bis wenige MB.
MAX_TAG = 64 * 1024 * 1024

_TEXT_ENCODINGS = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}

# Frames mit Bild-Nutzlast → nur Deskriptor.
_PICTURE_FRAMES = frozenset({"APIC", "PIC"})
# Kommentar-artige Frames: enc | sprache[3] | beschreibung \0 | text.
_LANG_FRAMES = frozenset({"COMM", "COM", "USLT", "ULT"})
# Benutzer-Text/-URL: enc | beschreibung \0 | wert.
_USER_TEXT = frozenset({"TXXX", "TXX"})
_USER_URL = frozenset({"WXXX", "WXX"})


def picture_descriptor(mime: str, pic_type: int | None, desc: str,
                       data: bytes) -> str:
    """Deskriptor eines eingebetteten Bilds (ADR 0083): JSON mit MIME, Typ,
    Beschreibung, Größe und SHA-256 — die Bildbytes selbst bleiben in der
    Datei (kein Blob-Ballast in der DB, Cover sind ohnehin informationsarm)."""
    return json.dumps({
        "mime": mime, "type": pic_type, "description": desc,
        "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
    }, ensure_ascii=False)


def _syncsafe(b: bytes) -> int:
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def _unsync(data: bytes) -> bytes:
    """Unsynchronisation rückgängig machen: ``FF 00`` → ``FF``."""
    return data.replace(b"\xff\x00", b"\xff")


def _is_frame_id(fid: bytes) -> bool:
    return len(fid) in (3, 4) and all(0x30 <= c <= 0x39 or 0x41 <= c <= 0x5A for c in fid)


# -- Text-Dekodierung --------------------------------------------------------

def _split_terminated(data: bytes, enc: int) -> tuple[bytes, bytes]:
    """Trenne ``data`` am ersten Terminator der Kodierung (``\\0`` bzw.
    ausgerichtetes ``\\0\\0`` bei UTF-16). Ohne Terminator: alles, Rest leer."""
    if enc in (1, 2):
        i = 0
        while i + 1 < len(data):
            if data[i] == 0 and data[i + 1] == 0:
                return data[:i], data[i + 2:]
            i += 2
        return data, b""
    i = data.find(b"\x00")
    return (data, b"") if i < 0 else (data[:i], data[i + 1:])


def _decode(raw: bytes, enc: int) -> tuple[str, str] | None:
    """Bytes eines ID3-Werts → (Text, Codec), sodass ``text.encode(codec)``
    die Bytes OHNE BOM exakt zurückgibt; BOM wird zum Codec-Namen. ``None``,
    wenn die Bytes nicht zur Kodierung passen (→ binär sichern)."""
    codec = _TEXT_ENCODINGS.get(enc)
    if codec is None:
        return None
    if codec == "utf-16":
        if raw[:2] == b"\xff\xfe":
            raw, codec = raw[2:], "utf-16-le"
        elif raw[:2] == b"\xfe\xff":
            raw, codec = raw[2:], "utf-16-be"
        else:
            codec = "utf-16-le"   # ohne BOM: in freier Wildbahn fast immer LE
    try:
        text = raw.decode(codec)
    except UnicodeDecodeError:
        return None
    if text.encode(codec) != raw:
        return None
    return text, codec


def _text_values(payload: bytes, enc: int) -> list[bytes]:
    """Werte eines Textframes: am Terminator getrennt (2.4-Mehrfachwerte),
    ein abschließender Terminator erzeugt keinen leeren Zusatzwert."""
    values: list[bytes] = []
    rest = payload
    while True:
        value, rest = _split_terminated(rest, enc)
        values.append(value)
        if not rest or not rest.strip(b"\x00"):
            break
    return values


def _text_item(source: str, keyword: str | None, raw: bytes, enc: int) -> RawMetadataItem:
    decoded = _decode(raw, enc)
    if decoded is None:
        return RawMetadataItem(source=source, keyword=keyword, text=None,
                               data=raw, encoding="binary")
    text, codec = decoded
    return RawMetadataItem(source=source, keyword=keyword, text=text,
                           data=None, encoding=codec)


def _latin1(raw: bytes) -> str:
    return raw.decode("latin-1")


# -- ID3v2 -------------------------------------------------------------------

def id3v2_size(head: bytes) -> int | None:
    """Gesamtgröße (Kopf + Rumpf + evtl. Fuß) eines ID3v2-Tags ab ``head``
    (mind. 10 Bytes) oder ``None``, wenn dort kein gültiger Kopf steht."""
    if len(head) < 10 or head[:3] != b"ID3" or head[3] == 0xFF or head[4] == 0xFF:
        return None
    if any(b & 0x80 for b in head[6:10]):
        return None
    size = 10 + _syncsafe(head[6:10])
    if head[5] & 0x10:   # Fuß (nur 2.4)
        size += 10
    return size


def read_id3v2_tags(fh: BinaryIO, offset: int, warnings: list[str]) -> tuple[list[RawMetadataItem], int]:
    """Lies ID3v2-Tags ab ``offset`` — auch mehrere hintereinander
    (fehlerhafte Tagger stapeln Tags). Gibt (Einträge, Ende-Offset) zurück;
    ohne Tag an ``offset`` ist die Liste leer und das Ende = ``offset``."""
    items: list[RawMetadataItem] = []
    pos = offset
    while True:
        fh.seek(pos)
        head = fh.read(10)
        size = id3v2_size(head)
        if size is None:
            return items, pos
        if size > MAX_TAG:
            warnings.append(f"ID3v2 tag too large ({size} bytes) — skipped.")
            return items, pos + size
        body = fh.read(size - 10)
        if len(body) < size - 10:
            warnings.append("File ends inside the ID3v2 tag (truncated?).")
        items.extend(parse_id3v2(head + body, warnings))
        pos += size


def parse_id3v2(tag: bytes, warnings: list[str]) -> list[RawMetadataItem]:
    """Ein vollständiger ID3v2-Tag (Kopf + Rumpf) → Roh-Einträge.

    Versionen 2.2/2.3/2.4, Unsynchronisation (2.3 ganzer Tag, 2.4 je Frame),
    erweiterter Kopf, Frame-Flags (zlib, Datenlänge, Gruppe, Verschlüsselung)
    und die nicht-syncsafen Framegrößen alter iTunes-Versionen in 2.4.
    """
    if len(tag) < 10 or tag[:3] != b"ID3":
        return []
    major, flags = tag[3], tag[5]
    if major not in (2, 3, 4):
        warnings.append(f"Unknown ID3v2 version 2.{major} — tag kept unread.")
        return []
    body = tag[10:10 + _syncsafe(tag[6:10])]
    if flags & 0x80 and major < 4:
        body = _unsync(body)
    pos = 0
    if flags & 0x40 and major >= 3:   # erweiterter Kopf
        if len(body) < 4:
            warnings.append("ID3v2 extended header truncated.")
            return []
        if major == 3:
            pos = 4 + struct.unpack(">I", body[:4])[0]
        else:
            pos = _syncsafe(body[:4])
        if pos > len(body):
            warnings.append("ID3v2 extended header larger than the tag.")
            return []

    items: list[RawMetadataItem] = []
    id_len, head_len = (3, 6) if major == 2 else (4, 10)
    while pos + head_len <= len(body):
        fid_raw = body[pos:pos + id_len]
        if fid_raw[0] == 0:
            break   # Padding
        if not _is_frame_id(fid_raw):
            warnings.append(f"ID3v2: invalid frame ID at offset {pos} — rest of tag skipped.")
            break
        fid = fid_raw.decode("ascii")
        if major == 2:
            fsize = int.from_bytes(body[pos + 3:pos + 6], "big")
            fflags = 0
        else:
            size_bytes = body[pos + 4:pos + 8]
            fflags = struct.unpack(">H", body[pos + 8:pos + 10])[0]
            fsize = (_syncsafe(size_bytes) if major == 4
                     else struct.unpack(">I", size_bytes)[0])
            if major == 4:
                fsize = _itunes_size(body, pos, fsize, size_bytes)
        start = pos + head_len
        payload = body[start:start + fsize]
        if len(payload) < fsize:
            warnings.append(f"ID3v2 frame {fid} truncated.")
        pos = start + fsize
        payload = _frame_payload(fid, payload, fflags, major, warnings)
        if payload is None:
            continue
        items.extend(_frame_items(fid, payload, warnings))
    return items


def _itunes_size(body: bytes, pos: int, fsize: int, size_bytes: bytes) -> int:
    """iTunes schrieb 2.4-Tags mit nicht-syncsafen Größen (Recherche §8):
    passt hinter der syncsafe gelesenen Größe keine Frame-ID, aber hinter der
    Big-Endian-Größe schon, gilt die Big-Endian-Lesart."""
    plain = struct.unpack(">I", size_bytes)[0]
    if plain == fsize:
        return fsize

    def plausible(size: int) -> bool:
        nxt = pos + 10 + size
        if nxt == len(body) or (nxt < len(body) and body[nxt] == 0):
            return True
        return nxt + 4 <= len(body) and _is_frame_id(body[nxt:nxt + 4])

    if not plausible(fsize) and plausible(plain):
        return plain
    return fsize


def _frame_payload(fid: str, payload: bytes, fflags: int, major: int,
                   warnings: list[str]) -> bytes | None:
    """Frame-Flags anwenden → Nutzlast (``None`` = nicht lesbar, schon gewarnt)."""
    if major == 3:
        compressed, encrypted, grouped = fflags & 0x80, fflags & 0x40, fflags & 0x20
        if encrypted:
            return payload          # verschlüsselt: byte-treu weiterreichen
        if grouped:
            payload = payload[1:]
        if compressed:
            payload = payload[4:]   # Originalgröße (u32) vor den zlib-Daten
    elif major == 4:
        grouped, compressed = fflags & 0x40, fflags & 0x08
        encrypted, unsync, datalen = fflags & 0x04, fflags & 0x02, fflags & 0x01
        if grouped:
            payload = payload[1:]
        if encrypted:
            return payload
        if datalen:
            payload = payload[4:]
        if unsync:
            payload = _unsync(payload)
    else:
        compressed = 0
    if compressed:
        dec = zlib.decompressobj()
        try:
            out = dec.decompress(payload, MAX_TAG)
        except zlib.error as exc:
            warnings.append(f"ID3v2 frame {fid}: zlib error ({exc}).")
            return None
        if dec.unconsumed_tail:
            warnings.append(f"ID3v2 frame {fid}: decompressed size above limit — skipped.")
            return None
        payload = out
    return payload


def _frame_items(fid: str, p: bytes, warnings: list[str]) -> list[RawMetadataItem]:
    source = f"id3v2:{fid}"
    if not p:
        return []
    enc = p[0]
    if fid in _USER_TEXT and enc in _TEXT_ENCODINGS:
        desc, rest = _split_terminated(p[1:], enc)
        dtext = _decode(desc, enc)
        key = dtext[0] if dtext else _latin1(desc)
        return [_text_item(source, key, v, enc) for v in _text_values(rest, enc)]
    if fid in _USER_URL and enc in _TEXT_ENCODINGS:
        desc, url = _split_terminated(p[1:], enc)
        dtext = _decode(desc, enc)
        return [RawMetadataItem(source=source, keyword=dtext[0] if dtext else _latin1(desc),
                                text=_latin1(url.rstrip(b"\x00")), data=None, encoding="latin-1")]
    if fid in _LANG_FRAMES and enc in _TEXT_ENCODINGS and len(p) >= 4:
        lang = _latin1(p[1:4])
        desc, text = _split_terminated(p[4:], enc)
        dtext = _decode(desc, enc)
        key = f"{lang}:{dtext[0] if dtext else _latin1(desc)}"
        return [_text_item(source, key, _text_values(text, enc)[0] if text else b"", enc)]
    if fid in _PICTURE_FRAMES and enc in _TEXT_ENCODINGS:
        if fid == "PIC":   # 2.2: Bildformat als 3 Zeichen statt MIME
            mime, rest = _latin1(p[1:4]), p[4:]
        else:
            mime_raw, rest = _split_terminated(p[1:], 0)
            mime = _latin1(mime_raw)
        pic_type = rest[0] if rest else None
        desc, data = _split_terminated(rest[1:], enc)
        dtext = _decode(desc, enc)
        dstr = dtext[0] if dtext else _latin1(desc)
        return [RawMetadataItem(source=source, keyword=dstr or None,
                                text=picture_descriptor(mime, pic_type, dstr, data),
                                data=None, encoding="utf-8")]
    if fid == "PRIV":
        owner, data = _split_terminated(p, 0)
        return [RawMetadataItem(source=source, keyword=_latin1(owner), text=None,
                                data=data, encoding="binary")]
    if fid in ("GEOB", "GEO") and enc in _TEXT_ENCODINGS:
        # Byte-treu (C2PA steckt hier, Recherche §7); das MIME als keyword,
        # damit Schicht 2 den Manifest-Store ohne Umparsen findet.
        mime, _rest = _split_terminated(p[1:], 0)
        return [RawMetadataItem(source=source, keyword=_latin1(mime), text=None,
                                data=p, encoding="binary")]
    if fid[0] == "T" and enc in _TEXT_ENCODINGS:
        return [_text_item(source, None, v, enc) for v in _text_values(p[1:], enc)]
    if fid[0] == "W":
        return [RawMetadataItem(source=source, keyword=None,
                                text=_latin1(p.rstrip(b"\x00")), data=None, encoding="latin-1")]
    return [RawMetadataItem(source=source, keyword=None, text=None, data=p, encoding="binary")]


# -- ID3v1 und APEv2 (Dateiende) ---------------------------------------------

_V1_FIELDS = (("title", 3, 33), ("artist", 33, 63), ("album", 63, 93), ("year", 93, 97))


def parse_id3v1(block: bytes) -> list[RawMetadataItem]:
    """Die letzten 128 Bytes (``TAG`` …) → Einträge ``id3v1`` je Feld.
    Füllbytes (``\\0``/Leerzeichen am Ende) sind Format, keine Daten."""
    if len(block) != 128 or block[:3] != b"TAG":
        return []
    items: list[RawMetadataItem] = []

    def add(key: str, raw: bytes) -> None:
        raw = raw.split(b"\x00", 1)[0].rstrip(b" ")
        if raw:
            items.append(RawMetadataItem(source="id3v1", keyword=key, text=_latin1(raw),
                                         data=None, encoding="latin-1"))

    for key, a, b in _V1_FIELDS:
        add(key, block[a:b])
    if block[125] == 0 and block[126] != 0:   # ID3v1.1: Tracknummer
        add("comment", block[97:125])
        items.append(RawMetadataItem(source="id3v1", keyword="track", text=str(block[126]),
                                     data=None, encoding="latin-1"))
    else:
        add("comment", block[97:127])
    if block[127] != 0xFF:
        items.append(RawMetadataItem(source="id3v1", keyword="genre", text=str(block[127]),
                                     data=None, encoding="latin-1"))
    return items


def parse_apev2_items(body: bytes, count: int, warnings: list[str]) -> list[RawMetadataItem]:
    """APEv2-Items (ohne Kopf/Fuß) → Einträge ``apev2``."""
    items: list[RawMetadataItem] = []
    pos = 0
    for _ in range(count):
        if pos + 8 > len(body):
            warnings.append("APEv2 tag truncated.")
            break
        size, flags = struct.unpack("<II", body[pos:pos + 8])
        end = body.find(b"\x00", pos + 8)
        if end < 0:
            warnings.append("APEv2 item key without terminator.")
            break
        key = _latin1(body[pos + 8:end])
        value = body[end + 1:end + 1 + size]
        pos = end + 1 + size
        kind = (flags >> 1) & 0x3
        if kind == 1 and key.lower().startswith("cover art"):
            # Binär: Dateiname \0 Bilddaten → Deskriptor wie APIC.
            name, data = _split_terminated(value, 0)
            items.append(RawMetadataItem(
                source="apev2", keyword=key,
                text=picture_descriptor("", None, _latin1(name), data),
                data=None, encoding="utf-8"))
        elif kind != 1:
            items.append(_text_item("apev2", key, value, 3))
        else:
            items.append(RawMetadataItem(source="apev2", keyword=key, text=None,
                                         data=value, encoding="binary"))
    return items


def read_tail_tags(fh: BinaryIO, end: int, warnings: list[str]) -> list[RawMetadataItem]:
    """ID3v1 und APEv2 am Dateiende (APEv2 steht vor einem evtl. ID3v1).
    ``end`` = Dateigröße. Reihenfolge der Einträge: APEv2, dann ID3v1."""
    items: list[RawMetadataItem] = []
    v1: list[RawMetadataItem] = []
    tail_end = end
    if end >= 128:
        fh.seek(end - 128)
        block = fh.read(128)
        if block[:3] == b"TAG":
            v1 = parse_id3v1(block)
            tail_end = end - 128
    if tail_end >= 32:
        fh.seek(tail_end - 32)
        foot = fh.read(32)
        if foot[:8] == b"APETAGEX":
            size, count = struct.unpack("<II", foot[12:20])
            if 32 <= size <= min(MAX_TAG, tail_end):
                fh.seek(tail_end - size)
                body = fh.read(size - 32)
                items.extend(parse_apev2_items(body, count, warnings))
            else:
                warnings.append("APEv2 footer with implausible size — skipped.")
    return items + v1
