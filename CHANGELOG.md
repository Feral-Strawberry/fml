# Changelog · Feral Media Library (fml)

> 🇩🇪 Diese Übersetzung wird aus dem deutschen [`CHANGELOG.de.md`](CHANGELOG.de.md)
> gepflegt; bei Widersprüchen gilt das deutsche Original.

What changed between snapshot releases, from the user's point of view.
Versions are date versions (`YYYY.MM` or `YYYY.MM.N`); a running
instance shows its version under Admin → Overview.

## 2026.09.1 (2026-09-23)

A security and diligence release: every package fml installs on your
machine is now named, pinned to an exact version and secured by checksum.

### After updating

1. **Start as usual with `start.sh` or `start.bat`.** The scripts reinstall
   the dependencies, this time in checksum mode, and clean up the earlier
   way fml itself was installed. Nothing else to do.
2. **Installing by hand:** `python -m pip install --require-hashes
   --only-binary=:all: -r requirements.txt` plus the `.pth` line from the
   README (section "For developers"); `pip install -e .` is no longer
   needed.

### Security

- **No unnamed packages any more.** `requirements.txt` is a complete lock:
  all runtime packages, direct and indirect, pip itself included, with an
  exact version and SHA-256 checksums. The start scripts install in
  checksum mode: pip refuses any package that is not listed and any file
  that was altered.
- **Nothing is built from source any more.** Only ready-made packages are
  installed; the start scripts neither download build tools nor an
  unpinned "latest" pip.
- **anyio 4.14.2** fixes three security advisories of the previous version
  (process groups, hanging process pools, TLS host names). fml does not use
  these functions directly, but updates anyway.
- **starlette, anyio and pydantic** are now pinned and documented as direct
  dependencies; fml uses them in its code, so far they only came in
  indirectly through fastapi.
- Automatic checks make sure it stays that way: an import without a named
  dependency, a package without checksum or without documentation turns
  the test suite red.

### Documentation

- New **Architecture** page with four diagrams: processes, the path of a
  file into the catalog, the path of a search to the gallery, installation
  and supply chain.
- The **security docs** describe every check around the dependencies, the
  test docs the new guard tests, the README the checked installation
  path.
- New **schema reference** of the database with an ER diagram, generated
  from the real schema.
- `DEPENDENCIES.md` lists every installed package with its role; the admin
  overview shows the six direct runtime packages with their versions.

## 2026.09 (2026-09-14)

The biggest step since the first release: 45 pull requests since
2026.07.3. The ComfyUI workflow preview now shows the graph the way
you know it from ComfyUI, the admin area is rebuilt from scratch,
metadata from Gemini/ChatGPT/Firefly/Topaz and modern ComfyUI
templates is recognised, plus noticeably more speed and a dozen fixes
from daily use with 70,000 media files. The test suite grew from 487 to 736 tests, for the first
time with regression tests for the user interface.

### After updating

1. **Update dependencies:** `pip install -r requirements.txt`
   (`start.sh` / `start.bat` do this on their own). The pins for
   fastapi and uvicorn were raised; Admin → Overview shows a yellow
   warning when the installed packages differ.
2. **Database:** migrated automatically to schema 24 on first start
   (two new migrations). Back up `feral.sqlite` beforehand, as with
   every update.
3. **Once: Admin → Maintenance → "Re-scan all locations":** collects
   the new raw metadata (C2PA manifests for generator detection,
   stream parameters for the video codec).
4. **Once: Admin → Maintenance → "Re-interpret":** the ComfyUI parser
   v11 finds steps/sampler/CFG in modern templates, plus Topaz,
   Midjourney models and video codecs. Unchanged items are skipped,
   the run is fast.
5. **Optional:** Maintenance → "Apply import rules to the library"
   now also lists items without a plausible creation date and removes
   them from the catalogue on request (see the date rule below).

### Highlights

