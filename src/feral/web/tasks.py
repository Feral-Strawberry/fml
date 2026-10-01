"""Langläufer-Aufgaben des Worker-Prozesses (ADR 0067).

EINE Aufgabe = EINE benannte Funktion ``fn(conn, params, progress, ctx)`` mit
**picklebaren Parametern** (Pfade als Strings, Regeln als Dicts, Datums-
werte als ``datetime``). Der Web-Prozess reiht nur ``(name, params)`` ein
(``ScanEngine.enqueue``); ausgeführt wird im Worker-Prozess — dort ist die
Verbindung die EINE schreibende für Langläufer (ADR 0007, Nachtrag).

``progress(report=..., current=...)`` macht den Zustand in ``/api/status``
sichtbar; ``ctx`` liefert die prozess-lokalen Helfer (Prozess-Pool fürs
Parsen, Thumbnail-Pool fürs Vorwärmen). Rückgabe: Dict, ein ``summary``
(Meldungs-Dict) wird zum ``last_result``.

Neue Langläufer-Aufgabe (Erweiterungs-Rezept): Funktion hier + ``@task("name")``,
im Web-Prozess ``engine.enqueue("name", params, label)``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable, Protocol

from ..messages import msg
from ..scan import ScanReport, scan_files


class Progress(Protocol):
    """Callback, mit dem eine Aufgabe ihren Zustand sichtbar macht."""

    def __call__(self, *, report: dict | None = None, current: Any = None) -> None: ...


class TaskContext(Protocol):
    """Prozess-lokale Helfer des Workers."""

    def pool(self):
        """Prozess-Pool (``concurrent.futures.Executor``) für reine Arbeit."""
        ...

    def thumb_pool(self):
        """``ThumbPool`` des Workers (ADR 0020, eigener Pool je Prozess)."""
        ...


class TaskPaused(Exception):
    """Halt an der Dateigrenze (ADR 0093): Pause, Beenden oder Vorrang eines
    Watch-Batches. Wirft die Fortschrittsmeldung des Workers; ``params`` ist
    die Fortsetzung (nur die restliche Arbeit) — ``None`` = mit denselben
    Parametern neu starten (Aufgaben, die das Fehlende selbst neu suchen)."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__("paused")
        self.params = params


# Aufgaben, die ein Watch-Batch mitten im Lauf überholen darf (ADR 0093):
# sie setzen nach dem Halt ohne Doppelarbeit fort (Dateiliste als
# Fortsetzung bzw. Cache/DB zeigen, was fehlt).
RESUMABLE = frozenset({"scan_files", "rescan", "recheck_filtered", "import_files",
                       "thumb_warm", "audio_warm", "backfill_dates"})


TaskFn = Callable[[sqlite3.Connection, dict[str, Any], Progress, TaskContext], dict[str, Any]]
TASKS: dict[str, TaskFn] = {}


def task(name: str) -> Callable[[TaskFn], TaskFn]:
    def register(fn: TaskFn) -> TaskFn:
        TASKS[name] = fn
        return fn
    return register


def report_dict(r: ScanReport) -> dict[str, int]:
    return {
        "scanned_files": r.scanned_files,
        "media_files": r.media_files,
        "new_items": r.new_items,
        "known_items": r.known_items,
        "with_metadata": r.with_metadata,
        "interpreted": r.interpreted,
        "pending_extractor": r.pending_extractor,
        "skipped_unknown": r.skipped_unknown,
        "ausgefiltert": r.ausgefiltert,
        "files_with_warnings": r.files_with_warnings,
        "failed": len(r.failed),
    }


def _counters(**values: int) -> dict[str, int]:
    """Zähler in die Scan-Report-Felder mappen — die Statusanzeige zeigt so
    auch bei Import/Thumbnails/Reparse lebendige Zahlen (54k-Läufe!)."""
    base = {k: 0 for k in report_dict(ScanReport())}
    base.update(values)
    return base


# -- Scannen ---------------------------------------------------------------------

