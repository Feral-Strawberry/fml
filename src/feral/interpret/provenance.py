"""Schicht-2-Parser: Herkunft aus C2PA-Manifesten und XMP-Credit (Issue #43, ADR 0066).

Gemini, ChatGPT, Firefly & Co. betten keine Prompts ein, aber **Content
Credentials** (C2PA): ein JUMBF-Baum mit CBOR-Claims, den Schicht 1 byte-treu
sichert (``png:caBX``, ``jpeg:APP11``, ``webp:C2PA``; Audio: ID3-``GEOB``,
``riff:C2PA``, ``isobmff:uuid``). Alle Textwerte darin
(``claim_generator``, ``claim_generator_info``, ``softwareAgent``, Zertifikats-
Aussteller, ``digitalSourceType``-URIs) liegen als UTF-8-Klartext im Payload —
**kein CBOR-Parser nötig**: Erzeuger werden per Substring erkannt, die
Rohstrings über den 1–3 Byte langen Kopf eines CBOR-Textstrings gelesen.

Ergebnis (Feldvokabular ``interpret/types.py``):

- ``tool``             **Plattform** (Konzeptrunde 2026-09-08, ADR-0066-Nachtrag):
                       ``google``, ``openai``, ``azure-openai``, ``adobe``, ``flux``,
                       ``suno`` — oder
                       ``c2pa`` = Manifest erkannt, kein belegter Marker. Die
                       Produkte darunter (Gemini, Google Fotos, GPT-4o, DALL·E 3,
                       Sora, Adobe Firefly) landen in ``model``, soweit belegt.
- ``model``            Produkt/Modell der Plattform, wo die Metadaten es nennen:
                       ``GPT-4o``, ``DALL-E 3``, ``Sora``, ``Adobe Firefly``,
                       ``Google Fotos``, ``Flux.1`` (Rohstring). Gemini nennt
                       kein Modell → bleibt manuell.
- ``claim_generator``  exakter Rohstring des Claim-Erzeugers (``DALL-E/3.0
                       c2pa-rs/0.28.4``, ``Adobe Photoshop/25.7.0 …``; aus
                       ``claim_generator_info`` als „Name Version")
- ``software_agent``   exakter Rohstring der Aktion (``GPT-4o``, ``Adobe
                       Firefly 1.0``, ``Azure OpenAI ImageGen``)
- ``ai_source_type``   IPTC-Begriff aus der DST-URI im Manifest
                       (``trainedAlgorithmicMedia`` = erzeugt,
                       ``compositeWithTrainedAlgorithmicMedia`` = Gen-Fill/
                       Magic Editor). Doppelt zu ``xmp`` möglich, gewollt.

Zweiter Kanal: XMP ``photoshop:Credit`` (IPTC-Leitlinie) — ``Made with/by
Google AI`` → ``google``, ``Edited with Google AI`` → ``google`` + Modell
``Google Fotos``. Die Midjourney-Signatur (Job-ID) setzt bereits ``xmp.py``.

**Workflow hat Vorrang:** Nennt die Datei ihren Erzeuger selbst (A1111-
``parameters``, ComfyUI-``workflow``/``prompt``), ist ein C2PA-Manifest eine
Nachbearbeitung (Windows Fotos, Paint, Photoshop, …) und KEINE Herkunft — der
Parser liefert dann nur die Rohfelder, weder ``tool`` noch ``model``.

**Nur Belegtes** (Recherche 2026-09-07, Markertabelle mit Quellen und
Zuverlässigkeit in der Konzeptnotiz zu ADR 0066 (Arbeitsrepo)
§2): Stability, Flux, Grok, Ideogram, Leonardo haben keine belegten
Signaturen und bekommen keine Rateregel. Ohne Samples ist v1 ein Recherche-
Stand; Korrekturen laufen rückwirkend (``python -m feral.interpret``).
"""

from __future__ import annotations

import re
from itertools import islice
from typing import Sequence

from ..extract.types import RawMetadataItem
from .types import InterpretedField, Interpretation

NAME = "provenance"
VERSION = 3   # v3: suno (Audio, ADR 0083); v2: Plattform statt Produkt, model, Workflow-Vorrang, flux

TOOL_UNKNOWN_C2PA = "c2pa"

# JUMBF-Kennzeichen (ISO 19566-5) und C2PA-Content-Type-UUIDs: ASCII-Präfix
# + festes Suffix (c2pa-rs ``jumbf/labels.rs``).
_JUMBF_MARKERS = (b"jumb", b"jumd")
_C2PA_UUID_SUFFIX = b"\x00\x11\x00\x10\x80\x00\x00\xaa\x00\x38\x9b\x71"
_C2PA_UUID_PREFIXES = (b"c2pa", b"c2ma", b"c2cl", b"c2cs", b"c2as")

