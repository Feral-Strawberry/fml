"""Tests für den PNG-Container-Extraktor (Schicht 1).

Bekannte, programmatisch gebaute PNGs -> erwartete Roh-Metadaten. Deckt die für
AI-Bilder typischen Fälle ab (ComfyUI-Workflow in iTXt, A1111-Parameter in tEXt)
sowie das defensive Verhalten bei beschädigten Dateien.
"""

from __future__ import annotations

import io
import struct
import zlib

from feral.extract import png
from feral.extract.png import PNG_SIGNATURE

from .pngbuild import (
    build_png,
    chunk,
    exif_chunk,
    itxt_chunk,
    text_chunk,
    ztxt_chunk,
)

# Realistische Beispieldaten.
A1111_PARAMS = (
    "masterpiece, 1girl\n"
    "Negative prompt: lowres\n"
    "Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 12345, Model: sd_xl_base"
)
COMFY_WORKFLOW = '{"nodes": [{"id": 1, "type": "KSampler"}], "seed": 42}'


def _extract_bytes(data: bytes):
    return png.extract(io.BytesIO(data))


def test_extracts_a1111_text_chunk():
    result = _extract_bytes(build_png(text_chunk("parameters", A1111_PARAMS)))

    assert result.container == "png"
    assert result.warnings == []
    assert len(result.items) == 1
    item = result.items[0]
    assert item.source == "png:tEXt"
    assert item.keyword == "parameters"
    assert item.text == A1111_PARAMS
    assert item.encoding == "latin-1"
    assert item.compressed is False


def test_extracts_comfy_itxt_workflow():
    result = _extract_bytes(build_png(itxt_chunk("workflow", COMFY_WORKFLOW)))

    assert result.warnings == []
    (item,) = result.items
    assert item.source == "png:iTXt"
    assert item.keyword == "workflow"
    assert item.text == COMFY_WORKFLOW
    assert item.encoding == "utf-8"


def test_preserves_order_of_multiple_chunks():
    result = _extract_bytes(
        build_png(
            text_chunk("parameters", A1111_PARAMS),
            itxt_chunk("workflow", COMFY_WORKFLOW),
            text_chunk("Software", "ComfyUI"),
        )
    )
    assert [i.keyword for i in result.items] == ["parameters", "workflow", "Software"]


def test_ztxt_is_decompressed_and_marked():
    result = _extract_bytes(build_png(ztxt_chunk("parameters", A1111_PARAMS)))
    (item,) = result.items
    assert item.source == "png:zTXt"
    assert item.text == A1111_PARAMS
    assert item.compressed is True
    assert result.warnings == []


def test_itxt_compressed_is_decompressed():
    result = _extract_bytes(
        build_png(itxt_chunk("workflow", COMFY_WORKFLOW, compressed=True))
    )
    (item,) = result.items
    assert item.text == COMFY_WORKFLOW
    assert item.compressed is True


def test_exif_chunk_kept_as_raw_bytes():
    raw = b"MM\x00\x2a\x00\x00\x00\x08fakeexif"
    result = _extract_bytes(build_png(exif_chunk(raw)))
    (item,) = result.items
    assert item.source == "png:eXIf"
    assert item.data == raw
    assert item.text is None
    assert item.encoding == "binary"


def test_unicode_text_in_itxt_roundtrips():
    text = "Prompt mit Ümläüten und Emoji 🍓"
    result = _extract_bytes(build_png(itxt_chunk("prompt", text)))
    (item,) = result.items
    assert item.text == text


# --- Defensives Verhalten -------------------------------------------------------


def test_non_png_signature_warns_without_items():
    result = _extract_bytes(b"not a png at all, just text")
    assert result.items == []
    assert any("Signatur" in w for w in result.warnings)


def test_skips_large_idat_and_still_finds_trailing_text():
    # Ein großer IDAT-Chunk vor dem Text darf den Extraktor nicht stören oder
    # in den Speicher gezwungen werden — Text danach wird trotzdem gefunden.
    big_idat = chunk(b"IDAT", b"\x00" * (2 * 1024 * 1024))
    data = build_png(big_idat, text_chunk("parameters", A1111_PARAMS))
    result = _extract_bytes(data)
    assert result.warnings == []
    assert [i.keyword for i in result.items] == ["parameters"]


