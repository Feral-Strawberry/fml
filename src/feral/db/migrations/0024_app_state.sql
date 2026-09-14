-- Issue #118 (ADR-0077-Nachtrag): kleine Schlüssel-Wert-Ablage für
-- Anwendungszustand, der einen Neustart überleben soll, aber kein eigenes
-- Schema verdient. Erster Nutzer: der gemerkte Stand der teuren
-- Admin-Kennzahlen (verwaiste Fundorte, Thumbnail-Cache) als JSON mit
-- Herkunftsstempel (Rechner + Cache-Pfad). Reine Anzeige-Daten: jederzeit
-- per Klick reproduzierbar, nie eine zweite Wahrheit.
CREATE TABLE IF NOT EXISTS app_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,          -- JSON
    updated_at TEXT NOT NULL           -- ISO-8601 UTC
);
