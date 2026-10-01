"""Musik-Angaben von Hand (ADR 0101, Issue #256), Teil der manuellen Schicht.

Titel, Interpret, Album-Interpret, Album, Titel- und CD-Nummer, Jahr und
Genre lassen sich je Song von Hand setzen. Die Wahrheit steht in
``manual_fields``; ``overlay`` legt sie beim Schreiben der Interpretation
über die Tag-Werte (Zeilen mit ``parser = 'manual'``), sodass alle
Lesestellen unverändert den geltenden Wert sehen. In die Dateien wird
nichts geschrieben (ADR 0041).

Rein bis auf die DB: keine Interpretation hier, das Neu-Interpretieren
nach einer Änderung macht ``interpret.reparse.reinterpret``.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import TYPE_CHECKING, Any, Iterable, Sequence

from ..messages import UserError

if TYPE_CHECKING:
    from ..interpret.types import Interpretation

PARSER = "manual"
PARSER_VERSION = 1
# Feste Feldliste in Anzeige-Reihenfolge (wie der Audio-Parser).
FIELDS = ("title", "artist", "album_artist", "album", "track", "disc", "year", "genre")
MULTI = frozenset({"artist", "genre"})       # mehrere Werte, Eingabe mit „;" getrennt
_NUMBERS = frozenset({"track", "disc"})
MAX_LENGTH = 300
MAX_VALUES = 20


def parse_input(field: str, text: str | None) -> list[str]:
    """Eingabe eines Feldes → geprüfte Werteliste; leer = Angabe von Hand
    entfernen. Mehrwertige Felder trennt das Semikolon. Ungültiges ⇒
    ``UserError`` (ADR 0101 Punkt 5)."""
    if field not in FIELDS:
        raise UserError("fieldUnknown", field=field)
    return check_values(field, (text or "").split(";") if field in MULTI else [text or ""])


def check_values(field: str, parts: Sequence[str]) -> list[str]:
    """Werte eines Feldes prüfen und bereinigen (Eingabe wie Austauschdatei):
    dieselben Längen- und Mengengrenzen für beide Wege (ADR 0101 Punkt 10)."""
    if field not in FIELDS:
        raise UserError("fieldUnknown", field=field)
    if field not in MULTI and len(parts) > 1:
        raise UserError("fieldTooMany", field=field, max=1)
    values: list[str] = []
    for part in parts:
        value = " ".join(part.split())           # getrimmt, Leerraum gefaltet
        if not value:
            continue
        if len(value) > MAX_LENGTH or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise UserError("fieldInvalid", field=field, value=value[:40])
        # Nur ASCII-Ziffern: ``isdigit`` allein ließe „²" oder Vollbreite durch.
        digits = value.isascii() and value.isdigit()
        if field in _NUMBERS:
            if not digits or len(value) > 6 or not 1 <= int(value) <= 9999:
                raise UserError("fieldInvalid", field=field, value=value[:40])
            value = str(int(value))
        elif field == "year":
            if not (digits and len(value) == 4
                    and 1000 <= int(value) <= date.today().year + 1):
                raise UserError("fieldInvalid", field=field, value=value[:40])
        if value not in values:
            values.append(value)
            # Grenze sofort prüfen: eine präparierte Datei mit hunderttausenden
            # Werten liefe sonst quadratisch (Release-QA 2026.10.1).
            if len(values) > MAX_VALUES:
                raise UserError("fieldTooMany", field=field, max=MAX_VALUES)
    return values


def parse_changes(changes: dict[str, Any]) -> dict[str, list[str]]:
    """Alle Felder einer Änderung prüfen (vor dem Schreiber)."""
    return {field: parse_input(field, text) for field, text in changes.items()}


def fields_of(conn: sqlite3.Connection, file_hash: str) -> dict[str, list[str]]:
    """Angaben von Hand eines Songs: ``{feld: [werte]}`` (nur gesetzte Felder)."""
    found: dict[str, list[str]] = {}
    for field, value in conn.execute(
        """SELECT field, value FROM manual_fields
            WHERE file_hash = ? ORDER BY field, ordinal""", (file_hash,),
    ):
        found.setdefault(field, []).append(value)
    return found


def year_of(conn: sqlite3.Connection, file_hash: str) -> int | None:
    """Das Jahr von Hand eines Songs (Datums-Kaskade, ADR 0101 Punkt 6)."""
    row = conn.execute(
        "SELECT value FROM manual_fields WHERE file_hash = ? AND field = 'year'",
        (file_hash,),
    ).fetchone()
    return int(row[0]) if row is not None and row[0].isdigit() else None


def overlay(
    conn: sqlite3.Connection, file_hash: str, interpretations: Sequence["Interpretation"],
) -> list["Interpretation"]:
    """Die Angaben von Hand über die Parser-Ergebnisse legen: Für jedes Feld
    mit einem Wert von Hand entfallen die Parser-Zeilen dieses Feldes, an
    ihre Stelle tritt eine Interpretation ``manual``. Idempotent (ein
    schon überdecktes Ergebnis bleibt gleich); ohne Angaben von Hand kommt
    die Eingabe unverändert zurück."""
    from ..interpret.types import InterpretedField, Interpretation   # Lazy: interpret → db

    manual = fields_of(conn, file_hash)
    base = [i for i in interpretations if i.parser != PARSER]
    if not manual:
        return base
    covered = [
        Interpretation(i.parser, i.parser_version,
                       [f for f in i.fields if f.field not in manual])
        for i in base
    ]
    covered.append(Interpretation(
        PARSER, PARSER_VERSION,
        [InterpretedField(f, v) for f in FIELDS for v in manual.get(f, [])],
    ))
    return covered


def set_fields(
    conn: sqlite3.Connection, hashes: Iterable[str], changes: dict[str, list[str]], *,
    source: str | None = None, now: str | None = None,
) -> list[str]:
    """Geprüfte Änderungen (``parse_changes``) für die Songs schreiben; eine
    leere Werteliste entfernt die Angabe von Hand. Unbekannte Hashes und
    alles, was kein Song ist, werden übersprungen. Läuft in der offenen Transaktion des Aufrufers und liefert
    die betroffenen Hashes; die Interpretation ist danach neu zu schreiben
    (``reparse.reinterpret``)."""
    from .store import now_iso
    ts = now or now_iso()
    touched: list[str] = []
    for file_hash in hashes:
        if conn.execute("SELECT 1 FROM items WHERE file_hash = ? AND media_kind = 'audio'",
                        (file_hash,)).fetchone() is None:
            continue
        for field, values in changes.items():
            conn.execute("DELETE FROM manual_fields WHERE file_hash = ? AND field = ?",
                         (file_hash, field))
            conn.executemany(
                """INSERT INTO manual_fields (file_hash, field, ordinal, value, source, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [(file_hash, field, n, v, source, ts) for n, v in enumerate(values)],
            )
        touched.append(file_hash)
    return touched


