"""Video-Container-Extraktor über ffprobe (Schicht 1) — WEBM/MKV und MP4/MOV.

``ffprobe`` (Teil von ffmpeg, System-Binary, KEIN pip-Paket — ADR 0008) liest den
Container-Umschlag und gibt die eingebetteten **Tags** als JSON aus. Wir übernehmen
jeden Tag unverändert mit Quell-Label (``matroska:format.tag`` bzw.
``matroska:stream0.tag`` usw.). Interpretiert wird nichts — Schicht 2 (ADR 0004).

Fehlt ffprobe auf dem System, ist das **kein Fehler**: die Datei wird trotzdem
katalogisiert (Hash + Fundort), die Extraktion liefert nur eine Warnung. Sobald
ffprobe installiert ist, holt ein erneuter Scan die Metadaten nach.
"""

from __future__ import annotations

import json
import subprocess

from ..tools import find_binary
from pathlib import Path
from typing import Any, BinaryIO

from .types import ContainerExtraction, RawMetadataItem

CONTAINERS = ("matroska", "isobmff")

# Obergrenze pro Datei — ffprobe liest nur Header, sollte nie so lange brauchen.
_TIMEOUT_SECONDS = 30


def _ffprobe() -> str | None:
    return find_binary("ffprobe")


def extract(source: str | Path | BinaryIO, *, container: str) -> ContainerExtraction:
    """Extrahiere alle Container-Tags einer Videodatei über ffprobe.

    `source` muss ein Dateipfad sein (ffprobe ist ein externes Programm); ein
    Binärstrom wird über sein ``name``-Attribut auf den Pfad zurückgeführt.
    Wirft nicht: fehlendes ffprobe, Timeouts und kaputte Dateien landen als
    Warnung in der (dann leeren) Extraktion.
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

    try:
        proc = subprocess.run(
            [
                _ffprobe() or "ffprobe", "-v", "error",
                "-print_format", "json",
                "-show_format", "-show_streams",
                str(path),
            ],
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        result.warnings.append(
            "ffprobe nicht gefunden — Datei ist katalogisiert, Metadaten folgen "
            "nach Installation von ffmpeg bei einem erneuten Scan (siehe DEPENDENCIES.md)."
        )
        return result
    except subprocess.TimeoutExpired:
        result.warnings.append(f"ffprobe-Timeout nach {_TIMEOUT_SECONDS}s.")
        return result

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        result.warnings.append(f"ffprobe meldet Fehler: {stderr or 'unbekannt'}")
        return result

    try:
        data = json.loads(proc.stdout)
    except ValueError:
        result.warnings.append("ffprobe lieferte kein gültiges JSON.")
        return result

    result.items.extend(items_from_ffprobe(data, container=container))
    result.width, result.height, result.fps = dimensions_from_ffprobe(data)
    return result


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
    und liefert je Format-Tag und je Stream-Tag einen `RawMetadataItem`.
    """
    items: list[RawMetadataItem] = []

    format_tags = (data.get("format") or {}).get("tags") or {}
    for key in sorted(format_tags):
        items.append(
            RawMetadataItem(
                source=f"{container}:format.tag", keyword=key,
                text=str(format_tags[key]), data=None, encoding="utf-8",
            )
        )

    for index, stream in enumerate(data.get("streams") or []):
        stream_tags = stream.get("tags") or {}
        for key in sorted(stream_tags):
            items.append(
                RawMetadataItem(
                    source=f"{container}:stream{index}.tag", keyword=key,
                    text=str(stream_tags[key]), data=None, encoding="utf-8",
                )
            )

    return items