- **ComfyUI workflows look like they do in ComfyUI**. The
  workflow view in the loupe used to be a box diagram; now it shows
  the graph the way you know it from ComfyUI: type colours on slots
  and links, widgets as pills with name and value, prompts and notes
  as text fields, bypass and mute marked, collapsed nodes, groups,
  expandable subgraphs with a way back. If you want to find a workflow
  again, you recognise it at a glance without opening ComfyUI. Still
  pure SVG from the embedded workflow, without a frontend dependency.
  Widget names of your own custom nodes come from one run of
  `tools/dump_object_info.py` against your ComfyUI instance.
- **Admin area rebuilt from scratch**. The
  admin is its own document under `/admin` with page navigation:
  Overview, Maintenance, Issues, Sources & Import, Configuration,
  Rankings, Logs. Browser back works, bookmarks too, the activity
  widget with the queue sits on every page. No more overlays: move-out
  and import rules are cards with three steps (target → preview →
  arm). Issues per error type with honest counters, block list paged
  with search over path, hash and reason. Configuration with an
  explanation per setting, "immediately" / "restart" badges and a
  save bar. The quick menu in the gallery is gone, the admin button is
  a link, dark/light has its own button in the top bar.
- **Better metadata detection**. Images from Gemini, ChatGPT/DALL-E/Sora, Adobe Firefly,
  Google Photos, Midjourney (V7, Niji 6) and Topaz post-processing are
  recognised by their embedded provenance data (C2PA, XMP) and appear
  in the new sidebar group "Generator"; Topaz counts as a model. The
  ComfyUI parser now finds steps, sampler, CFG and scheduler in modern
  templates with subgraphs and split sampler nodes (Flux, Wan, LTX)
  too; steps is the first chip in the panel. Videos carry codec,
  profile and pixel format as search fields. When a file names its
  creator itself (A1111, ComfyUI), that takes precedence.
- **A/B comparison**. Two selected images lie exactly
  on top of each other, key `C` or the "Compare" button. Wipe edge by
  mouse or arrow keys, `Tab` swaps A and B (blink comparison), zoom in
  real pixels, rate and reject straight from the view.
- **Faster, more stable, fewer hangs**. Long-running tasks (scan, import,
  re-interpret, thumbnails) run in their own worker process with a
  visible queue and progress; the interface stays fluid meanwhile.
  Gallery pages on large libraries 1.1 s → 3 ms, sidebar counters
  from one request instead of three, lists appear before the numbers,
  leaderboard 106 ms → 3 ms. Abandoned videos release their connection
  and the server detects aborted streams, large files no longer block
  anything. Unplayable videos (ProRes, DNxHD, 10-bit) show a poster
  plus a note instead of a black stage. Duels and ratings are no
  longer lost.
- **Saved search and ranking follow one pattern**. A ranking is a named search that duels run on: 🏆 creates
  it from the current chips, ✎ in the ranking loads its population
  into the gallery for editing and leads back. Saved searches: a click
  shows them, after a change ☆ offers "overwrite »name«" or "save as
  new search". The sidebar marks what is currently loaded.
- **Rankings: "Both out"**. Removes both items from the ranking
  for good; in the leaderboard they sit dimmed at the end with
  "Reinstate".

### Improvements

- Gallery: "All media" resets to the top, every other search change
  jumps back to the selected image. With watch folders a new
  image slides in at the top without the tiles flickering; selection
  and scroll position stay on the image.
- Single view and comparison: zoom level "max. 100 %", real pixels but
  at most screen-filling.
- Show in file manager: locations in a fixed order (library
  before source before external), Windows selects the file via the
  shell API and brings the Explorer window to the front, paths as
  clickable breadcrumbs (folders open, the file opens its
  application), no minute-long hangs on files over 64 MB.
- Sidebar: lists appear immediately, counters follow; all
  counters of a search state come from one request instead of three,
  a second click on the same search is free. Long lists
  (generator, model, LoRA) show hits on top, empty-in-context entries
  dimmed below.
