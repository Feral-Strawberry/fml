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
import sys
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


def default_workers() -> int:
    """Automatik der Pool-Größe (#225, ADR 0093): bis 4 logische Kerne EIN
    Prozess (auf kleinen Rechnern blieb sonst nichts für die Bedienung),
    darüber Kerne − 2. Gilt für Worker- und Thumbnail-Pool."""
    cores = os.cpu_count() or 4
    return 1 if cores <= 4 else cores - 2


# Windows: SetPriorityClass-Werte (winbase.h).
_IDLE = 0x00000040               # niedrigste Klasse — vererbt sich an ffmpeg & Co.
_BELOW_NORMAL = 0x00004000
_NORMAL = 0x00000020
_BACKGROUND_BEGIN = 0x00100000   # CPU-, E/A- und Speicherpriorität zugleich (nicht vererbt)
_BACKGROUND_END = 0x00200000

# Läuft DIESER Prozess leise? (von set_process_priority gesetzt) — ffmpeg-
# Aufrufe aus Pool-Prozessen fragen es ab (``ffmpeg_quiet_args``).
_quiet = False


def _win_kernel():
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.GetProcessAffinityMask.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
    kernel.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
    return ctypes, kernel


def one_core_mask(system_mask: int) -> int:
    """Der letzte verfügbare logische Kern als Affinitätsmaske (ADR 0093)."""
    return 1 << (system_mask.bit_length() - 1) if system_mask else 1


def _win_priority(quiet: bool, low: bool) -> None:
    ctypes, kernel = _win_kernel()
    handle = kernel.GetCurrentProcess()
    if quiet:
        # Klasse IDLE zuerst (erben gestartete Programme wie ffmpeg), dann
        # der Hintergrund-Modus für Platte und Speicher obendrauf.
        kernel.SetPriorityClass(handle, _IDLE)
        kernel.SetPriorityClass(handle, _BACKGROUND_BEGIN)
    else:
        kernel.SetPriorityClass(handle, _BACKGROUND_END)
        kernel.SetPriorityClass(handle, _BELOW_NORMAL if low else _NORMAL)
    # Harte Grenze: EIN Kern für diesen Prozess und alles, was er startet
    # (die Affinität erbt jeder Kindprozess); zurück = alle Kerne.
    process_mask, system_mask = ctypes.c_size_t(), ctypes.c_size_t()
    if kernel.GetProcessAffinityMask(handle, ctypes.byref(process_mask),
                                     ctypes.byref(system_mask)):
        target = one_core_mask(system_mask.value) if quiet else system_mask.value
        if target and target != process_mask.value:
            kernel.SetProcessAffinityMask(handle, target)


def set_process_priority(*, quiet: bool, low: bool = True) -> None:
    """Priorität des EIGENEN Prozesses setzen (ADR 0093), nur stdlib.

    ``quiet`` = Leise: unter Windows niedrigste Klasse + Hintergrund-Modus
    (CPU, Platte, Speicher) und **hart auf einen Kern** festgelegt — beides
    erben von hier gestartete Programme (ffmpeg). macOS ``PRIO_DARWIN_BG``,
    Linux ``nice 19`` (ohne Kern-Festlegung: die Zielgruppe hat Leistung
    genug, das Problem war ein Windows-Notebook). Sonst ``low`` = etwas
    unter normal (bisheriges Verhalten der Pool-Prozesse). Zurück aus
    ``quiet`` geht unter Windows und macOS; Linux lässt unprivilegiert
    keinen kleineren nice-Wert zu. Priorität ist Komfort: Fehler werden
    geschluckt."""
    global _quiet
    _quiet = quiet
    try:
        if sys.platform == "win32":
            _win_priority(quiet, low)
        elif sys.platform == "darwin" and hasattr(os, "PRIO_DARWIN_BG"):
            os.setpriority(os.PRIO_DARWIN_PROCESS, 0, os.PRIO_DARWIN_BG if quiet else 0)
            if not quiet and low:
                os.setpriority(os.PRIO_PROCESS, 0, max(os.getpriority(os.PRIO_PROCESS, 0), 10))
        else:
            target = 19 if quiet else (10 if low else 0)
            current = os.getpriority(os.PRIO_PROCESS, 0)
            if target > current:
                os.setpriority(os.PRIO_PROCESS, 0, target)
    except Exception:
        pass


def ffmpeg_quiet_args() -> list[str]:
    """Globale ffmpeg-Optionen im Leise-Modus (ADR 0093): ein Thread für
    Dekoder und Filter — sonst nimmt sich EIN ffmpeg alle Kerne."""
    if not _quiet:
        return []
    return ["-threads", "1", "-filter_threads", "1", "-filter_complex_threads", "1"]


def init_pool_process(low_priority: bool = False, quiet: bool = False) -> None:
    """Initializer für Pool-Prozesse: an den Elternprozess binden (ADR 0067)
    und die Priorität setzen (Leise-Modus, ADR 0093)."""
    exit_when_parent_dies()
    if quiet or low_priority:
        set_process_priority(quiet=quiet, low=low_priority)


# Steuerblock zwischen Web-Prozess und Worker (ADR 0093), ein
# ``multiprocessing.Array("i", CONTROL_SIZE)``:
CTRL_HALT = 0       # 0 = weiter, sonst Grund des Halts (HALT_*)
CTRL_QUIET = 1      # 1 = Leise (1 Prozess, Hintergrund-Priorität)
CTRL_WORKERS = 2    # konfigurierte Prozesszahl, 0 = Automatik
CTRL_LOW = 3        # 1 = Pool-Prozesse etwas unter normal
CONTROL_SIZE = 4
HALT_PAUSE, HALT_YIELD, HALT_SHUTDOWN = 1, 2, 3


def effective_workers(configured: int | None, quiet: bool) -> int:
    """Pool-Größe im gegebenen Modus: Leise = 1, sonst Config oder Automatik."""
    return 1 if quiet else (configured or default_workers())
