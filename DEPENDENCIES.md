# DEPENDENCIES.md

> Every external dependency is documented here: **what** (package/version),
> **where** (which modules use it), **why** (why building it ourselves would
> be disproportionate). Project rule: prefer the standard library. Tooling is
> **pip**, versions are **pinned**.

## Runtime dependencies

### Core
The core (scanner, PNG container extractor, layer-2 parsers, hashing, DB) runs
on the **pure standard library** (`hashlib`, `zlib`, `struct`, `json`,
`sqlite3`, `os`, `threading`), with one exception for image containers:

| Package | Version | Where | Why not built in-house |
|---------|---------|-------|------------------------|
| **Pillow** | `==12.3.0` | `src/feral/extract/image_pillow.py`: image containers other than PNG (JPEG, WEBP, TIFF, GIF, BMP); `src/feral/thumbs.py`: image thumbnails | *The* Python imaging library for 20+ years, present in every AI stack, reviewed millions of times (foundation library, not a niche package). Parsing dozens of container formats ourselves would be disproportionate and error-prone. Extraction uses Pillow only as a **container opener**; thumbnailing was explicitly planned as a Pillow case in the project brief. (ADR 0008/0013) |

| System program | Where | Why |
|----------------|-------|-----|
| **ffprobe/ffmpeg** | `src/feral/extract/video_ffprobe.py`: video container tags (WEBM/MKV, MP4/MOV); `src/feral/thumbs.py`: video poster frames | The 20-year-old de-facto standard for media containers; `ffprobe` prints container tags as JSON, `ffmpeg` extracts the poster frame. No pip package, called via `subprocess`. **Optional:** without ffmpeg, videos are still catalogued (without metadata/thumbnail); a later scan or viewing fetches both. Installation: macOS `brew install ffmpeg`, Debian/Ubuntu `apt install ffmpeg`, Windows `winget install ffmpeg`. (ADR 0008/0013) |

### Web interface (ADR 0001)

| Package | Version | Where | Why not built in-house |
|---------|---------|-------|------------------------|
| **fastapi** | `==0.141.1` | `src/feral/web/`: backend/routes of the local GUI | Chosen as the stack in the architecture workshop (ADR 0001). A home-grown HTTP/ASGI framework with validation would be an absurd amount of own code. Established, widely reviewed. |
| **uvicorn** | `==0.52.4` | `src/feral/web/`: ASGI server that runs the app | Standard ASGI server for FastAPI. Installed plain (without the `[standard]` extras) to keep the transitive dependency surface small. |

> Transitive dependencies of FastAPI/uvicorn (starlette, pydantic, anyio,
> sniffio, click, h11, typing-extensions, idna) are the standard companions of
> this stack, established and widely reviewed. The frontend itself is
> **dependency-free** (one HTML page with vanilla JS, no npm).

## Development dependencies

| Package | Version | Where | Why |
|---------|---------|-------|-----|
| **pytest** | `~=9.1` | `tests/` | De-facto standard for Python tests. Writing our own test runner would be absurd. Pure dev dependency, not on the runtime path. |

| System program | Where | Why |
|----------------|-------|-----|
| **Node.js** (>= 20.6, no npm package) | `tests/js/`: Node unit tests of the frontend ES modules, started from pytest (`tests/test_frontend_modules.py`) | The interface is vanilla JS without a build step; to test its modules without a browser, exactly one JavaScript runtime is needed. Node ships a test runner (`node:test`) and loader hooks: no npm, no jsdom, no Playwright (kept in reserve, ADR 0064). The DOM stub is our own (`tests/js/dom.mjs`). **Optional:** without Node these tests are skipped. Installation: macOS `brew install node`, Debian/Ubuntu `apt install nodejs`, Windows `winget install OpenJS.NodeJS.LTS`. |

## Keeping the pins current (ADR 0080)

- **Dependabot** (GitHub, private repo): alerts and automatic security-update
  PRs are switched on; no footprint in the repo.
- **`python tools/check_advisories.py`**: stdlib `urllib` against
  [OSV](https://osv.dev) for the pins above plus everything installed in the
  venv (transitive packages such as starlette/pydantic). `tools/publish.py`
  runs it before every snapshot export and refuses to export while an
  advisory is open (`--ignore-advisories` is the emergency exit).
- Raising a pin: edit `requirements*.txt`, `pip install -r`, run `pytest -q`,
  update this file and `docs/security.md`.

## Deliberately NOT used

- **SQLAlchemy / ORM**: stdlib `sqlite3` is enough for a single-file DB with
  one writer process; an ORM brings no advantage here. (ADR 0007/0009)
- **sd-prompt-reader / sd-parsers as runtime dependencies**: good reference
  projects and inspiration for the layer-2 parsers, but niche packages. We
  build the parsers ourselves (from the tools' documentation, ADR 0004) and
  keep control over the raw format.
- **jsdom / Playwright**: for the frontend tests (ADR 0064) a DOM stub of
  about 450 lines of our own is enough; jsdom would be an npm tree,
  Playwright a browser download. Playwright stays in reserve for
  rendering/video regressions.
- **watchdog (hot folder)**: was reconsidered for stage 4; stdlib polling
  turned out to be sufficient. Decision recorded by ADR.
