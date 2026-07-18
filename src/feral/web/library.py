"""Reine Datenfunktionen für die Web-Oberfläche (ohne HTTP, gut testbar).

Stellt den Server-seitigen Ordner-Browser, die Bestands-Statistik und eine simple
Suche bereit. Die FastAPI-Routen in `app.py` sind nur dünne Hüllen darum.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

from ..db import manual
from . import filters
from .cache import EpochCache
from typing import Any


def list_roots() -> list[dict[str, str]]:
    """Sinnvolle Einstiegspunkte ins Dateisystem (Laufwerke, Home).

    macOS/Linux: Wurzel ``/`` plus gemountete Laufwerke unter ``/Volumes`` sowie
    das Home-Verzeichnis. Windows: die Laufwerksbuchstaben.
    """
    roots: list[dict[str, str]] = []
    # Projekt-/Arbeitsordner zuerst: ohne konfigurierte Scan-Orte (frische
    # Installation, ADR 0029) hat der Nutzer so immer einen konkreten,
    # existierenden Startpunkt zum Durchklicken — statt ins Leere zu zeigen.
    cwd = Path.cwd()
    roots.append({"name": f"📂 {cwd.name or 'Arbeitsordner'}", "path": str(cwd)})
    home = Path.home()
    if home != cwd:
        roots.append({"name": f"🏠 {home.name or 'Home'}", "path": str(home)})

    if sys.platform == "win32":
        import string

        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            if drive.exists():
                roots.append({"name": f"{letter}:\\", "path": str(drive)})
    else:
        roots.append({"name": "/ (Wurzel)", "path": "/"})
        volumes = Path("/Volumes")
        if volumes.is_dir():
            for entry in sorted(volumes.iterdir()):
                if entry.is_dir():
                    roots.append({"name": f"💾 {entry.name}", "path": str(entry)})
    return roots


# (describe_locations — die „Festen Scan-Orte" — ist mit dem Watchordner-Block
# entfallen: das Konzept stand als konkurrierende Ordner-Liste neben den
# Watchordnern. Einstiegspunkte in den Browser sind jetzt immer list_roots().)


def browse_directory(path: str | Path) -> dict[str, Any]:
    """Liste die Unterordner eines Verzeichnisses (für die Ordner-Navigation).

    Gibt den aufgelösten Pfad, den Elternpfad (oder ``None`` an der Wurzel), die
    Unterordner und die Anzahl Dateien direkt in diesem Ordner zurück. Wirft
    `NotADirectoryError`, wenn `path` kein Verzeichnis ist.
    """
    p = Path(path).expanduser()
    try:
        p = p.resolve()
    except OSError:
        pass
    if not p.is_dir():
        raise NotADirectoryError(f"Kein Verzeichnis: {p}")

    subdirs: list[dict[str, str]] = []
    file_count = 0
    # Defensive Iteration: einzelne unzugängliche Einträge überspringen.
    try:
        entries = sorted(p.iterdir(), key=lambda e: e.name.lower())
    except PermissionError:
        entries = []
    for entry in entries:
        try:
            if entry.is_dir():
                subdirs.append({"name": entry.name, "path": str(entry)})
            elif entry.is_file():
                file_count += 1
        except OSError:
            continue

    parent = str(p.parent) if p.parent != p else None
    return {
        "path": str(p),
        "parent": parent,
        "subdirs": subdirs,
        "file_count": file_count,
    }


def library_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Kennzahlen über den Bestand für die Übersichtsanzeige.

    ``total_bytes`` summiert ``file_size`` über alle Items (je Item einmal,
    unabhängig von der Zahl der Fundorte); leerer Bestand ergibt 0.
    Seit I2 (ADR 0041) getrennt ausgewiesen: ``library_items``/``library_bytes``
    zählen Items mit mindestens einem Fundort unter ``library.root`` —
    ``library_configured`` sagt, ob die Unterscheidung überhaupt existiert.
    """
    total_items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    total_bytes = conn.execute(
        "SELECT COALESCE(SUM(file_size), 0) FROM items"
    ).fetchone()[0]
    lib_prefix = filters.library_like_prefix()
    library_items = library_bytes = 0
    if lib_prefix is not None:
        library_items, library_bytes = conn.execute(
            f"""SELECT COUNT(*), COALESCE(SUM(file_size), 0) FROM items
                 WHERE file_hash IN (SELECT file_hash FROM file_locations
                                      WHERE {filters.NORM_PATH} LIKE ? ESCAPE '\\')""",
            (lib_prefix,),
        ).fetchone()
    total_locations = conn.execute("SELECT COUNT(*) FROM file_locations").fetchone()[0]
    multi_location = conn.execute(
        """SELECT COUNT(*) FROM (SELECT file_hash FROM file_locations
            GROUP BY file_hash HAVING COUNT(*) > 1)"""
    ).fetchone()[0]
    # EXISTS-Proben über die Hash-Indizes statt COUNT(DISTINCT): Letzteres
    # liest die kompletten Blob-Tabellen (bei Feral Strawberry 1,4 GB) — pro Aufruf!
    with_metadata = conn.execute(
        """SELECT COUNT(*) FROM items i
            WHERE EXISTS (SELECT 1 FROM raw_metadata r WHERE r.file_hash = i.file_hash)"""
    ).fetchone()[0]
    interpreted = conn.execute(
        """SELECT COUNT(*) FROM items i
            WHERE EXISTS (SELECT 1 FROM interpreted_metadata m WHERE m.file_hash = i.file_hash)"""
    ).fetchone()[0]
    by_container = [
        {"container": row["container"], "count": row["n"]}
        for row in conn.execute(
            "SELECT container, COUNT(*) AS n FROM items "
            "GROUP BY container ORDER BY n DESC"
        ).fetchall()
    ]
    return {
        "total_items": total_items,
        "items_multi_location": multi_location,
        "total_bytes": total_bytes,
        "total_locations": total_locations,
        "library_configured": lib_prefix is not None,
        "library_items": library_items,
        "library_bytes": library_bytes,
        "items_with_metadata": with_metadata,
        "items_interpreted": interpreted,
        "by_container": by_container,
    }


# Zweistufen-/Zwei-Sichten-Workflows (Block N, ADR 0043): mehrere Modell-
# Rohnamen sind Stufen bzw. Sichten DERSELBEN Generierung — jedes Item
# erschiene doppelt in „Nach Modell". Kanonisierung NUR in Anzeige/Facette;
# Rohwerte bleiben unangetastet. KEIN allgemeines Varianten-Mapping
# (4L-Entscheidung gilt weiter) — nur die hier gelisteten, konkreten Marker:
# WAN 2.2 High/Low-Noise (ADR 0043) und Ideogram „unconditional" (Feral Strawberry,
# 2026-07-16 — gleiche Bilder tauchten mit und ohne Marker auf). Die
# Sicherung greift für beide: gefaltet wird erst, wenn dadurch >1 Rohname
# kollidiert — ein einzelner Name mit Marker bleibt roh stehen.
_STAGE_MARKERS = (
    re.compile(r"[\s._-]*(?:high|low)[\s._-]*noise", re.IGNORECASE),
    re.compile(r"[\s._-]*unconditional", re.IGNORECASE),
)


