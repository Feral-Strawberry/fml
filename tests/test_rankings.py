"""Tests für das Ranking-Modul (Großbaustelle R, ADR 0045)."""

from __future__ import annotations

import random

import pytest

from feral.db import connect, store_extraction
from feral.db import rankings as rankings_db
from feral.extract.types import ContainerExtraction
from feral.web import rankings as rankings_web

T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-01-02T00:00:00+00:00"

A = "aa" * 32
B = "bb" * 32
C = "cc" * 32
D = "dd" * 32


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    for file_hash, container in ((A, "png"), (B, "png"), (C, "png"), (D, "jpeg")):
        store_extraction(
            conn,
            file_hash=file_hash,
            file_size=123,
            path=tmp_path / f"{file_hash[:6]}.{container}",
            extraction=ContainerExtraction(container=container),
            now=T0,
        )
    yield conn
    conn.close()


@pytest.fixture
def arena(db):
    return rankings_db.create(db, "Testarena", "", now=T0)


# -- Arenen (CRUD) ---------------------------------------------------------------


def test_create_requires_name(db):
    with pytest.raises(ValueError):
        rankings_db.create(db, "  ", "")


def test_create_rejects_duplicate_name_case_insensitive(db, arena):
    with pytest.raises(ValueError):
        rankings_db.create(db, "TESTARENA", "")


def test_update_and_list(db, arena):
    rankings_db.update(db, arena, "Porträts", "container: png", now=T1)
    (entry,) = rankings_db.list_rankings(db)
    assert entry["name"] == "Porträts"
    assert entry["expression"] == "container: png"
    assert entry["duels"] == 0


def test_update_unknown_arena(db):
    with pytest.raises(ValueError):
        rankings_db.update(db, 999, "X", "")


def test_delete_cascades_duels_and_scores(db, arena):
    rankings_db.record_duel(db, arena, A, B, now=T0)
    assert rankings_db.delete(db, arena) is True
    assert db.execute("SELECT COUNT(*) FROM ranking_duels").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM ranking_scores").fetchone()[0] == 0
    assert rankings_db.delete(db, arena) is False


# -- Duelle + Elo -----------------------------------------------------------------


def test_first_duel_moves_16_points(db, arena):
    scores = rankings_db.record_duel(db, arena, A, B, now=T0)
    # Gleichstand (1000:1000) ⇒ Erwartung 0,5 ⇒ Gewinn = K/2 = 16.
    assert scores[A] == pytest.approx(1016.0)
    assert scores[B] == pytest.approx(984.0)


def test_duel_is_logged_append_only(db, arena):
    rankings_db.record_duel(db, arena, A, B, now=T0)
    rankings_db.record_duel(db, arena, B, A, now=T1)
    rows = db.execute(
        "SELECT winner_hash, loser_hash FROM ranking_duels ORDER BY created_at, id"
    ).fetchall()
    assert [(r[0], r[1]) for r in rows] == [(A, B), (B, A)]


def test_underdog_win_pays_more(db, arena):
    # A gewinnt dreimal gegen B, dann gewinnt B einmal: der Außenseiter-Sieg
    # bringt B mehr als 16 Punkte (Gegnerstärke zählt — der Witz von Elo).
    for _ in range(3):
        rankings_db.record_duel(db, arena, A, B, now=T0)
    before = db.execute(
        "SELECT score FROM ranking_scores WHERE ranking_id=? AND file_hash=?",
        (arena, B),
    ).fetchone()[0]
    after = rankings_db.record_duel(db, arena, B, A, now=T1)[B]
    assert after - before > 16.0


def test_duel_validates_items_and_arena(db, arena):
    with pytest.raises(ValueError):
        rankings_db.record_duel(db, arena, A, A)
    with pytest.raises(ValueError):
        rankings_db.record_duel(db, arena, A, "ff" * 32)
    with pytest.raises(ValueError):
        rankings_db.record_duel(db, 999, A, B)
    with pytest.raises(ValueError):
        rankings_db.record_duel(db, arena, A, B, outcome="unentschieden")


