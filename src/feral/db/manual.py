"""Manuelle Schicht: Rating, Notizen, Tags, Zeitkommentare (Stufe 3.1, ADR 0005/0017; #163).

Eigene Persistenz-Funktionen, strikt getrennt von der extrahierten Schicht —
hier schreibt ausschließlich Feral Strawberry (bzw. die GUI in seinem Auftrag), nie ein
Parser. Alle Funktionen sind idempotent und tragen Zeitstempel; `now` ist für
Tests injizierbar (Muster wie `store.py`).

Konventionen:
- `rating`: 1–5 Sterne; `0` oder `None` löscht die Bewertung.
- Eine `annotations`-Zeile ohne Rating und ohne Notizen wird entfernt.
- Tag-Namen werden getrimmt und case-insensitiv dedupliziert ("Portrait" ==
  "portrait"); Tags überleben das Entfernen vom letzten Item (Vokabular).
- Unbekannter `file_hash` ⇒ ``ValueError`` (klarer als ein FK-Fehler).
- Textänderungen (Notizen, Tags, manuelles Modell, Zeitkommentare) pflegen die FTS-Zeile des
  Items in derselben Transaktion (ADR 0036) — ein Tag ist sofort findbar.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..messages import UserError
from .store import now_iso, update_search_index


def _require_item(conn: sqlite3.Connection, file_hash: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM items WHERE file_hash = ?", (file_hash,)
    ).fetchone()
    if row is None:
        raise UserError("itemUnknown", hash=file_hash)


def _prune_empty(conn: sqlite3.Connection, file_hash: str) -> None:
    conn.execute(
        """DELETE FROM annotations
            WHERE file_hash = ? AND rating IS NULL AND notes IS NULL AND model IS NULL""",
        (file_hash,),
    )


def _upsert_annotation(
    conn: sqlite3.Connection, file_hash: str, column: str, value: Any, ts: str
) -> None:
    # column ist ein Code-Literal ('rating'/'notes'), nie Nutzereingabe.
    conn.execute(
        f"""
        INSERT INTO annotations (file_hash, {column}, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(file_hash) DO UPDATE SET
            {column}   = excluded.{column},
            updated_at = excluded.updated_at
        """,
        (file_hash, value, ts, ts),
    )


def set_rating(
    conn: sqlite3.Connection, file_hash: str, rating: int | None, *, now: str | None = None
) -> None:
    """Bewertung setzen (1–5) oder löschen (0/None). Idempotent."""
    if rating is not None and rating not in (0, 1, 2, 3, 4, 5):
        raise UserError("ratingRange", value=repr(rating))
    _require_item(conn, file_hash)
    value = None if not rating else int(rating)
    with conn:
        _upsert_annotation(conn, file_hash, "rating", value, now or now_iso())
        _prune_empty(conn, file_hash)


def set_notes(
    conn: sqlite3.Connection, file_hash: str, notes: str | None, *, now: str | None = None
) -> None:
    """Notizen setzen; leerer Text oder None löscht sie. Idempotent."""
    _require_item(conn, file_hash)
    value = notes.strip() if notes and notes.strip() else None
    with conn:
        _upsert_annotation(conn, file_hash, "notes", value, now or now_iso())
        _prune_empty(conn, file_hash)
        # ADR 0036: Notizen sind Teil der Standard-Suche — Index sofort
        # nachziehen, in derselben Transaktion (kein Drift, kein Admin-Knopf).
        update_search_index(conn, file_hash)


def set_model(
    conn: sqlite3.Connection, file_hash: str, model: str | None, *, now: str | None = None
) -> None:
    """Manuelles Modell setzen (ADR 0022); leerer Text oder None löscht es.

    Überschreibt in Zählern/Filtern das interpretierte Modell — gedacht zum
    Aufräumen metadatenloser Bestände (Midjourney-Screenshot-Ära)."""
    _require_item(conn, file_hash)
    value = model.strip() if model and model.strip() else None
    with conn:
        _upsert_annotation(conn, file_hash, "model", value, now or now_iso())
        _prune_empty(conn, file_hash)
        update_search_index(conn, file_hash)   # ADR 0036


def add_tag(
    conn: sqlite3.Connection, file_hash: str, name: str, *, now: str | None = None
) -> int:
    """Tag ans Item hängen (legt den Tag bei Bedarf an). Liefert die Tag-ID.

    Idempotent: erneutes Anhängen desselben (auch anders geschriebenen)
    Namens ändert nichts.
    """
    name = (name or "").strip()
    if not name:
        raise UserError("tagEmpty")
    _require_item(conn, file_hash)
    ts = now or now_iso()
    with conn:
        conn.execute(
            "INSERT INTO tags (name, created_at) VALUES (?, ?) ON CONFLICT(name) DO NOTHING",
            (name, ts),
        )
        tag_id = conn.execute(
            "SELECT id FROM tags WHERE name = ?", (name,)
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO item_tags (file_hash, tag_id, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT(file_hash, tag_id) DO NOTHING""",
            (file_hash, tag_id, ts),
        )
        update_search_index(conn, file_hash)   # ADR 0036: Tag sofort findbar
    return int(tag_id)


