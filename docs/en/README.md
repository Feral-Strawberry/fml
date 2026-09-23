# User & feature documentation (English)

> 🇩🇪 These pages are translated from the German originals in
> [`docs/`](../) — German is the single maintained source.


This documentation describes **per feature** *what it does and how to use
it* — without architecture rationale. It is written so that intermediate
builds can be handed to testers.


About the name: the project is called **Feral Media Library** — which is
where the abbreviation **fml** used throughout this documentation comes
from. It is developed by **Feral Strawberry** (also the name of the
GitHub organization).

## Feature blocks

- [Architecture](architektur.md) — the technical concept in four pictures:
  processes, intake with two metadata layers, search path, installation and
  supply chain.
- [Metadata extraction (layer 1)](extraction.md) — reads all embedded raw
  metadata from a media file. Implemented: PNG, JPEG/WEBP/GIF/BMP/TIFF
  (Pillow) and video (ffprobe).
- [Metadata interpretation (layer 2)](interpretation.md) — turns the raw
  metadata into searchable fields (prompt, model, seed, …); runs during
  the scan and retroactively via `python -m feral.interpret`.
- Content hashing — the stable identity of an item (covered in
  [extraction.md](extraction.md)).
- [Persistence / database](persistence.md) — how extracted data is stored
  and queried again.
- [Database schema](schema.md) — ER diagram and all tables with columns,
  keys and indexes, generated from the real schema.
- [Scanning folders](scanning.md) — recursively ingest a whole folder
  (`python -m feral.scan`). **The first step with real data.**
- [Import & watch folders](import.md) — sort source folders into the
  date-based media library (modes copy / move / catalog only, duplicate
  check, visible outcomes, import rules) and keep folders under
  permanent watch. **The everyday way to bring in new media.**
- [The interface (web GUI)](gui.md) — **gallery** with sidebar facets,
  chip search and saved searches, detail panel, loupe, single view with
  real zoom, A/B compare, workflow view for ComfyUI media, curating
  (rating, tags, notes, rejecting) and bulk actions (`python -m feral.web`
  or the start scripts). **Everyday use.**
- [Admin](admin.md) — its own page under `/admin` with overview,
  configuration, sources & import (watch folders), maintenance (re-scan,
  re-interpret, move out, apply import rules to the library, …), issues
  with block list, rankings and server log.
- [Rankings](rankings.md) — the optional ranking module: pairwise
  comparison with an Elo leaderboard over a saved search.
- [Multiple instances](instanzen.md) — parallel, independent galleries
  from one program folder (own DB + port per instance): **sub-galleries
  of a master library**, without touching any files. Start via
  `start.bat --config name.toml`.
- [Security](security.md) — how fml handles **untrusted** image files
  (untrusted metadata), operating recommendations, which dependencies get
  installed and how they are checked (lock with checksums, advisory check). **Read before passing the tool on to others.**
- [The test suite](tests.md) — what the 700-odd automated tests (Python
  and Node tests of the interface) guarantee, how to run them (`pytest -q`)
  and how to recognize a correct result.
  **Useful as an installation check on a new machine.**
