-- Block 4S: Modell-/Feld-Filter ohne Gedenkminute (Feral Strawberrys Windows-Runde 3).
--
-- Die Filteransichten „Nach Modell" prüften per EXISTS für JEDES Item, ob es
-- das Feld trägt — und mussten dafür jedes Mal in die Tabelle greifen (es gab
-- nur Indizes auf file_hash bzw. field allein). Bei 250k Items sind das 250k
-- zufällige Plattenzugriffe: auf kalter DB die „Gedenkminute" selbst bei einem
-- einzigen Treffer. Der Covering-Index (field, value_text, file_hash)
-- beantwortet »welche Items haben field=X mit Wert=Y« komplett aus dem Index:
-- 250k-Bench: 1 Treffer 1167 ms → <1 ms, 100k Treffer → <90 ms.
CREATE INDEX IF NOT EXISTS idx_interpreted_field_value
    ON interpreted_metadata(field, value_text, file_hash);

-- Der alte Index auf field allein ist damit ein reines Präfix des neuen —
-- weg damit, spart Platz und Schreibarbeit.
DROP INDEX IF EXISTS idx_interpreted_field;
