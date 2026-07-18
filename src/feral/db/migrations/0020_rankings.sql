-- Migration 0020: Ranking-Modul (Großbaustelle R, ADR 0045).
-- Eine Arena ist NUR ein Name + Filterausdruck als Population (Muster
-- smart_folders); die Duelle sind die append-only-Rohwahrheit, die Scores
-- eine abgeleitete, jederzeit per Replay reproduzierbare Sicht.

CREATE TABLE IF NOT EXISTS rankings (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    expression TEXT NOT NULL,                  -- '' = ganze Bibliothek
    created_at TEXT NOT NULL,                  -- ISO-8601 UTC
    updated_at TEXT NOT NULL
);

-- Bewusst KEIN Foreign Key auf items (ADR 0045): verschwindet ein Item aus
-- der Bibliothek, bleibt seine Duell-Geschichte vollständig — sonst hinge
-- das Replay-Ergebnis von der Löschhistorie ab.
CREATE TABLE IF NOT EXISTS ranking_duels (
    id          INTEGER PRIMARY KEY,
    ranking_id  INTEGER NOT NULL REFERENCES rankings(id) ON DELETE CASCADE,
    winner_hash TEXT NOT NULL,
    loser_hash  TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

-- Replay liest je Arena in fester Reihenfolge (created_at, dann id).
CREATE INDEX IF NOT EXISTS idx_ranking_duels_replay
    ON ranking_duels(ranking_id, created_at, id);

CREATE TABLE IF NOT EXISTS ranking_scores (
    ranking_id INTEGER NOT NULL REFERENCES rankings(id) ON DELETE CASCADE,
    file_hash  TEXT NOT NULL,
    score      REAL NOT NULL,
    duels      INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (ranking_id, file_hash)
);

-- Bestenliste sortiert je Arena nach Score.
CREATE INDEX IF NOT EXISTS idx_ranking_scores_order
    ON ranking_scores(ranking_id, score DESC);