def _scan_list(conn, files: list[Path], params: dict[str, Any],
               progress: Progress) -> ScanReport:
    """Dateiliste scannen; beim Halt (ADR 0093) als Fortsetzung nur die
    noch nicht gescannten Dateien mitgeben (die Meldung kommt NACH jeder
    Datei — bis dahin ist alles committet)."""
    done = 0

    def on_file(report: ScanReport, path: Path) -> None:
        nonlocal done
        done = report.scanned_files
        progress(report=report_dict(report), current=path.name)

    try:
        report = scan_files(conn, files, progress=on_file, rules=params.get("rules"))
    except TaskPaused:
        raise TaskPaused({**params, "files": [str(p) for p in files[done:]]}) from None
    progress(report=report_dict(report), current=None)
    return report


def _scan(conn, files: list[Path], params: dict[str, Any], progress: Progress) -> dict[str, Any]:
    return {"summary": scan_summary(_scan_list(conn, files, params, progress))}


@task("scan_files")
def scan_files_task(conn, params, progress, ctx) -> dict[str, Any]:
    """Konkrete Dateien scannen (katalogisieren-Watchordner, ADR 0031)."""
    return _scan(conn, [Path(p) for p in params["files"]], params, progress)


@task("rescan")
def rescan_task(conn, params, progress, ctx) -> dict[str, Any]:
    """Alle bekannten, noch existierenden Fundorte erneut scannen — mit den
    Import-Regeln (min_date!) aus der Config, sonst liefe die Datumsregel
    (ADR 0075) hier mit dem Standard 2015 statt dem konfigurierten Wert.
    ``files`` = Fortsetzung nach einem Halt (ADR 0093)."""
    if "files" in params:
        files = [Path(p) for p in params["files"]]
    else:
        files = [
            Path(p)
            for (p,) in conn.execute("SELECT DISTINCT path FROM file_locations")
            if Path(p).is_file()
        ]
    return _scan(conn, files, params, progress)


@task("recheck_filtered")
def recheck_filtered_task(conn, params, progress, ctx) -> dict[str, Any]:
    """Aussortierte neu prüfen (#230): Pfade mit Ausgang ``ausgefiltert`` im
    Stat-Gedächtnis (ADR 0042) erneut scannen — nach geänderten Import-
    Regeln (z. B. gesenktes min_date) erreicht sonst nichts diese Dateien.
    Katalogisierte fallen dabei aus scan_memory heraus, weiter Aussortierte
    bleiben mit neuem Stand drin; verschwundene Pfade werden vergessen.
    ``files`` = Fortsetzung nach einem Halt (ADR 0093)."""
    gone: list[str] = []
    if "files" in params:
        files = list(params["files"])
    else:
        rows = conn.execute(
            "SELECT path FROM scan_memory WHERE outcome = 'ausgefiltert' ORDER BY path"
        ).fetchall()
        files = []
        for (p,) in rows:
            (files if Path(p).is_file() else gone).append(p)
        if gone:
            with conn:
                conn.executemany("DELETE FROM scan_memory WHERE path = ?",
                                 [(p,) for p in gone])

    report = _scan_list(conn, [Path(p) for p in files], params, progress)
    return {"summary": msg("sumRecheckFiltered", taken=report.media_files,
                           still=report.ausgefiltert, gone=len(gone))}


@task("audio_subtitles")
def audio_subtitles_task(conn, params, progress, ctx) -> dict[str, Any]:
    """Songtext mit Zeiten nachholen (#234): Songs, deren Untertitel-Spur
    ffprobe schon kannte (``codec_type = subtitle``), deren Text Schicht 1
    aber noch nicht hat, einmal neu durch den Scan schicken. Nur diese
    Handvoll, kein Voll-Scan. ``files`` = Fortsetzung nach einem Halt."""
    if "files" in params:
        files = list(params["files"])
    else:
        rows = conn.execute(
            """SELECT DISTINCT i.file_hash FROM items i
                 JOIN raw_metadata r ON r.file_hash = i.file_hash
                WHERE i.media_kind = 'audio' AND r.keyword = 'codec_type'
                  AND r.value_text = 'subtitle'
                  AND NOT EXISTS (SELECT 1 FROM raw_metadata s
                                   WHERE s.file_hash = i.file_hash
                                     AND s.source LIKE '%.subtitle')""").fetchall()
        files = []
        for (file_hash,) in rows:
            paths = [p for (p,) in conn.execute(
                "SELECT path FROM file_locations WHERE file_hash = ? ORDER BY id", (file_hash,))]
            path = next((p for p in paths if Path(p).is_file()), None)
            if path:
                files.append(path)
    return _scan(conn, [Path(p) for p in files], params, progress)


