"""Ranking-Modul: Arenen, Duelle, Elo-Scores (Großbaustelle R, ADR 0045).

Nur Persistenz + Elo-Rechnung. Die Duelle sind die append-only-Rohwahrheit
(von Feral Strawberry erzeugte Urteile, manuelle Schicht im Sinne von ADR 0005); die
Scores sind eine abgeleitete Sicht und jederzeit per :func:`recompute_scores`
deterministisch aus dem Duell-Log reproduzierbar (Rescan-Prinzip).

Population/Paar-Auswahl/Bestenliste leben in ``feral.web.rankings`` — sie
brauchen die Filtergrammatik, und die Import-Richtung ist web → db.
``now`` ist für Tests injizierbar (Muster wie ``store.py``/``manual.py``).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..messages import UserError
from .store import now_iso

# Elo-Parameter (ADR 0045): Startwert und fester K-Faktor. Bewusst nicht
# konfigurierbar — wer andere Werte will, ändert sie hier und rechnet per
# Replay neu.
START_SCORE = 1000.0
K_FACTOR = 32.0

# Duell-Ausgänge (Spalte ranking_duels.outcome, Migration 0021).
WIN = "sieg"
BOTH_LOST = "beide_verloren"


def expected(score_a: float, score_b: float) -> float:
    """Elo-Erwartungswert für A gegen B (0..1)."""
    return 1.0 / (1.0 + 10.0 ** ((score_b - score_a) / 400.0))


# -- Arenen (CRUD, Muster folders.py) -----------------------------------------


def create(
    conn: sqlite3.Connection, name: str, expression: str, *, now: str | None = None
) -> int:
    """Arena anlegen; Name case-insensitiv einmalig. Liefert die ID.

    Ein leerer Ausdruck ist erlaubt und heißt „ganze Bibliothek" (dieselbe
    Konvention wie bei den Sammel-Aktionen, ADR 0040). Die Grammatik prüft
    die API-Schicht vorab (Muster Smart Folders).
    """
    name = (name or "").strip()
    if not name:
        raise UserError("arenaNeedsName")
    ts = now or now_iso()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO rankings (name, expression, created_at, updated_at)"
                " VALUES (?, ?, ?, ?)",
                (name, (expression or "").strip(), ts, ts),
            )
    except sqlite3.IntegrityError:
        raise UserError("arenaNameTaken", name=name)
    return int(cur.lastrowid)


def update(
    conn: sqlite3.Connection,
    ranking_id: int,
    name: str,
    expression: str,
    *,
    now: str | None = None,
) -> None:
    """Arena umbenennen und/oder Population ändern. Die Duelle bleiben —
    die Population wird ohnehin bei jeder Paar-Auswahl live ausgewertet."""
    name = (name or "").strip()
    if not name:
        raise UserError("arenaNeedsName")
    try:
        with conn:
            cur = conn.execute(
                "UPDATE rankings SET name = ?, expression = ?, updated_at = ?"
                " WHERE id = ?",
                (name, (expression or "").strip(), now or now_iso(), ranking_id),
            )
    except sqlite3.IntegrityError:
        raise UserError("arenaNameTaken", name=name)
    if cur.rowcount == 0:
        raise UserError("arenaGone")


def delete(conn: sqlite3.Connection, ranking_id: int) -> bool:
    """Arena löschen (bewusster Akt, ADR 0045) — CASCADE räumt Duelle und
    Scores mit ab. True, wenn eine entfernt wurde."""
    with conn:
        cur = conn.execute("DELETE FROM rankings WHERE id = ?", (ranking_id,))
    return cur.rowcount > 0


def get(conn: sqlite3.Connection, ranking_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, name, expression, created_at, updated_at"
        " FROM rankings WHERE id = ?",
        (ranking_id,),
    ).fetchone()
    return dict(row) if row else None


def list_rankings(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Alle Arenen, alphabetisch, mit Duell-Zähler."""
    return [
        dict(r)
        for r in conn.execute(
            """SELECT r.id, r.name, r.expression, r.created_at, r.updated_at,
                      (SELECT COUNT(*) FROM ranking_duels d
                        WHERE d.ranking_id = r.id) AS duels
                 FROM rankings r ORDER BY r.name COLLATE NOCASE"""
        )
    ]


# -- Duelle + Scores ------------------------------------------------------------


def _elo_deltas(
    score_a: float, score_b: float, outcome: str
) -> tuple[float, float]:
    """Score-Änderungen (delta_a, delta_b) für einen Duell-Ausgang.

    EINE Formel-Stelle für inkrementellen Weg UND Replay — Drift zwischen
    beiden wäre ein Bug (Test sichert das ab). ``sieg``: A gewinnt gegen B.
    ``beide_verloren`` (ADR-0045-Ergänzung): beide verlieren gegen einen
    virtuellen Durchschnittsgegner (START_SCORE) — wer hoch steht, verliert
    mehr; bei 1000 sind es K/2 = 16 Punkte.
    """
    if outcome == BOTH_LOST:
        return (
            -K_FACTOR * expected(score_a, START_SCORE),
            -K_FACTOR * expected(score_b, START_SCORE),
        )
    gain = K_FACTOR * (1.0 - expected(score_a, score_b))
    return gain, -gain


