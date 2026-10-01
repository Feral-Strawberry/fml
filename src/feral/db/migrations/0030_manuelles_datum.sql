-- ADR 0096 (#220): manuell gesetztes Datum, Teil der manuellen Schicht
-- (ADR 0005, wie das Modell in Migration 0011). ISO-8601 mit reduzierter
-- Genauigkeit: '1997', '1997-05' oder '1997-05-12' — die Länge IST die
-- Genauigkeit. Gewinnt immer gegen Metadaten, Tag-Jahr und Dateistempel
-- und wird nach items.media_date durchgeschrieben (Sortier-/Filterindex
-- bleibt unberührt); NULL = abgeleitetes Datum gilt.
ALTER TABLE annotations ADD COLUMN media_date TEXT;
