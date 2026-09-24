"""Audio-Container-Extraktor (Schicht 1, Standardbibliothek + ffprobe-Fakten).

Stdlib-Walker wie beim PNG (ADR 0008, ADR 0083): ffprobe verliert doppelte
Schlüssel, Mehrfachwerte, ``GEOB`` (C2PA), Bilder und Zusatz-Chunks
(Recherche §9). Darum liest dieses Modul die Struktur selbst und legt jeden
Frame/Chunk roh mit Quell-Label ab; ffprobe liefert NUR die technischen
Fakten (Dauer, Codec, Samplerate, Kanäle, Bittiefe, Bitrate) über
``video_ffprobe.probe``.

Container (Namen wie ``sniff_container`` sie vergibt):

- ``mp3``  — ID3v2 (auch gestapelt) + MPEG-Frames + APEv2/ID3v1 am Ende
- ``flac`` — evtl. ID3v2 davor (C2PA!), Metadatenblöcke (RFC 9639)
- ``ogg``  — Opus/Vorbis/FLAC; Kommentarpaket über Ogg-Seiten (RFC 3533)
- ``wav``  — RIFF WAVE/RF64/BW64; Chunks auch nach ``data``, Pad-Byte, ``ds64``
- ``aiff`` — AIFF/AIFC (big endian)
- ``caf``  — Core Audio Format (Logic-Bounce), ``info``-Chunk

Beschriftung: ``flac:<BLOCK>``, ``ogg:comment``, ``riff:<chunk>``,
``riff:INFO`` (keyword = INFO-ID), ``aiff:<chunk>``, ``caf:info``; Vorbis-
Kommentare mit dem Schlüssel in Originalschreibweise als keyword. Bilder
nur als Deskriptor (``id3.picture_descriptor``). Defensiv: Warnungen statt
Ausnahmen.
"""

from __future__ import annotations

import base64
import binascii
import struct
from pathlib import Path
from typing import BinaryIO

from . import id3
from .types import ContainerExtraction, RawMetadataItem

CONTAINERS = ("mp3", "flac", "ogg", "wav", "aiff", "caf")

# Deckel für einzeln eingelesene Blöcke/Chunks/Pakete (FLAC-Blöcke sind
# höchstens 16 MiB; ein ComfyUI-Workflow im Opus-Kommentar ~0,4 MiB).
_MAX_BLOCK = id3.MAX_TAG

# Chunks, die Audiodaten oder reine Technik tragen — Technik kommt aus
# ffprobe, Füller sind Format. Alles andere wird roh gesichert.
_RIFF_SKIP = frozenset({b"fmt ", b"data", b"fact", b"ds64", b"JUNK", b"junk",
                        b"PAD ", b"FLLR", b"pad "})
_AIFF_SKIP = frozenset({b"COMM", b"SSND", b"FVER"})
_AIFF_TEXT = frozenset({b"NAME", b"AUTH", b"(c) ", b"ANNO"})
_CAF_SKIP = frozenset({b"desc", b"data", b"pakt", b"kuki", b"chan", b"free"})


# -- Erkennung ---------------------------------------------------------------

def _mpeg_frame_ok(h: bytes) -> bool:
    """MPEG-Audio-Framekopf (Layer I–III) plausibel?"""
    if len(h) < 4 or h[0] != 0xFF or (h[1] & 0xE0) != 0xE0:
        return False
    version, layer = (h[1] >> 3) & 0x3, (h[1] >> 1) & 0x3
    bitrate, rate = h[2] >> 4, (h[2] >> 2) & 0x3
    return version != 1 and layer != 0 and bitrate not in (0, 15) and rate != 3


