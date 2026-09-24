# DEPENDENCIES.md

> Every external dependency is documented here: **what** (package/version),
> **where** (which modules use it), **why** (why building it ourselves would
> be disproportionate). Project rule: prefer the standard library. Tooling is
> **pip**; `requirements.txt` is a **complete lock**: every package that is
> installed, direct or transitive, is listed with an exact version and the
> SHA-256 hashes of its files, and nothing else can be installed (see
> "How the lock works" below).

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
| **ffprobe/ffmpeg** | `src/feral/extract/video_ffprobe.py`: video container tags (WEBM/MKV, MP4/MOV); `src/feral/thumbs.py`: video poster frames; `src/feral/audio_analysis.py`: loudness (`ebur128`), three-band waveform and lossless FLAC playback copies for audio | The 20-year-old de-facto standard for media containers; `ffprobe` prints container tags as JSON, `ffmpeg` extracts the poster frame. No pip package, called via `subprocess`. **Optional:** without ffmpeg, videos are still catalogued (without metadata/thumbnail); a later scan or viewing fetches both. Installation: macOS `brew install ffmpeg`, Debian/Ubuntu `apt install ffmpeg`, Windows `winget install ffmpeg`. (ADR 0008/0013) |

### Web interface (ADR 0001)

| Package | Version | Where | Why not built in-house |
|---------|---------|-------|------------------------|
| **fastapi** | `==0.141.1` | `src/feral/web/app.py`: backend/routes of the local GUI | Chosen as the stack in the architecture workshop (ADR 0001). A home-grown HTTP/ASGI framework with validation would be an absurd amount of own code. Established, widely reviewed. |
| **uvicorn** | `==0.52.4` | `src/feral/web/__main__.py`: ASGI server that runs the app | Standard ASGI server for FastAPI. Installed plain (without the `[standard]` extras) to keep the transitive dependency surface small. |
| **starlette** | `==1.6.0` | `src/feral/web/media.py`: media responses with range requests and abort detection | The ASGI toolkit FastAPI is built on. fml uses its `Response`/`Headers` directly for the media stream (ADR 0069), so it is a direct dependency, not only a transitive one. |
| **anyio** | `==4.14.2` | `src/feral/web/media.py`: moving file reads of media streams into their own thread pool | The async runtime layer under starlette. Used directly for the dedicated media thread pool (ADR 0069). 4.14.2 fixes three advisories of 4.14.1. |
| **pydantic** | `==2.13.4` | `src/feral/web/app.py`: request models (`BaseModel`) | FastAPI's validation library; request bodies are declared as pydantic models. |

### Transitive runtime packages

Not imported by fml, but installed because the packages above need them.
Each is pinned and hashed like a direct dependency.

| Package | Version | Needed by | Role |
|---------|---------|-----------|------|
| annotated-doc | `==0.0.4` | fastapi | documentation metadata for type annotations |
| annotated-types | `==0.7.0` | pydantic | reusable constraint types |
| click | `==8.4.2` | uvicorn | command line parsing of uvicorn |
| colorama | `==0.4.6` | click | coloured console output, **Windows only** |
| h11 | `==0.16.0` | uvicorn | HTTP/1.1 protocol implementation |
| idna | `==3.18` | anyio | internationalized domain names |
| pydantic-core | `==2.46.4` | pydantic | validation core (compiled, binary wheels) |
| typing-extensions | `==4.16.0` | fastapi, pydantic, starlette, anyio | backports of typing features |
| typing-inspection | `==0.4.2` | fastapi, pydantic | runtime inspection of type hints |

### Installer

| Package | Version | Where | Why |
|---------|---------|-------|-----|
| **pip** | `==26.2.1` | `start.sh` / `start.bat` | The installer itself is part of the lock: the start scripts bring the venv's pip to exactly this version (hash-checked) instead of "whatever is newest". |

The frontend itself is **dependency-free** (HTML pages with vanilla JS
modules, no npm, no build step).

## Development dependencies

| Package | Version | Where | Why |
|---------|---------|-------|-----|
| **pytest** | `==9.1.1` | `tests/` | De-facto standard for Python tests. Writing our own test runner would be absurd. Pure dev dependency, not on the runtime path. |
| iniconfig | `==2.3.0` | via pytest | reads pytest's ini configuration |
| packaging | `==26.2` | via pytest | version and marker parsing |
| pluggy | `==1.6.0` | via pytest | pytest's plugin system |
| pygments | `==2.20.0` | via pytest | syntax highlighting in failure reports |

`requirements-dev.txt` includes the runtime lock (`-r requirements.txt`) and
adds these packages, also pinned and hashed.

| System program | Where | Why |
|----------------|-------|-----|
| **Node.js** (>= 20.6, no npm package) | `tests/js/`: Node unit tests of the frontend ES modules, started from pytest (`tests/test_frontend_modules.py`) | The interface is vanilla JS without a build step; to test its modules without a browser, exactly one JavaScript runtime is needed. Node ships a test runner (`node:test`) and loader hooks: no npm, no jsdom, no Playwright (kept in reserve, ADR 0064). The DOM stub is our own (`tests/js/dom.mjs`). **Optional:** without Node these tests are skipped. Installation: macOS `brew install node`, Debian/Ubuntu `apt install nodejs`, Windows `winget install OpenJS.NodeJS.LTS`. |

## How the lock works (ADR 0082)

- **Complete:** `requirements.txt` lists the full dependency closure for
  Python 3.12-3.14 on Linux, macOS and Windows, with environment markers
  where a package is platform-specific (colorama). Entries marked
  `# direct: <where>` are the dependencies fml chose; every other entry says
  `# via <package>`.
- **Hash-checked:** every entry carries the SHA-256 hashes of all its files
  on PyPI. `start.sh`/`start.bat` install with `--require-hashes`, so pip
  refuses any package that is not listed and any file whose content differs.
- **Binary only:** `--only-binary=:all:` means nothing is built from
  source, so no build tools are downloaded behind the scenes. fml itself is
  made importable with a `.pth` file pointing at `src/` instead of
  `pip install -e .` (which would fetch setuptools).
- **Regenerated, not hand-edited:** `python tools/lock_deps.py` rebuilds the
  closure and the hashes from the `# direct` entries; `--check` reports a
  stale lock. It needs only the standard library and the `packaging` module
  that ships inside pip.
- **Guarded by tests:** `tests/test_dependencies.py` fails when code imports
  a third-party module that is not a direct dependency, when a locked
  package is missing from this file, when the installed environment differs
  from the lock, or when an entry has no hash.

## Keeping the pins current (ADR 0080)

- **Dependabot** (GitHub, private repo): alerts and automatic security-update
  PRs are switched on; because every transitive package is in the lock,
  Dependabot can now update those too.
- **`python tools/check_advisories.py`**: stdlib `urllib` against
  [OSV](https://osv.dev) for every locked package plus everything installed
  in the venv. `tools/publish.py` runs it before every snapshot export and
  refuses to export while an advisory is open (`--ignore-advisories` is the
  emergency exit).
- Raising a pin: edit the `# direct` line in `requirements*.txt`,
  `python -m pip install -r requirements-dev.txt`, run
  `python tools/lock_deps.py`, run `pytest -q`, update this file and
  `docs/security.md`.

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
