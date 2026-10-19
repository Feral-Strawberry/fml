"""Songtext von Hand (ADR 0106, Issue #285), Teil der manuellen Schicht.

Ein Dokument je Song in ``manual_lyrics``: die Zeilen im Format von
``lyrics_synced`` (``[[start_ms|null, end_ms|null, "Zeile"], …]``), die
Startzeit darf fehlen, Leerzeilen trennen Strophen. Das Dokument ersetzt den
Songtext aus der Datei als Ganzes; ``manual_fields.overlay`` legt seine
Projektion (``projection``) beim Schreiben der Interpretation über die
Parser-Zeilen ``lyrics``, ``lyrics_synced`` und ``song_sections``. In die
Dateien wird nichts geschrieben (ADR 0041).

Rein bis auf die DB: das Neu-Interpretieren nach einer Änderung macht
``interpret.reparse.reinterpret``.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from ..messages import UserError
from .manual_fields import PARSER

FIELDS = ("lyrics", "lyrics_synced", "song_sections")
MAX_LINES = 2000        # wie beim Lesen (interpret/lyrics_sync.py)
MAX_ROW = 500
_SECTION = re.compile(r"^\[([^\[\]]{1,40})\]$")   # Abschnittsmarke, wie lyrics_sync
_DAY_MS = 24 * 3600 * 1000   # Obergrenze ohne bekannte Songlänge
_SLACK_MS = 1000             # Sunos letzte Zeile darf knapp hinter dem Ende liegen

Line = list[Any]   # [start_ms | None, end_ms | None, "Zeile"]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _time(value: Any, limit: int, n: int) -> int | None:
    """Zeit einer Zeile prüfen: ganze Millisekunden von 0 bis ``limit``."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UserError("lyricsInvalid", line=n)
    if isinstance(value, float) and not value.is_integer():
        raise UserError("lyricsInvalid", line=n)
    ms = int(value)
    if ms < 0 or ms > limit:
        raise UserError("lyricsInvalid", line=n)
    return ms


def check_lines(raw: Any, duration: float | None = None) -> list[Line]:
    """Zeilen eines Songtexts prüfen und bereinigen (Eingabe und künftig
    Austausch, ADR 0106 Punkt 5): Leerraum gefaltet, keine Steuerzeichen,
    höchstens ``MAX_LINES`` Zeilen zu ``MAX_ROW`` Zeichen, Zeiten zwischen 0
    und der Songlänge, Startzeiten nicht rückwärts. Leerzeilen am Rand
    fallen weg, mehrere hintereinander werden eine; sie tragen keine Zeit.
    Eine Endzeit vor dem Start oder hinter dem Song fällt weg (dann gilt
    die Singdauer-Regel aus ADR 0099). Leeres Ergebnis = Fassung von Hand
    entfernen. Ungültiges ⇒ ``UserError``."""
    if not isinstance(raw, list):
        raise UserError("lyricsInvalid", line=0)
    if len(raw) > MAX_LINES:
        raise UserError("lyricsTooLong", max=MAX_LINES)
    limit = int(duration * 1000) + _SLACK_MS if duration and duration > 0 else _DAY_MS
    out: list[Line] = []
    last = -1
    for n, row in enumerate(raw, 1):
        if not (isinstance(row, (list, tuple)) and len(row) == 3 and isinstance(row[2], str)):
            raise UserError("lyricsInvalid", line=n)
        text = " ".join(row[2].split())
        if len(text) > MAX_ROW or any(ord(c) < 32 or ord(c) == 127 for c in text):
            raise UserError("lyricsInvalid", line=n)
        if not text:
            if out and out[-1][2]:
                out.append([None, None, ""])
            continue
        start = _time(row[0], limit, n)
        try:
            end = _time(row[1], limit, n)
        except UserError:
            end = None
        if end is not None and (start is None or end < start):
            end = None
        if start is not None:
            if start < last:
                raise UserError("lyricsOrder", line=n)
            last = start
        out.append([start, end, text])
    while out and not out[-1][2]:
        out.pop()
    return out


def projection(lines: list[Line]) -> dict[str, list[str]]:
    """Die Felder, die ein Songtext von Hand in Schicht 2 schreibt
    (ADR 0106 Punkt 3): ``lyrics`` immer; ``lyrics_synced`` und
    ``song_sections`` nur, wenn jede Textzeile eine Startzeit hat. Die
    Klammerzeilen gelten wörtlich als Abschnitte, ohne Solo-Schätzung."""
    if not lines:
        return {}
    out = {"lyrics": ["\n".join(text for _s, _e, text in lines)]}
    sung = [line for line in lines if line[2]]
    if sung and all(line[0] is not None for line in sung):
        out["lyrics_synced"] = [_json(sung)]
        marks = [[s, m.group(1).strip()] for s, _e, t in sung if (m := _SECTION.match(t))]
        if marks:
            out["song_sections"] = [_json(marks)]
    return out