def canonical_model(name: str) -> str:
    """Anzeige-Schlüssel eines Modellnamens: Stufen-/Sichten-Marker weggekürzt."""
    collapsed = name
    for marker in _STAGE_MARKERS:
        collapsed = marker.sub("", collapsed)
    collapsed = collapsed.strip()
    return collapsed or name


def _fold_noise_stages(
    conn: sqlite3.Connection, merged: dict[str, list]
) -> dict[str, tuple[int, str, list[str] | None]]:
    """Kollidierende Stufen-Namen zu EINEM Facetten-Eintrag zusammenlegen.

    Nur Namensgruppen mit >1 Rohwert werden gefaltet — einzelne Namen bleiben
    roh (auch wenn sie einen Stufenmarker tragen). Weil ein Zweistufen-Item
    BEIDE Modell-Zeilen trägt, darf nicht aufsummiert werden: je Gruppe eine
    gezielte Nachzählung (COUNT über DISTINCT Items, beide Quellen mit der
    Override-Regel aus ADR 0022). Gruppen sind selten (die paar WAN-Namen),
    die Nachzähl-Query läuft nur über deren Zeilen.
    """
    groups: dict[str, list[str]] = {}
    for name in merged:
        groups.setdefault(canonical_model(name), []).append(name)
    out: dict[str, tuple[int, str, list[str] | None]] = {}
    for canon, names in groups.items():
        if len(names) == 1:
            count, last = merged[names[0]]
            out[names[0]] = (count, last, None)
            continue
        marks = ", ".join("?" for _ in names)
        row = conn.execute(
            f"""SELECT COUNT(*) AS n, MAX(last) AS last FROM (
                  SELECT a.file_hash AS fh, MAX(COALESCE(i.media_date, '')) AS last
                    FROM annotations a JOIN items i ON i.file_hash = a.file_hash
                   WHERE a.model IN ({marks}) GROUP BY a.file_hash
                  UNION
                  SELECT m.file_hash, MAX(COALESCE(i.media_date, ''))
                    FROM interpreted_metadata m JOIN items i ON i.file_hash = m.file_hash
                   WHERE m.field = 'model' AND m.value_text IN ({marks})
                     AND m.file_hash NOT IN (SELECT file_hash FROM annotations
                                              WHERE model IS NOT NULL)
                   GROUP BY m.file_hash)""",
            (*names, *names),
        ).fetchone()
        out[canon] = (row["n"], row["last"] or "", sorted(names, key=str.lower))
    return out


def model_counts(
    conn: sqlite3.Connection, *, limit: int = 500, order: str = "zuletzt"
) -> list[dict[str, Any]]:
    """Sidebar-Gruppe „Nach Modell": effektives Modell je Item.

    Das **manuell gesetzte** Modell (ADR 0022, Aufräum-Werkzeug) gewinnt —
    Items mit manuellem Modell zählen NICHT mehr unter ihrem interpretierten
    (Override, kein Doppelzählen). Mehrere gleichlautende Schicht-2-Zeilen
    desselben Items zählen einmal; leere Werte fallen raus.
    """
    merged: dict[str, list] = {}   # model -> [count, last_seen]

    def add(model, count, last):
        row = merged.setdefault(model, [0, ""])
        row[0] += count
        row[1] = max(row[1], last or "")

    # „zuletzt" = jüngstes ERSTELLDATUM (media_date, ADR 0021) je Modell -
    # nicht der Import-Zeitpunkt: Feral Strawberry steigt beim Importieren in die
    # AI-Kreidezeit ab, aktuelle Modelle sollen trotzdem oben bleiben.
    for r in conn.execute(
        """SELECT a.model AS model, COUNT(*) AS count,
                  MAX(COALESCE(i.media_date, '')) AS last
             FROM annotations a JOIN items i ON i.file_hash = a.file_hash
            WHERE a.model IS NOT NULL AND a.model != '' GROUP BY a.model"""
    ):
        add(r["model"], r["count"], r["last"])
    for r in conn.execute(
        """
        SELECT m.value_text AS model, COUNT(DISTINCT m.file_hash) AS count,
               MAX(COALESCE(i.media_date, '')) AS last
          FROM interpreted_metadata m JOIN items i ON i.file_hash = m.file_hash
         WHERE m.field = 'model' AND m.value_text IS NOT NULL AND m.value_text != ''
           AND m.file_hash NOT IN (SELECT file_hash FROM annotations WHERE model IS NOT NULL)
         GROUP BY m.value_text
        """
    ):
        add(r["model"], r["count"], r["last"])

    folded = _fold_noise_stages(conn, merged)

    # Sortierung (Feral Strawberry, 2026-07-08, Admin -> Oberfläche): 'zuletzt' =
    # neueste Nutzung zuerst, 'alphabet', 'anzahl' = größte zuerst.
    if order == "alphabet":
        key = lambda kv: kv[0].lower()
        items_sorted = sorted(folded.items(), key=key)
    elif order == "anzahl":
        items_sorted = sorted(folded.items(), key=lambda kv: (-kv[1][0], kv[0].lower()))
    else:
        items_sorted = sorted(folded.items(), key=lambda kv: (kv[1][1], kv[0].lower()), reverse=True)
    out: list[dict[str, Any]] = []
    for m, (count, _last, variants) in items_sorted[:limit]:
        entry: dict[str, Any] = {"model": m, "count": count}
        if variants:
            # Gefalteter Eintrag: der Filter-Chip läuft weiter exakt über die
            # Rohwerte (model: high | low) — den kanonischen Namen gibt es
            # als Rohwert nicht.
            entry["variants"] = variants
        out.append(entry)
    return out


def model_unknown_count(conn: sqlite3.Connection) -> int:
    """Items ohne effektives Modell — Sidebar-Zeile „(unbekanntes Modell)".

    Feral Strawberrys Wunsch (Block 4S): metadatenarme Quellen (Midjourney, Gemini,
    ChatGPT, …) sollen sichtbar sein statt still aus „Nach Modell"
    herauszufallen. Ein manuell gesetztes Modell (ADR 0022) zählt als bekannt.
    """
    return conn.execute(
        """SELECT (SELECT COUNT(*) FROM items)
                - (SELECT COUNT(*) FROM (
                     SELECT file_hash FROM interpreted_metadata
                      WHERE field = 'model' AND value_text != ''
                     UNION
                     SELECT file_hash FROM annotations
                      WHERE model IS NOT NULL AND model != ''))"""
    ).fetchone()[0]


