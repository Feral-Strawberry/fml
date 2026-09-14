"""Schicht-2-Parser: Video-Codec, Profil und Pixelformat (Issue #71, ADR 0070).

Der ffprobe-Extraktor (Schicht 1) sichert je Stream die Eckwerte unter dem
Quell-Label ``isobmff:stream0`` / ``matroska:stream0`` (Keyword = ffprobe-
Feldname: ``codec_type``, ``codec_name``, ``profile``, ``pix_fmt`` …). Dieser
Parser nimmt den ERSTEN Video-Stream (nicht zwingend Stream 0 — bei manchen
Containern liegt der Ton vorn) und hebt drei kanonische Felder heraus:

- ``video_codec``   ffprobe-Codec-Name, klein (``prores``, ``hevc``, ``h264``,
                    ``vp9``, ``av1``)
- ``video_profile`` Profil, wie ffprobe es nennt (``HQ``, ``Main 10``,
                    ``High 10``)
- ``pixel_format``  Pixelformat (``yuv420p``, ``yuv422p10le``)

Damit findet der Chip ``video_codec: prores`` alle Betroffenen auf einen
Schlag, und der Player kann VOR dem Laden fragen, ob der Browser das
überhaupt dekodiert (``canPlayType``), statt eine schwarze Fläche zu zeigen.

Dazu die Einschätzung ``browser_support()`` — bewusst NICHT als Schicht-2-
Feld: ob ein Codec abspielbar ist, sagt nichts über die Datei, sondern über
Browser-Generationen. Sie speist das Scan-Problem „im Browser nicht
abspielbar" (Muster ``scan_issues``) und die Spalte im Diagnose-Kommando.
"""

from __future__ import annotations

import re
from typing import Sequence

from ..extract.types import RawMetadataItem
from .types import InterpretedField, Interpretation

NAME = "video"
VERSION = 1

_STREAM_SOURCE = re.compile(r"^(?:isobmff|matroska):stream(\d+)$")

# Codecs, die KEIN Browser dekodiert (Produktions-/Zwischencodecs; Safari
# spielt ProRes zwar nativ, ist aber die Ausnahme, die der Player selbst
# per canPlayType erkennt). Quelle: Browser-Codec-Tabellen (MDN, 2026).
NEVER_IN_BROWSER = frozenset({
    "prores", "dnxhd", "cineform", "mjpeg", "qtrle", "rawvideo", "ffv1",
    "huffyuv", "utvideo", "magicyuv", "hap", "v210", "png", "cfhd",
})
# Nur mit Hardware-Decoder bzw. je nach System (Chrome/Safari ja, Firefox
# nur über Systemcodecs, Linux nie).
LIMITED_IN_BROWSER = frozenset({"hevc"})
# H.264 spielen Browser nur als 8-bit 4:2:0 — High 10 / 4:2:2 / 4:4:4 nicht.
_H264_PIXEL_FORMATS = frozenset({"yuv420p", "yuvj420p", "nv12"})


def parse(items: Sequence[RawMetadataItem]) -> Interpretation | None:
    """Kanonische Video-Felder aus den Stream-Eckwerten des ersten Video-Streams."""
    facts = video_stream_facts(items)
    if not facts:
        return None
    fields: list[InterpretedField] = []
    codec = (facts.get("codec_name") or "").strip().lower()
    if codec:
        fields.append(InterpretedField("video_codec", codec))
    profile = (facts.get("profile") or "").strip()
    if profile:
        fields.append(InterpretedField("video_profile", profile))
    pix_fmt = (facts.get("pix_fmt") or "").strip().lower()
    if pix_fmt:
        fields.append(InterpretedField("pixel_format", pix_fmt))
    if not fields:
        return None
    return Interpretation(parser=NAME, parser_version=VERSION, fields=fields)


def video_stream_facts(items: Sequence[RawMetadataItem]) -> dict[str, str] | None:
    """Eckwerte des ersten Video-Streams (``codec_type = video``) als Dict.

    Streams werden über ihren Index im Quell-Label gruppiert; ``None``, wenn
    kein Stream mit ``codec_type = video`` vorliegt (z. B. reine Tonspur oder
    Bestand vor der Extraktor-Erweiterung — dann hilft ein Re-Scan).
    """
    streams: dict[int, dict[str, str]] = {}
    for item in items:
        if item.text is None or not item.keyword:
            continue
        m = _STREAM_SOURCE.match(item.source)
        if not m:
            continue
        streams.setdefault(int(m.group(1)), {})[item.keyword] = item.text
    for index in sorted(streams):
        if streams[index].get("codec_type") == "video":
            return streams[index]
    return None


def browser_support(codec: str | None, profile: str | None, pix_fmt: str | None) -> str:
    """Grobe, browserunabhängige Einschätzung: ``"ok"`` (übliche Web-Codecs),
    ``"limited"`` (nur manche Browser/Systeme, z. B. HEVC) oder ``"none"``
    (kein gängiger Browser, z. B. ProRes oder 10-bit-H.264). Unbekannte
    Codecs gelten als ``"ok"`` — lieber ein Hinweis zu wenig als ein falscher.
    Die verbindliche Antwort gibt am Ende der Browser selbst (``canPlayType``).
    """
    c = (codec or "").strip().lower()
    if not c:
        return "ok"
    if c in NEVER_IN_BROWSER:
        return "none"
    if c in LIMITED_IN_BROWSER:
        return "limited"
    if c == "h264":
        p = (pix_fmt or "").strip().lower()
        if p and p not in _H264_PIXEL_FORMATS:
            return "none"
        prof = (profile or "").strip().lower()
        if "10" in prof or "4:2:2" in prof or "4:4:4" in prof:
            return "none"
    return "ok"


def playback_issue(interpretations: Sequence[Interpretation]) -> tuple[str, dict[str, str]] | None:
    """Scan-Problem für nicht/eingeschränkt abspielbare Videos: ``(schlüssel,
    parameter)`` für ``messages.dump`` oder ``None``. Liest die Felder dieses
    Parsers aus den fertigen Interpretationen einer Datei — so teilen sich
    Scan und Import dieselbe Regel, ohne die Roh-Einträge erneut anzusehen.
    """
    facts: dict[str, str] = {}
    for interp in interpretations:
        if interp.parser != NAME:
            continue
        for f in interp.fields:
            facts.setdefault(f.field, f.value)
    codec = facts.get("video_codec")
    if not codec:
        return None
    verdict = browser_support(codec, facts.get("video_profile"), facts.get("pixel_format"))
    if verdict == "ok":
        return None
    # Immer beide Parameter: der Meldungs-Renderer lässt fehlende Platzhalter
    # roh stehen. ``detail`` = Profil + Pixelformat, soweit bekannt.
    detail = ", ".join(v for v in (facts.get("video_profile"), facts.get("pixel_format")) if v)
    params = {"codec": codec, "detail": detail or "-"}
    key = "issueUnplayable" if verdict == "none" else "issueLimitedPlayback"
    return key, params
