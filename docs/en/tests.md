# The test suite — what it checks and how to tell everything is fine

> What is this? The project ships an automated test suite: around **480
> small test programs** that run in a few seconds and check every central
> promise of the software. The complete suite runs before every code change
> that gets checked in. This page explains **how to start it**, **what a
> correct result looks like** and **what the individual test groups
> actually guarantee** — in a way that makes sense without a programming
> background.

## Running the tests

Install the development dependencies once (in the project folder):

```
python -m pip install --require-hashes --only-binary=:all: -r requirements-dev.txt
```

This installs exactly the packages from the lock (runtime plus pytest),
each with its checksum; see [`DEPENDENCIES.md`](../../DEPENDENCIES.md).

Then:

```
pytest -q
```

## How do I recognize the correct result?

At the end there is a line like:

```
907 passed in 40s
```

- **passed** = passed. The exact number grows with the project; what
  matters is: **0 failed, 0 errors**.
- **skipped** is fine: some tests need the tools `ffmpeg`/`ffprobe` and
  skip themselves if those are not installed on the machine. The app still
  works, just without video metadata, video thumbnails and audio
  loudness/waveform. Likewise the
  user-interface tests (group 9) skip themselves if **Node.js** is not
  installed, and on **Windows** one scan test that needs a symlink (Windows
  only allows that with admin rights or developer mode).
- A **failed** almost never means "the test is broken" but: a change broke
  one of the promises described below. That is exactly what the test
  exists for — it raised the alarm before the bug would show up on real
  data.

An important principle: the tests **never work with your real data**.
Every test builds its own inputs (for example a PNG, byte by byte) and
cleans up afterwards. You can therefore run the suite safely at any time.

## The test groups at a glance

The suite is cut along the architecture: every layer of the software has
its own tests. If you know the layers (see [extraction.md](extraction.md)
and [interpretation.md](interpretation.md)), you will find your way around
immediately.

### 1. Foundation: hashing, data types, format detection

| Test file | Checks |
|---|---|
| `test_hashing.py` | The SHA-256 fingerprint of a file is correct and always the same — whether computed in one go, in chunks, or straight from the file. |
| `test_types.py` | A raw metadata entry carries **exactly one** of: text or binary data. Never both, never neither. |
| `test_container.py` | Format detection (from the first bytes of a file) maps PNG, JPEG, WEBM etc. to the right reader module and reports unknown data cleanly instead of guessing. |
| `test_config.py` | The configuration file is read and written correctly; saving from the GUI loses no hand-written setting; old configurations (the earlier `[hotfolder]` format) are automatically migrated to the new watch-source format. |

**Why this matters:** the hash is the identity of every medium in the
library. Duplicate detection, import and later the sync between machines
all hang off it. If it were wrong, everything above it would be wrong.

### 2. Layer 1 — reading raw metadata from files

| Test file | Checks |
|---|---|
| `test_png_extractor.py` | The self-built PNG reader finds all text chunks (that is where A1111 parameters and ComfyUI workflows live), decompresses compressed parts and preserves the order. |
| `test_image_pillow.py` | JPEG/WEBP/GIF & co.: embedded EXIF/XMP data and comments come out unchanged; C2PA manifests (JPEG APP11 across several segments, WebP RIFF chunk) are reassembled byte-exact. |
| `test_video_ffprobe.py` | Video containers (WEBM, MP4, …): the metadata delivered by `ffprobe` is taken over correctly; if `ffprobe` is missing, there is a warning instead of a crash. |

**The actual point of this group:** more than half of these tests
deliberately feed the readers **broken files** — truncated, checksum
errors, mangled characters, missing end of file. The correct behavior is
always: **do not crash**, rescue what is readable, and record the problem
as a warning. In a collection of 250,000 files grown over years, the
damaged file is the normal case, not the exception — and a single one
must never abort a whole scan.

### 3. Layer 2 — understanding metadata (the largest block)

| Test file | Checks |
|---|---|
| `test_interpret.py` (48 tests) | The parsers turn raw metadata into searchable fields: prompt, model, LoRAs, seed, … — for A1111/Forge texts and for ComfyUI workflow graphs in all their shapes. |
| `test_interpret_xmp.py` | XMP data: Midjourney descriptions, Google AI labeling, Lightroom star ratings. |
| `test_interpret_provenance.py` | Generator from Content Credentials: Gemini, ChatGPT, OpenAI API, Azure, Firefly, Photoshop, Sora, Bing are recognized by their documented markers, priorities hold (Azure before OpenAI, ChatGPT before Sora), raw strings come out exact, unknown manifests are honestly called `c2pa`. |
| `test_reparse.py` | The retroactive re-interpretation of the whole collection: finds previously ununderstood data, changes nothing twice on repetition, and replaces outdated results when a parser was improved. |