# Bitraten (kbit/s) je (MPEG-1?, Layer) und Abtastraten je Version — für die
# Framelänge der Ketten-Prüfung. Version-Bits: 3 = MPEG-1, 2 = MPEG-2,
# 0 = MPEG-2.5; Layer-Bits: 3 = I, 2 = II, 1 = III.
_BITRATES = {
    (True, 3): (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
    (True, 2): (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
    (True, 1): (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    (False, 3): (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
    (False, 2): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    (False, 1): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
_SAMPLE_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def _frame_length(h: bytes) -> int:
    """Länge des MPEG-Audio-Frames ab diesem (plausiblen) Kopf in Bytes."""
    version, layer = (h[1] >> 3) & 0x3, (h[1] >> 1) & 0x3
    bitrate = _BITRATES[(version == 3, layer)][h[2] >> 4] * 1000
    rate = _SAMPLE_RATES[version][(h[2] >> 2) & 0x3]
    pad = (h[2] >> 1) & 0x1
    if layer == 3:
        return (12 * bitrate // rate + pad) * 4
    if layer == 1 and version != 3:
        return 72 * bitrate // rate + pad
    return 144 * bitrate // rate + pad


# Wie viele aufeinanderfolgende Frames ein nacktes MPEG-Audio belegen muss.
# Ein einzelner Kopf ist zu schwach: der UTF-16-BOM ``FF FE`` gefolgt von
# einem Textzeichen IST ein gültiger MPEG-1-Layer-I-Kopf — Windows-
# Sprachdateien (.lang) liefen so als MP3 in den Katalog (#159).
_CHAIN = 3


def _frame_chain(data: bytes, i: int) -> bool:
    """Stehen ab ``i`` ``_CHAIN`` gleichartige Frames hintereinander? Endet
    ``data`` (kleine Datei) vorher, genügt ein belegter Folge-Frame."""
    head = data[i:i + 4]
    if not _mpeg_frame_ok(head):
        return False
    seen = 1
    pos = i
    while seen < _CHAIN:
        pos += _frame_length(data[pos:pos + 4])
        nxt = data[pos:pos + 4]
        if len(nxt) < 4:
            return seen >= 2
        # Gleiche Version, gleicher Layer, gleiche Abtastrate wie der erste.
        if (not _mpeg_frame_ok(nxt) or (nxt[1] & 0xFE) != (head[1] & 0xFE)
                or (nxt[2] & 0x0C) != (head[2] & 0x0C)):
            return False
        seen += 1
    return True


def sniff(head: bytes) -> str | None:
    """Audio-Container aus den ersten Bytes (vorläufig bei ``ID3``: dahinter
    kann auch FLAC stehen — ``refine`` klärt das)."""
    if head[:3] == b"ID3":
        return "mp3"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] in (b"RIFF", b"RF64", b"BW64") and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    if head[:4] == b"caff":
        return "caf"
    if _mpeg_frame_ok(head[:4]):
        return "mp3"
    return None


def refine(path: str | Path, container: str) -> str | None:
    """Vorläufiges ``mp3`` prüfen: hinter ID3v2-Tags steht ``fLaC`` (→
    ``flac``) oder eine Kette von MPEG-Frames (→ ``mp3``, ``_frame_chain``);
    sonst ``None`` (unbekannt). Andere Container bleiben, wie sie sind."""
    if container != "mp3":
        return container
    with open(path, "rb") as fh:
        _items, pos = id3.read_id3v2_tags(fh, 0, [])
        fh.seek(pos)
        window = fh.read(64 * 1024)
    if window[:4] == b"fLaC":
        return "flac"
    for i in range(len(window) - 3):
        if window[i] == 0xFF and _frame_chain(window, i):
            return "mp3"
    return None


# -- Einstieg ----------------------------------------------------------------

def extract(source: str | Path, *, container: str) -> ContainerExtraction:
    """Roh-Metadaten (Walker) + technische Fakten (ffprobe) einer Audiodatei."""
    from . import video_ffprobe   # Lazy: Zyklus video_ffprobe → audio vermeiden

    result = ContainerExtraction(container=container, media_kind="audio")
    path = Path(source)
    try:
        with open(path, "rb") as fh:
            size = fh.seek(0, 2)
            fh.seek(0)
            _WALKERS[container](fh, size, result)
    except OSError as exc:
        result.warnings.append(f"Read error: {exc}")
    except Exception as exc:   # defensiv: Walker-Fehler nie als Absturz
        result.warnings.append(f"{container} walker failed: {exc!r}")
    video_ffprobe.add_technical_facts(path, result)
    return result


def _item(source: str, keyword: str | None, *, text: str | None = None,
          data: bytes | None = None, encoding: str = "utf-8") -> RawMetadataItem:
    if text is None:
        encoding = "binary"
    return RawMetadataItem(source=source, keyword=keyword, text=text, data=data,
                           encoding=encoding)


def _text_or_data(source: str, keyword: str | None, raw: bytes,
                  fallback: str | None = None) -> RawMetadataItem:
    """UTF-8, sonst ``fallback``-Codec (umkehrbar), sonst binär."""
    for codec in ("utf-8", fallback):
        if codec is None:
            continue
        try:
            text = raw.decode(codec)
        except UnicodeDecodeError:
            continue
        if text.encode(codec) == raw:
            return _item(source, keyword, text=text, encoding=codec)
    return _item(source, keyword, data=raw)


# -- MP3 ---------------------------------------------------------------------

def _walk_mp3(fh: BinaryIO, size: int, result: ContainerExtraction) -> None:
    items, _pos = id3.read_id3v2_tags(fh, 0, result.warnings)
    result.items.extend(items)
    result.items.extend(id3.read_tail_tags(fh, size, result.warnings))


# -- FLAC --------------------------------------------------------------------

def _walk_flac(fh: BinaryIO, size: int, result: ContainerExtraction) -> None:
    # ID3v2 vor fLaC überspringen, aber behalten (C2PA, Recherche §7).
    items, pos = id3.read_id3v2_tags(fh, 0, result.warnings)
    result.items.extend(items)
    fh.seek(pos)
    if fh.read(4) != b"fLaC":
        result.warnings.append("No 'fLaC' signature after the ID3 tags.")
        return
    while True:
        head = fh.read(4)
        if len(head) < 4:
            result.warnings.append("File ends inside the FLAC metadata (truncated?).")
            return
        last, btype = head[0] & 0x80, head[0] & 0x7F
        length = int.from_bytes(head[1:4], "big")
        if btype in (0, 1, 3):   # STREAMINFO (→ ffprobe), PADDING, SEEKTABLE
            fh.seek(length, 1)
        else:
            block = fh.read(length)
            if len(block) < length:
                result.warnings.append("FLAC metadata block truncated.")
                return
            result.items.extend(_flac_block(btype, block, "flac", result.warnings))
        if last:
            return


def _flac_block(btype: int, block: bytes, prefix: str, warnings: list[str]) -> list[RawMetadataItem]:
    if btype == 4:
        return _vorbis_comment(block, prefix, warnings)
    if btype == 6:
        item = _flac_picture(block, f"{prefix}:PICTURE", None, warnings)
        return [item] if item else []
    if btype == 2:
        return [_item(f"{prefix}:APPLICATION", block[:4].decode("latin-1"), data=block[4:])]
    if btype == 5:
        return [_item(f"{prefix}:CUESHEET", None, data=block)]
    return [_item(f"{prefix}:block{btype}", None, data=block)]


def _flac_picture(block: bytes, source: str, keyword: str | None,
                  warnings: list[str]) -> RawMetadataItem | None:
    """FLAC-PICTURE (auch Base64 in METADATA_BLOCK_PICTURE) → Deskriptor."""
    try:
        pic_type, mlen = struct.unpack(">II", block[:8])
        mime = block[8:8 + mlen].decode("latin-1")
        p = 8 + mlen
        (dlen,) = struct.unpack(">I", block[p:p + 4])
        desc = block[p + 4:p + 4 + dlen].decode("utf-8", errors="replace")
        p += 4 + dlen + 16   # Breite, Höhe, Farbtiefe, Palette
        (plen,) = struct.unpack(">I", block[p:p + 4])
        data = block[p + 4:p + 4 + plen]
    except (struct.error, IndexError):
        warnings.append("Malformed FLAC PICTURE block.")
        return None
    return _item(source, keyword,
                 text=id3.picture_descriptor(mime, pic_type, desc, data))


def _vorbis_comment(block: bytes, prefix: str, warnings: list[str]) -> list[RawMetadataItem]:
    """Vorbis-Kommentar (little endian): Vendor + ``KEY=wert``-Einträge.
    Doppelte Schlüssel und Reihenfolge bleiben erhalten (ffprobe verkettet
    sie mit ``;``); der Schlüssel behält seine Schreibweise."""
    items: list[RawMetadataItem] = []
    try:
        (vlen,) = struct.unpack("<I", block[:4])
        vendor = block[4:4 + vlen]
        items.append(_text_or_data(f"{prefix}:vendor", None, vendor))
        pos = 4 + vlen
        (count,) = struct.unpack("<I", block[pos:pos + 4])
        pos += 4
        for _ in range(count):
            (elen,) = struct.unpack("<I", block[pos:pos + 4])
            entry = block[pos + 4:pos + 4 + elen]
            if len(entry) < elen:
                warnings.append("Vorbis comment truncated.")
                break
            pos += 4 + elen
            key_raw, sep, value = entry.partition(b"=")
            key = key_raw.decode("latin-1") if sep else None
            if not sep:
                value = entry
            if key is not None and key.upper() == "METADATA_BLOCK_PICTURE":
                try:
                    pic = base64.b64decode(value, validate=False)
                except (binascii.Error, ValueError):
                    pic = b""
                item = _flac_picture(pic, f"{prefix}:comment", key, warnings)
                if item:
                    items.append(item)
                continue
            items.append(_text_or_data(f"{prefix}:comment", key, value))
    except struct.error:
        warnings.append("Vorbis comment truncated.")
        return items
    if pos < len(block) and block[pos:].strip(b"\x00\x01"):
        # OpusTags erlaubt Binärdaten hinter den Kommentaren — byte-treu.
        items.append(_item(f"{prefix}:comment_tail", None, data=block[pos:]))
    return items


# -- Ogg ---------------------------------------------------------------------

def _ogg_packets(fh: BinaryIO, warnings: list[str], wanted: int = 2):
    """Die ersten ``wanted`` Pakete des ersten logischen Streams (einer
    Serial folgen, Pakete über Seitengrenzen zusammensetzen)."""
    packets: list[bytes] = []
    current = bytearray()
    serial = None
    while len(packets) < wanted:
        head = fh.read(27)
        if len(head) < 27 or head[:4] != b"OggS":
            if len(head) >= 4:
                warnings.append("Ogg page sync lost.")
            break
        page_serial = struct.unpack("<I", head[14:18])[0]
        nseg = head[26]
        lacing = fh.read(nseg)
        body = fh.read(sum(lacing))
        if serial is None:
            serial = page_serial
        if page_serial != serial:
            continue
        pos = 0
        for lace in lacing:
            current += body[pos:pos + lace]
            pos += lace
            if len(current) > _MAX_BLOCK:
                warnings.append("Ogg header packet above limit — skipped.")
                return packets
            if lace < 255:
                packets.append(bytes(current))
                current = bytearray()
                if len(packets) >= wanted:
                    break
    return packets


def _walk_ogg(fh: BinaryIO, size: int, result: ContainerExtraction) -> None:
    packets = _ogg_packets(fh, result.warnings)
    if len(packets) < 2:
        result.warnings.append("Ogg stream without a comment packet.")
        return
    ident, comment = packets
    if ident.startswith(b"OpusHead") and comment.startswith(b"OpusTags"):
        body = comment[8:]
    elif ident.startswith(b"\x01vorbis") and comment.startswith(b"\x03vorbis"):
        body = comment[7:]
        # Framing-Bit am Ende ist Format, keine Nutzlast.
        if body.endswith(b"\x01"):
            body = body[:-1]
    elif ident.startswith(b"\x7fFLAC") and comment and comment[0] & 0x7F == 4:
        body = comment[4:]
    elif ident.startswith(b"Speex   "):
        body = comment
    else:
        result.warnings.append("Ogg stream with an unknown codec — no tags read.")
        return
    result.items.extend(_vorbis_comment(body, "ogg", result.warnings))


# -- RIFF WAVE / RF64 / BW64 -------------------------------------------------

def _plausible_id(b: bytes) -> bool:
    return len(b) == 4 and all(0x20 <= c <= 0x7E for c in b)


def _walk_riff(fh: BinaryIO, size: int, result: ContainerExtraction) -> None:
    head = fh.read(12)
    big = head[:4] in (b"RF64", b"BW64")
    ds64_data: int | None = None
    pos = 12
    while pos + 8 <= size:
        fh.seek(pos)
        ch = fh.read(8)
        cid, (csize,) = ch[:4], struct.unpack("<I", ch[4:8])
        if not _plausible_id(cid):
            result.warnings.append(f"RIFF: invalid chunk ID at offset {pos} — rest skipped.")
            return
        if cid == b"ds64":
            body = fh.read(min(csize, 64))
            if len(body) >= 16:
                ds64_data = struct.unpack("<Q", body[8:16])[0]
        if cid == b"data":
            if big and csize == 0xFFFFFFFF and ds64_data is not None:
                csize = ds64_data
            elif csize in (0, 0xFFFFFFFF):
                return   # Streaming-Schreiber: data läuft bis zum Dateiende
        elif csize == 0xFFFFFFFF and big:
            result.warnings.append(f"RF64 chunk {cid!r} with 64-bit size — rest skipped.")
            return
        start = pos + 8
        nxt = start + csize
        if csize % 2:
            # Pad-Byte — außer ein Schreiber hat es vergessen (Recherche §8).
            fh.seek(nxt + 1)
            with_pad = fh.read(4)
            fh.seek(nxt)
            without = fh.read(4)
            if _plausible_id(with_pad) or not _plausible_id(without):
                nxt += 1
        if cid not in _RIFF_SKIP:
            if csize > _MAX_BLOCK:
                result.warnings.append(f"RIFF chunk {cid!r} too large — skipped.")
            else:
                fh.seek(start)
                body = fh.read(csize)
                result.items.extend(_riff_chunk(cid, body, result.warnings))
        pos = nxt


def _riff_chunk(cid: bytes, body: bytes, warnings: list[str]) -> list[RawMetadataItem]:
    name = cid.decode("latin-1").rstrip()
    if cid in (b"id3 ", b"ID3 "):
        return id3.parse_id3v2(body, warnings)
    if cid == b"LIST" and len(body) >= 4:
        ltype = body[:4]
        if ltype == b"INFO":
            return _riff_list(body[4:], "riff:INFO", text=True, warnings=warnings)
        if ltype == b"adtl":
            return _riff_list(body[4:], "riff:adtl", text=False, warnings=warnings)
        return [_item(f"riff:LIST/{ltype.decode('latin-1').rstrip()}", None, data=body[4:])]
    if cid in (b"iXML", b"axml", b"_PMX"):
        return [_text_or_data(f"riff:{name}", None, body.rstrip(b"\x00"))]
    return [_item(f"riff:{name}", None, data=body)]


def _riff_list(body: bytes, source: str, *, text: bool, warnings: list[str]) -> list[RawMetadataItem]:
    """Unterchunks einer LIST: INFO als Text (Kodierung unbestimmt → UTF-8,
    sonst cp1252, Recherche §8), adtl roh."""
    items: list[RawMetadataItem] = []
    pos = 0
    while pos + 8 <= len(body):
        sid = body[pos:pos + 4]
        (ssize,) = struct.unpack("<I", body[pos + 4:pos + 8])
        value = body[pos + 8:pos + 8 + ssize]
        if len(value) < ssize:
            warnings.append(f"{source} sub-chunk truncated.")
        key = sid.decode("latin-1")
        if text:
            items.append(_text_or_data(source, key, value.rstrip(b"\x00"), fallback="cp1252"))
        else:
            items.append(_item(source, key, data=value))
        pos += 8 + ssize + (ssize % 2)
    return items


# -- AIFF / AIFC -------------------------------------------------------------

def _walk_aiff(fh: BinaryIO, size: int, result: ContainerExtraction) -> None:
    pos = 12
    while pos + 8 <= size:
        fh.seek(pos)
        ch = fh.read(8)
        cid, (csize,) = ch[:4], struct.unpack(">I", ch[4:8])
        if not _plausible_id(cid):
            result.warnings.append(f"AIFF: invalid chunk ID at offset {pos} — rest skipped.")
            return
        if cid not in _AIFF_SKIP:
            if csize > _MAX_BLOCK:
                result.warnings.append(f"AIFF chunk {cid!r} too large — skipped.")
            else:
                body = fh.read(csize)
                result.items.extend(_aiff_chunk(cid, body, result.warnings))
        pos += 8 + csize + (csize % 2)


def _aiff_chunk(cid: bytes, body: bytes, warnings: list[str]) -> list[RawMetadataItem]:
    name = cid.decode("latin-1").rstrip()
    if cid in (b"ID3 ", b"id3 "):
        return id3.parse_id3v2(body, warnings)
    if cid in _AIFF_TEXT:
        # ASCII/MacRoman (Recherche §8); mac_roman ist umkehrbar.
        return [_text_or_data(f"aiff:{name}", None, body.rstrip(b"\x00"), fallback="mac_roman")]
    if cid == b"APPL" and len(body) >= 4:
        return [_item("aiff:APPL", body[:4].decode("latin-1"), data=body[4:])]
    return [_item(f"aiff:{name}", None, data=body)]


# -- CAF ---------------------------------------------------------------------

def _walk_caf(fh: BinaryIO, size: int, result: ContainerExtraction) -> None:
    pos = 8   # 'caff' + UInt16 Version + UInt16 Flags
    while pos + 12 <= size:
        fh.seek(pos)
        ch = fh.read(12)
        ctype, (csize,) = ch[:4], struct.unpack(">q", ch[4:12])
        if ctype == b"data" and csize == -1:
            return   # data bis Dateiende
        if csize < 0 or not _plausible_id(ctype):
            result.warnings.append(f"CAF: invalid chunk at offset {pos} — rest skipped.")
            return
        if ctype not in _CAF_SKIP:
            if csize > _MAX_BLOCK:
                result.warnings.append(f"CAF chunk {ctype!r} too large — skipped.")
            else:
                body = fh.read(csize)
                result.items.extend(_caf_chunk(ctype, body, result.warnings))
        pos += 12 + csize


def _caf_chunk(ctype: bytes, body: bytes, warnings: list[str]) -> list[RawMetadataItem]:
    if ctype == b"info" and len(body) >= 4:
        (count,) = struct.unpack(">I", body[:4])
        parts = body[4:].split(b"\x00")
        items: list[RawMetadataItem] = []
        for i in range(count):
            if 2 * i + 1 >= len(parts):
                warnings.append("CAF info chunk truncated.")
                break
            key = parts[2 * i].decode("utf-8", errors="replace")
            items.append(_text_or_data("caf:info", key, parts[2 * i + 1]))
        return items
    name = ctype.decode("latin-1").rstrip()
    if ctype == b"uuid" and len(body) >= 16:
        return [_item("caf:uuid", body[:16].hex(), data=body[16:])]
    return [_item(f"caf:{name}", None, data=body)]


_WALKERS = {
    "mp3": _walk_mp3, "flac": _walk_flac, "ogg": _walk_ogg,
    "wav": _walk_riff, "aiff": _walk_aiff, "caf": _walk_caf,
}
