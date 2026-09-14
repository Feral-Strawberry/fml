"""Bild-Container-Extraktor über Pillow (Schicht 1) — JPEG, WEBP, GIF, BMP, TIFF.

Pillow wird hier ausschließlich als **Container-Öffner** genutzt (ADR 0008): es
liest die Metadaten-Segmente aus dem Umschlag (EXIF, XMP, ICC, Kommentare, …),
wir speichern sie **unverändert mit Quell-Label**. Interpretiert wird nichts —
das ist Schicht 2 (ADR 0004).

Pillow legt beim Öffnen alle gefundenen Container-Metadaten in ``Image.info`` ab:
Bytes-Werte (z. B. ``exif``, ``xmp``, ``icc_profile``) übernehmen wir byte-exakt
als Binär-Einträge, Text-Werte (z. B. ``comment`` bei GIF) als Text-Einträge.
Sonstige skalare Info-Werte (Zahlen/Tupel wie ``loop``, ``duration``) werden als
Text festgehalten — auch sie sind Teil des Umschlags.

**C2PA-Manifeste** (Content Credentials, ADR 0066) liefert Pillow nicht über
``Image.info``; sie werden hier zusätzlich byte-treu gesichert:

- JPEG: APP11-Segmente mit Kennung ``JP`` (JUMBF-in-JPEG, C2PA-Spec 2.4). Ein
  Manifest kann über mehrere Segmente gehen (max. 64000 Byte Nutzlast je
  Segment); Fortsetzungen wiederholen Kennung, Box-Instanz, Paketnummer und
  den 8-Byte-Superbox-Kopf. Die Segmente werden je Box-Instanz nach
  Paketnummer sortiert und zu EINEM Eintrag ``jpeg:APP11`` zusammengesetzt.
- WebP: RIFF-Chunk mit FourCC ``C2PA`` (kleiner eigener RIFF-Walk, Pillow
  reicht ihn nicht durch) → Eintrag ``webp:C2PA``.

Defensiv (Projektregel): beschädigte Dateien werfen nicht, sondern liefern eine
leere Extraktion mit ``warnings``.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import BinaryIO

from PIL import ExifTags, Image, UnidentifiedImageError

from .types import ContainerExtraction, RawMetadataItem

# Container, die dieser Extraktor bedient (PNG bleibt beim Stdlib-Eigenbau).
CONTAINERS = ("jpeg", "webp", "gif", "bmp", "tiff")

# ComfyUI-Konvention in EXIF-Textfeldern (SaveAnimatedWEBP u. a.): der Wert
# beginnt mit "prompt:{…}" bzw. "workflow:{…}" — das eingebettete Label ist
# ComfyUIs eigener Schlüssel, wir übernehmen ihn als Keyword (das Quell-Label
# behält den EXIF-Tag-Namen, ADR 0016).
_EMBEDDED_KEY = re.compile(r"^(prompt|workflow):\s*(?=[\[{])", re.IGNORECASE)

# JUMBF-in-JPEG (C2PA-Spec 2.4 / ISO 19566-5): Segment-Nutzlast beginnt mit
# CI ``JP`` (2), En = Box-Instanz (2, BE), Z = Paketnummer (4, BE, ab 1),
# dann der JUMBF-Superbox (LBox 4 + TBox ``jumb``). Fortsetzungen (Z > 1)
# wiederholen CI/En/Z UND den 8-Byte-Superbox-Kopf.
_JUMBF_CI = b"JP"
_JUMBF_PREFIX = 8          # CI + En + Z
_JUMBF_BOX_HEADER = 8      # LBox + TBox

# Deckel für einen einzelnen RIFF-Chunk beim WebP-Walk (C2PA-Manifeste sind
# Kilobytes bis wenige Megabytes; alles darüber ist eine defekte Datei).
_MAX_RIFF_CHUNK = 64 * 1024 * 1024


def extract(source: str | Path | BinaryIO, *, container: str) -> ContainerExtraction:
    """Extrahiere alle Roh-Metadaten aus einer Bilddatei über Pillow.

    `source` ist ein Dateipfad oder ein geöffneter Binärstrom; `container` ist der
    über Magic Bytes erkannte Container-Name (bestimmt das Quell-Label der
    Einträge). Wirft nicht bei beschädigten Dateien — Probleme landen in
    `warnings`.
    """
    result = ContainerExtraction(container=container)
    exif_items: list[RawMetadataItem] = []
    c2pa_items: list[RawMetadataItem] = []
    try:
        with Image.open(source) as img:
            img.load()  # Metadaten mancher Formate stehen erst nach load() bereit
            info = dict(img.info)
            exif_items = _decode_exif_text(img, container)
            if container == "jpeg":
                c2pa_items = _jpeg_c2pa_items(getattr(img, "applist", None) or [])
            result.width, result.height = img.size
            # Animiertes GIF/WEBP: fps aus der Frame-Dauer (Millisekunden).
            duration = info.get("duration")
            if getattr(img, "is_animated", False) and isinstance(duration, (int, float)) and duration > 0:
                result.fps = round(1000 / duration, 2)
    except UnidentifiedImageError:
        result.warnings.append(f"Pillow konnte die Datei nicht als Bild öffnen ({container}).")
        return result
    except OSError as exc:
        result.warnings.append(f"Lesefehler beim Öffnen über Pillow: {exc}")
        return result
    except Exception as exc:  # Pillow-Plugins werfen teils eigene Fehlerklassen
        result.warnings.append(f"Pillow-Fehler: {exc.__class__.__name__}: {exc}")
        return result

    for key in sorted(info):
        value = info[key]
        source_label = f"{container}:info"
        if isinstance(value, bytes):
            result.items.append(
                RawMetadataItem(
                    source=source_label, keyword=key,
                    text=None, data=value, encoding="binary",
                )
            )
        elif isinstance(value, str):
            result.items.append(
                RawMetadataItem(
                    source=source_label, keyword=key,
                    text=value, data=None, encoding="utf-8",
                )
            )
        elif isinstance(value, (int, float, tuple, list, bool)):
            result.items.append(
                RawMetadataItem(
                    source=source_label, keyword=key,
                    text=str(value), data=None, encoding="utf-8",
                )
            )
        # Andere Typen (verschachtelte Plugin-Objekte) sind keine Container-
        # Metadaten im Sinne von Schicht 1 — bewusst überspringen.

    result.items.extend(exif_items)
    if container == "webp":
        c2pa_items = _webp_c2pa_items(source, result)
    result.items.extend(c2pa_items)
    return result


def _jpeg_c2pa_items(applist: list[tuple[str, bytes]]) -> list[RawMetadataItem]:
    """JUMBF-Segmente (APP11 mit Kennung ``JP``) je Box-Instanz zusammensetzen.

    Reihenfolge nach Paketnummer (Z), nicht nach Dateireihenfolge — die Spec
    erlaubt beliebige Anordnung. Fortsetzungen verlieren ihren wiederholten
    Superbox-Kopf, damit das Ergebnis EIN zusammenhängender JUMBF-Baum ist
    (so setzt es auch c2pa-rs zusammen). Andere APP11-Nutzungen (z. B. JPEG
    XT ohne ``JP``) bleiben unberührt.
    """
    by_instance: dict[int, list[tuple[int, bytes]]] = {}
    for marker, payload in applist:
        if marker != "APP11" or len(payload) < _JUMBF_PREFIX + _JUMBF_BOX_HEADER:
            continue
        if payload[:2] != _JUMBF_CI:
            continue
        instance, sequence = struct.unpack(">HI", payload[2:8])
        by_instance.setdefault(instance, []).append((sequence, payload[_JUMBF_PREFIX:]))
    items: list[RawMetadataItem] = []
    for instance in sorted(by_instance):
        parts = sorted(by_instance[instance], key=lambda p: p[0])
        first_sequence = parts[0][0]
        buf = bytearray()
        for sequence, body in parts:
            buf += body if sequence == first_sequence else body[_JUMBF_BOX_HEADER:]
        items.append(
            RawMetadataItem(
                source="jpeg:APP11", keyword=None,
                text=None, data=bytes(buf), encoding="binary",
            )
        )
    return items


def _webp_c2pa_items(
    source: str | Path | BinaryIO, result: ContainerExtraction
) -> list[RawMetadataItem]:
    """RIFF-Walk durch eine WebP-Datei: Chunks ``FourCC + Länge(LE) + Daten``,
    auf gerade Länge gepolstert; gesucht wird die FourCC ``C2PA``. Alles
    andere wird per ``seek`` übersprungen, ohne es zu laden."""
    items: list[RawMetadataItem] = []
    try:
        if hasattr(source, "read"):
            stream = source  # type: ignore[assignment]
            stream.seek(0)
            items = _walk_riff(stream)
        else:
            with open(source, "rb") as fh:
                items = _walk_riff(fh)
    except (OSError, ValueError) as exc:
        result.warnings.append(f"RIFF-Walk (C2PA) abgebrochen: {exc}")
    return items


def _walk_riff(stream: BinaryIO) -> list[RawMetadataItem]:
    head = stream.read(12)
    if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WEBP":
        return []
    items: list[RawMetadataItem] = []
    while True:
        header = stream.read(8)
        if len(header) < 8:
            break
        fourcc = header[:4]
        length = struct.unpack("<I", header[4:8])[0]
        padded = length + (length & 1)
        if fourcc == b"C2PA":
            if length > _MAX_RIFF_CHUNK:
                raise ValueError(f"C2PA-Chunk meldet unplausible Länge {length}")
            data = stream.read(length)
            if data:
                items.append(
                    RawMetadataItem(
                        source="webp:C2PA", keyword=None,
                        text=None, data=data, encoding="binary",
                    )
                )
            if len(data) < length:
                break  # abgeschnitten — was da ist, bleibt trotzdem gesichert
            if length & 1:
                stream.read(1)
        else:
            stream.seek(padded, 1)
    return items


def _decode_exif_text(img: Image.Image, container: str) -> list[RawMetadataItem]:
    """EXIF-**Textfelder** zusätzlich als lesbare Einträge ablegen (ADR 0016).

    Der komplette EXIF-Block bleibt als Binär-Eintrag erhalten (verlustfrei);
    hier werden nur String-Tags des Haupt-IFD dekodiert, damit Schicht 2 und
    die Suche sie sehen. ComfyUI legt bei WEBP Prompt/Workflow als
    ``Model="prompt:{…}"`` / ``Make="workflow:{…}"`` ab — dann übernimmt das
    Keyword ComfyUIs eingebettetes Label, das Quell-Label nennt den EXIF-Tag.
    """
    items: list[RawMetadataItem] = []
    try:
        exif = img.getexif()
    except Exception:  # defekter EXIF-Block darf die Extraktion nicht stoppen
        return items
    for tag_id, value in exif.items():
        if not isinstance(value, str) or not value.strip():
            continue
        tag_name = ExifTags.TAGS.get(tag_id, f"0x{tag_id:04x}")
        match = _EMBEDDED_KEY.match(value)
        if match:
            items.append(
                RawMetadataItem(
                    source=f"{container}:exif.{tag_name}",
                    keyword=match.group(1).lower(),
                    text=value[match.end():], data=None, encoding="utf-8",
                )
            )
        else:
            items.append(
                RawMetadataItem(
                    source=f"{container}:exif", keyword=tag_name,
                    text=value, data=None, encoding="utf-8",
                )
            )
    return items
