# Changelog · Feral Media Library (fml)

> 🇩🇪 Diese Übersetzung wird aus dem deutschen [`CHANGELOG.de.md`](CHANGELOG.de.md)
> gepflegt; bei Widersprüchen gilt das deutsche Original.

What changed between snapshot releases, from the user's point of view.
Versions are date versions (`YYYY.MM` or `YYYY.MM.N`); a running
instance shows its version under Admin → Overview.

## 2026.09.3 (2026-09-25)

fml now reads **Kodak Photo CD**: the pictures from the photo CDs of the
90s, in full resolution. Plus two fixes in the audio module and more
robustness on Windows.

### After updating

1. **Start with `start.sh` or `start.bat` as usual.** Dependencies and
   database schema are unchanged.
2. **Photo CD files that were sorted out so far** (the watch folder's
   "unknown format" outcome folder): simply put them into the watch folder
   again, or rescan the scan location.

### New: Kodak Photo CD

- **`.PCD` files** are recognized, cataloged and displayed in the largest
  size the file holds: **3072×2048** (or 1536×1024). Portrait shots are
  rotated as noted on the CD.
- **Creation date from the CD:** the scan time is stored in the file's
  header and becomes the picture's date, even when the file stamp was lost
  long ago. The detail panel also shows scanner, film type and photo lab.
- **Fast from the second time on:** fml computes the large picture on the
  first view (one or two seconds) and then keeps it losslessly as PNG in
  the cache (`cache/preview` next to the database, about 11 MB per picture;
  safe to delete any time, location via `[cache] preview`).

### Fixes

- **Audio: the pause button** in the list and in the playback bar reacts
  reliably during playback. Before, a click on ❚❚ often went nowhere while
  the space bar worked.
- **Audio: the sidebar group "Lyrics"** now says "with lyrics" / "without
  lyrics" instead of "with vocals" / "instrumental": it only tells whether
  lyrics are stored in the file, not whether anyone sings.
- **Windows:** ffmpeg and ffprobe no longer flash console windows, and the
  server no longer crashes when its output is redirected (e.g. when started
  without a console).
- **Overview mode:** Admin → Sources no longer shows a false "no import
  target" warning.

### For installs without a console

- **`--exit-when-idle MINUTES`:** the server shuts itself down once no fml
  page has been open for that long and no task is running or waiting (at
  least 2 minutes).
- **`--help-dir DIR`:** a folder with an `index.html`, such as your own
  guide: fml then shows a **?** at the top right that opens it in a window
  above the library.

### Security

- **fml reads Photo CD with its own capped decoder:** at most 16 MiB per
  file, a bounded number of rows, the search for row markers runs in C. A
  crafted file ends quickly instead of blocking the thumbnail processes.
  Permanent test with mangled files.

## 2026.09.2 (2026-09-24)

fml now does **music** too: the new **audio module** catalogs songs from
Suno, from ComfyUI or your own recordings, shows them in a dedicated
audio view with a waveform, and brings a player built for comparing
versions. The module is off by default; if you only manage images and
videos, you get a tidier sidebar, the media type filter and the duration
of videos.

### After updating

1. **Start as usual with `start.sh` or `start.bat`.** The dependencies
   are unchanged.
2. **Database:** migrated automatically to schema 28 on the first start
   (four new migrations). Make a backup of `feral.sqlite` first, as with
   every update.
3. **Optional, once Admin → Maintenance → "Re-scan all locations":**
   gives videos you already cataloged their duration (for `duration:` and
   sorting by duration).
4. **Cataloging music:** switch on Admin → Configuration → Modules →
   **Audio module**, then run "Re-scan all locations" once for existing
   scan locations. Watch folders re-check skipped audio files by
   themselves. Duration, loudness, waveform and playing AIFF/CAF need
   **ffmpeg** (as for videos).

### Highlights: the audio module

- **Formats:** MP3, FLAC, Ogg/Opus, WAV (also RF64/BW64), AIFF, CAF and
  M4A or MKA/WEBM with sound only. Every tag and every chunk is stored
  unchanged, embedded covers are only described. The media type comes
  from the actual tracks: an MP4 with sound only is audio, no longer
  wrongly video.
