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
- [Scanning folders](scanning.md) — recursively ingest a whole folder
  (`python -m feral.scan`). **The first step with real data.**
- [Import & watch folders](import.md) — sort source folders into the
  date-based media library by copying (duplicate check, visible
  outcomes) and keep folders under permanent watch. **The everyday way
  to bring in new media.**
- [The interface (web GUI)](gui.md) — **gallery** with thumbnails and
  detail view, pick folders by click, scan, watch and search
  (`python -m feral.web`). **The most convenient way to test.**
- [Admin & maintenance](admin.md) — DB status, maintenance actions
  (re-interpret, re-scan, integrity check, …), scan issues and config
  editing in the GUI.
- [Multiple instances](instanzen.md) — parallel, independent galleries
  from one program folder (own DB + port per instance): **sub-galleries
  of a master library**, without touching any files. Start via
  `start.bat --config name.toml`.
- [Security](security.md) — how Feral handles **untrusted** image files
  (untrusted metadata), operating recommendations and which dependencies
  to keep up to date. **Read before passing the tool on to others.**
- [The test suite](tests.md) — what the ~240 automated tests guarantee,
  how to run them (`pytest -q`) and how to recognize a correct result.
  **Useful as an installation check on a new machine.**
