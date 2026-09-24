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


# -- Ausscheiden aus der Arena (#87, ADR-0045-Nachtrag 2026-09-08) ------------------


def _eliminated(db, arena):
    return {
        r[0]: r[1]
        for r in db.execute(
            "SELECT file_hash, eliminated FROM ranking_scores WHERE ranking_id=?", (arena,)
        )
    }


def test_both_lost_eliminates_both(db, arena):
    # „Beide raus": Punktabzug bleibt (Entscheidung 1), dazu sind beide ab
    # jetzt aus dem Pool dieser Arena — abgeleitet aus dem Log, keine
    # eigene Tabelle (Entscheidung 4).
    rankings_db.record_duel(db, arena, A, B, outcome=rankings_db.BOTH_LOST, now=T0)
    assert _eliminated(db, arena) == {A: 1, B: 1}


def test_win_duel_keeps_elimination(db, arena):
    # Ein vorgeholtes Sieg-Duell darf den Zustand nicht zurücksetzen.
    rankings_db.record_duel(db, arena, A, B, outcome=rankings_db.BOTH_LOST, now=T0)
    rankings_db.record_duel(db, arena, A, C, now=T1)
    assert _eliminated(db, arena) == {A: 1, B: 1, C: 0}


def test_next_pair_excludes_eliminated(db, arena):
    rankings_db.record_duel(db, arena, A, B, outcome=rankings_db.BOTH_LOST, now=T0)
    ranking = rankings_db.get(db, arena)
    for _ in range(10):
        pair = rankings_web.next_pair(db, ranking, rng=random.Random(5))
        assert pair["eliminated"] == 2
        assert _pair_hashes(pair) == {C, D}


def test_next_pair_reports_exhausted_pool(db, arena):
    # Weniger als zwei Aktive: kein 409 („Arena zu klein"), sondern die
    # Zahlen für den Hinweis (Entscheidung „Pool leer": Hinweis mit Zahlen).
    rankings_db.record_duel(db, arena, A, B, outcome=rankings_db.BOTH_LOST, now=T0)
    rankings_db.record_duel(db, arena, C, D, outcome=rankings_db.BOTH_LOST, now=T0)
    ranking = rankings_db.get(db, arena)
    assert rankings_web.next_pair(db, ranking) == {
        "population": 4, "eliminated": 4, "pair": None,
    }


def test_reinstate_restores_pool_keeps_score_and_logs(db, arena):
    # Rückweg append-only (Entscheidung 3): eine zurueck-Zeile, kein Löschen;
    # Score und Duell-Zahl bleiben.
    rankings_db.record_duel(db, arena, A, B, outcome=rankings_db.BOTH_LOST, now=T0)
    rankings_db.reinstate(db, arena, A, now=T1)
    assert _eliminated(db, arena) == {A: 0, B: 1}
    row = db.execute(
        "SELECT score, duels FROM ranking_scores WHERE ranking_id=? AND file_hash=?",
        (arena, A),
    ).fetchone()
    assert (row[0], row[1]) == (pytest.approx(984.0), 1)
    log = db.execute(
        "SELECT winner_hash, loser_hash, outcome FROM ranking_duels ORDER BY id"
    ).fetchall()
    assert [tuple(r) for r in log] == [(A, B, "beide_verloren"), (A, A, "zurueck")]
    ranking = rankings_db.get(db, arena)
    hashes = set()
    for _ in range(20):
        hashes |= _pair_hashes(rankings_web.next_pair(db, ranking, rng=random.Random(6)))
    assert A in hashes and B not in hashes


def test_reinstate_requires_eliminated(db, arena):
    rankings_db.record_duel(db, arena, A, B, now=T0)
    with pytest.raises(rankings_db.UserError):
        rankings_db.reinstate(db, arena, A, now=T1)       # aktiv
    with pytest.raises(rankings_db.UserError):
        rankings_db.reinstate(db, arena, C, now=T1)       # nie verglichen
    assert db.execute("SELECT COUNT(*) FROM ranking_duels").fetchone()[0] == 1


