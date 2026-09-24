-- Migration 0027: Zeitkommentare (Audio A6, Issue #163, ADR 0083 Punkt 8, ADR 0088).
-- Manuelle Schicht (ADR 0005/0017): Kommentare an Zeitpunkten eines Items,
-- Punkte statt Bereiche. Item-Bezug über den Hash, Zeitstempel je Änderung
-- (append-only-Tür, ADR 0003). Trägt auch Video; die Oberfläche gibt es
-- bisher nur für Audio.
CREATE TABLE IF NOT EXISTS time_comments (
    id         INTEGER PRIMARY KEY,
    file_hash  TEXT NOT NULL REFERENCES items(file_hash) ON DELETE CASCADE,
    at_ms      INTEGER NOT NULL CHECK (at_ms >= 0),   -- Stelle im Medium, Millisekunden
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL,                         -- ISO-8601 UTC
    updated_at TEXT NOT NULL
);

-- Je Item in zeitlicher Folge (Detailpanel, Pins, Zähler der Listenzeile).
CREATE INDEX IF NOT EXISTS idx_time_comments_item ON time_comments(file_hash, at_ms);