# -- Import / Rausverschieben ------------------------------------------------------

def _min_date(params: dict[str, Any]):
    """``min_date`` der Aufgabe als datetime. In den Parametern steht ISO-Text
    (JSON, ADR 0093); so kommt er auch aus der gesicherten Warteschlange."""
    from ..importer import rule_min_date

    return rule_min_date({"min_date": params.get("min_date")})


def _import_counters(index: int, rep) -> dict[str, int]:
    return _counters(
        scanned_files=index - 1,
        media_files=rep.importiert + rep.repariert + rep.dublette,
        new_items=rep.importiert + rep.repariert,
        known_items=rep.dublette,
        skipped_unknown=rep.unbekanntes_format + getattr(rep, "gesperrt", 0),
        ausgefiltert=rep.ausgefiltert,
        failed=rep.fehler,
    )


@task("import_folder")
def import_folder_task(conn, params, progress, ctx) -> dict[str, Any]:
    """Quellordner importieren (ADR 0019/0031/0033)."""
    from ..importer import import_folder

    def on_file(path: Path, index: int, total: int, rep) -> None:
        progress(current=msg("progressFile", index=index, total=total, name=path.name),
                 report=_import_counters(index, rep))

    report = import_folder(
        conn, Path(params["source_root"]), target_root=Path(params["target_root"]),
        min_date=_min_date(params), progress=on_file,
        source_mode=params.get("source_mode", "einsortieren"),
        remove_empty=bool(params.get("remove_empty", False)), rules=params.get("rules"),
    )
    return {"summary": import_summary(report)}


@task("import_files")
def import_files_task(conn, params, progress, ctx) -> dict[str, Any]:
    """Konkrete (zur Ruhe gekommene) Dateien importieren — Hotfolder (ADR 0025)."""
    from ..importer import ImportReport, import_file, remove_empty_dirs

    files = [Path(p) for p in params["files"]]
    source_root, target_root = Path(params["source_root"]), Path(params["target_root"])
    source_mode = params.get("source_mode", "einsortieren")
    report = ImportReport()
    for index, path in enumerate(files, start=1):
        try:
            progress(current=msg("progressFile", index=index, total=len(files), name=path.name),
                     report=_import_counters(index, report))
        except TaskPaused:   # Halt VOR dieser Datei: sie und der Rest folgen (ADR 0093)
            raise TaskPaused({**params, "files": [str(p) for p in files[index - 1:]]}) from None
        try:
            action, _detail = import_file(
                conn, path, source_root=source_root, target_root=target_root,
                min_date=_min_date(params), source_mode=source_mode,
                rules=params.get("rules"),
            )
        except Exception as exc:  # Einzelfehler töten den Batch nicht
            report.fehler += 1
            report.probleme.append(f"{path}: {exc}")
            continue
        setattr(report, action, getattr(report, action) + 1)
    if params.get("remove_empty") and source_mode != "belassen":
        report.leere_ordner = remove_empty_dirs(source_root)
    return {"summary": import_summary(report, hotfolder=True)}


@task("moveout")
def moveout_task(conn, params, progress, ctx) -> dict[str, Any]:
    """Pauschalweg des Rausverschiebe-Dialogs (I3, ADR 0041)."""
    from ..moveout import move_out

    def on_file(path: Path, index: int, total: int, rep) -> None:
        progress(current=msg("progressFile", index=index, total=total, name=path.name),
                 report=_counters(scanned_files=index - 1, media_files=rep.verschoben,
                                  new_items=rep.verschoben,
                                  skipped_unknown=rep.fehlt + rep.veraendert,
                                  failed=rep.fehler))

    report = move_out(conn, library_root=params["library_root"],
                      target_root=params["target_root"], min_date=_min_date(params),
                      progress=on_file)
    return {"summary": moveout_summary(report)}


# -- Wartung (Stufe 2A, ADR 0014) ---------------------------------------------------

