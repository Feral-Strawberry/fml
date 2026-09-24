"""Video-Container-Extraktor über ffprobe (Schicht 1) — WEBM/MKV und MP4/MOV.

``ffprobe`` (Teil von ffmpeg, System-Binary, KEIN pip-Paket — ADR 0008) liest den
Container-Umschlag und gibt die eingebetteten **Tags** als JSON aus. Wir übernehmen
jeden Tag unverändert mit Quell-Label (``matroska:format.tag`` bzw.
``matroska:stream0.tag`` usw.). Dazu je Stream die **Eckwerte** (Codec, Profil,
Pixelformat, Maße, Bitrate — Issue #71, ADR 0070) unter dem Quell-Label
``matroska:stream0`` mit dem ffprobe-Feldnamen als Keyword, ebenfalls
unverändert als Text. Interpretiert wird nichts — Schicht 2 (ADR 0004).

Fehlt ffprobe auf dem System, ist das **kein Fehler**: die Datei wird trotzdem
katalogisiert (Hash + Fundort), die Extraktion liefert nur eine Warnung. Sobald
ffprobe installiert ist, holt ein erneuter Scan die Metadaten nach.

Einzige Ausnahme vom „nur ffprobe": ffprobe sieht keine ``uuid``-Boxen. Das
C2PA-Manifest von MP4/M4A steckt in einer Top-Level-``uuid``-Box (C2PA 2.2
§A.5, Recherche Audio §7) — die liest ``c2pa_uuid_items`` byte-treu
(``isobmff:uuid``, Keyword = UUID hex), nur die Box-Köpfe werden gelesen.
"""

from __future__ import annotations

import json
import struct
import subprocess

from ..tools import find_binary, media_input
from pathlib import Path
from typing import Any, BinaryIO

from .types import ContainerExtraction, RawMetadataItem

CONTAINERS = ("matroska", "isobmff")

# C2PA-Manifest-Box in ISO-BMFF (Top-Level ``uuid``, c2pa-rs bmff_io.rs).
C2PA_UUID = bytes.fromhex("d8fec3d61b0e483c92975828877ec481")
_MAX_C2PA = 64 * 1024 * 1024   # Deckel wie id3.MAX_TAG

# Obergrenze pro Datei — ffprobe liest nur Header, sollte nie so lange brauchen.
_TIMEOUT_SECONDS = 30

# Stream-Eckwerte, die neben den Tags gesichert werden (Issue #71): genau die
# Felder, aus denen sich „kann der Browser das abspielen?" beantworten lässt.
# Werte bleiben, wie ffprobe sie liefert (nur nach str() — byte-treu genug,
# es sind kurze ASCII-Bezeichner und Zahlen). Keyword = ffprobe-Feldname.
STREAM_FACTS = (
    "codec_type", "codec_name", "codec_tag_string", "profile", "pix_fmt",
    "width", "height", "bit_rate",
    # Ton (ADR 0083): Samplerate, Kanäle, Bittiefe.
    "sample_rate", "channels", "channel_layout", "sample_fmt",
    "bits_per_raw_sample", "bits_per_sample",
)

# Format-Eckwerte (ADR 0083) unter ``<container>:format``.
FORMAT_FACTS = ("format_name", "duration", "bit_rate")


def _ffprobe() -> str | None:
    return find_binary("ffprobe")


