# Metadata extraction (layer 1)

> What does it do? It opens a media file, detects the format and pulls out
> **all** embedded metadata **unchanged** — the ComfyUI workflow, the A1111
> parameters, embedded EXIF and so on. It does not yet *interpret* the
> values (no "this is the seed"); that is layer 2's job later. Whatever is
> not interpreted is still stored completely.

**Status:** implemented are **PNG** (own stdlib reader),
**JPEG/WEBP/TIFF/GIF/BMP** (via Pillow), **PSD/PSB** (own reader) and
**video WEBM/MKV/MP4/MOV** (via the system program `ffprobe`). PDF is
*detected* but not extracted (deliberately dropped, ADR 0051). The
interpretation of the values is done by [layer 2](interpretation.md).

## Usage

```python
from feral.extract import extract

result = extract("/path/to/image.png")

print(result.container)      # "png"
for item in result.items:
    print(item.source, "|", item.keyword, "=>", (item.text or item.data))
print(result.warnings)       # empty list if everything was clean
```

### Result: `ContainerExtraction`

| Field | Meaning |
|------|-----------|
| `container` | detected container type, e.g. `"png"` (via magic bytes, not the file extension) |
| `items` | list of raw metadata entries found, in discovery order |
| `warnings` | non-fatal oddities (e.g. CRC errors, truncated file). Empty list = clean |

### One entry: `RawMetadataItem`

| Field | Meaning |
|------|-----------|
| `source` | where the entry came from, e.g. `"png:tEXt"`, `"png:iTXt"`, `"png:eXIf"` |
| `keyword` | key inside the chunk, e.g. `"parameters"` (A1111) or `"workflow"` (ComfyUI); `None` if there is none |
| `text` | the text value, unchanged — for textual entries |
| `data` | the raw bytes — for binary entries (e.g. EXIF) |
| `encoding` | how the text was decoded (`"latin-1"`, `"utf-8"`) or `"binary"` |
| `compressed` | `True` if the value was stored compressed and decompressed here |

Exactly **one** of `text` or `data` is always set.

## What is read from PNG

- **`tEXt`** — uncompressed text (A1111 writes its parameters here).
- **`zTXt`** — compressed text (decompressed automatically).
- **`iTXt`** — international/UTF-8 text (ComfyUI stores workflow/prompt
  here), optionally compressed.
- **`eXIf`** — embedded EXIF, taken over as raw bytes.

## What is read from JPEG/WEBP/GIF/BMP/TIFF (via Pillow)

All metadata segments Pillow finds in the container when opening — e.g.
embedded **EXIF** and **XMP**, the **ICC profile**, **comments** (JPEG COM,
GIF comment) and technical container values (animation `loop`, `duration`,
`dpi`). The source label is e.g. `"webp:info"`, the keyword is the Pillow
info key (`"exif"`, `"xmp"`, `"comment"`, …). Binary data stays
byte-exact, text stays unchanged.

## What is read from PSD/PSB (own reader)

Photoshop files carry their metadata in **image resource blocks**. The
known metadata resources are taken over byte-exact: **XMP** (as text — so
layer 2's XMP parser applies automatically), **EXIF**, **IPTC** and the
**ICC profile**, plus from the header the dimensions, color mode
(RGB/CMYK/Lab …) and bit depth. Source labels: `"psd:8bim"` and
`"psd:header"`. Embedded preview thumbnails and tool settings (print,
grids, guides) are not metadata and are skipped. Collections cataloged
before this extension existed: run **Admin → Maintenance → "Re-scan all
locations"** once.

## What is read from video (via ffprobe)

All **container tags** from the format header and the individual streams,
e.g. `ENCODER` or `COMMENT` for WEBM. Source labels:
`"matroska:format.tag"` and `"matroska:stream0.tag"` (analogously
`"isobmff:…"` for MP4/MOV).

> **Prerequisite:** `ffprobe` (part of **ffmpeg**) must be installed —
> macOS `brew install ffmpeg`, Debian/Ubuntu `apt install ffmpeg`, Windows
> `winget install ffmpeg`. **If it is missing, that is not an error:**
> videos are still cataloged (hash + location); a re-scan after installing
> it fetches the metadata.

## Robustness

The extraction **does not crash on broken files**. Problems (wrong
signature, CRC errors, truncated chunks, missing end of file, invalid
UTF-8) end up as text in `warnings`; where possible, the content is still
taken over (a broken decode is preserved losslessly as raw bytes). A file
that cannot be read at all later becomes a case for the `_failed` folder.

## Hashing (the identity of an item)

Every file gets its stable identity from its **SHA-256 file hash**:

```python
from feral.hashing import hash_file
ident = hash_file("/path/to/image.png")   # 64-character hex string
```

This hash also carries the duplicate check, recovery and sync.

## EXIF text fields (WEBP/JPEG)

In addition to the byte-exact EXIF binary block, the **string tags** of the
main EXIF IFD are stored as readable entries (ADR 0016). For WEBP, ComfyUI
stores prompt and workflow exactly there (`Model="prompt:{…}"`,
`Make="workflow:{…}"`) — these entries get the embedded label as their
keyword and thus become visible to interpretation, search and the workflow
view. Collections scanned before this extension existed: run
**Admin → Maintenance → "Re-scan all locations"** once.
