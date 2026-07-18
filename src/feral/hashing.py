"""Content-Hashing — die stabile Identität eines Items.

Jedes Item wird primär über seinen **Datei-Hash (SHA-256)** identifiziert
(ADR 0002). Dieser Hash trägt zugleich Dublettencheck, Re-Scan-Wiederherstellung
und Sync. Der Hash wird **gestreamt** gebildet, damit auch große Videos nicht
komplett in den Speicher geladen werden.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO

# 1 MiB — guter Kompromiss zwischen Syscalls und Speicher beim Streamen.
_CHUNK_SIZE = 1024 * 1024


def hash_stream(stream: BinaryIO, *, chunk_size: int = _CHUNK_SIZE) -> str:
    """Bilde den SHA-256-Hash über einen offenen Binärstrom.

    Liest den Strom in Blöcken bis zum Ende. Der Strom muss am gewünschten
    Startpunkt stehen (üblicherweise Anfang) und binär geöffnet sein.

    Gibt den Hash als Hex-String (64 Zeichen, Kleinbuchstaben) zurück.
    """
    digest = hashlib.sha256()
    while True:
        block = stream.read(chunk_size)
        if not block:
            break
        digest.update(block)
    return digest.hexdigest()


def hash_file(path: str | Path, *, chunk_size: int = _CHUNK_SIZE) -> str:
    """Bilde den SHA-256-Hash über die rohen Bytes einer Datei.

    Gibt den Hash als Hex-String zurück. Wirft die üblichen OS-Fehler
    (`FileNotFoundError`, `PermissionError`, …), wenn die Datei nicht lesbar ist —
    der Aufrufer entscheidet, ob daraus ein `_failed`-Fall wird (ADR 0006).
    """
    with open(path, "rb") as fh:
        return hash_stream(fh, chunk_size=chunk_size)


def hash_bytes(data: bytes) -> str:
    """Bilde den SHA-256-Hash über einen Bytes-Puffer (Hex-String)."""
    return hashlib.sha256(data).hexdigest()
