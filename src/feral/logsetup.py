"""Serverlog (Issue #64, ADR 0067): rotierende Datei neben der Datenbank.

Ein Aufruf je Prozess (Web-Prozess: ``fml-web.log``, Worker-Prozess:
``fml-worker.log``). Stdlib ``logging``, ``RotatingFileHandler`` 5 × 5 MB;
die Konsole bekommt weiterhin nur Warnungen und Fehler. Ohne ``log_dir``
(Tests, Ad-hoc-Aufrufe) gibt es keine Datei, nur die Konsole.
"""

from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5
FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
WEB_LOG = "fml-web.log"
WORKER_LOG = "fml-worker.log"

_MARK = "_fml_handler"

# Log-Härtung (Release-QA #138, ADR-0067-Nachtrag): Meldungen enthalten
# Dateinamen und Pfade fremder Dateien (Scan-Warnungen, Watch-Quellen). Ein
# präparierter Name mit Zeilenumbruch könnte sonst eine gefälschte Logzeile
# erzeugen ("\n2026-… ERROR database corrupted"), ANSI-Sequenzen die Konsole
# steuern, Unicode-Bidi-Zeichen die Anzeige umdrehen. Alles davon wird
# SICHTBAR gemacht statt entfernt (``\n``, ``\x1b``, ``\u202e``): der
# Versuch bleibt im Log erkennbar. Tab bleibt Tab. Greift beim Schreiben
# (Formatter) und nochmal beim Anzeigen (``tail``, für ältere Dateien).
_CONTROL = re.compile(
    "[\x00-\x08\x0b-\x1f\x7f-\x9f"          # C0 ohne \t/\n, DEL, C1
    "\u200e\u200f\u202a-\u202e\u2066-\u2069"  # Bidi-Marken und -Isolate
    "\u2028\u2029]"                              # Unicode-Zeilentrenner
)


def _visible(ch: str) -> str:
    code = ord(ch)
    return f"\\x{code:02x}" if code < 0x100 else f"\\u{code:04x}"


def sanitize(text: str, *, newlines: bool = True) -> str:
    """Steuerzeichen sichtbar machen. ``newlines=True`` (beim Schreiben)
    ersetzt auch ``\n``/``\r`` — eine Meldung ist eine Zeile; Tracebacks
    hängt ``logging`` separat an und bleiben mehrzeilig."""
    text = text.replace("\r", "\\r")
    if newlines:
        text = text.replace("\n", "\\n")
    return _CONTROL.sub(lambda m: _visible(m.group(0)), text)


class _SafeFormatter(logging.Formatter):
    """Formatter, der die formatierte Meldung (Kopf + ``%(message)s``)
    säubert; ``exc_text``/``stack_info`` bleiben unangetastet (Python
    ``repr``-quotet Dateinamen in Ausnahmen selbst)."""

    def formatMessage(self, record: logging.LogRecord) -> str:  # noqa: N802
        return sanitize(super().formatMessage(record))


def setup_logging(log_dir: str | Path | None, filename: str, *,
                  console_level: int = logging.WARNING) -> Path | None:
    """Root-Logger auf INFO; Datei (falls ``log_dir``) + Konsole (Warnungen).
    Idempotent: ein zweiter Aufruf im selben Prozess tauscht nur die Datei.
    Liefert den Pfad der Logdatei (oder ``None``)."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        if getattr(handler, _MARK, False):
            root.removeHandler(handler)
            handler.close()
    formatter = _SafeFormatter(FORMAT)
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(console_level)
    console.setFormatter(formatter)
    setattr(console, _MARK, True)
    root.addHandler(console)
    # uvicorn-Zugriffslog bleibt Rauschen (ADR 0067) — nur Warnungen/Fehler.
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    if log_dir is None:
        return None
    path = Path(log_dir) / filename
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8",
        )
    except OSError as exc:  # Logordner nicht beschreibbar: Konsole reicht
        root.warning("Log file %s could not be created: %s", path, exc)
        return None
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    setattr(file_handler, _MARK, True)
    root.addHandler(file_handler)
    return path


# Zeilenkopf nach FORMAT: "2026-09-12 16:49:20,123 WARNING feral.web: …".
# Alles, was nicht so beginnt (Traceback-Zeilen, mehrzeilige Meldungen),
# ist eine Folgezeile und gehört zum Eintrag davor.
_HEAD = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} (\w+)\s")
_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def filter_level(lines: list[str], min_level: int) -> list[str]:
    """Nur Einträge ab ``min_level`` (logging-Zahl), Folgezeilen bleiben bei
    ihrem Eintrag. Zeilen ohne erkennbaren Kopf vor dem ersten Eintrag
    fallen weg (angeschnittener Dateianfang nach Rotation)."""
    keep = False
    out: list[str] = []
    for line in lines:
        m = _HEAD.match(line)
        if m:
            keep = _LEVELS.get(m.group(1), 0) >= min_level
        if keep:
            out.append(line)
    return out


def tail(path: str | Path, lines: int = 100, *, min_level: int | None = None) -> list[str]:
    """Die letzten ``lines`` Zeilen einer Logdatei (ohne Zeilenumbrüche);
    fehlende Datei → leere Liste. Mit ``min_level`` (logging-Zahl, z. B.
    ``logging.WARNING``) vorher gefiltert (Admin → Logs, ADR 0074): der
    Filter läuft über die ganze Datei, das Ergebnis ist der Schwanz davon."""
    p = Path(path)
    if not p.is_file() or lines <= 0:
        return []
    # Logdateien sind höchstens MAX_BYTES groß — komplett lesen ist billig.
    # splitlines() trennt auch an \x0b/\x0c/\x1c-\x1e/\x85/\u2028/\u2029 —
    # ältere Dateien (vor dem Formatter) sind damit schon zeilenweise
    # ungefährlich; ANSI und Bidi werden hier sichtbar gemacht.
    all_lines = [sanitize(line, newlines=False)
                 for line in p.read_text(encoding="utf-8", errors="replace").splitlines()]
    if min_level is not None:
        all_lines = filter_level(all_lines, min_level)
    return all_lines[-lines:]


def tolerant_console(streams=None) -> None:
    """Konsolen-Ausgabe darf den Server nie abstürzen lassen (#187): Unter
    Windows schreibt Python in eine UMGELEITETE Ausgabe (Datei, Pipe) im
    ANSI-Zeichensatz (cp1252), der z. B. die 🍓 der Startzeile nicht kennt;
    ohne das hier bricht ``print`` mit UnicodeEncodeError ab. Nicht
    darstellbare Zeichen werden ersetzt statt zu werfen."""
    for stream in (sys.stdout, sys.stderr) if streams is None else streams:
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="backslashreplace")
            except (ValueError, OSError):
                pass
