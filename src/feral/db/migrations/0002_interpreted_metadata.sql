-- Migration 0002: Schicht-2-Tabelle (ADR 0011).
-- interpreted_metadata: von Parsern aus den Roh-Blobs gezogene, strukturierte
-- Felder. Schlüssel-Wert-Form, damit neue Parser/Felder KEINE Schema-Änderung
-- brauchen — Schicht 2 darf unvollständig sein und wächst iterativ (ADR 0004).
-- Herkunft bleibt klar: alles hier ist "aus Datei extrahiert", nie manuell
-- gesetzt (ADR 0005; manuelle Anreicherung bekommt später eine eigene Tabelle).

CREATE TABLE IF NOT EXISTS interpreted_metadata (
    id             INTEGER PRIMARY KEY,
    file_hash      TEXT NOT NULL REFERENCES items(file_hash) ON DELETE CASCADE,
    parser         TEXT NOT NULL,        -- Parser-Name aus der Registry: 'a1111','comfyui',...
    parser_version INTEGER NOT NULL,     -- Version des Parsers, der den Eintrag erzeugt hat
    ordinal        INTEGER NOT NULL,     -- Reihenfolge innerhalb eines Parser-Ergebnisses
    field          TEXT NOT NULL,        -- kanonischer Feldname: 'prompt','seed','model',...
    value_text     TEXT NOT NULL,        -- Wert als Text (durchsuchbar)
    interpreted_at TEXT NOT NULL,        -- ISO-8601 UTC
    UNIQUE(file_hash, parser, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_interpreted_hash  ON interpreted_metadata(file_hash);
CREATE INDEX IF NOT EXISTS idx_interpreted_field ON interpreted_metadata(field);
