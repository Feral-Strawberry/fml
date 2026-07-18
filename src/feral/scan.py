"""Rekursiver Verzeichnis-Scanner (Stufe 1).

Geht rekursiv über einen Ordner und nimmt jede Mediendatei auf: erkennen → hashen
→ Schicht-1-Metadaten extrahieren → in die DB schreiben. Damit wird ein Bestand
zum ersten Mal durchsuchbar (nach Prompt/Modell/Seed/Workflow).

Robust und nicht-abbrechend: Eine kaputte oder unlesbare Datei lässt den Scan nicht
sterben — sie landet im Report unter `failed`. Bekannte Container ohne fertigen
Extraktor (aktuell alles außer PNG) werden trotzdem **katalogisiert** (Hash,
Fundort, Container) und bekommen ihre Metadaten nachträglich, sobald der jeweilige
Extraktor steht — ganz im Sinne der Zwei-Schichten-Strategie (ADR 0004).

Aufruf als CLI:

    python -m feral.scan /pfad/zum/ordner --db ./feral.sqlite
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .db import connect, store_extraction, store_interpretations
from .db.store import now_iso
from .extract import container
from .extract.container import ExtractorNotImplementedError, UnknownContainerError
from .extract.types import ContainerExtraction
from .hashing import hash_file
from .interpret import interpret_items
from .messages import dump as msg_dump


@dataclass
class ScanReport:
    """Zusammenfassung eines Scan-Laufs."""

    scanned_files: int = 0          # insgesamt betrachtete Dateien
    media_files: int = 0            # als bekannter Container erkannt
    new_items: int = 0              # Hash war noch nicht in der DB
    known_items: int = 0            # Hash war bereits bekannt (Dublette/Re-Scan)
    with_metadata: int = 0          # Extraktion lieferte >= 1 Roh-Eintrag
    interpreted: int = 0            # Schicht 2 erkannte >= 1 strukturiertes Feld
    pending_extractor: int = 0      # erkannt, aber Extraktor folgt noch (z. B. PSD)
    skipped_unknown: int = 0        # kein bekannter Container (z. B. .txt, ._-Dateien)
    ausgefiltert: int = 0           # Import-Regeln (ADR 0046) — nicht katalogisiert
    blocked: int = 0                # Hash auf der Sperrliste (ADR 0023) — nicht katalogisiert
    files_with_warnings: int = 0    # Extraktion meldete Warnungen
    failed: list[tuple[str, str]] = field(default_factory=list)  # (pfad, fehler)

    def summary(self) -> str:
        lines = [
            f"  Dateien betrachtet : {self.scanned_files}",
            f"  davon Medien       : {self.media_files}",
            f"    neu aufgenommen  : {self.new_items}",
            f"    bereits bekannt  : {self.known_items}",
            f"    mit Metadaten    : {self.with_metadata}",
            f"    interpretiert    : {self.interpreted}",
            f"    Extraktor folgt  : {self.pending_extractor}",
            f"  übersprungen (kein Container): {self.skipped_unknown}",
            f"  ausgefiltert (Import-Regeln) : {self.ausgefiltert}",
            f"  gesperrt (Sperrliste) : {self.blocked}",
            f"  mit Warnungen      : {self.files_with_warnings}",
            f"  fehlgeschlagen     : {len(self.failed)}",
        ]
        return "\n".join(lines)


def scan_files(
    conn: sqlite3.Connection,
    files: Iterable[str | Path],
    *,
    progress: Callable[[ScanReport, Path], None] | None = None,
    rules: dict[str, Any] | None = None,
) -> ScanReport:
    """Scanne eine gegebene Menge von Dateien (erkennen → hashen → extrahieren → DB).

    Basis für `scan_directory` (alle Dateien eines Baums) und für den Auto-Watch
    (nur die geänderten Dateien). `progress` wird nach jeder Datei aufgerufen.
    ``rules`` — Import-Regeln (ADR 0046): Treffer werden NICHT katalogisiert
    (Zähler ``ausgefiltert``); bereits katalogisierte Items bleiben unberührt
    (dafür gibt es das Admin-Aufräumwerkzeug).
    """
    report = ScanReport()
    for path in files:
        path = Path(path)
        report.scanned_files += 1
        _process_file(conn, path, report, rules)
        if progress is not None:
            progress(report, path)
    return report


def scan_directory(
    conn: sqlite3.Connection,
    root: str | Path,
    *,
    progress: Callable[[ScanReport, Path], None] | None = None,
    rules: dict[str, Any] | None = None,
) -> ScanReport:
    """Scanne `root` rekursiv und schreibe alle Medien in die DB.

    Gibt den `ScanReport` zurück.
    """
    return scan_files(conn, _iter_files(Path(root)), progress=progress, rules=rules)


def _iter_files(root: Path):
    """Liefere alle regulären Dateien unter `root` (rekursiv, deterministisch sortiert)."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            yield Path(dirpath) / name