def year_counts(conn: sqlite3.Connection) -> dict[str, Any]:
    """Sidebar-Gruppe „Nach Jahr" (ADR 0021): Jahre mit Monats-Aufschlüsselung.

    Ein Index-Scan über ``media_date`` auf Monatsebene, in Python zu Jahren
    aggregiert. ``undated`` = Items ohne (plausibles) Erstelldatum.
    """
    years: dict[str, dict[str, Any]] = {}
    undated = 0
    for r in conn.execute(
        """SELECT substr(media_date, 1, 7) AS month, COUNT(*) AS count
             FROM items GROUP BY month ORDER BY month DESC"""
    ):
        if r["month"] is None:
            undated = r["count"]
            continue
        year = r["month"][:4]
        bucket = years.setdefault(year, {"year": year, "count": 0, "months": []})
        bucket["count"] += r["count"]
        bucket["months"].append({"month": r["month"], "count": r["count"]})
    return {"years": list(years.values()), "undated": undated}


def container_counts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Sidebar-Gruppe „Nach Dateityp": Verteilung der Container (PNG, WEBP, …)."""
    return [
        dict(r)
        for r in conn.execute(
            """SELECT container, COUNT(*) AS count
                 FROM items GROUP BY container ORDER BY count DESC, container ASC"""
        )
    ]


def format_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Sidebar-Gruppe „Nach Format": grobe Seitenverhältnis-Eimer (Block 4S).

    Dieselben Grenzen wie das ``format:``-Prädikat (``filters.FORMATS``) —
    Zähler und Filter dürfen nie auseinanderlaufen. Ein Scan über ``items``;
    Items ohne Maße fallen in keinen Eimer.
    """
    counts = {name: 0 for name in filters.FORMATS}
    rows = conn.execute(
        """
        SELECT CASE
                 WHEN i.width IS NULL OR i.height IS NULL OR i.height <= 0 THEN NULL
                 WHEN i.width < i.height * 0.95 THEN 'hochformat'
                 WHEN i.width <= i.height * 1.05 THEN 'quadratisch'
                 WHEN i.width < i.height * 1.7 THEN 'querformat'
                 ELSE 'widescreen'
               END AS format, COUNT(*) AS count
          FROM items i GROUP BY format
        """
    ).fetchall()
    for r in rows:
        if r["format"] is not None:
            counts[r["format"]] = r["count"]
    return counts


def megapixel_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Sidebar-Gruppe „Nach Auflösung": Megapixel-Eimer (Feral Strawberry, 2026-07-08).

    Dieselben Grenzen wie das ``mp:``-Prädikat (``filters.MEGAPIXELS``) —
    Zähler und Filter dürfen nie auseinanderlaufen. Items ohne Maße fallen
    in keinen Eimer (wie bei ``format_counts``).
    """
    counts = {name: 0 for name in filters.MEGAPIXELS}
    rows = conn.execute(
        """
        SELECT CASE
                 WHEN i.width IS NULL OR i.height IS NULL OR i.height <= 0 THEN NULL
                 WHEN i.width * i.height < 1000000 THEN '<1'
                 WHEN i.width * i.height < 2000000 THEN '1-2'
                 WHEN i.width * i.height < 4000000 THEN '2-4'
                 ELSE '>4'
               END AS bucket, COUNT(*) AS count
          FROM items i GROUP BY bucket
        """
    ).fetchall()
    for r in rows:
        if r["bucket"] is not None:
            counts[r["bucket"]] = r["count"]
    return counts


# -- Mitfilternde Facetten (Block S4, ADR 0037) -------------------------------
#
# Die Sidebar-Zähler reagieren auf den Suchzustand: jede Gruppe zählt im
# Kontext der ANDEREN Chips (die eigenen fliegen raus — Standard-Facetten-
# muster, sonst stünden bei aktivem [Modell: flux] alle anderen Modelle auf 0
# und ODER-Erweitern wäre unmöglich). Der Ausschluss passiert SERVERSEITIG:
# /api/facets beantwortet mehrere Gruppen in einem Request, und sobald Chips
# aus mehreren dieser Gruppen aktiv sind, braucht jede Gruppe einen anderen
# effektiven Filter — ein ?filter= pro Request kann das nicht tragen.
#
# Bauform nach 250k-Benchmark (ADR 0037, §0.6 erst messen): Treffermenge
# EINMAL als Temp-Tabelle MIT den items-Spalten materialisieren + ANALYZE —
# die Eimer-Facetten (Jahr/Dateityp/Format/Auflösung) scannen danach nur die
# kleine Tabelle, die Feld-Facetten joinen sie. Inline-WHERE je Facette
# zahlte die Filter-Auswertung ~10-fach (LIKE-Filter: 3,0 s statt 0,6 s).
# Ohne aktiven Filter bleibt der bestehende ungefilterte Weg (schneller).


def _group_predicates(
    predicates: list[filters.Predicate], *, kinds: tuple[str, ...] = (), field: str = ""
) -> list[filters.Predicate]:
    """Effektive Prädikate einer Facetten-Gruppe: eigene Chips ausklammern.

    ``kinds`` entfernt Prädikat-Arten (year/month, container, …); ``field``
    entfernt Feld-Prädikate dieses Felds und ``has:``-Chips, deren Werte
    ausschließlich dieses Feld nennen (z. B. „(unbekanntes Modell)" =
    ``-has: model`` gehört zur Modell-Gruppe).
    """
    out = []
    for p in predicates:
        if p.kind in kinds:
            continue
        if field and p.kind == "field" and p.field == field:
            continue
        if field and p.kind == "has" and all(v == field for v, _ in p.values):
            continue
        out.append(p)
    return out


