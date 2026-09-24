# Security Policy

fml is a local single-user application: the server binds to `127.0.0.1`
only, there are no accounts and no network service. That leaves two attack
surfaces: untrusted **media files** and the **packages fml runs on**.
Whoever builds an image/video file freely controls every EXIF/XMP/PNG text
chunk and every embedded ComfyUI/A1111 workflow JSON — fml therefore treats
embedded metadata like a form submission from the internet and never trusts
it blindly. And every third-party package is a way into your machine, so
fml keeps them few and installs nothing it has not named.

## Supply chain: every installed package is named

- **Complete lock with checksums.** `requirements.txt` lists every runtime
  package, direct and transitive, pip included, each pinned to an exact
  version with SHA-256 hashes. What each package is for is documented in
  [`DEPENDENCIES.md`](DEPENDENCIES.md).
- **Hash-checked install from ready-made wheels.** The start scripts install
  with `--require-hashes` and `--only-binary=:all:`: pip refuses any package
  that is not listed or whose file was altered, and nothing is built from
  source.
- **Automatic checks.** Guard tests turn the test suite red when code
  imports an unlisted package or the installed environment drifts from the
  lock; every locked package is checked against the open vulnerability
  database [OSV](https://osv.dev), and a public snapshot is not published
  while an advisory is open; GitHub Dependabot alerts and security updates
  are switched on.
- **Check it yourself:** `python tools/check_advisories.py` asks OSV about
  exactly the versions in the lock and in your installation.

## Safeguards against untrusted files

The most important safeguards (full write-up in
[`docs/en/security.md`](docs/en/security.md), German original:
[`docs/security.md`](docs/security.md)):

- **Capped decompression** for PNG text chunks — a "zlib bomb" aborts at
  64 MiB instead of exhausting memory.
- **XMP is parsed without DTD/entity resolution** — no "billion laughs",
  no XXE, no network access from the parser.
- **Pillow's decompression-bomb protection** for images; a broken or
  malicious file becomes an issue entry, never a crash of the run.
- **Audio tags are read by a capped parser** (no block read beyond 64 MiB,
  compressed frames capped too, embedded pictures never stored), and
  **ffmpeg/ffprobe may open local files only**
  (`-protocol_whitelist file`, absolute `file:` path): a crafted file cannot
  trigger network access, a file name is never read as an option.
- **All SQL is parameterized**, full-text search terms are quoted, and
  every text originating from a file is **HTML-escaped** on display.
- **Host-header guard against DNS rebinding** (only
  `localhost`/`127.0.0.1`/`::1` are accepted) plus
  `X-Content-Type-Options: nosniff` on all responses.
- **File-system jumps are whitelisted**: "show in file manager" and the
  location breadcrumbs open only locations stored for that item (content
  verified by hash before revealing); media delivery serves cataloged
  files by hash only and stops reading when the browser aborts.
- **Log injection is neutralised**: control characters in logged file
  names (line breaks, ANSI, bidi) are made visible instead of written
  raw; the admin log page reads two fixed files only.

Operating recommendation: keep the server on `localhost` — there is
deliberately no login and no tenant separation.

## Reporting a problem

fml is a hobby project without a formal security process. If a file makes
the interface act strangely or crashes the import, keep the file and open
a **GitHub issue**; if you have a direct line to Feral Strawberry, use
that. A reproducible sample file is worth more than any bug report from
memory.
