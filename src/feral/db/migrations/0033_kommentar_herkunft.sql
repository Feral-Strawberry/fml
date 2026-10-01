-- ADR 0098 (#228): Herkunft importierter Zeitkommentare. NULL = hier
-- geschrieben; sonst die im Importdialog eingegebene Quelle (z. B. der Name
-- des anderen), angezeigt als Etikett am Kommentar (ADR 0005: Herkunft
-- bleibt sichtbar).
ALTER TABLE time_comments ADD COLUMN source TEXT;
