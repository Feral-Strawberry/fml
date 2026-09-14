"""„Im Dateimanager anzeigen" (I6, ADR 0041): Explorer/Finder mit markierter Datei.

Der SERVER öffnet den Dateimanager — im Normalbetrieb (localhost, ADR 0001)
ist das genau der Rechner, vor dem der Anwender sitzt. Windows und macOS
können die Datei direkt markieren (``explorer /select,`` / ``open -R``);
sonst Fallback: den umgebenden Ordner öffnen (``xdg-open``).

Reine Anzeige — es wird nichts kopiert, verschoben oder gelöscht. Der
Übersichtsmodus (I4) sperrt hier deshalb bewusst nicht.

Windows-Eigenheiten (ADR-0062-Nachtrag, Issue #37): Erster Weg ist die
Shell-API ``SHOpenFolderAndSelectItems`` (per ``ctypes``, Stdlib) — sie
markiert zuverlässig UND scrollt die Datei ins Bild, auch wenn Explorer
erst ein Fenster hochziehen muss (``explorer /select,`` verliert die
Markierung dann oft, und in großen Ordnern liegt die Datei außerhalb des
Viewports; Windows-Befund von Feral Strawberry). Schlägt die API fehl, Rückfall auf
``explorer /select,``: explorer.exe zerlegt seine Kommandozeile SELBST.
Übergibt man ``/select,<pfad>`` als ein Listen-Argument, setzt
``subprocess`` bei Leerzeichen im Pfad die Anführungszeichen um das GANZE
Argument (``"/select,C:\\a b\\x.png"``) — das versteht Explorer nicht und
öffnet kommentarlos „Dokumente". Darum wird die Kommandozeile für Windows
als String gebaut, Anführungszeichen nur um den Pfad. Pfade über der
klassischen MAX_PATH-Grenze kann ``/select,`` nicht markieren; dann öffnet
fml ehrlich den umgebenden Ordner und meldet das (``selected=False``).

Absprung ins Standardprogramm / in den Ordner (ADR-0041-Nachtrag,
Issue #37): ``open_in_default_app`` öffnet eine Datei mit dem vom System
zugeordneten Programm bzw. einen Ordner im Dateimanager, ohne Markierung.
fml selbst fasst dabei weiterhin nichts an — was das fremde Programm
danach tut, liegt beim Anwender.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path, PurePath, PureWindowsPath

log = logging.getLogger(__name__)

# Klassische Windows-Pfadgrenze (MAX_PATH 260 inkl. NUL): darüber kann
# ``explorer /select,`` die Datei nicht markieren.
WINDOWS_MAX_PATH = 259


def windows_display_path(path: str) -> str:
    """Pfad so, wie explorer.exe ihn versteht: ohne ``\\\\?\\``-Präfix
    (Langpfad-Syntax nur für die Win32-API, nicht für Explorer);
    ``\\\\?\\UNC\\server\\share`` wird wieder ``\\\\server\\share``."""
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[len("\\\\?\\UNC\\"):]
    if path.startswith("\\\\?\\"):
        return path[len("\\\\?\\"):]
    return path


def reveal_command(
    path: PurePath, platform: str = sys.platform
) -> tuple[list[str] | str, bool]:
    """Das plattformrichtige Kommando (pur — testbar ohne Prozessstart)
    plus ``selected``: ob die Datei markiert wird (``False`` = nur der
    umgebende Ordner geht auf).

    Windows liefert die Kommandozeile als STRING (s. Modul-Doku), die
    anderen Plattformen eine Argumentliste.
    """
    if platform == "win32":
        shown = windows_display_path(str(path))
        if len(shown) > WINDOWS_MAX_PATH:
            # Explorer-Grenze: Datei nicht markierbar — Ordner öffnen.
            parent = windows_display_path(str(path.parent))
            return f'explorer "{parent}"', False
        # Windows-Pfade enthalten nie ", die Quotes sind darum sicher.
        return f'explorer /select,"{shown}"', True
    if platform == "darwin":
        return ["open", "-R", str(path)], True
    return ["xdg-open", str(path.parent)], False


def windows_shell_select(path: str) -> None:
    """Datei per Shell-API markieren (nur Windows): ``ILCreateFromPathW`` →
    ``SHOpenFolderAndSelectItems`` mit cidl=0 („vollständige PIDL, Elternordner
    öffnen und das Item markieren"). COM je Thread initialisieren — der
    Endpunkt läuft im FastAPI-Threadpool. Wirft OSError bei jedem Fehler
    (ctypes' HRESULT-Prüfung), der Aufrufer fällt dann zurück."""
    import ctypes
    from ctypes import wintypes

    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)
    try:
        shell32.ILCreateFromPathW.restype = ctypes.c_void_p
        shell32.ILCreateFromPathW.argtypes = [wintypes.LPCWSTR]
        pidl = shell32.ILCreateFromPathW(path)
        if not pidl:
            raise OSError(f"ILCreateFromPathW scheiterte: {path}")
        try:
            shell32.SHOpenFolderAndSelectItems.restype = ctypes.HRESULT
            shell32.SHOpenFolderAndSelectItems.argtypes = [
                ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, wintypes.DWORD]
            shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0)
        finally:
            shell32.ILFree.argtypes = [ctypes.c_void_p]
            shell32.ILFree(pidl)
    finally:
        ole32.CoUninitialize()


