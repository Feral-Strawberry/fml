-- ADR 0022: manuell gesetztes Modell (Aufräumen metadatenloser Bestände,
-- z. B. Feral Strawberrys Midjourney-Screenshot-Crops von 2022). Teil der manuellen
-- Schicht (ADR 0005/0017) — überschreibt das interpretierte Modell in
-- Zählern und Filtern; NULL = nicht gesetzt.
ALTER TABLE annotations ADD COLUMN model TEXT;
