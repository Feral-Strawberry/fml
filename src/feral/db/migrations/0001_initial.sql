-- Feral Media Library — Schema Version 1 (ADR 0010).
-- Stufe 1: Items (Datei-Hash-Identität), Fundorte, Roh-Metadaten (Schicht 1).
-- Interpretierte (Schicht 2) und manuelle Felder kommen später als eigene Tabellen.

-- items: eine Zeile pro einzigartiger Datei, identifiziert über den Datei-Hash.
CREATE TABLE IF NOT EXISTS items (
    file_hash     TEXT PRIMARY KEY NOT NULL,   -- SHA-256 (hex), stabile Item-ID (ADR 0002)
    file_size     INTEGER NOT NULL,            -- Bytes
    container     TEXT NOT NULL,               -- 'png','jpeg','webp',... (über Magic Bytes)
    media_kind    TEXT NOT NULL,               -- 'image' | 'video' | 'document'
    image_hash    TEXT,                        -- optionaler Bilddaten-Hash (ADR 0002), vorerst NULL
    first_seen_at TEXT NOT NULL,               -- ISO-8601 UTC
    updated_at    TEXT NOT NULL                -- ISO-8601 UTC (append-only-Tür, ADR 0003)
);

-- file_locations: wo dieselbe Datei (gleicher Hash) auf der Platte gesehen wurde.
-- Pfad ist Fundort, nicht Identität — eine Datei kann an mehreren Pfaden liegen.
CREATE TABLE IF NOT EXISTS file_locations (
    id            INTEGER PRIMARY KEY,
    file_hash     TEXT NOT NULL REFERENCES items(file_hash) ON DELETE CASCADE,
    path          TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    UNIQUE(file_hash, path)
);

CREATE INDEX IF NOT EXISTS idx_file_locations_hash ON file_locations(file_hash);

-- raw_metadata: Schicht 1, verlustfrei. value_raw ist immer byte-exakt gefüllt;
-- value_text ist der bequem durchsuchbare dekodierte Text (NULL bei binär/kaputt).
CREATE TABLE IF NOT EXISTS raw_metadata (
    id           INTEGER PRIMARY KEY,
    file_hash    TEXT NOT NULL REFERENCES items(file_hash) ON DELETE CASCADE,
    ordinal      INTEGER NOT NULL,             -- Reihenfolge im Container
    source       TEXT NOT NULL,                -- 'png:tEXt','png:iTXt','png:eXIf',...
    keyword      TEXT,                         -- Chunk-Keyword, falls vorhanden
    value_text   TEXT,                         -- dekodierter Text (NULL bei binär/kaputt)
    value_raw    BLOB NOT NULL,                -- byte-exakter Nutzinhalt (immer)
    encoding     TEXT NOT NULL,                -- 'latin-1','utf-8','binary'
    compressed   INTEGER NOT NULL DEFAULT 0,   -- 0/1: lag im Container komprimiert vor
    extracted_at TEXT NOT NULL,                -- ISO-8601 UTC
    UNIQUE(file_hash, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_raw_metadata_hash ON raw_metadata(file_hash);
CREATE INDEX IF NOT EXISTS idx_raw_metadata_keyword ON raw_metadata(keyword);
