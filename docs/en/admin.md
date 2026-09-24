# Admin (its own page under `/admin`)

> What is this? The administration area of the Feral Media Library — a
> **page of its own** under `/admin` (ADR 0074), reached via the admin
> button top right, the activity indicator or
> directly by address. The button is a real link: middle-click opens the
> admin in a second tab (watch an import while reviewing), bookmarks and
> browser back work. On the left a side navigation with **seven pages**,
> at its bottom the **activity widget** (what is running, waiting, whether
> the worker process is alive — visible on every page, click leads to the
> overview), below it instance name, schema version and port. On narrow
> windows (below 960 px) the navigation becomes an icon bar. "Back to the
> library" is an ordinary page change; the gallery then starts fresh or
> from the browser's history cache.

## Pages

1. **Overview** (`/admin/overview`) — collection, running work and system
   state, in four fixed rows:
   - **Collection:** key-figure tiles with share bars (items with "+N
     today"; with a configured media library **"library X GB / total
     cataloged Y GB"** — what physically sits under the collection root vs.
     everything cataloged (ADR 0041, I2) —, with metadata, interpreted,
     thumbnails with cache size, DB size with WAL). Next to them three
     panels: **composition by type** (stacked bar with table legend;
     underneath images and videos, each with their share of the item count
     and the storage they occupy across the whole collection — the sum is
     "total cataloged"), **growth of the last 30 days** (columns per day,
     today highlighted) and **years** by creation date. The numbers come
     from **the same source** as the gallery overview (ADR 0029).
   - **Activity:** the running task with bar, file counter, throughput
     (files/s) and remaining time; below it the **funnel** "where do files
     drop out" (seen → media → taken in → with metadata → interpreted,
     drops in between, failures red — only for tasks with a file report:
     ingest, scan, re-scan), **"new in this run"** with a throughput curve
     of the last three minutes, the **queue** with names and the
     **history** of the most recently finished tasks with duration
     (failures red).
   - **System:** six state tiles — worker process (running/ready/crashed,
     pool size), tools (`ffprobe`/`ffmpeg`, with an installation hint when
     missing), database (size, schema, WAL), **disk space** of the
     database drive as a ring with percentage, active parsers with
     version, instance (name, port, read-only mode/library management,
     fml/Python/SQLite version, uptime) — and the paths of database, logs
     and media library. The fml version is the release's date version
     (`2026.09`); a `+dev` suffix means "work in progress after that
     release", i.e. not a published state. Next to it the direct runtime
     packages **Pillow, fastapi, uvicorn, starlette, anyio, pydantic** with their actually installed
     version. If it differs from the pin in `requirements.txt` or a
     package is missing, the chip turns yellow, the tile gets the warning
     dot and the command to catch up is shown underneath. Anyone starting
     via `start.sh`/`start.bat` never sees this: the scripts install
     changed pins themselves before starting. The hint only concerns
     hand-maintained venvs and direct starts with `python -m feral.web`.
   - **Hint cards** with jumps: orphaned locations → Maintenance, open
     issues → Issues, block-list entries → Issues, watched sources →
     Sources.
2. **Configuration** (`/admin/config`) — edit `config.toml` from the GUI
   (see below): five cards, per setting a label, the input, an explanation
   underneath and a badge **immediate** or **restart**; changes collect in
   the **save bar** at the bottom. Plus **language** and **appearance**
   (dark/light), which apply immediately and only to this browser.
3. **Sources & import** (`/admin/sources`) — ONE ingest form at the top
   (once now / watch permanently), below it the watch folders as cards
   with live counters — see below.
4. **Maintenance** (`/admin/maintenance`) — four cards (raw files,
   thumbnails, database, re-evaluation) with a motivating key figure at
   the top and one row per action: title, explanation, button, **state
   right in the row** (running with bar · queued with position · last ✓
   result with time). Below them three cards of their own with the same
   logic in three steps and arming: **Move rejected out**, **Import rules
   on the collection** and **Clean up orphaned locations** — see
   "Maintenance actions".
