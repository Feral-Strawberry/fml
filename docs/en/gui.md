# The interface (local web GUI)

> What is this? The local web interface of the Feral Media Library (fml):
> browse and search the collection, read metadata, scan/watch folders and
> do the maintenance - all without a command line. Since block 3.0 in a
> three-column layout (dark theme, switchable).

## Starting

The everyday way is the start scripts (double-click `start.bat` or
`./start.sh`) — they set up the environment on first run and open the
browser as soon as the server is ready. By hand:

```bash
source .venv/bin/activate
python -m feral.web
```

Then open in the browser: **http://127.0.0.1:8765**

Options: `--config config.toml` (which instance), `--port`, `--host
127.0.0.1` (default: only locally reachable), `--db` (overrides the DB
path from the config), `--browser` (open as soon as the server responds —
used by the start scripts). The port can live permanently in the config
(`[web] port`; precedence: `--port` > `$PORT` > config > 8765).
**Several instances running in parallel** (per instance its own config +
DB + port, started via `start.bat --config name.toml`):
[instanzen.md](instanzen.md).

## Layout

**Top bar:** search box (center), right next to it the **sort button** and
the **density S/M/L** (up here since 2026-07-11 - the bar below the search
belongs to the chips), collection counter (items · total size), activity
indicator (pulses while a scan/maintenance runs - clicking opens the admin
console), admin button (click opens the quick menu - since 2026-07-16 it
also holds the only dark/light switch; the separate ◐ icon is gone). If an
**instance name** is set in the configuration, it appears here as a
colored pill (plus tab title and favicon color dot - distinguishes
instances running in parallel). If fml runs in **read-only mode** (the
default state, ADR 0041), the badge **"👁 Read-only mode"** also sits
here: fml only catalogs and curates - files are never copied, moved or
deleted. Unlocking the file-writing paths: Admin → Configuration →
**Library management** (see [admin.md](admin.md)).

