-- Migration 0008: Indizes für 250k-Bestände (Block 4S, aus Feral Strawberrys 54k-Lauf).
-- Gemessen an synthetischen 100k Items / 2 GB: Grid-Seite 185 ms → <1 ms,
-- tiefe Seite (OFFSET 80k) 109 ms → 2 ms. Ohne diese Indizes sortiert JEDE
-- Grid-Anfrage den kompletten Bestand.

CREATE INDEX IF NOT EXISTS idx_items_first_seen ON items(first_seen_at DESC, file_hash);
CREATE INDEX IF NOT EXISTS idx_items_size       ON items(file_size DESC, file_hash);
CREATE INDEX IF NOT EXISTS idx_items_container  ON items(container, first_seen_at DESC, file_hash);
