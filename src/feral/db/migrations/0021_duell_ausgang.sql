-- Duell-Ausgang „beide verloren" (ADR 0045, Ergänzung 2026-07-13):
-- Feral Strawberrys Praxisbefund — Überspringen schreibt nichts, also bleiben schlechte
-- Bilder „am wenigsten verglichen" und die Abdeckungs-Auswahl schlägt sie
-- immer wieder vor. Neuer Ausgang: beide bekommen ein Duell und verlieren
-- gegen einen virtuellen Durchschnittsgegner (START_SCORE).
--
-- outcome = 'sieg' (winner_hash gewinnt gegen loser_hash, wie bisher)
--         | 'beide_verloren' (beide Hashes verlieren; Spaltenreihenfolge egal)
ALTER TABLE ranking_duels ADD COLUMN outcome TEXT NOT NULL DEFAULT 'sieg';
