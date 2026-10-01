-- ADR 0093 (#223): die Warteschlange der Langläufer überlebt Neustarts.
-- Eine Zeile je laufender oder wartender Aufgabe; der Web-Prozess schreibt
-- Änderungen als Differenz (neu / weg / Reihenfolge). Beim Start wird die
-- Schlange in ``ord``-Reihenfolge wieder eingereiht. Parameter und Label
-- sind JSON (die Parameter waren schon picklebar, ADR 0067).
CREATE TABLE IF NOT EXISTS task_queue (
    id       INTEGER PRIMARY KEY,      -- Aufgaben-ID der Engine
    ord      INTEGER NOT NULL,         -- Position: 0 = läuft bzw. als Nächstes
    name     TEXT NOT NULL,            -- tasks.TASKS
    params   TEXT NOT NULL,            -- JSON
    label    TEXT NOT NULL,            -- JSON (Meldungs-Dict)
    key      TEXT NOT NULL,            -- Dubletten-Schlüssel
    priority INTEGER NOT NULL DEFAULT 0  -- 1 = Watch-Batch (Vorrang)
);
