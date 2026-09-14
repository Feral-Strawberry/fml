# The interface (local web GUI)

> What is this? The local web interface of the Feral Media Library (fml):
> browse and search the collection, read metadata, scan/watch folders and
> do the maintenance - all without a command line. Three-column layout,
> dark theme (switchable to light).

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
the **density S/M/L** (the bar below the search belongs to the chips), activity
indicator (pulses while a scan/maintenance runs - a link to the admin
page), **dark/light switch** (moon/sun; the same choice applies in the
admin), admin button (a real link to `/admin`: click opens the admin,
middle-click the admin in a second tab). If an
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
languages (ADR 0054). The search grammar additionally
understands **English aliases** for its German remnants: `file:` =
`datei:`, `location:` = `fundort:`, `portrait`/`square`/`landscape` =
`hochformat`/`quadratisch`/`querformat`, `-asc`/`-desc` = `-auf`/`-ab`,
`external` = `extern` and `unknown` = `unbekannt`. Both spellings are
always understood, whatever language is set; **canonical** (in chips,
saved searches and serialized expressions) remains the existing spelling
— saved smart folders stay valid untouched. All
**server-generated texts** follow the UI language as well: activity
labels and progress in the admin console, result summaries ("Import: 3
new · 2 duplicates"), error messages of the search grammar and all other
server errors. The only exception: scan issues recorded BEFORE that
update appear unchanged in their old (German) wording - new entries are
stored language-neutrally and translated on display.

**Left - sources:** "All media", **Duplicates** (items that sit at
several paths on disk - the panel shows all locations), your **saved
searches**, the **Rating** group (exactly n stars - also for finding
poorly rated media on purpose), **Generator** (the platform the file was
created on: ComfyUI, A1111, Midjourney, Google, OpenAI, Adobe, Topaz - from
the embedded metadata or Content Credentials, see
[interpretation](interpretation.md#generator-detection-gemini-chatgpt-firefly--co-c2paxmp);
chip `tool: google`, equivalently `generator: google`; a click makes the
model list below count in context), **By model** - including **"(unknown
model)"** for media without an interpreted model field (Midjourney,
Gemini, ChatGPT, …); WAN 2.2 two-stage checkpoints (high/low noise)
appear as ONE entry, the tooltip names both raw names and clicking
filters on both -, **By year** (creation date; the caret before the year
unfolds the months - legacy collections get their date via "Re-scan all
locations"), **By LoRA** (the LoRAs used during generation, most used first;
in the long lists Generator, Model and LoRA, rows with hits sit on top while
rows empty in context are dimmed below a divider "no hits with this filter · 106 models" - without an active chip that divider does not appear), **By file type** (PNG, WEBP, video containers, …), **By format**
(rough aspect-ratio classes: portrait / square / landscape / widescreen -
for troubleshooting after an import), **By resolution** (megapixel
ranges: under 1 / 1-2 / 2-4 / over 4 MP), **Input image** (with/without -
finds img2img and image-to-video results) and **Location** ("in the
library" = at least one copy sits in the media library, "external only" =
only cataloged in place, e.g. via `catalog` from external drives; the group
only appears when a media library is configured). A click puts a **chip**
into the search bar above the gallery (see "Searching").

**Click rule as in Lightroom (changed in September 2026 - please read if
you have been using fml for a while):**

- **Click** a value to select it - clicking a **different value of the
  same group replaces** the selection (switch from "Google" to "OpenAI"
  without deselecting first).
- **Cmd-click (Mac) or Ctrl-click (Windows/Linux)** **adds** and widens
  the chip to an **OR** ("flux OR krea").
- **Click the active (highlighted) value** to remove it again.

Until then a plain click already widened to an OR. If you want the OR,
hold the key now - or type it into the search bar (`tool: google |
openai`). The "+ criterion" popover and the typing help still add. The
hint also sits as a tooltip on every group heading and every row - with
the key of your system (⌘ on the Mac, Ctrl otherwise). And the first time
a click replaces an existing selection, a short line appears below the
group: "Selection replaced · ⌘-click adds (OR)" - at most three times,
then the rule is learned.

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
everything cataloged, external included).

