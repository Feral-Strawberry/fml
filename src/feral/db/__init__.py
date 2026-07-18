"""Persistenz-Schicht (stdlib sqlite3).

Trennt klar von der Extraktion: Extraktoren liefern reine Datenobjekte
(`feral.extract`), diese Schicht schreibt sie in die SQLite-DB.

- `connect(path)` — öffnet die DB, schaltet WAL + Foreign Keys, wendet Migrationen an.
- `store_extraction(...)` — schreibt Item, Fundort und Roh-Metadaten (ADR 0010).
- `store_interpretations(...)` — schreibt Schicht-2-Ergebnisse (ADR 0011).
- `manual` — manuelle Schicht: Rating/Notizen/Tags (Stufe 3.1, ADR 0017).
- `folders` — Smart Folders: gespeicherte Filterausdrücke (Stufe 3.3, ADR 0018).
"""

from __future__ import annotations

from .database import apply_migrations, connect, schema_version
from . import folders, manual
from .store import media_kind_for, store_extraction, store_interpretations

__all__ = [
    "connect",
    "apply_migrations",
    "schema_version",
    "store_extraction",
    "store_interpretations",
    "media_kind_for",
    "manual",
    "folders",
]
