# Metadata interpretation (layer 2)

> What does it do? It makes sense of the raw metadata stored by
> [layer 1](extraction.md) and turns it into **structured, searchable
> fields**: prompt, negative prompt, model, seed, sampler, steps, CFG and
> so on. Whatever no parser understands is still kept completely — "not
> recognized" only means "not structured yet".

**Status:** parsers for **A1111/Forge/SD.Next** (the `parameters`
infotext), **ComfyUI** (the embedded prompt graph, also in WEBM/MP4
videos) and **XMP** (standard metadata: Midjourney prompts, "Made with
Google AI" labels, Lightroom ratings, creator tool). More (NovelAI,
InvokeAI, …) will follow — every new parser applies **retroactively to
the entire collection**, without re-scanning any files.

## Runs automatically during the scan

While scanning ([scanning folders](scanning.md), [web GUI](gui.md)) every
file is interpreted right after raw extraction. In the scan report and the
activity display, the number appears under **"interpreted"**.

## Running retroactively over the collection

When a new or improved parser arrives:

```bash
python -m feral.interpret --db ./feral.sqlite
```

> **Windows:** `python` must be the project Python, otherwise you get
> "no module named feral" — inside the project folder call
> `.venv\Scripts\python.exe -m feral.interpret --db .\feral.sqlite`
> instead (the venv is created by `start.bat` on first start).

This reads the raw metadata already stored in the database, runs all
parsers over it and replaces the structured fields. No file access, which
is why it is fast even for 70,000 items. The run can be repeated any
number of times.

## Searching over the fields

In the [web GUI](gui.md) the search understands two forms:

- `flux` — free search across all fields **and** the raw metadata.
- `model: flux`, `seed: 777`, `prompt: strawberry` — targeted search in
  one field.

## The field names

