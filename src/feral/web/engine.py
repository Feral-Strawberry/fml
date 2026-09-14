"""Engine: Warteschlange im Web-Prozess, Langläufer im Worker-Prozess (ADR 0067).

Bis ADR 0067 lief hier ein Writer-Thread im Web-Prozess — ein rechnender
Langläufer bremste über den GIL jede HTTP-Antwort (#65). Jetzt:

- **Warteschlange und Status** leben hier im Web-Prozess. ``enqueue(name,
  params, label)`` reiht eine benannte Aufgabe (``tasks.py``) ein; gleiche
  Aufgabe (Name + Parameter) läuft oder wartet schon → ``AlreadyQueued``
  (HTTP 409). Dem **Worker-Prozess** (``worker.py``) geht **eine Aufgabe auf
  einmal** über eine Pipe zu; seine Ereignisse (Start/Fortschritt/Ende)
  liest ein Thread und hält den Snapshot für ``/api/status``.
- **Aufsicht:** stirbt der Worker, wird die laufende Aufgabe als
  fehlgeschlagen gemeldet und der Worker beim nächsten Auftrag neu gestartet;
  wartende Aufgaben bleiben erhalten. Der Worker startet lazy beim ersten
  Auftrag (Tests ohne Aufgaben zahlen keinen Prozess-Start).
- **Kurze Schreibgriffe** (``run_write``) schreibt der Web-Prozess selbst über
  eine eigene Verbindung hinter einem Lock — „ein Schreiber je Aufgabenart"
  (ADR 0007, Nachtrag); SQLite serialisiert die beiden Prozesse über WAL +
  ``busy_timeout``.
- Ordner-Wächter (``HotfolderWatcher``) bleiben Threads hier: sie lesen nur
  und reihen reife Dateien als Aufgabe ein.
"""

from __future__ import annotations

import atexit
import json
import logging
import multiprocessing as mp
import os
import queue
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..db import connect
from ..messages import msg
from ..scan import ScanReport, _iter_files
from .tasks import Progress, report_dict  # noqa: F401 — Progress bleibt exportiert
from .worker import run_worker

log = logging.getLogger("feral.engine")

WRITE_BUSY_TIMEOUT_MS = 3000       # kurze Schreibgriffe warten höchstens so lange auf den Worker
RESTART_WINDOW = 60.0              # Sekunden: mehr als RESTART_LIMIT Tode darin → kein Auto-Neustart
RESTART_LIMIT = 3


class AlreadyQueued(Exception):
    """Gleiche Aufgabe läuft oder wartet schon (ADR 0067, Mehrfachklick)."""

    def __init__(self, label: dict[str, Any], *, running: bool) -> None:
        super().__init__(f"Aufgabe {label.get('key', label)!r} "
                         f"{'läuft' if running else 'wartet'} bereits")
        self.label = label
        self.running = running


@dataclass
class _Queued:
    id: int
    name: str
    params: dict[str, Any]
    label: dict[str, Any]
    key: str


