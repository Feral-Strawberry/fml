"""Scan-Engine: serialisiert alle Schreibzugriffe über EINEN Worker-Thread.

ADR 0007 verlangt, dass ein einzelner Prozess alle Schreibzugriffe serialisiert.
Hier konkret: genau ein Worker-Thread besitzt die schreibende DB-Verbindung und
arbeitet eine **allgemeine Aufgaben-Warteschlange** ab — Scans, Auto-Watch und
seit Stufe 2A auch Wartungsaufgaben (Neu-Interpretieren, Re-Scan, Integritäts-
check, VACUUM, Aufräumen). Aufrufer **reihen nur Aufgaben ein** — geschrieben
wird ausschließlich im Worker. Kurze Schreibaufgaben können synchron über
`run_write()` laufen (der Aufrufer wartet auf das Ergebnis, geschrieben wird
trotzdem im Worker). Lese-Endpunkte nutzen eigene, kurzlebige Verbindungen
(dank WAL parallel zum einen Schreiber unproblematisch).
"""

from __future__ import annotations

import os
import queue
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from ..db import connect
from ..interpret import reparse_database
from ..messages import msg
from ..scan import ScanReport, _iter_files, scan_files


def _report_dict(r: ScanReport) -> dict[str, int]:
    return {
        "scanned_files": r.scanned_files,
        "media_files": r.media_files,
        "new_items": r.new_items,
        "known_items": r.known_items,
        "with_metadata": r.with_metadata,
        "interpreted": r.interpreted,
        "pending_extractor": r.pending_extractor,
        "skipped_unknown": r.skipped_unknown,
        "ausgefiltert": r.ausgefiltert,
        "files_with_warnings": r.files_with_warnings,
        "failed": len(r.failed),
    }


class Progress(Protocol):
    """Callback, mit dem eine Aufgabe ihren Zustand sichtbar macht."""

    def __call__(self, *, report: dict | None = None, current: str | None = None) -> None: ...


@dataclass
class _Task:
    # Meldungs-Dict (Block M.2, ADR 0054): {"key": ..., "params": ...} —
    # übersetzt wird erst im Frontend (servermsg.js).
    label: dict[str, Any]
    fn: Callable[[sqlite3.Connection, Progress], dict[str, Any]]
    done: threading.Event | None = None          # gesetzt bei synchronen Aufgaben
    result: dict[str, Any] = field(default_factory=dict)


