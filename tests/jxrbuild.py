"""Hilfen, um JPEG-XR-Dateien für Tests **programmatisch** zu bauen.

Zwei Sorten (keine Binärdateien im Repo):

- ``make_jxr`` baut Kopf und Verzeichnis von Hand, ohne Bilddaten. Das
  genügt für Erkennung und Schicht 1 und läuft auf jedem System.
- ``encode`` schreibt eine echte, dekodierbare Datei mit dem Encoder des
  Systems (Windows Imaging Component). Nur unter Windows; damit prüft der
  Decoder-Test den Weg durch ``ctypes``.
"""

from __future__ import annotations

import array
import ctypes
import struct
import uuid
from pathlib import Path

from PIL import Image, ImageMath

from feral.extract import jxr

PIXEL_FORMAT_RGBA_HALF = "6fddc324-4e03-4bfe-b185-3d77768dc93a"

_BYTE, _ASCII, _LONG = 1, 2, 4


def _table(entries: list[tuple[int, int, int, bytes]], base: int) -> bytes:
    """Verzeichnis ab Dateiposition ``base``: Einträge (Tag, Typ, Anzahl,
    Wert), Werte über 4 Bytes hinter der Tabelle."""
    out = struct.pack("<H", len(entries))
    blobs = b""
    blob_at = base + 2 + 12 * len(entries) + 4
    for tag, kind, count, value in sorted(entries):
        if len(value) > 4:
            field = struct.pack("<I", blob_at + len(blobs))
            blobs += value
        else:
            field = value.ljust(4, b"\x00")
        out += struct.pack("<HHI", tag, kind, count) + field
    return out + b"\x00" * 4 + blobs


def make_jxr(path: Path, *, width: int = 3840, height: int = 2160,
             pixel_format: str | None = jxr.PIXEL_FORMAT_RGBA_FLOAT,
             texts: dict[int, str] | None = None, exif: dict[int, str] | None = None,
             xmp: bytes | None = None, icc: bytes | None = None) -> Path:
    """Kopf + Verzeichnis einer JXR (ohne Bilddaten)."""
    def ascii_entry(tag: int, text: str) -> tuple[int, int, int, bytes]:
        raw = text.encode("latin-1") + b"\x00"
        return tag, _ASCII, len(raw), raw

    entries = [(0xBC80, _LONG, 1, struct.pack("<I", width)),
               (0xBC81, _LONG, 1, struct.pack("<I", height))]
    if pixel_format:
        entries.append((0xBC01, _BYTE, 16, uuid.UUID(pixel_format).bytes_le))
    entries += [ascii_entry(tag, text) for tag, text in (texts or {}).items()]
    if xmp is not None:
        entries.append((0x02BC, _BYTE, len(xmp), xmp))
    if icc is not None:
        entries.append((0x8773, 7, len(icc), icc))
    exif_table = b""
    if exif:
        # Platzhalter, um die Länge des Hauptverzeichnisses zu kennen.
        probe = _table(entries + [(0x8769, _LONG, 1, b"\x00" * 4)], 8)
        exif_at = 8 + len(probe)
        entries.append((0x8769, _LONG, 1, struct.pack("<I", exif_at)))
        exif_table = _table([ascii_entry(t, v) for t, v in exif.items()], exif_at)
    path.write_bytes(jxr.SIGNATURE + struct.pack("<I", 8) + _table(entries, 8) + exif_table)
    return path


def interleave(red: Image.Image, green: Image.Image, blue: Image.Image) -> bytearray:
    """Drei Kanäle im Modus ``F`` → RGBA-Gleitkomma (Alpha 1.0), wie der
    Decoder sie liefert."""
    count = red.width * red.height
    pixels = array.array("f", bytes(count * 16))
    for index, channel in enumerate((red, green, blue)):
        pixels[index::4] = array.array("f", channel.tobytes())
    pixels[3::4] = array.array("f", [1.0]) * count
    return bytearray(pixels.tobytes())


