"""Sammel-Aktionen auf das ganze Suchergebnis (Großbaustelle K, ADR 0040).

EIN Mechanismus für beide Scopes: Die Treffermenge — aus einem
Filterausdruck (ADR 0035) oder einer expliziten Hash-Liste (Multiselect) —
wird EINMAL als Temp-Tabelle materialisiert (Bauform aus ADR 0037), dann
laufen Set-basierte Statements in EINER Transaktion durch den einen Writer
(ADR 0007). Semantik (mit Feral Strawberry, ADR 0040):

- Bewertung ist BASIS-Bewertung: füllt nur Unbewertete, überschreibt nie.
- Tag wird allen Treffern angehängt (idempotent, Vokabular wie manual.add_tag).
- Notiz wird per Zeilenumbruch ANGEHÄNGT, nie überschrieben.
- Manuelles Modell wird gesetzt (wie die Multiselect-Aktion, ADR 0022).
- Ablehnen (ADR 0041, ersetzt Löschen) läuft ALLEIN: Item + Metadaten raus,
  Hash auf die Sperrliste samt letzter Fundort-Pfade — keine Mediendatei
  wird angefasst, nur der eigene Thumb-Cache wird aufgeräumt.

FTS-Pflege (ADR 0036) nur für tatsächlich geänderte Items; Bewertungen
stehen nicht im Index und brauchen keine.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ..db.store import drop_search_index_row, now_iso, update_search_index
from ..messages import UserError, dump
from . import filters

_HITS = "bulk_hits"


def apply_bulk(
    conn: sqlite3.Connection,
    *,
    filter_expr: str | None = None,
    hashes: list[str] | None = None,
    rating: int | None = None,
    add_tag: str | None = None,
    model: str | None = None,
    note: str | None = None,
    reject: bool = False,
    thumb_cache: str | Path | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Aktionen auf alle Treffer anwenden; liefert eine ehrliche Zusammenfassung.

    ``hashes`` gewinnt über ``filter_expr``; ein leerer Ausdruck heißt „alle
    Items". Unbekannte Hashes werden still übersprungen (wie
    ``/api/batch/annotate``). Ungültige Parameter ⇒ ``ValueError``.
    """
    add_tag = (add_tag or "").strip() or None
    model = (model or "").strip() or None
    note = (note or "").strip() or None
    if reject and (rating is not None or add_tag or model or note):
        # Kuratieren auf Items, die im selben Durchlauf verschwinden, wäre
        # nie das Gewollte — ehrlich ablehnen statt still halb ausführen.
        raise UserError("errRejectExclusive")
    if not reject and rating is None and add_tag is None and model is None and note is None:
        raise UserError("errNoAction")
    if rating is not None and rating not in (1, 2, 3, 4, 5):
        # 0 („löschen") gibt es hier bewusst nicht — die Basisbewertung füllt nur.
        raise UserError("errBaseRating", value=repr(rating))

    ts = now or now_iso()
    with conn:
        total = _materialize(conn, filter_expr=filter_expr, hashes=hashes)
        summary: dict[str, Any] = {"matched": total}
        fts_dirty: set[str] = set()
        try:
            if reject:
                summary["rejected"] = _apply_reject(conn, ts, thumb_cache)
            if rating is not None:
                summary["rating_set"] = _apply_rating(conn, rating, ts)
            if add_tag is not None:
                changed = _apply_tag(conn, add_tag, ts)
                summary["tagged"] = len(changed)
                fts_dirty.update(changed)
            if model is not None:
                changed = _apply_model(conn, model, ts)
                summary["model_set"] = len(changed)
                fts_dirty.update(changed)
            if note is not None:
                summary["noted"] = _apply_note(conn, note, ts)
                fts_dirty.update(
                    r[0] for r in conn.execute(f"SELECT file_hash FROM {_HITS}")
                )
            for file_hash in fts_dirty:
                update_search_index(conn, file_hash)   # ADR 0036, gleiche Transaktion
        finally:
            conn.execute(f"DROP TABLE IF EXISTS {_HITS}")
    return summary


def _materialize(
    conn: sqlite3.Connection, *, filter_expr: str | None, hashes: list[str] | None
) -> int:
    """Treffermenge als Temp-Tabelle ``bulk_hits`` (nur katalogisierte Items)."""
    conn.execute(f"DROP TABLE IF EXISTS {_HITS}")
    if hashes is not None:
        conn.execute(f"CREATE TEMP TABLE {_HITS} (file_hash TEXT PRIMARY KEY)")
        conn.executemany(
            f"INSERT OR IGNORE INTO {_HITS} (file_hash) "
            f"SELECT file_hash FROM items WHERE file_hash = ?",
            [(h,) for h in hashes],
        )
    else:
        # Leerer Ausdruck = „alle Items" (der Parser lehnt Leeres ehrlich ab).
        fragment, params = "", []
        if filter_expr and filter_expr.strip():
            fragment, params = filters.build_where(filters.parse(filter_expr))
        where = f"WHERE ({fragment})" if fragment else ""
        conn.execute(
            f"CREATE TEMP TABLE {_HITS} AS SELECT i.file_hash FROM items i {where}",
            params,
        )
        conn.execute(f"CREATE UNIQUE INDEX idx_{_HITS} ON {_HITS}(file_hash)")
    # ANALYZE verrät dem Planer die Größe (Muster aus ADR 0037).
    conn.execute(f"ANALYZE {_HITS}")
    return conn.execute(f"SELECT COUNT(*) FROM {_HITS}").fetchone()[0]