**Center - gallery:** virtualized grid (fluid even with very large
collections - only visible tiles are in memory), newest first. On top: a
breadcrumb with the search chips and the counter; anchored to its right
**✕ Reset filters** (appears as soon as filtering is active - **Esc**
also clears the filters when no overlay is open) and **⚡ Bulk action**.
If a medium was selected when the filter or sort order changed and it is
also part of the new result list, the gallery **jumps back to it**
instead of starting at the top - Esc out of the seed-variant search thus
leads straight back to the last clicked image. The one exception is a
click on **"All media"** in the sidebar: that is the reset key, afterwards
the gallery sits at the top with nothing selected.
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
the working view with real zoom: steps **fit / max 100 % / 50 / 100 / 200 %**, the
**mouse wheel** zooms continuously, **double-click in the image** jumps
between fit and 100 %, dragging pans. The percentages mean **real
pixels**: at 100 % one image pixel equals one screen pixel - regardless
of OS scaling (Windows 150 %, Retina Macs) and browser zoom. That makes
100 % pixel-sharp everywhere and the reliable step for judging details
and artifacts. The **last step chosen in the zoom bar is remembered**
and applies to every further image (if you always want 100 %, pick it
once). **max 100 %** is the everyday mode for mixed collections: real
size, but at most screen-filling - a small image stands pixel-sharp at
100 %, a large portrait image is shrunk as with "fit" instead of running
off the bottom. Mouse wheel and double-click produce image-dependent in-between
values and deliberately do not change the remembered step. On the right sits the complete
metadata panel in wide form - rating (also keys 1-5), tags, model and
notes work the same here; more tools will come mid-term (metadata
editing, push-to-ComfyUI). **←/→** pages in grid order; **Esc, Enter or
✕** lead back to the gallery, which stays on the last viewed image.

**📂 Show in file manager** (top right, also in the loupe): opens
Explorer (Windows) or Finder (macOS) with the file selected. If the file
exists at several locations, a fixed order applies: **library before
watch source before other places**, and only locations where the file is
still present with the right size. The **Locations** panel (below) shows
which one that is. The content is **verified via SHA-256** before opening
(if a different file now sits at the catalogued path, the button honestly
reports "no location left" instead of pointing at the wrong image) - for
files above 64 MB the hashing is skipped and only the size check counts,
so the button no longer hangs for minutes on large videos. While the
server checks, the button shows ⏳; if Explorer cannot select the file
(Windows path over 259 characters), fml opens just the folder and says so
(📁 + hint). Everything else (renaming, final deletion)
deliberately happens there: fml itself never touches files. Note: the
window opens on the machine the server runs on - in normal localhost
operation that is your own.

**Locations** (panel, collapsible): every path where fml knows the file,
in the same order the 📂 button uses. Each row carries an origin tag -
**Library** (under the library root), **Source** (under a watch source,
typically "catalogue") or **external** - and the location that "Show in
file manager" opens is marked with 📂. If the file is gone there, the row
says "(missing)"; if a different file now sits at the path (size does not
match), "(different file at this path)".

Every path is a **breadcrumb**: clicking a folder segment opens exactly
that folder in the file manager - **without** selecting the file,
deliberately unlike the 📂 button top right. Clicking the **file name**
(bold) opens the file with the application the system associates with
that type (Photoshop, VLC, …). That also gets you to a second location,
for instance to clean up duplicates in the file system yourself without
fml managing that folder. Segments are underlined only on hover; an error
(folder gone, file gone) shows for four seconds on the row. fml touches
nothing here - what the opened application does with the file afterwards
is your call there. Since the panel is the same in gallery and single
view, this works in both places.

## A/B compare (blend two images)

Variants from edit workflows often differ only in small things (a
finger, an edge, an artifact) - side by side you hardly see it. The
compare view puts **two selected images exactly on top of each other**
and reveals B with a **wipe edge**, like in ComfyUI edit workflows.