def _apply_outcome(
    conn: sqlite3.Connection,
    ranking_id: int,
    hash_a: str,
    hash_b: str,
    outcome: str,
    ts: str,
) -> tuple[float, float]:
    """Ein Elo-Update auf ``ranking_scores`` (Upsert); liefert die neuen Scores.

    ``sieg``: hash_a ist der Gewinner. ``beide_verloren``: Reihenfolge egal.
    """
    scores = {hash_a: START_SCORE, hash_b: START_SCORE}
    duels = {hash_a: 0, hash_b: 0}
    for row in conn.execute(
        "SELECT file_hash, score, duels FROM ranking_scores"
        " WHERE ranking_id = ? AND file_hash IN (?, ?)",
        (ranking_id, hash_a, hash_b),
    ):
        scores[row["file_hash"]] = row["score"]
        duels[row["file_hash"]] = row["duels"]
    delta_a, delta_b = _elo_deltas(scores[hash_a], scores[hash_b], outcome)
    new_a, new_b = scores[hash_a] + delta_a, scores[hash_b] + delta_b
    conn.executemany(
        """INSERT INTO ranking_scores (ranking_id, file_hash, score, duels, updated_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(ranking_id, file_hash) DO UPDATE SET
               score = excluded.score, duels = excluded.duels,
               updated_at = excluded.updated_at""",
        [
            (ranking_id, hash_a, new_a, duels[hash_a] + 1, ts),
            (ranking_id, hash_b, new_b, duels[hash_b] + 1, ts),
        ],
    )
    return new_a, new_b


def record_duel(
    conn: sqlite3.Connection,
    ranking_id: int,
    winner_hash: str,
    loser_hash: str,
    *,
    outcome: str = WIN,
    now: str | None = None,
) -> dict[str, float]:
    """Duell-Ausgang festhalten: Log-Zeile (append-only) + Elo-Update in
    EINER Transaktion. Überspringen erzeugt bewusst KEINEN Aufruf (ADR 0045).

    ``outcome=WIN``: winner_hash gewinnt. ``outcome=BOTH_LOST``
    (ADR-0045-Ergänzung): beide verlieren gegen den virtuellen
    Durchschnittsgegner — die Spaltennamen winner/loser sind dann nur
    Ablageplätze, die Reihenfolge ist egal.

    Liefert ``{hash: neuer Score, …}`` für die UI.
    """
    if outcome not in (WIN, BOTH_LOST):
        raise UserError("duelUnknownOutcome", outcome=repr(outcome))
    if winner_hash == loser_hash:
        raise UserError("duelSameItem")
    if get(conn, ranking_id) is None:
        raise UserError("arenaGone")
    for file_hash in (winner_hash, loser_hash):
        row = conn.execute(
            "SELECT 1 FROM items WHERE file_hash = ?", (file_hash,)
        ).fetchone()
        if row is None:
            raise UserError("itemUnknown", hash=file_hash)
    ts = now or now_iso()
    with conn:
        conn.execute(
            "INSERT INTO ranking_duels"
            " (ranking_id, winner_hash, loser_hash, outcome, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (ranking_id, winner_hash, loser_hash, outcome, ts),
        )
        new_a, new_b = _apply_outcome(
            conn, ranking_id, winner_hash, loser_hash, outcome, ts
        )
    return {winner_hash: new_a, loser_hash: new_b}


def recompute_scores(
    conn: sqlite3.Connection, ranking_id: int | None = None, *, now: str | None = None
) -> int:
    """Scores aus dem Duell-Log neu ableiten (Rescan-Prinzip, ADR 0045).

    Replay in fester Reihenfolge (created_at, id) — deterministisch, ersetzt
    den Bestand vollständig. ``ranking_id=None`` = alle Arenen (Admin-Knopf).
    Liefert die Zahl der abgespielten Duelle.
    """
    ts = now or now_iso()
    where, params = ("WHERE ranking_id = ?", [ranking_id]) if ranking_id is not None else ("", [])
    with conn:
        conn.execute(f"DELETE FROM ranking_scores {where}", params)
        scores: dict[tuple[int, str], float] = {}
        duels: dict[tuple[int, str], int] = {}
        replayed = 0
        for row in conn.execute(
            f"""SELECT ranking_id, winner_hash, loser_hash, outcome FROM ranking_duels
                {where} ORDER BY ranking_id, created_at, id""",
            params,
        ):
            rid, a, b = row["ranking_id"], row["winner_hash"], row["loser_hash"]
            ka, kb = (rid, a), (rid, b)
            delta_a, delta_b = _elo_deltas(
                scores.get(ka, START_SCORE), scores.get(kb, START_SCORE), row["outcome"]
            )
            scores[ka] = scores.get(ka, START_SCORE) + delta_a
            scores[kb] = scores.get(kb, START_SCORE) + delta_b
            duels[ka] = duels.get(ka, 0) + 1
            duels[kb] = duels.get(kb, 0) + 1
            replayed += 1
        conn.executemany(
            "INSERT INTO ranking_scores (ranking_id, file_hash, score, duels, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            [(rid, fh, score, duels[(rid, fh)], ts) for (rid, fh), score in scores.items()],
        )
    return replayed
