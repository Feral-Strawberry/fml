"""Smart Folders: gespeicherte Filterausdrücke (Stufe 3.3, ADR 0018).

Nur Persistenz — geparst und ausgeführt wird der Ausdruck in
``feral.web.filters``/``library.list_items``. ``now`` ist für Tests
injizierbar (Muster wie ``store.py``/``manual.py``).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..messages import UserError
from .store import now_iso


def create(
    conn: sqlite3.Connection, name: str, expression: str, *, now: str | None = None
) -> int:
    """Smart Folder anlegen; Name case-insensitiv einmalig. Liefert die ID."""
    name = (name or "").strip()
    expression = (expression or "").strip()
    if not name:
        raise UserError("folderNeedsName")
    if not expression:
        raise UserError("folderNeedsExpression")
    ts = now or now_iso()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO smart_folders (name, expression, created_at, updated_at)"
                " VALUES (?, ?, ?, ?)",
                (name, expression, ts, ts),
            )
    except sqlite3.IntegrityError:
        raise UserError("folderNameTaken", name=name)
    return int(cur.lastrowid)


def update(
    conn: sqlite3.Connection,
    folder_id: int,
    name: str,
    expression: str,
    *,
    now: str | None = None,
) -> None:
    """Smart Folder umbenennen und/oder Ausdruck überschreiben (Block S7)."""
    name = (name or "").strip()
    expression = (expression or "").strip()
    if not name:
        raise UserError("folderNeedsName")
    if not expression:
        raise UserError("folderNeedsExpression")
    try:
        with conn:
            cur = conn.execute(
                "UPDATE smart_folders SET name = ?, expression = ?, updated_at = ?"
                " WHERE id = ?",
                (name, expression, now or now_iso(), folder_id),
            )
    except sqlite3.IntegrityError:
        raise UserError("folderNameTaken", name=name)
    if cur.rowcount == 0:
        raise UserError("folderGone")


def delete(conn: sqlite3.Connection, folder_id: int) -> bool:
    """Smart Folder löschen. True, wenn einer entfernt wurde."""
    with conn:
        cur = conn.execute("DELETE FROM smart_folders WHERE id = ?", (folder_id,))
    return cur.rowcount > 0


def list_folders(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Alle Smart Folders, alphabetisch."""
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, name, expression, created_at, updated_at"
            " FROM smart_folders ORDER BY name COLLATE NOCASE"
        )
    ]
