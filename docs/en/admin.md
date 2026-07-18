# Admin console (in the web GUI)

> What is this? A **single dashboard** (button top right → quick menu →
> admin console) with everything needed for administration — no terminal
> and no page switching. The regions sit as tiles in a grid across the full
> screen width: on top the overview strip (key figures **and** activity),
> below it three columns (Sources & import | Maintenance, Issues |
> Configuration). On narrow windows the tiles stack; the "Jump to …" header
> then scrolls to the desired region (ADR 0029, 0034).

## Regions

1. **Overview** — split in two (ADR 0034): on the left the collection's
   key figures (items total; with a configured media library also
   **"library X GB / total indexed Y GB"** — what physically sits under
   the collection root vs. everything indexed (ADR 0041, I2) —, how many
   carry metadata, how many are interpreted, thumbnail cache, DB size
   (+WAL), orphaned locations, open issues; plus the `ffprobe`/`ffmpeg`
   status and the active layer-2 parsers), on the right the
   **Activity**: live progress of the running task (import/scan/VACUUM …)
   with counters in the same look. The numbers come from the **same
   source** as the gallery overview (ADR 0029).
2. **Sources & import** — the watch folders, ONE import form (once now /
   watch permanently) and "catalog without copying" (scanning in place) —
   see below.
3. **Maintenance** — small buttons, grouped by functional area (see
   below).