def synthetic_pixels(width: int, height: int) -> bytearray:
    """scRGB-Testbild: Struktur plus Rauschen, Rot bis 12.0 (960 Nits) und
    leicht negative Werte."""
    shape = Image.effect_mandelbrot((width, height), (-2.2, -1.2, 1.2, 1.2), 60).convert("F")
    noise = Image.effect_noise((width, height), 30).convert("F")
    return interleave(
        ImageMath.lambda_eval(
            lambda a: (a["m"] / 255.0) ** 3.0 * 12.0 + a["n"] / 2550.0 - 0.02, m=shape, n=noise),
        ImageMath.lambda_eval(
            lambda a: (a["m"] / 255.0) ** 2.0 * 2.0 + a["n"] / 2550.0, m=shape, n=noise),
        ImageMath.lambda_eval(
            lambda a: (a["m"] / 255.0) * 0.8 + a["n"] / 2550.0, m=shape, n=noise),
    )


def half_pixels(pixels: bytes | bytearray) -> bytearray:
    """RGBA 32-Bit-Gleitkomma → RGBA 16-Bit-Gleitkomma (das Format der
    Windows Game Bar)."""
    floats = memoryview(pixels).cast("f")
    return bytearray(struct.pack(f"<{len(floats)}e", *floats))


# Encoder des Systems: Methoden nach ihrem Platz in der vtable (wincodec.h).
_CONTAINER_WMP = "57a37caa-367a-4540-916b-f183c5093a4b"
_GENERIC_WRITE = 0x40000000
_FACTORY_CREATE_ENCODER = 8
_FACTORY_CREATE_STREAM = 14
_STREAM_INIT_FROM_FILENAME = 15
_ENCODER_INITIALIZE = 3
_ENCODER_CREATE_NEW_FRAME = 10
_ENCODER_COMMIT = 11
_FRAME_INITIALIZE = 3
_FRAME_SET_SIZE = 4
_FRAME_SET_PIXEL_FORMAT = 6
_FRAME_WRITE_PIXELS = 10
_FRAME_COMMIT = 12

_P, _OUT, _UINT = ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint32


def encode(path: Path, width: int, height: int, pixels: bytearray,
           pixel_format: str = jxr.PIXEL_FORMAT_RGBA_FLOAT) -> str:
    """Pixel als JPEG XR schreiben (nur Windows). ``pixels`` liegt schon im
    gewünschten Format vor. Gibt das Format zurück, das der Encoder nahm."""
    taken = jxr.guid(pixel_format)
    with jxr.ComSession() as com:
        stream, encoder, frame = com.new("stream"), com.new("encoder"), com.new("frame")
        com.factory.call(_FACTORY_CREATE_STREAM, (_OUT,), ctypes.byref(stream.ptr))
        stream.call(_STREAM_INIT_FROM_FILENAME, (ctypes.c_wchar_p, _UINT),
                    str(path), _GENERIC_WRITE)
        com.factory.call(
            _FACTORY_CREATE_ENCODER, (ctypes.POINTER(jxr._GUID), _P, _OUT),
            ctypes.byref(jxr.guid(_CONTAINER_WMP)), None, ctypes.byref(encoder.ptr))
        encoder.call(_ENCODER_INITIALIZE, (_P, _UINT), stream.ptr, 2)
        encoder.call(_ENCODER_CREATE_NEW_FRAME, (_OUT, _P), ctypes.byref(frame.ptr), None)
        frame.call(_FRAME_INITIALIZE, (_P,), None)
        frame.call(_FRAME_SET_SIZE, (_UINT, _UINT), width, height)
        frame.call(_FRAME_SET_PIXEL_FORMAT, (ctypes.POINTER(jxr._GUID),),
                   ctypes.byref(taken))
        frame.call(_FRAME_WRITE_PIXELS, (_UINT, _UINT, _UINT, _P),
                   height, len(pixels) // height, len(pixels),
                   (ctypes.c_ubyte * len(pixels)).from_buffer(pixels))
        frame.call(_FRAME_COMMIT, ())
        encoder.call(_ENCODER_COMMIT, ())
    return jxr.pixel_format_name(str(uuid.UUID(bytes_le=bytes(taken))))
