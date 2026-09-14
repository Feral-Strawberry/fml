"""Kindprozesse an ihren Elternprozess binden (ADR 0067).

``concurrent.futures``-Pool-Prozesse und der Worker warten auf Aufträge
über Pipes/Queues, deren Enden sie selbst mit offen halten — stirbt der
Elternprozess hart (SIGKILL, Absturz, Task-Manager), merken sie es nie und
bleiben als Waisen liegen (im Browser-Durchgang zu #65 gesehen: 11
Pool-Prozesse nach einem ``kill -9`` des Workers). ``exit_when_parent_dies``
startet einen Wächter-Thread, der auf das Ende des Elternprozesses wartet
(``multiprocessing.parent_process().join()`` — plattformübergreifend über
das Prozess-Sentinel) und den eigenen Prozess dann sofort beendet.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import threading


def exit_when_parent_dies() -> None:
    """Als Initializer von Pool-Prozessen bzw. am Anfang eines Worker-
    Einstiegs aufrufen. Ohne Elternprozess (Hauptprozess) passiert nichts."""
    parent = mp.parent_process()
    if parent is None:
        return

    def watch() -> None:
        parent.join()
        os._exit(0)

    threading.Thread(target=watch, name="parent-watch", daemon=True).start()