def lines_of(conn: sqlite3.Connection, file_hash: str) -> tuple[list[Line], str | None] | None:
    """Songtext von Hand eines Songs: ``(zeilen, herkunft)``, sonst ``None``."""
    row = conn.execute("SELECT lines, source FROM manual_lyrics WHERE file_hash = ?",
                       (file_hash,)).fetchone()
    if row is None:
        return None
    try:
        lines = json.loads(row[0])
    except ValueError:
        return None
    return (lines, row[1]) if isinstance(lines, list) else None


def projection_of(conn: sqlite3.Connection, file_hash: str) -> dict[str, list[str]]:
    """Projektion des Songtexts von Hand; leer ohne Fassung von Hand."""
    found = lines_of(conn, file_hash)
    return projection(found[0]) if found else {}


def _from_file(conn: sqlite3.Connection, file_hash: str) -> list[Line]:
    """Der geltende Songtext aus der Datei als Zeilen (Vorlage beim ersten
    Bearbeiten). Getimt: die Zeilen, die Klammerzeilen an ihrer geschätzten
    Stelle (``song_sections``), damit die Schätzung einmal festgeschrieben
    wird. Sonst der Songtext-Tag Zeile für Zeile, ohne Zeiten."""
    def first(field: str) -> str | None:
        row = conn.execute(
            """SELECT value_text FROM interpreted_metadata
                WHERE file_hash = ? AND field = ? AND parser != ? AND value_text != ''
                ORDER BY id LIMIT 1""", (file_hash, field, PARSER)).fetchone()
        return row[0] if row else None

    def loads(text: str | None) -> list[Any]:
        try:
            value = json.loads(text) if text else []
        except ValueError:
            return []
        return value if isinstance(value, list) else []

    synced = loads(first("lyrics_synced"))
    if synced:
        lines = [list(line) for line in synced]
        marks = [i for i, line in enumerate(lines) if _SECTION.match(line[2])]
        sections = loads(first("song_sections"))
        if len(marks) == len(sections):
            moved = [list(line) for line in lines]
            for i, (ms, _name) in zip(marks, sections):
                moved[i][0] = ms
            starts = [line[0] for line in moved]
            if starts == sorted(starts):   # Schätzung hält die Reihenfolge, sonst nicht anwenden
                lines = moved
        return lines
    text = first("lyrics")
    if not text:
        return []
    out: list[Line] = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if line or (out and out[-1][2]):
            out.append([None, None, line])
    while out and not out[-1][2]:
        out.pop()
    return out


def editable(conn: sqlite3.Connection, file_hash: str) -> dict[str, Any]:
    """Stand für die Ansicht „Songtext bearbeiten": die Fassung von Hand,
    sonst der Songtext aus der Datei (leer, wenn es keinen gibt)."""
    duration = duration_of(conn, file_hash)
    found = lines_of(conn, file_hash)
    if found is not None:
        return {"lines": found[0], "manual": True, "source": found[1], "duration": duration}
    return {"lines": _from_file(conn, file_hash), "manual": False, "source": None,
            "duration": duration}


def duration_of(conn: sqlite3.Connection, file_hash: str) -> float | None:
    row = conn.execute("SELECT duration FROM items WHERE file_hash = ?", (file_hash,)).fetchone()
    return row[0] if row else None


def is_song(conn: sqlite3.Connection, file_hash: str) -> bool:
    return conn.execute("SELECT 1 FROM items WHERE file_hash = ? AND media_kind = 'audio'",
                        (file_hash,)).fetchone() is not None


def set_lyrics(
    conn: sqlite3.Connection, file_hash: str, lines: list[Line], *,
    source: str | None = None, now: str | None = None,
) -> bool:
    """Geprüfte Zeilen (``check_lines``) als Fassung von Hand schreiben; leere
    Zeilen entfernen sie (der Songtext aus der Datei gilt wieder). Nur Songs;
    ``False``, wenn es keiner ist. Läuft in der offenen Transaktion des
    Aufrufers; die Interpretation ist danach neu zu schreiben
    (``reparse.reinterpret``)."""
    from .store import now_iso
    if not is_song(conn, file_hash):
        return False
    conn.execute("DELETE FROM manual_lyrics WHERE file_hash = ?", (file_hash,))
    if lines:
        conn.execute(
            "INSERT INTO manual_lyrics (file_hash, lines, source, updated_at) VALUES (?, ?, ?, ?)",
            (file_hash, _json(lines), source, now or now_iso()),
        )
    return True
