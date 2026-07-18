# Security Policy

fml is a local single-user application: the server binds to `127.0.0.1`
only, there are no accounts and no network service. The threat model is
untrusted **media files**: whoever builds an image/video file freely
controls every EXIF/XMP/PNG text chunk and every embedded ComfyUI/A1111
workflow JSON — fml therefore treats embedded metadata like a form
submission from the internet and never trusts it blindly.

The most important safeguards (full write-up in
[`docs/en/security.md`](docs/en/security.md), German original:
[`docs/security.md`](docs/security.md)):

- **Capped decompression** for PNG text chunks — a "zlib bomb" aborts at
  64 MiB instead of exhausting memory.
- **XMP is parsed without DTD/entity resolution** — no "billion laughs",
  no XXE, no network access from the parser.
- **Pillow's decompression-bomb protection** for images; a broken or
  malicious file becomes an issue entry, never a crash of the run.
- **All SQL is parameterized**, full-text search terms are quoted, and
  every text originating from a file is **HTML-escaped** on display.
- **Host-header guard against DNS rebinding** (only
  `localhost`/`127.0.0.1`/`::1` are accepted) plus
  `X-Content-Type-Options: nosniff` on all responses.

Operating recommendation: keep the server on `localhost` — there is
deliberately no login and no tenant separation.

## Reporting a problem

fml is a hobby project without a formal security process. If a file makes
the interface act strangely or crashes the import, keep the file and open
a **GitHub issue**; if you have a direct line to Feral Strawberry, use
that. A reproducible sample file is worth more than any bug report from
memory.