@task("thumb_warm")
def thumb_warm_task(conn, params, progress, ctx) -> dict[str, Any]:
    """„Thumbnails erstellen" (ADR 0013/0020/0042-Ergänzung): Automatik nur
    Fehlende, ``retry_failed`` (Admin-Knopf) auch Fehlgeschlagene."""
    from ..thumbs import warm_thumbnails

    def on_progress(index, total, created, skipped, failed):
        progress(current=msg("progressThumb", index=index, total=total),
                 report=_counters(scanned_files=index, media_files=total,
                                  new_items=created, known_items=skipped, failed=failed))

    retry_failed = bool(params.get("retry_failed", False))
    result = warm_thumbnails(conn, params["cache_dir"], size=int(params["size"]),
                             progress=on_progress, pool=ctx.thumb_pool(),
                             retry_failed=retry_failed)
    parts = [msg("sumThumbsNew", n=result["created"]),
             msg("sumThumbsSkipped", n=result["skipped"])]
    if result["failed"]:
        parts.append(msg("sumThumbsFailedIssues" if retry_failed else "sumThumbsFailed",
                         n=result["failed"]))
    return {"summary": msg("sumThumbs", parts=parts)}


@task("audio_warm")
def audio_warm_task(conn, params, progress, ctx) -> dict[str, Any]:
    """„Audio analysieren" (A4 #161): Lautheit, Wellenform und Wiedergabe-
    Proxy vorwärmen — Automatik nur Fehlende, ``retry_failed`` (Admin-Knopf)
    auch Fehlgeschlagene. Läuft über den Thumbnail-Pool des Workers."""
    from ..audio_analysis import warm_audio

    def on_progress(index, total, created, skipped, failed):
        progress(current=msg("progressAudio", index=index, total=total),
                 report=_counters(scanned_files=index, media_files=total,
                                  new_items=created, known_items=skipped, failed=failed))

    retry_failed = bool(params.get("retry_failed", False))
    result = warm_audio(conn, params["cache_dir"], progress=on_progress,
                        pool=ctx.thumb_pool(), retry_failed=retry_failed,
                        true_peak=bool(params.get("true_peak", True)))
    parts = [msg("sumThumbsNew", n=result["created"]),
             msg("sumThumbsSkipped", n=result["skipped"])]
    if result["failed"]:
        parts.append(msg("sumThumbsFailedIssues" if retry_failed else "sumThumbsFailed",
                         n=result["failed"]))
    return {"summary": msg("sumAudio", parts=parts)}


@task("backfill_dates")
def backfill_dates_task(conn, params, progress, ctx) -> dict[str, Any]:
    """Erstelldaten für den Alt-Bestand nachtragen (ADR 0021/0061)."""
    from ..importer import backfill_media_dates, rule_min_date

    def on_progress(index: int, total: int, dated: int) -> None:
        progress(current=msg("progressBackfill", index=index, total=total),
                 report=_counters(scanned_files=index, media_files=total, new_items=dated))

    # min_date aus der Config durchreichen (#113) — der Backfill lief sonst
    # immer mit dem Standard 2015, egal was in [import] min_date stand.
    min_date = rule_min_date(params)
    result = backfill_media_dates(conn, min_date=min_date, progress=on_progress)
    rest: Any = ""
    if result["undatable"]:
        rest = msg("sumBackfillUndatable", n=result["undatable"],
                   min_date=f"{min_date:%Y-%m-%d}")
    return {"summary": msg("sumBackfill", dated=result["dated"], total=result["total"],
                           rest=rest)}


@task("search_reindex")
def search_reindex_task(conn, params, progress, ctx) -> dict[str, Any]:
    """FTS5-Suchindex komplett neu aufbauen (ADR 0024)."""
    from ..db.store import update_search_index

    conn.execute("DELETE FROM search_index")
    conn.execute("DELETE FROM search_index_map")
    hashes = [r[0] for r in conn.execute("SELECT file_hash FROM items")]
    total = len(hashes)
    for index, file_hash in enumerate(hashes, start=1):
        update_search_index(conn, file_hash)
        if index % 500 == 0 or index == total:
            conn.commit()
            progress(current=msg("progressReindex", index=index, total=total),
                     report=_counters(scanned_files=index, media_files=total, new_items=index))
    conn.commit()
    return {"summary": msg("sumReindex", n=total)}


