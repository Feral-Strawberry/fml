"""Worker-Prozess für Langläufer (ADR 0067).

Der Web-Prozess startet genau EINEN Worker (``multiprocessing``, immer
``spawn``) und schickt ihm über eine Queue **eine Aufgabe auf einmal**
(``{"op": "run", "id", "name", "params", "label"}``); der Worker meldet
Ereignisse über eine Queue zurück:

    {"ev": "started",  "id", "at"}
    {"ev": "progress", "id", "report", "current"}      (gedrosselt, ≤ 10/s)
    {"ev": "finished", "id", "result", "report", "duration"}

Der Worker besitzt die EINE schreibende Verbindung für Langläufer (ADR
0007, Nachtrag) und hält prozess-lokal einen Prozess-Pool fürs Parsen
(Reparse) sowie einen eigenen ``ThumbPool`` fürs Vorwärmen. Eine kaputte
Aufgabe beendet nie den Worker; stirbt der Prozess trotzdem, merkt es der
Web-Prozess (``is_alive``) und startet ihn beim nächsten Auftrag neu.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import signal
import time
import traceback
from concurrent.futures import Executor, ProcessPoolExecutor
from typing import Any

from ..db import connect, optimize
from ..logsetup import WORKER_LOG, setup_logging
from ..messages import msg
from ..processes import exit_when_parent_dies
from .tasks import TASKS

log = logging.getLogger("feral.worker")

PROGRESS_INTERVAL = 0.1     # Sekunden zwischen zwei Fortschritts-Ereignissen
LOG_INTERVAL = 10.0         # Sekunden zwischen zwei Fortschritts-Logzeilen


def default_pool_workers() -> int:
    return max(2, (os.cpu_count() or 4) - 2)


class WorkerContext:
    """Prozess-lokale Helfer für Aufgaben (``tasks.TaskContext``)."""

    def __init__(self, *, pool_workers: int | None, thumb_workers: int | None,
                 thumb_low_priority: bool) -> None:
        self.pool_workers = pool_workers or default_pool_workers()
        self.thumb_workers = thumb_workers
        self.thumb_low_priority = thumb_low_priority
        self._pool: Executor | None = None
        self._thumbs = None

    def pool(self) -> Executor:
        if self._pool is None:
            # Pool-Prozesse sterben mit dem Worker (Eltern-Wächter) — sonst
            # bleiben sie nach einem harten Worker-Tod als Waisen liegen.
            self._pool = ProcessPoolExecutor(
                max_workers=self.pool_workers, mp_context=mp.get_context("spawn"),
                initializer=exit_when_parent_dies,
            )
            log.info("Process pool started: %d processes", self.pool_workers)
        return self._pool

    def thumb_pool(self):
        if self._thumbs is None:
            from ..thumbs import ThumbPool

            self._thumbs = ThumbPool(workers=self.thumb_workers,
                                     low_priority=self.thumb_low_priority)
        return self._thumbs

    def release(self) -> None:
        """Nach jeder Aufgabe: den Parse-Pool abbauen. Leerlaufende Pool-
        Prozesse halten sonst je ~90 MB (14 Prozesse: 1,2 GB, gemessen) und
        unter Windows bis zu 30 Prozesse — für Sekunden Arbeit. Der
        ThumbPool bleibt (ADR 0020: lazy, langlebig) — Watch-Schübe kämen
        sonst bei jedem neuen Bild mit 30 frischen Prozessstarts."""
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None
        if self._thumbs is not None:
            self._thumbs.shutdown()
            self._thumbs = None


def _label_text(label: Any) -> str:
    """Meldungs-Dict → knappe Logform (übersetzt wird nur im Frontend)."""
    if isinstance(label, dict):
        params = label.get("params") or {}
        return label.get("key", "?") + (f" {params}" if params else "")
    return str(label)


def run_task(conn, task: dict[str, Any], ctx, emit) -> None:
    """Eine Aufgabe ausführen und ihre Ereignisse über ``emit`` melden."""
    task_id, name = task["id"], task["name"]
    fn = TASKS.get(name)
    started = time.time()
    last_sent = 0.0
    last_logged = started
    state = {"report": None, "current": None}
    emit({"ev": "started", "id": task_id, "at": started})
    log.info("Start %s [%s] queue=%s", _label_text(task.get("label")), name,
             task.get("queue_pending", 0))

    def progress(*, report=None, current=None) -> None:
        nonlocal last_sent, last_logged
        if report is not None:
            state["report"] = report
        state["current"] = current
        now = time.monotonic()
        if now - last_sent >= PROGRESS_INTERVAL:
            last_sent = now
            emit({"ev": "progress", "id": task_id, "report": state["report"],
                  "current": current})
        wall = time.time()
        if wall - last_logged >= LOG_INTERVAL:
            last_logged = wall
            log.info("… %s: %s", name, _label_text(current))

    try:
        if fn is None:
            raise KeyError(f"unknown task {name!r}")
        result = fn(conn, task.get("params") or {}, progress, ctx)
        if conn.in_transaction:
            conn.commit()
        outcome = _label_text(result.get("summary")) if isinstance(result, dict) else str(result)
        log.info("Done %s after %.1fs: %s", name, time.time() - started, outcome or "ok")
    except Exception as exc:  # Aufgabe kaputt ≠ Worker kaputt
        try:
            conn.rollback()
        except Exception:
            pass
        log.error("Error in %s after %.1fs: %s\n%s", name, time.time() - started,
                  exc, traceback.format_exc())
        result = {"summary": msg("sumFailed", error=f"{exc.__class__.__name__}: {exc}")}
    emit({"ev": "finished", "id": task_id, "result": result, "report": state["report"],
          "duration": time.time() - started})


def run_worker(db_path: str, task_queue, status_queue, *, log_dir: str | None = None,
               pool_workers: int | None = None, thumb_workers: int | None = None,
               thumb_low_priority: bool = True) -> None:
    """Einstieg des Worker-Prozesses (importierbar — Windows ``spawn``)."""
    # Strg+C in der Konsole trifft die ganze Prozessgruppe: der Web-Prozess
    # fährt herunter und schickt uns „stop" — wir selbst ignorieren SIGINT.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # Stirbt der Web-Prozess hart, endet der Worker sofort (nicht erst,
    # wenn die laufende Aufgabe auf die tote Leitung stößt).
    exit_when_parent_dies()
    setup_logging(log_dir, WORKER_LOG)
    log.info("Worker started (pid %d)", os.getpid())
    ctx = WorkerContext(pool_workers=pool_workers, thumb_workers=thumb_workers,
                        thumb_low_priority=thumb_low_priority)
    conn = connect(db_path)
    try:
        while True:
            try:
                message = task_queue.get()
            except (EOFError, OSError):
                log.warning("Connection to the web process lost - worker exits.")
                break
            if not isinstance(message, dict) or message.get("op") == "stop":
                log.info("Worker stopped (stop).")
                break
            run_task(conn, message, ctx, status_queue.put)
            ctx.release()
            optimize(conn)  # Planer-Statistik nach jedem Schreib-Lauf (#85)
    finally:
        ctx.close()
        conn.close()
        try:
            status_queue.put({"ev": "bye"})
            status_queue.close()
            status_queue.join_thread()
        except Exception:
            pass