| Field | Meaning |
|------|-----------|
| `tool` | generating **platform**: `comfyui`, `a1111`, `midjourney`, `google`, `openai`, `azure-openai`, `adobe`, `flux`, `topaz`, `suno`; `c2pa` = manifest detected, not assigned. The product below it (Gemini, GPT-4o, Topaz Gigapixel, Midjourney V7) lives in `model` (see [generator detection](#generator-detection-gemini-chatgpt-firefly--co-c2paxmp)) |
| `prompt` / `negative_prompt` | the prompts |
| `model` / `model_hash` | checkpoint name / hash |
| `seed`, `sampler`, `scheduler`, `steps`, `cfg_scale`, `denoise`, `size` | sampling parameters |
| `lora`, `vae` | LoRAs loaded (normalized name, without path/extension) / VAE |
| `description` | image description from XMP (when no prompt is recognizable) |
| `credit` | origin credit, e.g. `Made with Google AI` (Gemini/Imagen) |
| `ai_source_type` | IPTC AI label, e.g. `trainedAlgorithmicMedia` |
| `creator_tool` | generating/editing program (e.g. Photoshop) |
| `rating` | rating embedded in the file (e.g. from Lightroom) |
| `job_id` | the generator's job ID (e.g. Midjourney) |
| `feature` | auxiliary tool used / workflow property (`adetailer`, `highres_fix`, `controlnet`, `refiner`, `prompt_builder`, `bbox`) |
| `input_image` | filename of the input image/video (present = img2img/i2v, not pure t2i) |
| `topaz_version`, `topaz_model`, `upscale_factor`, `source_size`, `topaz_settings` | Topaz post-processing (see below); `model` then carries `Topaz Photo AI` / `Topaz Gigapixel` / `Topaz Video AI` |
| `claim_generator`, `software_agent` | exact raw strings from the C2PA manifest (e.g. `DALL-E/3.0 c2pa-rs/0.28.4`, `GPT-4o`, `Adobe Firefly 1.0`) - lets you tell engines apart as soon as the metadata allows it |
| `video_codec`, `video_profile`, `pixel_format` | codec, profile and pixel format of the first video stream as ffprobe names them (`prores` / `HQ` / `yuv422p10le`; `hevc` / `Main 10`; `h264` / `High` / `yuv420p`); short form in the search field: `codec: prores` (see [below](#video-codec-and-playability)) |
| `lyrics`, `title` | lyrics and title tag of a music file (the lyrics are part of the full-text search) |
| `song_id`, `parent_id`, `relation` | song ID at the service (Suno), parent song and relationship (`extend`, `cover`, `remaster`, `edit` …), as far as the file names them |
| `bpm`, `key` | tempo and musical key |
| `audio_codec`, `sample_rate`, `channels`, `bit_depth` | technical data of the first audio track as ffprobe names it (`flac` / `48000` / `2` / `24`) |

A field can occur multiple times (e.g. several prompt candidates in a
ComfyUI graph with several text nodes).

## Usage from Python

```python
from feral.interpret import interpret_items

results = interpret_items(extraction.items)   # raw entries from layer 1
for interpretation in results:
    print(interpretation.parser, interpretation.parser_version)
    for f in interpretation.fields:
        print(" ", f.field, "=", f.value)
```

## ComfyUI: generator/API nodes and modern text encoders (parser v4)

Besides classic graphs (KSampler + CLIPTextEncode), the parser also
understands **generator/API nodes** that carry the prompt directly (e.g.
Krea 2 Turbo, Ideogram 4 — as a string or as a link to a source/builder
node such as the Ideogram 4 Prompt Builder from KJNodes) as well as
**custom text encoders** of modern templates (class name contains
"TextEncode", e.g. the Qwen encoder of the Krea 2 Turbo subgraph).
Already-scanned collections: run **Admin → Maintenance →
"Re-interpret"** once — it works retroactively over the stored raw blobs,
no new file scan needed.

**String chains** (v9): the text often does not hang directly off the
encoder but runs through chains of string holder, concatenation and
switch nodes (`PrimitiveStringMultiline`, `StringConcatenate` with
`string_a`/`string_b`, `TextBox1`, rgthree `Any Switch`). The parser
follows these chains and assembles concatenations (scene + style suffix,
the `delimiter` is respected); encoders not reachable via any sampler
path are resolved this way too. Graphs embedded under a foreign keyword
(e.g. in the MP4 `comment` tag) are recognized by their structure.

**Prompt-enhancer templates** (v10, ADR 0050 — Ernie Image/Turbo,
Krea 2): these templates toggle between the raw prompt and a built-in LLM
enhancer (`TextGenerate`) via a boolean switch. The parser resolves the
switch and reports the **raw user prompt** — the "enhanced" text only
comes into being at runtime and is not in the file; the enhancer's system
prompt template no longer shows up as the prompt. If the enhancer was
**active**, `feature: prompt_enhancer` marks the medium (in the panel
under FEATURES, searchable) — the displayed prompt is then the text
BEFORE enhancement. The empty negative of these workflows
(`ConditioningZeroOut`) is no longer wrongly attributed to the positive
text. To update the collection: Admin → Maintenance → "Re-interpret"
once.

**Prompt-builder workflows** (ADR 0028, e.g. Ideogram 4 Prompt Builder
KJ, also in Krea 2 setups): the final prompt only comes into being at
runtime there (JSON from drawn regions, often with AI enrichment) and is
not readably in the file. The parser instead reports the builder's
**general scene description** as `prompt` and marks the medium with
`feature: prompt_builder` (plus `feature: bbox` when region definitions
are involved) — visible in the panel under FEATURES, searchable via
`feature: prompt_builder`.

**Sampling settings from subgraphs and split nodes** (v11, ADR 0068,
issue #29): steps, sampler, CFG, scheduler and seed are also found where
no classic `KSampler` exists — in flattened subgraphs (node ids like
`30:3`, values as links from the subgraph boundary), in the split node
layouts of modern templates (`BasicScheduler`/`LTXVScheduler` for steps
and scheduler, `KSamplerSelect` for the sampler, `CFGGuider` for CFG) and
in LTX-2 workflows with `ManualSigmas` (nine sigma values = eight steps);
sampler nodes without a name field (`SamplerEulerAncestral`) derive the
name from the class. With several passes (hires fix, upscale pass) the
**main pass comes first** (full denoise before partial denoise; a sigma
list starting below 1.0 is a partial pass), the other
values remain as further rows; the detail panel shows steps as the first
chip. Without a `prompt` blob, the fallback reads the sampler widgets from
the UI graph — including subgraphs and values promoted to the subgraph
node. Cloud API nodes (MiniMax Hailuo, LTX 2.5 API) carry no steps; the
field honestly stays empty there. Existing collections: run **Admin →
Maintenance → "Re-interpret"** once.

## LoRA detection and the model actually used (ADR 0026/0027)

**LoRAs** are stored tool-independently as a **normalized name** (path and
extension stripped: `subdir/detail.safetensors` → `detail`), so that a
LoRA from ComfyUI and from A1111 maps to the same value and is found
together. Weights are deliberately not stored.

- **ComfyUI** detects LoRAs **generically** (ADR 0027): classic loaders
  and stackers (`lora_name`, `lora_name_1` …; on/off switches and
  `lora_count` are respected), dict slots (rgthree **Power Lora Loader**,
  pysssss) as well as unknown nodes whose class or input name contains
  "lora" and whose value names a model file. If the prompt blob is
  missing, the parser reads the **workflow blob** (UI graph) — where
  muted/bypassed nodes are skipped.
- **ComfyUI model**: the checkpoint **actually used** is reported — the
  parser traces the sampler's model input back through LoRA/model nodes
  to the loader. A checkpoint from a pure upscale/side branch no longer
  shows up wrongly as the model.
- **A1111** reads LoRAs from the **inline tags** in the prompt
  (`<lora:name:weight>`, `<lyco:…>`) and from the `Lora hashes:` line.
  The prompt text itself remains unchanged.

For existing collections: **Admin → Maintenance → "Re-interpret"**
(ADR 0011) — pulls the new LoRA/model values retroactively over the raw
blobs.

## Input image (img2img/i2v) and A1111 features (ADR 0027)

- **`input_image`** (ComfyUI): for every image/video load node
  (`LoadImage`, `VHS_LoadVideo`, …) the filename is stored. If the field
  is present, it was not pure text-to-image. Search: `has: input_image`
  or `-has: input_image` (pure t2i images).
- **`feature`** (A1111): shows auxiliary tools used — `adetailer`,
  `highres_fix`, `controlnet`, `refiner` (from the keys of the settings
  line). Search: `feature: controlnet`.
- **`feature`** (ComfyUI, ADR 0028): `prompt_builder` and `bbox` mark
  builder workflows whose displayed prompt is only the scene description
  (see above).

## Topaz: post-processing counts as a model (ADR 0066)

Files processed with **Topaz Photo AI, Gigapixel or Video AI** are
recognized by the `topaz` parser from the traces the programs leave:

- **Photo AI:** `Software` (EXIF) or `CreatorTool` (XMP), e.g.
  `Topaz Photo AI 3.2.2 (Windows)`.
- **Gigapixel:** the settings line in the image description, e.g.
  `Upscaled with Gigapixel v1.0.7. 1200x593 => 2400x1186 (2x) Model: High
  Compression, denoise: 0.26, sharpen: 0.41.` (Gigapixel only writes it when
  "Embed image settings" is enabled in the preferences - on by default).
- **Video AI:** the container tag `videoai`, e.g. `Enhanced using prob-3
  with recover details at 43 … Changed resolution to 1266x960`.

They appear in the sidebar **under "By model"** as `Topaz Photo AI`,
`Topaz Gigapixel` or `Topaz Video AI` and can be filtered with
`model: Topaz Gigapixel` - just as you used to assign them by hand as a
manual model. A manually set model still takes precedence. If the file keeps
its original generator data (A1111/ComfyUI), it is listed under both models:
generated with one, upscaled with Topaz.

The details sit next to it in the panel: `topaz_version`, `topaz_model`
(e.g. `High Compression`, `prob-3`; several for video chains),
`upscale_factor` (`2x`), `source_size` (size before processing, `size` is the
target size) and `topaz_settings` (the complete line, unchanged). Searchable
like any field: `topaz_model: prob-3`, `has: upscale_factor`.

Detection is based on community evidence (Topaz does not document its
metadata). If a case is missing, a report with the output of
`exiftool -a -G1 file` helps - the parser then runs retroactively over the
collection (`python -m feral.interpret`), no rescan needed.

## Video codec and playability

The `video` parser reads the **first video stream** (not necessarily stream
0 — some MOV files carry the audio first) from the ffprobe extractor's
stream facts ([extraction.md](extraction.md#what-is-read-from-video-via-ffprobe))
and stores `video_codec`, `video_profile` and `pixel_format`. With that:

- **Search:** `codec: prores` (alias for `video_codec: prores`),
  `codec: hevc`, `pixel_format: yuv420p10le` — all affected files at once,
  e.g. as a smart folder.
- **Honest player:** loupe, single view, panel and ranking ask the browser
  BEFORE loading (`canPlayType`) whether it decodes the codec. If not, the
  poster frame appears with the note "This browser cannot play ProRes (HQ,
  10-bit) …" instead of a black player that only delivers audio — and no
  stream is requested at all. If a video still fails during playback
  despite the browser's promise, the note names codec and error code.
- **Scan issue on ingest:** when cataloging, importing and in watch folders,
  videos with codecs no mainstream browser plays (ProRes, DNxHD, Motion
  JPEG, 10-bit or 4:2:2 H.264) get an issue of kind `playback` under Admin →
  Issues; HEVC (H.265) is reported as "only in some browsers" (Chrome/Safari
  with hardware decoder, Firefox depending on the system). The issue
  resolves itself once a re-scan finds the file in a playable codec.

No browser except Safari decodes ProRes; the audio track (AAC/PCM) still
plays — hence "audio without picture". Existing catalog: run one re-scan
(Admin → Maintenance), then `python -m feral.interpret`; the
[diagnostic command](scanning.md#diagnostics-video-codecs-in-the-catalog)
gives the overview beforehand.

## Generator detection: Gemini, ChatGPT, Firefly & co. (C2PA/XMP)

The sidebar group **"Generator"** shows the **platform** a file was created
on: ComfyUI, A1111 / Forge, Midjourney, Google, OpenAI, Adobe, Topaz. Below
it, in **"By model"**, sits the product or model: `flux1-dev` as well as
`Midjourney V7`, `GPT-4o` or `Topaz Gigapixel`. Both are layer-2 field values
(`tool` and `model`). Clicking a platform makes the model list count in
context, so the matching models move to the top.

Images from **Gemini, ChatGPT, Firefly, Photoshop (Generative Fill), Azure
OpenAI or Sora** carry no prompt, but usually **Content Credentials** (a C2PA
manifest, preserved as a raw block since the scan - see
[extraction](extraction.md)). The `provenance` parser reads platform and,
where the manifest allows, model from it:

| Platform (`tool`) | Recognized by | Model (`model`), when documented |
|---|---|---|
| `google` | Google's generator library in the manifest (`Google C2PA Core Generator Library`), issuer `Google LLC` together with the AI marker, or the XMP credit `Made with Google AI` / `Made by Google AI` | none - Google does not name the model (Imagen, Nano Banana, … stay manual); XMP credit `Edited with Google AI` → `Google Fotos` |
| `openai` | `ChatGPT`, `OpenAI API`, `DALL-E`, `Sora` in the manifest | `GPT-4o` (GPT Image 1), `DALL-E 3`, `Sora` |
| `azure-openai` | `Azure OpenAI DALL-E` / `Azure OpenAI ImageGen` | none |
| `adobe` | `Adobe_Firefly`, `Adobe Photoshop/…`, `Adobe Firefly` in the manifest | `Adobe Firefly` (also for Generative Fill in Photoshop) |
| `flux` | `Black Forest Labs`, `Flux.1` in the manifest (e.g. LMArena downloads) | the raw product string, e.g. `Flux.1`, `FLUX.1 Kontext [pro]` |
| `suno` | Suno's own entries in the manifest (`Suno, Inc.`); songs, see [Audio](audio.md#what-fml-reads-from-music) | `Suno v4.5`, `Suno v5` … (parser `suno`, from the model code name) |
| `c2pa` | manifest present but no known generator | none - the raw strings sit next to it |

From other parsers: `midjourney` (parser `xmp`, web downloads; the model
comes from the prompt parameters `--v 7` → `Midjourney V7`, `--niji 6` →
`Niji 6`; without the parameter the model stays manual) and `topaz` (parser
`topaz`; models `Topaz Photo AI`, `Topaz Gigapixel`, `Topaz Video AI`).

**The workflow wins.** If a file names its own generator (A1111 parameters,
ComfyUI workflow), an additional Content Credentials manifest is
post-processing - Windows Photos, Paint, Photoshop and others write it on
save. Such files stay under ComfyUI or A1111; the manifest only contributes
the raw strings. A Flux image made in ComfyUI does not become a Microsoft or
Adobe file just because it was opened there once.

In the search use `tool: google` or, equivalently, `generator: google`; for
models as always `model: "GPT-4o"`. The panel additionally shows the raw
strings `claim_generator` and `software_agent` (exact, with version) as well
as `ai_source_type` (`trainedAlgorithmicMedia` = generated,
`compositeWithTrainedAlgorithmicMedia` = AI-edited).

**Honesty:** Content Credentials often do not survive upload and sharing -
messengers, many websites and image editors strip them. Without a manifest
fml cannot recognize the origin; the image then sits under "(unknown model)"
without a generator. For Stability, Grok, Ideogram and
Leonardo there are no documented markers - fml does not guess. The rules are
based on research, not on samples from the own collection: please report
wrong or missing assignments (with the output of `exiftool -a -G1 file` or
`c2patool file`), they are corrected retroactively (`python -m
feral.interpret`).

**Catching up the collection:** files scanned before this version do not yet
have their manifest as a raw block - run **Admin → Re-scan all locations**
once, the interpretation then follows automatically. Midjourney and Topaz
models need no re-scan; `python -m feral.interpret` is enough there.

## Checking coverage: LoRA and prompt report

If LoRAs or prompts are missing in your collection, the diagnostics show
what the parser does not yet understand (both only read, they write
nothing):

```bash
python -m feral.interpret --db ./feral.sqlite --lora-report
python -m feral.interpret --db ./feral.sqlite --prompt-report
```

The **prompt report** takes all ComfyUI-suspect items without a
recognized prompt and sorts them by cause:

- `nur-workflow` (workflow only) — the file carries only the UI graph, no
  prompt blob (the saver did not write the API graph)
- `json-kaputt` (broken JSON) — the blob is not parseable JSON
- `text-unerkannt` (text not recognized) — graph readable, but the text
  hangs off nodes/inputs the parser does not know (listed with sample
  text)
- `fremdes-keyword` (foreign keyword) — the graph JSON sits under an
  unexpected keyword (e.g. in an EXIF field instead of the PNG chunk)

Please pass the output (categories, node types, sample hashes) to the
developers — every reported type becomes a test case for the next parser
version.
