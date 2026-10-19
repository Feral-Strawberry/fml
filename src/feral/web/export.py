"""Kopie-Export in einen Export-Ordner (ADR 0103).

Der dritte Ort, an dem fml Dateien schreibt (neben Import und
Rausverschieben, ADR 0041): Kopien einzelner Medien oder eines ganzen
Stapels landen in ``<root>/<JJJJ-MM-TT>[ <Paketname>]/``. Der Export ist
IMMER Kopie: Originale werden nur gelesen, an Library und Katalog ändert
sich nichts (kein Zustand am Item, keine Tabelle, kein Protokoll).

Je Datei: erster brauchbarer Fundort (Rangfolge wie überall, ADR 0062
Nachtrag; für den PNG-Export eines umgerechneten Formats reicht auch das
Bild im Vorschau-Cache) → Kopie unter vorläufigem Namen → Hash der Kopie gegen den
Item-Hash (ADR 0006) → umbenennen. Liegt am Ziel schon eine Datei des
Namens, entscheidet der Inhalt: bitgleich = „schon da", sonst
``name (1).ext`` wie im Dateimanager.

Zwei Ausnahmen vom bitgleichen Original: Formate, die fml selbst nur
über ein gerechnetes Bild anzeigt (``RENDERED_CONTAINERS``), gehen als PNG
raus, auf Wunsch als Original. Songs mit Angaben von Hand (Angaben,
Songtext, Cover) bekommen diese auf Wunsch in die Kopie geschrieben
(ADR 0107, ``feral.tagwrite``); geprüft wird dann der Ton statt des
Item-Hashes, und „schon da" gibt es für sie nicht.

Rein auf Verbindungs-Ebene (keine Engine-Kenntnis); die Aufgabe steht in
``tasks.py``, die Endpunkte in ``app.py``.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sqlite3
import stat
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .. import tagwrite
from ..db import manual_fields, manual_lyrics
from ..hashing import hash_file
from ..messages import msg
from ..extract.jxr import Tone
from ..thumbs import cover_jpeg, preview_cache_file, preview_variant, write_preview
from . import filters, library

log = logging.getLogger(__name__)

LAYOUTS = ("flat", "date")          # flach | Jahr/Monat/Tag
CONVERTED = ("png", "original")     # umgerechnete Formate: PNG | Rohdatei
NO_DATE_DIR = "ohne-datum"

# Container, die fml nur über ein gerechnetes Bild anzeigt (Punkt 8):
# Photo CD (ADR 0092) und JXR (ADR 0104).
RENDERED_CONTAINERS = frozenset({"pcd", "jxr"})

_CHUNK = 500
_PART = ".part"


def temp_file(directory: Path, name: str) -> Path:
    """Zwischendatei für ``name`` in ``directory``: eindeutig und exklusiv
    angelegt, damit eine vorhandene Datei gleichen Namens nie überschrieben
    (und danach weggeräumt) wird."""
    fd, path = tempfile.mkstemp(dir=directory, prefix=f".{name}.", suffix=_PART)
    os.close(fd)
    return Path(path)
# Unter Windows verbotene Zeichen samt Pfadtrennern und Steuerzeichen.
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_NAME_MAX = 80
_DATE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?")


class NoSpace(Exception):
    """Der freie Platz am Ziel reicht nicht für die Summe der Dateigrößen."""

    def __init__(self, need: int, free: int) -> None:
        super().__init__(f"need {need} bytes, {free} free")
        self.need, self.free = need, free


@dataclass
class ExportReport:
    """Zusammenfassung eines Export-Laufs (für last_result und Tests)."""

    kopiert: int = 0
    schon_da: int = 0             # bitgleich vorhanden, übersprungen
    nicht_erreichbar: int = 0     # kein Fundort erreichbar (offline)
    fehler: int = 0
    mit_angaben: int = 0          # davon mit Angaben von Hand beschriftet (ADR 0107)
    ohne_angaben: int = 0         # Angaben von Hand da, Format nicht beschriftbar
    erster_fehler: str = ""       # Datei + Grund, damit das Ergebnis ihn nennt
    erster_offline: dict | None = None   # Meldung: warum der erste nicht erreichbar war

    @property
    def done(self) -> int:
        return self.kopiert + self.schon_da + self.nicht_erreichbar + self.fehler


# -- Export-Ordner ------------------------------------------------------------------

def safe_package_name(name: str | None) -> str:
    """Paketname auf im Dateisystem erlaubte Zeichen beschränken (Punkt 7):
    Verbotenes (auch das unter Windows Verbotene, Pfadtrenner) wird zum
    Leerzeichen, Leerraum zusammengezogen, Punkte und Leerzeichen am Rand
    fallen weg (Windows schneidet sie sonst still ab)."""
    text = " ".join(_FORBIDDEN.sub(" ", name or "").split())
    return text.strip(" .")[:_NAME_MAX].rstrip(" .")


def package_dir(root: str | Path, name: str | None, today: date) -> Path:
    """``<root>/<JJJJ-MM-TT>[ <Paketname>]`` — das Datum ist der Tag des
    Exports (Punkt 6)."""
    package = safe_package_name(name)
    return Path(root) / (f"{today:%Y-%m-%d} {package}" if package else f"{today:%Y-%m-%d}")


def _parts(path: str | Path) -> tuple[str, ...]:
    return tuple(p.casefold() for p in Path(path).expanduser().resolve().parts)


def _nested(a: str | Path, b: str | Path) -> bool:
    """Liegt einer der beiden Ordner im anderen (oder sind sie gleich)?
    Ohne Groß/Klein-Unterschied: lieber einmal zu streng als ein Export,
    den fml wieder einliest."""
    pa, pb = _parts(a), _parts(b)
    n = min(len(pa), len(pb))
    return pa[:n] == pb[:n]


def root_conflict(
    root: str | Path, *, library_root: str | None, watch_roots: list[str],
    cache_dirs: list[str],
) -> str | None:
    """Womit der Export-Ordner kollidiert (Punkt 3): ``"library"``,
    ``"watch"`` oder ``"cache"`` — er darf in keinem davon liegen und
    keiner davon in ihm. ``None`` = frei."""
    if library_root and _nested(root, library_root):
        return "library"
    if any(w and w.strip() and _nested(root, w) for w in watch_roots):
        return "watch"
    if any(c and _nested(root, c) for c in cache_dirs):
        return "cache"
    return None


def holds_originals(conn: sqlite3.Connection, root: str | Path) -> bool:
    """Liegt im Export-Ordner schon ein katalogisierter Fundort (Punkt 4:
    Kopien nicht an den Ort der Originale)? Etwa ein einmal im
    Übersichtsmodus katalogisierter Ordner. Pfade wie gespeichert, ohne
    ``resolve()`` (wie ``filters.library_like_prefix``), dazu aufgelöst."""
    raw = str(Path(str(root)).expanduser())
    prefixes = {p.replace("\\", "/").rstrip("/") for p in (raw, str(Path(raw).resolve()))}
    for prefix in filter(None, prefixes):
        if conn.execute(
                f"SELECT 1 FROM file_locations WHERE {filters.NORM_PATH} LIKE ? ESCAPE '\\' "
                "LIMIT 1", (f"{filters._escape_like(prefix)}/%",)).fetchone():
            return True
    return False


# -- Umfang -------------------------------------------------------------------------

def scope_hashes(
    conn: sqlite3.Connection, *, hashes: list[str] | None = None,
    filter_expr: str | None = None, view_preds: tuple[filters.Predicate, ...] = (),
) -> list[str]:
    """Die Items des Scopes, wie bei den Sammel-Aktionen (ADR 0040):
    ``hashes`` (Auswahl, Reihenfolge bleibt) gewinnt über ``filter_expr``
    (Suchergebnis; leer = alle) samt Grundbereich der Ansicht."""
    if hashes is not None:
        known: set[str] = set()
        for start in range(0, len(hashes), _CHUNK):
            chunk = hashes[start:start + _CHUNK]
            marks = ",".join("?" * len(chunk))
            known.update(r[0] for r in conn.execute(
                f"SELECT file_hash FROM items WHERE file_hash IN ({marks})", chunk))
        return [h for h in dict.fromkeys(hashes) if h in known]
    predicates = list(view_preds)
    if filter_expr and filter_expr.strip():
        predicates += filters.parse(filter_expr)
    fragment, params = filters.build_where(predicates)
    where = f"WHERE ({fragment})" if fragment else ""
    return [r[0] for r in conn.execute(
        f"SELECT i.file_hash FROM items i {where} ORDER BY i.media_date, i.file_hash",
        params)]


# Ein Song hat Angaben von Hand, die in die Kopie können (ADR 0107).
_HAS_MANUAL = """media_kind = 'audio' AND (
    EXISTS (SELECT 1 FROM manual_fields f WHERE f.file_hash = items.file_hash)
    OR EXISTS (SELECT 1 FROM manual_lyrics l WHERE l.file_hash = items.file_hash)
    OR EXISTS (SELECT 1 FROM covers c WHERE c.file_hash = items.file_hash))"""


def plan(conn: sqlite3.Connection, hashes: list[str]) -> dict[str, int]:
    """Zahlen für Dialog und Platzprüfung: ``count``, ``bytes`` (Summe der
    Dateigrößen), ``converted`` (Items in einem umgerechneten Format) und
    ``tagged`` (Songs mit Angaben von Hand, ADR 0107)."""
    count = total = converted = tagged = 0
    rendered = ",".join(f"'{c}'" for c in sorted(RENDERED_CONTAINERS))
    for start in range(0, len(hashes), _CHUNK):
        chunk = hashes[start:start + _CHUNK]
        marks = ",".join("?" * len(chunk))
        row = conn.execute(
            f"""SELECT COUNT(*), COALESCE(SUM(file_size), 0),
                       COALESCE(SUM(container IN ({rendered})), 0),
                       COALESCE(SUM({_HAS_MANUAL}), 0)
                  FROM items WHERE file_hash IN ({marks})""", chunk).fetchone()
        count, total = count + row[0], total + row[1]
        converted, tagged = converted + row[2], tagged + row[3]
    return {"count": count, "bytes": total, "converted": converted, "tagged": tagged}


# -- Kopieren -----------------------------------------------------------------------

def _free_name(
    directory: Path, name: str, same: Callable[[Path], bool]
) -> Path | None:
    """Erster freier Name (``name``, ``name (1).ext``, …) in ``directory``.
    Liegt unter einem Kandidaten schon derselbe Inhalt (``same``), ist die
    Datei „schon da" → ``None``."""
    stem, suffix = Path(name).stem, Path(name).suffix
    for n in range(10_000):
        candidate = directory / (name if n == 0 else f"{stem} ({n}){suffix}")
        if not candidate.exists():
            return candidate
        if same(candidate):
            return None
    raise RuntimeError(f"no free name for {name!r} in {directory}")


