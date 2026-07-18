# Multiple instances: separate galleries from one program

> What is this? The Feral Media Library (fml) can run **in parallel** as
> often as you like — from the same program folder. An **instance** is: a
> config file + its own database + its own port. Every instance is a fully
> independent gallery with its own catalog, its own ratings, tags, saved
> searches and its own blocklist.

## What for? The sub-gallery use case

The main scenario: you have a **consolidated master library** (all media,
managed by one instance with library management enabled) and want to offer
**topic-specific partial views** of it — say, a curated selection to show
off, or one gallery per project. That is exactly what instances are built
for:

- The **main instance** manages the files (import, duplicates, date
  structure).
- Every **sub-instance** runs in read-only mode and only **catalogs the
  same files**: it reads them but is guaranteed never to touch them (no
  copying, no moving, no deleting — locked server-side).
- The sub-instance makes its selection by **rejecting**: whatever does not
  fit the topic flies out of *its* catalog — the file and the main
  instance remain untouched.

Result: the same files on disk, several independent views in the browser —
distinguishable by instance name, accent color and port.

## The model: what makes up an instance — and what is shared

| | per instance | shared |
| --- | --- | --- |
| config file (`--config`) | ✔ | |
| database (catalog, ratings, tags, notes, saved searches, blocklist, import log) | ✔ | |
| port, name, accent color (`[web]`) | ✔ | |
| watch folder list, library management on/off | ✔ | |
| program folder (code, `.venv`) | | ✔ |
| media files on disk | | ✔ (read only, except for imports by the managing instance) |
| thumbnail cache | | ✔ if the DBs sit in the same folder (see below) |

The thumbnail cache lives in the `cache/` folder **next to the respective
DB file**. If several instance DBs sit in the same folder (the simplest
setup), they share the cache — which is harmless and even economical,
because thumbnails are addressed by file hash: the same file gets the same
thumbnail in every instance and is computed only once. Worth knowing:
"Clear cache" (Admin → Maintenance) then affects all instances; the
thumbnails rebuild themselves on viewing.

## Creating a second instance (step by step)

**1. Create a config file** — in the program folder (next to `start.bat`),
e.g. `archive.toml`. Three entries suffice:

```toml
[database]
path = "./archive.sqlite"       # own DB — NEVER another instance's

[web]
port = 8801                     # own port — a different one per instance
name = "Archive"                # appears in the top bar, tab title and favicon
```

Optionally: `akzentfarbe = "#3b82f6"` under `[web]` colors this
instance's interface. You do not need to enter any further settings here
(watch folders, library management, thumbnail size …) — manage those in
this instance's GUI after starting it.

**2. Start** — with `--config`:

| System | Command |
| --- | --- |
| Windows | `start.bat --config archive.toml` |
| macOS / Linux | `./start.sh --config archive.toml` |

The browser opens on this instance's port as soon as the server is ready.
You keep starting the first instance normally without arguments
(`start.bat` uses `config.toml`) — both run at the same time, each in its
own browser tab.

**3. Configure** — in the new instance's GUI (Admin → Configuration).
Important to understand: **the GUI edits exactly the config file the
instance was started with.** Changes made in the archive instance land in
`archive.toml` and never touch `config.toml`.

**4. Stop** — close the instance's terminal/console window (or `Ctrl+C`).
Every instance has its own window.

## Walkthrough: sub-gallery "Nature" from the master library

Starting point: the main instance (`config.toml`, port 8765) manages the
library at `D:\Media\Library`.

1. Create `nature.toml`: DB `./nature.sqlite`, port `8802`, name
   `Nature`.
2. `start.bat --config nature.toml` — the Nature instance opens empty and
   in **read-only mode** (default; "👁" badge in the top bar). Library
   management deliberately stays OFF here.
3. In the Nature instance: Admin → Sources & import → path
   `D:\Media\Library`, mode **"catalog"**, "watch permanently" → Add.
   The instance indexes the entire collection in place — no file is
   copied or moved, only its own catalog is created. (A subfolder instead
   of the whole library works just the same.)
4. Curate: **reject** everything that does not fit the topic —
   individually (Del), via multi-select or with "⚡ Bulk action → reject"
   on a whole search result (e.g. filter `-tag: nature` first). Rejected
   media disappear from the Nature catalog and stay on this instance's
   blocklist — the watch folder will not pick them up again. File and
   main instance: unchanged.
5. From now on: port 8765 shows everything, port 8802 only Nature.
   Whatever the main instance newly imports shows up in the Nature
   instance automatically for sorting — keep or reject, once per file.

## Limits (by design)

- **One DB, one server:** two instances must **never** use the same DB
  file (`[database] path` must be unique per instance) — per database
  there is exactly one writing process (ADR 0007). Likewise the port must
  be unique per instance; an occupied port aborts the start with an error
  message.
- **Exactly one instance manages files:** library management
  (import/move-out into the same library root) belongs to ONE instance.
  All other instances only catalog — they do not need management, and two
  independently importing instances on the same root would drag
  duplicates into each other.
- **No sync between instances:** ratings, tags, notes and saved searches
  are independent per instance and are not synchronized. A sub-gallery is
  its own curation level, not a mirrored excerpt.
- **Backup per instance:** every instance has its own `*.sqlite` file —
  back up all the ones you care about.