**Why so many tests?** Almost every single test here is a **preserved
real-world case**: a workflow shape that at some point showed up in real
files and was not understood at first (nested nodes, LoRA loaders in five
variants, assembled text chains, graphs under a wrong name, …). When a
parser is developed further, these tests guarantee that **no previously
solved case breaks again**. That kept it measurable: of 1320 media
without a recognized prompt, only 23 remained after the parser
expansions — and it stays that way.

Two special cases deserve mention: one test checks that a workflow graph
with **circular references cannot freeze the software** (endless-loop
protection), and several check that parsers report "not responsible" on
foreign data instead of inventing nonsense.

### 4. Database and schema evolution

| Test file | Checks |
|---|---|
| `test_db.py` | Data is stored byte-exact (special characters included); re-scanning the same file creates **no duplicates**; the same file in a second place is recorded as a second **location** of the same medium, not as a new medium. |
| `test_migrations.py` | The database schema changes (numbered migration files) are gapless; a fresh database and one grown over months are guaranteed to end up in an **identical** state; two programs starting at the same time migrate exactly once. |

**Why this matters:** the migration tests are the insurance that a
software update **never** damages an existing library — no matter how old
its state was.

### 5. The pipelines: scanning and importing

| Test file | Checks |
|---|---|
| `test_scan.py` | The complete flow detect → hash → read → interpret → store produces the right counts; an unreadable file is recorded as a "scan issue" instead of aborting the run. |
| `test_importer.py` (27 tests) | The import workflow with all its safety guarantees (see [import.md](import.md)). |

The import tests are arguably the most important of the whole suite,
because they are about **"never lose data"**. Every test is a guarantee in
prose:

- Files are **copied, never moved**, and the copy is verified against the
  original by hash; if that fails, the file lands visibly in the error
  outcome.
- A **duplicate** (medium already present) is not copied again — but only
  if the existing copy is provably healthy. If the collection copy is
  damaged, it is **repaired instead of discarded**.
- Source files are only moved to the "done" folder **after** the database
  has durably stored the import. A crash in the middle can therefore
  never "lose" files.
- Name collisions get a suffix; files without a reliable date land in
  their own follow-up folder; an embedded creation date beats the
  filesystem date.
- What was deliberately deleted sits on a **blocklist** and is not
  silently imported again.

### 6. Manual layer: ratings, tags, notes

`test_manual.py` checks star ratings, tags and notes (set, change,
remove; setting twice is harmless). The most important single test makes
sure the manual layer **never writes into the extracted data**: what came
from the file and what you set yourself stay strictly separate. Only that
way can a re-scan never overwrite your ratings — and only that way does
it stay visible which information has which origin.

### 7. Web interface: search, filters, engine

| Test file | Checks |
|---|---|
| `test_filters.py` | The search bar's filter language (`model: flux`, `rating>=4`, `-tag: test`, `mp:`, `format:`, …) is parsed correctly and produces the right hit sets; typos in field names are rejected instead of silently ignored. |
| `test_web_library.py` (53 tests) | Gallery pages arrive in the right order and sorting; the full-text search finds prompts, filenames and word prefixes; the detail view shows all three information layers; the model counters in the sidebar are correct. |
| `test_web_media.py` (22 tests) | Serving media files (ADR 0069 addendum): range requests deliver exactly the requested bytes, unsatisfiable ranges end with 416, HEAD sends headers only — and when the browser drops the connection, the server stops reading after at most one more chunk instead of streaming a 4 GB video to the end. |
| `test_web_engine.py` | The queue and the real worker process (ADR 0067): tasks run one after another in the child process, a crashing task does not take it down, a dying process is reported and restarted, double clicks are rejected, short writes do not wait behind long tasks, every task is written to the server log; watched folders (watch sources) only notice new files once they have "come to rest" (finished copying). |
| `test_web_app_static.py` | The interface is served correctly, and the browser does not get a stale version from its cache after an update. |
| `test_admin.py` | The admin reports correct key figures (incl. overview numbers: kind, years, growth, disk space); scan issues can be recorded and resolved; orphaned database entries (file no longer exists) are found and cleaned up. |

### 8. Thumbnails

`test_thumbs.py` checks: thumbnails respect the size limit, small images
are not artificially enlarged, animated files take the first frame,
videos go through `ffmpeg`. For broken files a reminder ("fail marker")
is stored so the computation is not retried in vain on every view. And:
the parallel generation across several processor cores produces
**exactly the same result** as the simple sequential one — so the fast
variant can never silently diverge from the correct one.

### 9. The interface in miniature: the JavaScript modules in Node