def _has_hash(path: Path, file_hash: str, size: int | None = None) -> bool:
    try:
        if size is not None and path.stat().st_size != size:
            return False       # andere Größe = anderer Inhalt, ohne Hashen
        return hash_file(path) == file_hash
    except OSError:
        return False


def _date_dir(target: Path, media_date: str | None) -> Path:
    """Jahr/Monat/Tag wie die Library (ADR 0019), so tief wie das Datum des
    Items reicht (ein Datum von Hand kann nur ein Jahr sein, ADR 0096)."""
    m = _DATE.match(media_date or "")
    if not m:
        return target / NO_DATE_DIR
    return target.joinpath(*[part for part in m.groups() if part])


def _copy_original(source: Path, directory: Path, file_hash: str, size: int | None) -> bool:
    """Original bitgleich nach ``directory`` kopieren; ``False`` = schon da."""
    destination = _free_name(directory, source.name,
                             lambda p: _has_hash(p, file_hash, size))
    if destination is None:
        return False
    temp = temp_file(directory, destination.name)
    try:
        shutil.copy2(source, temp)
        # Schreibschutz der Quelle (von CD kopiert) nicht mitnehmen: eine
        # Kopie soll sich weiterverarbeiten und unter Windows auch wieder
        # wegräumen lassen. Inhalt und Zeitstempel bleiben.
        temp.chmod(temp.stat().st_mode | stat.S_IWRITE)
        if hash_file(temp) != file_hash:
            raise OSError("copy does not match the item hash")
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)
    return True


