# Persistenz / Datenbank

> Was tut sie? Sie speichert das Ergebnis der [Extraktion](extraction.md) in eine
> SQLite-Datei und macht es durchsuchbar — z. B. „alle Bilder, deren Prompt `Seed:
> 777` enthält". Die Datenbank liegt **außerhalb** des Repos (in `.gitignore`).

## Verwendung

```python
from feral.extract import extract
from feral.hashing import hash_file
from feral.db import connect, store_extraction

conn = connect("./feral.sqlite")        # legt die DB an und migriert sie bei Bedarf

path = "/media/2026/bild.png"
store_extraction(
    conn,
    file_hash=hash_file(path),
    file_size=__import__("os").path.getsize(path),
    path=path,
    extraction=extract(path),
)
```

## Was gespeichert wird

Alle Tabellen mit Spalten, Schlüsseln und Indexen samt ER-Diagramm stehen
in der [Schema-Referenz](schema.md) (aus dem echten Schema erzeugt). Kurz:
`items` ist der Hub (eine Zeile je Datei-Hash), daran hängen Fundorte,
Roh-Metadaten (Schicht 1), interpretierte Felder (Schicht 2), die manuelle
Schicht (Bewertung, Tags, Notizen, Datum von Hand, Zeitkommentare,
Musik-Angaben von Hand, Cover, gespeicherte Suchen samt eigener
Reihenfolge), das Ranking-Modul,
der Volltextindex und die Betriebstabellen (Sperrliste, Import-Log,
Watch-Gedächtnis, Probleme, gemerkte Kennzahlen, Warteschlange).

Zugriff auf die manuelle Schicht läuft über `feral/db/manual.py`
(`set_rating`, `set_notes`, `set_model`, `add_tag`, `remove_tag`,
`set_media_date`, `add_comment`, `set_cover`, `annotations_for`,
`list_tags`) — idempotent, `set_rating(0)` löscht die Bewertung. Tags
aus dem Finder (macOS) tragen ihre Herkunft; eine Zuordnung von Hand
wird davon nie überschrieben. Die Musik-Angaben von Hand liegen in
`feral/db/manual_fields.py` (`set_fields`, `fields_of`, `state`,
`overlay`): `overlay` legt sie beim Schreiben der interpretierten Felder
über die Werte aus den Tags, sodass jede Abfrage den geltenden Wert sieht.

## Wichtige Eigenschaften

- **Idempotenter Re-Scan:** Dieselbe Datei nochmal einlesen führt zum selben
  Zustand — keine Duplikate. `first_seen_at` bleibt, `updated_at` wandert mit.
- **Nichts geht verloren:** `raw_metadata.value_raw` hält die exakten Bytes; auch
  wenn ein Text mal nicht sauber dekodierbar ist, bleibt der Roh-Inhalt erhalten.
- **Re-Interpretation ohne Datei-Zugriff:** Neue Schicht-2-Parser laufen direkt
  über die gespeicherten Roh-Daten (`python -m feral.interpret`).
- **Automatische Migration:** Eine ältere DB wird beim Öffnen auf den aktuellen
  Schema-Stand gebracht (nummerierte Migrationsdateien).

## Beispiel-Queries

```sql
-- Alle Items, deren Roh-Metadaten "Seed: 777" enthalten:
SELECT DISTINCT file_hash FROM raw_metadata WHERE value_text LIKE '%Seed: 777%';

-- Alle mit flux-Modell generierten Items (Schicht 2):
SELECT DISTINCT file_hash FROM interpreted_metadata
 WHERE field = 'model' AND value_text LIKE '%flux%';
```

## Hinweise zum Betrieb

- Die DB-Datei **nie auf ein Netzlaufwerk** legen (SMB/NFS) — SQLite-Locking bricht
  dort. Lokal halten, sinnvollerweise neben dem Datenverzeichnis.
- Es schreibt immer nur **der Server** (der Webprozess für kurze Schreibgriffe,
  sein Arbeitsprozess für Langläufer; beide gehören zu einer Instanz). Nie zwei
  fml-Instanzen oder GUI und CLI-Scan gleichzeitig auf dieselbe Datei. Mehrere
  Leser gleichzeitig sind dank WAL kein Problem.
