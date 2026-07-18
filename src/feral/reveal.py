"""„Im Dateimanager anzeigen" (I6, ADR 0041): Explorer/Finder mit markierter Datei.

Der SERVER öffnet den Dateimanager — im Normalbetrieb (localhost, ADR 0001)
ist das genau der Rechner, vor dem der Anwender sitzt. Windows und macOS
können die Datei direkt markieren (``explorer /select,`` / ``open -R``);
sonst Fallback: den umgebenden Ordner öffnen (``xdg-open``).

Reine Anzeige — es wird nichts kopiert, verschoben oder gelöscht. Der
Übersichtsmodus (I4) sperrt hier deshalb bewusst nicht.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def reveal_command(path: Path, platform: str = sys.platform) -> list[str]:
    """Das plattformrichtige Kommando (pur — testbar ohne Prozessstart)."""
    if platform == "win32":
        # explorer erwartet Schalter und Pfad als EIN Argument: "/select,<pfad>".
        return ["explorer", f"/select,{path}"]
    if platform == "darwin":
        return ["open", "-R", str(path)]
    return ["xdg-open", str(path.parent)]


def show_in_file_manager(path: Path) -> None:
    """Dateimanager öffnen, Datei markiert (wo die Plattform das kann).

    Feuern und vergessen: explorer/open kehren sofort zurück, und auf den
    Exit-Code ist kein Verlass (explorer.exe meldet auch bei Erfolg 1).
    Ein fehlendes Binary (z. B. kein xdg-open) wirft OSError — das fängt
    der Endpunkt und meldet es ehrlich.
    """
    subprocess.Popen(
        reveal_command(path),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
