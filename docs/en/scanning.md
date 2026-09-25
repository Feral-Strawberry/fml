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
Scan finished for: /media/ai-bilder
  files seen         : 12877
  of which media     : 12450
    newly added      : 12450
    already known    : 0
    with metadata    : 9980
    interpreted      : 8100
    extractor pending: 120
  skipped (no container)   : 427
  filtered (import rules)  : 0
  blocked (block list)     : 0
  with warnings      : 14
  failed             : 0
```

(Console output is always English, like the server log; the web GUI shows
the same numbers in the interface language.)

## What the numbers mean

| Line | Meaning |
|-------|-----------|
| **files seen** | all files in the folder tree |
| **of which media** | recognized as a known container (PNG, JPEG, WEBP, …) |
| **newly added** / **already known** | hash was new or already in the DB (duplicate or re-scan) |
| **with metadata** | embedded metadata was found |
| **interpreted** | [layer 2](interpretation.md) recognized structured fields (prompt, seed, model, …) |
| **extractor pending** | recognized, but the extractor is not built yet (currently PDF and camera RAW such as ARW, NEF, CR2, DNG). The file is still **cataloged** and gets its metadata automatically once the extractor exists |
| **skipped (no container)** | no known container (e.g. `.txt`, macOS `._` files) |
| **filtered** / **blocked** | left out by the import rules or the block list |
| **failed** | file unreadable etc. — listed at the end of the run |

## Properties

- **Repeatable (idempotent):** scanning the same folder again creates no
  duplicates; already known files are only counted as "known".
- **Does not abort:** a broken file does not end the scan — it lands under
  "failed".
- **Duplicates fall out automatically:** bit-identical files in different
  places are kept as **one** item with multiple locations.

## Diagnostics: video codecs in the catalog

Which codec is inside my videos — and why does the browser play some of
them with audio only? One command answers that for the whole catalog,
without searching for a file and without a re-scan:

```bash
python -m feral.diagnose video-codecs --db ./feral.sqlite
```

It walks the locations of all videos, calls `ffprobe` on the file header
only (under a second even for 4 GB) and prints a table: codec · profile ·
pixel format · browser (`ok` / `eingeschränkt` = limited / `NEIN` = no) ·
number of files · example path. Nothing is written.

- `--min-size 1G` — only videos from this size (`500M`, `2G`, …).
- `--from-db` — reads the layer-2 fields `video_codec`/`video_profile`/
  `pixel_format` instead of calling ffprobe (fractions of a second;
  requires a re-scan after the extractor extension — videos without the
  field show as "unbekannt — Re-Scan nötig", i.e. unknown, re-scan needed).
- `--quiet` — no progress output.

Example:

```
Codec   Profile  Pixel format  Browser  Files  Example
------  -------  ------------  -------  -----  --------
prores  HQ       yuv422p10le   NO       212    /media/2026/07/12/topaz_4k.mov
h264    High     yuv420p       ok       1830   /media/2026/07/12/clip.mp4
hevc    Main 10  yuv420p10le   limited  4      /media/2026/05/01/wan.mp4

videos in the catalog: 2046 · probed: 2046
```

The same assessment lands as an issue of kind `playback` under Admin →
Issues when cataloging/importing; in the search field `codec: prores`
finds the files ([interpretation.md](interpretation.md#video-codec-and-playability)).
