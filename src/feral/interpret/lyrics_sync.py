"""Songtext mit Zeiten (#234): Zeilen und Abschnitte aus drei Quellen.

Reine Funktionen für den ``audio``-Parser, jede Quelle → ``[(start_ms,
end_ms | None, text), …]`` nach Startzeit sortiert:

- **SRT** (Schicht 1 ``…:streamN.subtitle``): die Untertitel-Spur, in die
  Suno V6 den Songtext schreibt (``mov_text``, ffmpeg gibt sie als SRT aus).
  Hat Start UND Ende je Zeile.
- **ID3 ``SYLT``** (roher Frame): nur Zeitformat 2 (Millisekunden); Format 1
  (MPEG-Frames) braucht die Framedauer und wird übergangen.
- **LRC im Songtext-Tag** (``[mm:ss.xx]Zeile``): wie ihn viele Werkzeuge in
  ``USLT``/``LYRICS`` ablegen. Nur Startzeiten.

Reine Klammerzeilen (``[Chorus]``, ``[Verse 2]``) sind Abschnittsmarken, so
wie Suno sie in den Text schreibt (``sections``).

Die Eingabe ist fremd (Tags einer beliebigen Datei) und deshalb gedeckelt:
Textlänge, Zeilenzahl, Zeilenlänge und Zeitstempel je Zeile haben feste
Obergrenzen, und kein Ausdruck hier läuft auf langen Zeilen quadratisch.
Ein Songtext ist wenige Kilobyte groß; alles darüber wird abgeschnitten.
"""

from __future__ import annotations

import re
import struct

Line = tuple[int, int | None, str]

_SRT_TIME = re.compile(
    r"(\d{1,3}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,3}):(\d{2}):(\d{2})[,.](\d{1,3})")
_LRC_STAMP = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
# <font …>, {\an8} aus SRT/ASS. Die Klassen schließen auch das öffnende
# Zeichen aus: eine Zeile aus lauter "<" bleibt so linear.
_MARKUP = re.compile(r"<[^<>]*>|\{\\[^{}]*\}")
_SECTION = re.compile(r"^\[([^\[\]]{1,40})\]$")
_MIN_LINES = 2   # ein einzelner Zeitstempel ist noch kein getimter Text

MAX_TEXT = 512 * 1024   # Zeichen je Quelle; ein Songtext ist wenige KB
MAX_LINES = 2000        # Zeilen je Song
MAX_ROW = 500           # Zeichen je Zeile
MAX_STAMPS = 20         # Zeitstempel vor einer LRC-Zeile (wiederholter Refrain)


def _ms(h: str, m: str, s: str, frac: str | None) -> int:
    frac = (frac or "0").ljust(3, "0")[:3]
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(frac)


def parse_srt(text: str) -> list[Line]:
    """SRT-Blöcke → Zeilen (mehrzeilige Blöcke mit Leerzeichen verbunden)."""
    lines: list[Line] = []
    for block in re.split(r"\r?\n\s*\r?\n", text[:MAX_TEXT].strip()):
        if len(lines) >= MAX_LINES:
            break
        rows = [r[:MAX_ROW] for r in block.strip().splitlines()]
        for i, row in enumerate(rows):
            m = _SRT_TIME.search(row)
            if m:
                body = " ".join(_MARKUP.sub("", r).strip() for r in rows[i + 1:]).strip()
                if body:
                    start, end = _ms(*m.group(1, 2, 3, 4)), _ms(*m.group(5, 6, 7, 8))
                    lines.append((start, end if end > start else None, body[:MAX_ROW]))
                break
    return _finish(lines)


def parse_lrc(text: str) -> list[Line]:
    """LRC-Text → Zeilen; ohne mindestens zwei getimte Zeilen: leer (dann
    ist es ein normaler Songtext mit zufälliger Klammer)."""
    lines: list[Line] = []
    for row in text[:MAX_TEXT].splitlines():
        if len(lines) >= MAX_LINES:
            break
        row = row.strip()
        stamps: list[int] = []
        pos = 0
        while len(stamps) < MAX_STAMPS:
            m = _LRC_STAMP.match(row, pos)
            if not m:
                break
            stamps.append(_ms("0", m.group(1), m.group(2), m.group(3)))
            pos = m.end()
        if not stamps:
            continue
        body = _MARKUP.sub("", row[pos:pos + MAX_ROW]).strip()
        lines.extend((t, None, body) for t in stamps if body)
    return _finish(lines[:MAX_LINES]) if len(lines) >= _MIN_LINES else []


def strip_lrc(text: str) -> str:
    """LRC-Text ohne Zeitstempel und ohne Kopfzeilen (``[ar:…]``) — für das
    normale ``lyrics``-Feld."""
    out = []
    for row in text.splitlines():
        if re.match(r"^\s*\[[a-z]+:[^\[\]]*\]\s*$", row, re.I):
            continue
        out.append(_LRC_STAMP.sub("", row).strip())
    return "\n".join(out).strip()


