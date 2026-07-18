# Persistence / database

> What does it do? It stores the result of the [extraction](extraction.md)
> in an SQLite file and makes it searchable — e.g. "all images whose prompt
> contains `Seed: 777`". The database lives **outside** the repo (in
> `.gitignore`).

## Usage

```python
from feral.extract import extract
from feral.hashing import hash_file
from feral.db import connect, store_extraction

conn = connect("./feral.sqlite")        # creates the DB and migrates it if needed

path = "/media/2026/image.png"
store_extraction(
    conn,
    file_hash=hash_file(path),
    file_size=__import__("os").path.getsize(path),
    path=path,
    extraction=extract(path),
)
```

## What is stored

| Table | Content |
|---------|--------|
| `items` | one row per unique file, identified by the **file hash**. With size, container, media kind, optional image-data hash and timestamps. |
| `file_locations` | where the same file (same hash) sits on disk — one file can appear at several paths. |
| `raw_metadata` | the raw metadata (layer 1): per entry the source, keyword, decoded text **and** the byte-exact raw bytes. |
| `interpreted_metadata` | the structured fields ([layer 2](interpretation.md)): per entry the parser (+ version), field name (`prompt`, `seed`, `model`, …) and value. |
| `annotations` | the **manual layer** (ADR 0017): rating (1–5, NULL = unrated) and notes — strictly separated from everything extracted. |
| `tags` / `item_tags` | your own tag vocabulary (case-insensitively unique) and the tag ↔ item assignment, each with timestamps. |
| `scan_issues` | problems collected while scanning (admin area, ADR 0014). |

Access to the manual layer goes through `feral/db/manual.py`
(`set_rating`, `set_notes`, `add_tag`, `remove_tag`, `annotations_for`,
`list_tags`) — idempotent; `set_rating(0)` clears the rating.

## Key properties

- **Idempotent re-scan:** reading the same file again leads to the same
  state — no duplicates. `first_seen_at` stays, `updated_at` moves along.
- **Nothing is lost:** `raw_metadata.value_raw` holds the exact bytes; even
  if a text does not decode cleanly, the raw content is preserved.
- **Re-interpretation without file access:** new layer-2 parsers run
  directly over the stored raw data (`python -m feral.interpret`).
- **Automatic migration:** an older DB is brought up to the current schema
  when opened (numbered migration files).

## Example queries

```sql
-- All items whose raw metadata contains "Seed: 777":
SELECT DISTINCT file_hash FROM raw_metadata WHERE value_text LIKE '%Seed: 777%';

-- All items generated with a flux model (layer 2):
SELECT DISTINCT file_hash FROM interpreted_metadata
 WHERE field = 'model' AND value_text LIKE '%flux%';
```

## Operating notes

- **Never** put the DB file on a network share (SMB/NFS) — SQLite locking
  breaks there. Keep it local, sensibly next to the data directory.
- Only **one** process ever writes (the server). Multiple simultaneous
  readers are no problem thanks to WAL.