def _record_issue(conn: sqlite3.Connection, path: Path, kind: str, message: str) -> None:
    """Halte ein Scan-Problem fest (idempotent; Re-Scan öffnet quittierte wieder)."""
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


def _resolve_issues(conn: sqlite3.Connection, path: Path) -> None:
    """Quittiere offene Probleme einer Datei, die jetzt sauber durchgelaufen ist."""
    with conn:
        conn.execute(
            "UPDATE scan_issues SET resolved = 1 WHERE path = ? AND resolved = 0",
            (str(path),),
        )


def _remember_outcome(
    conn: sqlite3.Connection, path: Path, outcome: str,
    *, stat: os.stat_result | None = None, file_hash: str | None = None,
) -> None:
    """Stat-Gedächtnis für Nicht-Katalogisiertes (ADR 0042-Ergänzung).

    Gescheiterte/unbekannte/gesperrte Pfade haben keine file_locations-Zeile —
    ohne dieses Gedächtnis liest jeder Watcher-Neustart sie neu ein, scheitert
    neu und macht quittierte Scan-Probleme wieder auf. Unveränderte Pfade
    (Größe + mtime_ns) überspringt der Watcher künftig ohne Inhalt-Lesen;
    neu probiert wird nur bei Änderung oder per vollem (Re-)Scan.
    Lässt sich die Datei nicht einmal statten, gibt es kein Gedächtnis —
    sie läuft weiter jede Runde (mehr wissen wir über sie nicht).
    """
    try:
        st = stat if stat is not None else path.stat()
    except OSError:
        return
    with conn:
        conn.execute(
            """INSERT INTO scan_memory
                   (path, file_size, mtime_ns, outcome, file_hash, last_seen_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(path) DO UPDATE SET
                   file_size = excluded.file_size, mtime_ns = excluded.mtime_ns,
                   outcome = excluded.outcome, file_hash = excluded.file_hash,
                   last_seen_at = excluded.last_seen_at""",
            (str(path), st.st_size, st.st_mtime_ns, outcome, file_hash, now_iso()),
        )


def _forget_outcome(conn: sqlite3.Connection, path: Path) -> None:
    """Katalogisiert ⇒ file_locations übernimmt das Gedächtnis (ADR 0042)."""
    with conn:
        conn.execute("DELETE FROM scan_memory WHERE path = ?", (str(path),))