def _dedupe_key(name: str, params: dict[str, Any]) -> str:
    return name + ":" + json.dumps(params, sort_keys=True, default=str)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ScanEngine:
    """Warteschlange + Worker-Aufsicht + kurze Schreibgriffe + Watcher."""

    def __init__(self, db_path: str | Path, *, log_dir: str | Path | None = None,
                 pool_workers: int | None = None, thumb_workers: int | None = None,
                 thumb_low_priority: bool = True) -> None:
        self.db_path = str(db_path)
        self.log_dir = str(log_dir) if log_dir is not None else None
        self.pool_workers = pool_workers
        self.thumb_workers = thumb_workers
        self.thumb_low_priority = thumb_low_priority
        self._ctx = mp.get_context("spawn")
        self._lock = threading.RLock()
        self._pending: deque[_Queued] = deque()
        self._running: _Queued | None = None
        self._next_id = 1
        self._proc = None
        self._task_q = None          # mp.Queue: put() blockiert nie (Feeder-Thread)
        self._status_q = None
        self._reader: threading.Thread | None = None
        self._worker_died = False
        self._deaths: deque[float] = deque()
        self._closed = False
        self._started_at: float | None = None
        self._state: dict[str, Any] = {
            "running": False,
            "label": None,
            "current_file": None,
            "report": report_dict(ScanReport()),
            "last_finished": None,
            "last_result": None,   # Kurz-Zusammenfassung der letzten Aufgabe
            "started_at": None,
            # Laufende Nummer fertiger Aufgaben: das Frontend erkennt daran
            # „etwas ist fertig geworden" — ein Vergleich der Label-Dicts
            # (Objektidentität) meldete seit M.2 bei JEDEM Poll eine Änderung
            # und ließ das Dashboard alle 700 ms /api/admin/info & Co. neu
            # laden (Feral Strawberrys „träge nach dem Lauf", 2026-09-07).
            "finished_seq": 0,
            # Verlauf (ADR 0074 Nachtrag): die letzten erledigten Aufgaben,
            # jüngste zuerst — Label, Dauer, Ergebnis, ok/fehlgeschlagen.
            # Nur im Speicher; ein Neustart beginnt leer (das Log hat alles).
            "history": [],
        }
        # Watch-Quellen-Modell (ADR 0030): N überwachte Ordner, je nach Pfad.
        self._watchers: dict[str, "HotfolderWatcher"] = {}
        # Haken nach jeder erledigten Aufgabe (#118, ADR 0077): ``fn(name, ok)``
        # mit dem Aufgabennamen aus ``tasks.TASKS``; läuft im Leser-Thread
        # AUSSERHALB der Sperre — kurz halten (z. B. Hintergrund-Zählung
        # anstoßen), nie blockieren.
        self.on_finished: list[Callable[[str, bool], None]] = []
        # Kurze Schreibgriffe: eigene Verbindung, ein Lock (ADR 0007, Nachtrag).
        self._write_conn: sqlite3.Connection | None = None
        self._write_lock = threading.Lock()
        # Der Worker ist kein Daemon (er hat selbst Kindprozesse) — beim
        # Interpreter-Ende würde multiprocessing auf ihn warten. Deshalb
        # räumt ein atexit-Haken auf, falls niemand shutdown() rief.
        atexit.register(self.shutdown)
        # Dispatcher-Thread: startet den Worker und stellt Aufgaben zu — NIE
        # unter self._lock. Ein Worker-Start dauert unter Windows (spawn +
        # Importe + Defender) 10–30 s; hielte enqueue() derweil die Sperre,
        # stünde /api/status (700-ms-Poll) und mit ihm der Request-Threadpool,
        # aus dem auch FileResponse die Bilder liest (Feral Strawberrys
        # 30-s-Hänger beim Blättern, 2026-09-07).
        self._wake = threading.Event()
        self._dispatcher = threading.Thread(
            target=self._dispatch_loop, name="feral-dispatch", daemon=True,
        )
        self._dispatcher.start()

    # -- Worker-Prozess --------------------------------------------------------

    def _start_worker(self) -> None:
        """Worker-Prozess starten — läuft im Dispatcher-Thread, ohne Sperre."""
        task_q = self._ctx.Queue()
        status_q = self._ctx.Queue()
        proc = self._ctx.Process(
            target=run_worker, args=(self.db_path, task_q, status_q),
            kwargs={"log_dir": self.log_dir, "pool_workers": self.pool_workers,
                    "thumb_workers": self.thumb_workers,
                    "thumb_low_priority": self.thumb_low_priority},
            name="feral-worker",
        )
        proc.start()
        reader = threading.Thread(
            target=self._read_status, args=(proc, status_q), name="feral-status", daemon=True,
        )
        with self._lock:
            self._proc, self._task_q, self._status_q, self._reader = proc, task_q, status_q, reader
            self._worker_died = False
        reader.start()
        log.info("Worker process started (pid %s)", proc.pid)

    def _may_restart_locked(self) -> bool:
        """Serien-Bremse: stirbt der Worker laufend, nicht endlos neu starten."""
        now = time.monotonic()
        while self._deaths and now - self._deaths[0] > RESTART_WINDOW:
            self._deaths.popleft()
        if len(self._deaths) > RESTART_LIMIT:
            log.error("Worker died %d times within %.0f s - no automatic restart; "
                      "the next task will try again.", len(self._deaths), RESTART_WINDOW)
            self._deaths.clear()
            return False
        return True

    def _dispatch_loop(self) -> None:
        """Dispatcher: wartet auf den Wecker, startet bei Bedarf den Worker und
        stellt die nächste Aufgabe zu. Blockierende Schritte (Prozess-Start,
        Queue-Put) passieren hier, außerhalb von self._lock."""
        while True:
            self._wake.wait(timeout=1.0)
            self._wake.clear()
            if self._closed:
                return
            with self._lock:
                if self._running is not None or not self._pending:
                    continue
                need_worker = self._proc is None or not self._proc.is_alive()
                if need_worker and not self._may_restart_locked():
                    continue
            if need_worker:
                try:
                    self._start_worker()
                except Exception as exc:  # pragma: no cover — Startfehler sichtbar machen
                    log.error("Worker process failed to start: %s", exc)
                    time.sleep(1.0)
                    continue
            with self._lock:
                if self._running is not None or not self._pending or self._task_q is None:
                    continue
                item = self._pending.popleft()
                self._running = item
                task_q = self._task_q
                message = {"op": "run", "id": item.id, "name": item.name,
                           "params": item.params, "label": item.label,
                           "queue_pending": len(self._pending)}
            try:
                task_q.put(message)
            except (OSError, ValueError) as exc:
                log.error("Task %s could not be delivered (%s) - worker dead?", item.name, exc)
                with self._lock:
                    self._pending.appendleft(item)
                    self._running = None
                    self._handle_death_locked(self._proc)

    def _read_status(self, proc, status_q) -> None:
        """Leser-Thread: Ereignisse des Workers → Snapshot; Tod erkennen."""
        while True:
            try:
                event = status_q.get(timeout=0.5)
            except queue.Empty:
                if not proc.is_alive():
                    # Nachzügler aus der Queue holen, dann den Tod verbuchen.
                    while True:
                        try:
                            self._handle_event(status_q.get(timeout=0.2))
                        except queue.Empty:
                            break
                    with self._lock:
                        self._handle_death_locked(proc)
                    return
                continue
            except (EOFError, OSError):
                with self._lock:
                    self._handle_death_locked(proc)
                return
            if not isinstance(event, dict):
                continue
            if event.get("ev") == "bye":
                return
            self._handle_event(event)

    def _handle_event(self, event: dict[str, Any]) -> None:
        finished: tuple[str, bool] | None = None
        with self._lock:
            running = self._running
            if running is None or event.get("id") != running.id:
                return
            kind = event.get("ev")
            if kind == "started":
                self._started_at = float(event.get("at") or time.time())
                self._state.update(
                    running=True, label=running.label, current_file=None,
                    report=report_dict(ScanReport()), started_at=_iso(self._started_at),
                )
            elif kind == "progress":
                if event.get("report") is not None:
                    self._state["report"] = event["report"]
                self._state["current_file"] = event.get("current")
            elif kind == "finished":
                result = event.get("result") or {}
                if event.get("report") is not None:
                    self._state["report"] = event["report"]
                self._state.update(running=False, current_file=None,
                                   last_finished=running.label, started_at=None,
                                   finished_seq=self._state["finished_seq"] + 1)
                if isinstance(result, dict) and "summary" in result:
                    self._state["last_result"] = result["summary"]
                # Fehlgeschlagen ist NUR eine Aufgabe, die mit sumFailed
                # endete (Ausnahme im Worker); ein Scan-Report mit
                # failed-Zähler ist ein erfolgreicher Lauf mit Befunden.
                summary = self._state["last_result"]
                ok = not (isinstance(summary, dict) and summary.get("key") == "sumFailed")
                self._remember_locked(running.label, summary, ok=ok)
                finished = (running.name, ok)
                self._running = None
                self._started_at = None
                self._wake.set()
        if finished is not None:
            for hook in list(self.on_finished):
                try:
                    hook(*finished)
                except Exception:
                    log.exception("on_finished hook %r failed", hook)

    HISTORY_MAX = 12

    def _remember_locked(self, label: dict[str, Any], result: Any, *, ok: bool) -> None:
        """Erledigte Aufgabe in den Verlauf (unter self._lock aufrufen)."""
        now = time.time()
        elapsed = (round(now - self._started_at, 1) if self._started_at is not None else None)
        entry = {"label": label, "result": result, "ok": ok,
                 "elapsed": elapsed, "finished_at": _iso(now)}
        self._state["history"] = [entry, *self._state["history"]][: self.HISTORY_MAX]

    def _handle_death_locked(self, proc) -> None:
        if proc is not self._proc or self._closed:
            return
        self._worker_died = True
        self._deaths.append(time.monotonic())
        code = getattr(proc, "exitcode", None)
        running, self._running = self._running, None
        self._started_at = None
        if running is not None:
            log.error("Worker process died (exitcode %s) during %s", code, running.name)
            self._state.update(
                running=False, current_file=None, last_finished=running.label,
                last_result=msg("sumWorkerDied", code=code if code is not None else "?"),
                started_at=None, finished_seq=self._state["finished_seq"] + 1,
            )
            self._remember_locked(running.label, self._state["last_result"], ok=False)
        else:
            log.error("Worker process died (exitcode %s)", code)
        try:
            self._task_q.close()
        except Exception:
            pass
        self._proc = self._task_q = self._status_q = None
        if self._pending:
            self._wake.set()   # Dispatcher startet den Worker neu (mit Serien-Bremse)

    # -- Einreihen ----------------------------------------------------------------

    def enqueue(self, name: str, params: dict[str, Any] | None = None,
                label: dict[str, Any] | None = None, *, key: str | None = None,
                dedupe: str = "all") -> int:
        """Eine benannte Aufgabe (``tasks.TASKS``) einreihen; liefert ihre ID.

        ``key`` (Standard: Name + Parameter) entscheidet über Dubletten:
        ``dedupe="all"`` weist ab, wenn die Aufgabe läuft ODER wartet
        (Mehrfachklick, ADR 0067); ``"pending"`` nur, wenn sie wartet — für
        Automatik-Nachläufer (Thumbnail-Vorwärmen nach Import), die nach
        einem laufenden Lauf noch einmal drankommen sollen."""
        params = dict(params or {})
        label = label or msg("taskGeneric")
        key = key or _dedupe_key(name, params)
        with self._lock:
            if self._closed:
                raise RuntimeError("Engine ist beendet")
            if dedupe == "all" and self._running is not None and self._running.key == key:
                raise AlreadyQueued(self._running.label, running=True)
            for queued in self._pending:
                if queued.key == key:
                    raise AlreadyQueued(queued.label, running=False)
            item = _Queued(id=self._next_id, name=name, params=params, label=label, key=key)
            self._next_id += 1
            self._pending.append(item)
            log.info("Queued: %s [%s] (waiting: %d)", label.get("key", label), name,
                     len(self._pending))
        self._wake.set()
        return item.id

    def run_write(
        self,
        label: dict[str, Any],
        fn: Callable[[sqlite3.Connection, Progress], dict],
        *,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        """Kurzen Schreibgriff **hier im Web-Prozess** ausführen (ADR 0007,
        Nachtrag): eigene Verbindung, ein Lock. Wartet höchstens ``timeout``
        auf einen anderen kurzen Schreibgriff und ``WRITE_BUSY_TIMEOUT_MS``
        auf eine Transaktion des Workers — sonst ``TimeoutError`` (→ 503).
        Fehler in ``fn`` kommen wie bisher als ``{"summary": sumFailed}``
        zurück, nicht als Exception."""
        if not self._write_lock.acquire(timeout=timeout):
            raise TimeoutError(f"Schreibaufgabe {label.get('key', label)!r} wartet noch.")
        try:
            conn = self._write_conn
            if conn is None:
                # EINE Verbindung für alle kurzen Schreibgriffe — FastAPI ruft
                # synchrone Routen aus wechselnden Pool-Threads auf. sqlite3
                # bindet Verbindungen standardmäßig an den erzeugenden Thread
                # (»SQLite objects created in a thread can only be used in
                # that same thread«, Issue #72: Duelle/Bewertungen gingen
                # intermittierend verloren). Das Teilen ist erlaubt, weil
                # JEDER Zugriff unter _write_lock läuft (siehe oben).
                conn = self._write_conn = connect(self.db_path, check_same_thread=False)
                conn.execute(f"PRAGMA busy_timeout={WRITE_BUSY_TIMEOUT_MS}")
            try:
                result = fn(conn, _noop_progress)
                if conn.in_transaction:
                    conn.commit()
                return result if isinstance(result, dict) else {}
            except sqlite3.OperationalError as exc:
                _rollback(conn)
                if "locked" in str(exc) or "busy" in str(exc):
                    log.warning("Write %s: database busy (%s)", label.get("key"), exc)
                    raise TimeoutError(str(exc)) from exc
                log.error("Write %s failed: %s", label.get("key"), exc)
                return {"summary": msg("sumFailed", error=f"{exc.__class__.__name__}: {exc}")}
            except Exception as exc:
                _rollback(conn)
                log.error("Write %s failed: %s", label.get("key"), exc)
                return {"summary": msg("sumFailed", error=f"{exc.__class__.__name__}: {exc}")}
        finally:
            self._write_lock.release()

    # -- Scan-Aufgaben (Hüllen um enqueue — die Routen bleiben unverändert) -------

    def enqueue_folder(self, root: str | Path,
                       rules: dict[str, Any] | None = None) -> int:
        """Reiht einen rekursiven Scan eines Ordners ein. Gibt die Dateianzahl
        zurück. ``rules`` — Import-Regeln (ADR 0046) auch fürs Katalogisieren."""
        files = [str(p) for p in _iter_files(Path(root))]
        self.enqueue("scan_files", {"files": files, "rules": rules},
                     msg("taskScan", root=str(root)), key=f"scan_folder:{root}")
        return len(files)

    def enqueue_files(self, files: list[Path], label: dict[str, Any],
                      rules: dict[str, Any] | None = None) -> None:
        """Reiht das Scannen konkreter Dateien ein (katalogisieren-Watchordner,
        ADR 0031: am Ort aufnehmen — weder kopieren noch bewegen)."""
        self.enqueue("scan_files", {"files": [str(p) for p in files], "rules": rules}, label)

    def enqueue_import(
        self, source_root: str | Path, *, target_root: str | Path, min_date,
        source_mode: str = "einsortieren", remove_empty: bool = False,
        rules: dict[str, Any] | None = None,
    ) -> int:
        """Reiht den Import eines Quellordners ein (ADR 0019). Gibt die Dateizahl
        zurück. ``source_mode`` (ADR 0031): einsortieren | belassen | loeschen;
        ``remove_empty`` (ADR 0033): leer gewordene Unterordner mit abräumen."""
        from ..importer import iter_import_files

        files = iter_import_files(Path(source_root))
        self.enqueue(
            "import_folder",
            {"source_root": str(source_root), "target_root": str(target_root),
             "min_date": min_date, "source_mode": source_mode,
             "remove_empty": remove_empty, "rules": rules},
            msg("taskImport", root=str(source_root)), key=f"import_folder:{source_root}",
        )
        return len(files)

    def enqueue_import_files(
        self, files: list[Path], *, source_root: Path, target_root: Path,
        min_date, source_mode: str = "einsortieren", remove_empty: bool = False,
        rules: dict[str, Any] | None = None,
    ) -> None:
        """Konkrete (zur Ruhe gekommene) Dateien importieren — Hotfolder (ADR 0025)."""
        frozen = [str(p) for p in files]
        self.enqueue(
            "import_files",
            {"files": frozen, "source_root": str(source_root), "target_root": str(target_root),
             "min_date": min_date, "source_mode": source_mode,
             "remove_empty": remove_empty, "rules": rules},
            msg("taskHotfolderImport", n=len(frozen)),
        )

    def enqueue_moveout(
        self, *, library_root: str | Path, target_root: str | Path, min_date
    ) -> None:
        """Pauschalweg des Rausverschiebe-Dialogs (I3, ADR 0041)."""
        self.enqueue("moveout", {"library_root": str(library_root),
                                 "target_root": str(target_root), "min_date": min_date},
                     msg("taskMoveout"))

    def enqueue_thumb_warm(
        self, cache_dir: str | Path, size: int, *, retry_failed: bool = False,
        auto: bool = False,
    ) -> None:
        """„Thumbnails erstellen" (ADR 0013/0020). ``auto`` = Nachläufer nach
        Import/Watch-Schub: wartet schon einer, reicht das; läuft gerade einer,
        kommt der neue trotzdem dran (neue Dateien)."""
        self.enqueue("thumb_warm",
                     {"cache_dir": str(cache_dir), "size": int(size),
                      "retry_failed": bool(retry_failed)},
                     msg("taskThumbWarm"), dedupe="pending" if auto else "all")

    def enqueue_media_date_backfill(self, min_date: datetime | None = None) -> None:
        """``min_date`` (konfiguriert, ``[import] min_date``) wandert mit —
        picklebar als ISO-Text (#113)."""
        params = {"min_date": f"{min_date:%Y-%m-%d}"} if min_date is not None else {}
        self.enqueue("backfill_dates", params, msg("taskBackfillDates"))

    def enqueue_search_reindex(self) -> None:
        self.enqueue("search_reindex", {}, msg("taskReindex"))

    # -- Wartungsaufgaben (Stufe 2A, ADR 0014) --------------------------------

    def enqueue_reparse(self) -> None:
        self.enqueue("reparse", {}, msg("taskReparse"))

    def enqueue_rescan(self, rules: dict[str, Any] | None = None) -> None:
        """``rules`` — Import-Regeln aus der Config; beim Re-Scan zählt vor
        allem ``min_date`` (Datumsregel, ADR 0075)."""
        self.enqueue("rescan", {"rules": rules}, msg("taskRescan"))

    def enqueue_integrity_check(self) -> None:
        self.enqueue("integrity", {}, msg("taskIntegrity"))

    def enqueue_vacuum(self) -> None:
        self.enqueue("vacuum", {}, msg("taskVacuum"))

    # -- Öffentliche API ------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._lock:
            st = dict(self._state)
            st["queue_pending"] = len(self._pending)
            st["queue"] = [q.label for q in self._pending]
            if self._worker_died:
                st["worker_alive"] = False
            elif self._proc is None:
                st["worker_alive"] = None       # noch nie gebraucht
            else:
                st["worker_alive"] = self._proc.is_alive()
            st["elapsed"] = (round(time.time() - self._started_at, 1)
                             if self._started_at is not None else None)
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
        """Beendet Watcher, Worker-Prozess und Schreibverbindung (idempotent)."""
        self.stop_all_watches()
        with self._lock:
            if self._closed:
                return
            self._closed = True
            proc, task_q, status_q, reader = self._proc, self._task_q, self._status_q, self._reader
            self._proc = self._task_q = self._status_q = self._reader = None
            self._pending.clear()
        self._wake.set()   # Dispatcher beenden
        if proc is not None:
            if proc.is_alive():
                try:
                    task_q.put({"op": "stop"})
                except (OSError, ValueError):
                    pass
                proc.join(timeout=5)
                if proc.is_alive():
                    log.warning("Worker does not respond to stop - terminating.")
                    proc.terminate()
                    proc.join(timeout=2)
            log.info("Worker process exited (exitcode %s)", proc.exitcode)
        if task_q is not None:
            task_q.close()
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=2)
        if status_q is not None:
            status_q.close()
        with self._write_lock:
            if self._write_conn is not None:
                self._write_conn.close()
                self._write_conn = None


def _noop_progress(*, report: dict | None = None, current: Any = None) -> None:
    return None


def _rollback(conn: sqlite3.Connection) -> None:
    try:
        if conn.in_transaction:
            conn.rollback()
    except Exception:
        pass


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
