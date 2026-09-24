-- Migration 0028: Cover eines Songs (Audio A8, Issue #165, ADR 0083 Punkt 9, ADR 0090).
-- Manuelle Schicht (ADR 0005/0017): ein Song verweist auf ein Bild der
-- Bibliothek, beide über ihren Hash — die erste Beziehung zwischen zwei
-- Items. Nichts wird in Dateien geschrieben. Wird das Coverbild abgelehnt
-- (Item raus aus der DB, ADR 0041), fällt der Verweis per CASCADE mit, und
-- der Song verlässt die Galerie ohne eigene Prüfung.
CREATE TABLE IF NOT EXISTS covers (
    file_hash  TEXT PRIMARY KEY NOT NULL REFERENCES items(file_hash) ON DELETE CASCADE,  -- der Song
    cover_hash TEXT NOT NULL REFERENCES items(file_hash) ON DELETE CASCADE,               -- das Bild
    created_at TEXT NOT NULL,                  -- ISO-8601 UTC
    updated_at TEXT NOT NULL
);

-- CASCADE beim Ablehnen eines Bildes sucht über die Bildseite.
CREATE INDEX IF NOT EXISTS idx_covers_cover ON covers(cover_hash);
