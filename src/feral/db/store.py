"""Persistenz der Schicht-1-Extraktion und Schicht-2-Interpretation (ADR 0010/0011).

Nimmt die reinen Datenobjekte aus `feral.extract` bzw. `feral.interpret` plus den
Datei-Hash und schreibt sie idempotent in die DB. „Idempotent" heißt: ein erneuter
Scan/Reparse derselben Datei (gleicher Hash) führt zum selben Zustand — die
Metadaten werden vor dem Neuschreiben ersetzt, `first_seen_at` bleibt erhalten.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from ..extract.types import ContainerExtraction, RawMetadataItem

if TYPE_CHECKING:  # nur für Typannotationen — kein Laufzeit-Importzyklus
    from ..interpret.types import Interpretation

# Container → grobe Medienart (ADR 0010).
_MEDIA_KIND = {
    "png": "image",
    "jpeg": "image",
    "webp": "image",
    "gif": "image",
    "bmp": "image",
    "tiff": "image",
    # Kamera-RAW (TIFF-basiert, eigener Name — container.py): Bilder ohne
    # fertigen Extraktor, v. a. für Import-Regeln/Filter relevant (ADR 0046).
    "arw": "image",
    "nef": "image",
    "cr2": "image",
    "dng": "image",
    "psd": "image",
    "pcd": "image",
    "pdf": "document",
    "matroska": "video",
    "isobmff": "video",
    # Audio-Modul (ADR 0083). M4A/tonloses Matroska setzt der Extraktor
    # selbst auf "audio" (ContainerExtraction.media_kind).
    "mp3": "audio",
    "flac": "audio",
    "ogg": "audio",
    "wav": "audio",
    "aiff": "audio",
    "caf": "audio",
}


def media_kind_for(container: str) -> str:
    """Grobe Medienart eines Containers: ``image`` | ``video`` | ``audio`` |
    ``document``."""
    return _MEDIA_KIND.get(container, "unknown")


def now_iso() -> str:
    """Aktueller Zeitstempel als ISO-8601 in UTC."""
    return datetime.now(timezone.utc).isoformat()


def record_issue(conn: sqlite3.Connection, path: str | Path, kind: str, message: str) -> None:
    """Halte ein Scan-Problem fest (``scan_issues``, ADR 0014) — idempotent
    über (Pfad, Art, Meldung); ein erneutes Auftreten öffnet Quittiertes
    wieder. ``message`` ist der Meldungs-JSON-Text (``messages.dump``).
    Gemeinsamer Schreibgriff für Scanner UND Importer (Issue #71)."""
    ts = now_iso()
    with conn:
        conn.execute(
            """
            INSERT INTO scan_issues (path, kind, message, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(path, kind, message) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                resolved = 0
            """,
            (str(path), kind, message, ts, ts),
        )


def _value_raw(item: RawMetadataItem) -> bytes:
    """Byte-exakter Nutzinhalt eines Eintrags (ADR 0010).

    Bei binären/kaputt dekodierten Einträgen sind das die Roh-Bytes direkt; bei
    dekodiertem Text die exakt zurückkodierten Bytes (latin-1/utf-8 sind dafür
    verlustfrei umkehrbar).
    """
    if item.data is not None:
        return item.data
    assert item.text is not None  # Invariante von RawMetadataItem
    return item.text.encode(item.encoding)


def store_extraction(
    conn: sqlite3.Connection,
    *,
    file_hash: str,
    file_size: int,
    path: str | Path,
    extraction: ContainerExtraction,
    image_hash: str | None = None,
    now: str | None = None,
    mtime_ns: int | None = None,
) -> None:
    """Schreibe Item, Fundort und Roh-Metadaten einer Datei in die DB.

    Alles läuft in **einer** Transaktion (atomar). Idempotent bei Re-Scan.

    Parameter:
        conn:       offene Verbindung (siehe `connect`).
        file_hash:  SHA-256 der Datei (stabile Item-ID).
        file_size:  Dateigröße in Bytes.
        path:       Fundort auf der Platte.
        extraction: Ergebnis der Schicht-1-Extraktion.
        image_hash: optionaler Bilddaten-Hash (vorerst i. d. R. None).
        now:        Zeitstempel (ISO-8601 UTC); Standard: jetzt. Für Tests injizierbar.
        mtime_ns:   mtime des Fundorts in Nanosekunden — Stat-Gedächtnis für
                    den Watcher (ADR 0042). None = kein Gedächtnis (der Pfad
                    wird beim nächsten Watcher-Start voll geprüft).
    """
    ts = now or now_iso()
    # Tatsächliche Spuren schlagen die Container-Zuordnung (ADR 0083).
    media_kind = extraction.media_kind or media_kind_for(extraction.container)

    with conn:  # commit bei Erfolg, rollback bei Ausnahme
        # items: anlegen oder updaten; first_seen_at bleibt beim ersten Mal.
        conn.execute(
            """
            INSERT INTO items
                (file_hash, file_size, container, media_kind, image_hash,
                 width, height, fps, duration, first_seen_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_hash) DO UPDATE SET
                file_size  = excluded.file_size,
                container  = excluded.container,
                media_kind = excluded.media_kind,
                image_hash = COALESCE(excluded.image_hash, items.image_hash),
                width      = COALESCE(excluded.width, items.width),
                height     = COALESCE(excluded.height, items.height),
                fps        = COALESCE(excluded.fps, items.fps),
                duration   = COALESCE(excluded.duration, items.duration),
                updated_at = excluded.updated_at
            """,
            (file_hash, file_size, extraction.container, media_kind, image_hash,
             extraction.width, extraction.height, extraction.fps,
             extraction.duration, ts, ts),
        )

        # Fundort-Eindeutigkeit (ADR 0049, Gegenrichtung zu ADR 0033): ein
        # Pfad enthält physisch genau EINE Datei. Liegt dort jetzt ein anderer
        # Inhalt (gleicher Name, neuer Hash — z. B. umsortierte ComfyUI-
        # Outputs), sind Fundort-Zeilen anderer Hashes für diesen Pfad
        # veraltet und würden /api/media & Thumbnail-Nachbau auf die falschen
        # Bytes lenken.
        conn.execute(
            "DELETE FROM file_locations WHERE path = ? AND file_hash != ?",
            (str(path), file_hash),
        )

        # file_locations: Fundort merken / last_seen_at aktualisieren.
        # file_size/mtime_ns = Stat-Gedächtnis (ADR 0042); nur überschreiben,
        # wenn der Aufrufer ein frisches Stat mitbringt — sonst bliebe ein
        # Aufruf ohne Stat und würde das Gedächtnis grundlos löschen.
        conn.execute(
            """
            INSERT INTO file_locations
                (file_hash, path, first_seen_at, last_seen_at, file_size, mtime_ns)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_hash, path) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                file_size = COALESCE(excluded.file_size, file_locations.file_size),
                mtime_ns  = COALESCE(excluded.mtime_ns, file_locations.mtime_ns)
            """,
            (file_hash, str(path), ts, ts,
             file_size if mtime_ns is not None else None, mtime_ns),
        )

        # raw_metadata: idempotent ersetzen (gleicher Hash ⇒ gleiche Metadaten).
        conn.execute("DELETE FROM raw_metadata WHERE file_hash = ?", (file_hash,))
        conn.executemany(
            """
            INSERT INTO raw_metadata
                (file_hash, ordinal, source, keyword, value_text, value_raw,
                 encoding, compressed, extracted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    file_hash,
                    ordinal,
                    item.source,
                    item.keyword,
                    item.text,
                    _value_raw(item),
                    item.encoding,
                    1 if item.compressed else 0,
                    ts,
                )
                for ordinal, item in enumerate(extraction.items)
            ],
        )


def store_interpretations(
    conn: sqlite3.Connection,
    *,
    file_hash: str,
    interpretations: Sequence["Interpretation"],
    now: str | None = None,
    commit: bool = True,
) -> None:
    """Schreibe die Schicht-2-Felder einer Datei in die DB (ADR 0011).

    Ersetzt alle vorhandenen interpretierten Felder des Items vollständig
    (idempotent) — die Roh-Metadaten (Schicht 1) bleiben unangetastet. Eine
    leere Liste löscht entsprechend nur den Altbestand.

    ``commit=False`` (ADR 0067): in der offenen Transaktion des Aufrufers
    schreiben — der Reparse bündelt so hunderte Items je Commit (der Commit
    je Item war der teurere Teil: 2,3 von 2,8 ms, Issue #62).
    """
    ts = now or now_iso()
    if commit:
        with conn:
            _write_interpretations(conn, file_hash, interpretations, ts)
    else:
        _write_interpretations(conn, file_hash, interpretations, ts)


def _write_interpretations(conn, file_hash, interpretations, ts) -> None:
    conn.execute(
        "DELETE FROM interpreted_metadata WHERE file_hash = ?", (file_hash,)
    )
    for interpretation in interpretations:
        conn.executemany(
            """
            INSERT INTO interpreted_metadata
                (file_hash, parser, parser_version, ordinal, field,
                 value_text, interpreted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    file_hash,
                    interpretation.parser,
                    interpretation.parser_version,
                    ordinal,
                    item.field,
                    item.value,
                    ts,
                )
                for ordinal, item in enumerate(interpretation.fields)
            ],
        )
    update_search_index(conn, file_hash)


def update_search_index(conn: sqlite3.Connection, file_hash: str) -> None:
    """FTS5-Zeile eines Items neu aufbauen (ADR 0024, kuratiert nach ADR 0036).

    Fünf Spalten: ``interp`` (Schicht 2 OHNE negative_prompt), ``names``
    (Basenamen der Fundorte), ``manuell`` (Tags/Notizen/manuelles Modell/
    Zeitkommentare),
    ``negativ`` (negative_prompt) und ``raw`` (Roh-Texte) — die Standard-
    Suche matcht nur {interp names manuell}. Wird von ``store_extraction``/
    ``store_interpretations`` UND ``db/manual.py`` mitgepflegt; Löschen
    (ADR 0023) entfernt die Zeile, der Start-Abgleich der Engine baut den
    Alt-Bestand auf. Läuft in der offenen Transaktion des Aufrufers.
    """
    interp = conn.execute(
        """SELECT group_concat(value_text, char(10)) FROM interpreted_metadata
            WHERE file_hash = ? AND value_text != ''
              AND field != 'negative_prompt'""", (file_hash,),
    ).fetchone()[0]
    negativ = conn.execute(
        """SELECT group_concat(value_text, char(10)) FROM interpreted_metadata
            WHERE file_hash = ? AND value_text != ''
              AND field = 'negative_prompt'""", (file_hash,),
    ).fetchone()[0]
    # Manuelle Schicht (ADR 0036): Tags + Notizen + manuelles Modell — damit
    # ein vergebener Tag sofort frei findbar ist (kein Admin-Abgleich nötig).
    manual_parts = [
        r[0]
        for r in conn.execute(
            """SELECT t.name FROM item_tags it JOIN tags t ON t.id = it.tag_id
                WHERE it.file_hash = ? ORDER BY t.name""", (file_hash,),
        )
    ]
    ann = conn.execute(
        "SELECT notes, model FROM annotations WHERE file_hash = ?", (file_hash,)
    ).fetchone()
    if ann is not None:
        manual_parts.extend(v for v in (ann[0], ann[1]) if v)
    # Zeitkommentare (#163): „Chorus" findet den Song.
    manual_parts.extend(
        r[0] for r in conn.execute(
            "SELECT text FROM time_comments WHERE file_hash = ? ORDER BY at_ms, id", (file_hash,),
        )
    )
    raw = conn.execute(
        """SELECT group_concat(value_text, char(10)) FROM raw_metadata
            WHERE file_hash = ? AND value_text IS NOT NULL""", (file_hash,),
    ).fetchone()[0]
    names = conn.execute(
        # Basename-Idiom wie web/filters.BASENAME ('\'→'/', rtrim-Trick).
        """SELECT group_concat(replace(replace(path, '\\', '/'),
                     rtrim(replace(path, '\\', '/'),
                           replace(replace(path, '\\', '/'), '/', '')), ''),
                 char(10))
             FROM file_locations WHERE file_hash = ?""", (file_hash,),
    ).fetchone()[0]
    # Über die rowid-Zuordnung löschen/ersetzen (Migration 0014): ein WHERE
    # auf die UNINDEXED-Spalte file_hash wäre ein Voll-Scan der FTS-Tabelle
    # pro Datei — bei 250k O(n²) für Import/Scan/Reindex.
    old = conn.execute(
        "SELECT fts_rowid FROM search_index_map WHERE file_hash = ?", (file_hash,)
    ).fetchone()
    if old is not None:
        conn.execute("DELETE FROM search_index WHERE rowid = ?", (old[0],))
    cur = conn.execute(
        """INSERT INTO search_index (interp, names, manuell, negativ, raw, file_hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (interp or "", names or "", "\n".join(manual_parts),
         negativ or "", raw or "", file_hash),
    )
    conn.execute(
        "INSERT OR REPLACE INTO search_index_map (file_hash, fts_rowid) VALUES (?, ?)",
        (file_hash, cur.lastrowid),
    )


def drop_search_index_row(conn: sqlite3.Connection, file_hash: str) -> None:
    """FTS-Zeile eines Items entfernen (Löschen, ADR 0023) — über die rowid."""
    old = conn.execute(
        "SELECT fts_rowid FROM search_index_map WHERE file_hash = ?", (file_hash,)
    ).fetchone()
    if old is not None:
        conn.execute("DELETE FROM search_index WHERE rowid = ?", (old[0],))
        conn.execute("DELETE FROM search_index_map WHERE file_hash = ?", (file_hash,))
