-- ADR 0041: Die Sperrliste merkt sich beim Ablehnen die letzten bekannten
-- Fundort-Pfade (JSON-Array) — Basis für den Rausverschiebe-Dialog (I3).
-- Ablehnen selbst fasst keine Mediendatei an; Alt-Einträge bleiben NULL.
ALTER TABLE blocked_hashes ADD COLUMN last_paths TEXT;
