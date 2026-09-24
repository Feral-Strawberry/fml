"""Rückwirkende Schicht-2-Interpretation über die gespeicherten Roh-Blobs.

Der Kern der Zwei-Schichten-Strategie (ADR 0004): Ein neuer oder verbesserter
Parser braucht **keinen erneuten Datei-Scan** — er läuft über die bereits in der
DB liegenden Roh-Metadaten und ersetzt die interpretierten Felder. Aufruf:

    python -m feral.interpret --db ./feral.sqlite

Seit ADR 0067 (Issue #62/#65) arbeitet der Lauf in **Schüben**: Roh-Blobs
eines Schubs lesen, interpretieren (wahlweise in einem Prozess-Pool — die
Parser sind rein), gebündelt schreiben, EIN Commit je Schub.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import Executor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Sequence

from ..db import store_interpretations
from ..db.store import now_iso
from ..extract.types import RawMetadataItem
from . import suno
from .registry import interpret_items
from .types import Interpretation

DEFAULT_CHUNK = 500


@dataclass
class ReparseReport:
    """Zusammenfassung eines Reparse-Laufs."""

    items_total: int = 0        # Items mit Roh-Metadaten in der DB
    items_interpreted: int = 0  # davon: mindestens ein Parser fühlte sich zuständig
    fields_written: int = 0     # insgesamt geschriebene Felder
    items_planned: int = 0      # Gesamtzahl zu Beginn (für Fortschritt index/total)
    items_unchanged: int = 0    # Ergebnis identisch mit dem Bestand → nichts geschrieben

    def summary(self) -> str:
        return "\n".join(
            [
                f"  items with raw metadata : {self.items_total}",
                f"  of which interpreted    : {self.items_interpreted}",
                f"  fields written          : {self.fields_written}",
                f"  skipped (unchanged)     : {self.items_unchanged}",
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


def interpret_chunk(
    chunk: Sequence[tuple[str, list[RawMetadataItem]]],
) -> list[tuple[str, list[Interpretation]]]:
    """Einen Schub interpretieren — rein, ohne DB; läuft auch im Pool-Prozess."""
    return [(file_hash, interpret_items(items)) for file_hash, items in chunk]


def _existing_rows(conn: sqlite3.Connection, file_hash: str) -> list[tuple]:
    return [
        tuple(r) for r in conn.execute(
            """SELECT parser, parser_version, ordinal, field, value_text
                 FROM interpreted_metadata WHERE file_hash = ?
                ORDER BY parser, ordinal""", (file_hash,),
        )
    ]


def _planned_rows(interpretations: Sequence[Interpretation]) -> list[tuple]:
    rows = [
        (i.parser, i.parser_version, ordinal, f.field, f.value)
        for i in interpretations for ordinal, f in enumerate(i.fields)
    ]
    rows.sort(key=lambda r: (r[0], r[2]))
    return rows


def _suno_media_date(
    conn: sqlite3.Connection, file_hash: str, interpretations: Sequence[Interpretation],
) -> None:
    """Suno-Erstellzeit wird Mediendatum (ADR 0083) — auch rückwirkend, damit
    ``python -m feral.interpret`` für den Bestand genügt (Rescan-Prinzip).
    Nur für Suno-Items: Bilddaten bleiben Sache der Scan-Kaskade."""
    if not any(i.parser == suno.NAME for i in interpretations):
        return
    when = suno.created_at(raw_items_for(conn, file_hash))
    if when is not None and when <= datetime.now(timezone.utc) + timedelta(days=1):
        from ..importer import set_media_date   # Lazy: importer → interpret
        set_media_date(conn, file_hash, when, "metadaten")


def reparse_database(
    conn: sqlite3.Connection,
    *,
    progress: Callable[[ReparseReport], None] | None = None,
    chunk_size: int = DEFAULT_CHUNK,
    pool: Executor | None = None,
) -> ReparseReport:
    """Interpretiere alle Items mit Roh-Metadaten neu (idempotent).

    Ersetzt je Item die vorhandenen Schicht-2-Felder vollständig — die Roh-Daten
    (Schicht 1) bleiben unangetastet. ``progress`` wird nach jedem Schub
    gerufen (``chunk_size`` Items, ein Commit). Mit ``pool`` (Executor) laufen
    die Parser parallel in Kindprozessen; das Ergebnis ist byte-gleich zum
    Einzelprozess (Parser sind rein, ADR 0011).

    Items, deren Ergebnis dem Bestand gleicht, werden **nicht** geschrieben
    (ADR 0067, gemessen): der teure Teil eines Reparse ist nicht das Parsen,
    sondern das Neu-Aufbauen der FTS5-Zeile je Item (Lösch-/Einfüge-Churn
    wächst über den Lauf) — bei einem erneuten Lauf mit denselben Parsern
    fällt so fast alle Schreibarbeit weg.
    """
    report = ReparseReport()
    hashes = [
        row[0]
        for row in conn.execute("SELECT DISTINCT file_hash FROM raw_metadata").fetchall()
    ]
    report.items_planned = len(hashes)
    ts = now_iso()
    chunk_size = max(1, chunk_size)

    def chunks():
        for start in range(0, len(hashes), chunk_size):
            yield [(h, raw_items_for(conn, h)) for h in hashes[start:start + chunk_size]]

    results = pool.map(interpret_chunk, chunks()) if pool is not None else map(interpret_chunk, chunks())
    for batch in results:
        for file_hash, interpretations in batch:
            report.items_total += 1
            if interpretations:
                report.items_interpreted += 1
                report.fields_written += sum(len(i.fields) for i in interpretations)
            if _existing_rows(conn, file_hash) == _planned_rows(interpretations):
                report.items_unchanged += 1
                continue
            store_interpretations(
                conn, file_hash=file_hash, interpretations=interpretations,
                now=ts, commit=False,
            )
            _suno_media_date(conn, file_hash, interpretations)
        conn.commit()
        if progress is not None:
            progress(report)
    return report
