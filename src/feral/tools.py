"""Externe Werkzeuge (ffmpeg/ffprobe) plattformübergreifend finden.

Auf macOS/Linux liegt ffmpeg üblicherweise im PATH. Auf Windows landet es je
nach Installationsweg woanders (winget verlinkt nach %LOCALAPPDATA%, und der
neue PATH gilt erst in NEUEN Prozessen — der laufende Server sieht ihn nicht).
Darum: PATH zuerst, dann bekannte Windows-Orte. Ergebnis wird gecacht;
`refresh()` erzwingt eine neue Suche (Admin-Statusseite).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_cache: dict[str, str | None] = {}


def _windows_candidates(name: str) -> list[Path]:
    exe = f"{name}.exe"
    candidates: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        # winget legt Shims hier ab — auch ohne PATH-Neustart auffindbar.
        candidates.append(Path(local) / "Microsoft" / "WinGet" / "Links" / exe)
        # winget-Paketordner (Gyan.FFmpeg): .../<paket>/ffmpeg-*/bin/ffmpeg.exe
        packages = Path(local) / "Microsoft" / "WinGet" / "Packages"
        if packages.is_dir():
            candidates.extend(sorted(packages.glob(f"Gyan.FFmpeg*/**/bin/{exe}"))[:1])
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), "C:\\"):
        if base:
            candidates.append(Path(base) / "ffmpeg" / "bin" / exe)
    # Chocolatey
    candidates.append(Path("C:\\ProgramData\\chocolatey\\bin") / exe)
    return candidates


def find_binary(name: str) -> str | None:
    """Vollständiger Pfad zu `name` (ffmpeg/ffprobe) oder None. Gecacht."""
    if name in _cache:
        return _cache[name]
    found = shutil.which(name)
    if found is None and sys.platform == "win32":
        for candidate in _windows_candidates(name):
            if candidate.is_file():
                found = str(candidate)
                break
    _cache[name] = found
    return found


def refresh() -> None:
    """Cache leeren — nächste Suche läuft frisch (z. B. nach Installation)."""
    _cache.clear()
