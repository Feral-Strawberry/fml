"""Rückwirkende Schicht-2-Interpretation über die gespeicherten Roh-Blobs.

Der Kern der Zwei-Schichten-Strategie (ADR 0004): Ein neuer oder verbesserter
Parser braucht **keinen erneuten Datei-Scan** — er läuft über die bereits in der
DB liegenden Roh-Metadaten und ersetzt die interpretierten Felder. Aufruf:

    python -m feral.interpret --db ./feral.sqlite
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable

from ..db import store_interpretations
from ..extract.types import RawMetadataItem
from .registry import interpret_items


@dataclass
class ReparseReport:
    """Zusammenfassung eines Reparse-Laufs."""

    items_total: int = 0        # Items mit Roh-Metadaten in der DB
    items_interpreted: int = 0  # davon: mindestens ein Parser fühlte sich zuständig
    fields_written: int = 0     # insgesamt geschriebene Felder

    def summary(self) -> str:
        return "\n".join(
            [
                f"  Items mit Roh-Metadaten : {self.items_total}",
                f"  davon interpretiert     : {self.items_interpreted}",
                f"  geschriebene Felder     : {self.fields_written}",
            ]
        )


def raw_items_for(conn: sqlite3.Connection, file_hash: str) -> list[RawMetadataItem]:
    """Rekonstruiere die Roh-Einträge eines Items aus der DB (Umkehrung von
    `store_extraction`): Text-Einträge aus ``value_text``, binäre aus ``value_raw``."""
    rows = conn.execute(
        """
        SELECT source, keyword, value_text, value_raw, encoding, compressed
          FROM raw_metadata WHERE file_hash = ? ORDER BY ordinal
        """,
        (file_hash,),
    ).fetchall()
    return [
        RawMetadataItem(
            source=row["source"],
            keyword=row["keyword"],
            text=row["value_text"],
            data=None if row["value_text"] is not None else row["value_raw"],
            encoding=row["encoding"],
            compressed=bool(row["compressed"]),
        )
        for row in rows
    ]


def reparse_database(
    conn: sqlite3.Connection,
    *,
    progress: Callable[[ReparseReport], None] | None = None,
) -> ReparseReport:
    """Interpretiere alle Items mit Roh-Metadaten neu (idempotent).

    Ersetzt je Item die vorhandenen Schicht-2-Felder vollständig — die Roh-Daten
    (Schicht 1) bleiben unangetastet.
    """
    report = ReparseReport()
    hashes = [
        row[0]
        for row in conn.execute("SELECT DISTINCT file_hash FROM raw_metadata").fetchall()
    ]
    for file_hash in hashes:
        report.items_total += 1
        interpretations = interpret_items(raw_items_for(conn, file_hash))
        store_interpretations(conn, file_hash=file_hash, interpretations=interpretations)
        if interpretations:
            report.items_interpreted += 1
            report.fields_written += sum(len(i.fields) for i in interpretations)
        if progress is not None:
            progress(report)
    return report