@task("reparse")
def reparse_task(conn, params, progress, ctx) -> dict[str, Any]:
    """Schicht 2 rückwirkend über den ganzen Bestand (ohne Datei-Zugriff) —
    Parser laufen im Prozess-Pool des Workers, Commits gebündelt (ADR 0067)."""
    from ..interpret import reparse_database

    def on_chunk(rep) -> None:
        progress(current=msg("progressReparse", index=rep.items_total, total=rep.items_planned),
                 report=_counters(scanned_files=rep.items_total, media_files=rep.items_planned,
                                  interpreted=rep.items_interpreted,
                                  with_metadata=rep.fields_written))

    # Pool nur auf Anfrage (ADR 0067, Messung): Parsen kostet 0,06 ms/Item,
    # der Pool-Start 14–30 Prozesse — auf 70k kein Gewinn (5,7 s vs. 5,3 s).
    pool = ctx.pool() if params.get("pool", False) else None
    # Untergrenze der Datumsregel fürs Tag-Jahr der Songs (#220, ADR 0096).
    from ..importer import rule_min_date
    report = reparse_database(conn, progress=on_chunk, pool=pool,
                              chunk_size=int(params.get("chunk_size", 500)),
                              min_date=rule_min_date(params.get("rules")))
    return {"summary": msg("sumReparse", interpreted=report.items_interpreted,
                           total=report.items_total, fields=report.fields_written)}


@task("music_fields")
def music_fields_task(conn, params, progress, ctx) -> dict[str, Any]:
    """Musik-Angaben von Hand für eine große Auswahl setzen (ADR 0101
    Punkt 4): schreiben, die Songs aus ihren Roh-Blobs neu interpretieren,
    ein Commit je Schub. Kein Dateizugriff außer dem Stempel fürs Datum,
    wenn das Jahr geleert wird."""
    from ..db import manual_fields
    from ..importer import rule_min_date
    from ..interpret.reparse import reinterpret

    hashes, changes = params["hashes"], params["changes"]
    min_date = rule_min_date(params.get("rules"))
    done = 0
    for start in range(0, len(hashes), 100):
        touched = manual_fields.set_fields(conn, hashes[start:start + 100], changes)
        reinterpret(conn, touched, dates="year" in changes, min_date=min_date)
        conn.commit()
        done += len(touched)
        index = min(start + 100, len(hashes))
        progress(current=msg("progressMusicFields", index=index, total=len(hashes)),
                 report=_counters(scanned_files=index, media_files=len(hashes), new_items=done))
    return {"summary": msg("sumMusicFields", n=done)}


@task("integrity")
def integrity_task(conn, params, progress, ctx) -> dict[str, Any]:
    verdict = conn.execute("PRAGMA integrity_check").fetchone()[0]
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return {"summary": msg("sumIntegrityOk") if verdict == "ok"
            else msg("sumIntegrityProblem", verdict=verdict)}


def _db_file(conn: sqlite3.Connection) -> Path | None:
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main" and row[2]:
            return Path(row[2])
    return None


@task("vacuum")
def vacuum_task(conn, params, progress, ctx) -> dict[str, Any]:
    db = _db_file(conn)
    size = lambda: db.stat().st_size if db is not None and db.is_file() else 0  # noqa: E731
    before = size()
    conn.execute("VACUUM")
    # VACUUM schreibt die DB durchs WAL neu — ohne Checkpoint bleibt eine
    # WAL-Datei in DB-Größe liegen (Feral Strawberrys 1,1→2,21-GB-Befund).
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return {"summary": msg("sumVacuum", before=f"{before/1e6:.1f}", after=f"{size()/1e6:.1f}")}


@task("import_rules")
def import_rules_task(conn, params, progress, ctx) -> dict[str, Any]:
    """Import-Regeln rückwirkend auf den Bestand (ADR 0046)."""
    from .admin import apply_import_rules

    n = apply_import_rules(conn, params.get("rules"), params.get("thumb_cache"))
    return {"summary": msg("sumImportRules", n=n)}


@task("cache_clear")
def cache_clear_task(conn, params, progress, ctx) -> dict[str, Any]:
    """Eine Cache-Art löschen (#227); alles darin entsteht bei Bedarf neu."""
    from .admin import clear_cache

    n = clear_cache(params["dirs"], params["kind"])
    return {"summary": msg("sumCacheClear", n=n)}