**Open:** select exactly two media (Ctrl/Cmd-click or Shift-click), then
**key `C`** or the button **⇆ Compare** in the gallery header (it only
appears with exactly two selected media). The first selected image is
**A** (left), the second is **B** (right).

- **Wipe edge:** drag anywhere in the image with the mouse or a finger;
  **`←`/`→`** move it in small steps (coarse with Shift), **`Home`/`End`**
  all the way left/right.
- **Space** (or the button at the top right) cycles three ways: **wipe →
  A only → B only → wipe**. "A only"/"B only" show one image in full -
  that gives the blink comparison where even tiny differences "jump".
  **Tab** swaps A and B (and with it the rating target).
- **Zoom** as in the single view: fit / max 100 % / 50 / 100 / 200 %, mouse wheel,
  `+`/`-`, double-click jumps between fit and 100 %. The percentages mean
  real pixels, and the remembered zoom step is the same one. When zoomed
  in, scroll with the scrollbars.
- **Decide:** above the image each side shows name, dimensions and the
  **rating dots**, plus **Reject** (item out + block, the file stays
  untouched). The keys **`1`-`5`/`0`** and **`Del`** act on **A** - use
  Tab to bring the other image to A. After rejecting, the compare view
  closes.
- **Different dimensions:** both images are matched to the width of A,
  and the hint "Dimensions differ" appears at the top right.
- **Esc, Enter or ✕** lead back to the gallery; the two-item selection
  stays.

First version **for images only**: if a video is among the two, the
compare view opens with a note instead of the images (frame-synchronous
comparison comes later).

## Loupe (full screen)

Space, or a click on the panel preview - the fast full screen for
browsing. Large medium (videos play, animated WEBPs animate), **`←`/`→`
pages** in grid order (neighbors are preloaded - built for fast review à
la Lightroom/IrfanView), `Home`/`End` jumps to the first/last medium,
`Space`/`Esc` closes - the overview afterwards sits on the last viewed
medium. Panel and gallery follow along while paging.

**🕸 Workflow view:** for ComfyUI media (videos too!) the image/workflow
toggle at the top switches to the embedded node graph. Since September
2026 it looks like ComfyUI itself: grid, node colors from the workflow,
**slot and link colors by data type** (MODEL purple, CLIP yellow,
CONDITIONING orange, LATENT pink, IMAGE blue, VAE red), **widgets as
pills with name and value** (`seed 123456789`, `steps 20`, `cfg 1`,
`sampler_name euler`), prompts as text boxes, groups with title bars,
**muted nodes dimmed, bypass magenta**, collapsed nodes as title bars,
and **subgraphs as boxes** ("⧉ 2 nodes · click to open") - a click shows
the inside with inputs and outputs, "‹ back" goes up. Dragging pans, the
mouse wheel zooms. The third button **"Single view"** switches to the
single view in the same place. "Load as .json" downloads the
**unmodified** original workflow, which can be dropped straight back into
ComfyUI. (The preview only reads the stored workflow JSON - it needs no
running ComfyUI and does not break with ComfyUI updates.)

*Widget names:* ComfyUI stores widget values without names. fml knows the
names of the core nodes (KSampler, loaders, encoders, latents, video, …)
and reads them straight from newer workflows when present
(`widgets_values_named`). For custom nodes a small tool fetches the names
from your own ComfyUI installation - run it once while ComfyUI is running,
after that the preview labels those nodes too:

```bash
python tools/dump_object_info.py            # ComfyUI at http://127.0.0.1:8188
python tools/dump_object_info.py --url http://192.168.1.20:8188
```

The result sits as `widgets.json` next to the UI and is pure information
about your installation (not code, not in the repo). Values with no known
name stay bare in the pill - never guessed.

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
  library or was only cataloged in place - fml deletes and moves nothing when
  rejecting ("the original is sacred"). The view does not jump back to
  the top either: the scroll position stays put and the selection moves
  to the **successor** at the same position — so a seed series can be
  sorted through briskly with Del, Del, Del … The blocklist remembers the
  file's last locations. Unblocking: admin → Issues → block list
  (searchable, paged) → unblock; after another scan/import the medium is fully back
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