def _cached_png(preview_cache: str | Path | None, file_hash: str,
                variant: str = "") -> Path | None:
    """Das schon gerechnete Anzeigebild im Vorschau-Cache, falls vorhanden."""
    if not preview_cache:
        return None
    cached = preview_cache_file(preview_cache, file_hash, variant)
    return cached if cached.is_file() else None


def _copy_rendered(
    source: Path | None, stem: str, directory: Path, file_hash: str,
    preview_cache: str | Path | None, variant: str = "", tone: Tone = Tone(),
) -> bool:
    """Umgerechnete Fassung als PNG nach ``directory`` (Punkt 8): aus dem
    Vorschau-Cache, sonst frisch aus ``source`` gerechnet. Mit dem Bild im
    Cache braucht es die Quelle nicht (``source`` darf dann ``None`` sein).
    ``False`` = schon da."""
    temp = temp_file(directory, f"{file_hash}.png")
    try:
        cached = _cached_png(preview_cache, file_hash, variant)
        if cached is not None:
            shutil.copyfile(cached, temp)
        else:
            reason = write_preview(source, temp, tone=tone, file_hash=file_hash)
            if reason:
                raise OSError(reason)
        rendered_hash = hash_file(temp)
        destination = _free_name(directory, stem + ".png",
                                 lambda p: _has_hash(p, rendered_hash))
        if destination is None:
            return False
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)
    return True


