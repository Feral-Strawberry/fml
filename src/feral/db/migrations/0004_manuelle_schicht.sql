-- Migration 0004: Manuelle Schicht — Rating, Notizen, Tags (Stufe 3.1, ADR 0017).
-- Strikt getrennt von extrahiert (Schicht 1/2, ADR 0005): eigene Tabellen,
-- NIE in raw_metadata/interpreted_metadata schreiben. Jede Änderung trägt
-- Zeitstempel (append-only-Tür, ADR 0003); Item-Bezug immer über den Hash.

-- annotations: höchstens eine Zeile pro Item (Rating + Notizen).
-- rating: NULL = unbewertet, 1–5 = Sterne. Eine Zeile ohne Rating und ohne
-- Notizen wird vom Store gelöscht (kein Leichen-Bestand).
CREATE TABLE IF NOT EXISTS annotations (
    file_hash  TEXT PRIMARY KEY NOT NULL REFERENCES items(file_hash) ON DELETE CASCADE,
    rating     INTEGER CHECK (rating BETWEEN 1 AND 5),
    notes      TEXT,
    created_at TEXT NOT NULL,                  -- ISO-8601 UTC
    updated_at TEXT NOT NULL
);

-- tags: das wachsende Vokabular. Namen case-insensitiv einmalig
-- ("Portrait" und "portrait" sind derselbe Tag). Tags überleben, auch wenn
-- kein Item sie mehr trägt — das Vokabular ist Kapital (Vorgriff auf Stufe 6).
CREATE TABLE IF NOT EXISTS tags (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL
);

-- item_tags: n:m zwischen Items und Tags.
CREATE TABLE IF NOT EXISTS item_tags (
    file_hash  TEXT NOT NULL REFERENCES items(file_hash) ON DELETE CASCADE,
    tag_id     INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (file_hash, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_item_tags_tag ON item_tags(tag_id);
CREATE INDEX IF NOT EXISTS idx_annotations_rating ON annotations(rating);
