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

Kalt-Markierung (Issue #95, ADR 0071): Wer ``get`` den ASGI-``scope`` der
laufenden Anfrage mitgibt, bekommt bei einer Neuberechnung ``scope[COLD_KEY]``
gesetzt — mit dem Grund (``"start"``: dieser Schlüssel wurde seit
Prozessstart noch nie gerechnet, ``"write"``: Eintrag da, aber Epoche
veraltet, ``"new"``: schon einmal gerechnet, aber aus dem LRU verdrängt). Die Anfragen-Middleware (``app._SlowRequestLog``) schreibt eine
so markierte langsame Anfrage als INFO ``kalt:`` statt WARNING ``langsam:``
— die Erstberechnung nach Start oder Schreibvorgang ist echte DB-Arbeit
und kein Fehler.
"""

from __future__ import annotations

import sqlite3
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

#: Schlüssel im ASGI-Scope: Grund der Neuberechnung ("start"/"write"/"new").
COLD_KEY = "feral.cold"


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
        self._seen: set[Any] = set()   # je gerechnete Schlüssel → Kalt-Grund

    def get(self, key: Any, compute: Callable[[], Any], *,
            scope: dict | None = None) -> Any:
        """Wert zu ``key`` aus dem Cache — oder ``compute()`` und merken.

        Die Epoche wird VOR ``compute`` gelesen: committet jemand während
        der Berechnung, liegt höchstens ein FRISCHERES Ergebnis unter der
        alten Epoche — der nächste Zugriff sieht die neue ``data_version``
        und rechnet neu. (Läse man sie danach, könnte ein veraltetes
        Ergebnis unter der neuen Epoche kleben bleiben.)

        ``scope`` (optional, der ASGI-Scope der Anfrage): bei einer
        Neuberechnung wird ``scope[COLD_KEY]`` mit dem Grund gesetzt — ein
        einmal gesetzter Grund bleibt (die erste Ursache zählt).
        """
        with self._lock:
            epoch = self._sentinel.execute("PRAGMA data_version").fetchone()[0]
            entry = self._entries.get(key)
            if entry is not None and entry[0] == epoch:
                self._entries.move_to_end(key)
                return entry[1]
            reason = "write" if entry else ("new" if key in self._seen else "start")
        if scope is not None:
            scope.setdefault(COLD_KEY, reason)
        value = compute()
        with self._lock:
            self._seen.add(key)
            self._entries[key] = (epoch, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._maxsize:
                self._entries.popitem(last=False)
        return value

    def close(self) -> None:
        with self._lock:
            self._entries.clear()
            self._sentinel.close()