def _apply_rating(conn: sqlite3.Connection, rating: int, ts: str) -> int:
    """Basisbewertung: nur Unbewertete erhalten den Wert (ADR 0040)."""
    n = conn.execute(
        f"""SELECT COUNT(*) FROM {_HITS} h
             LEFT JOIN annotations a ON a.file_hash = h.file_hash
            WHERE a.rating IS NULL"""
    ).fetchone()[0]
    conn.execute(
        f"""INSERT INTO annotations (file_hash, rating, created_at, updated_at)
            SELECT file_hash, ?, ?, ? FROM {_HITS} WHERE true
            ON CONFLICT(file_hash) DO UPDATE SET
                rating = excluded.rating, updated_at = excluded.updated_at
            WHERE annotations.rating IS NULL""",
        (rating, ts, ts),
    )
    return int(n)


def _apply_tag(conn: sqlite3.Connection, name: str, ts: str) -> list[str]:
    """Tag an alle Treffer (idempotent); liefert die neu getaggten Hashes."""
    conn.execute(
        "INSERT INTO tags (name, created_at) VALUES (?, ?) ON CONFLICT(name) DO NOTHING",
        (name, ts),
    )
    tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()[0]
    changed = [
        r[0]
        for r in conn.execute(
            f"""SELECT h.file_hash FROM {_HITS} h
                 WHERE NOT EXISTS (SELECT 1 FROM item_tags it
                                    WHERE it.file_hash = h.file_hash
                                      AND it.tag_id = ?)""",
            (tag_id,),
        )
    ]
    conn.execute(
        f"""INSERT OR IGNORE INTO item_tags (file_hash, tag_id, created_at)
            SELECT file_hash, ?, ? FROM {_HITS}""",
        (tag_id, ts),
    )
    return changed


def _apply_model(conn: sqlite3.Connection, model: str, ts: str) -> list[str]:
    """Manuelles Modell setzen (ADR 0022); liefert die geänderten Hashes."""
    changed = [
        r[0]
        for r in conn.execute(
            f"""SELECT h.file_hash FROM {_HITS} h
                 LEFT JOIN annotations a ON a.file_hash = h.file_hash
                WHERE a.model IS NOT ?""",
            (model,),
        )
    ]
    conn.execute(
        f"""INSERT INTO annotations (file_hash, model, created_at, updated_at)
            SELECT file_hash, ?, ?, ? FROM {_HITS} WHERE true
            ON CONFLICT(file_hash) DO UPDATE SET
                model = excluded.model, updated_at = excluded.updated_at""",
        (model, ts, ts),
    )
    return changed


def _apply_reject(
    conn: sqlite3.Connection, ts: str, thumb_cache: str | Path | None
) -> int:
    """Ablehnen (ADR 0041): Hash auf die Sperrliste samt letzter Fundort-
    Pfade, Item raus (CASCADE räumt Fundorte/Metadaten/manuelle Schicht ab),
    FTS-Zeile weg, Thumb-Cache-Dateien weg. Die Mediendatei bleibt liegen —
    egal ob Library oder nur indiziert (»Original heilig«)."""
    from ..thumbs import thumb_path

    hashes = [r[0] for r in conn.execute(f"SELECT file_hash FROM {_HITS}")]
    conn.execute(
        f"""INSERT OR REPLACE INTO blocked_hashes
                (file_hash, reason, blocked_at, last_paths)
            SELECT h.file_hash, ?, ?,
                   (SELECT json_group_array(fl.path) FROM file_locations fl
                     WHERE fl.file_hash = h.file_hash)
              FROM {_HITS} h""",
        (dump("blockedRejected"), ts),
    )
    # Stat-Gedächtnis (ADR 0042-Ergänzung, Migration 0019): die bekannten
    # Stats VOR dem CASCADE-Löschen übernehmen — der Watcher überspringt die
    # abgelehnten Dateien dann ohne Hashen; Entsperren räumt per Hash auf.
    # Alt-Zeilen ohne Stat (vor Migration 0018) laufen einmal den vollen Weg,
    # der Scan schreibt das Gedächtnis dann selbst ('gesperrt').
    conn.execute(
        f"""INSERT OR REPLACE INTO scan_memory
                (path, file_size, mtime_ns, outcome, file_hash, last_seen_at)
            SELECT fl.path, fl.file_size, fl.mtime_ns, 'gesperrt', fl.file_hash, ?
              FROM file_locations fl JOIN {_HITS} h USING (file_hash)
             WHERE fl.file_size IS NOT NULL AND fl.mtime_ns IS NOT NULL""",
        (ts,),
    )
    conn.execute(
        f"DELETE FROM items WHERE file_hash IN (SELECT file_hash FROM {_HITS})"
    )
    for file_hash in hashes:
        drop_search_index_row(conn, file_hash)
        if thumb_cache is not None:
            thumb = thumb_path(thumb_cache, file_hash)
            thumb.unlink(missing_ok=True)
            thumb.with_suffix(".fail").unlink(missing_ok=True)
    return len(hashes)


def _apply_note(conn: sqlite3.Connection, note: str, ts: str) -> int:
    """Notiz anhängen (Zeilenumbruch), nie überschreiben (ADR 0040)."""
    n = conn.execute(f"SELECT COUNT(*) FROM {_HITS}").fetchone()[0]
    conn.execute(
        f"""INSERT INTO annotations (file_hash, notes, created_at, updated_at)
            SELECT file_hash, ?, ?, ? FROM {_HITS} WHERE true
            ON CONFLICT(file_hash) DO UPDATE SET
                notes = COALESCE(annotations.notes || char(10), '') || excluded.notes,
                updated_at = excluded.updated_at""",
        (note, ts, ts),
    )
    return int(n)