def parse_sylt(payload: bytes) -> list[Line]:
    """Roher ID3-``SYLT``-Frame (ID3v2.3/2.4 §4.10): Kodierung, Sprache,
    Zeitformat, Inhaltstyp, Beschreibung, dann je Eintrag Text + 4-Byte-Zeit."""
    if len(payload) < 6 or payload[4] != 2:   # nur Millisekunden
        return []
    enc = payload[0]
    wide = enc in (1, 2)
    term = b"\x00\x00" if wide else b"\x00"
    codec = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}.get(enc)
    if codec is None:
        return []
    pos = _after_terminator(payload, 6, term, wide)   # Beschreibung überspringen
    lines: list[Line] = []
    while pos is not None and pos < len(payload) and len(lines) < MAX_LINES:
        end = _find_terminator(payload, pos, term, wide)
        if end is None or end + len(term) + 4 > len(payload):
            break
        raw = payload[pos:end]
        (stamp,) = struct.unpack(">I", payload[end + len(term):end + len(term) + 4])
        body = raw[:MAX_ROW * 4].decode(codec, errors="replace").lstrip("﻿").strip()
        if body:
            lines.append((stamp, None, body[:MAX_ROW]))
        pos = end + len(term) + 4
    return _finish(lines)


def _find_terminator(data: bytes, start: int, term: bytes, wide: bool) -> int | None:
    pos = start
    while True:
        at = data.find(term, pos)
        if at < 0:
            return None
        if not wide or (at - start) % 2 == 0:   # UTF-16: nur auf Zeichengrenzen
            return at
        pos = at + 1


def _after_terminator(data: bytes, start: int, term: bytes, wide: bool) -> int | None:
    at = _find_terminator(data, start, term, wide)
    return None if at is None else at + len(term)


def _finish(lines: list[Line]) -> list[Line]:
    return sorted(lines, key=lambda line: line[0])


# Ungefähre Singdauer einer Zeile, wie die Anzeige sie nutzt (lyrics.js:
# SHOW_BASE_MS/SHOW_PER_WORD_MS) — Sunos Endzeiten reichen oft bis zur
# nächsten gesungenen Zeile.
_SING_BASE_MS = 2500
_SING_PER_WORD_MS = 700


def _sung_until(start: int, end: int | None, text: str) -> int:
    cap = start + _SING_BASE_MS + _SING_PER_WORD_MS * len(text.split())
    return min(end, cap) if end is not None else cap


def sections(lines: list[Line]) -> list[tuple[int, str]]:
    """Abschnittsmarken: reine Klammerzeilen → ``(start_ms, 'Chorus')``.

    Instrumentale Abschnitte (Solo, Lead-Gitarre, Intro): Suno gibt einer
    Marke die Zeit des nächsten gesungenen Worts. Ohne Gesang bis zur
    nächsten Marke steht sie damit am ENDE des Solos, auf derselben Stelle
    wie der Abschnitt danach. Geschätzt beginnt sie stattdessen, wo die
    letzte gesungene Zeile davor endet (ganz am Anfang: bei 0); mehrere
    solche Marken hintereinander teilen sich die Lücke gleichmäßig."""
    marks = [(i, s, m.group(1).strip()) for i, (s, _e, t) in enumerate(lines)
             if (m := _SECTION.match(t))]
    out = [(s, name) for _i, s, name in marks]
    sung = [not _SECTION.match(t) for _s, _e, t in lines]
    last_sung: list[int | None] = []   # letzte gesungene Zeile VOR Index i
    seen: int | None = None
    for i, is_sung in enumerate(sung):
        last_sung.append(seen)
        if is_sung:
            seen = i
    k = 0
    while k < len(marks):
        # Lauf instrumentaler Marken: keine gesungene Zeile bis zur nächsten Marke.
        run = []
        while k < len(marks):
            i = marks[k][0]
            stop = marks[k + 1][0] if k + 1 < len(marks) else len(lines)
            if any(sung[i + 1:stop]) or k + 1 >= len(marks):
                break
            run.append(k)
            k += 1
        if run:
            before = last_sung[marks[run[0]][0]]
            gap_from = _sung_until(*lines[before]) if before is not None else 0
            gap_to = marks[run[-1] + 1][1]
            if gap_from < gap_to:
                step = (gap_to - gap_from) / len(run)
                for n, idx in enumerate(run):
                    out[idx] = (int(gap_from + n * step), out[idx][1])
            continue
        k += 1
    return out


def plain_text(lines: list[Line]) -> str:
    """Getimte Zeilen als normaler Songtext (ein Rückfall für ``lyrics``)."""
    return "\n".join(text for _s, _e, text in lines)
