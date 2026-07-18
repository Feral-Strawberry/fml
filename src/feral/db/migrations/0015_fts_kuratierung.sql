-- ADR 0036: kuratierter FTS-Index. Zwei Defekte aus Feral Strawberrys Alltag: Tags/
-- Notizen/manuelles Modell waren gar nicht frei durchsuchbar, und wer „hund"
-- suchte, fand über Roh-Blobs und interp auch Anti-Hund-Bilder
-- (negative_prompt). Fünf Spalten statt drei; die Standard-Suche matcht nur
-- {interp names manuell} — negativ und raw bleiben gezielt erreichbar.
-- FTS5 kann kein ALTER TABLE: neu anlegen, der Start-Abgleich (ADR 0024)
-- baut den Bestand einmalig neu auf (Zeilenzahl-Drift wird erkannt).
DROP TABLE IF EXISTS search_index;
CREATE VIRTUAL TABLE search_index USING fts5(
    interp,                 -- Schicht-2-Werte OHNE negative_prompt
    names,                  -- Basenamen der Fundorte
    manuell,                -- manuelle Schicht: Tags, Notizen, manuelles Modell
    negativ,                -- negative_prompt (nur gezielt durchsuchbar)
    raw,                    -- Roh-Texte (Schicht 1, nur auf Wunsch)
    file_hash UNINDEXED,
    tokenize = 'unicode61'
);
DELETE FROM search_index_map;
