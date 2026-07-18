-- Migration 0006: Import-Log (Stufe 4.1, ADR 0019).
-- Jede Quelldatei eines Import-Laufs bekommt genau eine Zeile: welcher der
-- vier Ausgänge, wohin kopiert, welche Datumsquelle. Das ist Feral Strawberrys Report
-- über zehntausende gefilterte Dubletten — und die Spur für Nachbehandlung
-- (z. B. Umdatieren von 'unplausibel'-Einträgen).

CREATE TABLE IF NOT EXISTS import_log (
    id          INTEGER PRIMARY KEY,
    imported_at TEXT NOT NULL,               -- ISO-8601 UTC (Lauf-Zeitpunkt je Datei)
    source_path TEXT NOT NULL,
    action      TEXT NOT NULL,               -- importiert|dublette|repariert|unbekanntes_format|fehler
    detail      TEXT,                        -- z. B. Fehlermeldung oder Bestandspfad der Dublette
    target_path TEXT,                        -- NULL außer bei importiert/repariert
    file_hash   TEXT,                        -- NULL, wenn nicht mehr hashbar
    date_source TEXT                         -- metadaten|dateisystem|unplausibel (nur importiert/repariert)
);

CREATE INDEX IF NOT EXISTS idx_import_log_action ON import_log(action, imported_at);