class _FacetHits:
    """Treffermengen je effektivem Ausdruck als Temp-Tabellen (Bauform C).

    Gruppen mit identischem effektivem Filter teilen sich die Tabelle
    (der häufige Fall: nur die Gruppen mit eigenen Chips weichen ab).
    ``table()`` liefert ``None`` bei leerem Filter — der Aufrufer nimmt dann
    den ungefilterten Weg. ``close()`` räumt auf (Temp-Tabellen sterben zwar
    mit der Verbindung, aber Leser aus Pools leben länger).
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._tables: dict[str, str] = {}

    def table(self, predicates: list[filters.Predicate]) -> str | None:
        fragment, params = filters.build_where(predicates)
        if not fragment:
            return None
        key = fragment + "\x00" + repr(params)
        name = self._tables.get(key)
        if name is None:
            name = f"facet_hits_{len(self._tables)}"
            self._conn.execute(
                f"CREATE TEMP TABLE {name} AS "
                f"SELECT i.file_hash, i.media_date, i.container, i.width, i.height "
                f"FROM items i WHERE ({fragment})",
                params,
            )
            self._conn.execute(f"CREATE UNIQUE INDEX idx_{name} ON {name}(file_hash)")
            # ANALYZE verrät dem Planer die Größe — ohne Statistik wählte er
            # bei kleinen Treffermengen die falsche Join-Reihenfolge (Bench).
            self._conn.execute(f"ANALYZE {name}")
            self._tables[key] = name
        return name

    def close(self) -> None:
        for name in self._tables.values():
            self._conn.execute(f"DROP TABLE IF EXISTS {name}")
        self._tables.clear()


def _filtered_model_counts(
    conn: sqlite3.Connection, hits: str, alias: dict[str, str] | None = None
) -> dict[str, int]:
    """Effektives Modell je Item (ADR 0022) innerhalb der Treffermenge.

    ``alias`` (Roh-Name → kanonischer Facetten-Eintrag, Block N/ADR 0043)
    kommt aus der globalen Basisliste — so landet auch eine EINZELN in der
    Treffermenge vertretene Stufe unter ihrem gefalteten Eintrag. Sind
    mehrere Stufen einer Gruppe vertreten, wird nachgezählt statt summiert
    (Zweistufen-Items trügen sonst doppelt bei).
    """
    counts: dict[str, int] = {}
    for r in conn.execute(
        f"""SELECT a.model AS model, COUNT(*) AS n
              FROM {hits} ht JOIN annotations a ON a.file_hash = ht.file_hash
             WHERE a.model IS NOT NULL AND a.model != '' GROUP BY a.model"""
    ):
        counts[r["model"]] = counts.get(r["model"], 0) + r["n"]
    for r in conn.execute(
        f"""SELECT m.value_text AS model, COUNT(DISTINCT m.file_hash) AS n
              FROM {hits} ht JOIN interpreted_metadata m ON m.file_hash = ht.file_hash
             WHERE m.field = 'model' AND m.value_text != ''
               AND m.file_hash NOT IN (SELECT file_hash FROM annotations
                                        WHERE model IS NOT NULL)
             GROUP BY m.value_text"""
    ):
        counts[r["model"]] = counts.get(r["model"], 0) + r["n"]
    if not alias:
        return counts

    folded: dict[str, int] = {}
    grouped: dict[str, list[str]] = {}
    for model, n in counts.items():
        canon = alias.get(model, model)
        grouped.setdefault(canon, []).append(model)
        folded[canon] = folded.get(canon, 0) + n
    for canon, names in grouped.items():
        if len(names) < 2:
            continue
        marks = ", ".join("?" for _ in names)
        folded[canon] = conn.execute(
            f"""SELECT COUNT(*) FROM (
                  SELECT a.file_hash FROM {hits} ht
                    JOIN annotations a ON a.file_hash = ht.file_hash
                   WHERE a.model IN ({marks})
                  UNION
                  SELECT m.file_hash FROM {hits} ht
                    JOIN interpreted_metadata m ON m.file_hash = ht.file_hash
                   WHERE m.field = 'model' AND m.value_text IN ({marks})
                     AND m.file_hash NOT IN (SELECT file_hash FROM annotations
                                              WHERE model IS NOT NULL))""",
            (*names, *names),
        ).fetchone()[0]
    return folded


def models_facet(
    conn: sqlite3.Connection, *, order: str = "zuletzt",
    filter_expr: str | None = None, cache: EpochCache | None = None,
) -> dict[str, Any]:
    """„Nach Modell" mit mitfilternden Zählern (Block S4).

    Die globale Liste bestimmt Menge und Reihenfolge der Zeilen (0-Einträge
    bleiben sichtbar und werden im Frontend gedimmt — sichtbar bleibt, was es
    gäbe); bei aktivem Filter werden die Zähler im Kontext gerechnet.
    Wirft ``ValueError`` bei ungültigem Ausdruck.

    ``cache`` (ADR 0048) merkt sich die teure globale Basisliste
    (``model_counts``, filter-unabhängig — ein Eintrag je Sortier-
    Reihenfolge) bis zum nächsten Schreibvorgang; die filterabhängigen
    Kontext-Zähler bleiben ungecacht.
    """
    if cache is not None:
        base = cache.get(("model_counts", order),
                         lambda: model_counts(conn, order=order))
    else:
        base = model_counts(conn, order=order)
    unknown = model_unknown_count(conn)
    predicates = filters.parse(filter_expr) if filter_expr else []
    effective = _group_predicates(predicates, field="model")
    hits_mgr = _FacetHits(conn)
    try:
        hits = hits_mgr.table(effective)
        if hits is None:
            return {"models": base, "unknown": unknown, "unknown_total": unknown}
        # Roh-Name → gefalteter Basis-Eintrag (Block N): die Kontext-Zähler
        # müssen unter denselben Schlüsseln laufen wie die Basisliste.
        alias = {raw: m["model"] for m in base for raw in m.get("variants", [])}
        counts = _filtered_model_counts(conn, hits, alias)
        total = conn.execute(f"SELECT COUNT(*) FROM {hits}").fetchone()[0]
        known = conn.execute(
            f"""SELECT COUNT(*) FROM {hits} ht
                 WHERE ht.file_hash IN (
                       SELECT file_hash FROM interpreted_metadata
                        WHERE field = 'model' AND value_text != ''
                       UNION
                       SELECT file_hash FROM annotations
                        WHERE model IS NOT NULL AND model != '')"""
        ).fetchone()[0]
        return {
            "models": [{**m, "count": counts.get(m["model"], 0)} for m in base],
            # unknown = Kontext-Zähler; unknown_total = global — die Zeile
            # „(unbekanntes Modell)" bleibt sichtbar (gedimmt), wenn es sie
            # überhaupt gibt (0-Dimmen statt Verstecken, Design-Doc §3.4).
            "unknown": total - known if unknown else 0,
            "unknown_total": unknown,
        }
    finally:
        hits_mgr.close()


def lora_counts(
    conn: sqlite3.Connection, *, limit: int = 500, hits: str | None = None
) -> list[dict[str, Any]]:
    """Sidebar-Gruppe „Nach LoRA" (Block S4): normalisierte LoRA-Namen
    (ADR 0026) mit Item-Zählern, meistgenutzte zuerst; optional innerhalb
    einer Treffermenge. Läuft über den Covering-Index aus Migration 0009."""
    join = f"JOIN {hits} ht ON ht.file_hash = m.file_hash" if hits else ""
    return [
        dict(r)
        for r in conn.execute(
            f"""SELECT m.value_text AS lora, COUNT(DISTINCT m.file_hash) AS count
                  FROM interpreted_metadata m {join}
                 WHERE m.field = 'lora' AND m.value_text != ''
                 GROUP BY m.value_text ORDER BY count DESC, lora ASC LIMIT ?""",
            (limit,),
        )
    ]


def tag_counts(
    conn: sqlite3.Connection, *, limit: int = 500, hits: str | None = None
) -> list[dict[str, Any]]:
    """Tag-Vokabular mit Item-Zählern für Popover/Tipphilfe (Block S5),
    meistgenutzte zuerst; optional innerhalb einer Treffermenge."""
    join = f"JOIN {hits} ht ON ht.file_hash = it.file_hash" if hits else ""
    return [
        dict(r)
        for r in conn.execute(
            f"""SELECT t.name AS tag, COUNT(DISTINCT it.file_hash) AS count
                  FROM tags t JOIN item_tags it ON it.tag_id = t.id {join}
                 GROUP BY t.id ORDER BY count DESC, t.name COLLATE NOCASE LIMIT ?""",
            (limit,),
        )
    ]


def input_image_counts(
    conn: sqlite3.Connection, *, hits: str | None = None
) -> dict[str, int]:
    """Facette „Eingangsbild" (Block S4): Items mit/ohne ``input_image``
    (img2img/i2v-Erkennung, ADR 0027), optional innerhalb einer Treffermenge."""
    src = hits or "items"
    mit = conn.execute(
        f"""SELECT COUNT(*) FROM {src}
             WHERE file_hash IN (SELECT file_hash FROM interpreted_metadata
                                  WHERE field = 'input_image' AND value_text != '')"""
    ).fetchone()[0]
    total = conn.execute(f"SELECT COUNT(*) FROM {src}").fetchone()[0]
    return {"mit": mit, "ohne": total - mit}


def fundort_counts(
    conn: sqlite3.Connection, *, hits: str | None = None
) -> dict[str, int] | None:
    """Facette „Fundort" (ADR 0041, I2): Items in der Library vs. nur extern
    indiziert, optional innerhalb einer Treffermenge. ``None``, wenn keine
    ``library.root`` konfiguriert ist — dann gibt es die Unterscheidung nicht
    (die Sidebar blendet die Gruppe aus)."""
    prefix = filters.library_like_prefix()
    if prefix is None:
        return None
    src = hits or "items"
    lib = conn.execute(
        f"""SELECT COUNT(*) FROM {src}
             WHERE file_hash IN (SELECT file_hash FROM file_locations
                                  WHERE {filters.NORM_PATH} LIKE ? ESCAPE '\\')""",
        (prefix,),
    ).fetchone()[0]
    total = conn.execute(f"SELECT COUNT(*) FROM {src}").fetchone()[0]
    return {"library": lib, "extern": total - lib}


def facets_payload(
    conn: sqlite3.Connection, *, filter_expr: str | None = None
) -> dict[str, Any]:
    """Alle Gruppen des ``/api/facets``-Endpunkts, je Gruppe im Kontext der
    anderen Chips (Block S4). Wirft ``ValueError`` bei ungültigem Ausdruck."""
    predicates = filters.parse(filter_expr) if filter_expr else []
    hits_mgr = _FacetHits(conn)
    try:
        # Dateityp: globale Liste bestimmt die Zeilen, Zähler im Kontext.
        hits = hits_mgr.table(_group_predicates(predicates, kinds=("container",)))
        containers = container_counts(conn)
        if hits is not None:
            counts = {r["container"]: r["n"] for r in conn.execute(
                f"SELECT container, COUNT(*) AS n FROM {hits} GROUP BY container")}
            containers = [{"container": c["container"],
                           "count": counts.get(c["container"], 0)} for c in containers]

        # Format/Auflösung: feste Eimer — dieselben Grenzen wie die Prädikate.
        hits = hits_mgr.table(_group_predicates(predicates, kinds=("format",)))
        formats = (format_counts(conn) if hits is None
                   else _bucket_counts(conn, hits, filters.FORMATS, _FORMAT_CASE))
        hits = hits_mgr.table(_group_predicates(predicates, kinds=("mp",)))
        megapixels = (megapixel_counts(conn) if hits is None
                      else _bucket_counts(conn, hits, filters.MEGAPIXELS, _MP_CASE))

        # Jahr/Monat: globale Struktur, Zähler im Kontext (inkl. „ohne Datum").
        hits = hits_mgr.table(_group_predicates(predicates, kinds=("year", "month")))
        years = year_counts(conn)
        years["undated_total"] = years["undated"]   # Zeile dimmen statt verstecken
        if hits is not None:
            by_month: dict[str | None, int] = {r["month"]: r["n"] for r in conn.execute(
                f"""SELECT substr(media_date, 1, 7) AS month, COUNT(*) AS n
                      FROM {hits} GROUP BY month""")}
            for y in years["years"]:
                for m in y["months"]:
                    m["count"] = by_month.get(m["month"], 0)
                y["count"] = sum(m["count"] for m in y["months"])
            years["undated"] = by_month.get(None, 0) if years["undated"] else 0

        # Nach LoRA + Eingangsbild (neu in S4).
        hits = hits_mgr.table(_group_predicates(predicates, field="lora"))
        loras = lora_counts(conn)
        if hits is not None:
            counts = {r["lora"]: r["count"] for r in lora_counts(conn, hits=hits)}
            loras = [{"lora": l["lora"], "count": counts.get(l["lora"], 0)}
                     for l in loras]
        hits = hits_mgr.table(_group_predicates(predicates, field="input_image"))
        input_image = input_image_counts(conn, hits=hits)

        # Fundort: Library vs. Extern (ADR 0041, I2) — None ohne library.root.
        hits = hits_mgr.table(_group_predicates(predicates, kinds=("fundort",)))
        fundort = fundort_counts(conn, hits=hits)

        # Tags (neu in S5): fürs „+ Kriterium"-Popover und die Tipphilfe —
        # globale Liste bestimmt die Zeilen, Zähler im Kontext.
        hits = hits_mgr.table(_group_predicates(predicates, kinds=("tag",)))
        tags = tag_counts(conn)
        if hits is not None:
            counts = {r["tag"]: r["count"] for r in tag_counts(conn, hits=hits)}
            tags = [{"tag": t["tag"], "count": counts.get(t["tag"], 0)}
                    for t in tags]

        return {
            "containers": containers,
            "formats": formats,
            "megapixels": megapixels,
            **years,
            "loras": loras,
            "input_image": input_image,
            "fundort": fundort,
            "tags": tags,
        }
    finally:
        hits_mgr.close()


def ratings_facet(
    conn: sqlite3.Connection, *, filter_expr: str | None = None
) -> list[dict[str, Any]]:
    """Bewertungs-Verteilung im Kontext der anderen Chips (Block S4)."""
    base = rating_counts(conn)
    predicates = filters.parse(filter_expr) if filter_expr else []
    hits_mgr = _FacetHits(conn)
    try:
        hits = hits_mgr.table(_group_predicates(predicates, kinds=("rating",)))
        if hits is None:
            return base
        counts = {r["rating"]: r["n"] for r in conn.execute(
            f"""SELECT a.rating, COUNT(*) AS n
                  FROM {hits} ht JOIN annotations a ON a.file_hash = ht.file_hash
                 WHERE a.rating IS NOT NULL GROUP BY a.rating""")}
        return [{"rating": b["rating"], "count": counts.get(b["rating"], 0)}
                for b in base]
    finally:
        hits_mgr.close()


# CASE-Ausdrücke der Eimer-Facetten über den Temp-Tabellen-Spalten — dieselben
# Grenzen wie filters.FORMATS/MEGAPIXELS (Zähler und Filter dürfen nie
# auseinanderlaufen; die Prädikat-Fassungen arbeiten auf Alias ``i``).
_FORMAT_CASE = """CASE
    WHEN width IS NULL OR height IS NULL OR height <= 0 THEN NULL
    WHEN width < height * 0.95 THEN 'hochformat'
    WHEN width <= height * 1.05 THEN 'quadratisch'
    WHEN width < height * 1.7 THEN 'querformat'
    ELSE 'widescreen' END"""
_MP_CASE = """CASE
    WHEN width IS NULL OR height IS NULL OR height <= 0 THEN NULL
    WHEN width * height < 1000000 THEN '<1'
    WHEN width * height < 2000000 THEN '1-2'
    WHEN width * height < 4000000 THEN '2-4'
    ELSE '>4' END"""


def _bucket_counts(
    conn: sqlite3.Connection, hits: str, buckets: dict[str, str], case_sql: str
) -> dict[str, int]:
    counts = {name: 0 for name in buckets}
    for r in conn.execute(
        f"SELECT {case_sql} AS bucket, COUNT(*) AS n FROM {hits} GROUP BY bucket"
    ):
        if r["bucket"] is not None:
            counts[r["bucket"]] = r["n"]
    return counts


# Container → MIME-Type für die Auslieferung der Originaldatei. Der Browser
# rendert WEBP/WEBM nativ — genau der Grund für das Browser-Frontend (ADR 0001).
_MIME = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "psd": "image/vnd.adobe.photoshop",
    "matroska": "video/webm",
    "isobmff": "video/mp4",
    "pdf": "application/pdf",
}


# Dateiname (Basename) des ``path``-Alias, rein in SQL: erst ``\`` → ``/``
# normalisieren (im Bestand liegen auch Windows-Pfade), dann per rtrim-Idiom
# alles bis zum letzten ``/`` abschneiden (rtrim entfernt von rechts alle
# Nicht-Trenner-Zeichen → übrig bleibt das Verzeichnis-Präfix, das replace
# dann tilgt).
_BASENAME = filters.BASENAME

# Whitelist der Sortierungen: nur fertige ORDER-BY-Klauseln aus diesem Dict
# landen im SQL — der Sortier-String von außen wird nie interpoliert.
# ``path`` ist der SELECT-Alias des ersten Fundorts (gültig in ORDER BY);
# ``name`` sortiert nach Dateiname statt Vollpfad, case-insensitiv wie
# Finder/Explorer/Lightroom.
# Sortier-Bauformen (ADR 0039, Feral Strawberrys Finding: „alles außer Hinzugefügt
# extrem langsam"). Zwei Formen, per 250k-Benchmark belegt:
#
# - "plain": ORDER BY deckt sich exakt mit einem Index (auch rückwärts
#   gelesen — deshalb sind bei den -auf/-ab-Varianten ALLE Spalten
#   gespiegelt, inklusive Tiebreaker). Das Offset-Überspringen wertet die
#   Anzeige-Subqueries dann nicht aus: tiefe Seiten in ~4 ms.
# - "paged" (unten): die Reihenfolge braucht einen Sorter (Dateiname,
#   Bewertung, Undatierte-ans-Ende) — der lief vorher über die korrelierten
#   Anzeige-Subqueries ALLER 250k Zeilen (name tief: 1,7 s). Stattdessen
#   erst eine schlanke Seiten-Query über die Hashes, die Anzeige-Spalten
#   nur für die eine Seite (name tief: 112 ms mit Expression-Index aus
#   Migration 0016, rating tief: 339 ms).
#
# created hatte ein `media_date IS NULL,`-Präfix vor dem DESC — SQLite
# stellt NULLs bei DESC ohnehin ans Ende, das Präfix hebelte nur den Index
# aus Migration 0010 aus (1,4 s je Seite). Schlüssel inkl. Richtungs-
# Varianten spiegeln filters.SORT_KEYS/SORT_DEFAULT_DIRECTION (Test).
_PLAIN_SORTS = {
    "added": "i.first_seen_at DESC, i.file_hash",
    "added-auf": "i.first_seen_at ASC, i.file_hash DESC",
    "size": "i.file_size DESC, i.file_hash",
    "size-auf": "i.file_size ASC, i.file_hash DESC",
    "container": "i.container ASC, i.first_seen_at DESC, i.file_hash",
    "container-ab": "i.container DESC, i.first_seen_at ASC, i.file_hash DESC",
    "created": "i.media_date DESC, i.file_hash",
    # created-auf ist NICHT plain: ASC stellte die Undatierten nach vorn —
    # sie gehören ans Ende, also Sorter-Bauform (unten).
}

# Basename über den Fundort-Pfad der inneren Query (Alias fl). Muss
# byte-gleich zum Ausdruck des Expression-Index aus Migration 0016 sein,
# sonst greift der Index nicht.
_BASENAME_FL = _BASENAME.replace("path", "fl.path")

# "paged"-Bauformen: (Zusatz-JOIN der inneren Query, ORDER BY innen,
# ORDER BY außen über die eine Seite, mitgeführte Sortier-Spalte oder "").
# Unbewertete/Unbenannte bleiben in BEIDEN Richtungen am Ende.
_FIRST_LOCATION_JOIN = (
    " JOIN file_locations fl ON fl.file_hash = i.file_hash"
    " AND fl.id = (SELECT MIN(l2.id) FROM file_locations l2"
    "               WHERE l2.file_hash = i.file_hash)"
)
_PAGED_SORTS = {
    "name": (
        _FIRST_LOCATION_JOIN,
        f"{_BASENAME_FL} COLLATE NOCASE ASC, fl.file_hash",
        "page.sortval COLLATE NOCASE ASC, i.file_hash",
        f"{_BASENAME_FL} AS sortval",
    ),
    "name-ab": (
        _FIRST_LOCATION_JOIN,
        f"{_BASENAME_FL} COLLATE NOCASE DESC, fl.file_hash DESC",
        "page.sortval COLLATE NOCASE DESC, i.file_hash DESC",
        f"{_BASENAME_FL} AS sortval",
    ),
    "rating": (
        " LEFT JOIN annotations sa ON sa.file_hash = i.file_hash",
        "sa.rating IS NULL, sa.rating DESC, i.first_seen_at DESC, i.file_hash",
        "rating IS NULL, rating DESC, i.first_seen_at DESC, i.file_hash",
        "",
    ),
    "rating-auf": (
        " LEFT JOIN annotations sa ON sa.file_hash = i.file_hash",
        "sa.rating IS NULL, sa.rating ASC, i.first_seen_at DESC, i.file_hash",
        "rating IS NULL, rating ASC, i.first_seen_at DESC, i.file_hash",
        "",
    ),
    "created-auf": (
        "",
        "i.media_date IS NULL, i.media_date ASC, i.file_hash",
        "i.media_date IS NULL, i.media_date ASC, i.file_hash",
        "",
    ),
}

# Für den Whitelist-Abgleich (?sort=-Parameter und Kopplungs-Test).
_SORTS = _PLAIN_SORTS | _PAGED_SORTS


def rating_counts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Verteilung der manuellen Bewertungen: [{rating, count}], nur 1–5."""
    return [
        dict(r)
        for r in conn.execute(
            """SELECT rating, COUNT(*) AS count FROM annotations
                WHERE rating IS NOT NULL GROUP BY rating ORDER BY rating DESC"""
        )
    ]