5. **Issues** (`/admin/issues`) — one card per error kind with an honest
   counter, the most recent entries and "dismiss all N of this kind"; the
   all button at the top names the true total. Below it the **block list**
   as its own card: loaded separately, **paged** (100 per page) with
   **search** over path, hash and reason — see "Issues and block list".
6. **Rankings** (`/admin/rankings`) — table of rankings (name,
   expression, population, duels, items with score, created) with
   **Delete** behind a confirmation dialog; below it "Recompute ranking
   scores" — see "Rankings".
7. **Logs** (`/admin/logs`) — both server-log files immediately visible
   (see "Activity, queue and server log").

> The admin has no overlays, only two dialogs (folder picker,
> confirmation). Overview and Maintenance load in two stages: key figures and charts
> immediately, the system state (tools, database, parsers) a moment
> later — until then "…" is shown.
>
> **Orphaned locations and cache size** are NOT counted on page load
> (several seconds of disk work on large collections); instead a
> **remembered stand with time** is shown ("as of 18:23"). Counting
> happens on click — **Check locations** and **Count cache** under
> Maintenance — and by itself in the background after matching tasks
> (intake, rescan, move-out, clean-up → locations; create thumbnails,
> clear cache, import rules → cache); while that runs, "checking …" is
> shown and the page fetches the new stand on its own. The stand
> **survives restarts** (remembered in the database; older stands carry
> the date: "as of 09/12 18:23"); it belongs to this computer and cache
> folder — a database carried to another machine shows "?" again there.
> "?" means: never counted.

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

The "Sources & import" page has **one** ingest form in the card at the
very top: path (type it, or 📁 folder picker with click-through navigation
and file counts per folder) + **mode** + **frequency** ("once now" /
"watch permanently").
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
turns it into a **watch folder** below the form.

## Watch folders — the purpose

Every watch folder (cards below the form, ADR 0030) is monitored
continuously; new files are imported by themselves after a quiet period
(copied into the `YYYY/MM/DD` structure, with duplicate check and hash
verification). Each card shows name, path, state (watching / off / not
found) and two **live counters**: how many files are currently
**pending** (in the quiet period) and how many have been **imported**
since the server started; the counters follow every status poll without
reloading. On each card the mode can be changed later (again with a
prompt), **Stop/Watch** toggles monitoring, and **✕ Remove** takes the
folder out of monitoring (deletes no files). The **mode** per folder:

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

> There is **ONE** folder concept, the watch folders. Older configs with
> `[hotfolder]` are taken over as a watch folder on start-up; "fixed scan
> locations" (`[[scan.locations]]`) no longer exist. The former
> "scanning" is the mode "catalog only" in the ingest form. Navigation
> happens everywhere in the 📁 folder dialog, which starts at the entry
> points project folder / home / drives and shows the file count per
> folder.

## Maintenance actions (by functional area)

Long-running jobs go through the internal queue in a separate worker
process (section "Activity, queue and server log"). Every action is a
**row** with title, explanation, button and its state: **running** (with
counter, duration and bar), **queued · position n** or **last ✓ result ·
time** from the engine history (empty after a restart — the log has
everything). While an action runs or waits, its button is locked.
Synchronous actions (clean up, clear cache) write their result into the
row immediately.

The key figure at the top of each card motivates the actions below; cheap
numbers show immediately. Orphaned locations and cache size are a
**remembered stand with time** (box above) with their own button in the
meter — **Check locations** and **Count cache**; "?" means never counted,
"checking …" means a background count is running.

**Raw files** — key figure: orphaned locations (share of all locations),
remembered stand; **Check locations** recounts everywhere.
- **Re-scan all locations** — read all known, still existing locations
  again (idempotent). Useful after installing ffmpeg or when files may have
  changed.
- Cleaning up orphaned locations is a card of its own (below).

