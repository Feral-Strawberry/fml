"""Zeitkommentare austauschen: Export als Datei, Import mit Vorschau (#228, ADR 0098).

Zwei fml-Instanzen tauschen Anmerkungen über eine JSON-Datei aus. Zuordnung
über den Datei-Hash (SHA-256, rechnerunabhängig); findet der Hash nichts,
hilft die Suno-Song-ID als Rückfallebene (gleicher Song, andere Datei) —
solche Treffer übernimmt der Import nur nach ausdrücklicher Bestätigung.

Format (englische Schlüssel, in ``docs/audio.md`` beschrieben)::

    {"format": "fml-time-comments", "version": 1, "exported_at": "…",
     "items": [{"file_hash": "…", "name": "song.mp3", "duration": 187.4,
                "suno_ids": ["…"],
                "comments": [{"at_ms": 61000, "text": "…",
                              "created_at": "…", "updated_at": "…"}]}]}

Die Datei ist fremde Eingabe: ``parse_exchange`` prüft Schema, Typen und
Deckel, bevor irgendetwas die Datenbank sieht; Pfade kommen darin nicht vor
(``name`` ist nur ein Hinweis für Menschen). Ein Kommentar mit gleichem
Item, gleicher Stelle und gleichem Text wird übersprungen — derselbe Import
zweimal ändert nichts, und ein Rückweg (A → B → A) verdoppelt nichts.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..db.store import now_iso, update_search_index
from ..messages import UserError
from . import filters

FORMAT = "fml-time-comments"
VERSION = 1

# Deckel für fremde Dateien (großzügig für echte Bestände, eng genug gegen Unfug).
MAX_BYTES = 20 * 1024 * 1024
MAX_ITEMS = 50_000
MAX_COMMENTS = 200_000
MAX_ITEM_COMMENTS = 2_000             # je Song; jede Listenzeile trägt ihre Kommentare
MAX_TEXT = 2_000
MAX_NAME = 300
MAX_SOURCE = 60
MAX_AT_MS = 48 * 3600 * 1000          # 48 h — länger ist kein Song
_HASH = re.compile(r"^[0-9a-f]{64}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_CHUNK = 500


# -- Export ---------------------------------------------------------------------------


def _commented_hashes(
    conn: sqlite3.Connection, *, hashes: list[str] | None, filter_expr: str | None,
    view_preds: tuple[filters.Predicate, ...],
) -> list[str]:
    has = "EXISTS (SELECT 1 FROM time_comments c WHERE c.file_hash = i.file_hash)"
    if hashes is not None:
        found: list[str] = []
        for start in range(0, len(hashes), _CHUNK):
            chunk = hashes[start:start + _CHUNK]
            marks = ",".join("?" * len(chunk))
            found += [r[0] for r in conn.execute(
                f"SELECT i.file_hash FROM items i WHERE i.file_hash IN ({marks}) AND {has}",
                chunk)]
        return sorted(set(found))
    predicates = list(view_preds)
    if filter_expr and filter_expr.strip():
        predicates += filters.parse(filter_expr)
    fragment, params = filters.build_where(predicates)
    where = f"({fragment}) AND {has}" if fragment else has
    return [r[0] for r in conn.execute(
        f"SELECT i.file_hash FROM items i WHERE {where} ORDER BY i.file_hash", params)]


def export_comments(
    conn: sqlite3.Connection, *, hashes: list[str] | None = None,
    filter_expr: str | None = None, view_preds: tuple[filters.Predicate, ...] = (),
    now: str | None = None,
) -> dict[str, Any]:
    """Austauschdatei für alle Items des Scopes, die Zeitkommentare tragen.

    Scope wie bei den Sammel-Aktionen: ``hashes`` (Auswahl) gewinnt über
    ``filter_expr`` (Suchergebnis; leer = alle) samt Grundbereich der Ansicht.
    """
    items = []
    for file_hash in _commented_hashes(conn, hashes=hashes, filter_expr=filter_expr,
                                       view_preds=view_preds):
        row = conn.execute(
            """SELECT i.duration,
                      (SELECT path FROM file_locations l WHERE l.file_hash = i.file_hash
                        ORDER BY l.id LIMIT 1) AS path
                 FROM items i WHERE i.file_hash = ?""", (file_hash,)).fetchone()
        entry: dict[str, Any] = {
            "file_hash": file_hash,
            "name": Path(row["path"]).name if row["path"] else None,
            "duration": row["duration"],
        }
        suno = [r[0] for r in conn.execute(
            """SELECT DISTINCT value_text FROM interpreted_metadata
                WHERE file_hash = ? AND field = 'song_id' ORDER BY value_text""", (file_hash,))]
        if suno:
            entry["suno_ids"] = suno
        entry["comments"] = [dict(r) for r in conn.execute(
            """SELECT at_ms, text, created_at, updated_at FROM time_comments
                WHERE file_hash = ? ORDER BY at_ms, id""", (file_hash,))]
        items.append(entry)
    return {"format": FORMAT, "version": VERSION, "exported_at": now or now_iso(),
            "items": items}


# -- Import: prüfen ---------------------------------------------------------------------


@dataclass
class ExchangeComment:
    at_ms: int
    text: str
    created_at: str | None = None


@dataclass
class ExchangeItem:
    file_hash: str
    name: str | None
    suno_ids: list[str] = field(default_factory=list)
    comments: list[ExchangeComment] = field(default_factory=list)


def _bad(detail: str) -> UserError:
    return UserError("exchangeInvalid", detail=detail)


def _stamp(value: Any) -> str | None:
    # Zeitstempel sind Anzeige-Beiwerk: nur ein kurzer ISO-artiger Text zählt.
    if isinstance(value, str) and 10 <= len(value) <= 40 and value[:4].isdigit():
        return value
    return None


def parse_exchange(data: Any) -> list[ExchangeItem]:
    """Austauschdatei (schon als JSON geladen) prüfen → Items.

    Wirft ``UserError`` mit dem ersten Fehler; nichts wird still repariert
    außer Beiwerk (unbrauchbarer Name/Zeitstempel fällt weg).
    """
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise UserError("exchangeWrongFormat")
    if data.get("version") != VERSION:
        raise UserError("exchangeWrongVersion", version=str(data.get("version")))
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise _bad("items")
    if len(raw_items) > MAX_ITEMS:
        raise _bad(f"items > {MAX_ITEMS}")
    items: list[ExchangeItem] = []
    total = 0
    for n, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            raise _bad(f"items[{n}]")
        file_hash = raw.get("file_hash")
        if not isinstance(file_hash, str) or not _HASH.match(file_hash):
            raise _bad(f"items[{n}].file_hash")
        name = raw.get("name")
        name = name[:MAX_NAME] if isinstance(name, str) and name.strip() else None
        suno = raw.get("suno_ids", [])
        if not isinstance(suno, list) or len(suno) > 20:
            raise _bad(f"items[{n}].suno_ids")
        suno_ids = [s.lower() for s in suno if isinstance(s, str) and _UUID.match(s.lower())]
        comments = raw.get("comments")
        if not isinstance(comments, list):
            raise _bad(f"items[{n}].comments")
        if len(comments) > MAX_ITEM_COMMENTS:
            raise _bad(f"items[{n}].comments > {MAX_ITEM_COMMENTS}")
        total += len(comments)
        if total > MAX_COMMENTS:
            raise _bad(f"comments > {MAX_COMMENTS}")
        parsed = []
        for c in comments:
            at_ms, text = (c.get("at_ms"), c.get("text")) if isinstance(c, dict) else (None, None)
            if (not isinstance(at_ms, int) or isinstance(at_ms, bool)
                    or not 0 <= at_ms <= MAX_AT_MS):
                raise _bad(f"items[{n}].comments.at_ms")
            if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
                raise _bad(f"items[{n}].comments.text")
            parsed.append(ExchangeComment(at_ms, text.strip(), _stamp(c.get("created_at"))))
        items.append(ExchangeItem(file_hash, name, suno_ids, parsed))
    return items


def clean_source(source: str | None) -> str:
    """Herkunfts-Etikett aus dem Dialog: getrimmt, Pflicht, gedeckelt."""
    value = " ".join((source or "").split())
    if not value:
        raise UserError("exchangeSourceEmpty")
    return value[:MAX_SOURCE]


# -- Import: planen + übernehmen ----------------------------------------------------------


def _targets(conn: sqlite3.Connection, item: ExchangeItem) -> tuple[str, list[str]]:
    """Wohin gehört ein Item? → ("hash" | "song_id" | "missing", Ziel-Hashes)."""
    if conn.execute("SELECT 1 FROM items WHERE file_hash = ?", (item.file_hash,)).fetchone():
        return "hash", [item.file_hash]
    if item.suno_ids:
        marks = ",".join("?" * len(item.suno_ids))
        found = [r[0] for r in conn.execute(
            f"""SELECT DISTINCT file_hash FROM interpreted_metadata
                 WHERE field = 'song_id' AND value_text IN ({marks})
                 ORDER BY file_hash""", item.suno_ids)]
        if found:
            return "song_id", found
    return "missing", []


def _is_new(conn: sqlite3.Connection, file_hash: str, c: ExchangeComment) -> bool:
    return conn.execute(
        "SELECT 1 FROM time_comments WHERE file_hash = ? AND at_ms = ? AND text = ?",
        (file_hash, c.at_ms, c.text)).fetchone() is None


def _display_name(conn: sqlite3.Connection, file_hash: str) -> str | None:
    row = conn.execute(
        "SELECT path FROM file_locations WHERE file_hash = ? ORDER BY id LIMIT 1",
        (file_hash,)).fetchone()
    return Path(row[0]).name if row else None


def preview_import(conn: sqlite3.Connection, items: list[ExchangeItem]) -> dict[str, Any]:
    """Was würde der Import tun? Nur lesend.

    ``by_hash``/``by_song_id``: Items und neue bzw. schon vorhandene
    Kommentare; ``song_id_items`` listet die Rückfall-Treffer (Name in der
    Datei → Name hier) zur Bestätigung, ``missing_names`` die Unauffindbaren.
    """
    out: dict[str, Any] = {
        "items": len(items), "comments": sum(len(i.comments) for i in items),
        "by_hash": {"items": 0, "new": 0, "known": 0},
        "by_song_id": {"items": 0, "new": 0, "known": 0},
        "song_id_items": [], "missing": 0, "missing_names": [],
    }
    for item in items:
        how, targets = _targets(conn, item)
        if how == "missing":
            out["missing"] += 1
            if len(out["missing_names"]) < 200:
                out["missing_names"].append(item.name or item.file_hash[:12])
            continue
        bucket = out["by_hash" if how == "hash" else "by_song_id"]
        bucket["items"] += 1
        for target in targets:
            for c in item.comments:
                bucket["new" if _is_new(conn, target, c) else "known"] += 1
        if how == "song_id" and len(out["song_id_items"]) < 200:
            out["song_id_items"].append({
                "name": item.name or item.file_hash[:12],
                "here": [_display_name(conn, t) or t[:12] for t in targets],
            })
    return out


def apply_import(
    conn: sqlite3.Connection, items: list[ExchangeItem], *, source: str,
    include_song_id: bool = False, now: str | None = None,
) -> dict[str, Any]:
    """Kommentare übernehmen, in EINER Transaktion. Liefert Zähler.

    Übernommene Kommentare tragen ``source`` als Herkunft; ``created_at``
    bleibt, wenn die Datei einen brauchbaren Wert hat (sonst jetzt).
    """
    source = clean_source(source)
    ts = now or now_iso()
    summary = {"added": 0, "known": 0, "items": 0, "skipped_song_id": 0, "missing": 0}
    with conn:
        for item in items:
            how, targets = _targets(conn, item)
            if how == "missing":
                summary["missing"] += 1
                continue
            if how == "song_id" and not include_song_id:
                summary["skipped_song_id"] += 1
                continue
            for target in targets:
                touched = False
                for c in item.comments:
                    if not _is_new(conn, target, c):
                        summary["known"] += 1
                        continue
                    conn.execute(
                        """INSERT INTO time_comments
                               (file_hash, at_ms, text, created_at, updated_at, source)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (target, c.at_ms, c.text, c.created_at or ts, ts, source))
                    summary["added"] += 1
                    touched = True
                if touched:
                    update_search_index(conn, target)   # ADR 0036: sofort findbar
            summary["items"] += 1
    return summary