def test_reinstate_is_not_a_duel(db, arena):
    rankings_db.record_duel(db, arena, A, B, outcome=rankings_db.BOTH_LOST, now=T0)
    rankings_db.reinstate(db, arena, A, now=T1)
    assert rankings_db.list_rankings(db)[0]["duels"] == 1


def test_recompute_restores_elimination_state(db, arena):
    # Replay muss auch den Ausscheide-Zustand reproduzieren: raus, wieder
    # rein, erneut raus — die letzte Zeile zählt. Zahl = echte Duelle.
    steps = [
        ("both", A, B), ("re", A, None), ("win", A, C), ("both", A, D), ("re", D, None),
        ("out", D, C),
    ]
    for i, (kind, x, y) in enumerate(steps):
        ts = f"2026-01-0{i + 1}T00:00:00+00:00"
        if kind == "both":
            rankings_db.record_duel(db, arena, x, y, outcome=rankings_db.BOTH_LOST, now=ts)
        elif kind == "win":
            rankings_db.record_duel(db, arena, x, y, now=ts)
        elif kind == "out":
            rankings_db.record_out(db, arena, x, y, now=ts)
        else:
            rankings_db.reinstate(db, arena, x, now=ts)
    before = {
        r[0]: (r[1], r[2], r[3])
        for r in db.execute(
            "SELECT file_hash, score, duels, eliminated FROM ranking_scores WHERE ranking_id=?",
            (arena,),
        )
    }
    assert {h: e for h, (_, _, e) in before.items()} == {A: 1, B: 1, C: 1, D: 0}
    assert rankings_db.recompute_scores(db, arena, now=T1) == 4
    after = {
        r[0]: (r[1], r[2], r[3])
        for r in db.execute(
            "SELECT file_hash, score, duels, eliminated FROM ranking_scores WHERE ranking_id=?",
            (arena,),
        )
    }
    assert after.keys() == before.keys()
    for h, (score, duels, eliminated) in before.items():
        assert after[h][0] == pytest.approx(score)
        assert after[h][1:] == (duels, eliminated)


def test_leaderboard_puts_eliminated_last(db, arena):
    # Entscheidung 2: Ausgeschiedene geschlossen am Ende, unter sich nach
    # Score; total zählt alle Gelisteten, eliminated sagt wie viele.
    rankings_db.record_duel(db, arena, A, B, now=T0)                        # A 1016, B 984
    rankings_db.record_duel(db, arena, C, D, outcome=rankings_db.BOTH_LOST, now=T0)  # 984
    rankings_db.record_duel(db, arena, C, B, now=T1)                        # C 1000, B 968
    ranking = rankings_db.get(db, arena)
    board = rankings_web.leaderboard(db, ranking)
    assert (board["total"], board["eliminated"]) == (4, 2)
    assert [e["file_hash"] for e in board["entries"]] == [A, B, C, D]
    assert [e["eliminated"] for e in board["entries"]] == [0, 0, 1, 1]
    assert [e["rank"] for e in board["entries"]] == [1, 2, 3, 4]


def test_migration_0023_backfills_old_both_lost(db, arena):
    # Bestehende „Beide verlieren"-Urteile gelten rückwirkend als
    # Ausscheiden: den Zustand vor der Migration nachstellen und nur den
    # UPDATE-Teil der Migrationsdatei erneut anwenden.
    from pathlib import Path

    from feral.db import database

    rankings_db.record_duel(db, arena, A, B, outcome=rankings_db.BOTH_LOST, now=T0)
    rankings_db.record_duel(db, arena, C, D, now=T0)
    db.execute("UPDATE ranking_scores SET eliminated = 0")
    db.commit()
    sql = (Path(database.__file__).parent / "migrations" / "0023_arena_ausscheiden.sql").read_text(
        encoding="utf-8"
    )
    updates = [s for s in database._statements(sql) if "UPDATE ranking_scores" in s]
    assert len(updates) == 1
    db.execute(updates[0])
    db.commit()
    assert _eliminated(db, arena) == {A: 1, B: 1, C: 0, D: 0}


