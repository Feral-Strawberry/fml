-- ADR 0024: FTS5-Volltextindex für die Suche (LIKE-Scan war bei 250k 2-9 s).
-- Eine Zeile je Item; befüllt/aktualisiert von store.update_search_index(),
-- Erst-Aufbau für den Alt-Bestand macht die Engine beim App-Start.
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
    interp,                 -- alle Schicht-2-Werte des Items
    raw,                    -- alle Roh-Texte (Schicht 1)
    names,                  -- Basenamen der Fundorte
    file_hash UNINDEXED,
    tokenize = 'unicode61'
);
