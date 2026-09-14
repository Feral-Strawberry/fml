"""Schicht-2-Parser: Topaz Photo AI / Gigapixel / Video AI (Issue #44, ADR 0066).

Topaz-Werkzeuge erzeugen nichts, sie skalieren hoch und schärfen — für die
Bibliothek zählen sie trotzdem **wie ein Modell** (Feral Strawberry, 2026-09-06): das
Feld ``model`` bekommt „Topaz Photo AI" / „Topaz Gigapixel" / „Topaz Video AI",
damit Modell-Facette und ``model:``-Chip direkt greifen. Ein manuell gesetztes
Modell hat weiter Vorrang (ADR 0005/0022). Daneben stehen Rohfelder:

- ``topaz_version``    Programmversion (``3.2.2``, ``1.0.7``)
- ``topaz_model``      Topaz-Modellname bzw. -Kürzel (``High Compression``,
                       ``prob-3``, ``chr-2`` — mehrfach möglich bei Ketten)
- ``upscale_factor``   Vergrößerung (``2x``)
- ``source_size``      Größe vor der Bearbeitung (``1200x593``)
- ``size``             Zielgröße (kanonisch, wie bei den Generatoren)
- ``topaz_settings``   die vollständige Einstellungszeile, unverändert

Belegte Signaturen (Recherche 2026-09-07, Community-Dumps — Topaz dokumentiert
nichts offiziell; Details in der Konzeptnotiz zu ADR 0066 im Arbeitsrepo):

- **Photo AI**: EXIF ``Software`` / XMP ``xmp:CreatorTool`` =
  ``Topaz Photo AI 3.2.2 (Windows)``. Einstellungen laut Hersteller im
  Beschreibungsfeld (Format nicht belegt → nur roh übernommen).
- **Gigapixel**: ``ImageDescription`` / ``dc:description`` =
  ``Upscaled with Gigapixel v1.0.7. 1200x593 => 2400x1186 (2x) Model: High
  Compression, denoise: 0.2585…, sharpen: 0.4128….`` (abschaltbar per
  „Embed image settings").
- **Video AI**: ffprobe-Format-Tag ``videoai`` (MKV: ``VIDEOAI``) =
  ``Enhanced using prob-3 with recover details at 43, … Changed resolution
  to 1266x960`` bzw. ``Slowmo 400% and framerate changed to 29.97 using
  chr-2 … Enhanced using prob-3 auto …``.

Defensiv: Der Parser fühlt sich nur zuständig, wenn eine dieser Signaturen
an der belegten Stelle steht (Software/CreatorTool/Beschreibung/``videoai``),
nicht bei bloßer Erwähnung im Prompt.
"""

from __future__ import annotations

import html
import re
from typing import Sequence

from ..extract.types import RawMetadataItem
from .types import InterpretedField, Interpretation

NAME = "topaz"
VERSION = 2   # v2: schreibt zusätzlich tool = topaz (Plattform, Konzeptrunde 2026-09-08)

MODEL_PHOTO_AI = "Topaz Photo AI"
MODEL_GIGAPIXEL = "Topaz Gigapixel"
MODEL_VIDEO_AI = "Topaz Video AI"

# Programmkennungen in Software/CreatorTool-Feldern.
_PHOTO_AI = re.compile(r"Topaz Photo AI\s+v?(\d+(?:\.\d+)+)", re.IGNORECASE)
_GIGAPIXEL_SW = re.compile(r"(?:Topaz\s+)?Gigapixel(?:\s+AI)?\s+v?(\d+(?:\.\d+)+)", re.IGNORECASE)

# Gigapixel-Einstellungszeile in der Beschreibung (spezifisch genug, um in
# jedem Textfeld gesucht zu werden).
_GIGAPIXEL_DESC = re.compile(
    r"Upscaled with (?:Topaz\s+)?Gigapixel(?:\s+AI)?\s+v?(?P<version>\d+(?:\.\d+)+)\.?"
    r"\s*(?P<src>\d+x\d+)\s*=>\s*(?P<dst>\d+x\d+)"
    r"\s*\((?P<factor>\d+(?:\.\d+)?)x\)"
    r"(?:\s*Model:\s*(?P<model>[^,.]+?)\s*(?=,|\.|$))?",
    re.IGNORECASE,
)

# Video AI: Modellkürzel nach "using", Zielgröße, Slowmo.
_VIDEO_MODEL = re.compile(r"\busing\s+([a-z]{2,5}-\d{1,3})\b", re.IGNORECASE)
_VIDEO_SIZE = re.compile(r"Changed resolution to\s+(\d+x\d+)", re.IGNORECASE)
_VIDEO_SIGNATURE = re.compile(
    r"^\s*(Enhanced using|Slowmo|Changed resolution|Deinterlaced|Stabilized|Frame interpolation)",
    re.IGNORECASE,
)

# XMP: CreatorTool als Attribut oder Element.
_XMP_CREATOR_TOOL = re.compile(
    r'(?:xmp:CreatorTool\s*=\s*"([^"]*)"|<xmp:CreatorTool>([^<]*)</xmp:CreatorTool>)',
    re.IGNORECASE,
)

