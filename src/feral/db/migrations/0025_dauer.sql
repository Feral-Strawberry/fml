-- ADR 0083 (Audio-Modul, Issue #158): Dauer in Sekunden für Audio UND
-- Video (modulunabhängig). Quelle: ffprobe (format.duration, sonst die
-- längste Spur); NULL = unbekannt bzw. Standbild. Bestehende Videos
-- bekommen ihre Dauer beim nächsten Re-Scan (Rescan-Prinzip).
ALTER TABLE items ADD COLUMN duration REAL;

-- Plain-Sortierung „Dauer" absteigend (ADR 0039: Index deckt ORDER BY
-- exakt) und die Vergleiche von dauer:.
CREATE INDEX IF NOT EXISTS idx_items_duration ON items(duration DESC, file_hash);