def list_items(
    conn: sqlite3.Connection,
    *,
    limit: int = 200,
    offset: int = 0,
    sort: str = "added",
    model: str | None = None,
    rating: int | None = None,
    filter_expr: str | None = None,
    dupes: bool = False,
    with_total: bool = True,
    cache: EpochCache | None = None,
) -> dict[str, Any]:
    """Eine Seite des Bestands fürs Grid, Sortierung per Whitelist (``_SORTS``).

    Unbekannte Sortierschlüssel fallen auf ``added`` (neueste zuerst) zurück;
    eine ``sort:``-Direktive im ``filter_expr`` gewinnt über ``sort`` (ADR 0035).
    Optional gefiltert: ``model`` (exakter Schicht-2-Modellwert, Sidebar) und
    ``rating`` (manuelle Schicht, exakt n Sterne — Feral Strawberry will auch gezielt
    schlecht Bewertetes sehen), ``filter_expr`` (Smart-Folder-Grammatik,
    ADR 0018 — wirft ``ValueError`` bei ungültigem Ausdruck) und ``dupes``
    (nur Items mit mehr als einem Fundort). Liefert ``total``
    (Gesamtzahl DES FILTERS für die Virtualisierung) und je Item Hash,
    Container, Medienart, Größe, Zeitstempel, einen Fundort-Dateinamen, das
    ``tool``-Feld aus Schicht 2 sowie das manuelle Rating.

    ``cache`` (ADR 0048) beschleunigt NUR gefilterte Zustände: die fertig
    sortierte Hash-Liste der Treffer wird einmal materialisiert und an die
    Schreib-Epoche gebunden; jede Seite ist dann Listen-Slice + eine
    Anzeige-Query. Der ungefilterte Pfad bleibt der Index-Spaziergang.
    """
    sort_key = sort if sort in _SORTS else "added"
    where = []
    params: list[Any] = []
    if model is not None:
        # Effektives Modell: manuell gesetztes gewinnt (ADR 0022). Von den
        # Treffern aus, nicht vom Gesamtbestand: die IN-Subqueries laufen über
        # den Covering-Index (Migration 0009) bzw. die kleine annotations-
        # Tabelle — die EXISTS-Form probte JEDES Item einzeln (Gedenkminute).
        where.append(
            """(i.file_hash IN (SELECT file_hash FROM annotations WHERE model = ?)
                OR (i.file_hash IN (SELECT file_hash FROM interpreted_metadata
                                     WHERE field = 'model' AND value_text = ?)
                    AND i.file_hash NOT IN (SELECT file_hash FROM annotations
                                             WHERE model IS NOT NULL)))"""
        )
        params.extend([model, model])
    if rating is not None:
        where.append(
            """EXISTS (SELECT 1 FROM annotations a
                        WHERE a.file_hash = i.file_hash AND a.rating = ?)"""
        )
        params.append(rating)
    if filter_expr is not None:
        predicates = filters.parse(filter_expr)
        # sort: im Ausdruck gewinnt über den ?sort=-Parameter (ADR 0035) —
        # damit ist die Sortierung Teil gespeicherter Suchen.
        directive = filters.sort_directive(predicates)
        if directive is not None:
            sort_key = directive
        fragment, fparams = filters.build_where(predicates)
        if fragment:  # Ausdruck nur aus sort: filtert nichts
            where.append(fragment)
        params.extend(fparams)
    if dupes:
        where.append(
            "(SELECT COUNT(*) FROM file_locations l2 WHERE l2.file_hash = i.file_hash) > 1"
        )
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    display = """
        SELECT i.file_hash, i.container, i.media_kind, i.file_size, i.first_seen_at,
               i.width, i.height, i.fps,
               (SELECT rating FROM annotations a
                 WHERE a.file_hash = i.file_hash) AS rating,
               (SELECT path FROM file_locations l
                 WHERE l.file_hash = i.file_hash ORDER BY l.id LIMIT 1) AS path,
               (SELECT value_text FROM interpreted_metadata m
                 WHERE m.file_hash = i.file_hash AND m.field = 'tool' LIMIT 1) AS tool
          FROM items i
        """
    if cache is not None and where:
        # Trefferlisten-Cache (ADR 0048), NUR für gefilterte Zustände: die
        # fertig sortierte Hash-Liste einmal materialisieren, an die
        # Schreib-Epoche binden — jedes Häppchen ist dann Slice + EINE
        # Anzeige-Query über die Seiten-Hashes. Schlüssel = (Sortierung,
        # WHERE-Fragment, Parameter); die fundort:-Library-Root steckt als
        # LIKE-Präfix in den Parametern und läuft damit automatisch mit.
        key = ("items", sort_key, where_sql, tuple(params))

        def _materialize() -> list[str]:
            if sort_key in _PLAIN_SORTS:
                order_by = _PLAIN_SORTS[sort_key]
                join = ""
            else:
                join, order_by, _, _ = _PAGED_SORTS[sort_key]
            return [r[0] for r in conn.execute(
                f"SELECT i.file_hash FROM items i{join}{where_sql}"
                f" ORDER BY {order_by}", params)]

        hashes = cache.get(key, _materialize)
        total = len(hashes)  # die COUNT-Query je Filterwechsel entfällt mit
        page_hashes = hashes[offset:offset + limit]
        rows = []
        if page_hashes:
            marks = ",".join("?" * len(page_hashes))
            by_hash = {r["file_hash"]: r for r in conn.execute(
                display + f" WHERE i.file_hash IN ({marks})", page_hashes)}
            # Reihenfolge kommt aus der Liste; zwischen Epochen-Prüfung und
            # Anzeige-Query gelöschte Items fallen still raus.
            rows = [by_hash[h] for h in page_hashes if h in by_hash]
        return {"total": total, "offset": offset, "items": _item_dicts(rows)}

    # COUNT nur für die erste Seite (Feral Strawberrys Windows-Runde 5): beim Durch-
    # scrollen lädt das Grid viele Folgeseiten — der Filter-COUNT je Seite
    # war ein Prüf-Scan pro Anfrage. -1 = „unverändert" (Frontend behält
    # den Zähler der ersten Seite).
    total = -1
    if with_total:
        total = conn.execute(
            f"SELECT COUNT(*) FROM items i{where_sql}", params
        ).fetchone()[0]
    if sort_key in _PLAIN_SORTS:
        rows = conn.execute(
            display + where_sql
            + f" ORDER BY {_PLAIN_SORTS[sort_key]} LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
    else:
        # "paged" (ADR 0039): erst die schlanke Hash-Seite in Ordnung
        # bringen, die Anzeige-Subqueries laufen dann nur für diese Seite.
        join, inner_order, outer_order, carry = _PAGED_SORTS[sort_key]
        inner = (
            f"SELECT i.file_hash AS h{', ' + carry if carry else ''}"
            f" FROM items i{join}{where_sql}"
            f" ORDER BY {inner_order} LIMIT ? OFFSET ?"
        )
        rows = conn.execute(
            display
            + f" JOIN ({inner}) page ON page.h = i.file_hash"
            + f" ORDER BY {outer_order}",
            (*params, limit, offset),
        ).fetchall()
    return {"total": total, "offset": offset, "items": _item_dicts(rows)}


def _item_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Anzeige-Zeilen der Galerie-Query → Item-Dicts fürs Grid."""
    return [
        {
            "file_hash": r["file_hash"],
            "container": r["container"],
            "media_kind": r["media_kind"],
            "file_size": r["file_size"],
            "first_seen_at": r["first_seen_at"],
            "name": Path(r["path"]).name if r["path"] else None,
            "tool": r["tool"],
            "rating": r["rating"],
            "width": r["width"],
            "height": r["height"],
            "fps": r["fps"],
        }
        for r in rows
    ]


def item_detail(conn: sqlite3.Connection, file_hash: str) -> dict[str, Any] | None:
    """Alles Sichtbare zu einem Item: Stammdaten, Fundorte, Schicht 2, Schicht 1.

    Binäre Roh-Einträge (EXIF, ICC) werden nicht ausgeliefert, nur beschrieben
    (Quelle + Bytegröße). ``None``, wenn der Hash unbekannt ist.
    """
    item = conn.execute(
        "SELECT * FROM items WHERE file_hash = ?", (file_hash,)
    ).fetchone()
    if item is None:
        return None

    locations = [
        {"path": r["path"], "exists": Path(r["path"]).is_file()}
        for r in conn.execute(
            "SELECT path FROM file_locations WHERE file_hash = ? ORDER BY id",
            (file_hash,),
        )
    ]
    interpreted = [
        {"parser": r["parser"], "field": r["field"], "value": r["value_text"]}
        for r in conn.execute(
            """SELECT parser, field, value_text FROM interpreted_metadata
                WHERE file_hash = ? ORDER BY parser, ordinal""",
            (file_hash,),
        )
    ]
    raw = [
        {
            "source": r["source"],
            "keyword": r["keyword"],
            "text": r["value_text"],
            "binary_bytes": None if r["value_text"] is not None else len(r["value_raw"]),
        }
        for r in conn.execute(
            """SELECT source, keyword, value_text, value_raw FROM raw_metadata
                WHERE file_hash = ? ORDER BY ordinal""",
            (file_hash,),
        )
    ]
    return {
        "file_hash": item["file_hash"],
        "container": item["container"],
        "media_kind": item["media_kind"],
        "file_size": item["file_size"],
        "first_seen_at": item["first_seen_at"],
        "updated_at": item["updated_at"],
        "media_date": item["media_date"],  # Basis der Gruppe „Nach Jahr" (ADR 0021)
        "width": item["width"],
        "height": item["height"],
        "fps": item["fps"],
        "locations": locations,
        "interpreted": interpreted,
        "raw": raw,
        "manual": manual.annotations_for(conn, file_hash),
    }


def workflow_json(conn: sqlite3.Connection, file_hash: str) -> str | None:
    """Das eingebettete ComfyUI-Workflow-JSON eines Items (UI-Graph, Schicht 1).

    Keyword case-insensitiv (`workflow` bei PNG, `WORKFLOW` bei Matroska).
    Unverändert aus der Roh-Schicht — genau der Blob, den ComfyUI gespeichert
    hat. ``None``, wenn keiner vorhanden ist.
    """
    row = conn.execute(
        """SELECT value_text FROM raw_metadata
            WHERE file_hash = ? AND LOWER(keyword) = 'workflow'
              AND value_text IS NOT NULL
            ORDER BY ordinal LIMIT 1""",
        (file_hash,),
    ).fetchone()
    return row["value_text"] if row else None


def a1111_fields(conn: sqlite3.Connection, file_hash: str) -> dict[str, list[str]]:
    """Schicht-2-Felder des a1111-Parsers als Feld → Werteliste.

    Substrat für den generierten ComfyUI-Graphen (Block N, ADR 0044) —
    leer, wenn das Item nicht aus A1111-artigen Tools stammt.
    """
    fields: dict[str, list[str]] = {}
    for r in conn.execute(
        """SELECT field, value_text FROM interpreted_metadata
            WHERE file_hash = ? AND parser = 'a1111' ORDER BY ordinal""",
        (file_hash,),
    ):
        fields.setdefault(r["field"], []).append(r["value_text"])
    return fields


def resolve_media(conn: sqlite3.Connection, file_hash: str) -> tuple[str, str] | None:
    """Der erste noch existierende Fundort eines Items plus MIME-Type.

    Nur Pfade aus `file_locations` kommen infrage — der Endpunkt kann also
    ausschließlich katalogisierte Dateien ausliefern. ``None``, wenn keiner
    der Fundorte mehr existiert.

    Größen-Wächter (ADR 0049): gleicher Hash ⇒ exakt gleiche Bytezahl.
    Weicht die Dateigröße auf der Platte von ``items.file_size`` ab, liegt
    an diesem Pfad nachweislich eine ANDERE Datei — der Fundort wird
    übersprungen statt fremde Bytes unter diesem Hash auszuliefern (Fenster
    zwischen Dateiwechsel und nächstem Watcher-Lauf). Größengleiche
    Fremd-Dateien fängt erst der Katalogisier-Cleanup in store_extraction;
    mtime bleibt außen vor (ändert sich auch ohne Inhaltswechsel).
    """
    rows = conn.execute(
        """SELECT l.path, i.file_size, i.container FROM file_locations l
             JOIN items i USING(file_hash) WHERE l.file_hash = ? ORDER BY l.id""",
        (file_hash,),
    ).fetchall()
    for row in rows:
        p = Path(row["path"])
        try:
            if not p.is_file() or p.stat().st_size != row["file_size"]:
                continue
        except OSError:
            continue
        mime = _MIME.get(row["container"], "application/octet-stream")
        return row["path"], mime
    return None