## Search, saved search, ranking: one idea

Everything in fml starts with a **search decision**: which media do I
want to see right now? Three things build on each other, in this order:

1. **The search** is ONE state made of **chips** above the gallery.
   Sidebar clicks, typed terms and filter expressions all land in these
   chips; the gallery always shows exactly what the chips say.
2. **A saved search** is this state **with a name**. A click in the
   sidebar loads the chips back, you see the images and can keep
   changing the chips. The ☆ saves: a new search or, if you came from a
   saved search, either **"overwrite »name«"** or **"save as new
   search"**.
3. **A ranking** is a saved search **that duels run over** (ranking
   module, off by default). 🏆 creates it from the current chips; ✎ in
   the ranking loads its population as chips into the gallery (**edit
   mode**), "Save ranking" leads back into the ranking. A ranking has two
   views: the **leaderboard** and the **duel mode**.

Terms: a criterion in the bar is a **chip**; a named search is a **saved
search**; a named search with duels is a **ranking** (no longer
"arena"), its two views **leaderboard** and **duel**. The sections below
follow this order; the rankings in detail are described in
[rankings.md](rankings.md).

## Searching: ONE search state made of chips

The search is **one state made of chips** above the gallery - sidebar
clicks, text terms and typed expressions all land in the same state and
combine instead of replacing each other:

```
[ Model: flux | krea ✕ ] [ Text: desert ✕ ] [ ★ ≥ 4 ✕ ] · 1,234   ☆ save · 🏆 Ranking · ✕ · ⚡
```

**☆ save**, **✕ Reset filters** and **⚡ Bulk action** sit as ONE button
group on the right; if the width is not enough, the group slides as a
whole below the chips. Below FullHD width, reset and bulk action show
only their icon (hover reveals the function) - small monitors stay tidy.
In a ranking's edit mode (see [Rankings](rankings.md)) all four buttons
show only their icon.

- **Typing filters live:** from the third character on, the gallery
  filters after a short typing pause (the gallery IS the hit list -
  thumbnails instead of text snippets). **Enter** turns the terms into
  fixed **text chips** (`"…"` keeps word sequences together; a quote
  INSIDE a value is written doubled: `prompt: "say ""hi"""`, likewise the
  apostrophe in `'…'`: `prompt: 'don''t stop'`); several words are
  AND-combined. The chip editor and the typing help understand `"…"`
  (exact) and `'…'` (contains) as well. Terms count as **word prefixes** (`des` finds
  "desert"; thanks to the full-text index in milliseconds even at 250k).
- **Sidebar clicks** become chips: a click **replaces** the group's
  selection, Cmd/Ctrl-click widens to an **OR**, a click on an active
  value removes it (Lightroom rule, since September 2026). The
  sidebar counters recalculate in the current context (empty values
  dimmed); "with/without input image" replace each other. All counters
  of a search state come from **one** run, and the server remembers the
  result until the collection changes - the second click on the same
  saved search costs nothing.
- **Typed filter expressions** (see above, Enter) are decomposed into
  chips - typed and clicked are guaranteed to be the same.
- **Clicking a chip** opens it for editing: remove or add values (OR),
  "exclude" turns the chip into a negation (neither-nor); ✕ on the chip
  removes the criterion. Everything at once: **"✕ Reset filters"** on
  the right of the header - or **Esc** (when no overlay is open) or "All
  media" in the sidebar.
- **☆ save** opens the save dialog (preview + hit count + name) and
  stores the whole state as a saved search; if the state came from a saved
  search, it offers "Overwrite »Name«" and "Save as new search".
- **🏆 Ranking** (only with the ranking module enabled, also without chips)
  creates a **new ranking** from the chips (pairwise comparison with
  leaderboard), see [Rankings](rankings.md).
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

## Filter expressions (for advanced users)

The search bar also understands filter
expressions - they immediately show the filtered grid. Predicates are
AND-combined, `-` negates; **several values in one predicate** are
separated by ` | ` (pipe with spaces) as OR:

```
model: flux -tag: wip rating>=4
model: flux | krea rating>=4
container: png -has: workflow
prompt: "red hair" rating=0
prompt: 'new york' -prompt: 'at night'
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

`field: value` searches as a substring, `field: "value"` exactly,
`field: 'two words'` as a **multi-word substring** ("contains":
`prompt: 'new york'` also finds "a view of New York at night",
`prompt: "new york"` only a prompt that reads exactly that);
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
cataloged outside; needs a configured library), `text:` (free term -
curated search across interpreted fields, filenames and the manual
layer; exactly the live search's semantics: `text: ball text: desert`),
`raw:` (like `text:`, but **additionally in the raw metadata** - finds
e.g. node names in workflow JSON: `raw: ipadapter`), `datei:` (in
English `file:`; specifically the **filename** of the locations, without
directory - substring, exact with `"…"`; handy for metadata-less
collections like Midjourney exports, and of course usable in ranking
expressions too) and the media metrics `width`/`height`/`fps` with
comparison (e.g. `width>=1920 fps>=24`). Saved searches are dynamic:
evaluated every time they are opened.

## Saved searches

Any search - whether assembled from sidebar clicks, text terms or typed
expressions - can be stored with the **☆ next to the chips**. The ☆ opens
the **save dialog**: it shows the chips as a preview, the current hit
count, a note if a sort order will be stored along, and asks for the
name. The search appears on the left under "Saved searches" with a live
counter; a click loads it **back as chips** (everything stays editable)
and shows its media, with no further mode. The list appears immediately,
the counters follow shortly after ("…" while they are being computed):
after a server start or an import they are counted once fresh, afterwards
they come from memory until the collection changes.

As long as the chips match the loaded search exactly, its row in the
sidebar is highlighted. Change a chip and the highlight goes off: from then
on it is a free search, nothing gets overwritten unnoticed. Press ☆ then
and the dialog says **"From the saved search »Name«"**, the name is
prefilled, and there are two clearly named ways:

- **Overwrite »Name«** stores the current chips as the new version of this
  search; a changed name renames it along the way.
- **Save as new search** creates a second search and leaves the old one as
  it was.

The origin ends with "All media", Esc, clearing the chips or loading
another search. Deleting happens via the ✕ on the sidebar row (second
click confirms). A sort order given along (`sort:` or the sort button) is
stored with the search and restored on loading.

## Rankings: a saved search with duels

With the ranking module enabled (Admin → Configuration → Modules) the
chip bar shows **🏆 Ranking**: it creates a new ranking from the current
chips (without chips: the whole library) and opens it. In the sidebar,
rankings appear in the group **Rankings** with their population as the
counter; a click opens the leaderboard. ✎ in the ranking loads the
population into the gallery, the header switches to edit mode, "Save
ranking" leads back. Everything else (leaderboard, duel mode, "Both
out", Elo scores): [rankings.md](rankings.md).

## Admin

The button top right leads straight into the **admin** (a real link to
`/admin`: bookmarks, middle-click and right-click → new tab). The former
quick menu with maintenance actions is gone; re-scan, re-interpret and
clear thumbnail cache live under Admin → Maintenance, dark/light sits as a
moon/sun button next to the language switch.

Since ADR 0074 the **admin** is a **page of its own** under `/admin` with a
side navigation on the left (Overview, Configuration, Sources & import,
Maintenance, Issues, Rankings, Logs) and the activity widget at the
bottom of the navigation - on every page you see what is running or
waiting. Every page has an address (`/admin/logs` …), browser back and
forward work; "Back to the library" is an ordinary page change (the
gallery comes from the browser's history cache or starts fresh). Gallery
and admin may run side by side in two tabs; the gallery refreshes key
figures, read-only badge and instance name as soon as its tab becomes
visible again.

Details: [admin.md](admin.md). After finished tasks, gallery and counters
refresh by themselves - gently: tiles stay in place, new images (e.g. from
a watch folder next to ComfyUI) slide in at the top and push the rest,
scroll position and selection stay on the image. Only tiles whose content
changed are refilled.

## Keyboard

| Key | Effect |
| --- | --- |
| `Space` | open/close the loupe |
| `Enter` / double-click | open/close the single view |
| `C` | open the A/B compare view for two selected images |
| `+` / `-` | zoom (single view, compare) |
| `1`–`5` / `0` | rate / clear rating (toggle) |
| `←` / `→` | page - in overview and loupe; wipe edge in compare |
| `↑` / `↓` | one row up/down (overview) |
| `Del` | reject the selection (item out + block, file stays) |
| `Home` / `End` | first/last medium (loupe); wipe edge fully left/right (compare) |
| `Tab` / `Space` | compare: swap A and B / wipe → A only → B only |
| `Esc` | close the topmost dialog, else the open overlay (loupe, single view) - otherwise: **Reset filters** |

### Dialogs and hanging requests

Dialogs (ranking, save, bulk action, reject - in the admin only folder
picker and confirmation) may stack: the folder picker opens on top of the
page or a confirmation, and cancelling keeps what you had typed. `Esc` always
closes only the topmost dialog. Switching the view (loupe, single view,
compare, ranking opening or closing) closes all open dialogs of the gallery;
the admin, being its own page, has its own dialog stack.

Read requests to the server (gallery pages, details, counters) time out
after 60 seconds, thumbnails after 20 seconds, and report that as a
normal error; gallery pages and thumbnails retry on their own afterwards.
Writing actions (import, maintenance, move-out) have no time limit. A
video the browser cannot open shows "No preview available" in the loupe,
single view and panel instead of a black area. If fml knows the codec
(layer 2, field `video_codec`), the player asks the browser BEFORE
loading: for ProRes, 10-bit H.264 or HEVC in Firefox the poster frame
appears with "This browser cannot play ProRes (HQ, 10-bit) …" — no stream,
no black player with audio only. The codec is also shown in the header of
panel, loupe and single view; `codec: prores` in the search field finds all
affected files ([interpretation.md](interpretation.md#video-codec-and-playability)).

## Important / limits (as of now)

- **"Catalog only" copies nothing.** This mode records files where they
  are. The import (copying into the date-based media library, with
  duplicate check and watch folders) is the path next to it - see
  [import.md](import.md).
- **Video metadata needs ffprobe** (part of ffmpeg, see
  [extraction.md](extraction.md)). Without ffprobe, videos are still
  cataloged; a re-scan after installing it fetches the metadata.
- **Which videos the browser plays:** fml serves videos unchanged (no
  transcoding, "originals are sacred"); whether a codec plays is therefore
  decided by the **browser**, not by fml. The player asks it before loading
  and, if the answer is no, shows the poster frame with a note. As of 2026
  (browsers change; when in doubt the browser's answer wins):

  | Codec / container | Chrome, Edge | Firefox | Safari (macOS) |
  |---|---|---|---|
  | H.264 8-bit 4:2:0 (MP4, MOV) | yes | yes | yes |
  | H.264 10-bit, 4:2:2, 4:4:4 (High 10 & co.) | no | no | no |
  | HEVC / H.265 | with hardware decoder | depends on the system (Windows: "HEVC Video Extensions", macOS: recent versions, Linux: no) | yes |
  | VP8 / VP9 (WebM) | yes | yes | yes (macOS 11+) |
  | AV1 | yes | yes | only recent Apple chips |
  | **ProRes (MOV, Topaz export)** | no | no | **yes** |
  | DNxHD, Motion JPEG, other intermediate codecs | no | no | no |
  | MKV container | partially | no | no |

  Mac users on Safari are therefore not affected by the ProRes problem; in
  Chrome and Firefox only another player (📂 show in file manager) or an
  H.264 export helps. Which codecs are in your own catalog is shown by
  `codec: prores` in the search field or the
  [diagnostic command](scanning.md#diagnostics-video-codecs-in-the-catalog);
  on ingest the issue appears under Admin → Issues (kind `playback`).
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