# Markerliste → Plattform, in PRIORITÄTSREIHENFOLGE (erste Übereinstimmung
# gewinnt): Azure vor OpenAI (Azure-Manifeste nennen auch „OpenAI").
_MARKERS: tuple[tuple[str, tuple[bytes, ...]], ...] = (
    ("azure-openai", (b"Azure OpenAI DALL-E", b"Azure OpenAI ImageGen")),
    # Black Forest Labs (Belegstufe A: Feral Strawberrys LMArena-Downloads,
    # 2026-09-08 — claim_generator „Black Forest Labs API", Produkt „Flux.1").
    ("flux", (b"Black Forest Labs", b"FLUX.1", b"Flux.1", b"flux.1")),
    ("openai", (b"OpenAI API", b"OpenAI-API", b"ChatGPT", b"DALL-E", b"Sora")),
    ("adobe", (b"Adobe_Firefly", b"Adobe Photoshop", b"Adobe Firefly")),
    ("google", (b"Google C2PA Core Generator Library",
                b"Google Media Processing Services")),
    # Suno (Belegstufe A: Manifest-Dump einer Suno-MP3 vom 2026-08-21,
    # Recherche Audio §12) — eigene Assertion und Anbietername. Das Modell
    # (Codename in claim_generator_info.version) übersetzt der suno-Parser.
    ("suno", (b"com.suno.provenance", b"Suno, Inc.")),
)

# Produkt/Modell je Plattform, soweit im Manifest belegt (erste Übereinstimmung).
# „DALL-E/3.0 c2pa-rs/…" ist der ältere ChatGPT-Claim (OpenAI-Hilfeartikel);
# GPT-4o der Software-Agent seit GPT Image 1 (example-assets ChatGPT_Image.json).
_MODEL_MARKERS: dict[str, tuple[tuple[bytes, str], ...]] = {
    "openai": ((b"GPT-4o", "GPT-4o"), (b"DALL-E", "DALL-E 3"), (b"Sora", "Sora")),
    "adobe": ((b"Adobe_Firefly", "Adobe Firefly"), (b"Adobe Firefly", "Adobe Firefly")),
}
# Flux: das Produkt steht als Rohstring im Manifest (``Flux.1``, ``FLUX.1
# Kontext [pro]`` …) — der erste Rohstring mit „flux" wird das Modell, sonst
# der Sammelname. Kein Mapping auf Anzeigenamen (ADR 0043-Leitplanke).
_FLUX_FALLBACK_MODEL = "FLUX.1"

# Native Erzeuger-Metadaten (A1111-Infotext, ComfyUI-Graph): dann ist das
# Manifest eine Nachbearbeitung — Workflow hat Vorrang.
_NATIVE_KEYWORDS = frozenset({"parameters", "workflow", "prompt"})

# Aussteller-Regeln (nur der Zertifikatsinhaber, kein Produktmarker) sind
# KEIN Beleg für ein Produkt: Feral Strawberrys Flux.1-Bild war von „Microsoft
# Corporation" signiert (Befund 2026-09-08) und wurde „bing"; ein Pixel-Foto
# mit Content Credentials trägt „Google LLC" ohne jede KI. Deshalb: `bing`
# gestrichen (ADR 0066 Punkt 7, nur Belegtes), `Google LLC` zählt nur noch
# zusammen mit dem KI-Kennzeichen im selben Manifest.
_GOOGLE_ISSUER = b"Google LLC"
_AI_SOURCE_TYPES = (b"trainedAlgorithmicMedia", b"compositeWithTrainedAlgorithmicMedia")

# CBOR-Schlüssel als Textstring < 24 Zeichen: Kopfbyte 0x60 + Länge.
def _cbor_key(name: str) -> bytes:
    return bytes([0x60 + len(name)]) + name.encode("ascii")


_KEY_CLAIM_GENERATOR = _cbor_key("claim_generator")
_KEY_CLAIM_GENERATOR_INFO = _cbor_key("claim_generator_info")
_KEY_SOFTWARE_AGENT = _cbor_key("softwareAgent")
_KEY_NAME = _cbor_key("name")
_KEY_VERSION = _cbor_key("version")
_MAP_WINDOW = 96   # Suchfenster für name/version hinter einem Map-/Array-Wert