def song_tags(
    conn: sqlite3.Connection, file_hash: str, *,
    roots: tuple[str | None, list[str]] = (None, []), tone: Tone = Tone(),
) -> tagwrite.Tags:
    """Was von Hand in die Kopie eines Songs soll (ADR 0107 Punkt 2): Angaben,
    Songtext und das Cover als fertiges JPEG. Gelesen wird aus der manuellen
    Schicht selbst (dort stehen Werte getrennt und alle Zeiten). Ein gerade
    nicht erreichbares Coverbild fehlt dann nur in der Kopie."""
    fields = {name: values for name, values in manual_fields.fields_of(conn, file_hash).items()
              if name in manual_fields.FIELDS and values}
    found = manual_lyrics.lines_of(conn, file_hash)
    row = conn.execute(
        """SELECT i.duration, c.cover_hash, v.file_size FROM items i
             LEFT JOIN covers c ON c.file_hash = i.file_hash
             LEFT JOIN items v ON v.file_hash = c.cover_hash
            WHERE i.file_hash = ?""", (file_hash,)).fetchone()
    duration, cover_hash, cover_size = row if row is not None else (None, None, None)
    cover = None
    if cover_hash:
        usable = [loc for loc in library.ordered_locations(
            conn, cover_hash, cover_size, roots=roots) if loc["usable"]]
        if usable:
            cover, reason = cover_jpeg(usable[0]["path"], tone=tone)
            if cover is None:
                log.warning("export: cover %s: %s", cover_hash[:12], reason)
        else:
            log.warning("export: cover %s unreachable, copy of %s without cover",
                        cover_hash[:12], file_hash[:12])
    return tagwrite.Tags(fields=fields, lyrics=found[0] if found and found[0] else None,
                         cover=cover,
                         duration_ms=int(duration * 1000) if duration else None)


def _copy_tagged(source: Path, directory: Path, file_hash: str, container: str,
                 tags: tagwrite.Tags) -> None:
    """Kopie mit Angaben von Hand nach ``directory`` (ADR 0107): immer unter
    einem freien Namen (kein „schon da"), erst nach bestandener Prüfung
    umbenannt. ``tagwrite.Unsupported`` kommt, bevor etwas liegt."""
    destination = _free_name(directory, source.name, lambda _p: False)
    temp = temp_file(directory, destination.name)
    try:
        dropped = tagwrite.write(container, source, temp, tags, file_hash)
        temp.replace(destination)
    finally:
        temp.unlink(missing_ok=True)
    if dropped:
        log.warning("export: tags dropped by ffmpeg in %s: %s", destination.name,
                    ", ".join(dropped))


def _why_unreachable(
    locations: list[dict[str, Any]], file_size: int | None
) -> tuple[dict[str, Any], str]:
    """Warum kein Fundort brauchbar war: Meldung fürs Ergebnis (erster
    Fundort der Rangfolge) und eine Zeile mit ALLEN Fundorten fürs Log."""
    if not locations:
        return msg("exportWhyNoLocation"), "no location in the catalog"
    lines, first = [], None
    for loc in locations:
        if not loc["exists"]:
            why, text = msg("exportWhyMissing", path=loc["path"]), "missing"
        else:
            try:
                actual = Path(loc["path"]).stat().st_size
            except OSError:
                actual = -1
            why = msg("exportWhyForeign", path=loc["path"], size=actual, expected=file_size)
            text = f"other content ({actual} bytes, catalog says {file_size})"
        first = first or why
        lines.append(f"{loc['path']}: {text}")
    return first, " | ".join(lines)


