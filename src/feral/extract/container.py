"""Dispatcher der Schicht-1-Extraktion.

Erkennt den Container über **Magic Bytes** (nicht über die Dateiendung — die lügt
zu oft) und ruft den passenden Extraktor aus der **Registry** auf. Ein neuer
Container = ein neues Extraktor-Modul + ein Registry-Eintrag (ADR 0008/0011):

- PNG        → Stdlib-Eigenbau (`png.py`)
- JPEG/WEBP/GIF/BMP/TIFF → Pillow als Container-Öffner (`image_pillow.py`)
- WEBM/MKV, MP4/MOV      → ffprobe-System-Binary (`video_ffprobe.py`)
- PSD/PSB    → Stdlib-Eigenbau (`psd.py`, ADR 0052)
- PDF        → erkannt, kein Extraktor (gestrichen, ADR 0051)
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Callable

from . import image_pillow, png, psd, video_ffprobe
from .types import ContainerExtraction


class ContainerError(Exception):
    """Basisklasse für Container-Erkennungsfehler."""


class UnknownContainerError(ContainerError):
    """Der Container konnte nicht erkannt werden (kein bekanntes Magic-Byte-Muster)."""


class ExtractorNotImplementedError(ContainerError):
    """Container erkannt, aber sein Schicht-1-Extraktor ist noch nicht gebaut."""

    def __init__(self, container: str) -> None:
        super().__init__(
            f"Container '{container}' erkannt, aber Extraktor noch nicht implementiert "
            f"(siehe ADR 0008)."
        )
        self.container = container


# Registry: Container-Name → Extraktorfunktion (nimmt einen Dateipfad).
# Wächst mit jedem neuen Extraktor; nicht gelistete, aber erkannte Container
# (PDF, Kamera-RAW) werden katalogisiert und bekommen ihre Metadaten später.
_EXTRACTORS: dict[str, Callable[[str | Path], ContainerExtraction]] = {
    "png": png.extract,
    "psd": psd.extract,
    **{c: partial(image_pillow.extract, container=c) for c in image_pillow.CONTAINERS},
    **{c: partial(video_ffprobe.extract, container=c) for c in video_ffprobe.CONTAINERS},
}

# Wie viele Bytes vom Dateianfang fürs Sniffing genügen (MP4-'ftyp' liegt bei 4..8,
# WEBP-'WEBP' bei 8..12).
_SNIFF_BYTES = 16

# TIFF-basierte Kamera-RAW-Formate: identische Magic Bytes wie TIFF — hier
# entscheidet ausnahmsweise die Endung (die Alternative wäre ein IFD-Parser
# nur für diese Unterscheidung; CR2 hat einen eigenen Marker und läuft über
# sniff_container). Ein eigener Container-Name macht sie ehrlich filterbar
# (`container: arw`, Import-Regeln ADR 0046) statt als TIFF durchzurutschen —
# Feral Strawberrys Sony-ARWs liefen als „tiff" mit, sind aber weder anzeigbar noch
# thumbnailbar (Befund 2026-07-16).
_TIFF_RAW_SUFFIXES = {".arw": "arw", ".nef": "nef", ".dng": "dng"}


def sniff_container(head: bytes) -> str | None:
    """Bestimme den Container-Typ aus den ersten Bytes einer Datei.

    Gibt einen kurzen Container-Namen (``"png"``, ``"jpeg"``, ``"webp"``, …) zurück
    oder ``None``, wenn kein bekanntes Muster passt. Erkennt absichtlich auch
    Container, deren Extraktor noch nicht gebaut ist — die Erkennung ist getrennt
    von der Extraktion.
    """
    if head.startswith(png.PNG_SIGNATURE):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:2] == b"BM":
        return "bmp"
    if head[:4] == b"II\x2a\x00" and head[8:10] == b"CR":
        return "cr2"   # Canon RAW v2: TIFF-Header + eigener Marker bei Byte 8
    if head[:4] in (b"II\x2a\x00", b"MM\x00\x2a"):
        return "tiff"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "matroska"  # WEBM/MKV (EBML)
    if head[4:8] == b"ftyp":
        return "isobmff"  # MP4/MOV/M4V (ISO Base Media File Format)
    if head.startswith(b"8BPS"):
        return "psd"
    if head.startswith(b"%PDF"):
        return "pdf"
    return None


def extract(source: str | Path) -> ContainerExtraction:
    """Erkenne den Container einer Datei und extrahiere ihre Roh-Metadaten.

    Snifft den Typ über Magic Bytes und delegiert an den zuständigen Extraktor
    aus der Registry.

    Erhebt:
        UnknownContainerError       — Magic Bytes passen zu keinem bekannten Format.
        ExtractorNotImplementedError — Format erkannt, Extraktor noch nicht gebaut.
    """
    path = Path(source)
    with open(path, "rb") as fh:
        head = fh.read(_SNIFF_BYTES)
    container = sniff_container(head)
    if container is None:
        raise UnknownContainerError(f"Unbekannter Container: {path}")
    if container == "tiff":
        # RAW-Verfeinerung (s. _TIFF_RAW_SUFFIXES): kein Extraktor registriert
        # ⇒ „erkannt, Extraktor folgt" — katalogisierbar und filterbar.
        container = _TIFF_RAW_SUFFIXES.get(path.suffix.lower(), "tiff")
    extractor = _EXTRACTORS.get(container)
    if extractor is None:
        raise ExtractorNotImplementedError(container)
    return extractor(path)
