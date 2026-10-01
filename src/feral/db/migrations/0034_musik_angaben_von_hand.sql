-- ADR 0101 (#256): Musik-Angaben von Hand, Teil der manuellen Schicht
-- (ADR 0005). Je Song und Feld (title, artist, album_artist, album, track,
-- disc, year, genre) ein Wert, bei artist/genre mehrere (ordinal). Die
-- Werte überdecken beim Schreiben der Interpretation die Tag-Werte
-- (interpreted_metadata, parser = 'manual'); die Dateien bleiben
-- unangetastet. source: NULL = hier eingegeben, sonst das Herkunfts-Etikett
-- eines Imports (wie time_comments.source).
CREATE TABLE manual_fields (
    file_hash  TEXT    NOT NULL REFERENCES items(file_hash) ON DELETE CASCADE,
    field      TEXT    NOT NULL,
    ordinal    INTEGER NOT NULL DEFAULT 0,
    value      TEXT    NOT NULL,
    source     TEXT,
    updated_at TEXT    NOT NULL,
    PRIMARY KEY (file_hash, field, ordinal)
);