def export_items(
    conn: sqlite3.Connection,
    hashes: list[str],
    *,
    target: str | Path,
    layout: str = "flat",
    converted: str = "png",
    preview_cache: str | Path | None = None,
    tone: Tone = Tone(),
    roots: tuple[str | None, list[str]] = (None, []),
    tags: bool = False,
    report: ExportReport | None = None,
    check_space: bool = True,
    progress: Callable[[int, int, str, ExportReport], None] | None = None,
) -> ExportReport:
    """``hashes`` als Kopie nach ``target`` (der fertige Paketordner) legen.

    ``progress(index, total, name, report)`` kommt VOR jeder Datei; wirft
    der Aufrufer dort (Halt an der Dateigrenze, ADR 0093), ist ``index - 1``
    die Zahl der erledigten. ``report`` nimmt die Zähler eines früheren
    Teillaufs mit. ``check_space`` prüft vor dem Start den freien Platz
    gegen die Summe der Dateigrößen (``NoSpace``). ``tags``: Angaben von
    Hand in die Kopien der Songs schreiben (ADR 0107).
    """
    target = Path(target)
    report = report if report is not None else ExportReport()
    target.mkdir(parents=True, exist_ok=True)
    if check_space:
        need, free = plan(conn, hashes)["bytes"], shutil.disk_usage(target).free
        if need > free:
            raise NoSpace(need, free)

    total = len(hashes)
    for index, file_hash in enumerate(hashes, start=1):
        row = conn.execute(
            "SELECT file_size, container, media_date, media_kind FROM items"
            " WHERE file_hash = ?",
            (file_hash,)).fetchone()
        locations = [] if row is None else library.ordered_locations(
            conn, file_hash, row[0], roots=roots)
        usable = [loc for loc in locations if loc["usable"]]
        source = Path(usable[0]["path"]) if usable else None
        # Der Name kommt vom Fundort, auch wenn dort gerade nichts liegt.
        named = source or (Path(locations[0]["path"]) if locations else Path(file_hash[:12]))
        as_png = (row is not None and converted == "png"
                  and row[1] in RENDERED_CONTAINERS)
        variant = preview_variant(row[1], tone) if as_png else ""
        if progress is not None:
            progress(index, total, named.name, report)
        # Das gerechnete Bild im Cache reicht für den PNG-Export: die
        # Quelle darf dann fehlen (ADR 0103, Umsetzung).
        if source is None and not (as_png and _cached_png(preview_cache, file_hash, variant)):
            report.nicht_erreichbar += 1
            why, line = _why_unreachable(locations, row[0] if row is not None else None)
            report.erster_offline = report.erster_offline or why
            log.warning("export: unreachable %s: %s", file_hash[:12], line)
            continue
        try:
            directory = _date_dir(target, row[2]) if layout == "date" else target
            directory.mkdir(parents=True, exist_ok=True)
            song = (tags and row[3] == "audio"
                    and song_tags(conn, file_hash, roots=roots, tone=tone)) or None
            if as_png:
                copied = _copy_rendered(source, named.stem, directory, file_hash,
                                        preview_cache, variant, tone)
            elif song and row[1] in tagwrite.WRITABLE and _tagged(
                    source, directory, file_hash, row[1], song):
                report.mit_angaben += 1
                copied = True
            else:
                report.ohne_angaben += bool(song)
                copied = _copy_original(source, directory, file_hash, row[0])
        except Exception as exc:  # Einzelfehler töten den Lauf nicht
            report.fehler += 1
            if not report.erster_fehler:
                report.erster_fehler = (
                    f"{named.name}: {exc.__class__.__name__}: {exc}")[:300]
            log.warning("export: %s: %s: %s", named, exc.__class__.__name__, exc)
            continue
        if copied:
            report.kopiert += 1
        else:
            report.schon_da += 1
    return report


def _tagged(source: Path, directory: Path, file_hash: str, container: str,
            tags: tagwrite.Tags) -> bool:
    """Beschriftete Kopie; ``False`` = Datei nicht beschriftbar (ID3v2.2,
    gestapelte Tags), dann geht sie bitgleich raus."""
    try:
        _copy_tagged(source, directory, file_hash, container, tags)
    except tagwrite.Unsupported as exc:
        log.info("export: %s copied without manual data: %s", source.name, exc)
        return False
    return True


def counts(report: ExportReport) -> dict[str, Any]:
    """Zähler als JSON-taugliches Dict (Fortsetzung nach einem Halt)."""
    return {"kopiert": report.kopiert, "schon_da": report.schon_da,
            "nicht_erreichbar": report.nicht_erreichbar, "fehler": report.fehler,
            "mit_angaben": report.mit_angaben, "ohne_angaben": report.ohne_angaben,
            "erster_fehler": report.erster_fehler,
            "erster_offline": report.erster_offline}