def test_truncated_chunk_warns():
    # Gültiger Anfang, dann ein Text-Chunk, der mehr Länge meldet, als Bytes folgen.
    good = build_png(include_iend=False)
    truncated_header = struct.pack(">I", 9999) + b"tEXt" + b"parameters"  # zu kurz
    result = _extract_bytes(good + truncated_header)
    assert any("abgeschnitten" in w.lower() for w in result.warnings)


def test_missing_iend_warns():
    data = build_png(text_chunk("parameters", "x"), include_iend=False)
    result = _extract_bytes(data)
    # Inhalt wird trotzdem extrahiert, aber das fehlende IEND wird gemeldet.
    assert result.items and result.items[0].keyword == "parameters"
    assert any("IEND" in w for w in result.warnings)


def test_crc_error_warns_but_keeps_content():
    # Text-Chunk mit absichtlich falscher CRC bauen.
    ctype, cdata = b"tEXt", b"parameters\x00wert"
    bad = struct.pack(">I", len(cdata)) + ctype + cdata + struct.pack(">I", 0xDEADBEEF)
    data = bytearray(PNG_SIGNATURE)
    from .pngbuild import ihdr

    data += ihdr()
    data += bad
    data += chunk(b"IEND", b"")
    result = _extract_bytes(bytes(data))
    assert result.items and result.items[0].text == "wert"
    assert any("CRC" in w for w in result.warnings)


def test_broken_itxt_utf8_falls_back_to_raw_bytes():
    # iTXt mit ungültigem UTF-8 im Textfeld -> verlustfrei als Roh-Bytes behalten.
    invalid_utf8 = b"\xff\xfe\x00\x80"
    data = (
        b"prompt\x00"  # keyword
        + b"\x00"  # nicht komprimiert
        + b"\x00"  # methode
        + b"\x00"  # leere sprache + trenner
        + b"\x00"  # leeres übersetztes keyword + trenner
        + invalid_utf8
    )
    png_bytes = build_png(chunk(b"iTXt", data))
    result = _extract_bytes(png_bytes)
    (item,) = result.items
    assert item.data == invalid_utf8
    assert item.encoding == "binary"
    assert any("UTF-8" in w for w in result.warnings)


# --- Schutz vor zlib-Dekompressionsbomben (ADR 0032) -----------------------------
# Ein winziger komprimierter Chunk, der zu weit mehr als dem Deckel entpackt.
# Nullbytes komprimieren extrem gut: ~65 MiB → wenige KB im Chunk.
_BOMB_SIZE = png._MAX_DECOMPRESSED + (1 << 20)  # Deckel + 1 MiB


def _ztxt_bomb(keyword: str = "parameters") -> bytes:
    payload = zlib.compress(b"\x00" * _BOMB_SIZE)
    data = keyword.encode("latin-1") + b"\x00" + b"\x00" + payload  # methode 0 = zlib
    return chunk(b"zTXt", data)


def _itxt_bomb(keyword: str = "workflow") -> bytes:
    payload = zlib.compress(b"\x00" * _BOMB_SIZE)
    data = (
        keyword.encode("latin-1") + b"\x00"
        + b"\x01"  # Kompressions-Flag
        + b"\x00"  # Methode 0
        + b"\x00"  # leere Sprache + Trenner
        + b"\x00"  # leeres übersetztes Keyword + Trenner
        + payload
    )
    return chunk(b"iTXt", data)


def test_ztxt_decompression_bomb_is_refused_not_expanded():
    """Ein zTXt, das über den Deckel entpackt, wird verworfen (Roh-Fallback +
    Warnung) statt Gigabytes in den Speicher zu ziehen."""
    result = _extract_bytes(build_png(_ztxt_bomb()))
    (item,) = result.items
    assert item.text is None            # nicht entpackt
    assert item.encoding == "binary"    # als Roh-Bytes behalten
    assert any("bombe" in w.lower() for w in result.warnings)


def test_itxt_decompression_bomb_is_refused_not_expanded():
    result = _extract_bytes(build_png(_itxt_bomb()))
    (item,) = result.items
    assert item.text is None
    assert item.encoding == "binary"
    assert any("bombe" in w.lower() for w in result.warnings)


def test_bomb_does_not_stop_later_chunks():
    """Nach einer verworfenen Bombe läuft der Extraktor weiter (defensiv, §8)."""
    result = _extract_bytes(
        build_png(_ztxt_bomb(), text_chunk("parameters", A1111_PARAMS))
    )
    assert any(i.text == A1111_PARAMS for i in result.items)
