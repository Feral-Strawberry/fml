"""Schicht 2 — Interpretation der Roh-Metadaten (ADR 0004/0011).

Parser ziehen aus den verlustfrei gespeicherten Roh-Blobs (Schicht 1)
strukturierte Felder (Prompt, Seed, Modell, …). Schicht 2 darf unvollständig
sein und wächst iterativ: neues Format = neues Parser-Modul + Registry-Eintrag,
dann rückwirkend `python -m feral.interpret` laufen lassen — kein Datei-Scan nötig.

- `interpret_items(items)` — alle Parser über die Roh-Einträge einer Datei.
- `reparse_database(conn)` — rückwirkend über den ganzen DB-Bestand.
"""

from __future__ import annotations

from .registry import PARSERS, interpret_items
from .reparse import ReparseReport, reparse_database
from .types import InterpretedField, Interpretation

__all__ = [
    "PARSERS",
    "interpret_items",
    "reparse_database",
    "ReparseReport",
    "Interpretation",
    "InterpretedField",
]
