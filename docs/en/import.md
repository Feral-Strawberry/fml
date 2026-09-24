# Import: sorting backups into the collection

> What is this? The way your scattered source folders (old backups, ComfyUI
> outputs, downloads) become **one** unambiguous, date-sorted collection.
> Duplicates are sorted out automatically along the way — visibly, not
> silently. (Rules: ADR 0006/0019.)

## Prerequisite

Copying and moving imports require two things (the "catalog" mode needs
neither): **library management** enabled, and the collection root — both in
the GUI under **Admin → Configuration** (checkbox "Library management",
field "Media library (import target)"; takes effect immediately, the
oldest plausible date lives there too). Alternatively directly in
`config.toml`:

```toml
[library]
root = "/path/to/collection"
```

## Flow

**Admin → Sources & import:** pick a folder, pick a mode,
frequency "once now", **Add**. The library side is the same in every mode:
new content is **copied** to `collection/YYYY/MM/DD/`, the copy is
verified against the source by hash and cataloged immediately (no extra
scan needed). The mode determines only what happens to the **source**
(ADR 0031):

- **"copy"** — the source is **never touched**; the import is purely
  reading. The per-file result (new/duplicate/error/…) is in the import
  log (Admin → Activity); nothing changes in the source folder itself.
  The right mode for third-party folders and tool outputs.
- **"move"** (with explicit confirmation) — successfully imported files
  are **deleted** from the source after verification; the folder empties
  itself. Only follow-up cases stay visibly behind. The outcome folder
  names are fixed identifiers, like the config values (`kopieren`,
  `verschieben`, `katalogisieren`): they stay the same (German) in every
  language so fml recognizes them in every installation; the table gives
  the meaning.

  | Outcome | Meaning |
  | --- | --- |
  | `_dubletten/` | content is already in the collection (bit-identical) — **and** the collection copy was freshly re-hashed |
  | `_unbekanntes-format/` | container not recognized — your stumbling-block folder for missing formats (audio files land here while the [audio module](audio.md) is off) |
  | `_fehler/` | read error, or the copy could not be verified |
  | `_gesperrt/` | hash is on the blocklist (rejected in the library) — will not be imported again (ADR 0023/0041) |
  | `_ausgefiltert/` | sorted out by the **import rules** (too small / too large / excluded format / no plausible date, see below) — after changing the rules, just drop them in again |

  So the only thing ever deleted is what verifiably sits bit-identical in
  the collection with its catalog entry stored — everything else stays
  behind as a visible remainder for review.
- **"catalog"** — neither copy nor move: records media **in place**. The
  only mode that needs no media library — and the only one allowed in
  read-only mode (the default).

Large runs execute as a **pipeline**: several worker threads
detect and hash ahead (the health check of collection copies for
duplicates runs in parallel the same way), while copying and cataloging
stays strictly sequential, stored in batches. Duplicate-heavy second
deliveries — the most common case — become several times faster this way.

## Import rules: keeping small fry and half-supported formats out

Under **Admin → Configuration → Media library** you can set rules that
apply to **every** ingestion path — import (copy/move), catalog and watch
folders:

- **Minimum size (shortest side)**, e.g. `240` px: filters embedded
  archive thumbnails and other small fry with no value.
- **Maximum size (longest side)**, e.g. `8000` px: filters huge contact
  sheets/thumbnail overviews (tens of thousands of pixels wide).
- **Exclude formats/extensions**, e.g. `psd, arw, lang`: don't even
  ingest half-supported formats or foreign files. An entry matches the
  detected format **or** the file extension: `lang` keeps programs'
  language files out, even if their content happens to look like a known
  format. Camera RAW files (Sony ARW, Nikon NEF, Canon CR2, DNG) are
  recognized specifically instead of slipping through as TIFF.
- **Earliest plausible date** (`[import] min_date`, default 2015-01-01):
  a file whose creation date is plausible neither from its metadata nor
  from its file timestamp (before `min_date` or in the future, e.g.
  1970-01-01) is **not ingested** — it counts as a rule hit just like an
  image that is too small. This rule is always active; lower `min_date`
  if you want to keep old material.

Both dimension rules apply only to **images with known dimensions** —
never to videos, and nothing is guessed without dimensions. During import
(move mode), hits land visibly in `_ausgefiltert/` (reason in the import
log); during cataloging they are simply skipped and counted in the
report. Nothing disappears silently, and in copy mode the source is, as
always, never touched.

For collections ingested **before** the rules existed, there is
**Admin → Maintenance → "Import rules against the collection"**: it first
shows how many items the current rules would hit (broken down by reason,
including "without a plausible date"), and on confirmation rejects them
collectively — the files stay put, only the catalog entries disappear
(reversible via the blocklist). Background: ADR 0046 and ADR 0075.

## Watch folders (automatic import)

With frequency **"watch permanently"** the folder becomes a **watch
folder** (a `[[watch]]` entry in `config.toml`, ADR 0030 — any number of
them, started automatically with the app): a file counts as finished when
its size and timestamp stay stable for `quiet_seconds` (half-written
copies are never touched) — then it runs through exactly the same import
as above, with the same mode semantics: "copy" only reads, "move" empties
the folder (follow-up cases stay behind; "delete empty folders"
optionally removes subfolders that have become empty, ADR 0033),
"catalog" records in place. Files already cataloged and unchanged are
skipped by the watcher based on size and timestamp without reading them
(ADR 0042) — across restarts too. Usage patterns and per-mode details:
[admin.md](admin.md). (Old `[hotfolder]` configs are automatically
migrated to a watch folder at startup.)

## Date

Files are sorted by **creation date**: the embedded date from the metadata
(if present), otherwise the older plausible filesystem timestamp. If there
is no plausible date (before `min_date`, e.g. 1970-01-01, or in the
future), the date rule above applies: the file is **not imported** and
lands visibly in `_ausgefiltert/` — instead of in a wrong date folder or in
the catalog with an empty date. The lower bound is configurable:
`[import] min_date = "2015-01-01"`. A `collection/_unbekanntes-datum/`
folder from earlier versions stays as it is: you can reject its entries
via "Import rules against the collection" (files stay put) or date them
honestly with a lowered `min_date` and "Backfill creation dates".

## Report

Every run ends with a summary line ("4 new · 8,311 duplicates · …", in
the admin overview's Activity). Every single file is recorded in the DB
table `import_log` (time, source, outcome, target, hash, date source).

## Safety

- A source only counts as a duplicate if the existing collection file is
  **healthy** (freshly re-hashed). If it is broken or gone, the file is
  imported anew (`repariert` in the log) — so deleting the `_dubletten/`
  folders later can never destroy a single good copy.
- Name collisions (different files, same name, same day) get a suffix:
  `name__2.ext`.
- A second run over the same folder is harmless: the outcome folders are
  not imported again.
