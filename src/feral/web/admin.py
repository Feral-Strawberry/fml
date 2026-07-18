"""Reine Datenfunktionen für den Admin-Bereich (Stufe 2A, ADR 0014).

Wie `library.py`: keine HTTP-Abhängigkeit, gut testbar. Lesende Funktionen
laufen auf kurzlebigen Verbindungen; schreibende werden von den Routen über
die Engine-Warteschlange bzw. `engine.run_write()` ausgeführt (ADR 0007).
"""

from __future__ import annotations

import json
import shutil

from .. import tools
import sqlite3
from pathlib import Path
from typing import Any

from ..interpret import PARSERS
from ..messages import load as msg_load

_TABLES = (
    "items", "file_locations", "raw_metadata", "interpreted_metadata",
    "scan_issues", "annotations", "tags", "item_tags",
)


def blocked_list(conn: sqlite3.Connection, *, limit: int = 500) -> list[dict[str, Any]]:
    """Die Sperrliste (ADR 0023/0041), neueste zuerst. ``last_paths`` = die
    beim Ablehnen gemerkten Fundort-Pfade (Basis für den Rausverschiebe-
    Dialog, I3); Alt-Einträge ohne Pfad-Wissen liefern eine leere Liste."""
    rows = conn.execute(
        """SELECT file_hash, reason, blocked_at, last_paths FROM blocked_hashes
            ORDER BY blocked_at DESC LIMIT ?""", (limit,),
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
    return out


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
    conn: sqlite3.Connection, *, db_path: str | Path, thumb_cache: str | Path
) -> dict[str, Any]:
    """Statusbild fürs Dashboard: DB, Cache, Werkzeuge, Parser — und als
    Kopf die **item-zentrischen** Kennzahlen aus `library.library_stats`
    (die EINE Quelle der Wahrheit, ADR 0029). Damit zeigen Galerie und Admin
    dieselben, an die Interpretation gekoppelten Zahlen; die rohen
    Tabellenzeilen (`tables`) bleiben nur als technisches Detail erhalten.
    """
    from . import library

    db_file = Path(db_path)
    wal = db_file.with_name(db_file.name + "-wal")
    tables = {
        name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]  # noqa: S608 — feste Liste
        for name in _TABLES
    }
    thumb_count, thumb_bytes = _dir_stats(Path(thumb_cache))
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
        "orphan_locations": len(orphan_locations(conn, limit=None)),
        "thumb_cache": str(Path(thumb_cache).resolve()),
        "thumb_count": thumb_count,
        "thumb_bytes": thumb_bytes,
        "ffprobe": _tool_found("ffprobe"),
        "ffmpeg": _tool_found("ffmpeg"),
        "parsers": [{"name": p.NAME, "version": p.VERSION} for p in PARSERS],
    }


def _dir_stats(root: Path) -> tuple[int, int]:
    """(Dateianzahl, Gesamtbytes) eines Verzeichnisbaums; (0, 0) wenn es fehlt."""
    count = size = 0
    if root.is_dir():
        for p in root.rglob("*"):
            if p.is_file():
                count += 1
                size += p.stat().st_size
    return count, size


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


# TIFF-basierte RAW-Formate: Alt-Bestand von VOR der RAW-Erkennung (ADR 0046)
# steht noch als »tiff« im Katalog — dort ist die Dateiendung die Wahrheit.
_TIFF_RAW_FORMATS = ("arw", "nef", "dng", "cr2")


def _import_rules_parts(rules: dict[str, Any] | None) -> list[tuple[str, str, list[Any]]]:
    """(Grund-Schlüssel, WHERE-Fragment über Alias ``i``, Parameter) je aktiver
    Regel. Maß-Regeln nur für Bilder mit bekannten Maßen (wie beim Import)."""
    from .filters import BASENAME

    if not rules:
        return []
    parts: list[tuple[str, str, list[Any]]] = []
    formate = rules.get("formate") or []
    if formate:
        marks = ", ".join("?" for _ in formate)
        frags = [f"i.container IN ({marks})"]
        params: list[Any] = list(formate)
        # Ausgeschlossene RAW-Formate treffen auch Alt-Items, die noch als
        # »tiff« katalogisiert sind (Feral Strawberrys Befund 2026-07-17: .ARW wurde
        # nur über »tiff« gefunden) — Suffix-Match auf den Fundort-Dateinamen,
        # damit kein Re-Scan nötig ist. Echte TIFFs bleiben unberührt.
        for ext in (f for f in formate if f in _TIFF_RAW_FORMATS):
            frags.append(
                f"(i.container = 'tiff' AND i.file_hash IN "
                f"(SELECT file_hash FROM file_locations WHERE {BASENAME} LIKE ?))"
            )
            params.append(f"%.{ext}")
        parts.append(("formate", "(" + " OR ".join(frags) + ")", params))
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
