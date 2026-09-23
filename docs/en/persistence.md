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

All tables with columns, keys and indexes plus an ER diagram are in the
[schema reference](schema.md) (generated from the real schema). In short:
`items` is the hub (one row per file hash); attached to it are locations,
raw metadata (layer 1), interpreted fields (layer 2), the manual layer
(rating, tags, notes, saved searches), the ranking module, the full-text
index and the operational tables (block list, import log, watch memory,
issues, remembered figures).

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
- Only **the server** ever writes (the web process for short writes, its
  worker process for long-running tasks; both belong to one instance). Never
  run two fml instances, or the GUI and a CLI scan, on the same file at the
  same time. Multiple simultaneous readers are no problem thanks to WAL.