# Härtung (ADR 0032-Prinzip: der Blob stammt aus fremden Dateien). Ein echtes
# Manifest nennt jeden Schlüssel eine Handvoll Mal; eine präparierte Datei
# könnte ihn hunderttausendfach mit je neuem Wert wiederholen. Deshalb feste
# Deckel: so viele Vorkommen werden je Schlüssel überhaupt angesehen, so
# viele verschiedene Werte je Feld behalten — danach ist Schluss, linear.
_MAX_OCCURRENCES = 64
_MAX_VALUES = 8

# JSON-Form (ältere/andere Erzeuger serialisieren Assertions teils als JSON).
# Alle Wiederholungen sind nach oben begrenzt — kein unbegrenztes Backtracking.
_JSON_CLAIM_GENERATOR = re.compile(rb'"claim_generator"\s*:\s*"([^"\\]{1,200})"')
_JSON_SOFTWARE_AGENT = re.compile(
    rb'"softwareAgent"\s*:\s*(?:"([^"\\]{1,200})"|\{[^}]{0,300}?"name"\s*:\s*"([^"\\]{1,200})")'
)

_DIGITAL_SOURCE_TYPE = re.compile(rb"digitalsourcetype/([A-Za-z]{4,64})")

# XMP photoshop:Credit als Attribut oder Element.
_XMP_CREDIT = re.compile(
    r'(?:photoshop:Credit\s*=\s*"([^"]*)"|<photoshop:Credit>([^<]*)</photoshop:Credit>)',
    re.IGNORECASE,
)
# Credit → (Plattform, Modell|None)
_CREDIT_TOOLS: tuple[tuple[re.Pattern[str], str, str | None], ...] = (
    (re.compile(r"^Made (?:with|by) Google AI$", re.IGNORECASE), "google", None),
    (re.compile(r"^Edited with Google AI$", re.IGNORECASE), "google", "Google Fotos"),
)


def parse(items: Sequence[RawMetadataItem]) -> Interpretation | None:
    """Herkunft aus allen C2PA-Blobs und XMP-Credits der Datei bestimmen."""
    blobs = [item.data for item in items if item.data is not None and is_c2pa(item.data)]
    credit = _credit(items)
    if not blobs and credit is None:
        return None

    platform: str | None = None
    models: list[str] = []
    claim_generators: list[str] = []
    software_agents: list[str] = []
    source_types: list[str] = []
    for blob in blobs:
        if platform is None:
            platform = _match_tool(blob)
        if platform is not None:
            _extend_unique(models, _match_models(blob, platform))
        _extend_unique(claim_generators, _claim_generators(blob))
        _extend_unique(software_agents, _software_agents(blob))
        _extend_unique(source_types, [m.group(1).decode("ascii") for m in
                                      islice(_DIGITAL_SOURCE_TYPE.finditer(blob), _MAX_OCCURRENCES)])
    if platform == "flux" and not models:
        raw_flux = [v for v in software_agents + claim_generators if "flux" in v.lower()]
        models.append(raw_flux[0] if raw_flux else _FLUX_FALLBACK_MODEL)
    if credit is not None:
        credit_platform, credit_model = credit
        platform = platform or credit_platform
        if credit_model:
            _extend_unique(models, [credit_model])
    if platform is None:
        platform = TOOL_UNKNOWN_C2PA

    fields: list[InterpretedField] = []
    # Workflow hat Vorrang: nennt die Datei ihren Erzeuger selbst, ist das
    # Manifest eine Nachbearbeitung — nur Rohfelder, keine Plattform.
    if not _has_native_generator(items):
        fields.append(InterpretedField("tool", platform))
        fields += [InterpretedField("model", m) for m in models]
    fields += [InterpretedField("claim_generator", v) for v in claim_generators]
    fields += [InterpretedField("software_agent", v) for v in software_agents]
    fields += [InterpretedField("ai_source_type", v) for v in source_types]
    if not fields:
        return None
    return Interpretation(parser=NAME, parser_version=VERSION, fields=fields)


def _has_native_generator(items: Sequence[RawMetadataItem]) -> bool:
    return any((item.keyword or "").lower() in _NATIVE_KEYWORDS and (item.text or "").strip()
               for item in items)


def is_c2pa(blob: bytes) -> bool:
    """Sieht der Blob wie ein C2PA-Manifest aus? JUMBF-Boxen ODER eine der
    C2PA-Content-Type-UUIDs — beides reicht, keins ist zwingend vollständig."""
    if all(marker in blob for marker in _JUMBF_MARKERS):
        return True
    return any(prefix + _C2PA_UUID_SUFFIX in blob for prefix in _C2PA_UUID_PREFIXES)