# XMP: dc:description als Attribut oder als rdf:Alt/rdf:li-Element.
_XMP_DESCRIPTION = re.compile(
    r'(?:dc:description\s*=\s*"([^"]*)"|<dc:description>.*?<rdf:li[^>]*>([^<]*)</rdf:li>)',
    re.IGNORECASE | re.DOTALL,
)

_SOFTWARE_KEYWORDS = frozenset({"software", "creatortool", "creator_tool"})
# Beschreibungsfelder; UserComment bewusst NICHT dabei — dort liegen bei JPEG
# die A1111-Parameter, die wären als „Topaz-Einstellungen" falsch.
_DESCRIPTION_KEYWORDS = frozenset({"imagedescription", "description"})


def parse(items: Sequence[RawMetadataItem]) -> Interpretation | None:
    """Erkenne Topaz-Signaturen in den Roh-Einträgen einer Datei."""
    fields: list[InterpretedField] = []
    seen_models: set[str] = set()

    def add_model(name: str) -> None:
        if name not in seen_models:
            seen_models.add(name)
            fields.append(InterpretedField("model", name))

    texts = [(item, _text_of(item)) for item in items]
    texts = [(item, text) for item, text in texts if text]
    # Plattform (Facette „Generator"): Topaz ist die Plattform, Photo AI /
    # Gigapixel / Video AI sind ihre „Modelle" (Feral Strawberry, 2026-09-08).
    # Wird nur gesetzt, wenn unten ein Produkt erkannt wurde (siehe Ende).

    # -- Video AI: Container-Tag `videoai` ------------------------------------------
    for item, text in texts:
        if (item.keyword or "").lower() != "videoai" or not _VIDEO_SIGNATURE.match(text):
            continue
        add_model(MODEL_VIDEO_AI)
        for m in _VIDEO_MODEL.finditer(text):
            fields.append(InterpretedField("topaz_model", m.group(1).lower()))
        size = _VIDEO_SIZE.search(text)
        if size:
            fields.append(InterpretedField("size", size.group(1)))
        fields.append(InterpretedField("topaz_settings", text.strip()))

    # -- Software / CreatorTool: Photo AI, Gigapixel ----------------------------------
    for item, text in texts:
        for value in _software_values(item, text):
            m = _PHOTO_AI.search(value)
            if m:
                add_model(MODEL_PHOTO_AI)
                fields.append(InterpretedField("topaz_version", m.group(1)))
                continue
            m = _GIGAPIXEL_SW.search(value)
            if m and "upscaled with" not in value.lower():
                add_model(MODEL_GIGAPIXEL)
                fields.append(InterpretedField("topaz_version", m.group(1)))

    # -- Gigapixel-Einstellungszeile (überall, die Signatur ist eindeutig) -------------
    gigapixel_seen = False
    for item, text in texts:
        for value in _description_values(item, text):
            m = _GIGAPIXEL_DESC.search(value)
            if not m or gigapixel_seen:
                continue
            gigapixel_seen = True
            add_model(MODEL_GIGAPIXEL)
            if not any(f.field == "topaz_version" and f.value == m["version"] for f in fields):
                fields.append(InterpretedField("topaz_version", m["version"]))
            if m["model"]:
                fields.append(InterpretedField("topaz_model", m["model"].strip()))
            fields.append(InterpretedField("upscale_factor", f"{m['factor']}x"))
            fields.append(InterpretedField("source_size", m["src"]))
            fields.append(InterpretedField("size", m["dst"]))
            fields.append(InterpretedField("topaz_settings", value.strip()))

    # -- Photo AI: Einstellungen im Beschreibungsfeld (Format nicht belegt → roh) -----
    if MODEL_PHOTO_AI in seen_models and not gigapixel_seen:
        for item, text in texts:
            if (item.keyword or "").lower() in _DESCRIPTION_KEYWORDS and text.strip():
                fields.append(InterpretedField("topaz_settings", text.strip()))
                break

    if not fields:
        return None
    fields.insert(0, InterpretedField("tool", NAME))
    return Interpretation(parser=NAME, parser_version=VERSION, fields=fields)


def _text_of(item: RawMetadataItem) -> str | None:
    if item.text:
        return item.text
    if item.data is not None and b"x:xmpmeta" in item.data:
        return item.data.decode("utf-8", errors="replace")
    return None


def _software_values(item: RawMetadataItem, text: str) -> list[str]:
    """Werte, die ein Programm benennen: EXIF Software, XMP CreatorTool."""
    if (item.keyword or "").lower() in _SOFTWARE_KEYWORDS:
        return [text]
    if "x:xmpmeta" in text:
        return [html.unescape(a or b) for a, b in _XMP_CREATOR_TOOL.findall(text)]
    return []


def _description_values(item: RawMetadataItem, text: str) -> list[str]:
    """Beschreibungsfelder: EXIF ImageDescription, PNG Description, XMP dc:description."""
    keyword = (item.keyword or "").lower()
    if keyword in _DESCRIPTION_KEYWORDS:
        return [text]
    if "x:xmpmeta" in text:
        return [html.unescape(a or b) for a, b in _XMP_DESCRIPTION.findall(text)]
    return []
