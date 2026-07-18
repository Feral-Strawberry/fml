-- ADR 0042: Stat-Gedächtnis pro Fundort — Watcher-Neustart ohne Voll-Rescan.
-- Scan und Import schreiben Größe + mtime des Fundorts mit; der Watcher
-- überspringt Pfade mit unverändertem Stat, ohne ein Byte Inhalt zu lesen.
-- Alt-Bestand bleibt NULL und füllt sich beim ersten Durchlauf (Backfill).
ALTER TABLE file_locations ADD COLUMN file_size INTEGER;
ALTER TABLE file_locations ADD COLUMN mtime_ns INTEGER;
