"""Schicht 1 — verlustfreie Roh-Extraktion von Container-Metadaten.

Diese Schicht versteht **Container, nicht Konventionen** (ADR 0004). Sie zieht alle
textuellen/strukturierten Metadaten **unverändert** heraus und liefert sie als
beschriftete Roh-Blobs. Interpretation (Prompt/Seed/Modell/Workflow) ist Sache von
Schicht 2 und arbeitet später über genau diese Roh-Blobs.

Öffentliche API:

- `extract(path)` — Dispatcher: erkennt den Container über Magic Bytes und ruft den
  passenden Extraktor auf (`feral.extract.container.extract`).
- `RawMetadataItem`, `ContainerExtraction` — die Wertobjekte (`feral.extract.types`).
"""

from __future__ import annotations

from .container import extract, sniff_container
from .types import ContainerExtraction, RawMetadataItem

__all__ = [
    "extract",
    "sniff_container",
    "ContainerExtraction",
    "RawMetadataItem",
]
