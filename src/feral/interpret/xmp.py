"""Schicht-2-Parser: XMP-Pakete (Adobe/IPTC-Standard) — inkl. Midjourney.

Viele Tools, die keine eigenen Parameter einbetten, hinterlassen trotzdem ein
**XMP-Paket** (`<x:xmpmeta>` in PNG-iTXt ``XML:com.adobe.xmp``, WEBP-XMP-Chunk,
JPEG-APP1). Daraus lässt sich Standardisiertes ziehen (XMP-/IPTC-Spezifikation):

- ``dc:description``       — bei **Midjourney** der Prompt, gefolgt von
                              ``Job ID: <uuid>`` (laut Midjourney-Doku); sonst
                              eine Bildbeschreibung.
- ``photoshop:Credit``      — z. B. ``"Made with Google AI"`` (Gemini/Imagen).
- ``Iptc4xmpExt:DigitalSourceType`` — IPTC-Kennzeichnung für AI-Bilder
                              (``…/trainedAlgorithmicMedia`` u. ä.).
- ``xmp:CreatorTool``       — erzeugendes/bearbeitendes Programm.
- ``xmp:Rating``            — Bewertung (z. B. aus Lightroom) — extrahiert,
                              nicht manuell: bleibt Schicht 2 (ADR 0005).

XMP erlaubt Eigenschaften als XML-**Attribute** oder als **Kind-Elemente**
(dc:description meist als ``rdf:Alt``/``rdf:li``) — beide Formen werden gelesen.
Defensiv: kaputtes XML ⇒ Parser fühlt sich nicht zuständig, kein Fehler.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Sequence

from ..extract.types import RawMetadataItem
from .types import InterpretedField, Interpretation

NAME = "xmp"
VERSION = 1

_NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "photoshop": "http://ns.adobe.com/photoshop/1.0/",
    "iptcext": "http://iptc.org/std/Iptc4xmpExt/2008-02-29/",
}

# (Namespace-URI, Attribut-/Elementname) → kanonisches Feld.
_PROPERTY_MAP = {
    (_NS["photoshop"], "Credit"): "credit",
    (_NS["iptcext"], "DigitalSourceType"): "ai_source_type",
    (_NS["xmp"], "CreatorTool"): "creator_tool",
    (_NS["xmp"], "Rating"): "rating",
}

# Midjourney-Signatur am Ende der Beschreibung: "<prompt> Job ID: <uuid>"
_JOB_ID = re.compile(r"\s*Job ID:\s*([0-9a-fA-F-]{8,})\s*$")


def parse(items: Sequence[RawMetadataItem]) -> Interpretation | None:
    """Interpretiere das erste lesbare XMP-Paket der Datei (falls vorhanden)."""
    root = _first_xmp_root(items)
    if root is None:
        return None

    properties = _collect_properties(root)
    fields: list[InterpretedField] = []

    description = properties.pop("__description__", None)
    if description:
        match = _JOB_ID.search(description)
        if match:  # Midjourney: Beschreibung = Prompt + Job ID
            fields.append(InterpretedField("tool", "midjourney"))
            prompt = _JOB_ID.sub("", description).strip()
            if prompt:
                fields.append(InterpretedField("prompt", prompt))
            fields.append(InterpretedField("job_id", match.group(1)))
        else:
            fields.append(InterpretedField("description", description))

    for field, value in properties.items():
        fields.append(InterpretedField(field, value))

    if not fields:
        return None
    return Interpretation(parser=NAME, parser_version=VERSION, fields=fields)


def _first_xmp_root(items: Sequence[RawMetadataItem]) -> ET.Element | None:
    """Das erste als XML lesbare XMP-Paket aus den Roh-Einträgen."""
    for item in items:
        text = item.text
        if text is None and item.data is not None and b"x:xmpmeta" in item.data:
            text = item.data.decode("utf-8", errors="replace")
        if not text or "x:xmpmeta" not in text:
            continue
        # Härtung (ADR 0032): XMP-Pakete tragen NIE einen DTD-/Entity-Block.
        # Einen dennoch vorhandenen ablehnen — ElementTree expandiert interne
        # Entities und wäre sonst für „billion laughs"/quadratische Aufblähung
        # anfällig (das XML stammt aus fremden Dateien). Externe Entities holt
        # ElementTree ohnehin nicht (kein XXE). Legitime Dateien verlieren nichts.
        if "<!DOCTYPE" in text or "<!ENTITY" in text:
            continue
        # xpacket-Hülle abstreifen; ElementTree will genau ein Wurzelelement.
        start = text.find("<x:xmpmeta")
        end = text.rfind("</x:xmpmeta>")
        if start == -1 or end == -1:
            continue
        try:
            return ET.fromstring(text[start : end + len("</x:xmpmeta>")])
        except ET.ParseError:
            continue
    return None


def _collect_properties(root: ET.Element) -> dict[str, str]:
    """Bekannte XMP-Eigenschaften einsammeln — als Attribute und als Elemente."""
    found: dict[str, str] = {}

    def add(uri: str, local: str, value: str | None) -> None:
        value = (value or "").strip()
        if not value:
            return
        if (uri, local) == (_NS["dc"], "description"):
            found.setdefault("__description__", value)
            return
        canonical = _PROPERTY_MAP.get((uri, local))
        if canonical == "ai_source_type":
            value = value.rsplit("/", 1)[-1]  # IPTC-URI → kurzer Begriff
        if canonical:
            found.setdefault(canonical, value)

    for element in root.iter():
        for qname, value in element.attrib.items():
            if qname.startswith("{"):
                uri, _, local = qname[1:].partition("}")
                add(uri, local, value)
        if element.tag.startswith("{"):
            uri, _, local = element.tag[1:].partition("}")
            if (uri, local) == (_NS["dc"], "description"):
                # Elementform: dc:description > rdf:Alt > rdf:li
                li = element.find(
                    "rdf:Alt/rdf:li",
                    {"rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"},
                )
                add(uri, local, li.text if li is not None else element.text)
            elif (uri, local) in _PROPERTY_MAP:
                add(uri, local, element.text)

    return found
