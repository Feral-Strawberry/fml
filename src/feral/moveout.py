"""Rausverschieben abgelehnter Library-Dateien (Großbaustelle I, Block I3).

Der EINZIGE Weg neben dem Import, auf dem fml Dateien anfasst (ADR 0041,
Datei-Berührungsregel): abgelehnte Dateien — Sperrliste mit gemerkten
Fundort-Pfaden (Migration 0017) —, die physisch unter ``library.root``
liegen, werden in einen Zielordner verschoben. Datumsstruktur und
Kollisionsregeln wie beim Import (ADR 0019), Protokoll im ``import_log``.
Danach entscheidet der Dateimanager, nicht fml.

Sicherheiten:
- Vor JEDEM Anfassen wird der Datei-Hash verifiziert. Fehlt die Datei oder
  liegt unter dem gemerkten Pfad inzwischen etwas anderes, wird ehrlich
  gemeldet und NICHTS angefasst (ADR 0041: „meldet Abweichungen ehrlich").
- Verschieben auf derselben Platte ist ein atomares ``rename`` (der Inhalt
  wird nie kopiert, kann also nicht korrumpieren). Über Laufwerksgrenzen
  gilt die Import-Kette: kopieren → Hash der Kopie verifizieren → erst
  dann die Quelle löschen (ADR 0006).
- Externe Fundorte (nicht unter ``library.root``) sind nie Kandidaten.

Rein auf Verbindungs-Ebene (keine Engine-Kenntnis) — der Aufrufer sorgt
für den EINEN Schreiber (ADR 0007).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .db.store import now_iso
from .extract import container
from .extract.types import ContainerExtraction
from .hashing import hash_file
from .importer import DEFAULT_MIN_DATE, UNKNOWN_DATE_DIR, _free_name, _log, determine_date


@dataclass
class MoveoutReport:
    """Zusammenfassung eines Rausverschiebe-Laufs (für last_result und Tests)."""

    verschoben: int = 0
    fehlt: int = 0          # gemerkter Pfad existiert nicht mehr
    veraendert: int = 0     # Pfad existiert, Inhalt ist nicht mehr der abgelehnte
    fehler: int = 0
    probleme: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"{self.verschoben} verschoben"]
        if self.fehlt:
            parts.append(f"{self.fehlt} nicht mehr auffindbar")
        if self.veraendert:
            parts.append(f"{self.veraendert} verändert (nicht angefasst)")
        if self.fehler:
            parts.append(f"{self.fehler} Fehler")
        return "Rausverschieben: " + " · ".join(parts)


def _under_root(path: Path, root: Path) -> bool:
    # Unaufgelöste Pfad-Semantik wie importer._bestand_locations und das
    # fundort:-Prädikat (ADR 0041/I2) — kein resolve(), kein SQL-LIKE.
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def library_candidates(
    conn: sqlite3.Connection, library_root: str | Path
) -> list[tuple[str, Path]]:
    """Alle gemerkten Sperrlisten-Pfade unter ``library_root`` als
    ``(file_hash, pfad)`` — die Kandidaten des Pauschalwegs. Ohne
    Dateisystem-Zugriff (Existenz/Hash prüft erst der Lauf selbst)."""
    root = Path(library_root)
    out: list[tuple[str, Path]] = []
    for file_hash, raw in conn.execute(
        "SELECT file_hash, last_paths FROM blocked_hashes "
        "WHERE last_paths IS NOT NULL ORDER BY blocked_at, file_hash"
    ):
        for text in json.loads(raw):
            path = Path(text)
            if _under_root(path, root):
                out.append((file_hash, path))
    return out


def overview(
    conn: sqlite3.Connection, library_root: str | Path, *, sample: int = 20
) -> dict[str, Any]:
    """Vorschau für den Dialog: ehrliche Zahlen + eine gedeckelte Beispiel-
    Liste (Lehre aus dem Probleme-Overlay: mit TAUSENDEN Einträgen rechnen).
    ``movable``/``bytes`` zählen nur noch existierende Dateien; der Hash wird
    bewusst erst beim Verschieben geprüft (tausendfaches Hashen wäre für
    eine Vorschau zu teuer)."""
    candidates = library_candidates(conn, library_root)
    movable = missing = total_bytes = 0
    paths: list[str] = []
    for _file_hash, path in candidates:
        try:
            stat = path.stat()
        except OSError:
            missing += 1
            continue
        movable += 1
        total_bytes += stat.st_size
        if len(paths) < sample:
            paths.append(str(path))
    return {
        "total_blocked": conn.execute(
            "SELECT COUNT(*) FROM blocked_hashes"
        ).fetchone()[0],
        "movable": movable,
        "missing": missing,
        "bytes": total_bytes,
        "sample": paths,
    }


def _replace_last_path(
    conn: sqlite3.Connection, file_hash: str, old: Path, new: Path
) -> None:
    # Pfad-Gedächtnis aktuell halten: der Eintrag zeigt nach dem Lauf auf den
    # neuen Ort (außerhalb der Library) statt auf einen toten Pfad.
    row = conn.execute(
        "SELECT last_paths FROM blocked_hashes WHERE file_hash = ?", (file_hash,)
    ).fetchone()
    paths = json.loads(row[0]) if row and row[0] else []
    paths = [str(new) if p == str(old) else p for p in paths]
    conn.execute(
        "UPDATE blocked_hashes SET last_paths = ? WHERE file_hash = ?",
        (json.dumps(paths), file_hash),
    )


def _move_verified(source: Path, destination: Path, file_hash: str) -> None:
    """Quelle nach ``destination`` bewegen — atomar wo möglich, sonst mit
    der Import-Sicherheitskette (kopieren → verifizieren → Quelle löschen)."""
    try:
        source.rename(destination)
        return
    except OSError:
        pass  # z. B. anderes Laufwerk (EXDEV) → Kopier-Kette unten
    temp = destination.with_name(destination.name + ".part")
    try:
        shutil.copy2(source, temp)
        if hash_file(temp) != file_hash:
            raise OSError("Hash der Kopie stimmt nicht mit der Quelle überein")
        temp.replace(destination)
    except OSError:
        temp.unlink(missing_ok=True)
        raise
    source.unlink()


def move_out(
    conn: sqlite3.Connection,
    *,
    library_root: str | Path,
    target_root: str | Path,
    min_date: datetime = DEFAULT_MIN_DATE,
    progress: Callable[[Path, int, int, "MoveoutReport"], None] | None = None,
    commit_every: int = 50,
) -> MoveoutReport:
    """Der Pauschalweg: ALLE abgelehnten Dateien unter ``library_root`` in
    die Datumsstruktur unter ``target_root`` verschieben. Liefert den Report;
    jede berührte (oder ehrlich übersprungene) Datei steht im ``import_log``.
    """
    target_root = Path(target_root)
    candidates = library_candidates(conn, library_root)
    total = len(candidates)
    report = MoveoutReport()

    for index, (file_hash, path) in enumerate(candidates, start=1):
        if progress is not None:
            progress(path, index, total, report)
        ts = now_iso()
        try:
            # 1) Verifikation vor JEDEM Anfassen (ADR 0041).
            if not path.is_file():
                report.fehlt += 1
                _log(conn, ts=ts, source=path, action="rausverschieben_fehlt",
                     detail="Datei nicht mehr vorhanden", file_hash=file_hash)
                continue
            if hash_file(path) != file_hash:
                report.veraendert += 1
                _log(conn, ts=ts, source=path, action="rausverschieben_veraendert",
                     detail="Inhalt entspricht nicht mehr dem abgelehnten Hash — nicht angefasst",
                     file_hash=file_hash)
                continue

            # 2) Zielpfad aus der Datums-Kaskade (ADR 0019). Die Extraktion
            #    darf hier scheitern (unbekannter/kaputter Container) — dann
            #    greift der Dateisystem-Stempel als Rückfall.
            try:
                extraction = container.extract(path)
            except Exception:
                extraction = ContainerExtraction(container="unbekannt")
            when, date_source = determine_date(extraction, path.stat(), min_date=min_date)
            if when is None:
                target_dir = target_root / UNKNOWN_DATE_DIR
            else:
                target_dir = target_root / f"{when:%Y}" / f"{when:%m}" / f"{when:%d}"
            target_dir.mkdir(parents=True, exist_ok=True)
            destination = _free_name(target_dir, path.name)

            # 3) Bewegen + Buchführung (Pfad-Gedächtnis + Protokoll).
            _move_verified(path, destination, file_hash)
            _replace_last_path(conn, file_hash, path, destination)
            report.verschoben += 1
            _log(conn, ts=ts, source=path, action="rausverschoben",
                 target=destination, file_hash=file_hash, date_source=date_source)
        except Exception as exc:  # Einzelfehler töten den Lauf nicht
            report.fehler += 1
            report.probleme.append(f"{path}: {exc}")
            _log(conn, ts=ts, source=path, action="rausverschieben_fehler",
                 detail=str(exc), file_hash=file_hash)
        if index % commit_every == 0:
            conn.commit()
    conn.commit()
    return report