def _match_tool(blob: bytes) -> str | None:
    for tool, markers in _MARKERS:
        if any(marker in blob for marker in markers):
            return tool
    if _GOOGLE_ISSUER in blob and any(dst in blob for dst in _AI_SOURCE_TYPES):
        return "google"
    return None


def _match_models(blob: bytes, platform: str) -> list[str]:
    for marker, model in _MODEL_MARKERS.get(platform, ()):
        if marker in blob:
            return [model]
    return []


# -- Rohstrings ------------------------------------------------------------------

def _cbor_text(blob: bytes, pos: int) -> str | None:
    """Textstring (CBOR Major Type 3) an Position ``pos`` lesen — nur die drei
    Kopfvarianten bis 65535 Byte; alles andere ist hier kein Textwert."""
    if pos >= len(blob):
        return None
    head = blob[pos]
    if 0x60 <= head <= 0x77:
        length, start = head - 0x60, pos + 1
    elif head == 0x78 and pos + 1 < len(blob):
        length, start = blob[pos + 1], pos + 2
    elif head == 0x79 and pos + 2 < len(blob):
        length, start = int.from_bytes(blob[pos + 1 : pos + 3], "big"), pos + 3
    else:
        return None
    raw = blob[start : start + length]
    if len(raw) < length:
        return None
    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None
    return text or None


def _named_value(blob: bytes, pos: int) -> str | None:
    """Wert hinter einem Schlüssel: direkter Textstring — oder (Map/Array
    mit Maps, z. B. ``claim_generator_info``) ``name`` + ``version`` aus
    dem nächsten Fenster."""
    direct = _cbor_text(blob, pos)
    if direct is not None:
        return direct
    window_end = min(len(blob), pos + _MAP_WINDOW)
    name_at = blob.find(_KEY_NAME, pos, window_end)
    if name_at == -1:
        return None
    name = _cbor_text(blob, name_at + len(_KEY_NAME))
    if name is None:
        return None
    version_at = blob.find(_KEY_VERSION, pos, window_end + 64)
    version = _cbor_text(blob, version_at + len(_KEY_VERSION)) if version_at != -1 else None
    return f"{name} {version}" if version else name


def _values_after(blob: bytes, key: bytes) -> list[str]:
    out: list[str] = []
    start = 0
    for _ in range(_MAX_OCCURRENCES):
        at = blob.find(key, start)
        if at == -1:
            break
        value = _named_value(blob, at + len(key))
        if value is not None and value not in out and len(out) < _MAX_VALUES:
            out.append(value)
        start = at + len(key)
    return out


def _claim_generators(blob: bytes) -> list[str]:
    values: list[str] = []
    # ``claim_generator_info`` enthält ``claim_generator`` als Präfix — die
    # Info-Variante gezielt zuerst, dann die Kurzform ohne ihre Treffer.
    _extend_unique(values, _values_after(blob, _KEY_CLAIM_GENERATOR_INFO))
    _extend_unique(values, _values_after(blob, _KEY_CLAIM_GENERATOR))
    _extend_unique(values, [m.group(1).decode("utf-8", "replace") for m in
                            islice(_JSON_CLAIM_GENERATOR.finditer(blob), _MAX_OCCURRENCES)])
    return values


def _software_agents(blob: bytes) -> list[str]:
    values: list[str] = []
    _extend_unique(values, _values_after(blob, _KEY_SOFTWARE_AGENT))
    _extend_unique(values, [(m.group(1) or m.group(2)).decode("utf-8", "replace") for m in
                            islice(_JSON_SOFTWARE_AGENT.finditer(blob), _MAX_OCCURRENCES)])
    return values


def _extend_unique(target: list[str], values: Sequence[str]) -> None:
    """Anhängen ohne Doppel, gedeckelt — ``target`` bleibt klein (≤ _MAX_VALUES),
    damit die Doppel-Prüfung nie quadratisch wird."""
    for v in values:
        if len(target) >= _MAX_VALUES:
            return
        if v and v not in target:
            target.append(v)


# -- XMP-Credit ------------------------------------------------------------------

def _credit(items: Sequence[RawMetadataItem]) -> tuple[str, str | None] | None:
    for item in items:
        text = item.text
        if text is None and item.data is not None and b"photoshop:Credit" in item.data:
            text = item.data.decode("utf-8", errors="replace")
        if not text or "photoshop:Credit" not in text:
            continue
        for match in _XMP_CREDIT.finditer(text):
            credit = (match.group(1) or match.group(2) or "").strip()
            for pattern, tool, model in _CREDIT_TOOLS:
                if pattern.match(credit):
                    return tool, model
    return None