The user interface is written in JavaScript modules (gallery, loupe, single
view, admin, search). Since 2026-09 they have their own tests **without a
browser**: Node.js runs the modules against a tiny imitation of the browser
page (`tests/js/`), and pytest starts them along with everything else
(`test_frontend_modules.py`). This requires an installed **Node.js 20.6 or
newer** — if it is missing, exactly these tests are skipped and the rest of
the suite runs as usual.

| Test file | Checks |
|---|---|
| `tests/js/dom.test.mjs` | The browser imitation itself: building the page from `index.html`, finding elements, keyboard/click events in the right order. |
| `tests/js/overlays.test.mjs` | Loupe and single view: Space/Enter/Esc in every combination — never two full-screen layers at once; a video is removed on close (does not keep playing twice); a video error shows the hint, closing aborts the running request, `view-changed` on open/close. |
| `tests/js/zoom.test.mjs` | Zoom step "max 100 %": small image in real pixels, large one like fit, device pixels (dpr 2), memory across images, gestures start from the effective scale, double-click goes to 100 %. |
| `tests/js/workflow.test.mjs` | Workflow preview in the ComfyUI look: slot/link colors by data type, sizes and palette, widget labels (named before instance dump before core table, else raw), bypass/mute/collapsed, groups, subgraph box and inside view, hardening against foreign workflow JSON. |
| `test_dump_object_info.py` | The tool reduces ComfyUI's `object_info` to widget names per node type in the right order (seed extra, required before optional) and tolerates garbage. |
| `tests/js/sidebar.test.mjs` | Sidebar facet "Generator": platform rows with display name and counter, the group sits above "By model", rows empty in context are dimmed below the divider (also in the model list), a click produces exactly one `chip-toggle` with an exact `tool:` predicate, the search state goes to the counters as a filter. |
| `tests/js/gallery.test.mjs` | Gallery: after a filter change it jumps back to the last selected image; "All media" leads to the top with no selection; when a new image arrives in a watch folder, the old tiles stay put and the new one slots in at the top. |
| `tests/js/dialogs.test.mjs` | Dialog stack of the gallery (ADR 0069): hidden dialogs (save) hang on the stack, Esc closes, a view change closes every dialog through its close function; read-request timeout with a translated message. |
| `tests/js/picker.test.mjs` | Folder picker in the admin document: open, cancel, open again, choose, apply — the chosen folder ends up in the field, Esc closes only the topmost dialog, no keyboard traps remain; the same in the move-out card (no dialog underneath), also after a page change. |
| `tests/js/status.test.mjs` | Shared status poller (ADR 0074): the gallery's top-bar badge is a link to `/admin`, shows the translated task name (never "[object Object]"), counts the queue, marks a crashed worker process; `engine-idle` fires only on the running→idle edge, "task finished" only on a changed `finished_seq`. |
| `tests/js/admin_shell.test.mjs` | Admin document: router (unknown slug → overview, click on a nav link → pushState + page, browser back renders the previous one, modifier clicks and the gallery link bypass the router), seven pages in fixed order, activity widget in all states, instance pill, schema/port. |
| `tests/js/admin_overview.test.mjs` | Overview page: key-figure tiles with shares, composition/growth/years, activity with funnel and history, reload only when a task finished, system tiles (disk ring, parsers, instance), hint cards with links. |
| `tests/js/admin_overview_pending.test.mjs` | Overview in two stages: key figures/charts immediately, expensive numbers (locations, thumbnail cache) show "…" and a checking hint until `/api/admin/info` arrives; no fade-in animation. |
| `tests/js/admin_logs.test.mjs` | Logs page: both files immediately (one call each with `?file=`), "WARNING and above only" as `?level=warning`, line count and refresh per file, coloring, honest empty message, wrap lines/stacked (remembered by the browser), refresh after a finished task. |
| `tests/js/admin_issues.test.mjs` | Issues page (A3, #66): one card per error kind with counter and "latest n of N", all button with the true number, dismissing reports the number and reloads; block list loaded separately, paged (100) with back/next and range, search with "n matches of total", unblock single and all (only after confirmation). |
| `tests/js/admin_maintenance.test.mjs` | Maintenance page (A3): four cards with action rows, state per row from the status poll (running with bar → queued with position → last ✓), enqueue and synchronous actions inline, move-out, import-rules and clean-up cards with two-step arming (clean-up: scope, preview only on click, scope change invalidates), DB breakdown only on click and honestly "not available" without dbstat. |
| `tests/js/admin_arenas.test.mjs` | Rankings page (A3): table with all columns, delete only after a confirmation dialog, recompute scores with inline result. |
| `tests/js/context.test.mjs` | Edit mode for rankings (ADR 0081/#133): "Editing: 🏆 Name" up front, header `editing`, save only on deviation without `sort:`, rename stores only the name, ✕ back into the ranking; a saved search opens no mode. |
| `tests/js/savedialog.test.mjs` | Save dialog (#133): without origin only Save; from a loaded search the origin is in the dialog, name prefilled, "Overwrite »Name«" (PUT) and "Save as new search" (POST), origin ends on clearing. |
| `tests/js/admin_dialogs.test.mjs` | Dialog stack of the admin document: picker above the confirmation, Esc top-down, folder picker of the move-out card (cancel keeps the field, choosing applies), closing from outside resolves the picker promise, confirmation dialog (yes/cancel/Esc). |

**"Expected red":** some of these tests describe behaviour that is still to
be built (they carry the number of the related issue in their name). They run
along, and their failing counts as passed — until the bug is fixed. Then the
test says so explicitly and becomes a normal test. Known bugs are thus
captured as checks from day one.

A single file can also be started directly:

```
node --import ./tests/js/setup.mjs tests/js/overlays.test.mjs
```

### 10. Dependencies and documentation guards

| Test file | Checks |
|---|---|
| `test_dependencies.py` | **No unnamed dependency:** every third-party import in the code is a directly named dependency; every lock entry has an exact version and checksums; every locked package is in `DEPENDENCIES.md`; the installed environment matches the lock exactly; the start scripts install in hash mode only. |
| `test_lock_deps.py` | The tool that generates the lock: complete closure across Linux, macOS and Windows, platform markers (e.g. Windows only), version bounds, file format. |
| `test_check_advisories.py` | The vulnerability database query: pins are read, hits are reported, and "offline" is an error, not a silent green. |
| `test_schema_doc.py` | The schema reference in the docs matches the real database schema. |

**Why this matters:** these tests make sure nothing unnamed creeps in,
neither into the program nor onto the machine, and that the documentation
does not silently go stale.

## Two recurring patterns

Reading the suite, you keep running into the same two ideas:

1. **Idempotence** ("running twice = running once"): re-scan,
   re-interpretation, migrations, setting a tag — everything may be
   repeated at will without creating duplicates or damage. That is the
   cheapest safety net for anything that runs over a 250,000-file
   collection.
2. **Equivalence** ("the fast variant must produce the same as the simple
   one"): parallel thumbnails vs. sequential, stream hash vs. whole-file
   hash. That is how performance rebuilds can be attempted without
   risking correctness.

## Interface check protocol (once per stage, in the browser)

The Node tests see no pixels: no real scrolling, no video error codes, no
rendering. That is why this fixed click list is worked through in the browser
**once per completed stage** (not per hand movement) — against a sandbox
server with a synthetic collection, never against the real library. The
result goes into the PR description as one line: `Check protocol: passed` or
`Check protocol: P4 deviates — …`.

**Preparation:** start a server with test data (at least two pages of
images, one video, one watch folder in catalogue mode), browser console and
network tab open.

| No. | Step | Expected |
|---|---|---|
| P1 | Load the page | counter in the header, tiles appear, no errors in the console |
| P2 | Scroll the gallery to the end and back; switch density S/M/L | no permanently empty tiles, scroll position stays sensible across density changes |
| P3 | Click an image, arrow keys, Shift-click, Ctrl/Cmd-click | ring follows the selection, panel shows the image, multi-selection counts correctly |
| P4 | Space, Enter, Esc in every combination; browse ←/→ in loupe and single view; open and close a video | never two full-screen layers at once, video plays once and stops on close, browsing moves the selection along |
| P5 | Type search text, remove a chip, click a facet in the sidebar, then "All media" | hit count follows, chips are right, "All media" leads to the top with no selection |
| P6 | Drop an image into the watch folder, wait | new image appears at the top, old tiles stay put, selection stays on the chosen image |
| P7 | Open admin (`/admin`); folder picker: open, cancel, open again, choose, apply; move-out card with picker; Esc; browser back | chosen folder ends up in the field, Esc closes only the topmost dialog, the page stays usable, back leads to the previous admin page or the gallery |
| P8 | Switch language (EN/DE) and back | interface switches completely, state remains |
| P9 | Review console and network | no JavaScript errors, no 5xx responses |

If a step fails, the finding is recorded as an issue (with the step number)
and — where the Node tests could have seen it — added as an "expected red"
test in `tests/js/`.

## For testers: when should I run the suite?

Normally not at all — the tests run before every check-in of changes. A
run makes sense when you have set the project up **freshly on a new
machine** and want to know whether the environment is right (Python
version, dependencies, optionally ffmpeg): `pytest -q` — if the end says
`passed` without `failed`, the installation is fine.