def test_out_is_a_win_for_the_partner_and_eliminates_the_loser(db, arena):
    # „raus" an der Duellkarte (#87-Nachtrag, Variante 2): der Partner gewinnt
    # nach Elo-Formel, der Verlierer verliert und ist raus — EINE Log-Zeile.
    scores = rankings_db.record_out(db, arena, B, A, now=T0)
    assert scores[B] == pytest.approx(1016.0)
    assert scores[A] == pytest.approx(984.0)
    rows = {
        r[0]: (r[1], r[2])
        for r in db.execute(
            "SELECT file_hash, duels, eliminated FROM ranking_scores WHERE ranking_id=?", (arena,)
        )
    }
    assert rows == {A: (1, 1), B: (1, 0)}
    log = db.execute("SELECT winner_hash, loser_hash, outcome FROM ranking_duels").fetchall()
    assert [tuple(r) for r in log] == [(B, A, "raus")]
    assert rankings_db.list_rankings(db)[0]["duels"] == 1
    ranking = rankings_db.get(db, arena)
    for _ in range(10):
        assert A not in _pair_hashes(rankings_web.next_pair(db, ranking, rng=random.Random(7)))
    # Replay reproduziert Sieg + Ausscheiden.
    assert rankings_db.recompute_scores(db, arena, now=T1) == 1
    assert _eliminated(db, arena) == {A: 1, B: 0}


def test_out_legacy_rows_replay_one_sided(db, arena):
    # Zeilen aus dem ersten Bauzustand (winner == loser) bleiben abspielbar.
    db.execute(
        "INSERT INTO ranking_duels (ranking_id, winner_hash, loser_hash, outcome, created_at)"
        " VALUES (?, ?, ?, 'raus', ?)",
        (arena, A, A, T0),
    )
    db.commit()
    assert rankings_db.recompute_scores(db, arena, now=T1) == 1
    row = db.execute(
        "SELECT score, duels, eliminated FROM ranking_scores WHERE ranking_id=? AND file_hash=?",
        (arena, A),
    ).fetchone()
    assert (row[0], row[1], row[2]) == (pytest.approx(984.0), 1, 1)


# -- Paarung ohne Populations-Kopie (#98, ADR 0072) -------------------------------


def test_next_pair_without_sample_uses_exact_fallback(db, arena, monkeypatch):
    # Stichprobe leer erzwingen: A (und ggf. B) kommen über den exakten
    # Fallback-Lauf — die Semantik „Unbewertete zuerst" bleibt.
    monkeypatch.setattr(rankings_web, "SAMPLE_SIZE", 0)
    rankings_db.record_duel(db, arena, A, B, now=T0)
    ranking = rankings_db.get(db, arena)
    for seed in range(10):
        hashes = _pair_hashes(rankings_web.next_pair(db, ranking, rng=random.Random(seed)))
        assert len(hashes) == 2
        assert hashes & {C, D}   # ein Unbewerteter ist immer dabei


def test_next_pair_all_scored_picks_fewest_duels_and_window(db, arena):
    # Alle bewertet: A = seltenst verglichen (C), B aus dem Fenster um C —
    # A mit 1400 liegt außerhalb und darf nie kommen.
    db.executemany(
        "INSERT INTO ranking_scores (ranking_id, file_hash, score, duels, updated_at)"
        " VALUES (?, ?, ?, ?, ?)",
        [(arena, A, 1400.0, 5, T0), (arena, B, 1000.0, 5, T0),
         (arena, C, 1050.0, 1, T0), (arena, D, 1100.0, 5, T0)],
    )
    db.commit()
    ranking = rankings_db.get(db, arena)
    for seed in range(10):
        hashes = _pair_hashes(rankings_web.next_pair(db, ranking, rng=random.Random(seed)))
        assert C in hashes
        assert A not in hashes


