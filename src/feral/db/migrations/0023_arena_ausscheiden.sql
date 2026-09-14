-- Issue #87 (ADR-0045-Nachtrag 2026-09-08): „Beide raus" nimmt beide Items
-- dauerhaft aus dieser Arena. Der Zustand ist KEINE zweite Wahrheit, sondern
-- wie der Score aus dem append-only Duell-Log abgeleitet: ausgeschieden =
-- letzte Zustandszeile ist 'beide_verloren', wieder drin = 'zurueck'.
-- Replay (recompute_scores) setzt die Spalte deterministisch neu.
ALTER TABLE ranking_scores ADD COLUMN eliminated INTEGER NOT NULL DEFAULT 0;

-- Backfill: bisherige „Beide verlieren"-Urteile gelten rückwirkend als
-- Ausscheiden (das war die gemeinte Bedeutung, #87). 'zurueck'-Zeilen gibt
-- es vor dieser Migration nicht, die Ableitung ist also exakt.
UPDATE ranking_scores SET eliminated = 1
 WHERE EXISTS (SELECT 1 FROM ranking_duels d
                WHERE d.ranking_id = ranking_scores.ranking_id
                  AND d.outcome = 'beide_verloren'
                  AND (d.winner_hash = ranking_scores.file_hash
                       OR d.loser_hash = ranking_scores.file_hash));

-- Bestenliste: Aktive nach Score, Ausgeschiedene dahinter.
CREATE INDEX IF NOT EXISTS idx_ranking_scores_pool
    ON ranking_scores(ranking_id, eliminated, score DESC);