**Language (DE/EN):** without any action on your part, the interface
follows the browser language (German for `de*`, English otherwise). The
**DE/EN** button in the top bar (also a selector under Admin →
Configuration → Interface) switches hard: once set, the choice applies
permanently in this browser and overrides the browser language; switching
reloads the page. The language belongs to the viewer (browser), not to
the instance - two machines can view the same instance in different
languages (ADR 0054). Since block M.3 the search grammar additionally
understands **English aliases** for its German remnants: `file:` =
`datei:`, `location:` = `fundort:`, `portrait`/`square`/`landscape` =
`hochformat`/`quadratisch`/`querformat`, `-asc`/`-desc` = `-auf`/`-ab`,
`external` = `extern` and `unknown` = `unbekannt`. Both spellings are
always understood, whatever language is set; **canonical** (in chips,
saved searches and serialized expressions) remains the existing spelling
— saved smart folders stay valid untouched. Since block M.2 all
**server-generated texts** follow the UI language as well: activity
labels and progress in the admin console, result summaries ("Import: 3
new · 2 duplicates"), error messages of the search grammar and all other
server errors. The only exception: scan issues recorded BEFORE that
update appear unchanged in their old (German) wording - new entries are
stored language-neutrally and translated on display.

**Left - sources:** "All media", **Duplicates** (items that sit at
several paths on disk - the panel shows all locations), your **saved
searches**, the **Rating** group (exactly n stars - also for finding
poorly rated media on purpose), **By model** - including **"(unknown
model)"** for media without an interpreted model field (Midjourney,
Gemini, ChatGPT, …); WAN 2.2 two-stage checkpoints (high/low noise)
appear as ONE entry, the tooltip names both raw names and clicking
filters on both -, **By year** (creation date; the caret before the year
unfolds the months - legacy collections get their date via "Re-scan all
locations"), **By LoRA** (the LoRAs used during generation, most used
first), **By file type** (PNG, WEBP, video containers, …), **By format**
(rough aspect-ratio classes: portrait / square / landscape / widescreen -
for troubleshooting after an import), **By resolution** (megapixel
ranges: under 1 / 1-2 / 2-4 / over 4 MP), **Input image** (with/without -
finds img2img and image-to-video results) and **Location** ("in the
library" = at least one copy sits in the media library, "external only" =
only indexed in place, e.g. via `catalog` from external drives; the group
only appears when a media library is configured). A click puts a **chip**
into the search bar above the gallery (see "Searching"); a click on a
**second value of the same group** widens the chip to an OR ("flux OR
krea"), a click on an active (highlighted) value removes it again.

The counters **filter along**: as soon as chips are active, every group
shows how many hits a click would bring **in the current context** -
computed against the respectively *other* criteria (the own group
excludes itself, otherwise no OR could ever be built). Values that would
currently hit nothing are **dimmed instead of hidden** - what would exist
stays visible.

Every group can be **collapsed/expanded** by clicking its header
(remembered). At the bottom the library footer: items and total size -
with a configured media library split as **"library X GB · total Y GB"**
(library = what physically sits under the collection root, total =
everything indexed, external included).

**Center - gallery:** virtualized grid (fluid even with very large
collections - only visible tiles are in memory), newest first. On top: a
breadcrumb with the search chips and the counter; anchored to its right
**✕ Reset filters** (appears as soon as filtering is active - **Esc**
also clears the filters when no overlay is open) and **⚡ Bulk action**.
If a medium was selected when the filter or sort order changed and it is
also part of the new result list, the gallery **jumps back to it**
instead of starting at the top - Esc out of the seed-variant search thus
leads straight back to the last clicked image.
The **sort button** (Added / Created / Filename / File size / Container /
Rating - unrated and undated items last) and the **density S/M/L** sit up
in the top bar next to the search box. The sort button opens a small
menu; a **second click on the active entry flips the direction** (arrow
↑/↓ on the button and the chip). The sort order is part of the search
state: any choice other than the default "Added" appears as a sort chip
next to the filters and is **stored with** a saved search; loading a
search also restores its sort order. The sort order last chosen in the
menu is **remembered in the browser**: it keeps applying wherever no
search brings its own sort chip — including after a restart and after
"✕ reset filters". Videos carry a VIDEO badge, every
tile a tool/container chip. **Click** selects a medium (panel on the
right), **Space** opens the loupe (fast browsing), **double-click or
Enter** the single view (zoom + metadata); **arrow keys** move the
selection in the overview as well (←/→ one medium, ↑/↓ one row).

**Right - detail panel:** always visible. Top to bottom: preview (click →
loupe) · filename, type, format, size, **rating dots** · **CURATED**
(your tags and notes) · **GENERATION** (the interpreted fields: model,
sampler/steps/CFG, seed with click-to-copy, prompt/negative - with a
badge naming the parser that produced them; a negative prompt identical
to the prompt is not shown - some workflows leave the two
indistinguishable for us, and the same text twice would only be noise. At
the bottom **"🎲 Find seed variants"**: builds an exact chip search for
the same generation - prompt, negative, model, LoRAs, sampler, scheduler,
steps, CFG and size of this image, only the seed varies. Ideal for
cleaning up and comparing seed series; too strict? Removing individual
chips loosens the search) · **WORKFLOW** (for ComfyUI media: "View node
graph" and "load as .json"; for A1111 images with the badge "ComfyUI ·
generated" - see workflow view - plus **"Copy A1111 infotext"**: the
unmodified infotext for PNG Info / txt2img in A1111 and Forge) ·
collapsible **raw metadata** (layer 1, byte-true with source label) and
**locations** · **FILE** (format, size, **Created** - the creation date
with time of day (UTC) that "By year" groups by and that the "Created"
sort orders to the second; "no date" means: no plausible date found,
date without a time means: the time could no longer be determined
reliably for legacy entries -, Added, hash). Media without recognized generation data show a note - the
raw layer always stays inspectable.

**Panel widths:** the dividers left and right of the gallery can be
**dragged** (e.g. wider sidebar for long model names, wider right panel
for landscape images); double-clicking a divider restores the default.
The choice is remembered.

## Single view (zoom + metadata)

**Double-click or Enter** opens the selected medium in the single view -
the working view with real zoom: steps **fit / 50 / 100 / 200 %**, the
**mouse wheel** zooms continuously, **double-click in the image** jumps
between fit and 100 %, dragging pans. The percentages mean **real
pixels**: at 100 % one image pixel equals one screen pixel - regardless
of OS scaling (Windows 150 %, Retina Macs) and browser zoom. That makes
100 % pixel-sharp everywhere and the reliable step for judging details
and artifacts. The **last step chosen in the zoom bar is remembered**
and applies to every further image (if you always want 100 %, pick it
once); mouse wheel and double-click produce image-dependent in-between
values and deliberately do not change the remembered step. On the right sits the complete
metadata panel in wide form - rating (also keys 1-5), tags, model and
notes work the same here; more tools will come mid-term (metadata
editing, push-to-ComfyUI). **←/→** pages in grid order; **Esc, Enter or
✕** lead back to the gallery, which stays on the last viewed image.

**📂 Show in file manager** (top right, also in the loupe): opens
Explorer (Windows) or Finder (macOS) with the file selected - at the
first still-existing location, whose content is **verified via SHA-256**
before opening (if a different file now sits at the catalogued path, the
button honestly reports "no location left" instead of pointing at the
wrong image; for large videos the check can take a moment). Everything
else (renaming, final deletion)
deliberately happens there: fml itself never touches files. Note: the
window opens on the machine the server runs on - in normal localhost
operation that is your own.

## Loupe (full screen)

Space, or a click on the panel preview - the fast full screen for
browsing. Large medium (videos play, animated WEBPs animate), **`←`/`→`
pages** in grid order (neighbors are preloaded - built for fast review à
la Lightroom/IrfanView), `Home`/`End` jumps to the first/last medium,
`Space`/`Esc` closes - the overview afterwards sits on the last viewed
medium. Panel and gallery follow along while paging.

**🕸 Workflow view:** for ComfyUI media (videos too!) the image/workflow
toggle at the top switches to the embedded node graph - nodes with
titles, colors, widget values and connections; dragging pans, the mouse
wheel zooms. The third button **"Single view"** switches to the single
view in the same place. "Load as .json" downloads the **unmodified**
original workflow, which can be dropped straight back into ComfyUI. (The
preview only reads the stored workflow JSON - it needs no running ComfyUI
and does not break with ComfyUI updates.)

**A1111 images** get the same view: a minimal, real ComfyUI graph is
generated from the interpreted fields (checkpoint → LoRAs →
prompt/negative → KSampler → decode) - the bar honestly says "generated
from the A1111 infotext". The download loads directly into ComfyUI
(sampler names translated, file extensions are a guess); hires fix,
ADetailer & co. are deliberately not modeled by the graph - for those
there is **"Copy A1111 infotext"** in the detail panel.

## Curating (rating, tags, notes)

Everything manual is its own layer - strictly separated from what was
extracted from the files.

- **Selecting several:** **Shift-click** marks a range, **Ctrl/Cmd-click**
  adds or removes individual tiles. Rating, tags and model assignment
  then apply to the **whole selection** (the panel shows a note with the
  count).
- **Rating:** keys `1`–`5` on the selected medium (in overview and
  loupe), `0` clears, the same number again clears too (toggle). Or click
  the dots in the panel header / at the bottom of the loupe. Tiles show
  the stars as a small row of dots.
- **Assigning a model:** input field under CURATED (with suggestions from
  the collection) - for media without usable metadata (the
  Midjourney-screenshot era & co.). The manual model **overrides** the
  detected one in "By model" and all model filters; an empty field
  removes it again. The GENERATION section keeps showing unchanged what
  was extracted.
- **Tags:** type into the panel under CURATED and hit Enter - existing
  tags are suggested while typing (your vocabulary). ✕ on a tag detaches
  it from the medium; it stays in the vocabulary.
- **Notes:** free text in the panel; saves when leaving the field.
- **Rejecting (replaces deleting):** key **Del** on the selection (also
  multi-select). A dialog names the count and explains the consequences;
  after confirmation the medium disappears from the library (including
  rating/tags/notes) and its hash goes onto the **blocklist** - a
  re-import is prevented (visible outcome `_gesperrt/` in the source
  folder). **The file itself stays untouched**, whether it sits in the
  library or was only indexed - fml deletes and moves nothing when
  rejecting ("the original is sacred"). The view does not jump back to
  the top either: the scroll position stays put and the selection moves
  to the **successor** at the same position — so a seed series can be
  sorted through briskly with Del, Del, Del … The blocklist remembers the
  file's last locations. Unblocking: admin console → Issues → "View &
  clean up" → unblock; after another scan/import the medium is fully back
  (only the earlier curation is not).

## Bulk action: all hits at once (⚡)

For "narrow down this search, then tag/rate ALL hits" there is the
**⚡ Bulk action** button on the right of the header above the gallery
(next to "Reset filters"). It opens a dialog that shows what will be hit
(the chips + hit count) and offers five actions - whether 50 or 20,000
hits:

- **Base rating** (1-5 ★): fills **only unrated items** - existing
  ratings stay untouched. Nothing is destroyed.
- **Append tag:** all hits get the tag (whoever already has it is
  skipped - the summary honestly says how many).
- **Set model:** like the model assignment in the panel, just for all
  hits (overwrites an existing manual model).
- **Append note:** the text is **appended** to existing notes (new
  line), never overwritten.
- **Reject:** remove all hits from the catalog + block the hashes (like
  Del, see above - the files stay untouched). Deliberately also affects
  rated items and runs **alone**, not combined with other actions.

If a multi-select selection exists, the dialog asks whether the action
should apply to the **selection (N)** or to **all hits (M)**. Without
chips it honestly applies to the whole library - the number is displayed
large in the dialog. The apply button asks once more on the first click
("Really apply to …?"); the second click executes. Afterwards the dialog
shows a summary, and grid + sidebar refresh themselves.

## Saved searches

Any search - whether assembled from sidebar clicks, text terms or typed
expressions - can be stored with the **☆ next to the chips**. The ☆ opens
the **save dialog**: it shows the chips as a preview, the current hit
count, a note if a sort order will be stored along, and asks for the
name. The search appears on the left under "Saved searches" with a live
counter; a click loads it **back as chips** (everything stays editable).
If a saved search is loaded, the dialog becomes its maintenance:
**Overwrite** stores the edited state (a changed name renames it), **Save
as new search** creates a copy, **Delete** removes it (second click
confirms). The ✕ on the sidebar row still deletes directly. A sort order
given along (`sort:` or the sort button) is stored with the search and
restored on loading.

**For advanced users:** the search bar also understands filter
expressions - they immediately show the filtered grid. Predicates are
AND-combined, `-` negates; **several values in one predicate** are
separated by ` | ` (pipe with spaces) as OR:

```
model: flux -tag: wip rating>=4
model: flux | krea rating>=4
container: png -has: workflow
prompt: "red hair" rating=0
year: 2022 | unbekannt sort: created
```

`model: flux | krea` means flux OR krea; `-tag: wip | alt` means neither
`wip` nor `alt`. OR only exists for value predicates - comparisons
(`rating>=`, `width>=` …) form ranges via `>=`/`<=` pairs. The directive
**`sort: <key>`** (once per expression) sets the sort order and is stored
with the search: `added`, `created` (creation date), `size`, `name`,
`container`, `rating`. A suffix flips the direction: `sort: created-auf`
(oldest first), `sort: name-ab` (Z–A) - in English `-asc`/`-desc`
(`sort: created-asc`). Without a suffix the sensible default direction
applies (newest/largest/best first, names A–Z); unrated and undated items
stay at the end in both directions.

`field: value` searches as a substring, `field: "value"` exactly;
`rating=0` means unrated; the allowed fields are those of
[layer 2](interpretation.md) plus `tag:`, `container:`, `has:`
(`has: workflow` = embedded workflow, `has: model` = layer-2 field
present - **`-has: model`** finds media **without** a recognized model),
`format:` (rough aspect-ratio classes
`quadratisch`/`hochformat`/`querformat`/`widescreen` - in English
`square`/`portrait`/`landscape`/`widescreen`), `mp:` (megapixel ranges
`<1`/`1-2`/`2-4`/`>4`), `year:`/`month:` (creation date: `year: 2022`,
`month: 2022-07`, `year: unbekannt` - in English `year: unknown`),
`fundort:` (in English `location:`; `library` = at least one location
sits in the media library, `extern` - in English `external` - = only
indexed outside; needs a configured library), `text:` (free term -
curated search across interpreted fields, filenames and the manual
layer; exactly the live search's semantics: `text: ball text: desert`),
`raw:` (like `text:`, but **additionally in the raw metadata** - finds
e.g. node names in workflow JSON: `raw: ipadapter`), `datei:` (in
English `file:`; specifically the **filename** of the locations, without
directory - substring, exact with `"…"`; handy for metadata-less
collections like Midjourney exports, and of course usable in arena
expressions too) and the media metrics `width`/`height`/`fps` with
comparison (e.g. `width>=1920 fps>=24`). Saved searches are dynamic:
evaluated every time they are opened.

## Searching: ONE search state made of chips

The search is **one state made of chips** above the gallery - sidebar
clicks, text terms and typed expressions all land in the same state and
combine instead of replacing each other:

```
Library / [ Model: flux | krea ✕ ] [ Text: desert ✕ ] [ ★ ≥ 4 ✕ ] · 1,234   ☆ save · ✕ · ⚡
```

**☆ save**, **✕ Reset filters** and **⚡ Bulk action** sit as ONE button
group on the right; if the width is not enough, the group slides as a
whole below the chips. Below FullHD width, reset and bulk action show
only their icon (hover reveals the function) and the "Library /" prefix
is hidden - small monitors stay tidy.

- **Typing filters live:** from the third character on, the gallery
  filters after a short typing pause (the gallery IS the hit list -
  thumbnails instead of text snippets). **Enter** turns the terms into
  fixed **text chips** (`"…"` keeps word sequences together; a quote
  INSIDE a value is written doubled: `prompt: "say ""hi"""`); several
  words are AND-combined. Terms count as **word prefixes** (`des` finds
  "desert"; thanks to the full-text index in milliseconds even at 250k).
- **Sidebar clicks** become chips: a second value of the same group
  widens to an **OR**, a click on an active value removes it. The
  sidebar counters recalculate in the current context (empty values
  dimmed); "with/without input image" replace each other.
- **Typed filter expressions** (see above, Enter) are decomposed into
  chips - typed and clicked are guaranteed to be the same.
- **Clicking a chip** opens it for editing: remove or add values (OR),
  "exclude" turns the chip into a negation (neither-nor); ✕ on the chip
  removes the criterion. Everything at once: **"✕ Reset filters"** on
  the right of the header - or **Esc** (when no overlay is open) or "All
  media" in the sidebar.
- **☆ save** opens the save dialog (preview + hit count + name) and
  stores the whole state as a saved search; loaded searches can be
  overwritten, renamed, copied and deleted there.
- **"+ Criterion"** (next to the chips) opens the **builder**: all
  categories (model, LoRA, tags, rating, text, year, file type, format,
  resolution, input image, metrics, raw-data search, filename, sort
  order) with value lists and **counters in the current context**.
  Clicking several values = OR chip; "exclude" makes negative criteria;
  the raw-data search is the opt-in for hits in workflow JSONs (`raw:`).
- **Typing help:** while typing, the search box suggests matching facets
  ("Model: flux.1-dev (1,234)", "Tag: favorite (56)", …). ↑/↓ selects,
  **Enter takes the suggestion as a chip** - Enter without a selection
  makes text chips as usual. Learning the grammar is thereby optional.

The search is **curated**: across the interpreted fields (prompt, model,
seed, sampler, …), the **filename** (for metadata-poor sources like
Midjourney often the only thing describing the image) and **your manual
layer** (tags, notes, manual model - an assigned tag is findable
immediately). **Not** in the default search: negative prompts (whoever
searches "dog" does not want images that explicitly should NOT show a
dog - targeted: `negative_prompt: dog`) and the raw metadata/workflow
JSONs (opt-in: the **raw-data search** category in the "+ Criterion"
builder, or `raw: term`). For the manual layer: **`rating>=4`** (also
`<=`, `=`) finds by your stars, **`tag: xyz`** by your tags. The
**duplicates view** remains its own view outside the chips.

**Scrolling in filtered views is brisk** (ADR 0048): when a filter is
set, the hit list is built once (a brief moment for very large
collections); after that, deep scrolling and scrollbar jumps cost
practically nothing - no matter how deep. The server remembers the list
until something in the collection changes (import, rating, re-scan, …);
after that, the next access rebuilds it automatically. While an import is
running, the collection changes continuously - scrolling is then
temporarily as leisurely as it used to be, but always shows the fresh
state.

## Quick menu + admin console

The button top right opens the **quick menu**: a jump into the admin
console, the most frequent maintenance actions (re-scan, re-interpret,
clear thumbnail cache) and the theme switch - without leaving the
library. Esc or a click beside it closes.

The **admin console** (from the quick menu or via the activity
indicator) is ONE page with regions:

1. **Overview:** the collection's key figures (items, metadata, thumbnail
   cache, DB size, parsers, ffprobe/ffmpeg) and next to them the
   **Activity** of the running task with live progress.
2. **Sources & import:** ONE ingest form (folder + mode
   copy / move / catalog + "once now" / "watch permanently") and the
   list of watch folders.
3. **Maintenance:** small buttons by functional area - re-scan, orphaned
   locations, thumbnails, integrity check, VACUUM, re-interpret,
   backfill creation dates, rebuild search index.
4. **Issues:** summary with an overlay for acknowledging (grouped by
   error kind, honest numbers); the blocklist lives there too (unblock
   rejected media).
5. **Configuration:** media library (takes effect immediately), oldest
   plausible date, thumbnail size (creates `config.toml.bak`; the
   commented reference is `config.example.toml`).

Details: [admin.md](admin.md). "Back to the library" top left (or `Esc`)
closes the console. After finished tasks, gallery and counters refresh by
themselves.

## Keyboard

| Key | Effect |
| --- | --- |
| `Space` | open/close the loupe |
| `Enter` / double-click | open/close the single view |
| `+` / `-` | zoom (single view) |
| `1`–`5` / `0` | rate / clear rating (toggle) |
| `←` / `→` | page - in overview and loupe |
| `↑` / `↓` | one row up/down (overview) |
| `Del` | reject the selection (item out + block, file stays) |
| `Home` / `End` | first/last medium (loupe) |
| `Esc` | close the open overlay (loupe, dialogs, admin) - otherwise: **Reset filters** |

## Important / limits (as of now)

- **"Catalog only" copies nothing.** This mode records files where they
  are. The import (copying into the date-based media library, with
  duplicate check and watch folders) is the path next to it - see
  [import.md](import.md).
- **Video metadata needs ffprobe** (part of ffmpeg, see
  [extraction.md](extraction.md)). Without ffprobe, videos are still
  cataloged; a re-scan after installing it fetches the metadata.
- **TIFF and PSD** are not displayed natively by any browser — gallery,
  loupe and single view render a JPEG server-side for them (the original
  stays untouched). PSD uses the embedded composite. PSDs saved
  **without "maximize compatibility"** carry no composite (only the
  layers) — they honestly show "No preview available" instead of a wrong
  white image. To see them, re-save them once in Photoshop with
  "maximize compatibility". **PDF** is only cataloged (no extractor,
  ADR 0051).
- **Meant for you only:** the server binds to `localhost` by default and
  has no access control - do not expose it to the network unprotected.
- **Only ever one writer:** do not let the GUI and a CLI scan loose on
  the same DB at the same time (ADR 0007).
