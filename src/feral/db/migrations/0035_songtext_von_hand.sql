-- ADR 0106 (#285): Songtext von Hand, Teil der manuellen Schicht (ADR 0005).
-- Ein Dokument je Song: lines = JSON [[start_ms|null, end_ms|null, "Zeile"], …]
-- wie lyrics_synced, die Startzeit darf fehlen. Es überdeckt beim Schreiben
-- der Interpretation lyrics, lyrics_synced und song_sections aller Parser
-- (interpreted_metadata, parser = 'manual'); die Dateien bleiben
-- unangetastet. source: NULL = hier eingegeben, sonst das Herkunfts-Etikett
-- eines Imports (wie manual_fields.source).
CREATE TABLE manual_lyrics (
    file_hash  TEXT NOT NULL PRIMARY KEY REFERENCES items(file_hash) ON DELETE CASCADE,
    lines      TEXT NOT NULL,
    source     TEXT,
    updated_at TEXT NOT NULL
);
