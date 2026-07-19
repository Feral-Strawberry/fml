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
pip install -r requirements-dev.txt
```

Then:

```
pytest -q
```

## How do I recognize the correct result?

At the end there is a line like:

```
480 passed, 2 skipped in 4.2s
```

- **passed** = passed. The exact number grows with the project; what
  matters is: **0 failed, 0 errors**.
- **skipped** is fine: two tests need the video tools `ffmpeg`/`ffprobe`
  and skip themselves if those are not installed on the machine. The app
  still works, just without video metadata and video thumbnails.
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
| `test_image_pillow.py` | JPEG/WEBP/GIF & co.: embedded EXIF/XMP data and comments come out unchanged. |
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
| `test_web_engine.py` | The internal worker that processes all writes one after another: a crashing task does not take it down; watched folders (watch sources) only notice new files once they have "come to rest" (finished copying). |
| `test_web_app_static.py` | The interface is served correctly, and the browser does not get a stale version from its cache after an update. |
| `test_admin.py` | The admin console reports correct key figures; scan issues can be recorded and resolved; orphaned database entries (file no longer exists) are found and cleaned up. |

### 8. Thumbnails

`test_thumbs.py` checks: thumbnails respect the size limit, small images
are not artificially enlarged, animated files take the first frame,
videos go through `ffmpeg`. For broken files a reminder ("fail marker")
is stored so the computation is not retried in vain on every view. And:
the parallel generation across several processor cores produces
**exactly the same result** as the simple sequential one — so the fast
variant can never silently diverge from the correct one.

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

## For testers: when should I run the suite?

Normally not at all — the tests run before every check-in of changes. A
run makes sense when you have set the project up **freshly on a new
machine** and want to know whether the environment is right (Python
version, dependencies, optionally ffmpeg): `pytest -q` — if the end says
`passed` without `failed`, the installation is fine.
