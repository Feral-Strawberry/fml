"""Audio-Dateien für Tests **programmatisch** bauen (Projektregel: keine
Binär-Blobs im Repo). Gebaut wird nur, was die Walker sehen: Tags, Blöcke,
Chunks, Seitenrahmen — Audiodaten sind Füllbytes (ffprobe ist in den
Walker-Tests abgeschaltet)."""

from __future__ import annotations

import base64
import struct
import zlib

# Ein gültiger MPEG-1-Layer-III-Framekopf (128 kbit/s, 44,1 kHz) + Nutzlast.
MPEG_FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 413


def syncsafe(n: int) -> bytes:
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def id3_frame(fid: str, payload: bytes, *, major: int = 4, flags: int = 0,
              itunes: bool = False) -> bytes:
    if major == 2:
        return fid.encode() + len(payload).to_bytes(3, "big") + payload
    size = (struct.pack(">I", len(payload)) if major == 3 or itunes
            else syncsafe(len(payload)))
    return fid.encode() + size + struct.pack(">H", flags) + payload


def id3_tag(frames: bytes, *, major: int = 4, flags: int = 0, padding: int = 16,
            ext: bytes = b"") -> bytes:
    body = ext + frames + b"\x00" * padding
    return b"ID3" + bytes([major, 0, flags]) + syncsafe(len(body)) + body


def txxx(desc: str, value: str, enc: int = 3) -> bytes:
    codec = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}[enc]
    term = b"\x00\x00" if enc in (1, 2) else b"\x00"
    return bytes([enc]) + desc.encode(codec) + term + value.encode(codec)


def text_frame(value: str, enc: int = 3) -> bytes:
    codec = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}[enc]
    return bytes([enc]) + value.encode(codec)


def comm(lang: str, desc: str, text: str) -> bytes:
    return b"\x03" + lang.encode() + desc.encode() + b"\x00" + text.encode()


def apic(mime: str, pic_type: int, desc: str, data: bytes) -> bytes:
    return b"\x03" + mime.encode() + b"\x00" + bytes([pic_type]) + desc.encode() + b"\x00" + data


def id3v1(title: str = "", artist: str = "", comment: str = "", track: int = 0,
          genre: int = 255) -> bytes:
    def pad(s: str, n: int) -> bytes:
        return s.encode("latin-1")[:n].ljust(n, b"\x00")
    body = (b"TAG" + pad(title, 30) + pad(artist, 30) + pad("", 30) + pad("", 4))
    if track:
        body += pad(comment, 28) + b"\x00" + bytes([track])
    else:
        body += pad(comment, 30)
    return body + bytes([genre])


def apev2(items: list[tuple[str, bytes, int]]) -> bytes:
    """APEv2 mit Fuß (ohne Kopf); items = (Schlüssel, Wert, Flags)."""
    body = b"".join(struct.pack("<II", len(v), f) + k.encode() + b"\x00" + v
                    for k, v, f in items)
    foot = b"APETAGEX" + struct.pack("<IIII", 2000, len(body) + 32, len(items), 0) + b"\x00" * 8
    return body + foot


def mp3(tag: bytes = b"", *, tail: bytes = b"", frames: int = 3) -> bytes:
    return tag + MPEG_FRAME * frames + tail


# -- FLAC / Vorbis -------------------------------------------------------------

def vorbis_comment(entries: list[bytes], vendor: bytes = b"Lavf61.7.100") -> bytes:
    out = struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", len(entries))
    for e in entries:
        out += struct.pack("<I", len(e)) + e
    return out


def flac_picture(mime: str, pic_type: int, desc: str, data: bytes) -> bytes:
    return (struct.pack(">II", pic_type, len(mime)) + mime.encode()
            + struct.pack(">I", len(desc.encode())) + desc.encode()
            + struct.pack(">IIII", 1, 1, 24, 0) + struct.pack(">I", len(data)) + data)


def flac_block(btype: int, data: bytes, last: bool = False) -> bytes:
    return bytes([(0x80 if last else 0) | btype]) + len(data).to_bytes(3, "big") + data


