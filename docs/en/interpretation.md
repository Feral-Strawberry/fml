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
| `tool` | generating tool (`a1111`, `comfyui`) |
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