class ScanEngine:
    """Verwaltet den Writer-Thread, die Aufgaben-Warteschlange und den Watcher."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._queue: queue.Queue[_Task | None] = queue.Queue()
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "running": False,
            "label": None,
            "current_file": None,
            "report": _report_dict(ScanReport()),
            "last_finished": None,
            "last_result": None,   # Kurz-Zusammenfassung der letzten Wartungsaufgabe
        }
        # Watch-Quellen-Modell (ADR 0030): N überwachte Ordner, je nach Pfad.
        self._watchers: dict[str, "HotfolderWatcher"] = {}
        self._worker = threading.Thread(
            target=self._run, name="feral-writer", daemon=True
        )
        self._worker.start()

    # -- Worker ------------------------------------------------------------

    def _run(self) -> None:
        conn = connect(self.db_path)
        try:
            while True:
                task = self._queue.get()
                if task is None:  # Sentinel zum Beenden
                    break
                self._execute(conn, task)
        finally:
            conn.close()

    def _execute(self, conn: sqlite3.Connection, task: _Task) -> None:
        with self._lock:
            self._state.update(
                running=True, label=task.label, current_file=None,
                report=_report_dict(ScanReport()),
            )

        def progress(*, report: dict | None = None, current: str | None = None) -> None:
            with self._lock:
                if report is not None:
                    self._state["report"] = report
                self._state["current_file"] = current

        try:
            result = task.fn(conn, progress)
        except Exception as exc:  # Aufgabe kaputt ≠ Worker kaputt
            result = {"summary": msg("sumFailed",
                                     error=f"{exc.__class__.__name__}: {exc}")}

        with self._lock:
            self._state.update(
                running=False, current_file=None, last_finished=task.label,
            )
            if "summary" in result:
                self._state["last_result"] = result["summary"]
        task.result.update(result)
        if task.done is not None:
            task.done.set()

    # -- Einreihen ----------------------------------------------------------

    def _submit(self, label: dict[str, Any],
                fn: Callable[[sqlite3.Connection, Progress], dict]) -> None:
        self._queue.put(_Task(label=label, fn=fn))

    def enqueue_task(
        self, label: dict[str, Any], fn: Callable[[sqlite3.Connection, Progress], dict]
    ) -> None:
        """Reiht eine beliebige **lange** Schreibaufgabe ein (öffentliche Hülle
        um ``_submit`` für Routen ohne eigene enqueue_*-Methode). Das Label
        erscheint in der Status-Anzeige; ein ``summary`` im Ergebnis wird zum
        ``last_result``."""
        self._submit(label, fn)

    def run_write(
        self,
        label: dict[str, Any],
        fn: Callable[[sqlite3.Connection, Progress], dict],
        *,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        """Führe eine **kurze** Schreibaufgabe im Worker aus und warte auf das Ergebnis.

        Für kleine Handgriffe aus HTTP-Handlern (z. B. ein Issue quittieren), die
        trotzdem durch den einen Schreiber müssen (ADR 0007). Lange Aufgaben
        gehören in `_submit`.
        """
        # Läuft gerade ein Langläufer (Import, VACUUM, …), würde der volle
        # Timeout den Aufrufer 15 s hängen lassen, nur um dann doch zu
        # scheitern — lieber kurz abwarten (falls die Aufgabe gerade endet)
        # und sonst sofort ehrlich melden (Block 4S; wird zur 503 mit Label).
        with self._lock:
            busy = self._state["running"]
        if busy:
            timeout = min(timeout, 1.0)
        task = _Task(label=label, fn=fn, done=threading.Event())
        self._queue.put(task)
        if not task.done.wait(timeout):
            raise TimeoutError(
                f"Schreibaufgabe {label.get('key', label)!r} wartet noch (Queue voll?)."
            )
        return task.result

    # -- Scan-Aufgaben -------------------------------------------------------

    @staticmethod
    def _scan_task(files_provider: Callable[[sqlite3.Connection], list[Path]],
                   rules: dict[str, Any] | None = None):
        def fn(conn: sqlite3.Connection, progress: Progress) -> dict[str, Any]:
            files = files_provider(conn)

            def on_file(report: ScanReport, path: Path) -> None:
                progress(report=_report_dict(report), current=path.name)

            report = scan_files(conn, files, progress=on_file, rules=rules)
            progress(report=_report_dict(report), current=None)
            return {}

        return fn

    def enqueue_folder(self, root: str | Path,
                       rules: dict[str, Any] | None = None) -> int:
        """Reiht einen rekursiven Scan eines Ordners ein. Gibt die Dateianzahl
        zurück. ``rules`` — Import-Regeln (ADR 0046) auch fürs Katalogisieren."""
        files = list(_iter_files(Path(root)))
        self._submit(msg("taskScan", root=str(root)),
                     self._scan_task(lambda _conn: files, rules))
        return len(files)

    def enqueue_import(
        self, source_root: str | Path, *, target_root: str | Path, min_date,
        source_mode: str = "einsortieren", remove_empty: bool = False,
        rules: dict[str, Any] | None = None,
    ) -> int:
        """Reiht den Import eines Quellordners ein (ADR 0019). Gibt die Dateizahl
        zurück. ``source_mode`` (ADR 0031): einsortieren | belassen (Quelle
        nie anfassen) | loeschen (Verschiebe-Modus, ADR 0025).
        ``remove_empty`` (ADR 0033): leer gewordene Unterordner mit abräumen."""
        from ..importer import import_folder, iter_import_files

        source = Path(source_root)
        files = iter_import_files(source)

        def fn(conn: sqlite3.Connection, progress: Progress) -> dict[str, Any]:
            def on_file(path: Path, index: int, total: int, rep) -> None:
                # Zähler in die Scan-Report-Felder mappen — die Statusanzeige
                # zeigt damit auch beim Import lebendige Zahlen (54k-Läufe!).
                progress(
                    current=msg("progressFile", index=index, total=total,
                                name=path.name),
                    report={
                        "scanned_files": index - 1,
                        "media_files": rep.importiert + rep.repariert + rep.dublette,
                        "new_items": rep.importiert + rep.repariert,
                        "known_items": rep.dublette,
                        "skipped_unknown": rep.unbekanntes_format,
                        "ausgefiltert": rep.ausgefiltert,
                        "failed": rep.fehler,
                        "with_metadata": 0, "interpreted": 0,
                        "pending_extractor": 0, "files_with_warnings": 0,
                    },
                )

            report = import_folder(
                conn, source, target_root=Path(target_root), min_date=min_date,
                progress=on_file, source_mode=source_mode, remove_empty=remove_empty,
                rules=rules,
            )
            return {"summary": _import_summary(report)}

        self._submit(msg("taskImport", root=str(source)), fn)
        return len(files)

    def enqueue_import_files(
        self, files: list[Path], *, source_root: Path, target_root: Path,
        min_date, source_mode: str = "einsortieren", remove_empty: bool = False,
        rules: dict[str, Any] | None = None,
    ) -> None:
        """Konkrete (zur Ruhe gekommene) Dateien importieren — Hotfolder (ADR 0025).
        ``remove_empty`` (ADR 0033): nach dem Batch leere Unterordner der
        Quelle abräumen (gefahrlos neben dem Watcher: halbe Kopien machen
        ihren Ordner nicht leer)."""
        from ..importer import ImportReport, import_file, remove_empty_dirs

        frozen = list(files)

        def fn(conn: sqlite3.Connection, progress: Progress) -> dict[str, Any]:
            report = ImportReport()
            for index, path in enumerate(frozen, start=1):
                progress(
                    current=msg("progressFile", index=index, total=len(frozen),
                                name=path.name),
                    report={
                        "scanned_files": index - 1,
                        "media_files": report.importiert + report.repariert + report.dublette,
                        "new_items": report.importiert + report.repariert,
                        "known_items": report.dublette,
                        "skipped_unknown": report.unbekanntes_format + report.gesperrt,
                        "ausgefiltert": report.ausgefiltert,
                        "failed": report.fehler, "with_metadata": 0, "interpreted": 0,
                        "pending_extractor": 0, "files_with_warnings": 0,
                    },
                )
                try:
                    action, detail = import_file(
                        conn, path, source_root=source_root, target_root=target_root,
                        min_date=min_date, source_mode=source_mode, rules=rules,
                    )
                except Exception as exc:  # Einzelfehler töten den Batch nicht
                    report.fehler += 1
                    report.probleme.append(f"{path}: {exc}")
                    continue
                setattr(report, action, getattr(report, action) + 1)
            if remove_empty and source_mode != "belassen":
                report.leere_ordner = remove_empty_dirs(source_root)
            return {"summary": _import_summary(report, hotfolder=True)}

        self._submit(msg("taskHotfolderImport", n=len(frozen)), fn)

    def enqueue_moveout(
        self, *, library_root: str | Path, target_root: str | Path, min_date
    ) -> None:
        """Reiht den Pauschalweg des Rausverschiebe-Dialogs ein (I3, ADR 0041):
        alle abgelehnten Dateien unter ``library_root`` in die Datumsstruktur
        unter ``target_root`` verschieben — der einzige Datei-Bewegungsweg
        neben dem Import."""
        from ..moveout import move_out

        def fn(conn: sqlite3.Connection, progress: Progress) -> dict[str, Any]:
            def on_file(path: Path, index: int, total: int, rep) -> None:
                progress(
                    current=msg("progressFile", index=index, total=total,
                                name=path.name),
                    report={
                        "scanned_files": index - 1,
                        "media_files": rep.verschoben,
                        "new_items": rep.verschoben,
                        "known_items": 0,
                        "skipped_unknown": rep.fehlt + rep.veraendert,
                        "failed": rep.fehler,
                        "with_metadata": 0, "interpreted": 0,
                        "pending_extractor": 0, "files_with_warnings": 0,
                    },
                )

            report = move_out(
                conn, library_root=library_root, target_root=target_root,
                min_date=min_date, progress=on_file,
            )
            return {"summary": _moveout_summary(report)}

        self._submit(msg("taskMoveout"), fn)

    def enqueue_thumb_warm(
        self, cache_dir: str | Path, size: int, pool=None, *, retry_failed: bool = False,
    ) -> None:
        """Reiht „Thumbnails erstellen" ein (ADR 0013-Nachrüstung).

        Läuft nach großen Importen automatisch mit — sonst erzeugt der erste
        Grid-Besuch zehntausende Thumbnails on-demand und würgt die
        Oberfläche ab. Die Automatik erzeugt NUR Fehlende; erst
        ``retry_failed=True`` (Admin-Knopf) versucht Fehlgeschlagene erneut
        (z. B. nach ffmpeg-Installation) und schreibt dauerhafte Fehler als
        Scan-Probleme (ADR-0042-Ergänzung: die Automatik machte sonst bei
        jedem Schub alle quittierten thumbnail-Probleme wieder auf).
        Mit ``pool`` (ThumbPool, ADR 0020) generieren die Prozesse parallel —
        DB-Schreiben bleibt trotzdem hier im Writer-Thread.
        """
        from ..thumbs import warm_thumbnails

        def fn(conn: sqlite3.Connection, progress: Progress) -> dict[str, Any]:
            def on_progress(index, total, created, skipped, failed):
                progress(
                    current=msg("progressThumb", index=index, total=total),
                    report={
                        "scanned_files": index, "media_files": total,
                        "new_items": created, "known_items": skipped,
                        "failed": failed, "skipped_unknown": 0,
                        "with_metadata": 0, "interpreted": 0,
                        "pending_extractor": 0, "files_with_warnings": 0,
                    },
                )

            result = warm_thumbnails(conn, cache_dir, size=size, progress=on_progress,
                                     pool=pool, retry_failed=retry_failed)
            parts = [msg("sumThumbsNew", n=result["created"]),
                     msg("sumThumbsSkipped", n=result["skipped"])]
            if result["failed"]:
                parts.append(msg("sumThumbsFailedIssues" if retry_failed
                                 else "sumThumbsFailed", n=result["failed"]))
            return {"summary": msg("sumThumbs", parts=parts)}

        self._submit(msg("taskThumbWarm"), fn)

    def enqueue_media_date_backfill(self) -> None:
        """Erstelldaten für den Alt-Bestand nachtragen (ADR 0021) — läuft beim
        App-Start automatisch, wenn Items ohne ``media_date`` existieren."""
        from ..importer import backfill_media_dates

        def fn(conn: sqlite3.Connection, progress: Progress) -> dict[str, Any]:
            def on_progress(index: int, total: int, dated: int) -> None:
                progress(
                    current=msg("progressBackfill", index=index, total=total),
                    report={
                        "scanned_files": index, "media_files": total,
                        "new_items": dated, "known_items": 0, "failed": 0,
                        "skipped_unknown": 0, "with_metadata": 0,
                        "interpreted": 0, "pending_extractor": 0,
                        "files_with_warnings": 0,
                    },
                )

            result = backfill_media_dates(conn, progress=on_progress)
            return {"summary": msg("sumBackfill", dated=result["dated"],
                                   total=result["total"])}

        self._submit(msg("taskBackfillDates"), fn)

    def enqueue_search_reindex(self) -> None:
        """FTS5-Suchindex komplett neu aufbauen (ADR 0024) — läuft beim
        App-Start automatisch, wenn Item- und Index-Zahl auseinanderliegen
        (Alt-Bestand vor Migration 0013, Drift nach Aufräum-Aktionen)."""
        from ..db.store import update_search_index

        def fn(conn: sqlite3.Connection, progress: Progress) -> dict[str, Any]:
            conn.execute("DELETE FROM search_index")
            conn.execute("DELETE FROM search_index_map")
            hashes = [r[0] for r in conn.execute("SELECT file_hash FROM items")]
            total = len(hashes)
            for index, file_hash in enumerate(hashes, start=1):
                update_search_index(conn, file_hash)
                if index % 500 == 0 or index == total:
                    conn.commit()
                    progress(
                        current=msg("progressReindex", index=index, total=total),
                        report={
                            "scanned_files": index, "media_files": total,
                            "new_items": index, "known_items": 0, "failed": 0,
                            "skipped_unknown": 0, "with_metadata": 0,
                            "interpreted": 0, "pending_extractor": 0,
                            "files_with_warnings": 0,
                        },
                    )
            conn.commit()
            return {"summary": msg("sumReindex", n=total)}

        self._submit(msg("taskReindex"), fn)

    def enqueue_files(self, files: list[Path], label: dict[str, Any],
                      rules: dict[str, Any] | None = None) -> None:
        """Reiht das Scannen konkreter Dateien ein (katalogisieren-Watchordner,
        ADR 0031: am Ort aufnehmen — weder kopieren noch bewegen)."""
        frozen = list(files)
        self._submit(label, self._scan_task(lambda _conn: frozen, rules))

    # -- Wartungsaufgaben (Stufe 2A, ADR 0014) --------------------------------

    def enqueue_reparse(self) -> None:
        """Schicht 2 rückwirkend über den ganzen Bestand (ohne Datei-Zugriff)."""

        def fn(conn: sqlite3.Connection, _progress: Progress) -> dict[str, Any]:
            report = reparse_database(conn)
            return {"summary": msg("sumReparse",
                                   interpreted=report.items_interpreted,
                                   total=report.items_total,
                                   fields=report.fields_written)}

        self._submit(msg("taskReparse"), fn)

    def enqueue_rescan(self) -> None:
        """Alle bekannten, noch existierenden Fundorte erneut scannen."""

        def files_provider(conn: sqlite3.Connection) -> list[Path]:
            return [
                Path(p)
                for (p,) in conn.execute("SELECT DISTINCT path FROM file_locations")
                if Path(p).is_file()
            ]

        self._submit(msg("taskRescan"), self._scan_task(files_provider))

    def enqueue_integrity_check(self) -> None:
        def fn(conn: sqlite3.Connection, _progress: Progress) -> dict[str, Any]:
            verdict = conn.execute("PRAGMA integrity_check").fetchone()[0]
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            ok = verdict == "ok"
            return {"summary": msg("sumIntegrityOk") if ok
                    else msg("sumIntegrityProblem", verdict=verdict)}

        self._submit(msg("taskIntegrity"), fn)

    def enqueue_vacuum(self) -> None:
        def fn(conn: sqlite3.Connection, _progress: Progress) -> dict[str, Any]:
            before = Path(self.db_path).stat().st_size if Path(self.db_path).is_file() else 0
            conn.execute("VACUUM")
            # VACUUM schreibt die DB durchs WAL neu — ohne Checkpoint bleibt
            # eine WAL-Datei in DB-Größe liegen und die Kennzahl „DB (+WAL)"
            # zeigt scheinbar das Doppelte (Feral Strawberrys 1,1→2,21-GB-Befund).
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            after = Path(self.db_path).stat().st_size if Path(self.db_path).is_file() else 0
            return {"summary": msg("sumVacuum", before=f"{before/1e6:.1f}",
                                   after=f"{after/1e6:.1f}")}

        self._submit(msg("taskVacuum"), fn)

    # -- Öffentliche API ------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._lock:
            st = dict(self._state)
        st["queue_pending"] = self._queue.qsize()
        st["watchers"] = [w.status() for w in self._watchers.values()]
        return st

    # -- Watch-Quellen (ADR 0030) --------------------------------------------
    # Mehrere überwachte Quellordner, jeder mit eigenem Modus (kopieren/
    # verschieben). Alle speisen dieselbe Import-Pipeline (ADR 0019) über den
    # `on_ready`-Callback, der die reifen Dateien einreiht. Schlüssel ist der
    # aufgelöste Pfad — derselbe Ordner läuft nie doppelt.

    @staticmethod
    def watch_key(path: str | Path) -> str:
        return str(Path(path).resolve())

    def _load_stat_memory(self, root: str | Path) -> dict[str, tuple[int, int]]:
        """Stat-Gedächtnis der Wurzel (ADR 0042): Pfad → (Größe, mtime_ns) aller
        katalogisierten Fundorte unterhalb von ``root`` — EINE Query beim
        Watcher-Start. Damit überspringt der Watcher unveränderte Pfade, ohne
        ein Byte Inhalt zu lesen; Neustarts lesen den Bestand nicht mehr voll.
        Alt-Zeilen ohne mtime_ns (vor Migration 0018) fehlen bewusst — sie
        laufen einmal den vollen Weg (Backfill).

        Dazu ``scan_memory`` (Migration 0019): das Gedächtnis der NICHT
        katalogisierten Pfade (gescheitert/unbekannt/gesperrt) — sonst liest
        jeder Neustart genau diese Dateien neu ein, scheitert neu und macht
        quittierte Scan-Probleme wieder auf."""
        prefix = str(Path(root)) + os.sep
        escaped = (prefix.replace("\\", "\\\\")
                   .replace("%", "\\%").replace("_", "\\_"))
        conn = connect(self.db_path)
        try:
            rows = conn.execute(
                """SELECT path, file_size, mtime_ns FROM file_locations
                    WHERE mtime_ns IS NOT NULL AND path LIKE ? ESCAPE '\\'
                    ORDER BY last_seen_at""",
                (escaped + "%",),
            ).fetchall()
            skipped = conn.execute(
                """SELECT path, file_size, mtime_ns FROM scan_memory
                    WHERE path LIKE ? ESCAPE '\\' ORDER BY last_seen_at""",
                (escaped + "%",),
            ).fetchall()
        finally:
            conn.close()
        # Bei doppelten Pfaden (Datei geändert ⇒ neuer Hash, alte Zeile bleibt
        # bis zum Aufräumen) gewinnt die zuletzt gesehene Zeile; scan_memory
        # überstimmt file_locations (es ist das jüngere Wissen — beim
        # Katalogisieren wird es gelöscht, Restfälle sind Ausnahmen).
        memory = {path: (size, mt) for path, size, mt in rows}
        memory.update({path: (size, mt) for path, size, mt in skipped})
        return memory

    def start_watch_source(self, source: dict[str, Any], on_ready) -> None:
        """Überwache einen Quellordner (normalisierter Eintrag aus
        `config.watch_sources`). Ein bereits laufender Watcher desselben Pfads
        wird zuvor gestoppt (idempotent)."""
        key = self.watch_key(source["path"])
        self.stop_watch_source(source["path"])
        watcher = HotfolderWatcher(
            Path(source["path"]), on_ready,
            name=str(source.get("name") or Path(source["path"]).name),
            modus=str(source.get("modus", "kopieren")),
            quiet_seconds=float(source.get("quiet_seconds", 5.0)),
            poll_seconds=float(source.get("poll_seconds", 1.0)),
            known_stats=self._load_stat_memory(source["path"]),
        )
        self._watchers[key] = watcher
        watcher.start()

    def stop_watch_source(self, path: str | Path) -> bool:
        """Stoppe den Watcher eines Pfads. True, wenn einer lief."""
        key = self.watch_key(path)
        watcher = self._watchers.pop(key, None)
        if watcher is not None:
            watcher.stop()
            return True
        return False

    def stop_all_watches(self) -> None:
        for watcher in list(self._watchers.values()):
            watcher.stop()
        self._watchers.clear()

    def is_watching(self, path: str | Path) -> bool:
        return self.watch_key(path) in self._watchers

    def shutdown(self) -> None:
        """Beendet alle Watcher und den Worker sauber (für Tests/Neustart)."""
        self.stop_all_watches()
        self._queue.put(None)
        self._worker.join(timeout=5)


def _import_summary(report, *, hotfolder: bool = False) -> dict[str, Any]:
    """ImportReport → Meldungs-Dict (Gegenstück zu ``ImportReport.summary()``,
    das fürs CLI deutsch bleibt): nur belegte Zähler als ``parts``-Liste —
    der Frontend-Renderer joint sie mit « · » (Block M.2, ADR 0054)."""
    parts = [msg("sumImportNew", n=report.importiert)]
    if report.repariert:
        parts.append(msg("sumImportRepaired", n=report.repariert))
    parts.append(msg("sumImportDupes", n=report.dublette))
    if report.unbekanntes_format:
        parts.append(msg("sumImportUnknown", n=report.unbekanntes_format))
    if report.ausgefiltert:
        parts.append(msg("sumImportFiltered", n=report.ausgefiltert))
    if report.gesperrt:
        parts.append(msg("sumImportBlocked", n=report.gesperrt))
    if report.fehler:
        parts.append(msg("sumImportErrors", n=report.fehler))
    if report.leere_ordner:
        parts.append(msg("sumImportEmptyDirs", n=report.leere_ordner))
    return msg("sumHotfolderImport" if hotfolder else "sumImport", parts=parts)


def _moveout_summary(report) -> dict[str, Any]:
    """MoveoutReport → Meldungs-Dict (wie ``_import_summary``)."""
    parts = [msg("sumMoveMoved", n=report.verschoben)]
    if report.fehlt:
        parts.append(msg("sumMoveMissing", n=report.fehlt))
    if report.veraendert:
        parts.append(msg("sumMoveChanged", n=report.veraendert))
    if report.fehler:
        parts.append(msg("sumMoveErrors", n=report.fehler))
    return msg("sumMoveout", parts=parts)


class HotfolderWatcher(threading.Thread):
    """Hotfolder mit Ruhe-Erkennung (Block 4.2, ADR 0025, stdlib-Polling).

    Eine Datei gilt als fertig, wenn (Größe, mtime) über ``quiet_seconds``
    stabil bleibt — halbe Kopien werden nie importiert. Reife Dateien gehen
    als Batch an ``on_ready`` (die App reiht damit den Import-Kern ein);
    solange eine Datei im Ordner liegt (bis der Writer sie wegbewegt/löscht),
    hält ``_inflight`` Doppel-Einreihungen fern.

    ``known_stats`` (ADR 0042): Stat-Gedächtnis aus der DB (Pfad → (Größe,
    mtime_ns)). Pfade mit unverändertem Stat gelten als katalogisiert und
    werden übersprungen, ohne Inhalt zu lesen — sonst liest jeder
    Serverneustart den gesamten überwachten Bestand neu.
    """

    def __init__(
        self, root: Path, on_ready, *,
        name: str | None = None, modus: str = "kopieren",
        quiet_seconds: float = 5.0, poll_seconds: float = 1.0,
        clock=time.monotonic,
        known_stats: dict[str, tuple[int, int]] | None = None,
    ) -> None:
        super().__init__(name="feral-hotfolder", daemon=True)
        self.root = Path(root)
        self.on_ready = on_ready
        self.watch_name = name or self.root.name or str(self.root)
        self.modus = modus
        self.quiet_seconds = quiet_seconds
        self.poll_seconds = poll_seconds
        self._clock = clock
        self._stop = threading.Event()
        self._seen: dict[str, tuple[tuple[float, int], float]] = {}  # pfad -> (sig, seit)
        self._inflight: set[str] = set()
        self._enqueued_total = 0
        self._known = known_stats or {}

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict[str, Any]:
        return {
            "name": self.watch_name,
            "root": str(self.root),
            "modus": self.modus,
            "exists": self.root.is_dir(),
            "pending": len(self._seen) - len(self._inflight),
            "enqueued_total": self._enqueued_total,
        }

    def poll_once(self, now: float | None = None) -> list[Path]:
        """Ein Durchlauf: reife Dateien ermitteln und melden (testbar)."""
        from ..importer import iter_import_files

        now = self._clock() if now is None else now
        ready: list[Path] = []
        current: set[str] = set()
        for path in iter_import_files(self.root):
            key = str(path)
            current.add(key)
            if key in self._inflight:
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            # Stat-Gedächtnis (ADR 0042): unverändert katalogisierte Pfade
            # überspringen, ohne Inhalt zu lesen — nichts wird eingereiht,
            # der Writer bleibt nach einem Neustart sofort frei.
            if self._known.get(key) == (st.st_size, st.st_mtime_ns):
                self._seen.pop(key, None)
                continue
            sig = (st.st_mtime, st.st_size)
            known = self._seen.get(key)
            if known is None or known[0] != sig:
                self._seen[key] = (sig, now)      # (wieder) in Bewegung
                continue
            if now - known[1] >= self.quiet_seconds:
                ready.append(path)
                self._inflight.add(key)
        # Verschwundene Dateien (importiert/gelöscht/weggeräumt) vergessen.
        for key in list(self._seen):
            if key not in current:
                self._seen.pop(key, None)
                self._inflight.discard(key)
        if ready:
            self._enqueued_total += len(ready)
            self.on_ready(ready)
        return ready

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:  # Polling darf nie sterben
                pass
            self._stop.wait(self.poll_seconds)
