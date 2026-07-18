"""PSD-Container-Extraktor (Schicht 1, reine Standardbibliothek).

Photoshop-Dateien tragen ihre Metadaten in den **Image Resource Blocks**
zwischen Header und Ebenen-Daten. Dieser Extraktor läuft durch die
Container-Struktur und zieht die bekannten Metadaten-Ressourcen
**unverändert** heraus (ADR 0008/0052) — interpretiert wird nichts, das ist
Schicht 2 (ADR 0004). Der XMP-Block landet als Text und wird damit vom
bestehenden ``xmp``-Parser gefunden.

PSD-Aufbau (Adobe-Spezifikation):

- 26-Byte-Header: ``8BPS | version(2) | reserviert(6) | kanäle(2) |
  höhe(4) | breite(4) | tiefe(2) | farbmodus(2)`` (alles big-endian;
  Version 2 = PSB/„Large Document", Header identisch).
- Farbmodus-Daten: ``länge(4) | daten``.
- Image Resources: ``gesamtlänge(4)``, darin Blöcke je
  ``'8BIM' | id(2) | name(pascal, auf gerade Länge gepolstert) |
  größe(4) | daten (auf gerade Länge gepolstert)``.
- Danach Ebenen- und Pixeldaten — für Schicht 1 uninteressant.

Der Extraktor ist **defensiv** (CLAUDE.md §8): beschädigte oder
abgeschnittene Dateien werfen nicht, sondern sammeln `warnings`. Pixel-
und Ebenen-Daten werden nie in den Speicher geladen.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import BinaryIO

from .types import ContainerExtraction, RawMetadataItem

PSD_SIGNATURE = b"8BPS"

# Ressourcen-IDs, aus denen wir Metadaten ziehen: ID → (Keyword, Encoding).
# Alles andere (eingebettete Vorschau-Thumbnails, Druck-/Raster-Einstellungen,
# Hilfslinien) sind abgeleitete bzw. Werkzeug-Daten, keine Container-Metadaten
# im Sinne von Schicht 1 — bewusst übersprungen (wie die Plugin-Objekte in
# image_pillow).
_RESOURCES: dict[int, tuple[str, str]] = {
    0x0404: ("iptc", "binary"),         # IPTC-NAA-Record
    0x040F: ("icc_profile", "binary"),  # ICC-Farbprofil
    0x0422: ("exif", "binary"),         # EXIF-Block (TIFF-Struktur)
    0x0424: ("xmp", "utf-8"),           # XMP-Paket (XML, UTF-8)
}

# Farbmodus-Feld des Headers → lesbarer Name (Umschlag-Angabe, als Text-Item
# festgehalten: für CMYK/Lab-Dateien erklärt er, warum Farben anders wirken).
_COLOR_MODES = {
    0: "bitmap", 1: "grayscale", 2: "indexed", 3: "rgb",
    4: "cmyk", 7: "multichannel", 8: "duotone", 9: "lab",
}

_HEADER = struct.Struct(">4sH6sHIIHH")  # Signatur bis Farbmodus, 26 Bytes

# Version-Info-Ressource: trägt das Flag ``hasRealMergedData`` (ADR 0052) —
# Photoshop schreibt den flachgerechneten Composite nur mit „Maximale
# Kompatibilität". Fehlt er, liest Pillow einen weißen Platzhalter statt der
# Ebenen. Über dieses Flag lässt sich das ehrlich erkennen (statt Weiß zu
# zeigen), ohne die Ebenen selbst zusammenrechnen zu müssen.
_VERSION_INFO_ID = 0x0421


def extract(source: str | Path | BinaryIO) -> ContainerExtraction:
    """Extrahiere alle Roh-Metadaten aus einer PSD-/PSB-Quelle.

    `source` ist ein Dateipfad oder ein geöffneter Binärstrom. Wirft nicht bei
    beschädigten Dateien — Probleme landen in `warnings`.
    """
    if hasattr(source, "read"):
        return _extract_stream(source)  # type: ignore[arg-type]
    with open(source, "rb") as fh:
        return _extract_stream(fh)


def has_real_composite(source: str | Path | BinaryIO) -> bool:
    """Trägt die PSD einen echten, flachgerechneten Composite? (ADR 0052)

    Photoshop schreibt ihn nur mit „Maximale Kompatibilität". Ohne ihn liest
    Pillow einen weißen Platzhalter — Thumbnail/Vorschau würden also Weiß statt
    des Bildes zeigen. Das Version-Info-Resource (`0x0421`) hält dafür das Flag
    ``hasRealMergedData``. Ist es ``False``, gibt es keine anzeigbaren Pixel
    (die liegen nur in den Ebenen, die wir bewusst nicht zusammenrechnen).

    Fehlt die Ressource ganz (alte/fremde Dateien) oder lässt sich die Datei
    nicht lesen, wird ``True`` angenommen: solche PSDs haben einen echten
    Composite in der Bilddaten-Sektion — im Zweifel anzeigen, nicht verstecken.
    """
    try:
        if hasattr(source, "read"):
            return _read_composite_flag(source)  # type: ignore[arg-type]
        with open(source, "rb") as fh:
            return _read_composite_flag(fh)
    except (OSError, struct.error):
        return True


def _read_composite_flag(fh: BinaryIO) -> bool:
    header = fh.read(_HEADER.size)
    if len(header) < _HEADER.size:
        return True
    signature, version, *_rest = _HEADER.unpack(header)
    if signature != PSD_SIGNATURE or version not in (1, 2):
        return True
    (cm_len,) = struct.unpack(">I", fh.read(4))
    fh.seek(cm_len, 1)                                  # Farbmodus-Daten überspringen
    (resources_len,) = struct.unpack(">I", fh.read(4))
    end = fh.tell() + resources_len
    while fh.tell() < end:
        block_head = fh.read(6)
        if len(block_head) < 6 or block_head[:4] != b"8BIM":
            break
        resource_id = struct.unpack(">H", block_head[4:6])[0]
        name_len = (fh.read(1) or b"\x00")[0]
        fh.seek(name_len + (0 if name_len % 2 else 1), 1)  # Pascal-Name (gerade)
        size_raw = fh.read(4)
        if len(size_raw) < 4:
            break
        (size,) = struct.unpack(">I", size_raw)
        if resource_id != _VERSION_INFO_ID:
            fh.seek(size + size % 2, 1)                 # uninteressant: überspringen
            continue
        data = fh.read(5)                               # version(4) | hasRealMergedData(1)
        return bool(data[4]) if len(data) >= 5 else True
    return True


def _extract_stream(fh: BinaryIO) -> ContainerExtraction:
    result = ContainerExtraction(container="psd")

    header = fh.read(_HEADER.size)
    if len(header) < _HEADER.size:
        result.warnings.append("Datei endet im PSD-Header (abgeschnitten?).")
        return result
    signature, version, _reserved, channels, height, width, depth, mode = (
        _HEADER.unpack(header)
    )
    if signature != PSD_SIGNATURE:
        result.warnings.append("Keine PSD-Signatur ('8BPS') am Dateianfang.")
        return result
    if version not in (1, 2):  # 1 = PSD, 2 = PSB
        result.warnings.append(f"Unbekannte PSD-Version {version}.")
        return result
    result.width, result.height = width, height
    result.items.append(
        RawMetadataItem(
            source="psd:header", keyword="color_mode",
            text=_COLOR_MODES.get(mode, f"unbekannt ({mode})"),
            data=None, encoding="utf-8",
        )
    )
    result.items.append(
        RawMetadataItem(
            source="psd:header", keyword="depth",
            text=f"{depth} bit, {channels} Kanäle", data=None, encoding="utf-8",
        )
    )

    try:
        # Farbmodus-Daten (nur bei Indexed/Duotone gefüllt) überspringen.
        (cm_len,) = struct.unpack(">I", fh.read(4))
        fh.seek(cm_len, 1)
        (resources_len,) = struct.unpack(">I", fh.read(4))
    except struct.error:
        result.warnings.append("Datei endet vor den Image Resources (abgeschnitten?).")
        return result

    _walk_resources(fh, resources_len, result)
    return result


def _walk_resources(fh: BinaryIO, total: int, result: ContainerExtraction) -> None:
    """Alle Image Resource Blocks durchlaufen, bekannte Metadaten einsammeln."""
    end = fh.tell() + total
    while fh.tell() < end:
        block_head = fh.read(6)
        if len(block_head) < 6:
            result.warnings.append("Image Resources enden mitten im Block (abgeschnitten?).")
            return
        block_sig, resource_id = block_head[:4], struct.unpack(">H", block_head[4:6])[0]
        if block_sig != b"8BIM":
            # Fremd-Signaturen (z. B. 'MeSa' von ImageReady) haben dasselbe
            # Layout nicht garantiert — ab hier ist nichts mehr verlässlich.
            result.warnings.append(
                f"Unbekannte Ressourcen-Signatur {block_sig!r} — Rest übersprungen."
            )
            return
        # Pascal-Name, auf gerade Gesamtlänge gepolstert.
        name_len = (fh.read(1) or b"\x00")[0]
        fh.seek(name_len + (0 if name_len % 2 else 1), 1)
        size_raw = fh.read(4)
        if len(size_raw) < 4:
            result.warnings.append("Image Resources enden mitten im Block (abgeschnitten?).")
            return
        (size,) = struct.unpack(">I", size_raw)

        known = _RESOURCES.get(resource_id)
        if known is None:
            fh.seek(size + size % 2, 1)  # uninteressant: überspringen, nicht laden
            continue
        keyword, encoding = known
        data = fh.read(size)
        if len(data) < size:
            result.warnings.append(
                f"Ressource 0x{resource_id:04x} ({keyword}) ist abgeschnitten."
            )
            return
        if size % 2:
            fh.seek(1, 1)

        if encoding == "utf-8":
            try:
                result.items.append(
                    RawMetadataItem(
                        source="psd:8bim", keyword=keyword,
                        text=data.decode("utf-8"), data=None, encoding="utf-8",
                    )
                )
            except UnicodeDecodeError:
                result.warnings.append(
                    f"Ressource 0x{resource_id:04x} ({keyword}) ist kein gültiges "
                    "UTF-8 — als Binär-Eintrag übernommen."
                )
                result.items.append(
                    RawMetadataItem(
                        source="psd:8bim", keyword=keyword,
                        text=None, data=data, encoding="binary",
                    )
                )
        else:
            result.items.append(
                RawMetadataItem(
                    source="psd:8bim", keyword=keyword,
                    text=None, data=data, encoding="binary",
                )
            )