def remove_tag(conn: sqlite3.Connection, file_hash: str, name: str) -> bool:
    """Tag vom Item lösen (der Tag selbst bleibt im Vokabular).

    Liefert True, wenn eine Verknüpfung entfernt wurde.
    """
    with conn:
        cur = conn.execute(
            """DELETE FROM item_tags
                WHERE file_hash = ?
                  AND tag_id = (SELECT id FROM tags WHERE name = ?)""",
            (file_hash, (name or "").strip()),
        )
        if cur.rowcount > 0:
            # Nur bei echter Änderung — sonst legte ein unbekannter Hash
            # eine verwaiste FTS-Zeile an (Drift gegen items).
            update_search_index(conn, file_hash)   # ADR 0036
    return cur.rowcount > 0


def annotations_for(conn: sqlite3.Connection, file_hash: str) -> dict[str, Any]:
    """Manuelle Schicht eines Items: {rating, notes, model, updated_at, tags, cover}."""
    row = conn.execute(
        "SELECT rating, notes, model, updated_at FROM annotations WHERE file_hash = ?",
        (file_hash,),
    ).fetchone()
    tags = [
        r["name"]
        for r in conn.execute(
            """SELECT t.name FROM item_tags it JOIN tags t ON t.id = it.tag_id
                WHERE it.file_hash = ? ORDER BY t.name COLLATE NOCASE""",
            (file_hash,),
        )
    ]
    return {
        "rating": row["rating"] if row else None,
        "notes": row["notes"] if row else None,
        "model": row["model"] if row else None,
        "updated_at": row["updated_at"] if row else None,
        "tags": tags,
        # Cover eines Songs (#165, ADR 0090): Hash des Bildes oder None.
        "cover": cover_of(conn, file_hash),
    }


