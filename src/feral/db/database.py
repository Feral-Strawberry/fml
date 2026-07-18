"""DB-Verbindung und Schema-Migrationen (stdlib sqlite3).

Eine Verbindung pro Server-Prozess serialisiert alle Schreibzugriffe (ADR 0007).
Schema-Versionierung über ``PRAGMA user_version`` + **nummerierte Migrationsdateien**
in ``migrations/NNNN_*.sql`` (ADR 0012): Datei ``0001_…`` bringt die DB auf
Version 1, ``0002_…`` auf Version 2 usw. Eine Schema-Änderung = eine neue Datei,
kein Anfassen von bestehendem Code.
"""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

_MIGRATIONS_DIR = Path(__file__).with_name("migrations")
_MIGRATION_NAME = re.compile(r"^(\d{4})_.+\.sql$")


def migration_files() -> list[tuple[int, Path]]:
    """Alle Migrationsdateien als ``(version, pfad)``, aufsteigend sortiert.

    Prüft, dass die Versionen lückenlos bei 1 beginnen — eine vergessene oder
    doppelt vergebene Nummer soll sofort auffallen, nicht erst in einer kaputten DB.
    """
    found: list[tuple[int, Path]] = []
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        m = _MIGRATION_NAME.match(path.name)
        if not m:
            raise RuntimeError(f"Migrationsdatei passt nicht zum Muster NNNN_name.sql: {path.name}")
        found.append((int(m.group(1)), path))
    for expected, (version, path) in enumerate(found, start=1):
        if version != expected:
            raise RuntimeError(
                f"Migrationen nicht lückenlos: erwartet {expected:04d}, gefunden {path.name}"
            )
    return found


def schema_version() -> int:
    """Die aktuellste Schema-Version (= höchste Migrationsnummer)."""
    files = migration_files()
    return files[-1][0] if files else 0


def connect(path: str | Path) -> sqlite3.Connection:
    """Öffne (oder erstelle) die DB und bringe sie auf den aktuellen Schema-Stand.

    Schaltet WAL (gleichzeitige Leser neben dem einen Schreiber) und Foreign-Key-
    Durchsetzung ein. Gibt eine offene Verbindung mit ``sqlite3.Row`` als
    Row-Factory zurück (Zugriff per Spaltenname).

    ``path`` darf ``":memory:"`` sein (für Tests). **Nie auf Netzlaufwerken**
    anlegen (ADR 0007).
    """
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    # busy_timeout ZUERST: bei parallelem Erst-Start (Engine-Thread + erste
    # Anfrage) braucht schon der Migrations-Lock das Warten — sonst fliegt
    # sofort »database is locked«.
    conn.execute("PRAGMA busy_timeout=30000")
    # Der WAL-Umschalter nutzt den busy-Handler nicht zuverlässig: schalten
    # mehrere frische Verbindungen gleichzeitig um, wirft er trotz Timeout —
    # kurz nachfassen (danach ist die DB dauerhaft WAL, der Fall ist einmalig).
    for _ in range(600):
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            break
        except sqlite3.OperationalError:
            time.sleep(0.05)
    else:
        conn.execute("PRAGMA journal_mode=WAL")  # letzter Versuch: Fehler zeigen
    conn.execute("PRAGMA foreign_keys=ON")
    apply_migrations(conn)
    return conn


def _statements(sql: str):
    """Zerlege ein Migrationsskript in einzelne Statements (für execute()).

    ``executescript`` committet implizit — damit ließe sich der Migrationslauf
    nicht in EINE Transaktion sperren. Migrationsdateien sind unsere eigenen:
    jedes Statement endet mit ``;`` (``sqlite3.complete_statement`` erkennt das
    auch über Kommentare und Strings hinweg); ein Rest ohne ``;`` ist nur noch
    Kommentar/Leerraum und fällt weg.
    """
    pending = ""
    for line in sql.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            yield pending
            pending = ""


def apply_migrations(conn: sqlite3.Connection) -> None:
    """Bringe die DB auf die aktuellste Version (idempotent, nebenläufigkeitsfest).

    Liest ``PRAGMA user_version`` und spielt alle Migrationsdateien mit höherer
    Nummer der Reihe nach ein — in **einer** Schreib-Transaktion
    (``BEGIN IMMEDIATE``). Das serialisiert parallele Erst-Starts (der
    Engine-Writer-Thread und die erste HTTP-Anfrage öffnen beide eine
    Verbindung): ohne den Lock migrierten beide, und ``ALTER TABLE`` ist im
    Gegensatz zu ``CREATE … IF NOT EXISTS`` nicht idempotent. Der Zweite
    wartet (busy_timeout), liest ``user_version`` erneut und hat nichts zu tun.
    """
    files = migration_files()
    if not files:
        return
    if conn.execute("PRAGMA user_version").fetchone()[0] >= files[-1][0]:
        return  # Schnellpfad: aktuell — kein Schreib-Lock nötig

    conn.execute("BEGIN IMMEDIATE")
    try:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for version, path in files:
            if version <= current:
                continue
            for statement in _statements(path.read_text(encoding="utf-8")):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version={version}")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