def flac(blocks: list[tuple[int, bytes]], prefix: bytes = b"") -> bytes:
    streaminfo = flac_block(0, b"\x00" * 34)
    rest = b"".join(flac_block(t, d, last=(i == len(blocks) - 1))
                    for i, (t, d) in enumerate(blocks))
    return prefix + b"fLaC" + streaminfo + rest + b"\xff\xf8" + b"\x00" * 64


def metadata_block_picture(mime: str, data: bytes) -> bytes:
    return b"METADATA_BLOCK_PICTURE=" + base64.b64encode(flac_picture(mime, 3, "", data))


# -- Ogg -----------------------------------------------------------------------

def ogg_pages(packets: list[bytes], serial: int = 1, max_segments: int = 255) -> bytes:
    """Pakete in Ogg-Seiten verpacken (Lacing, Seitenumbruch bei vollen
    Segmenttabellen). CRC wird nicht geprüft und bleibt 0."""
    lacing_all: list[tuple[int, bytes]] = []
    for p in packets:
        n, pos = len(p), 0
        while n >= 255:
            lacing_all.append((255, p[pos:pos + 255]))
            pos += 255
            n -= 255
        lacing_all.append((n, p[pos:pos + n]))
    out, seq, i = b"", 0, 0
    while i < len(lacing_all):
        chunk = lacing_all[i:i + max_segments]
        i += len(chunk)
        head = (b"OggS" + b"\x00" + bytes([2 if seq == 0 else 0]) + b"\x00" * 8
                + struct.pack("<III", serial, seq, 0) + bytes([len(chunk)]))
        out += head + bytes(l for l, _ in chunk) + b"".join(d for _, d in chunk)
        seq += 1
    return out


def opus(entries: list[bytes]) -> bytes:
    head = b"OpusHead" + b"\x01\x02" + b"\x00" * 9
    return ogg_pages([head, b"OpusTags" + vorbis_comment(entries)])


def ogg_vorbis(entries: list[bytes]) -> bytes:
    ident = b"\x01vorbis" + b"\x00" * 23
    return ogg_pages([ident, b"\x03vorbis" + vorbis_comment(entries) + b"\x01"])


# -- RIFF / AIFF / CAF ---------------------------------------------------------

def riff_chunk(cid: bytes, data: bytes, *, pad: bool = True) -> bytes:
    out = cid + struct.pack("<I", len(data)) + data
    return out + (b"\x00" if pad and len(data) % 2 else b"")


def wav(chunks: bytes, form: bytes = b"RIFF") -> bytes:
    fmt = riff_chunk(b"fmt ", struct.pack("<HHIIHH", 1, 2, 48000, 192000, 4, 16))
    body = b"WAVE" + fmt + chunks
    return form + struct.pack("<I", len(body)) + body


def info_list(pairs: list[tuple[bytes, bytes]]) -> bytes:
    return riff_chunk(b"LIST", b"INFO" + b"".join(riff_chunk(k, v + b"\x00") for k, v in pairs))


def aiff_chunk(cid: bytes, data: bytes) -> bytes:
    out = cid + struct.pack(">I", len(data)) + data
    return out + (b"\x00" if len(data) % 2 else b"")


def aiff(chunks: bytes) -> bytes:
    body = b"AIFF" + aiff_chunk(b"COMM", b"\x00" * 18) + chunks + aiff_chunk(b"SSND", b"\x00" * 16)
    return b"FORM" + struct.pack(">I", len(body)) + body


def caf_chunk(ctype: bytes, data: bytes, size: int | None = None) -> bytes:
    return ctype + struct.pack(">q", len(data) if size is None else size) + data


def caf(chunks: bytes) -> bytes:
    return b"caff" + struct.pack(">HH", 1, 0) + caf_chunk(b"desc", b"\x00" * 32) + chunks


def caf_info(pairs: list[tuple[str, str]]) -> bytes:
    body = struct.pack(">I", len(pairs)) + b"".join(
        k.encode() + b"\x00" + v.encode() + b"\x00" for k, v in pairs)
    return caf_chunk(b"info", body)


def zlib_frame_v4(payload: bytes) -> tuple[bytes, int]:
    """(Nutzlast, Flags) eines zlib-komprimierten 2.4-Frames (mit Datenlänge)."""
    comp = zlib.compress(payload)
    return syncsafe(len(payload)) + comp, 0x08 | 0x01
