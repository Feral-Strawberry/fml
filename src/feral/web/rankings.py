"""Ranking-Modul, Populations-Seite: Paar-Auswahl + Bestenliste (ADR 0045).

Die Population einer Arena ist ihr Filterausdruck, live ausgewertet (wie
Smart Folders); ein leerer Ausdruck heißt „ganze Bibliothek" (ADR 0040).
Die Treffermenge wird als Temp-Tabelle materialisiert (Bauform ADR 0037) und
mit ``ranking_scores`` geschnitten — Items ohne Score zählen mit
``START_SCORE``/0 Duellen. Abgelehnte/verschwundene Items fallen automatisch
heraus: sie stehen nicht mehr in ``items`` (ihre Duell-Geschichte bleibt,
siehe ``db/rankings.py``).

Paar-Auswahl „Abdeckung, dann Nähe" (ADR 0045): Kandidat A ist einer der
seltenst-verglichenen (Zufall unter Gleichen), Kandidat B kommt zufällig aus
einem Score-Fenster um A — knappe Duelle liefern die meiste Information;
ist das Fenster leer, irgendein anderes Item. Die Seiten werden gemischt,
damit der Seltener-Verglichene nicht immer links steht.
"""

from __future__ import annotations

import random
import sqlite3
from typing import Any

from ..db.rankings import START_SCORE
from . import filters

# Score-Fenster der Nähe-Stufe: ±150 Elo ≈ 70/30-Erwartung — noch offen genug,
# dass Duelle nicht vorentschieden wirken.
SCORE_WINDOW = 150.0

_POP = "arena_pop"


def _materialize_population(conn: sqlite3.Connection, expression: str) -> int:
    """Population der Arena als Temp-Tabelle ``arena_pop`` (nur Hashes)."""
    conn.execute(f"DROP TABLE IF EXISTS {_POP}")
    fragment, params = "", []
    if expression and expression.strip():
        fragment, params = filters.build_where(filters.parse(expression))
    where = f"WHERE ({fragment})" if fragment else ""
    conn.execute(
        f"CREATE TEMP TABLE {_POP} AS SELECT i.file_hash FROM items i {where}",
        params,
    )
    conn.execute(f"CREATE UNIQUE INDEX idx_{_POP} ON {_POP}(file_hash)")
    conn.execute(f"ANALYZE {_POP}")   # Planer-Statistik (Muster ADR 0037)
    return conn.execute(f"SELECT COUNT(*) FROM {_POP}").fetchone()[0]


# Population × Scores: Items ohne Score-Zeile starten bei START_SCORE/0.
# Als Subquery gekapselt, damit WHERE/ORDER BY die Aliasse sauber sehen.
# media_kind kommt mit (Block R2): die Duell-Ansicht rendert <img> vs.
# <video>, ohne je Kandidat das volle Item nachzuladen. container ebenso
# (ADR 0052): TIFF/PSD laufen über die gerenderte Vorschau statt /api/media.
_POP_SCORED = f"""
    SELECT * FROM (
        SELECT p.file_hash, i.media_kind, i.container,
               COALESCE(s.score, {START_SCORE}) AS score,
               COALESCE(s.duels, 0) AS duels
          FROM {_POP} p
          JOIN items i ON i.file_hash = p.file_hash
          LEFT JOIN ranking_scores s
            ON s.ranking_id = ? AND s.file_hash = p.file_hash
    )
"""


def next_pair(
    conn: sqlite3.Connection, ranking: dict[str, Any], *, rng: random.Random | None = None
) -> dict[str, Any] | None:
    """Nächstes Duell-Paar der Arena — oder ``None`` bei Population < 2.

    ``rng`` ist für Tests injizierbar (bestimmt nur die Seiten-Mischung;
    die SQL-Zufälle laufen über SQLites ``RANDOM()``).
    """
    rng = rng or random.Random()
    population = _materialize_population(conn, ranking["expression"])
    try:
        if population < 2:
            return None
        a = conn.execute(
            f"{_POP_SCORED} ORDER BY duels ASC, RANDOM() LIMIT 1",
            (ranking["id"],),
        ).fetchone()
        b = conn.execute(
            f"""{_POP_SCORED}
                WHERE file_hash != ? AND ABS(score - ?) <= ?
                ORDER BY RANDOM() LIMIT 1""",
            (ranking["id"], a["file_hash"], a["score"], SCORE_WINDOW),
        ).fetchone()
        if b is None:   # Fenster leer — irgendein anderes Item (ADR 0045)
            b = conn.execute(
                f"{_POP_SCORED} WHERE file_hash != ? ORDER BY RANDOM() LIMIT 1",
                (ranking["id"], a["file_hash"]),
            ).fetchone()
        pair = [dict(a), dict(b)]
        rng.shuffle(pair)
        return {"population": population, "pair": pair}
    finally:
        conn.execute(f"DROP TABLE IF EXISTS {_POP}")


def leaderboard(
    conn: sqlite3.Connection, ranking: dict[str, Any], *, limit: int = 100, offset: int = 0
) -> dict[str, Any]:
    """Bestenliste der Arena: Population ∩ Scores, bester Score zuerst.

    Items ohne Duell tauchen nicht auf (kein Rang ohne Urteil); ``total``
    zählt die Gelisteten, ``population`` die ganze Arena.
    """
    population = _materialize_population(conn, ranking["expression"])
    try:
        total = conn.execute(
            f"""SELECT COUNT(*) FROM {_POP} p
                 JOIN ranking_scores s
                   ON s.ranking_id = ? AND s.file_hash = p.file_hash""",
            (ranking["id"],),
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT p.file_hash, i.media_kind, i.container, s.score, s.duels FROM {_POP} p
                 JOIN items i ON i.file_hash = p.file_hash
                 JOIN ranking_scores s
                   ON s.ranking_id = ? AND s.file_hash = p.file_hash
                ORDER BY s.score DESC, s.duels DESC, p.file_hash
                LIMIT ? OFFSET ?""",
            (ranking["id"], limit, offset),
        ).fetchall()
        return {
            "population": population,
            "total": total,
            "entries": [
                {"rank": offset + i + 1, **dict(row)} for i, row in enumerate(rows)
            ],
        }
    finally:
        conn.execute(f"DROP TABLE IF EXISTS {_POP}")
