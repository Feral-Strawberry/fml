"""Hilfen, um PNG-Dateien für Tests **programmatisch** zu bauen.

So testen wir gegen bekannte, von uns konstruierte Eingaben (CLAUDE.md §8) — kein
einziger Binär-Blob muss ins Repo. Wir bauen nur so viel PNG, wie der Extraktor
sieht: Signatur, ein gültiger IHDR, die Metadaten-Chunks, IEND.
"""

from __future__ import annotations

import struct
import zlib

from feral.extract.png import PNG_SIGNATURE


def chunk(ctype: bytes, data: bytes) -> bytes:
    """Baue einen vollständigen PNG-Chunk inkl. korrekter Länge und CRC."""
    return (
        struct.pack(">I", len(data))
        + ctype
        + data
        + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
    )


def ihdr(width: int = 1, height: int = 1) -> bytes:
    """Minimaler, gültiger IHDR-Chunk (8-Bit Truecolor, ohne Interlace)."""
    data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return chunk(b"IHDR", data)


def text_chunk(keyword: str, text: str) -> bytes:
    """``tEXt``-Chunk (Latin-1, unkomprimiert)."""
    data = keyword.encode("latin-1") + b"\x00" + text.encode("latin-1")
    return chunk(b"tEXt", data)


def ztxt_chunk(keyword: str, text: str) -> bytes:
    """``zTXt``-Chunk (Latin-1, zlib-komprimiert)."""
    data = (
        keyword.encode("latin-1")
        + b"\x00"
        + b"\x00"  # Kompressionsmethode 0 = zlib
        + zlib.compress(text.encode("latin-1"))
    )
    return chunk(b"zTXt", data)


def itxt_chunk(
    keyword: str,
    text: str,
    *,
    compressed: bool = False,
    language: str = "",
    translated: str = "",
) -> bytes:
    """``iTXt``-Chunk (UTF-8, optional zlib-komprimiert)."""
    text_bytes = text.encode("utf-8")
    flag = b"\x01" if compressed else b"\x00"
    if compressed:
        text_bytes = zlib.compress(text_bytes)
    data = (
        keyword.encode("latin-1")
        + b"\x00"
        + flag
        + b"\x00"  # Kompressionsmethode 0
        + language.encode("latin-1")
        + b"\x00"
        + translated.encode("utf-8")
        + b"\x00"
        + text_bytes
    )
    return chunk(b"iTXt", data)


def exif_chunk(raw: bytes) -> bytes:
    """``eXIf``-Chunk mit rohem EXIF-/TIFF-Block."""
    return chunk(b"eXIf", raw)


def build_png(*body_chunks: bytes, include_ihdr: bool = True, include_iend: bool = True) -> bytes:
    """Setze eine vollständige PNG-Bytefolge aus den gegebenen Chunks zusammen."""
    out = bytearray(PNG_SIGNATURE)
    if include_ihdr:
        out += ihdr()
    for c in body_chunks:
        out += c
    if include_iend:
        out += chunk(b"IEND", b"")
    return bytes(out)