def test_both_lost_drops_both_and_counts_duels(db, arena):
    # ADR-0045-Ergänzung: beide verlieren gegen den virtuellen
    # Durchschnittsgegner — bei 1000 sind das K/2 = 16 Punkte je Item,
    # und beide bekommen ein Duell (Abdeckung: das Paar drängt sich
    # nicht wieder auf).
    scores = rankings_db.record_duel(
        db, arena, A, B, outcome=rankings_db.BOTH_LOST, now=T0
    )
    assert scores[A] == pytest.approx(984.0)
    assert scores[B] == pytest.approx(984.0)
    rows = db.execute(
        "SELECT file_hash, duels FROM ranking_scores WHERE ranking_id=?", (arena,)
    ).fetchall()
    assert {r[0]: r[1] for r in rows} == {A: 1, B: 1}
    assert db.execute("SELECT outcome FROM ranking_duels").fetchone()[0] == "beide_verloren"


def test_both_lost_penalizes_high_scores_more(db, arena):
    # Wer über dem Durchschnitt steht, „sollte" gewinnen — und verliert
    # beim Doppel-Verlust entsprechend mehr als ein bereits Abgestrafter.
    rankings_db.record_duel(db, arena, A, B, now=T0)        # A 1016, B 984
    scores = rankings_db.record_duel(
        db, arena, A, B, outcome=rankings_db.BOTH_LOST, now=T1
    )
    assert 1016.0 - scores[A] > 16.0 > 984.0 - scores[B]


def test_recompute_matches_incremental(db, arena):
    # Replay und inkrementeller Weg müssen dieselben Zahlen liefern —
    # sonst wäre „Scores neu berechnen" (Rescan-Prinzip) eine Lüge.
    # Gemischte Ausgänge: Siege UND „beide verloren" (Migration 0021).
    duels = [
        (A, B, rankings_db.WIN),
        (B, C, rankings_db.WIN),
        (A, C, rankings_db.BOTH_LOST),
        (C, A, rankings_db.WIN),
        (A, B, rankings_db.BOTH_LOST),
    ]
    for i, (w, l, outcome) in enumerate(duels):
        rankings_db.record_duel(
            db, arena, w, l, outcome=outcome, now=f"2026-01-0{i + 1}T00:00:00+00:00"
        )
    incremental = {
        r[0]: (r[1], r[2])
        for r in db.execute(
            "SELECT file_hash, score, duels FROM ranking_scores WHERE ranking_id=?",
            (arena,),
        )
    }
    assert rankings_db.recompute_scores(db, arena, now=T1) == len(duels)
    replayed = {
        r[0]: (r[1], r[2])
        for r in db.execute(
            "SELECT file_hash, score, duels FROM ranking_scores WHERE ranking_id=?",
            (arena,),
        )
    }
    assert replayed.keys() == incremental.keys()
    for file_hash, (score, count) in incremental.items():
        assert replayed[file_hash][0] == pytest.approx(score)
        assert replayed[file_hash][1] == count


def test_duel_log_survives_item_deletion(db, arena):
    # ADR 0045: kein FK auf items — Item weg, Geschichte bleibt, Replay läuft.
    rankings_db.record_duel(db, arena, A, B, now=T0)
    db.execute("DELETE FROM items WHERE file_hash = ?", (A,))
    db.commit()
    assert rankings_db.recompute_scores(db, arena, now=T1) == 1
    row = db.execute(
        "SELECT score FROM ranking_scores WHERE ranking_id=? AND file_hash=?",
        (arena, A),
    ).fetchone()
    assert row[0] == pytest.approx(1016.0)


def test_recompute_all_arenas(db, arena):
    other = rankings_db.create(db, "Zweite", "", now=T0)
    rankings_db.record_duel(db, arena, A, B, now=T0)
    rankings_db.record_duel(db, other, C, D, now=T0)
    assert rankings_db.recompute_scores(db) == 2


# -- Paar-Auswahl -----------------------------------------------------------------


def _pair_hashes(pair):
    return {entry["file_hash"] for entry in pair["pair"]}


def test_next_pair_needs_two_items(db):
    rid = rankings_db.create(db, "Nur JPEG", "container: jpeg", now=T0)  # nur D
    ranking = rankings_db.get(db, rid)
    assert rankings_web.next_pair(db, ranking) is None