@task("issues_reject")
def issues_reject_task(conn, params, progress, ctx) -> dict[str, Any]:
    """Alle offenen Probleme einer Art ablehnen (#217)."""
    from .admin import reject_issues

    r = reject_issues(conn, kind=params["kind"], thumb_cache=params.get("thumb_cache"))
    return {"summary": msg("sumIssuesReject", n=r["rejected"], skipped=r["skipped"])}


# -- Testhilfen (nur für die Testsuite: Prozess-Protokoll ehrlich prüfen) ----------

@task("_sleep")
def _sleep_task(conn, params, progress, ctx) -> dict[str, Any]:
    """Wartet ``seconds`` (Test: run_write neben einem Langläufer, Warteschlange)."""
    import time

    steps = max(1, int(params.get("steps", 1)))
    for index in range(1, steps + 1):
        progress(current=f"step {index}/{steps}", report=_counters(scanned_files=index,
                                                                 media_files=steps))
        time.sleep(float(params.get("seconds", 0.1)) / steps)
    return {"summary": msg("sumTest", n=steps)}


@task("_boom")
def _boom_task(conn, params, progress, ctx) -> dict[str, Any]:
    """Wirft (Test: Aufgabe kaputt ≠ Worker kaputt)."""
    raise RuntimeError(params.get("text", "kaputt"))


@task("_die")
def _die_task(conn, params, progress, ctx) -> dict[str, Any]:
    """Beendet den Worker-Prozess hart (Test: Aufsicht + Neustart)."""
    import os

    os._exit(3)


# -- Zusammenfassungen -----------------------------------------------------------------

def import_summary(report, *, hotfolder: bool = False) -> dict[str, Any]:
    """ImportReport → Meldungs-Dict (Gegenstück zu ``ImportReport.summary()``,
    das fürs CLI deutsch bleibt): nur belegte Zähler als ``parts``-Liste —
    der Frontend-Renderer joint sie mit « · » (Block M.2, ADR 0054)."""
    parts = [msg("sumImportNew", n=report.importiert)]
    if report.repariert:
        parts.append(msg("sumImportRepaired", n=report.repariert))
    parts.append(msg("sumImportDupes", n=report.dublette))
    if report.unbekanntes_format:
        parts.append(msg("sumImportUnknown", n=report.unbekanntes_format))
    if report.ausgefiltert:
        parts.append(msg("sumImportFiltered", n=report.ausgefiltert))
    if report.gesperrt:
        parts.append(msg("sumImportBlocked", n=report.gesperrt))
    if report.fehler:
        parts.append(msg("sumImportErrors", n=report.fehler))
    if report.leere_ordner:
        parts.append(msg("sumImportEmptyDirs", n=report.leere_ordner))
    return msg("sumHotfolderImport" if hotfolder else "sumImport", parts=parts)


def scan_summary(report: ScanReport) -> dict[str, Any]:
    """ScanReport → Meldungs-Dict (#233): Scan-Aufgaben hatten keine eigene
    Zusammenfassung — Verlauf und Wartung zeigten dann die der VORIGEN
    Aufgabe. Teile wie beim Import: nur belegte Zähler außer neu/bekannt."""
    parts = [msg("sumImportNew", n=report.new_items),
             msg("sumScanKnown", n=report.known_items)]
    if report.skipped_unknown:
        parts.append(msg("sumImportUnknown", n=report.skipped_unknown))
    if report.ausgefiltert:
        parts.append(msg("sumImportFiltered", n=report.ausgefiltert))
    if report.blocked:
        parts.append(msg("sumImportBlocked", n=report.blocked))
    if report.failed:
        parts.append(msg("sumImportErrors", n=len(report.failed)))
    return msg("sumScan", parts=parts)


def moveout_summary(report) -> dict[str, Any]:
    """MoveoutReport → Meldungs-Dict (wie ``import_summary``)."""
    parts = [msg("sumMoveMoved", n=report.verschoben)]
    if report.fehlt:
        parts.append(msg("sumMoveMissing", n=report.fehlt))
    if report.veraendert:
        parts.append(msg("sumMoveChanged", n=report.veraendert))
    if report.fehler:
        parts.append(msg("sumMoveErrors", n=report.fehler))
    return msg("sumMoveout", parts=parts)
