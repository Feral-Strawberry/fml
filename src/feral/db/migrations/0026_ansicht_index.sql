-- ADR 0085 (Audio A2, Issue #159): Grundbereich der Ansicht als Bedingung
-- auf items.media_kind (Galerie: kein Audio, Audioansicht: nur Audio).
-- media_kind als HINTERSTE Spalte der Plain-Sortier-Indizes: die Sortierung
-- deckt der Index weiter exakt (ADR 0039), und die Bedingung prüft SQLite
-- im Index statt je übersprungener Zeile in der Tabelle. 250k-Bench: tiefe
-- Galerie-Seite 120-170 ms ohne, ~10 ms mit (ungefiltert ~7 ms).
DROP INDEX IF EXISTS idx_items_first_seen;
CREATE INDEX idx_items_first_seen ON items(first_seen_at DESC, file_hash, media_kind);
DROP INDEX IF EXISTS idx_items_size;
CREATE INDEX idx_items_size ON items(file_size DESC, file_hash, media_kind);
DROP INDEX IF EXISTS idx_items_container;
CREATE INDEX idx_items_container ON items(container, first_seen_at DESC, file_hash, media_kind);
DROP INDEX IF EXISTS idx_items_media_date;
CREATE INDEX idx_items_media_date ON items(media_date DESC, file_hash, media_kind);
DROP INDEX IF EXISTS idx_items_duration;
CREATE INDEX idx_items_duration ON items(duration DESC, file_hash, media_kind);
