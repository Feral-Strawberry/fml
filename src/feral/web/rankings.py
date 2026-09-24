"""Ranking-Modul, Populations-Seite: Paar-Auswahl + Bestenliste (ADR 0045).

Die Population einer Arena ist ihr Filterausdruck, live ausgewertet (wie
Smart Folders); ein leerer Ausdruck heißt „ganze Bibliothek" (ADR 0040).
Audio gehört nie dazu (#175, ``ARENA_VIEW``): Songs vergleicht und bewertet
das Audio-Modul mit eigenen Werkzeugen.
Abgelehnte/verschwundene Items fallen automatisch heraus: sie stehen nicht
mehr in ``items`` (ihre Duell-Geschichte bleibt, siehe ``db/rankings.py``).

Bauform seit Issue #98 (ADR 0072): **EIN Filterlauf je Aufruf, keine
Temp-Tabelle.** Die frühere Temp-Tabelle ``arena_pop`` (Muster ADR 0037:
Kopie + Unique-Index + ANALYZE + vier Joins) kostete bei einer Arena über
die ganze Bibliothek die 250k-Kopie, bei kleinen Arenen mit schweren
Filtern den Filterlauf — beides je Duell. Jetzt zwei Pfade mit derselben
Auswahl-Logik:

- **Gefilterte Arena:** die Population wird EINMAL als materialisierte
  CTE gebaut (ein Filterlauf) und Zähler, Score-Schnitt und Stichprobe
  kommen in EINEM Statement aus derselben Kopie — Feral Strawberrys Arenen
  sind ein paar tausend Medien mit 3–20 Prädikaten, da ist der Filterlauf
  der Kostenblock, nicht die Kopie.
- **Ganze Bibliothek:** kein Filter, nichts zu kopieren — Zähler aus
  ``library.count_items`` (Epochen-Cache), Score-Zeilen der Arena als
  Dict, Stichprobe als Index-Pass über ``items``.

Paar-Auswahl „Abdeckung, dann Nähe" (ADR 0045), unverändert in der
Semantik: Kandidat A ist einer der seltenst-verglichenen (Zufall unter
Gleichen — gibt es unbewertete Items, hat A 0 Duelle und kommt aus der
Stichprobe), Kandidat B kommt zufällig aus einem Score-Fenster um A —
knappe Duelle liefern die meiste Information; ist das Fenster leer,
irgendein anderes aktives Item. Unbewertete stehen bei ``START_SCORE`` und
werden gegenüber den Bewerteten im Fenster nach ihrer Anzahl gewichtet, so
dass B wie zuvor gleichverteilt über die Fenster-Mitglieder ist. Die Seiten
werden gemischt, damit der Seltener-Verglichene nicht immer links steht.
"""

from __future__ import annotations

import random
import sqlite3
from typing import Any

from ..db.rankings import START_SCORE
from . import filters, library
from .cache import EpochCache

# Score-Fenster der Nähe-Stufe: ±150 Elo ≈ 70/30-Erwartung — noch offen genug,
# dass Duelle nicht vorentschieden wirken.
SCORE_WINDOW = 150.0

# Stichprobe je Paarung (#98): so viele zufällige unbewertete Populations-
# Items liefert der eine Lauf; A und B kommen daraus. Klein genug, dass der
# Sortierer nichts kostet; groß genug, dass beide Kandidaten fast immer
# dabei sind (im Bibliotheks-Pfad sonst der exakte, seltene Fallback-Lauf).
SAMPLE_SIZE = 8

# Grundbereich jeder Arena (#175): Bilder und Videos, nie Audio — zum
# Vergleichen und Bewerten von Songs hat das Audio-Modul eigene Werkzeuge
# (Vergleichsansicht, Zeitkommentare). Ausdrücklich per ``media_kind``, NICHT
# über den Galerie-Grundbereich der Ansicht: der nimmt mit Modul an die Songs
# mit Cover auf (ADR 0090). ``typ: audio`` ergibt damit einen leeren Pool.
# Steht vor dem Ausdruck wie ``view_preds`` vor den Chips — und im Zähler-
# Cache-Schlüssel, den Sidebar (``/api/rankings``) und Paarung teilen.
ARENA_VIEW = (filters.view_predicate("galerie"),)
_COLS = "i.file_hash, i.media_kind, i.container"
_FIELDS = ("file_hash", "media_kind", "container", "score", "duels", "eliminated")

