# Security

> Short version for users and testers: what Feral does so that **untrusted
> image files** cannot abuse the tool as an attack path — and what you
> should keep an eye on yourself.


## Threat model

As long as you only manage **your own** images, this is background
knowledge. As soon as you import **files from others** (third-party
collections, downloaded images, a shared watch folder) or **pass the tool
on**, this applies:

> **Every piece of metadata embedded in a file is untrusted.**

Whoever builds an image/video file freely controls every EXIF/XMP/PNG text
chunk and every embedded ComfyUI/A1111 workflow JSON — including malicious
content. Feral therefore treats this data like a form submission from the
internet: never trust it blindly.

## What Feral protects against

**Input / parsers (during scan & import):**

- **PNG text chunks** are read with **capped decompression**: a tiny
  `zTXt`/`iTXt` chunk deliberately inflatable to gigabytes ("zlib bomb")
  is aborted at 64 MiB, discarded and logged — it cannot take down the
  import via memory exhaustion.
- **XMP** (embedded XML) is read without DTD/entity resolution; a packet
  containing `<!DOCTYPE`/`<!ENTITY` (e.g. "billion laughs") is skipped.
  The parser never fetches external entities (no XXE, no network access).
- **Images** are opened by Pillow with its built-in protection against
  decompression bombs; an extractor error on a broken/malicious file never
  stops the whole run — the file becomes an issue entry, the scan goes on.
- **ComfyUI workflow graphs** are evaluated with cycle protection — a
  deliberately chained/cyclic graph does not run into an endless loop.

**Processing / database:**

- All database queries are **parameterized** — no metadata or search text
  is ever concatenated into SQL. The full-text search (FTS5) quotes the
  search terms; field and sort names come from fixed whitelists.

**Display (in the browser interface):**

- Every text originating from a file (prompt, raw metadata, filename,
  tags, search hits) is **HTML-escaped** when inserted into the page —
  embedded malicious code is displayed as text, not executed.
- The workflow graph preview forces all coordinates from the untrusted
  JSON to **numbers**, so no value can break out of the SVG.

## Residual risks & operating recommendation

- **Bind to `localhost` only.** Feral is a local single-user application.
  Do not run the server openly reachable on a network — there is
  deliberately no login/tenant separation.
- **Host guard against DNS rebinding.** Even a server bound to
  `localhost` only can be attacked in the browser if a malicious website
  rebinds its domain to `127.0.0.1` via DNS. Feral therefore rejects any
  request whose `Host` header is not `localhost`/`127.0.0.1`/`::1`
  (400). If you deliberately bind wider via `--host` (e.g. for access
  over a private VPN like Tailscale), that list opens automatically —
  which makes the recommendation above matter all the more. All
  responses additionally carry `X-Content-Type-Options: nosniff`.
- **The folder browser is powerful.** The admin interface can list
  directories across the whole machine (for choosing source/target
  folders). That is intended, but one more reason not to expose the
  server.
- **New formats = new review.** PSD/PDF preview and further parsers are
  still open; when they come, the same rules apply (cap the parsers,
  escape the output).

## Keeping an eye on dependencies

Feral deliberately keeps the dependency surface **tiny** (project rule
"prefer the standard library"; details in
[`DEPENDENCIES.md`](../../DEPENDENCIES.md)) — three
runtime packages plus one optional system program. Still: **whoever runs
the tool should keep these few dependencies up to date**, because they
take part in processing the untrusted files:

| What | Version (pinned) | Why keep an eye on it |
|-----|-------------------|-------------------------|
| **Pillow** | `12.3.0` | Opens untrusted image files (JPEG/WEBP/TIFF/…). Image parsers are a classic target for security bugs — on a Pillow CVE, **update promptly**. |
| **fastapi** | `0.136.3` | Web backend of the local interface. |
| **uvicorn** | `0.49.0` | ASGI server; deliberately without the `[standard]` extras (smaller transitive surface). |
| **ffmpeg/ffprobe** | system (optional) | Reads untrusted video containers. Not a pip package — keep current via the system's package manager. Without ffmpeg, videos are only cataloged. |
| pytest (development only) | `~=8.0` | Not in the runtime path. |

Practically: the pinned versions provide reproducible installs; when
updating a dependency, raise the pin in `requirements.txt` and run the
tests (`pytest -q`). Watching security advisories is most worthwhile for
**Pillow** and **ffmpeg**, because both directly touch untrusted binary
data.

## Found a problem?

Feral is a private learning project without a formal security process. If
something odd happens while testing (a file that makes the interface act
strangely, a crash during import), keep the file and tell Feral Strawberry —
easiest as a GitHub issue; if you have the direct line, use that. As a
reproducible test case the file is worth more than any bug report from
memory.
