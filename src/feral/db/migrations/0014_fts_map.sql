-- ADR 0024, Nachbesserung: Zuordnung Hash → FTS-rowid. Das Aktualisieren je
-- Item lief sonst als Voll-Scan der FTS-Tabelle (file_hash ist dort
-- UNINDEXED) — bei 250k ein O(n²)-Fressloch für Import/Scan/Reindex.
CREATE TABLE IF NOT EXISTS search_index_map (
    file_hash TEXT PRIMARY KEY NOT NULL,
    fts_rowid INTEGER NOT NULL
);
