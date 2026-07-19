"""Import-Kern (Stufe 4.1, ADR 0006/0019): kopieren, nie verschieben.

Jede Quelldatei nimmt genau einen sichtbaren Ausgang (Unterordner im
Quellordner): ``_importiert``, ``_dubletten``, ``_unbekanntes-format``,
``_fehler``, ``_gesperrt`` oder ``_ausgefiltert`` (Import-Regeln, ADR 0046).
Ablauf je Datei: erkennen → Regeln prüfen → hashen → Dublettencheck (inkl.
Gesundheitsprüfung des Bestands!) → Kopie in die Datumsstruktur schreiben →
**Hash der Kopie verifizieren** → katalogisieren → erst dann die Quelle
bewegen. Alles wird in ``import_log`` protokolliert.

Rein auf Verbindungs-Ebene (keine Engine-Kenntnis) — der Aufrufer sorgt für
den EINEN Schreiber (ADR 0007).

Durchsatz (Block 4S): ``import_folder`` arbeitet als **Pipeline** — ein
Thread-Pool liest voraus (Container erkennen, Quelle hashen, Bestand auf
Gesundheit prüfen; alles nur Lese-Arbeit, eigene Lese-Verbindungen dank WAL),
während der Aufrufer-Thread seriell kopiert, katalogisiert und **gebündelt
committet** (ein fsync je Schub statt je Datei). Quellen wandern erst NACH
dem Commit ihres Schubs in ``_importiert`` — die ADR-0006-Garantie „Quelle
bewegt sich erst, wenn die Kopie sicher ist" schließt damit auch die
Katalog-Persistenz ein.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .db.store import media_kind_for, now_iso, store_extraction, store_interpretations
from .extract import container
from .extract.container import ExtractorNotImplementedError, UnknownContainerError
from .extract.types import ContainerExtraction
from .hashing import hash_file
from .interpret import interpret_items

# Sichtbare Ausgänge im Quellordner (ADR 0019).
STATE_DIRS = {
    "importiert": "_importiert",
    "dublette": "_dubletten",
    "unbekanntes_format": "_unbekanntes-format",
    "fehler": "_fehler",
    "gesperrt": "_gesperrt",       # ADR 0023: Hash steht auf der Sperrliste
    "ausgefiltert": "_ausgefiltert",  # ADR 0046: Import-Regeln (Maße/Format)
}
UNKNOWN_DATE_DIR = "_unbekanntes-datum"
DEFAULT_MIN_DATE = datetime(2015, 1, 1, tzinfo=timezone.utc)

# Systemdateien, die einen Ordner nicht „belegt“ machen (ADR 0033): macOS/
# Windows streuen sie überall hin — ein Ordner, der nur noch solche Dateien
# enthält, gilt beim Leerordner-Aufräumen als leer.
_JUNK_FILES = {".ds_store", "thumbs.db", "desktop.ini"}


def _is_junk(name: str) -> bool:
    return name.lower() in _JUNK_FILES or name.startswith("._")

# EXIF-Textfelder mit Erstelldatum, in Prioritätsreihenfolge (ADR 0019).
_DATE_KEYWORDS = ("DateTimeOriginal", "CreateDate", "DateTime")
_DATE_FORMATS = ("%Y:%m:%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")


@dataclass
class ImportReport:
    """Zusammenfassung eines Import-Laufs (für last_result und Tests)."""

    importiert: int = 0
    dublette: int = 0
    repariert: int = 0
    unbekanntes_format: int = 0
    fehler: int = 0
    gesperrt: int = 0
    ausgefiltert: int = 0
    leere_ordner: int = 0
    probleme: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"{self.importiert} neu"]
        if self.repariert:
            parts.append(f"{self.repariert} repariert")
        parts.append(f"{self.dublette} Dubletten")
        if self.unbekanntes_format:
            parts.append(f"{self.unbekanntes_format} unbekanntes Format")
        if self.ausgefiltert:
            parts.append(f"{self.ausgefiltert} ausgefiltert (Import-Regeln)")
        if self.gesperrt:
            parts.append(f"{self.gesperrt} gesperrt")
        if self.fehler:
            parts.append(f"{self.fehler} Fehler")
        if self.leere_ordner:
            parts.append(f"{self.leere_ordner} leere Ordner entfernt")
        return "Import: " + " · ".join(parts)


def filter_reason(
    extraction: ContainerExtraction, rules: dict[str, Any] | None
) -> str | None:
    """Grund, warum die Import-Regeln (``[import]``, ADR 0046) diese Datei
    ausfiltern — oder ``None`` (aufnehmen).

    - Ausgeschlossene Formate treffen jeden Container (auch solche ohne
      fertigen Extraktor, z. B. PSD/ARW).
    - Die Maß-Grenzen gelten NUR für Bilder mit bekannten Maßen: Videos
      bleiben draußen (kleine Videos sind legitim), und ohne Maße wird
      nicht geraten — lieber ein Mini-Bild zu viel als ein Original zu wenig.
    """
    if not rules:
        return None
    if extraction.container in rules.get("formate", ()):
        return f"Format ausgeschlossen ({extraction.container})"
    if media_kind_for(extraction.container) != "image":
        return None
    w, h = extraction.width, extraction.height
    if not w or not h:
        return None
    min_k = rules.get("min_kante") or 0
    max_k = rules.get("max_kante") or 0
    if min_k and min(w, h) < min_k:
        return f"zu klein ({w}×{h}, kleinste Seite unter {min_k} px)"
    if max_k and max(w, h) > max_k:
        return f"zu groß ({w}×{h}, längste Seite über {max_k} px)"
    return None


def _parse_date_text(text: str) -> datetime | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text.strip()[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _parse_embedded_date(extraction: ContainerExtraction) -> datetime | None:
    for keyword in _DATE_KEYWORDS:
        for item in extraction.items:
            if item.keyword != keyword or not item.text:
                continue
            parsed = _parse_date_text(item.text)
            if parsed is not None:
                return parsed
    return None


def determine_date(
    extraction: ContainerExtraction,
    stat: Any,
    *,
    min_date: datetime = DEFAULT_MIN_DATE,
    now: datetime | None = None,
) -> tuple[datetime | None, str]:
    """Erstelldatum nach ADR-0019-Kaskade: Metadaten → Dateisystem → unplausibel.

    Liefert ``(datum, quelle)``; ``(None, "unplausibel")``, wenn kein Datum im
    Plausibilitätsfenster liegt (dann: ``_unbekanntes-datum``-Bereich).
    """
    upper = (now or datetime.now(timezone.utc)) + timedelta(days=1)

    def plausible(dt: datetime) -> bool:
        return min_date <= dt <= upper

    embedded = _parse_embedded_date(extraction)
    if embedded is not None and plausible(embedded):
        return embedded, "metadaten"

    stamps = [stat.st_mtime]
    birthtime = getattr(stat, "st_birthtime", None)
    if birthtime:
        stamps.append(birthtime)
    fs_dt = datetime.fromtimestamp(min(stamps), tz=timezone.utc)
    if plausible(fs_dt):
        return fs_dt, "dateisystem"
    return None, "unplausibel"


def set_media_date(
    conn: sqlite3.Connection, file_hash: str, when: datetime | None, source: str
) -> None:
    """``items.media_date`` setzen (ADR 0021; seit ADR 0061 mit Uhrzeit,
    ``YYYY-MM-DD HH:MM:SS`` in UTC — sortiert lexikografisch korrekt, und
    ``substr``-Filter auf Jahr/Monat laufen unverändert).

    Metadaten-Daten überschreiben, Dateisystem-Daten füllen nur NULL auf —
    Kopien/Backups verfälschen mtimes, eingebettete Daten nicht. ``None``
    (unplausibel) lässt die Spalte unangetastet.
    """
    if when is None:
        return
    value = f"{when:%Y-%m-%d %H:%M:%S}"
    if source == "metadaten":
        conn.execute(
            "UPDATE items SET media_date = ? WHERE file_hash = ?", (value, file_hash)
        )
    else:
        conn.execute(
            "UPDATE items SET media_date = ? WHERE file_hash = ? AND media_date IS NULL",
            (value, file_hash),
        )


def backfill_media_dates(
    conn: sqlite3.Connection,
    *,
    min_date: datetime = DEFAULT_MIN_DATE,
    progress: Callable[[int, int, int], None] | None = None,
) -> dict[str, int]:
    """``media_date`` für den Alt-Bestand nachtragen (ADR 0021) — ohne Hashen.

    Läuft automatisch beim App-Start, wenn Items ohne Datum existieren (die
    manuelle Re-Scan-Pflicht war eine Stolperfalle: Feral Strawberrys 7500er-Bestand
    stand komplett auf „ohne Datum"). Eingebettete Daten kommen aus den
    **gespeicherten Roh-Texten** (DB, kein Dateizugriff), der Rückfall ist
    der älteste plausible Dateisystem-Stempel des ersten noch existierenden
    Fundorts — dieselbe Kaskade wie ADR 0019, nur aus zweiter Hand.
    Items ohne plausibles Datum bleiben ehrlich NULL („ohne Datum").

    Uhrzeit-Auffrischung (ADR 0061): Alt-Einträge mit reinem Datum
    (``length = 10``, vor ADR 0061 gespeichert) werden um die Uhrzeit
    ergänzt — aus Metadaten immer (eingebettete Daten sind maßgeblich),
    aus dem Dateisystem NUR, wenn der Stempel noch denselben Tag nennt.
    Weicht er ab (Datei seit dem Import kopiert/berührt), bleibt das
    gespeicherte Datum stehen: lieber ehrlich datumsgenau als eine
    plausibel aussehende, falsche Uhrzeit.
    """
    upper = datetime.now(timezone.utc) + timedelta(days=1)
    rows = conn.execute(
        """SELECT file_hash, media_date FROM items
            WHERE media_date IS NULL OR length(media_date) = 10"""
    ).fetchall()
    total, dated = len(rows), 0
    for index, row in enumerate(rows, start=1):
        file_hash = row["file_hash"]
        when: datetime | None = None
        source = "dateisystem"
        for keyword in _DATE_KEYWORDS:
            hit = conn.execute(
                """SELECT value_text FROM raw_metadata
                    WHERE file_hash = ? AND keyword = ? AND value_text IS NOT NULL
                    ORDER BY ordinal LIMIT 1""",
                (file_hash, keyword),
            ).fetchone()
            if hit is None:
                continue
            parsed = _parse_date_text(hit["value_text"])
            if parsed is not None and min_date <= parsed <= upper:
                when, source = parsed, "metadaten"
                break
        if when is None:
            for (path,) in conn.execute(
                "SELECT path FROM file_locations WHERE file_hash = ? ORDER BY id",
                (file_hash,),
            ):
                try:
                    stat = Path(path).stat()
                except OSError:
                    continue
                stamps = [stat.st_mtime]
                birthtime = getattr(stat, "st_birthtime", None)
                if birthtime:
                    stamps.append(birthtime)
                candidate = datetime.fromtimestamp(min(stamps), tz=timezone.utc)
                if min_date <= candidate <= upper:
                    when = candidate
                break
        if when is not None:
            if row["media_date"] is None or source == "metadaten":
                set_media_date(conn, file_hash, when, source)
                dated += 1
            else:
                # Uhrzeit-Auffrischung aus dem Dateisystem: nur wenn der
                # aktuelle Stempel noch auf dem gespeicherten Tag liegt.
                value = f"{when:%Y-%m-%d %H:%M:%S}"
                cur = conn.execute(
                    """UPDATE items SET media_date = ?
                        WHERE file_hash = ? AND media_date = substr(?, 1, 10)""",
                    (value, file_hash, value),
                )
                dated += cur.rowcount
        if index % 500 == 0:
            conn.commit()
            if progress is not None:
                progress(index, total, dated)
    conn.commit()
    if progress is not None:
        progress(total, total, dated)
    return {"total": total, "dated": dated}


def _free_name(directory: Path, name: str, *, matches_hash: str | None = None) -> Path | None:
    """Ersten freien Namen (`name`, `name__2`, …) in `directory` finden.

    Liegt unter einem Kandidaten bereits eine Datei mit Hash ``matches_hash``,
    ist das der Bestand selbst → ``None`` (Aufrufer behandelt es als Dublette).
    """
    stem, suffix = Path(name).stem, Path(name).suffix
    for n in range(1, 10_000):
        candidate = directory / (name if n == 1 else f"{stem}__{n}{suffix}")
        if not candidate.exists():
            return candidate
        if matches_hash is not None:
            try:
                if hash_file(candidate) == matches_hash:
                    return None
            except OSError:
                continue
    raise RuntimeError(f"Kein freier Name für {name!r} in {directory}")


def _move_to_state(source: Path, source_root: Path, state: str) -> Path:
    """Quelle in den Ausgangs-Ordner bewegen (flach, Kollision per Suffix)."""
    state_dir = source_root / STATE_DIRS[state]
    state_dir.mkdir(parents=True, exist_ok=True)
    destination = _free_name(state_dir, source.name)
    source.replace(destination)
    return destination


def _log(
    conn: sqlite3.Connection, *, ts: str, source: Path, action: str,
    detail: str | None = None, target: Path | None = None,
    file_hash: str | None = None, date_source: str | None = None,
) -> None:
    # Bewusst OHNE Commit — der Aufrufer committet gebündelt (Block 4S:
    # ein fsync je Datei war ein spürbarer Teil der 54k-Import-Dauer).
    conn.execute(
        """INSERT INTO import_log
           (imported_at, source_path, action, detail, target_path, file_hash, date_source)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (ts, str(source), action, detail,
         str(target) if target else None, file_hash, date_source),
    )


def _bestand_locations(
    conn: sqlite3.Connection, file_hash: str, target_root: Path
) -> tuple[Path | None, bool]:
    """(gesunde Bestandskopie | None, Hash überhaupt im Bestand registriert?).

    Nur Fundorte unterhalb von ``target_root`` zählen als Bestand — der
    Vergleich läuft über Pfade (kein SQL-LIKE: ``_``/``%`` in Windows-Pfaden
    wären dort Wildcards). Eine kaputte oder verschwundene Kopie macht die
    Quelle NICHT zur Dublette (ADR 0019).
    """
    rows = conn.execute(
        "SELECT path FROM file_locations WHERE file_hash = ? ORDER BY id",
        (file_hash,),
    ).fetchall()
    healthy: Path | None = None
    known = False
    for row in rows:
        path = Path(row["path"])
        try:
            path.relative_to(target_root)
        except ValueError:
            continue
        known = True
        if healthy is None:
            try:
                if path.is_file() and hash_file(path) == file_hash:
                    healthy = path
            except OSError:
                continue
    return healthy, known


@dataclass
class _Prepared:
    """Ergebnis der DB-schreibfreien Vorarbeit zu einer Quelldatei (Stage 1).

    Alles hier ist reine Lese-Arbeit (Datei + DB-Lesezugriffe) und darf darum
    in Vorarbeiter-Threads mit eigenen Lese-Verbindungen laufen (WAL); die
    Schreib-Seite (`_finish`) bleibt beim EINEN Writer (ADR 0007).
    """

    source: Path
    outcome: str | None = None          # 'unbekanntes_format'|'fehler' oder None
    detail: str | None = None
    extraction: ContainerExtraction | None = None
    file_hash: str | None = None
    stat: Any = None
    healthy_bestand: Path | None = None
    known_in_bestand: bool = False


def _prepare(
    source: Path, conn: sqlite3.Connection, target_root: Path,
    rules: dict[str, Any] | None = None,
) -> _Prepared:
    """Erkennen + hashen + Bestands-Gesundheitscheck — ohne DB-Schreibzugriff."""
    # 1) Container erkennen (unbekannt/kaputt aussortieren, ADR 0019).
    try:
        extraction = container.extract(source)
    except UnknownContainerError:
        return _Prepared(source, outcome="unbekanntes_format")
    except ExtractorNotImplementedError as exc:
        # Erkannt, Extraktor folgt (PSD/PDF): trotzdem importieren.
        extraction = ContainerExtraction(container=exc.container)
    except OSError as exc:
        return _Prepared(source, outcome="fehler", detail=f"Lesefehler: {exc}")

    # Import-Regeln (ADR 0046) — VOR dem Hashen: Ausgefiltertes kostet
    # keinen Voll-Lesedurchgang.
    reason = filter_reason(extraction, rules)
    if reason is not None:
        return _Prepared(source, outcome="ausgefiltert", detail=reason)

    # 2) Hash + Stat der Quelle.
    try:
        file_hash = hash_file(source)
        stat = source.stat()
    except OSError as exc:
        return _Prepared(source, outcome="fehler",
                         detail=f"Hash/Stat fehlgeschlagen: {exc}")

    # Sperrliste (ADR 0023): bewusst Gelöschtes kommt nicht wieder herein.
    if conn.execute(
        "SELECT 1 FROM blocked_hashes WHERE file_hash = ?", (file_hash,)
    ).fetchone():
        return _Prepared(source, outcome="gesperrt", file_hash=file_hash)

    # 3) Dublettencheck-Vorarbeit — nur eine GESUNDE Bestandskopie zählt
    #    (ADR 0019; hasht ggf. die Bestandskopie — genau deshalb Stage 1).
    existing, known = _bestand_locations(conn, file_hash, target_root)
    return _Prepared(source, extraction=extraction, file_hash=file_hash,
                     stat=stat, healthy_bestand=existing, known_in_bestand=known)


def _finish(
    conn: sqlite3.Connection,
    prep: _Prepared,
    *,
    source_root: Path,
    target_root: Path,
    min_date: datetime,
    pending: dict[str, str],
    ts: str,
    keep_source: bool = False,
) -> tuple[str, str | None, Path | None]:
    """Schreib-Seite: Kopie/Katalog/Log — läuft immer beim EINEN Writer.

    Liefert ``(Ausgang, Detail, aufgeschobener Quell-Move | None)``: beim
    Ausgang „importiert/repariert" wandert die Quelle erst NACH dem Commit
    des Schubs (ADR 0006 schließt die Katalog-Persistenz ein); alle anderen
    Ausgänge bewegen sofort (die Quelle ist dort redundant bzw. unlesbar).
    ``pending`` hält die Hashes dieses Laufs für den In-Run-Dublettencheck.

    ``keep_source`` (Modus „belassen", ADR 0031): die Quelle wird NIE bewegt —
    kein Einsortieren in Ausgangs-Ordner, kein aufgeschobener Move. Für
    kopieren-Watchordner auf fremde Output-Verzeichnisse (rein lesend).
    """
    def forget_location(path: Path) -> None:
        # Fundort-Invariante (ADR 0033): wer die Quelle bewegt oder löscht,
        # räumt ihre Fundort-Zeile im selben Zug ab — sonst hinterlässt der
        # Wechsel katalogisieren→verschieben zehntausende verwaiste Fundorte.
        # Läuft in derselben Transaktion wie das Import-Log (Batch-Commit).
        if prep.file_hash is not None:
            conn.execute(
                "DELETE FROM file_locations WHERE file_hash = ? AND path = ?",
                (prep.file_hash, str(path)),
            )

    def sort_out(path: Path, state: str) -> str:
        if keep_source:
            return "belassen (kopieren-Modus)"
        forget_location(path)
        return f"verschoben nach {_move_to_state(path, source_root, state)}"

    source = prep.source
    if prep.outcome == "unbekanntes_format":
        _log(conn, ts=ts, source=source, action="unbekanntes_format",
             detail=sort_out(source, "unbekanntes_format"))
        return "unbekanntes_format", None, None
    if prep.outcome == "ausgefiltert":
        # Import-Regeln (ADR 0046): sichtbar aussortieren wie unbekanntes
        # Format — nach einer Config-Änderung einfach neu einwerfen.
        _log(conn, ts=ts, source=source, action="ausgefiltert",
             detail=f"{prep.detail} — {sort_out(source, 'ausgefiltert')}")
        return "ausgefiltert", prep.detail, None
    if prep.outcome == "fehler":
        sort_out(source, "fehler")
        _log(conn, ts=ts, source=source, action="fehler", detail=prep.detail)
        return "fehler", prep.detail, None
    if prep.outcome == "gesperrt":
        sort_out(source, "gesperrt")
        _log(conn, ts=ts, source=source, action="gesperrt",
             detail="Hash steht auf der Sperrliste (ADR 0023)",
             file_hash=prep.file_hash)
        return "gesperrt", None, None

    file_hash, extraction, stat = prep.file_hash, prep.extraction, prep.stat

    # Dublette gegen den Bestand (Stage-1-Befund) ODER gegen diesen Lauf
    # (zwei identische neue Dateien in einem Rutsch).
    existing = prep.healthy_bestand or (
        Path(pending[file_hash]) if file_hash in pending else None
    )
    if existing is not None:
        sort_out(source, "dublette")
        _log(conn, ts=ts, source=source, action="dublette",
             detail=f"Bestand: {existing}", file_hash=file_hash)
        return "dublette", str(existing), None

    # Zielpfad aus der Datums-Kaskade.
    when, date_source = determine_date(extraction, stat, min_date=min_date)
    if when is None:
        target_dir = target_root / UNKNOWN_DATE_DIR
    else:
        target_dir = target_root / f"{when:%Y}" / f"{when:%m}" / f"{when:%d}"

    # Kopieren mit Verifikation (Tempname → Hash → endgültiger Name).
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = _free_name(target_dir, source.name, matches_hash=file_hash)
    if destination is None:
        # Hash-gleiche Datei liegt (unkatalogisiert) schon im Zielordner.
        sort_out(source, "dublette")
        _log(conn, ts=ts, source=source, action="dublette",
             detail="lag bereits (unkatalogisiert) im Bestand", file_hash=file_hash)
        return "dublette", None, None
    temp = destination.with_name(destination.name + ".part")
    try:
        shutil.copy2(source, temp)   # copy2: Zeitstempel bleiben erhalten
        if hash_file(temp) != file_hash:
            raise OSError("Hash der Kopie stimmt nicht mit der Quelle überein")
        temp.replace(destination)
    except OSError as exc:
        temp.unlink(missing_ok=True)
        sort_out(source, "fehler")
        _log(conn, ts=ts, source=source, action="fehler",
             detail=f"Kopie fehlgeschlagen: {exc}", file_hash=file_hash)
        return "fehler", str(exc), None

    # Sofort katalogisieren (Ziel-Fundort; Quelle wird bewusst nicht registriert).
    # Stat-Gedächtnis (ADR 0042) mit dem Stat der KOPIE — copy2 erhält zwar
    # die Zeitstempel, aber Dateisystem-Rundungen machen Quelle ≠ Ziel.
    try:
        dst_mtime_ns = destination.stat().st_mtime_ns
    except OSError:
        dst_mtime_ns = None
    store_extraction(
        conn, file_hash=file_hash, file_size=stat.st_size,
        path=destination, extraction=extraction, now=ts,
        mtime_ns=dst_mtime_ns,
    )
    store_interpretations(
        conn, file_hash=file_hash,
        interpretations=interpret_items(extraction.items), now=ts,
    )
    set_media_date(conn, file_hash, when, date_source)  # ADR 0021
    pending[file_hash] = str(destination)

    action = "repariert" if prep.known_in_bestand else "importiert"
    _log(conn, ts=ts, source=source, action=action,
         detail=None if action == "importiert" else "Bestandskopie war kaputt/verschwunden",
         target=destination, file_hash=file_hash, date_source=date_source)
    # „belassen": kein aufgeschobener Quell-Move — Original bleibt liegen.
    if not keep_source:
        forget_location(source)
    return action, str(destination), (None if keep_source else source)


def import_file(
    conn: sqlite3.Connection,
    source: Path,
    *,
    source_root: Path,
    target_root: Path,
    min_date: datetime = DEFAULT_MIN_DATE,
    now: str | None = None,
    source_mode: str = "einsortieren",
    rules: dict[str, Any] | None = None,
) -> tuple[str, str | None]:
    """Eine Quelldatei verarbeiten. Liefert (Ausgang, Detail).

    ``rules`` — Import-Regeln (ADR 0046, ``config.import_rules``): Maß-
    Grenzen und ausgeschlossene Formate; Treffer nehmen den sichtbaren
    Ausgang ``_ausgefiltert``.

    ``source_mode`` — was mit der QUELLE passiert (ADR 0031):
    - ``"einsortieren"`` (ADR 0019): Erfolg → ``_importiert/``, andere
      Ausgänge → sichtbare Ausgangs-Ordner.
    - ``"belassen"``: Quelle wird NIE angefasst (kopieren-Watchordner auf
      fremde Output-Verzeichnisse — rein lesend).
    - ``"loeschen"`` (Verschiebe-Modus, ADR 0025): Erfolg → Quelle gelöscht,
      andere Ausgänge → Ausgangs-Ordner (Nachschau).
    """
    ts = now or now_iso()
    prep = _prepare(source, conn, target_root, rules)
    action, detail, deferred = _finish(
        conn, prep, source_root=source_root, target_root=target_root,
        min_date=min_date, pending={}, ts=ts,
        keep_source=source_mode == "belassen",
    )
    conn.commit()
    if deferred is not None:
        if source_mode == "loeschen":
            deferred.unlink()
        else:
            _move_to_state(deferred, source_root, "importiert")
    return action, detail


def iter_import_files(source_root: Path) -> list[Path]:
    """Alle zu importierenden Dateien (rekursiv), Ausgangs-Ordner ausgenommen."""
    skip = set(STATE_DIRS.values())
    files: list[Path] = []
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        relative = path.relative_to(source_root)
        if relative.parts and relative.parts[0] in skip:
            continue
        files.append(path)
    return files


def remove_empty_dirs(source_root: Path) -> int:
    """Leer gewordene Unterordner der Quelle entfernen (ADR 0033).

    Bottom-up, damit Ketten leerer Unterunterordner in einem Durchlauf
    kollabieren. Die Quell-Wurzel selbst und die sichtbaren Ausgangs-Ordner
    (``_importiert`` & Co.) bleiben immer stehen. Ordner, die nur noch
    Systemdateien enthalten (.DS_Store, Thumbs.db, desktop.ini, ``._*``),
    gelten als leer — die Systemdateien werden mitgelöscht (Feral Strawberry,
    2026-07-09: sonst bliebe auf dem Mac praktisch jeder Datumsordner
    stehen). Gibt die Zahl entfernter Ordner zurück.
    """
    source_root = Path(source_root)
    skip = set(STATE_DIRS.values())
    removed = 0
    for dirpath, _dirnames, _filenames in os.walk(source_root, topdown=False):
        directory = Path(dirpath)
        relative = directory.relative_to(source_root)
        if not relative.parts or relative.parts[0] in skip:
            continue
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        # Nur echte Junk-Dateien dürfen übrig sein — jeder andere Inhalt
        # (Datei, Unterordner, Symlink) lässt den Ordner stehen.
        if not all(entry.is_file() and _is_junk(entry.name) for entry in entries):
            continue
        try:
            for entry in entries:
                entry.unlink()
            directory.rmdir()
            removed += 1
        except OSError:
            continue   # z. B. gerade neu befüllt — nächster Lauf räumt nach
    return removed


def _db_file(conn: sqlite3.Connection) -> str | None:
    """Datei-Pfad der Haupt-DB dieser Verbindung (None bei :memory:)."""
    for row in conn.execute("PRAGMA database_list"):
        if row["name"] == "main":
            return row["file"] or None
    return None


def import_folder(
    conn: sqlite3.Connection,
    source_root: Path,
    *,
    target_root: Path,
    min_date: datetime = DEFAULT_MIN_DATE,
    progress: Callable[[Path, int, int, "ImportReport"], None] | None = None,
    workers: int | None = None,
    commit_every: int = 50,
    source_mode: str = "einsortieren",
    remove_empty: bool = False,
    rules: dict[str, Any] | None = None,
) -> ImportReport:
    """Einen Quellordner komplett verarbeiten (ADR 0019). Liefert den Report.

    Pipeline (Block 4S): ``workers`` Vorarbeiter-Threads erledigen die reine
    Lese-Arbeit (erkennen, hashen, Bestands-Gesundheit) mit eigenen
    Lese-Verbindungen und begrenztem Vorlauf; dieser Thread (der EINE Writer)
    konsumiert die Ergebnisse **in Datei-Reihenfolge**, kopiert/katalogisiert
    seriell und committet alle ``commit_every`` Dateien. Quell-Moves nach
    ``_importiert`` laufen erst nach dem Commit ihres Schubs. Der In-Run-
    Dublettencheck (identische neue Dateien im selben Lauf) passiert hier im
    Writer über die Hashes dieses Laufs — Stage 1 sieht nur den alten Bestand.

    ``source_mode`` wie bei ``import_file`` (ADR 0031): einsortieren |
    belassen (Quelle nie anfassen) | loeschen (Verschiebe-Modus, ADR 0025).
    ``remove_empty`` (ADR 0033): nach dem Lauf leer gewordene Unterordner
    der Quelle entfernen — wirkungslos im Modus „belassen“ (dort wird die
    Quelle grundsätzlich nie angefasst).
    """
    source_root = Path(source_root)
    target_root = Path(target_root)
    report = ImportReport()
    files = iter_import_files(source_root)
    total = len(files)
    if workers is None:
        workers = max(2, min(8, (os.cpu_count() or 4) // 2))
    db_file = _db_file(conn)

    pending: dict[str, str] = {}          # Hashes dieses Laufs → Zielpfad
    deferred_moves: list[Path] = []       # Quellen, die auf den Commit warten

    def finish_run() -> ImportReport:
        # ADR 0033: erst wenn alle Quell-Moves durch sind, leere Ordner fegen.
        if remove_empty and source_mode != "belassen":
            report.leere_ordner = remove_empty_dirs(source_root)
        return report

    def flush() -> None:
        conn.commit()
        for src in deferred_moves:
            try:
                if source_mode == "loeschen":
                    # Verschiebe-Modus (ADR 0025): Kopie ist verifiziert und
                    # der Katalog committet — die Quelle (selbst nur eine
                    # Kopie aus Backups) darf verschwinden.
                    src.unlink()
                else:
                    _move_to_state(src, source_root, "importiert")
            except OSError as exc:        # Kopie+Katalog sind sicher — nur melden
                report.probleme.append(f"{src}: Quelle nicht bewegt/gelöscht: {exc}")
        deferred_moves.clear()

    def handle(index: int, path: Path, prep: _Prepared) -> None:
        if progress is not None:
            progress(path, index, total, report)
        try:
            action, detail, deferred = _finish(
                conn, prep, source_root=source_root, target_root=target_root,
                min_date=min_date, pending=pending, ts=now_iso(),
                keep_source=source_mode == "belassen",
            )
        except Exception as exc:  # Einzelfehler töten den Lauf nicht
            report.fehler += 1
            report.probleme.append(f"{path}: {exc}")
            return
        if action == "fehler" and detail:
            report.probleme.append(f"{path}: {detail}")
        setattr(report, action, getattr(report, action) + 1)
        if deferred is not None:
            deferred_moves.append(deferred)
        if index % commit_every == 0:
            flush()

    if db_file is None:
        # Keine Datei-DB (Tests mit :memory:): Vorarbeit seriell mit derselben
        # Verbindung — identische Semantik, nur ohne Parallelität.
        for index, path in enumerate(files, start=1):
            handle(index, path, _prepare(path, conn, target_root, rules))
        flush()
        return finish_run()

    # Thread-lokale Lese-Verbindungen (WAL: Leser laufen parallel zum Writer).
    # check_same_thread=False, weil sie am Ende vom Writer-Thread geschlossen
    # werden — benutzt (Queries) werden sie nur im jeweils eigenen Thread.
    local = threading.local()
    read_conns: list[sqlite3.Connection] = []

    def prepare_with_own_conn(path: Path) -> _Prepared:
        if getattr(local, "conn", None) is None:
            local.conn = sqlite3.connect(db_file, check_same_thread=False)
            local.conn.row_factory = sqlite3.Row
            local.conn.execute("PRAGMA busy_timeout=30000")
            read_conns.append(local.conn)
        try:
            return _prepare(path, local.conn, target_root, rules)
        except Exception as exc:  # defensiv: Vorarbeit darf den Lauf nie töten
            return _Prepared(path, outcome="fehler", detail=f"Vorarbeit: {exc}")

    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="feral-import") as pool:
            # Begrenzter Vorlauf: höchstens 2× workers Ergebnisse im Fenster —
            # 54k Extraktionen auf einmal im Speicher wären keine gute Idee.
            window: list = []
            depth = workers * 2
            iterator = enumerate(files, start=1)
            exhausted = False
            while window or not exhausted:
                while not exhausted and len(window) < depth:
                    try:
                        index, path = next(iterator)
                    except StopIteration:
                        exhausted = True
                        break
                    window.append((index, path, pool.submit(prepare_with_own_conn, path)))
                if window:
                    index, path, future = window.pop(0)
                    handle(index, path, future.result())
            flush()
    finally:
        for rc in read_conns:
            rc.close()
    return finish_run()
