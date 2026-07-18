-- ADR 0039: Sortierung nach Dateiname bei 250k (Feral Strawberrys Finding 2026-07-09,
-- „alles außer Hinzugefügt extrem langsam"). Expression-Index über die
-- Basename-Formel aus filters.BASENAME — MUSS byte-gleich zu ihr bleiben,
-- sonst greift der Index nicht (library._BASENAME_FL nutzt ihn für die
-- schlanke Seiten-Query; 250k-Bench: Seite 1 685 → 2 ms, tief 1719 → 112 ms;
-- Indexaufbau bei 250k: ~0,6 s).
CREATE INDEX IF NOT EXISTS idx_loc_basename
    ON file_locations(
        replace(replace(path, '\', '/'), rtrim(replace(path, '\', '/'), replace(replace(path, '\', '/'), '/', '')), '') COLLATE NOCASE,
        file_hash
    );
