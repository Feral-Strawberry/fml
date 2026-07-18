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

| Tabelle | Inhalt |
|---------|--------|
| `items` | eine Zeile pro einzigartiger Datei, identifiziert über den **Datei-Hash**. Mit Größe, Container, Medienart, optionalem Bilddaten-Hash und Zeitstempeln. |
| `file_locations` | wo dieselbe Datei (gleicher Hash) auf der Platte liegt — eine Datei kann an mehreren Pfaden auftauchen. |
| `raw_metadata` | die rohen Metadaten (Schicht 1): pro Eintrag Quelle, Keyword, dekodierter Text **und** byte-exakte Roh-Bytes. |
| `interpreted_metadata` | die strukturierten Felder ([Schicht 2](interpretation.md)): pro Eintrag Parser (+ Version), Feldname (`prompt`, `seed`, `model`, …) und Wert. |
| `annotations` | die **manuelle Schicht** (ADR 0017): Rating (1–5, NULL = unbewertet) und Notizen — strikt getrennt von allem Extrahierten. |
| `tags` / `item_tags` | eigenes Tag-Vokabular (case-insensitiv einmalig) und die Zuordnung Tag ↔ Item, jeweils mit Zeitstempeln. |
| `scan_issues` | beim Scannen aufgelaufene Probleme (Admin-Bereich, ADR 0014). |

Zugriff auf die manuelle Schicht läuft über `feral/db/manual.py`
(`set_rating`, `set_notes`, `add_tag`, `remove_tag`, `annotations_for`,
`list_tags`) — idempotent, `set_rating(0)` löscht die Bewertung.

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
- Es schreibt immer nur **ein** Prozess (der Server). Mehrere Leser gleichzeitig
  sind dank WAL kein Problem.
