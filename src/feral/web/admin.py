"""Reine Datenfunktionen für den Admin-Bereich (Stufe 2A, ADR 0014).

Wie `library.py`: keine HTTP-Abhängigkeit, gut testbar. Lesende Funktionen
laufen auf kurzlebigen Verbindungen; schreibende werden von den Routen über
die Engine-Warteschlange bzw. `engine.run_write()` ausgeführt (ADR 0007).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import threading
from datetime import datetime, timedelta, timezone

from .. import tools
import sqlite3
from pathlib import Path
from typing import Any, Callable
from importlib import metadata
import re

from ..db import connect
from ..interpret import PARSERS
from ..messages import load as msg_load

log = logging.getLogger(__name__)

_TABLES = (
    "items", "file_locations", "raw_metadata", "interpreted_metadata",
    "scan_issues", "annotations", "tags", "item_tags", "time_comments",
)


def _like_escape(q: str) -> str:
    """Suchtext für LIKE: `%` und `_` sind Zeichen, keine Platzhalter."""
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def blocked_page(
    conn: sqlite3.Connection, *, q: str | None = None, offset: int = 0, limit: int = 100
) -> dict[str, Any]:
    """Die Sperrliste (ADR 0023/0041) SEITENWEISE, neueste zuerst, mit
    ehrlichem Zähler (#66, A3 #107): ``total`` zählt alle Einträge, die zum
    Suchtext passen, ``total_all`` alle überhaupt. ``q`` sucht per LIKE in
    gemerkten Pfaden, Grund und Hash — kein FTS nötig (Messung 2026-09-13,
    20k Einträge: Zähler + Seite zusammen einstellige Millisekunden).
    ``last_paths`` = die beim Ablehnen gemerkten Fundort-Pfade (Basis für
    das Rausverschieben, I3); Alt-Einträge ohne Pfad-Wissen liefern []."""
    where, params = "", []
    if q:
        like = f"%{_like_escape(q.strip())}%"
        where = ("WHERE last_paths LIKE ? ESCAPE '\\' OR reason LIKE ? ESCAPE '\\' "
                 "OR file_hash LIKE ? ESCAPE '\\'")
        params = [like, like, like]
    total_all = conn.execute("SELECT COUNT(*) FROM blocked_hashes").fetchone()[0]
    total = (conn.execute(f"SELECT COUNT(*) FROM blocked_hashes {where}", params).fetchone()[0]  # noqa: S608
             if where else total_all)
    rows = conn.execute(
        f"""SELECT file_hash, reason, blocked_at, last_paths FROM blocked_hashes {where}
            ORDER BY blocked_at DESC, file_hash LIMIT ? OFFSET ?""",  # noqa: S608
        [*params, limit, offset],
    )
    out = []
    for r in rows:
        entry = dict(r)
        entry["last_paths"] = json.loads(entry["last_paths"]) if entry["last_paths"] else []
        # Meldungs-Dict oder roher Alt-Text (Block M.2, ADR 0054). Der
        # Alt-Wert „abgelehnt" (einziger je geschriebener Grund vor M.2)
        # wird beim Lesen auf seinen Schlüssel gemappt — keine Migration
        # nötig, Alt-Einträge erscheinen trotzdem übersetzt.
        entry["reason"] = ({"key": "blockedRejected"}
                           if entry["reason"] == "abgelehnt"
                           else msg_load(entry["reason"]))
        out.append(entry)
    return {"blocked": out, "total": total, "total_all": total_all,
            "offset": offset, "limit": limit}


def blocked_list(conn: sqlite3.Connection, *, limit: int = 500) -> list[dict[str, Any]]:
    """Kurzform: die ersten ``limit`` Sperr-Einträge (Importer-Tests)."""
    return blocked_page(conn, limit=limit)["blocked"]


def unblock(conn: sqlite3.Connection, file_hash: str | None) -> int:
    """Sperr-Eintrag entfernen (None = alle) — danach ist Re-Import möglich.

    Räumt auch das Stat-Gedächtnis der gesperrten Pfade ab (Migration 0019):
    sonst würde der Watcher die entsperrten Dateien weiter überspringen und
    der Re-Import fände sie nie."""
    if file_hash is None:
        conn.execute("DELETE FROM scan_memory WHERE file_hash IS NOT NULL")
        cur = conn.execute("DELETE FROM blocked_hashes")
    else:
        conn.execute("DELETE FROM scan_memory WHERE file_hash = ?", (file_hash,))
        cur = conn.execute("DELETE FROM blocked_hashes WHERE file_hash = ?", (file_hash,))
    conn.commit()
    return cur.rowcount


def _tool_found(name: str) -> bool:
    # Frisch suchen (Cache leeren): Nach einer Installation soll der
    # Status-Reiter das Werkzeug ohne Server-Neustart finden.
    tools.refresh()
    return tools.find_binary(name) is not None


def admin_info(
    conn: sqlite3.Connection, *, db_path: str | Path, thumb_cache: str | Path,
    log_dir: str | Path | None = None, slow: SlowCounts | None = None,
) -> dict[str, Any]:
    """Statusbild fürs Dashboard: DB, Cache, Werkzeuge, Parser — und als
    Kopf die **item-zentrischen** Kennzahlen aus `library.library_stats`
    (die EINE Quelle der Wahrheit, ADR 0029). Damit zeigen Galerie und Admin
    dieselben, an die Interpretation gekoppelten Zahlen; die rohen
    Tabellenzeilen (`tables`) bleiben nur als technisches Detail erhalten.

    Nur billige Zugriffe (#118, ADR 0077): verwaiste Fundorte und
    Cache-Größe kommen als **gemerkter Stand** aus ``slow`` (``orphans``/
    ``cache`` je ``None`` = noch nie gezählt, ``checking`` = läuft gerade im
    Hintergrund) — nie als Platten-Lauf beim Seitenaufruf.
    """
    from . import library

    db_file = Path(db_path)
    wal = db_file.with_name(db_file.name + "-wal")
    tables = {
        name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]  # noqa: S608 — feste Liste
        for name in _TABLES
    }
    stand = slow.snapshot() if slow is not None else SlowCounts.EMPTY
    return {
        "stats": library.library_stats(conn),
        "db_path": str(db_file.resolve()),
        "db_bytes": db_file.stat().st_size if db_file.is_file() else 0,
        "wal_bytes": wal.stat().st_size if wal.is_file() else 0,
        "schema_version": conn.execute("PRAGMA user_version").fetchone()[0],
        "tables": tables,
        "open_issues": conn.execute(
            "SELECT COUNT(*) FROM scan_issues WHERE resolved = 0"
        ).fetchone()[0],
        # Sperrlisten-Zähler vom Server (ADR 0034 Nachtrag): die Liste selbst
        # ist gedeckelt, die Hinweiskarte der Übersicht braucht die echte Zahl.
        "blocked_count": conn.execute("SELECT COUNT(*) FROM blocked_hashes").fetchone()[0],
        "thumb_cache": str(Path(thumb_cache).resolve()),
        "log_dir": str(Path(log_dir).resolve()) if log_dir else None,
        "orphans": stand["orphans"],
        "cache": stand["cache"],
        "checking": stand["checking"],
        "ffprobe": _tool_found("ffprobe"),
        "ffmpeg": _tool_found("ffmpeg"),
        "parsers": [{"name": p.NAME, "version": p.VERSION} for p in PARSERS],
    }


def overview_stats(
    conn: sqlite3.Connection, *, db_path: str | Path, library_root: str | Path | None,
    days: int = 30, now: datetime | None = None,
) -> dict[str, Any]:
    """Zahlen für die Diagramme der Admin-Übersicht (ADR 0074 Nachtrag,
    Mockup Runde 3): Zusammensetzung nach Art (Bilder/Videos mit Bytes),
    Jahrgänge nach Erstelldatum, Zuwachs je Tag der letzten ``days`` Tage
    und der Speicherplatz der Laufwerke von Datenbank und Media Library.
    Reine Lesezugriffe über die vorhandenen Indizes (Messung 2026-09-12,
    250k Items: Art 47 ms, Jahrgänge 47 ms, Zuwachs 9 ms); die
    Typ-Zusammensetzung kommt aus ``library_stats`` (``by_container``).
    ``now`` (UTC) ist für Tests injizierbar: EIN Zeitpunkt für Fenster und
    letzten Tag, kein Kippen an der Tagesgrenze (#180).
    """
    now = now or datetime.now(timezone.utc)
    by_kind = [
        {"kind": row[0], "count": row[1], "bytes": row[2]}
        for row in conn.execute(
            "SELECT media_kind, COUNT(*), COALESCE(SUM(file_size), 0) FROM items "
            "GROUP BY media_kind ORDER BY 2 DESC"
        ).fetchall()
    ]
    by_year = [
        {"year": row[0], "count": row[1]}          # year None = ohne Datum
        for row in conn.execute(
            "SELECT substr(media_date, 1, 4) AS y, COUNT(*) FROM items "
            "GROUP BY y ORDER BY y"
        ).fetchall()
    ]
    since = (now - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    per_day = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT substr(first_seen_at, 1, 10) AS d, COUNT(*) FROM items "
            "WHERE first_seen_at >= ? GROUP BY d ORDER BY d", (since,)
        ).fetchall()
    }
    today = now.date()
    growth = [
        {"day": (d := (today - timedelta(days=days - 1 - i)).isoformat()), "count": per_day.get(d, 0)}
        for i in range(days)
    ]
    disks = []
    seen: set[str] = set()
    for label, path in (("db", db_path), ("library", library_root)):
        if not path:
            continue
        target = Path(path).resolve().parent if label == "db" else Path(path)
        try:
            usage = shutil.disk_usage(target)
            # Gleiches Laufwerk = gleiche Geräte-ID (Windows: Volume-Seriennummer).
            # Früher: gleiche Gesamt-/Frei-Zahlen — schrieb ein anderer Prozess
            # zwischen den beiden Abfragen, erschien dieselbe Platte doppelt (#180).
            key = str(os.stat(target).st_dev)
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        disks.append({"for": label, "path": str(path), "total": usage.total,
                      "used": usage.used, "free": usage.free})
    return {"by_kind": by_kind, "by_year": by_year, "growth": growth, "disks": disks}


def _dir_stats(root: Path) -> tuple[int, int]:
    """(Dateianzahl, Gesamtbytes) eines Verzeichnisbaums; (0, 0) wenn es fehlt."""
    count = size = 0
    if root.is_dir():
        for p in root.rglob("*"):
            if p.is_file():
                count += 1
                size += p.stat().st_size
    return count, size


# -- Gemerkter Stand der teuren Kennzahlen (#118, ADR 0077) ----------------------
#
# Verwaiste Fundorte (ein stat je Fundort) und Thumbnail-Cache (Verzeichnis-
# lauf) kosteten bei 70k Fundorten zusammen 7,6 s — bei JEDEM Aufruf von
# Übersicht und Wartung. Beide Zahlen ändern sich nur durch Aufgaben, die
# fml selbst ausführt (Aufräumen, Thumbnails erstellen, Cache leeren,
# Import), oder durch äußere Eingriffe, die ohnehin niemand live sieht.
# Deshalb ein gemerkter Stand mit Zeitstempel: neu gerechnet auf Klick
# (synchron, mit sichtbarem „wird geprüft …") oder nach passenden Aufgaben
# im Hintergrund — nie beim Seitenladen. Nur im Speicher; ein Neustart
# beginnt mit „noch nicht geprüft".


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# app_state (Migration 0024): Schlüssel-Wert-Ablage für Zustand, der einen
# Neustart überleben soll. Werte sind JSON; Schreiben läuft über die Routen
# per engine.run_write() (ADR 0067), Lesen auf jeder Verbindung.

def read_app_state(conn: sqlite3.Connection, key: str) -> Any:
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row[0])
    except ValueError:
        return None


def write_app_state(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO app_state (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, json.dumps(value, ensure_ascii=False), _now_iso()),
    )


class SlowCounts:
    """Gemerkter Stand von ``orphans`` (verwaiste Fundorte) und ``cache``
    (Thumbnail-Dateien + Bytes), je mit Zeitstempel ``at``.

    Überlebt Neustarts (ADR-0077-Nachtrag): jeder gesetzte Stand geht mit
    einem **Herkunftsstempel** (Rechnername + Cache-Pfad) über ``persist``
    nach ``app_state``; ``load()`` nimmt beim Start nur Stände mit passendem
    Stempel zurück — eine mitgereiste Datenbank (portabler Modus) zeigt
    sonst Zahlen eines anderen Rechners.
    """

    KEYS = ("orphans", "cache")
    EMPTY: dict[str, Any] = {"orphans": None, "cache": None, "checking": []}
    STATE_PREFIX = "slow."

    def __init__(self, db_path: str | Path, thumb_cache: str | Path, *,
                 persist: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        self._db_path = str(db_path)
        self._thumb_cache = Path(thumb_cache)
        self._persist = persist
        self._lock = threading.Lock()
        self._stand: dict[str, dict[str, Any] | None] = {"orphans": None, "cache": None}
        self._checking: set[str] = set()     # läuft gerade im Hintergrund
        self._again: set[str] = set()        # Wunsch kam während eines Laufs

    def stamp(self) -> dict[str, str]:
        """Herkunft eines Standes: dieser Rechner, dieser Cache-Ordner."""
        return {"host": socket.gethostname(), "cache": str(self._thumb_cache.resolve())}

    def load(self, conn: sqlite3.Connection) -> None:
        """Gemerkte Stände aus ``app_state`` übernehmen (nur mit passendem Stempel)."""
        stamp = self.stamp()
        for key in self.KEYS:
            value = read_app_state(conn, self.STATE_PREFIX + key)
            if not isinstance(value, dict) or value.get("stamp") != stamp:
                continue
            stand = {k: v for k, v in value.items() if k != "stamp"}
            if "count" in stand and "at" in stand:
                with self._lock:
                    self._stand[key] = stand

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"orphans": self._stand["orphans"], "cache": self._stand["cache"],
                    "checking": sorted(self._checking)}

    # -- setzen (Ergebnis liegt schon vor) --------------------------------------

    def _set(self, key: str, stand: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._stand[key] = stand
        if self._persist is not None:
            try:
                self._persist(self.STATE_PREFIX + key, {**stand, "stamp": self.stamp()})
            except Exception:
                log.warning("State %s not persisted (kept in memory until restart)",
                            key, exc_info=True)
        return stand

    def set_orphans(self, count: int) -> dict[str, Any]:
        return self._set("orphans", {"count": int(count), "at": _now_iso()})

    def set_cache(self, count: int, size: int) -> dict[str, Any]:
        return self._set("cache", {"count": int(count), "bytes": int(size), "at": _now_iso()})

    # -- synchron zählen (Klick) ------------------------------------------------

    def count_orphans(self, conn: sqlite3.Connection) -> dict[str, Any]:
        return self.set_orphans(len(orphan_locations(conn, limit=None)))

    def count_cache(self) -> dict[str, Any]:
        return self.set_cache(*_dir_stats(self._thumb_cache))

    # -- im Hintergrund zählen (nach Aufgaben) -----------------------------------

    def refresh_later(self, *keys: str) -> None:
        """Je Schlüssel höchstens EIN Lauf gleichzeitig; kommt währenddessen
        ein zweiter Wunsch (Aufgabenserie), läuft danach genau eine Runde
        nach. Der Thread ist ein Daemon: beim Beenden wartet niemand."""
        for key in keys:
            if key not in self.KEYS:
                raise ValueError(f"unbekannter Zähler: {key}")
            with self._lock:
                if key in self._checking:
                    self._again.add(key)
                    continue
                self._checking.add(key)
            threading.Thread(target=self._run, args=(key,), daemon=True,
                             name=f"fml-slow-{key}").start()

    def _run(self, key: str) -> None:
        while True:
            try:
                if key == "orphans":
                    conn = connect(self._db_path)
                    try:
                        self.count_orphans(conn)
                    finally:
                        conn.close()
                else:
                    self.count_cache()
            except Exception:
                log.exception("Background count %s failed", key)
            with self._lock:
                if key in self._again:
                    self._again.discard(key)
                    continue
                self._checking.discard(key)
                return

    def wait_idle(self, timeout: float = 10.0) -> bool:
        """Auf laufende Hintergrund-Zählungen warten (Tests)."""
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if not self._checking:
                    return True
            time.sleep(0.01)
        return False


# -- Wartungsseite (A3, #107) ---------------------------------------------------


def maintenance_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Zahlen für die Wartungskarten — nur billige Lesezugriffe (Messung
    2026-09-13, 250k Items / 2,5 Mio. Schicht-2-Zeilen, siehe ADR-0074-
    Nachtrag A3): Items je Parser (``ordinal = 0`` = genau eine Zeile je
    Item und Parser), Items ohne Erstelldatum (Index ``idx_items_media_date``),
    offene Probleme und Sperrlisten-Einträge. Registrierte Parser ohne
    Treffer erscheinen mit 0, damit die Liste die Registry zeigt."""
    counts = dict(conn.execute(
        """SELECT parser, COUNT(*) FROM interpreted_metadata
            WHERE ordinal = 0 GROUP BY parser"""
    ).fetchall())
    parsers = [{"parser": p.NAME, "version": p.VERSION, "items": counts.pop(p.NAME, 0)}
               for p in PARSERS]
    # Parser, die es nicht mehr gibt (Alt-Zeilen): ehrlich mitzeigen.
    parsers += [{"parser": name, "version": None, "items": n} for name, n in counts.items()]
    parsers.sort(key=lambda p: (-p["items"], p["parser"]))
    return {
        "parsers": parsers,
        # Ob die DB-Aufteilung überhaupt geht: der Knopf erscheint nur dann
        # (Befund 2026-09-13: Windows-Python ohne dbstat, Knopf produzierte
        # nur die Fehlermeldung). PRAGMA compile_options ist kostenlos.
        "dbstat": dbstat_available(conn),
        "undated": conn.execute(
            "SELECT COUNT(*) FROM items WHERE media_date IS NULL").fetchone()[0],
        "open_issues": conn.execute(
            "SELECT COUNT(*) FROM scan_issues WHERE resolved = 0").fetchone()[0],
        "blocked_count": conn.execute("SELECT COUNT(*) FROM blocked_hashes").fetchone()[0],
    }


# Zuordnung Tabelle → Gruppe der DB-Aufteilung (Mockup Runde 3: Roh-Blobs /
# Items + Fundorte / Schicht 2 / Suchindex / Rest). Indizes zählen zur
# Tabelle, an der sie hängen; Freie Seiten kommen aus PRAGMA freelist_count.
_DB_GROUPS: dict[str, str] = {
    "raw_metadata": "raw",
    "items": "items", "file_locations": "file_locations",
    "interpreted_metadata": "interpreted",
}
_DB_GROUP_ORDER = ("raw", "items", "interpreted", "search", "other")


def dbstat_available(conn: sqlite3.Connection) -> bool:
    """Hat der SQLite-Build die virtuelle Tabelle ``dbstat``
    (``SQLITE_ENABLE_DBSTAT_VTAB``)? Python-Builds unterscheiden sich je
    Plattform; ohne sie bietet die Wartung die Aufteilung gar nicht erst an."""
    options = {r[0] for r in conn.execute("PRAGMA compile_options")}
    return "ENABLE_DBSTAT_VTAB" in options


def db_breakdown(conn: sqlite3.Connection) -> dict[str, Any]:
    """Aufteilung der Datenbankdatei nach Inhalt über die virtuelle Tabelle
    ``dbstat`` im aggregierten Modus (eine Zeile je Tabelle/Index statt je
    Seite). Liest trotzdem die GANZE Datei — deshalb nur auf Knopfdruck
    (Wartung → Datenbank), nie im Seitenladen (Messung 2026-09-13,
    ADR-0074-Nachtrag A3). Fehlt ``SQLITE_ENABLE_DBSTAT_VTAB`` im
    SQLite-Build (fremde Python-Builds), meldet die Antwort ehrlich
    ``available: False`` statt zu raten. Dateigröße und WAL kommen aus
    ``admin_info`` (im WAL-Modus liegen frische Seiten in der -wal-Datei)."""
    try:
        rows = conn.execute(
            "SELECT name, SUM(pgsize) FROM dbstat('main', 1) GROUP BY name"
        ).fetchall()
    except sqlite3.OperationalError:
        return {"available": False}
    owner = {r[0]: r[1] for r in conn.execute(
        "SELECT name, tbl_name FROM sqlite_master WHERE type IN ('table', 'index')")}
    groups = {k: 0 for k in _DB_GROUP_ORDER}
    index_bytes = 0
    for name, size in rows:
        table = owner.get(name, name)
        if table.startswith("search_index"):
            key = "search"
        elif table in _DB_GROUPS:
            key = _DB_GROUPS[table]
            key = "items" if key == "file_locations" else key
        else:
            key = "other"
        groups[key] += size or 0
        if name != table:
            index_bytes += size or 0
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    free_bytes = conn.execute("PRAGMA freelist_count").fetchone()[0] * page_size
    return {
        "available": True,
        "free_bytes": free_bytes,
        "index_bytes": index_bytes,
        "groups": [{"key": k, "bytes": groups[k]} for k in _DB_GROUP_ORDER],
    }


def list_issues(conn: sqlite3.Connection, *, limit: int = 200) -> list[dict[str, Any]]:
    """Offene Scan-Probleme, jüngste zuerst."""
    rows = conn.execute(
        """SELECT id, path, kind, message, last_seen_at FROM scan_issues
            WHERE resolved = 0 ORDER BY last_seen_at DESC, id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) | {"message": msg_load(r["message"])} for r in rows]


def issue_overview(conn: sqlite3.Connection, *, per_kind: int = 20) -> dict[str, Any]:
    """Offene Probleme gruppiert nach Fehlerart (Block N): ehrliche
    Gesamtzahl + je Art Zähler und nur die jüngsten ``per_kind`` Einträge.
    So bleibt das Overlay auch bei tausenden Fehlern bedienbar, ohne dass
    Zahlen unterschlagen werden (Feral Strawberrys Laufwerks-Test: >2000)."""
    kinds = []
    for kind, count in conn.execute(
        """SELECT kind, COUNT(*) FROM scan_issues WHERE resolved = 0
            GROUP BY kind ORDER BY COUNT(*) DESC, kind"""
    ).fetchall():
        rows = conn.execute(
            """SELECT id, path, kind, message, last_seen_at FROM scan_issues
                WHERE resolved = 0 AND kind = ?
                ORDER BY last_seen_at DESC, id DESC LIMIT ?""",
            (kind, per_kind),
        ).fetchall()
        kinds.append({"kind": kind, "count": count,
                      "issues": [dict(r) | {"message": msg_load(r["message"])}
                                 for r in rows]})
    return {"total": sum(k["count"] for k in kinds), "kinds": kinds}


def resolve_issues(
    conn: sqlite3.Connection, *, issue_id: int | None = None, kind: str | None = None
) -> int:
    """Quittiere ein Problem, eine ganze Fehlerart oder alle (Block N).
    Gibt die Anzahl der quittierten Einträge zurück."""
    if issue_id is not None:
        cur = conn.execute(
            "UPDATE scan_issues SET resolved = 1 WHERE id = ? AND resolved = 0",
            (issue_id,),
        )
    elif kind is not None:
        cur = conn.execute(
            "UPDATE scan_issues SET resolved = 1 WHERE kind = ? AND resolved = 0",
            (kind,),
        )
    else:
        cur = conn.execute("UPDATE scan_issues SET resolved = 1 WHERE resolved = 0")
    conn.commit()
    return cur.rowcount


def orphan_locations(
    conn: sqlite3.Connection, *, limit: int | None = 50, under: str | None = None
) -> list[dict[str, Any]]:
    """Fundorte, deren Pfad nicht mehr existiert (Datei verschoben/gelöscht).

    ``under`` schränkt auf Pfade unterhalb eines Ordners ein (ADR 0033):
    „nicht existent“ kann auch „gerade nicht erreichbar“ heißen (ausgehängte
    Platte, nicht gemountetes NAS) — pfad-bezogen aufräumen schützt davor,
    korrekte Fundorte auf Offline-Speichern wegzuwerfen.
    """
    scope = Path(under) if under else None
    rows = conn.execute("SELECT id, path FROM file_locations ORDER BY id").fetchall()
    orphans = [
        dict(r) for r in rows
        if (scope is None or Path(r["path"]).is_relative_to(scope))
        and not Path(r["path"]).is_file()
    ]
    return orphans if limit is None else orphans[:limit]


def prune_orphan_locations(conn: sqlite3.Connection, *, under: str | None = None) -> int:
    """Entferne verwaiste Fundort-Einträge (optional nur unterhalb ``under``).
    Items (und ihre Metadaten) bleiben — gelöscht wird nur die
    Pfad-Buchhaltung, nie etwas an Mediendateien."""
    ids = [o["id"] for o in orphan_locations(conn, limit=None, under=under)]
    with conn:
        conn.executemany("DELETE FROM file_locations WHERE id = ?", [(i,) for i in ids])
    return len(ids)


def clear_thumb_cache(thumb_cache: str | Path) -> int:
    """Leere den Thumbnail-Cache (inkl. `.fail`-Marker). Gibt die Anzahl gelöschter
    Dateien zurück. Gefahrlos: Thumbnails regenerieren sich beim Ansehen (ADR 0013)."""
    root = Path(thumb_cache)
    count, _ = _dir_stats(root)
    if root.is_dir():
        shutil.rmtree(root)
    return count


# -- Import-Regeln auf den Bestand (ADR 0046) --------------------------------------
#
# Dieselben Regeln, die Import/Scan künftig anwenden, rückwirkend auf schon
# katalogisierte Items: Vorschau (Zahlen je Grund) + Sammel-Ablehnen über die
# bestehende Mechanik (bulk._apply_reject via apply_bulk) — Originale bleiben
# unangetastet („Original heilig", ADR 0041), Entsperren macht es rückgängig.


def _import_rules_parts(rules: dict[str, Any] | None) -> list[tuple[str, str, list[Any]]]:
    """(Grund-Schlüssel, WHERE-Fragment über Alias ``i``, Parameter) je aktiver
    Regel. Maß-Regeln nur für Bilder mit bekannten Maßen (wie beim Import);
    ``datum`` = ohne plausibles Erstelldatum (ADR 0075)."""
    from .filters import BASENAME, _escape_like

    if not rules:
        return []
    parts: list[tuple[str, str, list[Any]]] = []
    formate = rules.get("formate") or []
    if formate:
        marks = ", ".join("?" for _ in formate)
        # Container ODER Dateiendung eines Fundorts — wie beim Scan
        # (importer.filter_reason). Die Endung trifft auch Alt-Bestand, der
        # unter falschem Container steht: RAW von vor der RAW-Erkennung als
        # »tiff« (Befund 2026-07-17), Windows-Sprachdateien als »mp3« (#159).
        # LIKE ist für ASCII groß/klein-unabhängig (.ARW = .arw).
        likes = " OR ".join(f"{BASENAME} LIKE ? ESCAPE '\\'" for _ in formate)
        frag = (f"(i.container IN ({marks}) OR i.file_hash IN "
                f"(SELECT file_hash FROM file_locations WHERE {likes}))")
        params: list[Any] = [*formate, *(f"%.{_escape_like(f)}" for f in formate)]
        parts.append(("formate", frag, params))
    guard = ("i.media_kind = 'image' AND i.width IS NOT NULL "
             "AND i.height IS NOT NULL AND i.height > 0 AND i.width > 0")
    if rules.get("min_kante"):
        parts.append(("min_kante",
                      f"({guard} AND MIN(i.width, i.height) < ?)",
                      [int(rules["min_kante"])]))
    if rules.get("max_kante"):
        parts.append(("max_kante",
                      f"({guard} AND MAX(i.width, i.height) > ?)",
                      [int(rules["max_kante"])]))
    if rules.get("min_date"):
        # Datumsregel (ADR 0075, #113): Items ohne plausibles Datum. NULL
        # heißt nach dem (automatischen) Backfill genau das — weder
        # Metadaten noch Dateistempel liegen im Fenster [min_date, jetzt].
        parts.append(("datum", "i.media_date IS NULL", []))
    return parts


def import_rules_overview(
    conn: sqlite3.Connection, rules: dict[str, Any] | None
) -> dict[str, Any]:
    """Vorschau: wie viele Bestand-Items träfen die aktuellen Import-Regeln?

    ``counts`` je Grund (Überschneidungen möglich), ``total`` = eindeutige
    Items. ``active`` = False, wenn gar keine Regel konfiguriert ist.
    """
    parts = _import_rules_parts(rules)
    counts = {
        key: conn.execute(f"SELECT COUNT(*) FROM items i WHERE {frag}", params).fetchone()[0]
        for key, frag, params in parts
    }
    if parts:
        ors = " OR ".join(frag for _, frag, _ in parts)
        params = [p for _, _, ps in parts for p in ps]
        total = conn.execute(
            f"SELECT COUNT(*) FROM items i WHERE {ors}", params
        ).fetchone()[0]
    else:
        total = 0
    return {"active": bool(parts), "rules": rules or {}, "counts": counts, "total": total}


def apply_import_rules(
    conn: sqlite3.Connection, rules: dict[str, Any] | None,
    thumb_cache: str | Path | None,
) -> int:
    """Alle Bestand-Treffer der Import-Regeln ablehnen (Sperrliste, ADR 0023/
    0041). Gibt die Zahl der abgelehnten Items zurück; ohne aktive Regel 0."""
    from .bulk import apply_bulk

    parts = _import_rules_parts(rules)
    if not parts:
        return 0
    ors = " OR ".join(frag for _, frag, _ in parts)
    params = [p for _, _, ps in parts for p in ps]
    hashes = [r[0] for r in conn.execute(
        f"SELECT i.file_hash FROM items i WHERE {ors}", params
    )]
    if not hashes:
        return 0
    summary = apply_bulk(conn, hashes=hashes, reject=True, thumb_cache=thumb_cache)
    return int(summary.get("rejected", 0))


# -- Laufzeit-Pakete für die Instanz-Kachel (Issue #42, ADR 0080) ----------------

#: Die direkten Laufzeit-Abhängigkeiten aus requirements.txt (Einträge mit
#: ``# direct``, ohne pip; DEPENDENCIES.md, ADR 0082). tests/test_dependencies.py
#: hält die Liste gleich mit dem Lock.
RUNTIME_PACKAGES = ("Pillow", "fastapi", "uvicorn", "starlette", "anyio", "pydantic")
_PIN_LINE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([A-Za-z0-9.*+!-]+)")


def read_pins(requirements: Path | None) -> dict[str, str]:
    """``name -> version`` der ``==``-Pins einer requirements-Datei (Name
    kleingeschrieben); fehlende Datei = keine Pins."""
    if requirements is None or not Path(requirements).is_file():
        return {}
    pins: dict[str, str] = {}
    for line in Path(requirements).read_text(encoding="utf-8").splitlines():
        m = _PIN_LINE.match(line.split("#", 1)[0])
        if m:
            pins[m.group(1).lower()] = m.group(2)
    return pins


def package_versions(requirements: Path | None = None,
                     names: tuple[str, ...] = RUNTIME_PACKAGES) -> list[dict[str, Any]]:
    """Installierte Version je Laufzeit-Paket neben dem Pin aus
    ``requirements.txt``: ``{name, installed, pinned, ok}``. ``installed``
    ist None, wenn das Paket im venv fehlt; ``ok`` heißt: installiert und
    entweder ohne Pin oder gleich dem Pin (Drift nach ``git pull`` ohne
    ``pip install -r`` wird so im Admin sichtbar)."""
    pins = read_pins(requirements)
    out = []
    for name in names:
        try:
            installed: str | None = metadata.version(name)
        except metadata.PackageNotFoundError:
            installed = None
        pinned = pins.get(name.lower())
        out.append({"name": name, "installed": installed, "pinned": pinned,
                    "ok": installed is not None and (pinned is None or installed == pinned)})
    return out