def _process_file(
    conn: sqlite3.Connection, path: Path, report: ScanReport,
    rules: dict[str, Any] | None = None,
) -> None:
    # 1) Container erkennen und extrahieren. Unbekanntes/Nicht-Implementiertes
    #    sauseinanderhalten; echte Lesefehler als 'failed' verbuchen.
    pending = False
    try:
        extraction = container.extract(path)
    except UnknownContainerError:
        report.skipped_unknown += 1
        _remember_outcome(conn, path, "unbekannt")
        return
    except ExtractorNotImplementedError as exc:
        # Erkannt, aber Extraktor folgt: trotzdem katalogisieren (leere Schicht 1).
        extraction = ContainerExtraction(container=exc.container)
        pending = True
    except OSError as exc:
        report.failed.append((str(path), f"Lesefehler: {exc}"))
        _record_issue(conn, path, "failed", msg_dump("issueReadError", error=str(exc)))
        _remember_outcome(conn, path, "fehlgeschlagen")
        return

    # Import-Regeln (ADR 0046) — auch beim Katalogisieren: ganze Laufwerke
    # scannen war genau der Weg, über den tausende Mini-Thumbnails und
    # RAW/PSD-Dateien hereinkamen. Kein Katalog-Eintrag, kein Hashen; das
    # Stat-Gedächtnis (ADR 0042) verhindert Neu-Lesen bei jedem Watcher-Lauf.
    # (Lazy-Import wie determine_date unten — scan bleibt ohne harte
    # importer-Abhängigkeit beim Modul-Laden.)
    from .importer import filter_reason

    reason = filter_reason(extraction, rules)
    if reason is not None:
        report.ausgefiltert += 1
        _remember_outcome(conn, path, "ausgefiltert")
        return
    if pending:
        report.pending_extractor += 1

    report.media_files += 1

    # 2) Hash + Größe bilden (eigener Fehlerpfad — Datei kann zwischenzeitlich weg sein).
    try:
        file_hash = hash_file(path)
        stat = path.stat()
        file_size = stat.st_size
    except OSError as exc:
        report.failed.append((str(path), f"Hash/Stat fehlgeschlagen: {exc}"))
        _record_issue(conn, path, "failed", msg_dump("issueHashError", error=str(exc)))
        _remember_outcome(conn, path, "fehlgeschlagen")
        return

    # Sperrliste (ADR 0023): bewusst Gelöschtes wird nicht neu katalogisiert.
    if conn.execute(
        "SELECT 1 FROM blocked_hashes WHERE file_hash = ?", (file_hash,)
    ).fetchone():
        report.blocked += 1
        # Gedächtnis samt Hash: der Watcher hasht Abgelehnte sonst bei jedem
        # Neustart voll neu, ehe die Sperrliste greift (ADR-0042-Lücke);
        # Entsperren räumt die Zeilen über den Hash wieder ab.
        _remember_outcome(conn, path, "gesperrt", stat=stat, file_hash=file_hash)
        return

    # 3) Buchhaltung: neu oder bereits bekannt?
    already = conn.execute(
        "SELECT 1 FROM items WHERE file_hash = ?", (file_hash,)
    ).fetchone()
    if already:
        report.known_items += 1
    else:
        report.new_items += 1

    if extraction.items:
        report.with_metadata += 1
    if extraction.warnings:
        report.files_with_warnings += 1
        for warning in extraction.warnings:
            _record_issue(conn, path, "warning", msg_dump("issueWarning", text=warning))
    else:
        _resolve_issues(conn, path)  # Datei ist jetzt sauber → Altlasten quittieren

    # 4) Schicht 2: strukturierte Felder aus den frisch extrahierten Roh-Einträgen.
    interpretations = interpret_items(extraction.items)
    if interpretations:
        report.interpreted += 1

    # 5) Speichern (idempotent, ADR 0010/0011).
    try:
        store_extraction(
            conn,
            file_hash=file_hash,
            file_size=file_size,
            path=path,
            extraction=extraction,
            mtime_ns=stat.st_mtime_ns,   # Stat-Gedächtnis (ADR 0042)
        )
        store_interpretations(
            conn, file_hash=file_hash, interpretations=interpretations
        )
        # Medien-Erstelldatum (ADR 0021) — dieselbe Kaskade wie beim Import;
        # so füllt „Re-Scan: alle bekannten Fundorte" den Alt-Bestand nach.
        from .importer import determine_date, set_media_date

        when, date_source = determine_date(extraction, stat)
        set_media_date(conn, file_hash, when, date_source)
        conn.commit()
        _forget_outcome(conn, path)   # katalogisiert ⇒ file_locations übernimmt
    except sqlite3.Error as exc:
        report.failed.append((str(path), f"DB-Fehler: {exc}"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m feral.scan",
        description="Scanne einen Ordner rekursiv und nimm alle Medien in die DB auf.",
    )
    parser.add_argument("root", help="Wurzelordner, der rekursiv gescannt wird")
    parser.add_argument(
        "--db",
        default="./feral.sqlite",
        help="Pfad zur SQLite-Datei (Standard: ./feral.sqlite)",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="keine Fortschrittsausgabe"
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"Fehler: '{root}' ist kein Verzeichnis.", file=sys.stderr)
        return 2

    conn = connect(args.db)

    def progress(report: ScanReport, _path: Path) -> None:
        if not args.quiet and report.scanned_files % 500 == 0:
            print(f"  … {report.scanned_files} Dateien", file=sys.stderr)

    # Import-Regeln (ADR 0046) gelten auch im CLI-Scan — gleiche Quelle wie
    # die GUI (./config.toml, falls vorhanden).
    from .config import import_rules, load_config

    rules = import_rules(load_config())

    try:
        report = scan_directory(conn, root, progress=progress, rules=rules)
    finally:
        conn.close()

    print(f"\nScan abgeschlossen für: {root}")
    print(report.summary())
    if report.failed:
        print("\nFehlgeschlagene Dateien (Auszug):")
        for p, err in report.failed[:10]:
            print(f"  - {p}: {err}")
        if len(report.failed) > 10:
            print(f"  … und {len(report.failed) - 10} weitere")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
