-- Migration 0007: Medien-Eckwerte (Feral Strawberry, 2026-07-08).
-- Pixelmaße und fps direkt am Item — für Anzeige (Grid/Panel/Loupe) und
-- Filter (width>=1920 …). Befüllt beim Scan/Import; Bestände holen die Werte
-- per „Re-Scan aller Fundorte" nach (Rescan-Prinzip, BAUPLAN Arbeitsweise 7).

ALTER TABLE items ADD COLUMN width INTEGER;
ALTER TABLE items ADD COLUMN height INTEGER;
ALTER TABLE items ADD COLUMN fps REAL;
