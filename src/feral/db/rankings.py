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

# Duell-Ausgänge (Spalte ranking_duels.outcome, Migration 0021). Seit #87
# (ADR-0045-Nachtrag 2026-09-08) nimmt ``beide_verloren`` beide Items
# dauerhaft aus der Arena; ``zurueck`` ist die append-only Gegenzeile
# (winner = loser = das Item, kein Score-/Duell-Effekt). „Ausgeschieden" ist
# damit wie der Score aus dem Log abgeleitet (``ranking_scores.eliminated``,
# Migration 0023) — keine zweite Wahrheit.
WIN = "sieg"
BOTH_LOST = "beide_verloren"
REINSTATED = "zurueck"
# ``raus`` (#87-Nachtrag, Variante 2): ein Duell-Ausgang — winner_hash gewinnt
# wie bei ``sieg``, loser_hash verliert UND scheidet aus der Arena aus.
# Übergangs-Sonderfall winner == loser (Zeilen aus dem ersten Bauzustand):
# einseitiger Verlust gegen den Durchschnittsgegner + Ausscheiden.
OUT = "raus"


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
    """Alle Arenen, alphabetisch, mit Duell-Zähler (Wieder-rein-Zeilen sind
    keine Duelle) und ``rated`` = Items, die schon einen Score haben
    (Admin-Arenen-Tabelle, A3 #107)."""
    return [
        dict(r)
        for r in conn.execute(
            f"""SELECT r.id, r.name, r.expression, r.created_at, r.updated_at,
                      (SELECT COUNT(*) FROM ranking_duels d
                        WHERE d.ranking_id = r.id
                          AND d.outcome != '{REINSTATED}') AS duels,
                      (SELECT COUNT(*) FROM ranking_scores s
                        WHERE s.ranking_id = r.id) AS rated
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
    return gain, -gain   # sieg UND raus: A gewinnt, B verliert (raus: B zusätzlich draußen)


def _apply_outcome(
    conn: sqlite3.Connection,
    ranking_id: int,
    hash_a: str,
    hash_b: str,
    outcome: str,
    ts: str,
) -> tuple[float, float]:
    """Ein Elo-Update auf ``ranking_scores`` (Upsert); liefert die neuen Scores.

    ``sieg``: hash_a ist der Gewinner. ``beide_verloren``: Reihenfolge egal,
    beide gelten ab jetzt als ausgeschieden (#87). Ein Sieg-Duell rührt den
    Ausscheide-Zustand nicht an (Paarbildung schließt Ausgeschiedene ohnehin
    aus; ein vorgeholtes Paar darf den Zustand nicht zurücksetzen).
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
    out_a = 1 if outcome == BOTH_LOST else 0
    out_b = 1 if outcome in (BOTH_LOST, OUT) else 0
    conn.executemany(
        """INSERT INTO ranking_scores
               (ranking_id, file_hash, score, duels, eliminated, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(ranking_id, file_hash) DO UPDATE SET
               score = excluded.score, duels = excluded.duels,
               eliminated = MAX(ranking_scores.eliminated, excluded.eliminated),
               updated_at = excluded.updated_at""",
        [
            (ranking_id, hash_a, new_a, duels[hash_a] + 1, out_a, ts),
            (ranking_id, hash_b, new_b, duels[hash_b] + 1, out_b, ts),
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
    if outcome not in (WIN, BOTH_LOST, OUT):
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


def reinstate(
    conn: sqlite3.Connection, ranking_id: int, file_hash: str, *, now: str | None = None
) -> None:
    """Ausgeschiedenes Item zurück in den Pool der Arena holen (#87).

    Append-only wie alles im Log: eine ``zurueck``-Zeile (winner = loser =
    das Item), kein Löschen. Score und Duell-Zahl bleiben — das Item ordnet
    sich mit seinem alten Elo wieder in die Bestenliste ein. Ein Item, das
    nicht ausgeschieden ist, gibt einen Fehler statt einer Leerzeile im Log.
    """
    if get(conn, ranking_id) is None:
        raise UserError("arenaGone")
    row = conn.execute(
        "SELECT eliminated FROM ranking_scores WHERE ranking_id = ? AND file_hash = ?",
        (ranking_id, file_hash),
    ).fetchone()
    if row is None or not row["eliminated"]:
        raise UserError("arenaItemActive")
    ts = now or now_iso()
    with conn:
        conn.execute(
            "INSERT INTO ranking_duels"
            " (ranking_id, winner_hash, loser_hash, outcome, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (ranking_id, file_hash, file_hash, REINSTATED, ts),
        )
        conn.execute(
            "UPDATE ranking_scores SET eliminated = 0, updated_at = ?"
            " WHERE ranking_id = ? AND file_hash = ?",
            (ts, ranking_id, file_hash),
        )


def record_out(
    conn: sqlite3.Connection,
    ranking_id: int,
    winner_hash: str,
    loser_hash: str,
    *,
    now: str | None = None,
) -> dict[str, float]:
    """„raus" an der Duellkarte (#87-Nachtrag, Variante 2): das Duell endet
    mit einem Sieg des Partners, der Verlierer scheidet zusätzlich aus.
    EINE Log-Zeile (``raus``), damit das Replay ein Ereignis sieht."""
    return record_duel(conn, ranking_id, winner_hash, loser_hash, outcome=OUT, now=now)


def recompute_scores(
    conn: sqlite3.Connection, ranking_id: int | None = None, *, now: str | None = None
) -> int:
    """Scores aus dem Duell-Log neu ableiten (Rescan-Prinzip, ADR 0045).

    Replay in fester Reihenfolge (created_at, id) — deterministisch, ersetzt
    den Bestand vollständig, inklusive des Ausscheide-Zustands (#87:
    ``beide_verloren`` setzt ihn, ``zurueck`` hebt ihn auf; die letzte Zeile
    zählt). ``ranking_id=None`` = alle Arenen (Admin-Knopf). Liefert die Zahl
    der abgespielten Duelle (Wieder-rein-Zeilen zählen nicht).
    """
    ts = now or now_iso()
    where, params = ("WHERE ranking_id = ?", [ranking_id]) if ranking_id is not None else ("", [])
    with conn:
        conn.execute(f"DELETE FROM ranking_scores {where}", params)
        scores: dict[tuple[int, str], float] = {}
        duels: dict[tuple[int, str], int] = {}
        eliminated: dict[tuple[int, str], int] = {}
        replayed = 0
        for row in conn.execute(
            f"""SELECT ranking_id, winner_hash, loser_hash, outcome FROM ranking_duels
                {where} ORDER BY ranking_id, created_at, id""",
            params,
        ):
            rid, a, b = row["ranking_id"], row["winner_hash"], row["loser_hash"]
            ka, kb = (rid, a), (rid, b)
            if row["outcome"] == REINSTATED:
                eliminated[ka] = 0
                scores.setdefault(ka, START_SCORE)
                continue
            if row["outcome"] == OUT and a == b:
                # Übergangs-Zeilen des ersten Bauzustands: einseitig.
                base = scores.get(ka, START_SCORE)
                scores[ka] = base + _elo_deltas(base, START_SCORE, BOTH_LOST)[0]
                duels[ka] = duels.get(ka, 0) + 1
                eliminated[ka] = 1
                replayed += 1
                continue
            delta_a, delta_b = _elo_deltas(
                scores.get(ka, START_SCORE), scores.get(kb, START_SCORE), row["outcome"]
            )
            scores[ka] = scores.get(ka, START_SCORE) + delta_a
            scores[kb] = scores.get(kb, START_SCORE) + delta_b
            duels[ka] = duels.get(ka, 0) + 1
            duels[kb] = duels.get(kb, 0) + 1
            if row["outcome"] == BOTH_LOST:
                eliminated[ka] = eliminated[kb] = 1
            elif row["outcome"] == OUT:
                eliminated[kb] = 1
            replayed += 1
        conn.executemany(
            "INSERT INTO ranking_scores"
            " (ranking_id, file_hash, score, duels, eliminated, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                (rid, fh, score, duels.get((rid, fh), 0), eliminated.get((rid, fh), 0), ts)
                for (rid, fh), score in scores.items()
            ],
        )
    return replayed
