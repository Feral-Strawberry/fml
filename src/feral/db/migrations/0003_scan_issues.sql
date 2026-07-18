-- Migration 0003: Scan-Probleme sichtbar machen (Stufe 2A, ADR 0014).
-- Bisher lebten Warnungen/Fehler nur im flüchtigen Scan-Report. Jetzt werden sie
-- pro Datei festgehalten, damit der Admin-Bereich sie anzeigen kann und nichts
-- stillschweigend untergeht. Ein sauberer Re-Scan derselben Datei quittiert
-- ihre offenen Einträge automatisch.

CREATE TABLE IF NOT EXISTS scan_issues (
    id            INTEGER PRIMARY KEY,
    path          TEXT NOT NULL,               -- betroffene Datei
    kind          TEXT NOT NULL,               -- 'failed' (nicht aufgenommen) | 'warning'
    message       TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,               -- ISO-8601 UTC
    last_seen_at  TEXT NOT NULL,
    resolved      INTEGER NOT NULL DEFAULT 0,  -- 0 = offen, 1 = quittiert/behoben
    UNIQUE(path, kind, message)                -- Re-Scan erzeugt keine Duplikate
);

CREATE INDEX IF NOT EXISTS idx_scan_issues_open ON scan_issues(resolved, last_seen_at);
