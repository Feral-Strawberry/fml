"""In-Prozess-Cache mit SQLite-Schreib-Epoche (ADR 0048).

Ergebnisse, die sich nur durch Schreibzugriffe ändern (sortierte
Trefferlisten, Modell-Basisliste), werden im Web-Prozess gemerkt und erst
verworfen, wenn tatsächlich geschrieben wurde. Epochen-Quelle ist SQLite
selbst: eine langlebige Sentinel-Lese-Verbindung liefert per ``PRAGMA
data_version`` einen Wert, der sich ändert, sobald IRGENDEINE andere
Verbindung committet hat — auch der Engine-Writer und CLI-Schreiber wie
``python -m feral.interpret``, die an der Engine vorbeischreiben.
``data_version`` ist nur je Verbindung aussagekräftig, daher die EINE
Sentinel-Verbindung pro Cache; sie führt ausschließlich dieses PRAGMA aus
(Mikrosekunden) und hält nie eine Lese-Transaktion offen.

Korrektheitsregel (ADR 0048): **kein Cache-Treffer ohne aktuelle
data_version.**
"""

from __future__ import annotations

import sqlite3
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable


class EpochCache:
    """Kleiner LRU, dessen Einträge an die Schreib-Epoche der DB hängen.

    Threadsicher (FastAPI bedient ``def``-Endpunkte aus einem Threadpool).
    ``compute`` läuft bewusst AUSSERHALB des Locks: parallele Erst-Anfragen
    rechnen schlimmstenfalls doppelt, blockieren sich aber nicht — für
    Lese-Queries der richtige Tausch. Gecachte Werte gelten als
    unveränderlich; Aufrufer dürfen sie nicht mutieren.
    """

    def __init__(self, db_path: str | Path, *, maxsize: int = 4) -> None:
        # Eigene nackte Verbindung statt db.connect(): keine Migrationen,
        # kein WAL-Umschalten — das Sentinel liest nur die Epochennummer.
        self._sentinel = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        self._maxsize = maxsize
        self._entries: OrderedDict[Any, tuple[int, Any]] = OrderedDict()

    def get(self, key: Any, compute: Callable[[], Any]) -> Any:
        """Wert zu ``key`` aus dem Cache — oder ``compute()`` und merken.

        Die Epoche wird VOR ``compute`` gelesen: committet jemand während
        der Berechnung, liegt höchstens ein FRISCHERES Ergebnis unter der
        alten Epoche — der nächste Zugriff sieht die neue ``data_version``
        und rechnet neu. (Läse man sie danach, könnte ein veraltetes
        Ergebnis unter der neuen Epoche kleben bleiben.)
        """
        with self._lock:
            epoch = self._sentinel.execute("PRAGMA data_version").fetchone()[0]
            entry = self._entries.get(key)
            if entry is not None and entry[0] == epoch:
                self._entries.move_to_end(key)
                return entry[1]
        value = compute()
        with self._lock:
            self._entries[key] = (epoch, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._maxsize:
                self._entries.popitem(last=False)
        return value

    def close(self) -> None:
        with self._lock:
            self._entries.clear()
            self._sentinel.close()