def state(conn: sqlite3.Connection, hashes: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Stand der acht Felder für eine Auswahl (Panel): je Feld der geltende
    Wert (mehrere mit ``"; "`` verbunden), ``mixed`` bei unterschiedlichen
    Werten in der Auswahl, ``manual`` wenn mindestens ein Song den Wert von
    Hand trägt, ``source`` = Herkunfts-Etikett eines importierten Wertes.
    Gezählt werden nur die Songs der Auswahl."""
    # Nur Songs zählen: in einer gemischten Auswahl (Song mit Cover neben
    # Bildern in der Galerie) hätte sonst jedes Feld „verschieden".
    songs: list[str] = []
    for start in range(0, len(hashes), 400):
        chunk = list(hashes[start:start + 400])
        holes = ",".join("?" * len(chunk))
        audio = {r[0] for r in conn.execute(
            f"SELECT file_hash FROM items WHERE file_hash IN ({holes}) AND media_kind = 'audio'",
            chunk)}
        songs += [h for h in chunk if h in audio]
    hashes = songs
    per_song: dict[str, dict[str, list[str]]] = {h: {} for h in hashes}
    manual: dict[str, bool] = {}
    source: dict[str, str] = {}
    marks = ",".join("?" * len(FIELDS))
    for start in range(0, len(hashes), 400):
        chunk = list(hashes[start:start + 400])
        holes = ",".join("?" * len(chunk))
        for file_hash, field, value, parser in conn.execute(
            f"""SELECT file_hash, field, value_text, parser FROM interpreted_metadata
                 WHERE file_hash IN ({holes}) AND field IN ({marks}) AND value_text != ''
                 ORDER BY file_hash, parser, ordinal""", (*chunk, *FIELDS),
        ):
            values = per_song[file_hash].setdefault(field, [])
            if value not in values and (field in MULTI or not values):
                values.append(value)
            if parser == PARSER:
                manual[field] = True
        for field, src in conn.execute(
            f"""SELECT field, source FROM manual_fields
                 WHERE file_hash IN ({holes}) AND source IS NOT NULL""", chunk,
        ):
            source.setdefault(field, src)
    result: dict[str, dict[str, Any]] = {}
    for field in FIELDS:
        seen = {"; ".join(per_song[h].get(field, [])) for h in hashes}
        mixed = len(seen) > 1
        result[field] = {
            "value": "" if mixed or not seen else next(iter(seen)),
            "mixed": mixed,
            "manual": manual.get(field, False),
            "source": source.get(field),
        }
    return result