# Gefilterte Arena, Paarung: Population EINMAL materialisiert (``AS
# MATERIALIZED``, SQLite ≥ 3.35 — Python 3.12+ bringt neuere mit), daraus
# Zähler ('n', Zahl in file_hash), Score-Schnitt ('s') und Stichprobe der
# Unbewerteten ('u') in EINEM Statement. Spaltennamen kommen aus dem ersten
# SELECT der UNION.
_FILTERED_PAIR = """
WITH p AS MATERIALIZED (SELECT {cols} FROM items i WHERE {pop})
SELECT 'n' AS kind, COUNT(*) AS file_hash, NULL AS media_kind, NULL AS container,
       NULL AS score, NULL AS duels, NULL AS eliminated FROM p
UNION ALL
SELECT 's', p.file_hash, p.media_kind, p.container, s.score, s.duels, s.eliminated
  FROM p JOIN ranking_scores s ON s.ranking_id = ? AND s.file_hash = p.file_hash
UNION ALL
SELECT * FROM (
    SELECT 'u', p.file_hash, p.media_kind, p.container, NULL, NULL, NULL FROM p
     WHERE NOT EXISTS (SELECT 1 FROM ranking_scores s
                        WHERE s.ranking_id = ? AND s.file_hash = p.file_hash)
     ORDER BY RANDOM() LIMIT ?)
"""

# Gefilterte Arena, Bestenliste: dieselbe Kopie, daraus Population ('n'),
# Gelistete + Ausgeschiedene ('t': COUNT in file_hash, SUM in eliminated)
# und die Seite ('r'; Reihenfolge wird in Python noch einmal festgezogen —
# eine UNION garantiert die Ordnung der Teil-Abfrage nicht).
_FILTERED_BOARD = """
WITH p AS MATERIALIZED (SELECT {cols} FROM items i WHERE {pop})
SELECT 'n' AS kind, COUNT(*) AS file_hash, NULL AS media_kind, NULL AS container,
       NULL AS score, NULL AS duels, NULL AS eliminated FROM p
UNION ALL
SELECT 't', COUNT(*), NULL, NULL, NULL, NULL, COALESCE(SUM(s.eliminated), 0)
  FROM p JOIN ranking_scores s ON s.ranking_id = ? AND s.file_hash = p.file_hash
UNION ALL
SELECT * FROM (
    SELECT 'r', p.file_hash, p.media_kind, p.container, s.score, s.duels, s.eliminated
      FROM p JOIN ranking_scores s ON s.ranking_id = ? AND s.file_hash = p.file_hash
     ORDER BY s.eliminated, s.score DESC, s.duels DESC, p.file_hash
     LIMIT ? OFFSET ?)
"""

# Ganze Bibliothek: Score-Zeilen der Arena, nur Items, die es noch gibt
# und die im Grundbereich liegen (``{pop}``, Parameter nach der Arena-ID).
# CROSS JOIN legt die Reihenfolge fest (SQLite-Konvention): außen die
# kleine Score-Menge über den Primärschlüssel (ranking_id, file_hash).
_LIBRARY_SCORED = """
    FROM ranking_scores s
    CROSS JOIN items i ON i.file_hash = s.file_hash
    WHERE s.ranking_id = ? AND {pop}
"""

_BOARD_ORDER = "ORDER BY s.eliminated, s.score DESC, s.duels DESC, s.file_hash"


def _population_where(expression: str) -> tuple[str, list[Any], bool]:
    """Populationsbedingung über Alias ``i`` (Grundbereich ``ARENA_VIEW`` +
    Ausdruck), Parameter und ob der Ausdruck filtert (sonst: ganze
    Bibliothek). Wirft bei ungültigem Ausdruck (``UserError``, ein
    ``ValueError``)."""
    base, params = filters.build_where(list(ARENA_VIEW))
    if expression and expression.strip():
        fragment, extra = filters.build_where(filters.parse(expression))
        if fragment:
            return f"({base}) AND ({fragment})", [*params, *extra], True
    return f"({base})", params, False


def _entry(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in _FIELDS}


