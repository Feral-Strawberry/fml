-- ADR 0042 (Ergänzung): Stat-Gedächtnis auch für Nicht-Katalogisiertes.
-- Gescheiterte (Lesefehler), unbekannte Container und gesperrte/abgelehnte
-- Dateien bekamen keine file_locations-Zeile — jeder Watcher-Neustart und
-- jedes Config-Speichern (setzt alle Watcher neu auf) las sie darum neu
-- ein, scheiterte neu und machte quittierte Scan-Probleme wieder auf.
-- Der Watcher lädt dieses Gedächtnis zusammen mit file_locations und
-- überspringt unveränderte Pfade, ohne ein Byte Inhalt zu lesen.
-- Neu probiert wird bewusst nur bei geänderter Datei, per „Re-Scan aller
-- Fundorte" oder manuellem Ordner-Scan (beide bleiben voll).
CREATE TABLE scan_memory (
    path         TEXT PRIMARY KEY,
    file_size    INTEGER NOT NULL,
    mtime_ns     INTEGER NOT NULL,
    outcome      TEXT NOT NULL,       -- 'fehlgeschlagen' | 'unbekannt' | 'gesperrt'
    file_hash    TEXT,                -- nur bei 'gesperrt' bekannt; Entsperren räumt darüber auf
    last_seen_at TEXT NOT NULL
);

CREATE INDEX idx_scan_memory_hash
    ON scan_memory (file_hash) WHERE file_hash IS NOT NULL;
