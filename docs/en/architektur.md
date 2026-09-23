# Architecture

> What is this? The technical concept behind fml in four pictures: which
> processes talk to each other, how a file gets into the catalog, how a
> search turns into a fast gallery and how fml itself gets onto a machine
> safely. For everyone who wants to understand
> what happens under the surface before reading the code.

fml is one application that runs as a server at home or on a laptop on
the go, always through `localhost` in the browser.

Technology: Python 3.12+ · FastAPI + uvicorn · SQLite (stdlib `sqlite3`,
WAL) · Pillow · ffprobe/ffmpeg · ES modules in the browser without a build
step. Every installed package is named with an exact version and checksum.

## Processes and boundaries

![The browser talks to the web process over HTTP. The web process reads the database, writes only short changes itself and hands long-running tasks through a queue to the worker process, which does the long writes and reads and copies files.](../img/architektur-prozesse.en.svg)

Two processes, one database. The web process answers every request and
stays fluid because everything long-running happens in a second process.
**The two write paths are shown in red:** short changes (rating, tags,
notes, duels) are written by the web process itself under a lock,
everything long-running (scan, import, re-interpret, thumbnails) is
written by the worker. The worker is started with `spawn`, gets one task
at a time and reports progress through a second queue; if it dies, the
next task restarts it. Media go through their own thread pool so large
videos never block a gallery request. The watcher checks every watch
folder and only queues a file once it has stayed unchanged for a quiet
time.

## How a file gets into the catalog

![Intake chain: source, detect, import rules, SHA-256, optional copy and verify, catalog, optional empty source. Cataloging stores layer 1 byte-exact in raw_metadata, layer 2 interprets fields from it, both end up in the full-text index. Re-interpreting runs over raw_metadata without file access.](../img/architektur-aufnahme.en.svg)

Every file runs through the same chain once, whether it arrives by
import, watch folder or cataloging. The mode only decides the dashed
steps: copy and move place a verified copy in the media library, only
move empties the source afterwards (see [Import](import.md)).

Identity is the content: the SHA-256 of the file is the key, a path is
only a location. Layer 1 understands containers, not conventions, and
stores every metadata entry unchanged. Layer 2 turns them into fields and
may have gaps. **Because the raw blob is kept,** a new or improved parser
runs over the whole collection without opening a single file. Ratings,
tags and notes are stored separately and are never overwritten by a
parser. Details: [Extraction](extraction.md),
[Interpretation](interpretation.md).

## From search to gallery

![Sidebar, typing and saved searches only create chips. The grammar turns chips into predicates, which become parameterized SQL. The epoch cache asks SQLite for data_version and recomputes only when the epoch has changed. Every commit, including external ones, changes data_version.](../img/architektur-suche.en.svg)

There is exactly one search state. Sidebar, builder, suggestions and
saved searches have no state of their own, they only create chips; the
grammar translates in both directions, so typed and clicked are
guaranteed to be the same. The epoch cache in the web process keeps hit
lists and counts until **any commit** changes SQLite's `data_version`,
including one from outside such as `python -m feral.interpret`. Deep
scrolling and the second click on the same search therefore cost
practically nothing. How to search: [The interface](gui.md).

## Installation and supply chain

![The direct packages are the source; tools/lock_deps.py generates requirements.txt from them with a fixed version and SHA-256 per file, the hashes come from PyPI. The start script has pip install in hash mode: pip downloads only ready-made wheels from PyPI, compares every file with the lock and aborts on an unlisted package or a wrong hash. Guard tests, advisory check, export gate and Dependabot check and maintain the lock.](../img/architektur-lieferkette.en.svg)

Only what is named gets onto the machine. `requirements.txt` is a complete
lock: every package, direct or indirect and pip itself, with an exact
version and the SHA-256 checksums of all its files. It is generated from
the direct packages (`# direct: where used`) by `tools/lock_deps.py`. The
start scripts have pip install **in hash mode and from ready-made wheels
only**: **an unlisted package or an altered file aborts the
installation**, and nothing is built from source. fml itself is hooked in
through a `.pth` file, without a build step.

Four guards keep the lock honest: tests fail when code imports a package
that is not named directly, when an entry has no checksum or no
documentation, or when the installed environment differs from the lock.
The advisory check asks the OSV database about every locked package, and
an open advisory blocks the public export. Dependabot proposes security
updates directly on the lock. Details: [Security](security.md),
[`DEPENDENCIES.md`](../../DEPENDENCIES.md).

## Guard rails

- **The original is sacred:** fml only touches files when importing and
  when moving rejected files out. Out of the box it runs in read-only
  mode: never copy, move or delete.
- **Everything derived is reproducible:** layer 2, thumbnails, creation
  date and full-text index can be recomputed from hash and raw blobs,
  without re-importing.
- **One writer per kind of task:** the worker writes long-running tasks,
  the web process short changes. SQLite in WAL mode, never on a network
  drive.
- **Provenance kept apart:** extracted from the file, interpreted from
  that, and set by a person are three separate stores.
- **Measure first, then build:** every scaling decision is measured
  against 250,000 synthetic media. SQLite stays because the numbers carry
  it.
- **Few, named dependencies:** six direct ones at runtime (Pillow,
  fastapi, uvicorn, starlette, anyio, pydantic), every other one is in the
  lock with version and checksum; plus ffprobe/ffmpeg as a system program.
  The frontend has no library and no build step.

The data model with all tables is in the
[schema reference](schema.md).
