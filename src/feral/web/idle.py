"""Selbst-Beenden bei Leerlauf (``--exit-when-idle``, ADR 0091).

Für Installationen ohne Kommandozeile: Der Server beendet sich selbst,
wenn einige Minuten lang keine Seite mehr ``/api/status`` abgefragt hat
UND keine Aufgabe läuft oder wartet. Jede offene fml-Seite (Bibliothek wie
Admin) fragt alle 0,7 s ab, auch im Hintergrund; Browser drosseln Timer
verdeckter Tabs aber auf etwa einen pro Minute. Die Grenze liegt deshalb
bei Minuten, nicht Sekunden.

Ohne den Schalter ändert sich nichts: ``IdleWatch`` wird dann nie gebaut.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

# Kürzer als die Browser-Drosselung verdeckter Tabs (1 Abruf/Minute) wäre
# gefährlich: ein minimiertes Fenster sähe dann aus wie ein geschlossenes.
MIN_IDLE_SECONDS = 120.0


def is_busy(status: dict[str, Any]) -> bool:
    """Läuft eine Aufgabe oder wartet eine? (wie ``isBusy`` in status.js)"""
    return bool(status.get("running")) or int(status.get("queue_pending") or 0) > 0


class IdleWatch:
    """Merkt sich den letzten Status-Abruf und entscheidet über das Ende.

    ``clock`` ist austauschbar (Tests). ``touch()`` ruft die Status-Route
    bei jedem Abruf; ``should_exit()`` prüft der Wächter-Thread."""

    def __init__(self, idle_seconds: float, *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.idle_seconds = max(float(idle_seconds), MIN_IDLE_SECONDS)
        self._clock = clock
        # Start zählt als Abruf: das Fenster bekommt die volle Frist, bis es
        # zum ersten Mal fragt.
        self._last = clock()

    def touch(self) -> None:
        self._last = self._clock()

    def idle_for(self) -> float:
        return self._clock() - self._last

    def should_exit(self, status: dict[str, Any]) -> bool:
        return self.idle_for() >= self.idle_seconds and not is_busy(status)


def start_watchdog(watch: IdleWatch, status: Callable[[], dict[str, Any]],
                   stop: Callable[[], None], *, interval: float = 10.0) -> threading.Thread:
    """Daemon-Thread: prüft alle ``interval`` Sekunden und ruft EINMAL
    ``stop()`` (uvicorn fährt dann regulär herunter, inkl. Worker)."""

    def run() -> None:
        while True:
            time.sleep(interval)
            try:
                if watch.should_exit(status()):
                    log.info("background: no page open for %.0f s and nothing to do, shutting down",
                             watch.idle_for())
                    stop()
                    return
            except Exception:  # der Wächter darf den Server nie mitreißen
                log.exception("background: idle watchdog failed")
                return

    thread = threading.Thread(target=run, name="idle-watchdog", daemon=True)
    thread.start()
    return thread