**Thumbnails** — key figure: cache files versus items (rough; failure
markers count too) and cache size, remembered stand; **Count cache**
re-reads the cache folder.
- **Create thumbnails** — create missing ones and **retry** failed ones
  (important after installing ffmpeg); permanent failures appear with a
  reason under Issues (kind `thumbnail`). This button is the ONLY path
  with a retry: the automatic runs after import/watch only create missing
  ones and leave dismissed failures alone.
- **Clear cache** — delete all previews including failure markers; they
  regenerate when viewed.
- **Analyse audio** (audio module only) — loudness and waveform for all
  audio items: create missing ones, retry failed ones, recalculate
  outdated measurements after an update. Playable copies (AIFF/ALAC/CAF)
  are only created on first playback; the button releases failed ones for
  the next attempt.
  Permanent failures appear under Issues (kind `audio`). After
  import/watch this runs automatically for new items; the audio cache is
  separate (`cache/audio`) and survives clearing the previews.

**Database** — key figure: file size, WAL, schema version. The button
**Compute breakdown** shows what the file consists of (raw blobs, items +
locations, layer 2, search index, other, free) — it reads the whole file
for that (seconds for GB-sized files) and therefore runs only on click;
if the SQLite build lacks the `dbstat` table needed for it (depends on the
platform of the Python build), there is no button at all, only the note
"not available".
- **Integrity check** — `PRAGMA integrity_check` + checkpoint the WAL.
- **VACUUM** — compact the database (after big delete/rebuild actions);
  "free" in the breakdown is what VACUUM reclaims.

**Re-evaluation** (all retroactive, no file access) — key figure:
interpreted items per parser (with parser version), plus items with raw
metadata but no interpretation (stock for new parsers) and items without
creation date.
- **Re-interpret** — layer-2 parsers retroactively over the whole
  collection. After new/improved parsers. Unchanged results are skipped —
  a repeat run over 70,000 items therefore takes seconds; the summary
  names interpreted items and fields.
- **Backfill creation dates** — add missing capture/creation dates
  (`media_date`) from metadata/file; also adds the **time of day** to
  legacy entries with a bare date. Uses the configured `[import]
  min_date`. Items without a plausible date honestly stay undated; the
  summary names their number. Get rid of them: "Import rules on the
  collection", keep them: lower `min_date`.
- **Rebuild search index** — recreate the FTS5 full-text index from scratch.

### Move rejected out (its own card)

The **only** way besides import in which fml moves files (ADR 0041). Three
steps side by side:

1. **Target folder** — type it or pick it via 📁; must be outside the
   media library.
2. **Preview** — honest numbers from the server: how many rejected files
   (block list with remembered paths) still sit **inside the media
   library**, how many GB, sample paths, paths no longer found. "Refresh
   preview" fetches them again.
3. **Run** — first the checkbox "Armed: target and preview checked" (only
   selectable with a target and hits), then the red button "Move N
   files". The task runs in the worker; its progress appears in a run box
   below the steps, in the widget on the left and in the overview.

The files move into a `YYYY/MM/DD/` date structure under the target
(collisions get `__2` suffixes, like on import). Before anything is
touched the **hash is verified** — if the file is missing or was replaced,
that is only reported. Every file is in the import log; the block list
remembers the new place. External (cataloged in place only) locations are never
candidates. In read-only mode the card is locked.

### Import rules on the collection (its own card)

Applies the configured import rules (min/max edge, excluded formats,
creation date from `min_date` — see the [import docs](import.md), ADR 0046
and ADR 0075) retroactively to the catalog, in three steps:

1. **Rules** — the active rules from the configuration, with a jump there.
2. **Preview** — how many items would the rules hit, broken down by reason
   (too small, too large, format, no date). Already computed when the page
   opens; "Check library" recomputes **and only then enables the
   checkbox**.
3. **Reject** — checkbox "Armed: preview checked", then "Reject N hits".
   Rejecting only marks (block list, reversible); files stay where they
   are and are moved only via "Move rejected out".