def probe(path: str | Path) -> tuple[dict[str, Any] | None, str | None]:
    """ffprobe-JSON (Format + Streams) einer Datei → (Daten, Warnung).

    Wirft nicht: fehlendes ffprobe, Timeouts und kaputte Dateien kommen als
    Warnungstext zurück (Daten dann ``None``)."""
    try:
        proc = subprocess.run(
            [
                _ffprobe() or "ffprobe", "-v", "error",
                "-print_format", "json",
                "-show_format", "-show_streams",
                *media_input(path),
            ],
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return None, (
            "ffprobe nicht gefunden — Datei ist katalogisiert, Metadaten folgen "
            "nach Installation von ffmpeg bei einem erneuten Scan (siehe DEPENDENCIES.md)."
        )
    except subprocess.TimeoutExpired:
        return None, f"ffprobe-Timeout nach {_TIMEOUT_SECONDS}s."

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        return None, f"ffprobe meldet Fehler: {stderr or 'unbekannt'}"

    try:
        return json.loads(proc.stdout), None
    except ValueError:
        return None, "ffprobe lieferte kein gültiges JSON."


def extract(source: str | Path | BinaryIO, *, container: str) -> ContainerExtraction:
    """Extrahiere alle Container-Tags einer Videodatei über ffprobe.

    `source` muss ein Dateipfad sein (ffprobe ist ein externes Programm); ein
    Binärstrom wird über sein ``name``-Attribut auf den Pfad zurückgeführt.
    Wirft nicht: fehlendes ffprobe, Timeouts und kaputte Dateien landen als
    Warnung in der (dann leeren) Extraktion.

    Dazu Dauer und Medienart aus den tatsächlichen Spuren (ADR 0083): ein
    Container ohne echte Videospur (M4A, Matroska nur mit Ton) wird
    ``audio`` — das Cover-Bild (``attached_pic``) zählt nicht als Video.
    """
    result = ContainerExtraction(container=container)

    if hasattr(source, "read"):
        # Offener Strom: nur echte Datei-Objekte tragen in `name` ihren Pfad.
        path = getattr(source, "name", None)
        if not isinstance(path, (str, Path)):
            result.warnings.append("ffprobe braucht einen Dateipfad, bekam einen anonymen Strom.")
            return result
    else:
        path = source

    if container == "isobmff":
        result.items.extend(c2pa_uuid_items(path, result.warnings))
    data, warning = probe(path)
    if data is None:
        result.warnings.append(warning or "ffprobe: keine Daten.")
        return result

    result.items.extend(items_from_ffprobe(data, container=container))
    result.width, result.height, result.fps = dimensions_from_ffprobe(data)
    result.duration = duration_from_ffprobe(data)
    result.media_kind = media_kind_from_ffprobe(data)
    return result


def c2pa_uuid_items(path: str | Path, warnings: list[str]) -> list[RawMetadataItem]:
    """C2PA-``uuid``-Boxen der obersten Ebene einer MP4/M4A-Datei, byte-treu.
    Liest nur Box-Köpfe (Sprung über ``mdat``); kaputte Größen beenden den
    Lauf mit Warnung statt Ausnahme."""
    items: list[RawMetadataItem] = []
    try:
        with open(path, "rb") as fh:
            size = fh.seek(0, 2)
            pos = 0
            while pos + 8 <= size:
                fh.seek(pos)
                box_size, box_type = struct.unpack(">I4s", fh.read(8))
                header = 8
                if box_size == 1:
                    box_size = struct.unpack(">Q", fh.read(8))[0]
                    header = 16
                elif box_size == 0:
                    box_size = size - pos
                if box_size < header:
                    warnings.append(f"ISO-BMFF: invalid box size at offset {pos}.")
                    break
                if box_type == b"uuid" and box_size >= header + 16:
                    if fh.read(16) == C2PA_UUID:
                        length = box_size - header - 16
                        if length > _MAX_C2PA:
                            warnings.append("C2PA uuid box too large — skipped.")
                        else:
                            items.append(RawMetadataItem(
                                source="isobmff:uuid", keyword=C2PA_UUID.hex(),
                                text=None, data=fh.read(length), encoding="binary"))
                pos += box_size
    except (OSError, struct.error) as exc:
        warnings.append(f"ISO-BMFF box walk failed: {exc!r}")
    return items


def add_technical_facts(path: str | Path, result: ContainerExtraction) -> None:
    """Technische Fakten einer Audiodatei aus ffprobe an ``result`` hängen
    (ADR 0083): Format-Eckwerte und die Eckwerte der Tonspur(en) — KEINE
    Tags, die liest der Stdlib-Walker vollständiger. Dazu die Dauer.
    Ohne ffprobe: Warnung, die Walker-Einträge bleiben."""
    data, warning = probe(path)
    if data is None:
        result.warnings.append(warning or "ffprobe: keine Daten.")
        return
    result.items.extend(fact_items(data, container=result.container, audio_only=True))
    result.duration = duration_from_ffprobe(data)


def _is_cover(stream: dict[str, Any]) -> bool:
    return bool((stream.get("disposition") or {}).get("attached_pic"))


def media_kind_from_ffprobe(data: dict[str, Any]) -> str | None:
    """``video`` bei echter Videospur, ``audio`` bei nur Ton, sonst ``None``
    (unbekannt — der Aufrufer bleibt bei der Container-Zuordnung)."""
    streams = data.get("streams") or []
    if any(s.get("codec_type") == "video" and not _is_cover(s) for s in streams):
        return "video"
    if any(s.get("codec_type") == "audio" for s in streams):
        return "audio"
    return None


def duration_from_ffprobe(data: dict[str, Any]) -> float | None:
    """Dauer in Sekunden: ``format.duration``, sonst die längste Spur."""
    candidates = [(data.get("format") or {}).get("duration")]
    candidates += [s.get("duration") for s in data.get("streams") or []]
    for value in candidates:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            continue
        if seconds > 0:
            return round(seconds, 3)
    return None


def dimensions_from_ffprobe(data: dict[str, Any]) -> tuple[int | None, int | None, float | None]:
    """Maße + fps des ersten Video-Streams (reine Funktion, gut testbar)."""
    for stream in data.get("streams") or []:
        if stream.get("codec_type") != "video":
            continue
        width = stream.get("width") if isinstance(stream.get("width"), int) else None
        height = stream.get("height") if isinstance(stream.get("height"), int) else None
        fps = None
        for key in ("avg_frame_rate", "r_frame_rate"):
            rate = stream.get(key)
            if isinstance(rate, str) and "/" in rate:
                num, _, den = rate.partition("/")
                try:
                    if float(den) > 0 and float(num) > 0:
                        fps = round(float(num) / float(den), 2)
                        break
                except ValueError:
                    continue
        return width, height, fps
    return None, None, None


def items_from_ffprobe(data: dict[str, Any], *, container: str) -> list[RawMetadataItem]:
    """Bilde die Tag-Abschnitte einer ffprobe-JSON-Ausgabe auf Roh-Einträge ab.

    Reine Funktion (gut testbar, ohne ffprobe-Aufruf): nimmt das geparste JSON
    und liefert je Format-Tag und je Stream-Tag einen `RawMetadataItem`,
    dazu die technischen Eckwerte (``fact_items``).
    """
    return fact_items(data, container=container, audio_only=False, tags=True)


def _fact(value: Any) -> str | None:
    """Eckwert als Text; leere/Null-Werte (ffprobe meldet ``bits_per_sample``
    0 bei verlustbehafteten Codecs) entfallen."""
    if value is None or value == "" or value == 0 or value == "0":
        return None
    return str(value)


def fact_items(data: dict[str, Any], *, container: str, audio_only: bool,
               tags: bool = False) -> list[RawMetadataItem]:
    """Eckwerte (und optional Tags) einer ffprobe-Ausgabe als Roh-Einträge.

    ``audio_only``: nur Tonspuren (bei Audiodateien — das Cover erscheint in
    ffprobe als Bild-„Video"-Spur und ist kein technischer Fakt des Tons)."""
    items: list[RawMetadataItem] = []
    fmt = data.get("format") or {}

    def add(source: str, key: str, text: str) -> None:
        items.append(RawMetadataItem(source=source, keyword=key, text=text,
                                     data=None, encoding="utf-8"))

    if tags:
        format_tags = fmt.get("tags") or {}
        for key in sorted(format_tags):
            add(f"{container}:format.tag", key, str(format_tags[key]))
    for key in FORMAT_FACTS:
        value = _fact(fmt.get(key))
        if value is not None:
            add(f"{container}:format", key, value)

    for index, stream in enumerate(data.get("streams") or []):
        if audio_only and stream.get("codec_type") != "audio":
            continue
        # Eckwerte des Streams (Codec & Co.) VOR seinen Tags — feste
        # Reihenfolge, damit der Roh-Blob deterministisch bleibt.
        for key in STREAM_FACTS:
            value = _fact(stream.get(key))
            if value is not None:
                add(f"{container}:stream{index}", key, value)
        if tags:
            stream_tags = stream.get("tags") or {}
            for key in sorted(stream_tags):
                add(f"{container}:stream{index}.tag", key, str(stream_tags[key]))

    return items


def video_stream_facts(data: dict[str, Any]) -> dict[str, str] | None:
    """Eckwerte des ERSTEN Video-Streams als ``{feldname: text}`` (reine
    Funktion). Grundlage des Diagnose-Kommandos ``python -m feral.diagnose
    video-codecs`` (Issue #71), das ffprobe nur mit ``-select_streams v:0``
    aufruft und die Antwort nicht in der DB ablegt. ``None`` ohne Video-Stream."""
    for stream in data.get("streams") or []:
        if stream.get("codec_type") != "video":
            continue
        return {
            key: str(stream[key]) for key in STREAM_FACTS
            if stream.get(key) is not None and stream.get(key) != ""
        }
    return None