def list_tags(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Das Tag-Vokabular mit Nutzungszählern (alphabetisch)."""
    return [
        dict(r)
        for r in conn.execute(
            """SELECT t.id, t.name, COUNT(it.file_hash) AS count
                 FROM tags t LEFT JOIN item_tags it ON it.tag_id = t.id
                GROUP BY t.id ORDER BY t.name COLLATE NOCASE"""
        )
    ]


# -- Zeitkommentare (Audio A6, #163, ADR 0088) ---------------------------------------------

def _comment_text(text: str | None) -> str:
    value = (text or "").strip()
    if not value:
        raise UserError("commentEmpty")
    return value


def _comment_ms(at_ms: int) -> int:
    if not isinstance(at_ms, int) or isinstance(at_ms, bool) or at_ms < 0:
        raise UserError("commentTime", value=repr(at_ms))
    return at_ms


def list_comments(conn: sqlite3.Connection, file_hash: str) -> list[dict[str, Any]]:
    """Zeitkommentare eines Items in zeitlicher Folge."""
    return [
        dict(r)
        for r in conn.execute(
            """SELECT id, at_ms, text, created_at, updated_at FROM time_comments
                WHERE file_hash = ? ORDER BY at_ms, id""",
            (file_hash,),
        )
    ]


def add_comment(
    conn: sqlite3.Connection, file_hash: str, at_ms: int, text: str, *, now: str | None = None
) -> int:
    """Kommentar an der Stelle ``at_ms`` anlegen → id. Leerer Text ⇒ Fehler."""
    _require_item(conn, file_hash)
    value, ms = _comment_text(text), _comment_ms(at_ms)
    ts = now or now_iso()
    with conn:
        cur = conn.execute(
            """INSERT INTO time_comments (file_hash, at_ms, text, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (file_hash, ms, value, ts, ts),
        )
        update_search_index(conn, file_hash)   # ADR 0036: sofort findbar
    return int(cur.lastrowid)


def _require_comment(conn: sqlite3.Connection, file_hash: str, comment_id: int) -> None:
    row = conn.execute(
        "SELECT 1 FROM time_comments WHERE id = ? AND file_hash = ?", (comment_id, file_hash)
    ).fetchone()
    if row is None:
        raise UserError("commentUnknown", id=comment_id)


def update_comment(
    conn: sqlite3.Connection, file_hash: str, comment_id: int, *,
    text: str | None = None, at_ms: int | None = None, now: str | None = None,
) -> None:
    """Text und/oder Stelle eines Kommentars ändern. Leerer Text ⇒ Fehler
    (Löschen ist ``delete_comment``)."""
    _require_comment(conn, file_hash, comment_id)
    sets, params = [], []
    if text is not None:
        sets.append("text = ?")
        params.append(_comment_text(text))
    if at_ms is not None:
        sets.append("at_ms = ?")
        params.append(_comment_ms(at_ms))
    if not sets:
        return
    with conn:
        conn.execute(
            f"UPDATE time_comments SET {', '.join(sets)}, updated_at = ? WHERE id = ?",  # noqa: S608 — feste Spaltennamen
            (*params, now or now_iso(), comment_id),
        )
        update_search_index(conn, file_hash)


def delete_comment(conn: sqlite3.Connection, file_hash: str, comment_id: int) -> bool:
    """Kommentar löschen; ``False``, wenn es ihn (für dieses Item) nicht gab."""
    with conn:
        cur = conn.execute(
            "DELETE FROM time_comments WHERE id = ? AND file_hash = ?", (comment_id, file_hash)
        )
        if cur.rowcount:
            update_search_index(conn, file_hash)
    return bool(cur.rowcount)


# -- Cover (Audio A8, #165, ADR 0090) --------------------------------------------------------

def cover_of(conn: sqlite3.Connection, file_hash: str) -> str | None:
    """Hash des Coverbilds eines Songs oder ``None``."""
    row = conn.execute(
        "SELECT cover_hash FROM covers WHERE file_hash = ?", (file_hash,)
    ).fetchone()
    return row[0] if row else None


def set_cover(
    conn: sqlite3.Connection, file_hash: str, cover_hash: str, *, now: str | None = None
) -> None:
    """Bild ``cover_hash`` als Cover des Songs ``file_hash`` setzen (ersetzt ein
    vorhandenes). Nur ein Verweis in der DB, keine Datei wird angefasst.
    Song muss Audio sein, das Cover ein Bild der Bibliothek."""
    kinds = dict(conn.execute(
        "SELECT file_hash, media_kind FROM items WHERE file_hash IN (?, ?)",
        (file_hash, cover_hash),
    ).fetchall())
    for h in (file_hash, cover_hash):
        if h not in kinds:
            raise UserError("itemUnknown", hash=h)
    if kinds[file_hash] != "audio":
        raise UserError("coverNotSong")
    if kinds[cover_hash] != "image":
        raise UserError("coverNotImage")
    ts = now or now_iso()
    with conn:
        conn.execute(
            """INSERT INTO covers (file_hash, cover_hash, created_at, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(file_hash) DO UPDATE
                  SET cover_hash = excluded.cover_hash, updated_at = excluded.updated_at""",
            (file_hash, cover_hash, ts, ts),
        )


def remove_cover(conn: sqlite3.Connection, file_hash: str) -> bool:
    """Cover entfernen; ``False``, wenn der Song keins hatte."""
    with conn:
        cur = conn.execute("DELETE FROM covers WHERE file_hash = ?", (file_hash,))
    return bool(cur.rowcount)


def has_embedded_picture(conn: sqlite3.Connection, file_hash: str) -> bool:
    """Trägt die Audiodatei ein eingebettetes Bild (Suno-Cover, APIC, FLAC-
    PICTURE, M4A-``covr``)? Aus Schicht 1: Bild-Deskriptoren der Walker
    (``id3.picture_descriptor``) oder eine Bildspur in ffprobes Eckwerten —
    bei Audio ist jede „Video"-Spur das Cover. Zählt NICHT als Cover."""
    return conn.execute(
        """SELECT EXISTS (SELECT 1 FROM raw_metadata
                           WHERE file_hash = ?
                             AND (value_text LIKE '{"mime": %'
                                  OR (keyword = 'codec_type' AND value_text = 'video')))""",
        (file_hash,),
    ).fetchone()[0] == 1