Legacy collections whose RAW files (ARW/NEF/DNG/CR2) are still cataloged
as TIFF are still hit by the format exclusion (file-extension match).
Common spellings like `tif` or `jpg` are mapped to the internal names
(`tiff`, `jpeg`).

### Clean up orphaned locations (its own card)

Removes path entries whose file no longer exists. **Items and metadata
stay**, media files are never touched — only the path bookkeeping goes.
The same three steps as the two cards above:

1. **Scope** — "everywhere" or "only under folder" (type a path or pick
   it via 📁; ADR 0033). Careful with "everywhere" while an external drive
   or NAS is unmounted — its locations would look orphaned; scope by path
   then.
2. **Preview** — "Check locations" counts within the chosen scope (checks
   every location's file, seconds on large collections) and shows sample
   paths. Runs only on click, never on page load; "everywhere" is at the
   same time the new remembered stand of the raw-files card. Any change
   to the scope invalidates the preview.
3. **Clean up** — checkbox "Armed: scope and preview checked", then
   "Clean up N locations"; the result stays in the card and the key
   figure of the raw-files card is refreshed.

## Issues and block list

At the top the summary ("N open issues in K kinds") with the all button,
which names the **true total** (ADR 0034). Below it **one card per error
kind**: counter, the 20 most recent entries ("latest 20 of 2013"),
"dismiss" per entry, "dismiss all N of this kind" at the bottom.
Dismissing reports the number of dismissed entries and reloads the cards.
Kinds: `failed` (not ingested), `warning` (extractor warning), `thumbnail`
(no preview) and `playback` (video that no or only some browsers play —
ProRes, 10-bit H.264, HEVC; see
[interpretation.md](interpretation.md#video-codec-and-playability)).

The **block list** (rejected media, ADR 0041) is its own card and is loaded
**separately** from the issues — with drives that are only cataloged it holds thousands
of entries:

- **Paged**, 100 per page, with "Back/Next" and range ("101–200"); the
  counter comes from the server and is never capped.
- **Search** over remembered path, hash and reason (typing searches after
  a short pause, Enter immediately); matches read "n matches of total".
- **Unblock** per entry allows re-import; "Unblock all N …" asks first.
  Rejected files sit untouched at their remembered location — rejecting
  never touched them.

## Rankings

Table of all rankings of the ranking module (ADR 0045): name, expression
(empty = all media), population (items the expression matches), duels,
items with score, created. **Delete** lives here and asks in a
confirmation dialog — it removes the ranking with all duels and scores, for
good. Below it **Recompute ranking scores** (Elo replay over the duel log
of all rankings, rescan principle) with an inline result. A ranking is
created only in the gallery (🏆 in the chip bar, the population is built
from the chips, see [Rankings](rankings.md)). **Edit** per row jumps to the
gallery into this ranking's edit mode, the same way as ✎ in the ranking.

## Activity, queue and server log

Long tasks (import, scan, re-scan, re-interpret, search index, creation
dates, thumbnails, VACUUM …) run **in a separate worker process** next to
the web server. The interface stays usable meanwhile: browsing, searching,
rating, tags and notes respond immediately, even while a 70,000-item run
is computing. Only when the database is briefly locked exclusively (VACUUM,
integrity check) does a write show "busy" — wait a moment and retry.

- **Activity** (overview, second row): the running task with progress
  (`Interpreting 12,400/70,000`), duration, throughput and funnel; below
  it the **queue** with the names of all waiting tasks and the **history**
  of the most recently finished ones (duration, result; in memory only —
  after a restart it starts empty, the log has everything). The widget at
  the bottom of the navigation and the dot in the gallery's top bar show
  the same in short form (`+2` = two waiting).
- **Repeated clicks** do not pile up: a task that is already running or
  waiting is not queued again (hint "already running"). Automatic
  follow-ups (thumbnails after an import) may queue once behind a running
  run.
- **Worker process crashed** (marked red): the running task is reported as
  aborted, waiting tasks are kept, the next task restarts the process. What
  happened is in the server log.
- **Server log**: folder `logs/` next to the database, two rotating files
  (`fml-web.log` for the web server, `fml-worker.log` for the tasks; at
  most 5 × 5 MB each). Every task is recorded with start, progress,
  duration, result and errors (with traceback). The **Logs** page shows
  both files side by side right away (stacked on narrow windows), per file
  with size, line count 100/500/2000, **Refresh** and the switch
  **"WARNING and above only"** (the filter runs on the server, traceback
  lines stay with their entry); WARNING lines are yellow, ERROR red, the
  newest line is at the bottom. At the top of the page: **wrap lines**
  (default on) and **stacked** instead of side by side — the browser
  remembers both. After every finished task both panes
  refresh by themselves — the first place to look when asking "is it
  stuck?". **The log is always in English**, regardless of the interface
  language: it is what other users paste into bug reports. Tasks appear
  under their key (`taskScan`, `sumReparse` …), not under the translated
  name. Requests taking longer than a quarter of a second appear as
  `slow:` with endpoint, duration, bytes and the number of requests
  running at the same time (`concurrent`). **Start-up requests are
  deliberately logged more tolerantly:** key figures, saved searches,
  rankings and the model list are computed once fresh after the server
  starts (and after every import) — that takes a few seconds on large
  collections and is not an error. Such lines appear as `cold:` with the
  reason (`first computation since server start`, `recomputed after a
  write`); afterwards the numbers come from memory until the
  collection changes. The same applies to the sidebar counters of a
  search: the first click on a saved search computes (`cold:`), every
  further one comes from memory. Equally tolerant: pairs for the duel that the
  frontend prefetches in the background while the current duel is on
  screen — in rankings with many filter criteria every pairing costs one
  filter run that nobody waits for. Such lines appear as `background:`;
  only a visible load remains a `slow:` warning. When
  the browser aborts
  a media stream (video switched, view closed), the server stops reading
  immediately and writes `aborted: … (client gone)`; the `concurrent`
  number therefore counts only live requests.

## First start (fresh installation)

Without a `config.toml`, the folder browser shows the **project/working
folder** as its first entry point (instead of a void) — from there you can
click through. **No** media folders are created automatically. For real
operation, set a media library and sources in the configuration.

## Editing the configuration

Five cards: **Media library** (import target, **library management** as
the read-only-mode switch, oldest plausible date, import rules),
**Thumbnails & performance** (size, processes, full power, slow
threshold), **Interface**, **Instance** and **Modules**
([rankings](rankings.md), [audio](audio.md)). Every setting has
a label, the input, a short explanation underneath and a badge:
**immediate** takes effect on save, **restart** only after restarting the
server. Changes collect in the **save bar** at the bottom, which only
appears while something is unsaved ("N changes · Save · Discard");
**Discard** restores the saved state, server errors show right in the
bar. **Language** and **appearance** (dark/light) in the "Interface" card
belong to the browser (ADR 0054): they apply immediately, without saving,
only to this browser, not to the instance, and therefore never count as a
change in the bar.

**Slow threshold** (card "Thumbnails & performance", `[performance]
slow_request_ms`, ADR 0076): from this response time on, fml reports a
request as `slow:` (warning in the log and on the console). The
default of 250 ms suits a desktop with NVMe; the selection recommends
profiles (laptop with SATA SSD 600 ms, Chromebook/USB drive/NAS 1,500 ms)
or a custom value. **Never warn** (0) leaves slow requests from 250 ms on
as info in the log file only. Cold-start runs (`cold:`) and prefetched
requests always stay info. Takes effect immediately, no restart. (Watch folders are **not** managed here but
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

- Media library, library management, import rules, slow threshold,
  instance name, accent color and module switches take effect
  **immediately** (badge).
- Port, thumbnail size, processes and DB path take effect **after
  restarting** the server.
- **Careful:** comments in a hand-maintained `config.toml` do not survive
  saving from the GUI. A backup `config.toml.bak` is created
  automatically beforehand; the commented reference is
  [`config.example.toml`](../../config.example.toml).