def _unscored(entry: dict[str, Any]) -> dict[str, Any]:
    """Ein Populations-Item ohne Score-Zeile: Startwert, 0 Duelle, aktiv."""
    return {**entry, "score": START_SCORE, "duels": 0, "eliminated": 0}


def _filtered_population(
    conn: sqlite3.Connection, ranking_id: int, pop: str, params: list[Any], sample_n: int
) -> tuple[int, dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """(Population, Score-Zeilen je Hash, Stichprobe Unbewerteter) — ein
    Filterlauf, ein Statement."""
    population, scored, sample = 0, {}, []
    for row in conn.execute(
        _FILTERED_PAIR.format(cols=_COLS, pop=pop), (*params, ranking_id, ranking_id, sample_n)
    ):
        if row["kind"] == "n":
            population = row["file_hash"]
        elif row["kind"] == "s":
            scored[row["file_hash"]] = _entry(row)
        else:
            sample.append(_unscored(_entry(row)))
    return population, scored, sample


def _library_population(
    conn: sqlite3.Connection, ranking_id: int, pop: str, params: list[Any], sample_n: int,
    cache: EpochCache | None, scope: dict | None,
) -> tuple[int, dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Wie ``_filtered_population`` für die ganze Bibliothek: nichts zu
    kopieren — Zähler aus dem Epochen-Cache, Stichprobe als Index-Pass.
    ``pop`` ist hier nur der Grundbereich (``ARENA_VIEW``)."""
    population = library.count_items(conn, None, cache=cache, scope=scope,
                                     view_preds=ARENA_VIEW)
    scored = {
        row["file_hash"]: _entry(row) for row in conn.execute(
            f"SELECT s.file_hash, i.media_kind, i.container, s.score, s.duels, s.eliminated"
            f"{_LIBRARY_SCORED.format(pop=pop)}", (ranking_id, *params))
    }
    sample = [
        _unscored(_entry(row)) for row in conn.execute(
            f"SELECT {_COLS}, NULL AS score, NULL AS duels, NULL AS eliminated"
            f" FROM items i WHERE {pop} ORDER BY RANDOM() LIMIT ?", (*params, sample_n))
        if row["file_hash"] not in scored
    ]
    return population, scored, sample


def _random_unscored(
    conn: sqlite3.Connection, ranking_id: int, pop: str, params: list[Any],
    exclude: str | None,
) -> dict[str, Any]:
    """Exakter Fallback (Bibliotheks-Pfad, selten): ein zufälliges
    unbewertetes Item per Lauf über den Bestand — wenn die Stichprobe nur
    Bewertete traf. Aufrufer garantieren, dass es eines gibt."""
    row = conn.execute(
        f"""SELECT {_COLS}, NULL AS score, NULL AS duels, NULL AS eliminated
              FROM items i
             WHERE {pop} AND i.file_hash != ?
               AND NOT EXISTS (SELECT 1 FROM ranking_scores s
                                WHERE s.ranking_id = ? AND s.file_hash = i.file_hash)
             ORDER BY RANDOM() LIMIT 1""",
        (*params, exclude or "", ranking_id),
    ).fetchone()
    return _unscored(_entry(row))


def next_pair(
    conn: sqlite3.Connection, ranking: dict[str, Any], *,
    rng: random.Random | None = None,
    cache: EpochCache | None = None, scope: dict | None = None,
) -> dict[str, Any] | None:
    """Nächstes Duell-Paar der Arena — oder ``None`` bei Population < 2.

    Ausgeschiedene (#87) gehören nicht zum Pool; bleiben weniger als zwei
    aktive Items, kommt ``pair: None`` mit den Zahlen (die UI zeigt „n von m
    ausgeschieden" und den Weg zur Bestenliste, wo „Wieder rein" wohnt).

    ``rng`` ist für Tests injizierbar (Wahl innerhalb der Stichprobe bzw.
    unter Gleichen und die Seiten-Mischung; die Stichprobe selbst zieht
    SQLites ``RANDOM()``). ``cache``/``scope`` (ADR 0048/0071) gehen an den
    Populationszähler des Bibliotheks-Pfads.
    """
    rng = rng or random.Random()
    rid = ranking["id"]
    pop, params, filtered = _population_where(ranking["expression"])
    if not filtered:
        population, scored, sample = _library_population(
            conn, rid, pop, params, SAMPLE_SIZE, cache, scope)
    else:
        population, scored, sample = _filtered_population(conn, rid, pop, params, SAMPLE_SIZE)
    if population < 2:
        return None
    eliminated = sum(1 for s in scored.values() if s["eliminated"])
    result: dict[str, Any] = {"population": population, "eliminated": eliminated}
    if population - eliminated < 2:
        return {**result, "pair": None}
    unscored = population - len(scored)
    active = [s for s in scored.values() if not s["eliminated"]]

    # Kandidat A: seltenst verglichen. Unbewertete haben 0 Duelle und gewinnen
    # damit immer, solange es welche gibt.
    if unscored > 0:
        if sample:
            a = sample.pop(rng.randrange(len(sample)))
        else:
            a = _random_unscored(conn, rid, pop, params, None)
        a_unscored = True
    else:
        fewest = min(s["duels"] for s in active)
        a = rng.choice([s for s in active if s["duels"] == fewest])
        a_unscored = False
    others = [s for s in active if s["file_hash"] != a["file_hash"]]
    unscored_others = unscored - (1 if a_unscored else 0)

    # Kandidat B: Fenster um A — Unbewertete zählen mit ihrer Anzahl, damit
    # die Wahl gleichverteilt über alle Fenster-Mitglieder bleibt.
    near = [s for s in others if abs(s["score"] - a["score"]) <= SCORE_WINDOW]
    near_unscored = unscored_others if abs(START_SCORE - a["score"]) <= SCORE_WINDOW else 0
    if near_unscored + len(near) == 0:   # Fenster leer — irgendein anderes (ADR 0045)
        near, near_unscored = others, unscored_others
    if rng.randrange(near_unscored + len(near)) < near_unscored:
        b = sample.pop(rng.randrange(len(sample))) if sample \
            else _random_unscored(conn, rid, pop, params, a["file_hash"])
    else:
        b = rng.choice(near)
    pair = [a, b]
    rng.shuffle(pair)
    return {**result, "pair": pair}


def leaderboard(
    conn: sqlite3.Connection, ranking: dict[str, Any], *,
    limit: int = 100, offset: int = 0,
    cache: EpochCache | None = None, scope: dict | None = None,
) -> dict[str, Any]:
    """Bestenliste der Arena: Population ∩ Scores, bester Score zuerst;
    Ausgeschiedene (#87) geschlossen am Ende, unter sich nach Score.

    Items ohne Duell tauchen nicht auf (kein Rang ohne Urteil); ``total``
    zählt die Gelisteten (inklusive Ausgeschiedene, ``eliminated`` sagt wie
    viele), ``population`` die ganze Arena. ``rank`` ist die Position in der
    Liste — für Ausgeschiedene zeigt die UI statt der Zahl den Marker.
    """
    rid = ranking["id"]
    pop, params, filtered = _population_where(ranking["expression"])
    if not filtered:
        population = library.count_items(conn, None, cache=cache, scope=scope,
                                         view_preds=ARENA_VIEW)
        scored_sql = _LIBRARY_SCORED.format(pop=pop)
        total, eliminated = conn.execute(
            f"SELECT COUNT(*), COALESCE(SUM(s.eliminated), 0){scored_sql}", (rid, *params)
        ).fetchone()
        rows = [_entry(r) for r in conn.execute(
            f"SELECT s.file_hash, i.media_kind, i.container, s.score, s.duels, s.eliminated"
            f"{scored_sql} {_BOARD_ORDER} LIMIT ? OFFSET ?", (rid, *params, limit, offset))]
    else:
        population, total, eliminated, rows = 0, 0, 0, []
        for row in conn.execute(
            _FILTERED_BOARD.format(cols=_COLS, pop=pop),
            (*params, rid, rid, limit, offset),
        ):
            if row["kind"] == "n":
                population = row["file_hash"]
            elif row["kind"] == "t":
                total, eliminated = row["file_hash"], row["eliminated"]
            else:
                rows.append(_entry(row))
        rows.sort(key=lambda e: (e["eliminated"], -e["score"], -e["duels"], e["file_hash"]))
    return {
        "population": population,
        "total": total,
        "eliminated": eliminated,
        "entries": [{"rank": offset + i + 1, **row} for i, row in enumerate(rows)],
    }