- Gallery pages on large libraries 1.1 s → 3 ms, thumbnails stay
  fluid while scrolling.
- Admin figures that count on disk (orphaned locations, cache size)
  are a remembered state with a timestamp that survives restarts,
  instead of 7.6 s per page load.
- Overview shows images and videos each with share and storage; the
  instance card names the installed versions of Pillow, fastapi and
  uvicorn and warns when they differ from the pin.
- Top bar tidied: library counters only in the sidebar footer,
  no more ADR numbers in visible texts.
- Topaz post-processing counts as a model (`Topaz Photo AI`,
  `Topaz Gigapixel`, `Topaz Video AI`) with raw fields for version,
  upscale factor and source size.
- Server log: first computations after start-up are logged as
  `cold:`, prefetched duel pairings as `background:`, only warm slow
  requests remain warnings. The threshold is a setting,
  live without restart.
- Dialogs may stack (folder picker over move-out), Esc closes from top
  to bottom, input is preserved.
- Videos: codec, profile and pixel format are search fields
  (`codec: prores`), scan and import report unplayable videos as an
  issue, `python -m feral.diagnose video-codecs` gives an overview of
  the library without a re-scan.
- Date rule as an import rule: files without a
  plausible creation date (before `min_date` or in the future) end up
  in `_ausgefiltert/` on every intake path instead of
  `_unbekanntes-datum`; the start-up backfill only fires when it can
  actually date something.
- Phrases in field predicates: `prompt: 'new york'` searches
  for the multi-word substring; `"…"` stays exact, bare words stay
  substrings.

### Fixes

- Duels, ratings, tags and notes were lost intermittently ("SQLite
  objects created in a thread …"): the write connection was bound to
  one thread.
- On Windows the interface hung for 10 to 30 s whenever a task
  started: a lock was held across blocking IPC.
- The admin dashboard reloaded all figures on every poll (poll storm,
  10 % CPU when idle).
- A backfill for undatable items was queued on every server start; `min_date` was ignored in the process.
- The loupe opened on top of the open single view.
- Thumbnails stayed empty once four requests hung: time limits for all
  read requests; the video stage stayed black on errors.
- Discarded `<video>` elements kept their connection open until none
  was left (panel, loupe, single view, ranking).
- Explorer opened an empty window or the Documents folder for paths
  with spaces.
- Single-file scans from a watch folder were faster than the status
  poll, the gallery did not refresh.
- The chip editor placeholder was cut off at the first quotation mark.
- Overview showed an unlabelled GB figure next to "Videos".
- Pillow warning "Corrupt EXIF data" captured in two tests.

### For operators and developers

- Dependencies: fastapi 0.141.1, uvicorn 0.52.4, pytest 9.1; Pillow
  stays at 12.3.0. An advisory check against OSV runs before every
  export, Dependabot delivers security updates.
- Server log, console and `DEPENDENCIES.md` are always English,
  regardless of the browser language; prefixes `slow:` / `cold:` /
  `background:` / `aborted:`.
- New setting `[performance] slow_request_ms` (default 250, 0 = never
  warn).
- Version display: the instance shows the date version of the release,
  a working state after it carries `+dev`.
- Migrations 0023 (`ranking_scores.eliminated`) and 0024 (`app_state`
  for remembered figures with an origin stamp).
- New CLI: `python -m feral.diagnose video-codecs --db feral.sqlite`.
- Tests: Node regression tests of the ES modules without npm, test suite runs on Windows, 736 tests.
- Removed: quick menu in the gallery, top bar library counters, temp
  table `arena_pop`.

## 2026.07.3 (2026-07-19)

- After a search change the gallery jumps back to the selected image.
- Creation date with time of day; sort order "Created" is stable
  within a day.
- "Show in file manager" verifies the location by hash before opening
  and normalises the path.
- READMEs explain the ADR references.

## 2026.07.2 (2026-07-19)

- Example config starts in overview mode; test figures in the docs
  corrected.

## 2026.07 (2026-07-19)

First public release.