def explorer_title_matches(title: str, folder: str) -> bool:
    """Gehört ein Explorer-Fenstertitel zu ``folder``? Explorer zeigt den
    Anzeigenamen des Ordners (letztes Segment), mit der Option „vollständigen
    Pfad in der Titelleiste" den ganzen Pfad, bei Laufwerkswurzeln
    „Bezeichnung (D:)". Vergleich ASCII-case-unempfindlich (pur, testbar)."""
    t = title.strip().lower()
    full = folder.rstrip("\\").lower()
    if not t or not full:
        return False
    if t == full:
        return True
    base = full.rsplit("\\", 1)[-1]
    # Windows 11 hängt je nach Build „ - Datei-Explorer" o. Ä. an.
    if t == base or t.startswith(base + " "):
        return True
    return len(full) == 2 and full.endswith(":") and t.endswith(f"({full})")


def explorer_windows() -> list[tuple[int, str]]:
    """Sichtbare Explorer-Fenster (Klasse ``CabinetWClass``) als
    ``(hwnd, titel)`` in Z-Reihenfolge, oberstes zuerst (nur Windows)."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    hits: list[tuple[int, str]] = []

    def cb(hwnd, _lparam):
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value == "CabinetWClass" and user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd) + 1
            buf = ctypes.create_unicode_buffer(n)
            user32.GetWindowTextW(hwnd, buf, n)
            hits.append((hwnd, buf.value))
        return True

    user32.EnumWindows(enum_proc(cb), 0)
    return hits


def explorer_handles_before() -> frozenset[int]:
    """Momentaufnahme der Explorer-Fenster VOR dem Öffnen — damit danach das
    NEUE Fenster sofort erkannt wird, ohne auf Titel-Raten oder einen
    Timeout angewiesen zu sein. Leer, wo es keine Windows-API gibt."""
    try:
        return frozenset(h for h, _t in explorer_windows())
    except Exception:  # noqa: BLE001 - nur Komfort
        return frozenset()


def windows_focus_explorer(
    folder: str, *, before: frozenset[int] = frozenset(), timeout: float = 1.0
) -> bool:
    """Das Explorer-Fenster zu ``folder`` in den Vordergrund holen (nur
    Windows). ``SHOpenFolderAndSelectItems`` und ``os.startfile`` auf einen
    Ordner öffnen über die laufende Shell — ein Hintergrundprozess wie der
    fml-Server darf deren Fenster nicht nach vorn holen (Foreground-Sperre),
    das Fenster landet HINTER dem Browser. Der frühere Weg über einen neuen
    ``explorer.exe``-Prozess bekam das Fokusrecht mit.

    Fenster finden, in dieser Reihenfolge: (1) ein Fenster, das seit
    ``before`` NEU ist (der Normalfall — sofort, sobald es da ist, 50-ms-
    Polling); (2) ein Fenster, dessen Titel zum Ordner passt (Fenster wurde
    wiederverwendet); (3) nach ``timeout`` das oberste Explorer-Fenster.
    Dann ``SetForegroundWindow``, bei Sperre der AttachThreadInput-Weg,
    zuletzt ``SwitchToThisWindow`` (Alt-Tab-Mechanik). Keine
    Tastensimulation (ein simuliertes ALT klappt im Browser die Menüleiste
    auf). Liefert, ob das Fenster im Vordergrund ist."""
    import ctypes
    import time

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    deadline = time.monotonic() + timeout
    hwnd = None
    while True:
        wins = explorer_windows()
        hwnd = next((h for h, _t in wins if h not in before), None)
        if hwnd is None:
            hwnd = next((h for h, t in wins if explorer_title_matches(t, folder)), None)
        if hwnd or time.monotonic() > deadline:
            if hwnd is None and wins:
                hwnd = wins[0][0]
            break
        time.sleep(0.05)
    if not hwnd:
        return False

    SW_RESTORE = 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    if user32.GetForegroundWindow() == hwnd:
        return True
    # Foreground-Sperre: an den Eingabe-Thread des aktuellen Vordergrund-
    # fensters anhängen, dann darf unser Thread den Vordergrund setzen.
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    me = kernel32.GetCurrentThreadId()
    if fg_thread and fg_thread != me and user32.AttachThreadInput(me, fg_thread, True):
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            user32.AttachThreadInput(me, fg_thread, False)
    if user32.GetForegroundWindow() != hwnd:
        user32.SwitchToThisWindow(hwnd, True)
    return user32.GetForegroundWindow() == hwnd


def show_in_file_manager(path: Path, platform: str = sys.platform) -> tuple[bool, str]:
    """Dateimanager öffnen, Datei markiert (wo die Plattform das kann).
    Liefert ``(selected, via)``: ob die Datei markiert wird oder nur ihr
    Ordner aufgeht, und welcher Weg es war (``shell-api`` / ``explorer`` /
    ``open`` / ``xdg-open``) — für die Windows-Diagnose in der Antwort.

    Windows: erst die Shell-API, danach das Fenster in den Vordergrund
    (``via`` = ``shell-api-nofocus``, wenn das nicht gelang); wirft die
    API, Rückfall auf ``explorer`` (wird geloggt). Feuern und vergessen: explorer/open kehren sofort
    zurück, und auf den Exit-Code ist kein Verlass (explorer.exe meldet
    auch bei Erfolg 1). Ein fehlendes Binary (z. B. kein xdg-open) wirft
    OSError — das fängt der Endpunkt und meldet es ehrlich.
    """
    if platform == "win32":
        shown = windows_display_path(str(path))
        before = explorer_handles_before()
        try:
            windows_shell_select(shown)
        except (OSError, AttributeError) as exc:
            log.warning("Shell API selection failed, falling back to explorer: %s", exc)
        else:
            # Fenster nach vorn — ohne das landet es hinter dem Browser.
            focused = _focus_quietly(str(PureWindowsPath(shown).parent), before)
            return True, "shell-api" if focused else "shell-api-nofocus"
    cmd, selected = reveal_command(path, platform)
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    via = cmd.split(" ", 1)[0] if isinstance(cmd, str) else cmd[0]
    return selected, via


def _focus_quietly(folder: str, before: frozenset[int]) -> bool:
    """Fokus ist Komfort, nie ein Fehler: Ausnahmen werden geloggt."""
    try:
        return windows_focus_explorer(folder, before=before)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not focus the Explorer window: %s", exc)
        return False


def open_command(path: PurePath, platform: str = sys.platform) -> list[str] | None:
    """Kommando, das Datei ODER Ordner mit dem zugeordneten Programm öffnet
    (Ordner ⇒ Dateimanager, ohne Markierung). ``None`` = ``os.startfile``
    (Windows, Stdlib — löst die Zuordnung über die Shell auf)."""
    if platform == "win32":
        return None
    if platform == "darwin":
        return ["open", str(path)]
    return ["xdg-open", str(path)]


def open_in_default_app(path: Path, platform: str = sys.platform) -> None:
    """Datei im zugeordneten Programm bzw. Ordner im Dateimanager öffnen.
    OSError bei fehlendem Binary/Zuordnung — der Endpunkt meldet es."""
    cmd = open_command(path, platform)
    if cmd is None:
        shown = windows_display_path(str(path))
        is_dir = Path(shown).is_dir()
        # Ordner gehen über die Shell auf und landen hinter dem Browser
        # (s. windows_focus_explorer); Programme holen sich den Fokus selbst.
        before = explorer_handles_before() if is_dir else frozenset()
        os.startfile(shown)  # type: ignore[attr-defined]
        if is_dir:
            _focus_quietly(shown, before)
        return
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