4. **Issues** — a one-line summary ("⚠ N open issues · M blocklist
   entries"). **View & clean up …** opens an overlay, **grouped by error
   kind** with honest counters: per kind the most recent entries plus
   "acknowledge all N of this kind"; the all-button names the true total
   ("Acknowledge all 2013") — even thousands of errors (a drive scan)
   stay manageable (ADR 0034, block N). Below it the blocklist: rejected
   media (ADR 0041) with their remembered location; unblocking allows
   re-import — the file itself was never touched when rejecting.
5. **Configuration** — edit `config.toml` from the GUI.

## Read-only mode and library management (default: hands off)

Out of the box the Feral Media Library (fml) runs in **read-only mode**:
it only catalogs and curates — **files are never copied, moved or
deleted** (the hands-off guarantee, ADR 0041). Locked are all
file-writing paths: the copy/move import (also as a watch folder) and
"Move rejected out". Still possible are `catalog`, rejecting and all
curation. A badge "👁 Read-only mode" in the top bar shows the state;
locked places explain it honestly ("Disabled in read-only mode — enable
library management in the configuration").

To build a media library, consciously enable **library management** once
in the configuration (`[library] verwaltung = true` — also as a checkbox
in Admin → Configuration; takes effect immediately, no restart). Existing
configs with a `library.root` set, or with copy/move watch folders, count
as deliberately set up: there the switch is automatically on as long as
it is not explicitly `false`.

## Adding folders — ONE form for everything

The "Sources & import" region has **one** ingest form: path (type it, or
📁 folder picker with click-through navigation and file counts per
folder) + **mode** + **frequency** ("once now" / "watch permanently").
The three modes (ADR 0031), with the same meaning everywhere:

- **copy (original stays)** — copy into the media library; the source is
  **never** touched. Safe for third-party output directories.
- **move (empty the folder)** — successes are deleted from the source
  after import; duplicates/errors/unknown formats stay behind in visible
  outcome folders (for review). Always with a safety prompt.
- **catalog only (in place)** — records the media where they are; neither
  copies nor moves. Needs no media library — the developer-friendly
  "just add to the data" option.

"Once now" processes the folder immediately, once; "watch permanently"
turns it into a **watch folder** in the list above.

## Watch folders — the purpose

Every watch folder (list at the top of the region, ADR 0030) is monitored
continuously; new files are imported by themselves after a quiet period
(copied into the `YYYY/MM/DD` structure, with duplicate check and hash
verification). On each card the mode can be changed later (again with a
prompt); ✕ removes the folder from monitoring (deletes no files). The
**mode** per folder:

- **copy** — for **standing watchers** on the output folders of your
  ComfyUI/tool installations: new media are continuously copied into the
  media library, the originals stay **untouched** in place (ADR 0031 —
  nothing gets sorted away or moved).
- **move** — as an **archive cleanup tool**: tip hundreds of legacy
  folders into it one after another; successfully imported files are
  **deleted** from the source (the content is already a copy from
  backups), the folder ends up empty. Only duplicates/errors/unknown/
  blocked files stay behind. Switching to "move" requires explicit
  confirmation and is only active with a media library set
  (`[library] root`). Additionally per folder: **"delete empty folders"**
  (ADR 0033) — after each run, source subfolders that have become empty
  are removed (date-folder trees disappear along with their media).
  Folders containing only system files (.DS_Store, Thumbs.db & co.)
  count as empty; the source root and the outcome folders
  (`_importiert` …) always remain. Default: off — you keep subfolders
  e.g. when ComfyUI renders into fixed subfolders.
- **catalog** — records new files in place, without copying or moving
  (in-place watcher, ADR 0031).

Changes take effect immediately (config is written, watchers are set up
anew); at app start all configured, existing folders are watched
automatically. Fine-tuning (quiet time/poll interval per folder) lives as
`[[watch]]` entries in `config.toml`.

**Restarts are cheap** (ADR 0042): every watcher remembers size +
modification time of cataloged files in the database and on the next
start skips everything unchanged without reading its content — even huge
watched collections are usable again right after a server restart. Only
new or changed files run through the pipeline. If you distrust the stat
comparison in a doubtful case: **"Re-scan all locations"** (Maintenance)
still checks every file's content by hash. The very first round after the
update is slow one single time (the memory fills up during the first
pass).

> This resolves the old duplications: there used to be a single hotfolder
> **and** a separate in-place watcher (ADR 0030 revises ADR 0025) — and
> the interface showed "watched sources" and "fixed scan locations" as
> competing folder lists side by side (Feral Strawberry, 2026-07-09: "nobody
> understands this"). Now: **ONE** folder concept, the watch folders. The
> former "fixed scan locations" (`[[scan.locations]]`) are gone without
> replacement; navigation happens everywhere in the 📁 folder dialog,
> which always starts at the neutral entry points project folder / home /
> drives and shows the file count per folder. The former "scanning" is
> the mode "catalog only" in the ingest form.

## Maintenance actions (by functional area)

All actions run through the internal queue (only ever one writer);
progress and result appear under **Activity**.

**Raw files**
- **Re-scan all locations** — re-read all known, still existing locations
  (idempotent). Useful after installing ffmpeg or when files might have
  changed.
- **Clean up orphaned locations** — remove path entries whose file no
  longer exists. **Items and metadata stay**; media files are never
  touched. The button first asks **where**: "everywhere" or "only under
  folder …" (ADR 0033). Careful with "everywhere" while an external
  drive/NAS is unmounted — its locations would look orphaned. (Rarely
  needed since ADR 0033: move imports clean up the location row of a
  moved source automatically.)
- **Move rejected out …** — the **only** way besides import in which fml
  moves files (ADR 0041). Opens a dialog with honest numbers: how many
  rejected files (blocklist with remembered paths) still sit **inside
  the media library**, how many GB, plus sample paths. Choose a target
  folder (must be outside the library) → confirm in two steps → the
  files move into a date structure `YYYY/MM/DD/` under the target
  (collisions get `__2` suffixes, as in the import). Safeties: before
  anything is touched, the **hash is verified** — if the file is missing
  or was replaced by hand, that is only reported and nothing is touched.
  Every file (including skipped ones) is recorded in the import log; the
  blocklist remembers the new location. External (indexed-only)
  locations are never candidates. After that it is the file manager's
  call — final deletion deliberately happens outside fml.
- **Import rules against the collection** — applies the configured import
  rules (minimum/maximum size, excluded formats — see the
  [import docs](import.md) and ADR 0046) retroactively to the catalog:
  first an honest preview (how many items, broken down by reason), then
  after clicking "reject now" the bulk rejection via the blocklist. Files
  stay untouched; unblocking makes individual items importable again.
  Legacy collections whose RAW files (ARW/NEF/DNG/CR2) are still
  cataloged as TIFF are still hit by the format exclusion (file extension
  match) — a re-scan is not needed for that, but does fix the container
  labels permanently. Common spellings such as `tif` or `jpg` are mapped
  to the internal names (`tiff`, `jpeg`).

**Thumbnails**
- **Generate thumbnails** — create missing ones and **retry** failed ones
  (important after installing ffmpeg); permanent failures appear with
  their reason under Issues (kind `thumbnail`). This button is the ONLY
  path that retries: the automatic runs after import/watch only create
  missing ones and leave known failures and acknowledged issues alone —
  acknowledged stays acknowledged, across restarts and config saves.
- **Clear cache** — delete all thumbnails including fail markers; they
  regenerate on viewing.

**Database**
- **Integrity check** — `PRAGMA integrity_check` + compact the WAL.
- **VACUUM** — compact the database (after large delete/rebuild
  operations).

**Re-evaluating existing data** (all retroactive, no file access)
- **Re-interpret** — run the layer-2 parsers retroactively over the whole
  collection. After new/improved parsers.
- **Backfill creation dates** — fill in missing capture/creation dates
  (`media_date`) from metadata/file.
- **Rebuild search index** — regenerate the FTS5 full-text index from
  scratch.

## First start (fresh installation)

Without a `config.toml`, the folder browser shows the **project/working
folder** as its first entry point (instead of a void) — from there you can
click through. **No** media folders are created automatically. For real
operation, set a media library and sources in the configuration.

## Editing the configuration

Media library (import target), **library management** (the read-only-mode
switch, see above), oldest plausible date, thumbnail size/processes,
interface options and the **instance** can be edited directly; **Save**
writes `config.toml`. (Watch folders are **not** managed here but
directly in "Sources & import" — they land as `[[watch]]` entries in the
same file. There are deliberately no folder lists in the configuration
anymore.)

**Instance** (useful when several fml instances run in parallel — per
instance its own config file and its own database; guide and sub-gallery
use case: [instanzen.md](instanzen.md)): a **name** appears as a badge in
the top bar and in the tab title, an own **accent color** tints the
interface and puts a colored dot into the favicon — so two tabs are
distinguishable at a glance. The **port** determines where this instance
runs (empty = 8765); at startup `--port` wins over `$PORT` over the
config. `start.bat` automatically opens the browser on the port actually
used, as soon as the server is reachable.

- Media library, library management, instance name and accent color take
  effect **immediately**.
- Port, thumbnail size and DB path take effect **after restarting** the
  server.
- **Careful:** comments in a hand-maintained `config.toml` do not survive
  saving from the GUI. A backup `config.toml.bak` is created
  automatically beforehand; the commented reference is
  [`config.example.toml`](../../config.example.toml).
