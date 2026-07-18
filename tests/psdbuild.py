"""Hilfen, um PSD-Dateien für Tests **programmatisch** zu bauen.

Wie ``pngbuild``: bekannte, selbst konstruierte Eingaben statt Binär-Blobs im
Repo (CLAUDE.md §8). Gebaut wird eine **vollständige, gültige** Minimal-PSD
(RGB, 8 Bit, unkomprimierte Pixeldaten) — Pillow kann sie öffnen, damit
dieselbe Fixture auch die Thumbnail-/Vorschau-Strecke testet (ADR 0052).
"""

from __future__ import annotations

import struct

from feral.extract.psd import PSD_SIGNATURE


def resource(resource_id: int, data: bytes, name: bytes = b"") -> bytes:
    """Ein vollständiger Image Resource Block ('8BIM', Polsterung inklusive)."""
    pascal = bytes([len(name)]) + name
    if len(pascal) % 2:
        pascal += b"\x00"
    block = b"8BIM" + struct.pack(">H", resource_id) + pascal
    block += struct.pack(">I", len(data)) + data
    if len(data) % 2:
        block += b"\x00"
    return block


def version_info(has_real_merged_data: bool) -> bytes:
    """Version-Info-Ressource (0x0421) mit dem ``hasRealMergedData``-Flag.

    Layout: ``version(4) | hasRealMergedData(1) | writer(unicode) |
    reader(unicode) | fileVersion(4)`` (ADR 0052). Für den Detektor zählt nur
    das Flag-Byte; die Unicode-Strings bauen wir minimal, damit die Ressource
    strukturell echt ist.
    """
    def unicode_str(s: str) -> bytes:
        chars = s + "\x00"                       # Photoshop zählt den Abschluss mit
        return struct.pack(">I", len(chars)) + chars.encode("utf-16-be")

    data = struct.pack(">I", 1)                  # version
    data += bytes([1 if has_real_merged_data else 0])
    data += unicode_str("fml") + unicode_str("fml")
    data += struct.pack(">I", 1)                 # fileVersion
    return resource(0x0421, data)


def build_psd(
    *resources: bytes,
    width: int = 2,
    height: int = 2,
    color=(255, 0, 0),
) -> bytes:
    """Setze eine komplette PSD-Bytefolge zusammen (einfarbige RGB-Fläche)."""
    out = bytearray()
    out += PSD_SIGNATURE
    out += struct.pack(">H", 1)          # Version 1 = PSD
    out += b"\x00" * 6                   # reserviert
    out += struct.pack(">HIIHH", 3, height, width, 8, 3)  # 3 Kanäle, 8 Bit, RGB
    out += struct.pack(">I", 0)          # Farbmodus-Daten: leer
    body = b"".join(resources)
    out += struct.pack(">I", len(body)) + body   # Image Resources
    out += struct.pack(">I", 0)          # Ebenen-/Masken-Info: leer
    out += struct.pack(">H", 0)          # Pixeldaten: Kompression 0 = raw
    for channel in color:                # planar: erst alle R, dann G, dann B
        out += bytes([channel]) * (width * height)
    return bytes(out)