def test_next_pair_respects_population(db):
    rid = rankings_db.create(db, "Nur PNG", "container: png", now=T0)
    ranking = rankings_db.get(db, rid)
    for _ in range(10):
        pair = rankings_web.next_pair(db, ranking, rng=random.Random(1))
        assert pair["population"] == 3
        hashes = _pair_hashes(pair)
        assert len(hashes) == 2
        assert D not in hashes


def test_next_pair_prefers_least_dueled(db, arena):
    # A/B/D haben je ein Duell, C keins ⇒ Kandidat A der Auswahl ist immer C.
    rankings_db.record_duel(db, arena, A, B, now=T0)
    rankings_db.record_duel(db, arena, A, D, now=T0)
    rankings_db.record_duel(db, arena, B, D, now=T0)
    ranking = rankings_db.get(db, arena)
    for _ in range(10):
        assert C in _pair_hashes(rankings_web.next_pair(db, ranking, rng=random.Random(2)))


def test_next_pair_falls_back_outside_window(db, arena):
    # Scores künstlich weit auseinander (> Fenster): es kommt trotzdem ein Paar.
    db.execute(
        "INSERT INTO ranking_scores (ranking_id, file_hash, score, duels, updated_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (arena, A, 5000.0, 3, T0),
    )
    db.executemany(
        "INSERT INTO ranking_scores (ranking_id, file_hash, score, duels, updated_at)"
        " VALUES (?, ?, ?, ?, ?)",
        [(arena, h, 1000.0, 5, T0) for h in (B, C, D)],
    )
    db.commit()
    ranking = rankings_db.get(db, arena)
    pair = rankings_web.next_pair(db, ranking, rng=random.Random(3))
    assert A in _pair_hashes(pair)   # A hat die wenigsten Duelle
    assert len(_pair_hashes(pair)) == 2


# -- Bestenliste ------------------------------------------------------------------


def test_leaderboard_orders_and_ranks(db, arena):
    rankings_db.record_duel(db, arena, A, B, now=T0)
    rankings_db.record_duel(db, arena, A, C, now=T0)
    ranking = rankings_db.get(db, arena)
    board = rankings_web.leaderboard(db, ranking)
    assert board["population"] == 4
    assert board["total"] == 3                     # D hat kein Duell
    assert [e["file_hash"] for e in board["entries"]][0] == A
    assert [e["rank"] for e in board["entries"]] == [1, 2, 3]


def test_leaderboard_hides_items_outside_population(db, arena):
    # Verschwundene Items (z. B. abgelehnt) fallen aus der Liste; die
    # Score-Zeile bleibt für das Replay (ADR 0045).
    rankings_db.record_duel(db, arena, A, B, now=T0)
    db.execute("DELETE FROM items WHERE file_hash = ?", (A,))
    db.commit()
    ranking = rankings_db.get(db, arena)
    board = rankings_web.leaderboard(db, ranking)
    assert [e["file_hash"] for e in board["entries"]] == [B]
    assert db.execute(
        "SELECT COUNT(*) FROM ranking_scores WHERE file_hash = ?", (A,)
    ).fetchone()[0] == 1


def test_pair_and_leaderboard_carry_media_kind(db, arena):
    # Block R2: die Duell-Ansicht rendert <img> vs. <video>, die Bestenliste
    # zeigt das VIDEO-Badge — media_kind kommt direkt mit, kein Nachladen.
    ranking = rankings_db.get(db, arena)
    pair = rankings_web.next_pair(db, ranking, rng=random.Random(4))
    assert all(entry["media_kind"] == "image" for entry in pair["pair"])
    rankings_db.record_duel(db, arena, A, B, now=T0)
    board = rankings_web.leaderboard(db, ranking)
    assert all(entry["media_kind"] == "image" for entry in board["entries"])


def test_leaderboard_paging(db, arena):
    rankings_db.record_duel(db, arena, A, B, now=T0)
    rankings_db.record_duel(db, arena, A, C, now=T0)
    ranking = rankings_db.get(db, arena)
    page = rankings_web.leaderboard(db, ranking, limit=1, offset=1)
    assert page["total"] == 3
    assert len(page["entries"]) == 1
    assert page["entries"][0]["rank"] == 2
