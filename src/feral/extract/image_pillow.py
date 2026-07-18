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

Defensiv (CLAUDE.md §8): beschädigte Dateien werfen nicht, sondern liefern eine
leere Extraktion mit ``warnings``.
"""

from __future__ import annotations

import re
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


def extract(source: str | Path | BinaryIO, *, container: str) -> ContainerExtraction:
    """Extrahiere alle Roh-Metadaten aus einer Bilddatei über Pillow.

    `source` ist ein Dateipfad oder ein geöffneter Binärstrom; `container` ist der
    über Magic Bytes erkannte Container-Name (bestimmt das Quell-Label der
    Einträge). Wirft nicht bei beschädigten Dateien — Probleme landen in
    `warnings`.
    """
    result = ContainerExtraction(container=container)
    exif_items: list[RawMetadataItem] = []
    try:
        with Image.open(source) as img:
            img.load()  # Metadaten mancher Formate stehen erst nach load() bereit
            info = dict(img.info)
            exif_items = _decode_exif_text(img, container)
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
    return result


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