def test_next_pair_population_count_uses_epoch_cache(db, arena, tmp_path):
    from feral.web.cache import COLD_KEY, EpochCache

    cache = EpochCache(tmp_path / "feral.sqlite")
    ranking = rankings_db.get(db, arena)
    scope: dict = {}
    assert rankings_web.next_pair(db, ranking, cache=cache, scope=scope)["population"] == 4
    assert scope[COLD_KEY] == "start"
    scope = {}
    rankings_web.next_pair(db, ranking, cache=cache, scope=scope)
    assert COLD_KEY not in scope   # warm: Zahl aus dem Cache
    rankings_db.record_duel(db, arena, A, B, now=T0)   # Commit ⇒ neue Epoche
    scope = {}
    assert rankings_web.leaderboard(db, ranking, cache=cache, scope=scope)["population"] == 4
    assert scope[COLD_KEY] == "write"
    cache.close()


def test_filtered_arena_scores_and_elimination(db, arena):
    # Gefilterter Pfad (materialisierte CTE, ADR 0072): Population „nur PNG"
    # (A/B/C), A ausgeschieden ⇒ Paar aus {B, C}, Zahlen stimmen, D (JPEG)
    # bleibt draußen — auch in der Bestenliste.
    rid = rankings_db.create(db, "Nur PNG", "container: png", now=T0)
    rankings_db.record_duel(db, rid, A, B, now=T0)
    rankings_db.record_duel(db, rid, A, D, outcome=rankings_db.OUT, now=T0)   # D raus (außerhalb)
    db.execute("UPDATE ranking_scores SET eliminated = 1 WHERE ranking_id = ? AND file_hash = ?",
               (rid, A))
    db.commit()
    ranking = rankings_db.get(db, rid)
    for seed in range(10):
        pair = rankings_web.next_pair(db, ranking, rng=random.Random(seed))
        assert (pair["population"], pair["eliminated"]) == (3, 1)
        assert _pair_hashes(pair) == {B, C}
    board = rankings_web.leaderboard(db, ranking)
    assert (board["population"], board["total"], board["eliminated"]) == (3, 2, 1)
    assert [e["file_hash"] for e in board["entries"]] == [B, A]   # Ausgeschiedene zuletzt


# -- Keine Songs in Arenen (#175) ---------------------------------------------------

SONG = "ee" * 32


def _add_song(db, *, cover: str | None = None) -> None:
    store_extraction(db, file_hash=SONG, file_size=1, path=f"/lib/{SONG[:6]}.mp3",
                     extraction=ContainerExtraction(container="mp3"), now=T0)
    if cover:   # finalisierter Song (ADR 0090): steht in der Galerie, nie in Arenen
        db.execute("INSERT INTO covers (file_hash, cover_hash, created_at, updated_at)"
                   " VALUES (?, ?, ?, ?)", (SONG, cover, T0, T0))
    db.commit()


@pytest.mark.parametrize("cover", [None, A])
def test_library_arena_never_contains_songs(db, arena, cover, tmp_path):
    from feral.web.cache import EpochCache

    _add_song(db, cover=cover)
    # Altlast: ein Duell mit dem Song von vor #175 — die Score-Zeile bleibt
    # fürs Replay, der Song taucht trotzdem nirgends auf.
    rankings_db.record_duel(db, arena, SONG, A, now=T0)
    ranking = rankings_db.get(db, arena)
    cache = EpochCache(tmp_path / "feral.sqlite")
    for seed in range(20):
        pair = rankings_web.next_pair(db, ranking, rng=random.Random(seed), cache=cache)
        assert pair["population"] == 4
        assert SONG not in _pair_hashes(pair)
    board = rankings_web.leaderboard(db, ranking, cache=cache)
    assert board["population"] == 4
    assert [e["file_hash"] for e in board["entries"]] == [A]
    assert board["total"] == 1
    cache.close()


def test_filtered_arena_excludes_songs_and_typ_audio_is_empty(db):
    _add_song(db)
    rid = rankings_db.create(db, "Ohne GIF", "-container: gif", now=T0)
    pair = rankings_web.next_pair(db, rankings_db.get(db, rid), rng=random.Random(5))
    assert pair["population"] == 4
    rid = rankings_db.create(db, "Songs", "typ: audio", now=T0)
    ranking = rankings_db.get(db, rid)
    assert rankings_web.next_pair(db, ranking) is None   # kein Einstieg in eine Audio-Arena
    assert rankings_web.leaderboard(db, ranking)["population"] == 0
