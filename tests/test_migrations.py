"""Tests für den Migrations-Läufer (nummerierte SQL-Dateien, ADR 0012)."""

from __future__ import annotations

import sqlite3

from feral.db import apply_migrations, connect, schema_version
from feral.db.database import migration_files


def test_migration_files_are_gapless_and_start_at_one():
    files = migration_files()
    assert [v for v, _ in files] == list(range(1, len(files) + 1))
    assert schema_version() == len(files)


def test_fresh_db_gets_latest_version(tmp_path):
    conn = connect(tmp_path / "fresh.sqlite")
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == schema_version()
        # Tabellen aus beiden Migrationen vorhanden.
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"items", "file_locations", "raw_metadata", "interpreted_metadata"} <= tables
    finally:
        conn.close()


def test_old_db_is_migrated_forward(tmp_path):
    # DB von Hand auf Version 1 bringen (nur die erste Migration).
    path = tmp_path / "old.sqlite"
    raw = sqlite3.connect(path)
    version_1 = migration_files()[0][1]
    raw.executescript(version_1.read_text(encoding="utf-8"))
    raw.execute("PRAGMA user_version=1")
    raw.commit()
    # Bestandsdaten anlegen, die die Migration überleben müssen.
    raw.execute(
        "INSERT INTO items (file_hash, file_size, container, media_kind,"
        " first_seen_at, updated_at) VALUES ('h', 1, 'png', 'image', 't', 't')"
    )
    raw.commit()
    raw.close()

    conn = connect(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == schema_version()
        assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
        # Neue Tabelle ist nutzbar.
        conn.execute("SELECT COUNT(*) FROM interpreted_metadata").fetchone()
    finally:
        conn.close()


def test_apply_migrations_is_idempotent(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    try:
        apply_migrations(conn)  # zweiter Lauf darf nichts kaputt machen
        assert conn.execute("PRAGMA user_version").fetchone()[0] == schema_version()
    finally:
        conn.close()


def test_parallel_first_connects_migrate_exactly_once(tmp_path):
    """Beim allerersten Start öffnen Engine-Writer-Thread und erste HTTP-Anfrage
    gleichzeitig eine Verbindung — beide liefen die Migrationen und ALTER TABLE
    (0007) knallte mit »duplicate column«. BEGIN IMMEDIATE serialisiert das."""
    import threading

    db = tmp_path / "race.sqlite"
    errors: list[Exception] = []
    barrier = threading.Barrier(4)

    def open_and_close() -> None:
        try:
            barrier.wait()
            connect(db).close()
        except Exception as exc:  # pragma: no cover — nur im Fehlerfall
            errors.append(exc)

    threads = [threading.Thread(target=open_and_close) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    conn = connect(db)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == schema_version()
    finally:
        conn.close()
