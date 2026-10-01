-- ADR 0097 (#222): Finder-Tags (macOS) werden normale fml-Tags.
-- tags.color: Finder-Farbindex 1–7 (1 Grau, 2 Grün, 3 Lila, 4 Blau, 5 Gelb,
-- 6 Rot, 7 Orange); NULL = keine Farbe. Die Farbe gehört dem Tag (wie im
-- Finder), der zuletzt gelesene Finder-Farbwert gewinnt.
-- item_tags.source: Herkunft der Zuordnung — NULL = manuell in fml,
-- 'finder' = beim Import/Scan aus dem Finder übernommen (ADR 0005: Herkunft
-- bleibt unterscheidbar). Eine manuelle Zuordnung wird nie überschrieben.
ALTER TABLE tags ADD COLUMN color INTEGER CHECK (color BETWEEN 1 AND 7);
ALTER TABLE item_tags ADD COLUMN source TEXT;
