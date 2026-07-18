-- ADR 0021: Medien-Erstelldatum (YYYY-MM-DD, NULL = unbekannt/unplausibel).
-- Bisher steckte das Datum nur im Import-Zielpfad; für „Nach Jahr"-Filter
-- braucht es die Spalte. Befüllt bei Import und (Re-)Scan über die
-- Datums-Kaskade aus ADR 0019.
ALTER TABLE items ADD COLUMN media_date TEXT;

CREATE INDEX IF NOT EXISTS idx_items_media_date
    ON items(media_date DESC, file_hash);