- **What fml reads from music:** title, lyrics, tempo, key and the
  technical details of the audio track. **Suno:** song ID, the creation
  time as media date and the Suno version from the Content Credentials
  (`Suno v4.5`, `Suno v5` …). **ComfyUI music** (YuE, ACE-Step, MiniMax
  Music): style prompt, lyrics, seed and model. Logic Pro bounces and
  iPhone voice memos are recognized. The **lyrics are in the full-text
  search**: one line finds every version of a song.
- **Audio view:** switch **▦ Gallery | ♪ Audio** at the top left; both
  views share the search. Songs appear as a full-width list, every row
  with a **three-colour waveform** (bass, mids, highs) on a shared time
  axis, loudness in LUFS, rating and comment count. Shared name
  beginnings are dimmed so the difference stands out.
- **Player:** every row has **its own playhead**, exactly one plays at a
  time: four versions can be heard chorus against chorus. **Loudness
  matching** to -14 LUFS (on by default) so the louder version does not
  win; tempo without pitch change, A–B loop, **"Play all"** like a CD, a
  playback bar that keeps running when you switch to the gallery, and the
  keyboard's media keys. AIFF, CAF and ALAC get a lossless FLAC copy in
  the cache on first play, only if the browser cannot play the format
  itself.
- **Time comments** like on SoundCloud: **K** puts "Chorus" or "voice
  cracks" at the playhead position. Pins under the waveform jump exactly
  there on click, the texts fade in during playback, and the search finds
  them.
- **Comparing:** mark 2 to 6 songs, press **C**: the list narrows to
  them, the waves grow, the comments show as text. Rate and reject as
  usual, **Esc** returns to the same spot in the full list.
- **Covers and finished songs:** an image from your own library as cover
  makes a song "finished". It then also appears **in the gallery**, as a
  tile with ♪ and duration, with single view and player; playback bar and
  media keys show the cover too. Nothing is written into the files.
- **Music playlist on the side:** regular music (no AI generator) shows its
  embedded album picture in the list, the playback bar and with the media
  keys; the default pictures from Suno & Co. stay out. A song still only
  enters the gallery with a chosen cover. Muted preview videos in the
  detail panel and in rankings no longer pause the music, and the playback
  bar stays visible in a ranking.
- **Loudness and waveform** are measured in the background after every
  import; Admin → Maintenance → "Analyse audio" catches up on anything
  missing.
- Rankings stay with images and videos; songs are never part of them.

### Improvements for everyone

- **Tidier sidebar:** new group **Media type** (Image · Video, with the
  module also Audio). File type, aspect, resolution, input image and
  location now live in the block **"More criteria"**, collapsed by
  default; if a value inside is active, the header says "· 1 active". The
  "+ Criterion" popover follows the same order and knows media type,
  generator and duration.
- **New filters:** `type:` (`image`, `video`, `audio`; German `typ:`) and
  `duration:` (`duration: >120`, `duration: <=3:30`, `duration: 60-180`;
  German `dauer:`), plus sorting **by duration**. Videos show their
  duration in the detail panel, the loupe and the single view.
- **Typing help:** if a word exactly matches a media type ("video"), it
  comes first, with the full-text search below.
- **Import rule "Exclude formats/extensions"** also matches the file
  extension, on import and in the collection tool: `lang` keeps programs' language
  files out even if their content happens to look like a known format.
- **"🎲 Find seed variants"** only appears for media that have a seed.

### Bug fixes

- **Admin → Overview** sometimes showed the same disk twice when another
  process was writing while it was displayed. Drives are now recognized
  by their device ID.

### Security and docs

- **ffmpeg and ffprobe only open local files now:** a crafted video or
  audio file can no longer make them access the network, and a file name
  starting with `-` is never read as an option.
- The new **audio parser** is capped against truncated files and forged
  length fields and was tested with tens of thousands of mangled files.
- **`SECURITY.md`** now names the supply chain right at the start: every
  installed package named and secured by checksum, automatic checks
  against the OSV vulnerability database, and how to check yourself
  (`python tools/check_advisories.py`).
- New **audio module** page in the docs; README and user docs describe
  audio, covers and the new sidebar.
- `config.example.toml` names the log prefixes the way the log writes
  them (`slow:`, `cold:`).

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
