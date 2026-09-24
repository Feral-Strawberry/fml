"""Schicht-2-Parser: Suno-Songs (ADR 0083, Recherche §2 und §12).

Suno bettet keinen Style-Prompt ein, aber die **Identität** eines Clips:

- Kommentar ``made with suno[ studio]; created=<ISO-Zeit>; id=<clip-uuid>``
  — in MP3 als ``COMM`` UND/ODER ``TXXX:comment``, in WAV als ``ICMT``, in
  M4A als ``comment``-Tag (ffprobe). Zeit mit oder ohne Millisekunden.
- ``WOAS`` = ``https://suno.com/song/<clip-uuid>``.
- C2PA (seit ca. 08/2026, MP3-``GEOB``): ``claim_generator_info`` =
  ``{name: "Suno", version: "<Modell-Codename>"}`` → Modellversion über
  die Codename-Tabelle (Recherche §2.1).
- Tags von Community-Downloadern (Recherche §2.4, Quellcode geprüft):
  SunoSync ``TXXX:SUNO_UUID``; rs-suno ``SUNO_ID``, ``SUNO_URL``,
  ``SUNO_STYLE`` (= Style → ``prompt``), ``SUNO_STYLE_SUMMARY`` (=
  Beschreibungsprompt → ``description``), ``SUNO_MODEL`` (``chirp-crow
  (v5)``), ``SUNO_PARENT`` + ``SUNO_LINEAGE`` (``Extended from 1a2b3c4d``).

Felder: ``tool`` = ``suno``, ``model`` (``Suno v5``), ``song_id``,
``parent_id``, ``relation``, ``prompt``, ``description``. Titel, Songtext
und Technik liefert der allgemeine ``audio``-Parser. Die Erstellzeit wird
KEIN Feld, sondern Mediendatum (``created_at`` für die Datumskaskade).

Nicht geraten wird: SunoSyncs ``TXXX:prompt`` und rs-sunos ``SUNO_PROMPT``
(bei Suno heißt der Songtext intern „prompt" — welcher Text dort steht, ist
nicht belegt), geschke-Downloads (keine Suno-Kennung in den Tags).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Sequence

from ..extract.types import RawMetadataItem
from . import provenance
from .types import InterpretedField, Interpretation

NAME = "suno"
VERSION = 1

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_NULL_UUID = "00000000-0000-0000-0000-000000000000"
_COMMENT = re.compile(r"^\s*made with suno(?: studio)?\s*;", re.IGNORECASE)
_COMMENT_CREATED = re.compile(r"created=([0-9T:.\-]+Z?)", re.IGNORECASE)
_COMMENT_ID = re.compile(rf"\bid=(?:m_)?({_UUID})", re.IGNORECASE)
_SONG_URL = re.compile(rf"suno\.(?:com|ai)/song/(?:m_)?({_UUID})", re.IGNORECASE)
_UUID_ONLY = re.compile(rf"^\s*(?:m_)?({_UUID})\s*$", re.IGNORECASE)
# Deckel: Kommentare sind kurz; Songtexte (USLT) sind nie der Suno-Kommentar.
_MAX_COMMENT = 1024

# Modell-Codename (API ``model_name``, C2PA-Version) → UI-Version, Recherche
# §2.1 (A). Längster Präfix gewinnt, Grenze an ``-`` (``chirp-auk-turbo-t2``
# ist v4.5, ``chirp-v3-5`` nicht v3).
_CODENAMES = {
    "chirp-v2-xxl-alpha": "v2", "chirp-v3-0": "v3", "chirp-v3-5": "v3.5",
    "chirp-v4": "v4", "chirp-auk": "v4.5", "chirp-bluejay": "v4.5+",
    "chirp-crow": "v5", "chirp-fenix": "v5.5", "chirp-hawk": "v6",
    "chirp-goose": "v6-mini",
    "chirp-bass": "v4.5+ Remaster", "chirp-carp": "v5 Remaster",
    "chirp-flounder": "v5.5 Remaster",
}
_CODENAME_ORDER = sorted(_CODENAMES, key=len, reverse=True)

# rs-suno ``SUNO_LINEAGE`` (erste Zeile „<Kante> <Eltern-ID[:8]>") →
# Beziehungsart (``lineage.rs`` EdgeType::label).
_RELATIONS = (
    ("cover of", "cover"), ("remaster of", "remaster"),
    ("speed-edited from", "speed_edit"), ("edited from", "edit"),
    ("extended from", "extend"), ("section replaced from", "section_replace"),
    ("stitched from", "stitch"), ("derived from", "derived"),
)


_KEY_SYSTEM_VERSION = bytes([0x60 + len("systemVersion")]) + b"systemVersion"
_UI_VERSION = re.compile(r"^v?(\d+(?:\.\d+)?\+?(?:-[a-z]+)?)$", re.IGNORECASE)


def _version_label(text: str) -> str | None:
    """``v5.5`` / ``5.5`` / ``v6-mini`` → ``Suno v5.5``; sonst ``None``."""
    m = _UI_VERSION.match(text.strip())
    return f"Suno v{m.group(1).lower()}" if m else None


def model_label(codename: str) -> str | None:
    """``chirp-auk-turbo-t2`` → ``Suno v4.5``; unbekannter ``chirp-…``-Name →
    ``Suno <codename>`` (lieber roh als geraten); sonst ``None``."""
    code = codename.strip().lower()
    for known in _CODENAME_ORDER:
        if code == known or code.startswith(known + "-"):
            return f"Suno {_CODENAMES[known]}"
    return f"Suno {code}" if code.startswith("chirp-") else None


def _comments(items: Sequence[RawMetadataItem]) -> list[str]:
    return [i.text for i in items
            if i.text and len(i.text) <= _MAX_COMMENT and _COMMENT.match(i.text)]


def _tags(items: Sequence[RawMetadataItem]) -> dict[str, str]:
    """Downloader-Tags nach Schlüssel (Großschreibung; erster Wert gewinnt) —
    unabhängig vom Container: ID3-``TXXX``, Vorbis-Kommentar, M4A-Freiform."""
    tags: dict[str, str] = {}
    for item in items:
        key = (item.keyword or "").upper()
        if key.startswith("SUNO_") and item.text and item.text.strip():
            tags.setdefault(key, item.text.strip())
    return tags


def _c2pa_suno(items: Sequence[RawMetadataItem]) -> list[bytes]:
    return [i.data for i in items
            if i.data is not None and b"Suno" in i.data and provenance.is_c2pa(i.data)]


def parse(items: Sequence[RawMetadataItem]) -> Interpretation | None:
    comments = _comments(items)
    tags = _tags(items)
    urls: list[str] = []
    for item in items:
        if item.text and (item.source.startswith("id3v2:W")
                          or (item.keyword or "").upper() == "SUNO_URL"):
            m = _SONG_URL.search(item.text)
            if m:
                urls.append(m.group(1).lower())
    c2pa = _c2pa_suno(items)
    if not (comments or urls or c2pa or "SUNO_ID" in tags or "SUNO_UUID" in tags):
        return None

    fields: list[InterpretedField] = [InterpretedField("tool", NAME)]
    seen: set[tuple[str, str]] = {("tool", NAME)}

    def add(field: str, value: str | None) -> None:
        if value and (field, value) not in seen:
            seen.add((field, value))
            fields.append(InterpretedField(field, value))

    # Modell: C2PA (Codename der Datei selbst) vor rs-suno-Tag.
    for blob in c2pa:
        for generator in provenance._claim_generators(blob):
            name, _, version = generator.partition(" ")
            if name == "Suno" and version:
                add("model", model_label(version))
    # Rückfall: Sunos eigene Assertion ``com.suno.provenance`` nennt
    # ``systemVersion`` (suno.com/safety: „v5.5") — falls der Codename fehlt.
    if not any(f.field == "model" for f in fields):
        for blob in c2pa:
            for version in provenance._values_after(blob, _KEY_SYSTEM_VERSION):
                add("model", model_label(version) or _version_label(version))
    if "SUNO_MODEL" in tags:
        add("model", model_label(tags["SUNO_MODEL"].split("(")[0]))

    ids = [m.group(1).lower() for c in comments for m in [_COMMENT_ID.search(c)] if m]
    ids += urls
    for key in ("SUNO_ID", "SUNO_UUID"):
        m = _UUID_ONLY.match(tags.get(key, ""))
        if m:
            ids.append(m.group(1).lower())
    for song_id in ids:
        add("song_id", song_id)

    parent = _UUID_ONLY.match(tags.get("SUNO_PARENT", ""))
    if parent and parent.group(1).lower() != _NULL_UUID:
        add("parent_id", parent.group(1).lower())
    lineage = tags.get("SUNO_LINEAGE", "").splitlines()[:1]
    for line in lineage:
        low = line.lower()
        for label, relation in _RELATIONS:
            if low.startswith(label):
                add("relation", relation)
                break

    add("prompt", tags.get("SUNO_STYLE"))
    add("description", tags.get("SUNO_STYLE_SUMMARY"))
    return Interpretation(parser=NAME, parser_version=VERSION, fields=fields)


def created_at(items: Sequence[RawMetadataItem]) -> datetime | None:
    """Erstellzeit des Clips aus dem Suno-Kommentar (UTC) — Mediendatum für
    die Datumskaskade (``importer``), mit oder ohne Millisekunden."""
    for comment in _comments(items):
        m = _COMMENT_CREATED.search(comment)
        if m is None:
            continue
        parsed = parse_created(m.group(1))
        if parsed is not None:
            return parsed
    return None


def parse_created(text: str) -> datetime | None:
    stamp = text.strip().rstrip("Zz").split(".")[0]
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
