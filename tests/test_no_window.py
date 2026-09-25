"""Konsolen-Werkzeuge ohne aufblitzendes Fenster unter Windows (#187).

Läuft fml ohne Konsole (pythonw, Windows-Paket), öffnet Windows für jeden
ffmpeg-/ffprobe-Aufruf ohne CREATE_NO_WINDOW ein eigenes cmd-Fenster, das
sofort wieder zugeht. Der Wächter hält alle Aufrufstellen auf **NO_WINDOW.
"""

from __future__ import annotations

import re
from pathlib import Path

from feral.tools import no_window

SRC = Path(__file__).resolve().parent.parent / "src" / "feral"

# reveal.py startet den Explorer (ein Fensterprogramm, kein Konsolen-Werkzeug).
EXEMPT = {"reveal.py"}

CALL = re.compile(r"(?:subprocess\.(?:run|Popen|check_output|call)|\bproc = run)\(")


def test_flag_only_on_windows():
    assert no_window("win32") == {"creationflags": 0x08000000}
    assert no_window("darwin") == {}
    assert no_window("linux") == {}


def _call_text(text: str, start: int) -> str:
    """Den Aufruf bis zur schließenden Klammer (Klammern gezählt)."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]


def test_every_console_tool_call_passes_no_window():
    missing = []
    for path in SRC.rglob("*.py"):
        if path.name in EXEMPT:
            continue
        text = path.read_text(encoding="utf-8")
        for m in CALL.finditer(text):
            call = _call_text(text, m.end() - 1)
            if "**NO_WINDOW" not in call:
                line = text.count("\n", 0, m.start()) + 1
                missing.append(f"{path.relative_to(SRC)}:{line}")
    assert not missing, "subprocess-Aufruf ohne **NO_WINDOW: " + ", ".join(missing)
