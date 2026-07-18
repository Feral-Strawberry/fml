-- ADR 0049: Fundort-Eindeutigkeit — ein Pfad gehört genau einem Hash.
-- Der Katalogisier-Cleanup in store_extraction löscht fremde Hash-Zeilen
-- desselben Pfads; ohne Pfad-Index wäre das bei 250k+ Fundorten ein
-- Tabellenscan pro katalogisierter Datei.
CREATE INDEX IF NOT EXISTS idx_file_locations_path ON file_locations(path);
