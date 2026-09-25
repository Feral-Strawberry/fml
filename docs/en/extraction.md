# Metadata extraction (layer 1)

> What does it do? It opens a media file, detects the format and pulls out
> **all** embedded metadata **unchanged** — the ComfyUI workflow, the A1111
> parameters, embedded EXIF and so on. It does not yet *interpret* the
> values (no "this is the seed"); that is layer 2's job later. Whatever is
> not interpreted is still stored completely.

**Status:** implemented are **PNG** (own stdlib reader),
**JPEG/WEBP/TIFF/GIF/BMP** (via Pillow), **PSD/PSB** and **Kodak Photo CD** (own readers) and
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
- **`caBX`** — **C2PA manifest** (Content Credentials from Gemini, ChatGPT,
  Firefly, …), taken over as raw bytes (source label `png:caBX`). It is
  only interpreted in layer 2 ([generator detection](interpretation.md#generator-detection-gemini-chatgpt-firefly--co-c2paxmp)).

## What is read from JPEG/WEBP/GIF/BMP/TIFF (via Pillow)

All metadata segments Pillow finds in the container when opening — e.g.
embedded **EXIF** and **XMP**, the **ICC profile**, **comments** (JPEG COM,
GIF comment) and technical container values (animation `loop`, `duration`,
`dpi`). The source label is e.g. `"webp:info"`, the keyword is the Pillow
info key (`"exif"`, `"xmp"`, `"comment"`, …). Binary data stays
byte-exact, text stays unchanged.

In addition, **C2PA manifests** that Pillow does not pass through are
preserved: for **JPEG** the APP11 segments with the `JP` marker (a manifest
may span several segments; they are reassembled by packet number, source
label `jpeg:APP11`), for **WebP** the RIFF chunk `C2PA` (source label
`webp:C2PA`), for **MP4/M4A** the top-level `uuid` box with the C2PA
identifier (source label `isobmff:uuid`; ffprobe does not see it, so fml
reads just the box headers for it). Again: raw bytes, no interpretation.
Audio (ID3 `GEOB`, WAV chunk `C2PA`) is covered in [Audio](audio.md).

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

## What is read from Kodak Photo CD (own reader)

fml recognizes Photo CD files (`.PCD`, "Image Pac", about 1992–2004) by the
`PCD_IPI` signature at byte 2048. The **IPI header** is taken over
byte-exact (source label `"pcd:ipi"`), plus its text fields: film type
(`product_type`), scanner (`scanner_vendor`, `scanner_product`,
`scanner_firmware`, `scanner_serial`), maker of the writing station
(`piw_manufacturer`) and the photo lab (`photofinisher`). The **scan time**
is available as `CreateDate` — so it becomes the image's creation date,
even when the file stamp was lost long ago.

A Photo CD file contains the picture in several sizes. fml shows the
largest one present: **16Base with 3072×2048 pixels** (or 4Base with
1536×1024), in gallery, loupe and single view. The first full-size view
takes one or two seconds; fml then stores the picture losslessly as PNG
(default `cache/preview` next to the database, about 11 MB per picture),
after that it appears instantly. The folder may be deleted at any time,
the pictures are recreated on the next view.
Portrait shots are rotated as noted on the CD.

## What is read from video (via ffprobe)

All **container tags** from the format header and the individual streams,
e.g. `ENCODER` or `COMMENT` for WEBM. Source labels:
`"matroska:format.tag"` and `"matroska:stream0.tag"` (analogously
`"isobmff:…"` for MP4/MOV).

In addition, per stream the **key facts** under the label `"isobmff:stream0"`
(or `"matroska:stream0"`), keyword = ffprobe field name, value verbatim:
`codec_type`, `codec_name` (`prores`, `hevc`, `h264`, `vp9`, `av1`, …),
`codec_tag_string`, `profile`, `pix_fmt`, `width`, `height`, `bit_rate`.
[Layer 2](interpretation.md#video-codec-and-playability) turns these into
the fields `video_codec`, `video_profile` and `pixel_format` — and the
player knows before loading whether the browser decodes the codec. Videos
cataloged before this extension do not have the facts yet: run **Admin →
Maintenance → "Re-scan all locations"** once (or the
[diagnostic command](scanning.md#diagnostics-video-codecs-in-the-catalog)
for a quick overview without a re-scan).

> **Prerequisite:** `ffprobe` (part of **ffmpeg**) must be installed —
> macOS `brew install ffmpeg`, Debian/Ubuntu `apt install ffmpeg`, Windows
> `winget install ffmpeg`. **If it is missing, that is not an error:**
> videos are still cataloged (hash + location); a re-scan after installing
> it fetches the metadata.

On top, the **format facts** under `"isobmff:format"` (`format_name`,
`duration`, `bit_rate`) and the **duration** as its own column. The media
type comes from the actual tracks: a container without a real video
track (M4A, Matroska with sound only) is audio, see
[Audio module](audio.md) (without the module: unknown format).

## What is read from audio

Only with the [audio module](audio.md) switched on: MP3, FLAC, Ogg, WAV,
AIFF and CAF via dedicated walkers (standard library), every frame and
chunk raw with a source label; ffprobe only supplies duration, codec,
sample rate, channels, bit depth and bit rate. Details and examples of
the source labels in [Audio module](audio.md#what-is-stored).

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
