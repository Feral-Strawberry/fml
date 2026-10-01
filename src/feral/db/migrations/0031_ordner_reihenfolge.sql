-- ADR 0095 (#218): manuelle Reihenfolge innerhalb einer gespeicherten Suche
-- (Playlist-Probehören). Die Reihenfolge gehört der Suche, nicht dem Medium;
-- hash-basiert wie alles Manuelle. Treffer ohne Zeile stehen hinten
-- (Hinzufüge-Reihenfolge); wer aus der Suche fällt, behält seine Zeile still.
-- Suche gelöscht → Reihenfolge weg (CASCADE), Item abgelehnt → ebenso.
CREATE TABLE IF NOT EXISTS folder_order (
    folder_id INTEGER NOT NULL REFERENCES smart_folders(id) ON DELETE CASCADE,
    file_hash TEXT NOT NULL REFERENCES items(file_hash) ON DELETE CASCADE,
    position  REAL NOT NULL,
    PRIMARY KEY (folder_id, file_hash)
);
