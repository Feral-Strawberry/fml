-- ADR 0023: Sperrliste gelöschter Medien. Ein Eintrag verhindert Re-Import
-- und Re-Scan (hash-basiert); Entsperren = Zeile löschen (Admin-Konsole).
CREATE TABLE IF NOT EXISTS blocked_hashes (
    file_hash  TEXT PRIMARY KEY NOT NULL,   -- SHA-256, wie items.file_hash
    reason     TEXT,                        -- z. B. 'aus der GUI gelöscht'
    blocked_at TEXT NOT NULL                -- ISO-8601 UTC
);
