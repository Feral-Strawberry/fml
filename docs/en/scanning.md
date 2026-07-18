# Scanning folders

> What does it do? It walks a folder recursively and ingests every media
> file into the library: detect → hash → [extract metadata](extraction.md) →
> [interpret](interpretation.md) → [store](persistence.md). Afterwards the
> collection is searchable — including targeted searches by prompt, model or
> seed.

> **Important:** the scanner only **reads** and **copies/moves nothing**. It
> catalogs the files where they are. (The later import, which copies into a
> date-based structure, is a separate step.)

## Invocation

```bash
python -m feral.scan /path/to/folder --db ./feral.sqlite
```

- `root` (required): the folder to search recursively.
- `--db` (optional): path to the SQLite file (default `./feral.sqlite`).
  Created if needed.
- `--quiet` (optional): no intermediate progress output.

## Example output

```
Scan abgeschlossen für: /media/ai-bilder
  Dateien betrachtet : 12877
  davon Medien       : 12450
    neu aufgenommen  : 12450
    bereits bekannt  : 0
    mit Metadaten    : 9980
    interpretiert    : 8100
    Extraktor folgt  : 120
  übersprungen (kein Container): 427
  mit Warnungen      : 14
  fehlgeschlagen     : 0
```

(The CLI report is developer output and stays German; the web GUI shows
the same numbers in the interface language.)

## What the numbers mean

| Line | Meaning |
|-------|-----------|
| **Dateien betrachtet** (files considered) | all files in the folder tree |
| **davon Medien** (of which media) | recognized as a known container (PNG, JPEG, WEBP, …) |
| **neu aufgenommen** / **bereits bekannt** (newly ingested / already known) | hash was new or already in the DB (duplicate or re-scan) |
| **mit Metadaten** (with metadata) | embedded metadata was found |
| **interpretiert** (interpreted) | [layer 2](interpretation.md) recognized structured fields (prompt, seed, model, …) |
| **Extraktor folgt** (extractor to follow) | recognized, but the extractor is not built yet (currently PSD and PDF). The file is still **cataloged** and gets its metadata automatically once the extractor exists |
| **übersprungen** (skipped) | no known container (e.g. `.txt`, macOS `._` files) |
| **fehlgeschlagen** (failed) | file unreadable etc. — listed at the end of the run |

## Properties

- **Repeatable (idempotent):** scanning the same folder again creates no
  duplicates; already known files are only counted as "known".
- **Does not abort:** a broken file does not end the scan — it lands under
  "failed".
- **Duplicates fall out automatically:** bit-identical files in different
  places are kept as **one** item with multiple locations.
