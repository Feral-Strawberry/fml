# Audio module

fml can catalog music and other audio files: with all embedded metadata,
their duration and a dedicated player. The module is **off by default**; if
you only manage images and videos, nothing changes for you.

What the module does, in the order of this page: a dedicated **audio
view** as a list with a three-colour waveform, a **player** with loudness
matching, "Play all" and a playback bar, **time comments** at points in a
song, **comparing** two to six versions, and **covers** that bring
finished songs into the gallery. On top of that fml reads the metadata of
Suno, ComfyUI music and your own recordings, measures loudness and
waveform, and also searches the lyrics.

**Needs ffmpeg** (like videos, installation see README): ffprobe provides
the duration, ffmpeg measures loudness and waveform, creates playable
copies and reads the lyrics with timings from the subtitle track. Without
ffmpeg, MP3, FLAC, Ogg, WAV, AIFF and CAF are still cataloged with all
their tags. **M4A and Matroska with sound only** are read entirely via
ffprobe: without ffprobe the tags are missing there, and the file counts
as video until a re-scan with ffmpeg installed catches up on it.

## Turning it on

**Admin → Configuration → Modules → Audio module** ("catalog audio") or in
`config.toml`:

```toml
[audio]
enabled = true
```

The setting takes effect immediately for the next scan and import. When
it is switched on, watch folders re-check audio files they skipped
earlier as "unknown format". Folders that were only cataloged **once**
you add once more (**Admin → Sources & import**, "catalog only", "once
now"): what is known is skipped, the music is added. "Re-scan all
locations" is not enough for that, it only checks files that are already
in the catalog.

**Off** means: audio files count as unknown format and are not cataloged,
exactly as without the module. This also applies to M4A files and
Matroska files with only an audio track, which used to show up wrongly as
video. Audio items that are already cataloged stay in the catalog but are
invisible: the gallery then shows no audio, not even songs with a cover,
and the switch to the audio view only exists with the module. Switch it
back on and everything is there.

## Audio view

With the module on, the switch **▦ Gallery | ♪ Audio** sits at the top
left next to the logo. Both views share the search: the chips stay when
you switch, only the **base scope** changes. `tag: regenzeit` shows the
images in the gallery and the matching songs in the audio view. The one
exception is the **media type**: it always applies within the view.
Values that do not exist in the new view are dropped on switching
("Image" disappears when switching to audio). "Audio" stays when
switching to the gallery and shows the finished songs with a cover there.

- **Gallery** = images, videos and **finished songs**: songs with a cover
  (see [Cover](#cover-finished-songs-in-the-gallery)).
- **Audio** = all audio items, as a **full-width list**.

A chip never switches the view. With `type: audio` in the gallery, it
shows only the finished songs (with a cover); if there are none, it stays
empty and says "Audio lives in the audio view" with a button to switch (the same the other way round for images in the audio view).
Typing "audio" into the gallery's search box, the typing help offers **→
Audio view**: Enter switches the view, the search stays as it was. The
browser remembers the chosen view.

**A row** shows ▶, the **file name** (Suno puts comments into the song
title and thus into the file name), **artist · album** from the tags,
for AI music without these tags the generator (model, otherwise tool),
the duration, the loudness (LUFS), the rating and under 💬 the number of
time comments. If a song has a cover, it sits small in front of the name.
If a name starts like the one above it, the shared beginning is dimmed:
with "Regenzeit v3 refrain lauter" and "Regenzeit v3 refrain leiser" the
difference stands out. The full name is in the tooltip. When the middle
is narrow (small window, sidebar and detail panel open), generator and
loudness give way so the name has room.

Below each row lies the **waveform in three colours**, explained in the
legend above the list (the tooltip says more):

| Colour | Band | What you hear there |
|---|---|---|
| Blue | bass, below 200 Hz | kick, bassline |
| Green | mids, 200 Hz to 2 kHz | voice, guitar, piano, pads |
| Light | highs, above 2 kHz | cymbals, hi-hats, sibilants |

Each band is drawn at its own strength, the height is the level. Where a
colour stands out, that range dominates: lots of blue means bass and kick
push (typically a chorus or drop), wide green means vocals and harmony up
front (verse, bridge), lots of light a bright, airy or hissing passage. If
a version sounds dull or harsh, the share of light often shows it already.
All rows share **one time axis**: the full width is the longest song in
the list, a shorter song ends correspondingly earlier. The ruler above
the list shows the minutes. This way the choruses of different versions
line up visibly. The part already played is bright, the red line is the
row's **playhead**. A click into the waveform plays the row from that
spot.

**Controls:**

| Key / mouse | Effect |
|---|---|
| ↑ / ↓ | change row |
| Alt+↑ / Alt+↓ | move the row one place (sort "Manual" only, see [Your own order](#your-own-order-of-a-saved-search)) |
| Space, ▶, double-click | play / pause (Space also right after clicking a button such as ⏮ or ≈ Loudness) |
| ← / → | move the row's playhead 5 seconds back / forward (with Shift 1 second) |
| click into the waveform | play from that spot |
| K | time comment at the row's playhead |
| click on a comment pin ▲ | play from the comment |
| 1 to 5, 0 | set / remove stars (also by clicking the row's dots) |
| Delete | reject |
| Shift/⌘ or Ctrl click | select several rows, as in the gallery |
| C | compare the marked songs (2 to 6, see "Comparing") |
| Esc | while comparing: back to the full list |

Always **exactly one** row plays, but **every row has its own playhead**.
Starting another pauses the first; it remembers its position, the next ▶
continues there. This way four versions can be heard chorus against
chorus: set each one to its chorus once, then ▶ in turn. The arrow keys
move the playhead of the selected row even while it is not playing.
S/M/L at the top of the header changes the row height.

**▶ Play all** (top right in the audio view) plays the whole list in the
current sort order, every song from the start, like a CD. The order is
**frozen** when playback starts: searching or re-sorting afterwards does
not change the running "CD". Starting a song in between that does not
belong to it ends "Play all"; one from the sequence continues it there.

The **sidebar** counts per view: "All media", saved searches, models,
years and all other groups count only audio in the audio view, only
images and videos in the gallery. Groups that make no sense for the view
disappear (LoRA, aspect, resolution, input image, rankings in the audio
view; media type would have only one row there). Songs never belong to a
[ranking](rankings.md), not even with a cover: for comparing and rating
there are dedicated tools here. New in the audio view is
the group **Lyrics**: "with lyrics" (`has: lyrics`) and "without lyrics"
(`-has: lyrics`). It only tells whether lyrics are stored in the file, not
whether anyone sings: many songs with vocals carry no lyrics. The "+ Criterion" popover also shows only the fitting
categories. A **bulk action** on the search result hits exactly what the
view shows.

The detail panel on the right shows the selected song's metadata, lyrics
and raw data as usual.

## Which formats

| Format | Detection | What is read |
|---|---|---|
| MP3 | ID3v2 tag or MPEG frame at the start | ID3v2 (2.2 to 2.4), APEv2 and ID3v1 at the end |
| FLAC | `fLaC`, also with ID3v2 in front | Vorbis comment, pictures, APPLICATION blocks, the leading ID3v2 |
| Ogg (Opus, Vorbis, FLAC) | `OggS` | Vorbis comment or OpusTags, also across several pages |
| WAV (also RF64/BW64) | `RIFF`/`RF64`/`BW64` + `WAVE` | `LIST/INFO`, `bext`, `iXML`, `_PMX`, `id3 `, `C2PA`, `cue` and more, also after the audio data |
| AIFF/AIFC | `FORM` + `AIFF`/`AIFC` | `NAME`, `AUTH`, `ANNO`, `COMT`, `APPL`, `ID3 ` and more |
| CAF (e.g. Logic bounce) | `caff` | `info` chunk, other chunks raw |
| M4A, MKA/WEBM with audio only | like video, but without a video track | tags via ffprobe |

The media type comes from the **actual tracks**, not from the extension
or the container: an MP4 with a picture track is video, an MP4 with sound
only is audio. An embedded cover does not count as a picture track.

## What is stored

Every tag frame and every chunk is stored **unchanged** as its own raw
metadata entry (layer 1), in file order, including duplicate keys. The
detail panel shows them under "Raw metadata" with their origin, for example:

| Source · key | Meaning |
|---|---|
| `id3v2:TXXX · prompt` | user-defined text, here a ComfyUI prompt |
| `id3v2:COMM · eng:` | comment (language `eng`, empty description) |
| `id3v2:USLT · eng:` | lyrics |
| `id3v2:TIT2` | title |
| `id3v2:GEOB · application/c2pa` | embedded object, here a C2PA manifest (byte-exact) |
| `flac:comment · prompt` | Vorbis comment (the key keeps its spelling) |
| `ogg:comment · TITLE` | comment in Ogg/Opus |
| `riff:INFO · ICMT` | WAV comment |
| `aiff:NAME`, `caf:info · title` | title in AIFF or CAF |

**Pictures** (covers in ID3, FLAC, Ogg, APEv2) are not stored as bytes,
only described: MIME type, picture type, size and SHA-256. The pictures
stay in the file.

On top come the **technical facts** from ffprobe: duration, codec, sample
rate, channels, bit depth and bit rate (source e.g. `mp3:format`,
`mp3:stream0`). Without ffprobe the tags are still read; only the
duration is missing then (exception: M4A and Matroska, see above).

## What fml reads from music

fml turns the raw data into searchable fields (layer 2). This runs during
the scan, and for files already cataloged via **Admin → Maintenance →
Re-interpret**, without re-import.

**From every music file:** title (`title`), lyrics (`lyrics`), tempo
(`bpm`), key (`key`) from the usual tags (ID3, Vorbis comment, WAV INFO,
M4A), plus the technical data of the audio track: `audio_codec`,
`sample_rate`, `channels`, `bit_depth`. The **lyrics are part of the
full-text search**: typing one line of them into the search field finds
every version of a song that carries the same text.

**Timed lyrics:** songs from Suno V6 carry their lyrics line by line with
times in a subtitle track, including sections such as `[Verse]` or
`[Chorus]`. fml reads this track (M4A, audio-only Matroska), as well as
ID3 `SYLT` (in milliseconds) and LRC text (`[01:23.45]line`) in the lyrics
tag; LRC in the tag becomes plain lyrics without time stamps. It shows in
three places:

- **Centred below the waveform of the playback bar**, the line
  currently playing is shown in small print, with its section in front ("Chorus · Sing it
  loud"). During passages without vocals (solo, bridge) it stays empty:
  a line is shown at most about as long as it takes to sing it and
  disappears as soon as a new section begins. With very fast, multi-voice
  singing the track itself is already jumbled; fml then shows it as it
  comes.
- **On the waveform of every list row**, narrow labels mark the sections;
  when two lie close together, the first is shortened (full name in the
  tooltip). The section the playhead is in appears in full and in the
  accent colour. Instrumental sections (solo, lead guitar, intro) have no
  time of their own at Suno, they carry that of the next sung word; fml
  estimates their start at the end of the last sung line before them
  (after **Re-interpret**).
- **In the detail panel** (GENERATION → Lyrics), the lines follow along
  during playback; clicking a line jumps there. If you do not need that,
  collapse the section.

Songs that were already in the catalog before fml 2026.10 are fetched once
automatically (task "Fetch timed lyrics" at the first start with the
audio module switched on, only songs with a subtitle track; needs
ffmpeg). For `SYLT` and LRC, **Re-interpret** is enough.

**ComfyUI music** (YuE2, MiniMax Music 3, ACE-Step 1.0/1.5): the style
text (`style` for YuE2, `tags` for ACE-Step, `caption` for MiniMax)
becomes `prompt`, the lyrics become `lyrics`, plus seed, model and, for
ACE-Step 1.5, BPM and key. Texts that come in through a separate text
node are resolved. The embedded `prompt` is enough; runs via the API do
not write a `workflow`.

**Suno:** Suno writes `made with suno; created=…; id=…` into the comment
(MP3, WAV, M4A) and the song address `suno.com/song/…`. These give
`tool: suno` and the `song_id`. The **song's creation time becomes the
media date** (not the download time). Newer downloads (since about August
2026) carry Content Credentials with the internal model name; fml
translates it into the version, e.g. `chirp-auk` → `Suno v4.5`,
`chirp-crow` → `Suno v5`, `chirp-hawk` → `Suno v6`. Lyrics and title come
from the normal tags. **Suno does not write the style prompt into the
file**, so it is missing. Downloaders such as rs-suno (`SUNO_STYLE`,
`SUNO_MODEL`, `SUNO_PARENT`) and SunoSync (`SUNO_UUID`) are read as far
as their tags are unambiguous.

**Content Credentials** are recognized in audio too: in the ID3 tag (MP3,
FLAC), in the WAV chunk `C2PA` and in the `uuid` box of M4A/MP4.

**Your own recordings:** Logic Pro bounces (WAV) get `creator_tool: Logic
Pro` (or the exact program name from the Broadcast Wave header), iPhone
Voice Memos get `creator_tool: Voice Memos`.

Search examples: `tool: suno`, `model: "Suno v5"`, `bpm: 120`,
`audio_codec: flac`, `has: lyrics`.

## Music collection: artist, album, genre

For an ordinary music collection (ripped CDs as MP3, say) fml reads from
the tags:

| Field | From | Example |
|---|---|---|
| Artist (`artist`) | ID3 `TPE1`, Vorbis `ARTIST`, WAV `IART`, M4A | `Nena` |
| Album artist (`album_artist`) | ID3 `TPE2`, Vorbis `ALBUMARTIST`, M4A | `Various Artists` |
| Album (`album`) | ID3 `TALB`, Vorbis `ALBUM`, WAV `IPRD`, M4A | `99 Luftballons` |
| Track and disc number (`track`, `disc`) | `TRCK`/`TPOS`, `TRACKNUMBER`/`DISCNUMBER` | `3` (from `3/12`) |
| Year (`year`) | ID3 `TDRC`/`TYER`, Vorbis `DATE`, WAV `ICRD`, M4A | `1983` |
| Genre (`genre`) | ID3 `TCON`, Vorbis `GENRE`, WAV `IGNR`, M4A | `Pop` |

Old ID3v1 tags (at the end of the file, at most 30 characters) only count
where an ID3v2 tag is missing; their genre numbers (and the `(17)`
notation in ID3v2) become names. The year becomes the song's date, see
[Date of a song](#date-of-a-song).

**Sidebar (audio view only):** three new groups, alphabetical.

- **Artist**: the album artist where the tag names one, otherwise the
  artist of the track. A compilation thus stays together under
  "Various Artists" instead of falling apart into a hundred names.
- **Album**: one click shows the album; together with an artist, albums
  of the same name ("Greatest Hits") can be told apart.
- **Genre**: collapsed out of the box (click the heading to open it).

Groups for which no song has tags don't appear at all. The counts filter
along as everywhere: after clicking an artist, their albums are on top.

**Search:**

- `albumartist: "Nena"` (German `interpret:`) — the same rule as the
  group: album artist, otherwise artist.
- `artist: nena` — only the artist of the single track, so Nena's tracks
  on compilations as well.
- `album: luftballons`, `genre: pop`.
- Artist, album and genre are also in the **full-text search**.

**Sort "Album"** (`sort: album`, audio view only): artist → album →
disc → track number, and for equal or missing track numbers the file name
(ripped CDs are usually called `01 Title.mp3`). An album thus plays in its
order, also with **▶ Play all**. Songs without these tags come last.

**Clicking an album** (group Album or an `album:` chip) sorts the list by
album automatically, **as long as there is no sort chip in the search
bar**. Without a chip, the sort last picked in the sort menu applies
otherwise (see [Interface](gui.md)); an album chip takes precedence over
it. If there is a sort chip (picked in the menu or brought along by a
saved search), it wins. So to get something else for an album, pick it in
the sort menu, even "Added"; it then shows as a chip. The gallery and
searches without an album chip stay unchanged.

**Updating the collection:** for music cataloged before, run **Admin →
Maintenance → Re-interpret** once; the tags are already in the catalog,
no re-import needed. Two exceptions need the file itself: Content
Credentials in **M4A/MP4** cataloged before fml 2026.09.2 ("Re-scan all
locations" once, because that building block is only stored since then),
and the lyrics with timings from the subtitle track (fml fetches them by
itself, see above).

## Your own order of a saved search

To audition a planned playlist, the order of the songs can be set **by
hand**. The order belongs to a [saved search](gui.md), not to the song:
the same song can sit at different places in two playlists.

### Two things that are saved separately

| What | How is it saved? |
|---|---|
| **The order itself** (which song sits where) | **Automatically, right away** with every move. No ☆ needed. |
| **That the search opens in this order** | Only with **☆ → Overwrite »name«**. This saves the sort chip "Manual" in the search. |

If you only reorder and never press ☆, nothing is lost: the order is
saved, but the search opens with the normal sort. Pick "Manual" in the
sort menu once, and your own order is back.

### Setting it up once

1. Tag the songs, e.g. `release candidate`.
2. Type the search `tag: "release candidate"` and store it with **☆ save**,
   e.g. as "CD 2026".
3. Open the saved search on the left under "Saved searches".
4. Pick **"Manual"** in the sort menu (see below for when it is there).
5. Put the songs into the order you want (next section).
6. **☆ → Overwrite »CD 2026«.** The dialog shows "The sort order is saved
   along: Manual". From now on "CD 2026" always opens in your own order.

### Reordering

- Drag the **file name** of a row onto another row: onto the upper half =
  before, onto the lower half = after.
- Or select a row and move it one place with **Alt+↑ / Alt+↓**.
- While this works, a line above the list says "Order: drag the name or
  Alt+↑/↓". If a move fails, the message appears in the same place.
- **▶ Play all** plays the list in exactly this order.

### When "Manual" is available

"Manual" only appears in the sort menu when **all** of this holds:

- the audio view is open (not the gallery),
- a saved search is open,
- its chips are still exactly as they were saved.

Searching for something else afterwards (typing, clicking in the sidebar,
picking "All media") leaves the saved search. "Manual" disappears, and the
list goes back to its previous sort. The order stays saved; clicking the
saved search brings it back.

### What happens to the order

- **Newly tagged songs** append at the end, in the order they were
  cataloged.
- **A song that loses the tag** drops out of the list; when it gets it
  back, it returns to its old place.
- **☆ → Save as new search** creates a new search with its **own, empty**
  order; the old search keeps its own.
- **Deleting the saved search** deletes its order too.
- There is deliberately no export (such as `.m3u`); the order is for
  planning and auditioning.

## Date of a song

A song's date (sort "Created", sidebar "By year", `year:`) comes from
this order:

1. **set by hand** (field under CURATED or the "Date" row of the bulk
   action, see [Interface](gui.md)) — always wins;
2. an **embedded date**, e.g. Suno's creation time;
3. the **year from the tags** (ID3 `TDRC`/`TYER`, Vorbis `DATE`, M4A
   `©day`), usually the release year. It only counts as a year: it shows
   as "1987", not "1987-01-01";
4. the **file stamp**.

The [date rule](import.md) applies to the tag year too: a year before the
configured oldest date (2015 out of the box) counts as implausible, and
the file stamp wins. Anyone reading in old music first sets the date back
accordingly ("Oldest plausible date" under Admin → Configuration → Media
library) and then
runs **Re-interpret**. When importing with copying, a song with a tag
year lands in the library folder `1987/01/01`.

## Duration (also for videos)

Every audio and video item has a **duration** in seconds. It is shown in
the detail panel, the loupe and the single view. Videos cataloged before
fml 2026.09.2 get their duration with a **re-scan of all locations**.

## Searching and sorting

These filters work regardless of the module:

- **`type:`** (German `typ:`) — media type: `image`, `video`, `audio`
  (German `bild`, `video`, `audio`). `type: audio`, `-type: image`,
  `type: video | audio`.
  Clickable as the sidebar group **Media type**, in the "+ Criterion"
  builder and in the typing help.
- **`duration:`** (German `dauer:`) — duration with a comparison in
  seconds or as minutes:seconds: `duration: >120`, `duration: <=3:30`,
  `duration: 60-180` (range, inclusive). Several values with ` | ` are OR.
  Items without a duration (images) never match, not even negated:
  `-duration: >120` finds short media, not all images.
- **Sort "Duration"** (`sort: duration`): longest first,
  `sort: duration-asc` shortest first; media without a duration stay at
  the end in both directions.
- **Sort "Album"** (`sort: album`) and **"Manual"** exist only in the
  audio view, see [Music collection](#music-collection-artist-album-genre)
  and [Your own order](#your-own-order-of-a-saved-search).

Example: `type: audio duration: >120 sort: duration`.

## Playback

In the audio view the row itself plays (see above); the detail panel
shows only metadata and lyrics there, no second player. Where a song
appears without a row (in the gallery's detail panel and in the single
view of a song with a cover), a small player shows
the same waveform (stretched to the song's length), ▶, position and
duration; it never starts by itself and is the same playhead as the row.
If a video with sound starts anywhere (loupe, single view), the song
pauses, and the other way round. Muted preview videos in the detail panel and in
rankings let the music keep playing.

**Songs have no loupe, and a single view only with a cover** (see
[Cover](#cover-finished-songs-in-the-gallery)): the list with player and
detail panel can do more. "View node graph" in the detail panel opens the
loupe with the workflow for ComfyUI songs. The 📂 button in front of the
preferred location in the detail panel (section Locations) shows the file
selected in Finder/Explorer. Enter opens nothing in the audio view.

**Playback bar.** As soon as a song plays, the bar appears at the bottom:
⏮ (within the first three seconds: the previous song of "Play all";
after that: back to the start), ▶/❚❚, ⏭ (next song of "Play all"), the name and the position
in the sequence, the song's waveform with click-to-seek and the options on
the right:

- **≈ Loudness** matches the loudness (default: on). Every song is brought
  to -14 LUFS so that the louder version does not win when comparing; the
  bar shows by how many dB. Loud songs get quieter, quiet ones only as
  much louder as keeps the true peak below -1 dBTP (otherwise it clips;
  measured as sample peak below -2 dBFS, see below).
  The waveforms show the matched height: what you see is what you hear.
  The setting applies to all songs and is remembered. The file itself
  never changes.
- **Tempo** cycles 1.00× → 1.25× → 1.50× **without** changing the pitch:
  for quick previewing.
- **⟲ A–B** repeats a range: the first click sets A at the playback
  position, the second sets B and the range loops; the third click turns
  it off. The range is marked in the waveforms.
- **✕** stops playback and hides the bar; the position stays remembered.

The bar **keeps playing when you switch to the gallery**: you can browse
images while "Play all" runs. It also stays at the bottom in an open
[ranking](rankings.md), so you can click through duels while listening to
music. The playing row is highlighted in the list.

The keyboard's **media keys** (play/pause, next, previous) and the
operating system's media controls operate the player, even with the
browser window in the background. They show the file name as the title.

Browsers play MP3, FLAC, WAV, M4A (AAC) and usually Ogg/Opus. **AIFF**
plays only in Safari, **CAF** in no browser, **ALAC** in M4A only in
Safari. For these three fml creates a **playable copy**: lossless FLAC,
which every browser plays, created **only on first playback** and **only
if the browser cannot play the format itself**: Safari plays AIFF and ALAC
directly and therefore gets no copy. The first ▶ takes a moment longer
(a 3-minute song needs about 0.2 seconds on a current Mac, about one on a
small home server); after that the song plays at once. The original stays
untouched; the copy lives in the cache (default `cache/audio` next to the
database, `[cache] audio` in `config.toml`) and can be recreated at any
time. It is lossless and about half the size of an AIFF. If the copy fails
too (for example without ffmpeg, or with a missing file), row, player and
bar honestly say "Playback not possible"; the locations in the detail
panel lead to the file.

## Time comments

A time comment belongs to a **point in the song**, as on SoundCloud:
"Chorus" at 1:40, "voice cracks" at 2:15. Comments are part of the manual
layer like ratings and tags; nothing is written into the file.

**Adding** always happens at the playhead:

- **K** in the audio view: for the selected row, at its own playhead
  (which stays put even when the row isn't playing: move it with ←/→,
  then press K). In the gallery, K means the song in the playback bar.
- **💬** in the playback bar: for the song that is playing.
- **＋ Comment at the playhead** in the detail panel.

A small input opens with the position in front. **Enter** saves (so does
clicking elsewhere when there is text), **Esc** discards.

**Seeing and jumping:** every comment is a small pin ▲ below the
waveform, in the list, in the player and in the playback bar. Hover to
read the text, click to play from exactly there. With "Chorus" on the
chorus of two versions, chorus against chorus is one click each.

**Comments appear while playing:** one second before the spot comes up,
the text shows above the waveform and stays for five seconds after it.
When you pause, it stays visible. Comments close together are stacked.

**In the detail panel** all comments of the song are listed under "Time
comments": click a line to play from there, **double-click the text** to
edit it (Enter saves, Esc cancels), **✕** deletes.

**Searching:** comments are part of the normal search. Searching for
"strings" also finds the song with "strings come in" attached.

### Exchanging comments with another fml

Two people with their own fml each can send each other comments as a
file (mail, USB stick, cloud folder).

**Export:** in the audio view select the songs or narrow down a search,
open the **batch action** and click **Export** next to "Time comments".
This creates a file `fml-comments-YYYY-MM-DD.json` with all comments of
these songs. Nothing changes here.

**Import** happens on the other side under **Admin → Maintenance →
Import time comments**, in three steps:

1. **File and origin:** choose the file and enter who the comments are
   from (e.g. a name).
2. **Preview:** how many songs were found, how many comments are new and
   how many are already there, and which songs don't exist here.
3. **Take over.** Every imported comment carries its origin as a small
   label (in the panel, on the pin, when it fades in).

**How fml finds the songs:** by the file itself (its hash). A file that
was copied, zipped or sent unchanged is found on any computer. If
someone changed the file (edited tags in a player or tag editor,
downloaded it again, converted it to another format), it is a different
file for fml. For **Suno songs** there is a second chance via the Suno
song ID: the preview shows these matches separately, and they are only
taken over with the checkbox "Also take over songs found only by their
Suno ID".

**No duplicates:** a comment at the same position with the same text is
skipped. Running the same import twice changes nothing, and comments
sent back and forth don't double up.

**The file format** (for the curious): JSON with `"format":
"fml-time-comments"` and `"version": 1`; per song `file_hash`, `name`
(only as a hint), `duration`, `suno_ids` if present and the list
`comments` with `at_ms` (position in milliseconds), `text`,
`created_at`, `updated_at`; at the very top there are also `exported_at`
and the list `items` with the songs. fml accepts at most 20 MB, 50,000
songs and 200,000 comments per file, 2,000 comments per song and comment
texts up to 2,000 characters.

## Comparing

For the shortlist: **mark 2 to 6 songs** (Shift or ⌘/Ctrl click) and press
**C** or click **⇆ Compare** at the top right. The list **narrows down to
these songs** and enlarges the rows: a taller waveform, and the **time
comments stand as text** above the wave (two close together are stacked).
The time axis is now the longest of the compared songs, so the waves use
the full width. With more than six marked songs the button is disabled.

- **Match loudness** is **always on first** while comparing, so the louder
  version does not win. The switch at the top right toggles it for this
  comparison; your own setting comes back unchanged afterwards.
- **The rows are the player:** the playback bar at the bottom is hidden
  while comparing, leaving more room for waves and comments. Set tempo and
  the A–B loop in the bar beforehand; the tempo keeps applying while
  comparing. After Esc the bar is back.
- **Works like the list:** ↑/↓ changes the row, space plays, ←/→ moves the
  playhead, 1 to 5 rates, **Delete rejects**, K adds a comment, tags and
  notes in the detail panel. Only the current row is selected: a rating
  hits only that row.
- **Rejected songs** leave the comparison at once; the row below moves up.
- **Esc** (or **✕ End comparison**) brings back the full list at **the same
  scroll position**. The remaining songs stay marked: **C** compares them
  again right away. Filters and search stay as they were. A new search, a
  different sort order or switching to the gallery also ends the
  comparison.

Example: mark six Suno candidates, C, set every version to the chorus and
listen to them in turn, reject two with Delete, rate the other four, Esc.

In the gallery, C still compares **two images** on top of each other (A/B
with a wipe edge); the audio view has no image comparison.

## Cover: finished songs in the gallery

A song is **finished** once it has a **cover**: an image from your own
library, for example artwork generated in ComfyUI. With a cover the song
also appears **in the gallery**, among images and videos. All other takes
stay in the audio view.

**Setting it:** select the song (in the list, the gallery or the single
view) and click **🖼 Choose cover …** at the top of the detail panel.
The dialog shows images from the library and starts with `typ: bild` and
the **song's tags** (combined with OR): if the song has the tag
`regenzeit`, images with that tag come first. ✕ removes chips; the field
next to them searches like the gallery search field: a word filters by
text while you type (from three characters), Enter turns it into a chip,
and expressions like `model: flux` work too. Click an
image, then **Set as cover** (or double-click the image). Tip: give the
artwork the same tag as the song when you generate it.

From then on the cover is the song's face: it sits **at the top of the
detail panel** like an image's preview, in every view, with **✓ Finalised**
and **Change …** / **Remove** right below it. The playback bar shows it
left of the title, and so do the system's media keys.

- **Nothing is written to files.** fml only remembers which image belongs
  to which song. The audio file and the image stay unchanged.
- **In the gallery** the tile shows the cover image with **♪ and the
  duration**; ▶ on the tile and the space bar play the song, and the
  playback bar appears as usual. **Double-click or Enter** opens the
  **single view**: a large cover, the player below it, the detail panel on
  the right. ←/→ browses through the gallery as usual.
- **Removing the cover**, **rejecting** the cover image (Del) or blocking
  it: the song leaves the gallery and is only in the audio view. From the
  single view you then return to the overview.
- **Embedded covers** never count as a cover: they bring no song into the
  gallery and do not make it "finished". The detail panel shows them small
  and faded under **File** ("Embedded picture").
- **Regular music** (no AI generator detected, such as a purchased album)
  still shows its embedded picture as a **display picture**: small in front
  of the name in the list, in the playback bar and with the system's media
  keys. That way the audio view works as a music playlist while you browse
  images in the gallery or click through duels. Songs from Suno, ComfyUI &
  Co. do not show their bundled default picture; they only get a picture
  once you choose a cover. A chosen cover always takes precedence.
- With the audio module switched off, the gallery does not show songs
  with a cover either; the covers stay stored.

## Loudness and waveform

After every import (and when switching the module on) fml measures each
audio file once in the background:

- **Loudness** according to EBU R128: integrated loudness in LUFS,
  loudness range (LRA) in LU and true peak in dBTP. It is shown in the
  detail panel under "File", e.g. `-9.0 LUFS · LRA 6.1 LU · true peak
  -0.3 dBTP`. **True peak or sample peak** (`[audio] true_peak` in
  `config.toml`, default `true`): true peak also estimates the peaks
  between samples (4x oversampling) and is the mastering measure, but it
  takes almost half of the whole measuring time. With `true_peak = false`
  fml measures the sample peak (in dBFS, shown as `sample peak -0.3
  dBFS`): the measurement takes about half as long, which can save days
  for large collections on slow computers; loudness matching then keeps
  1 dB more headroom (-2 dBFS). The setting applies to new measurements,
  finished ones keep their value. For orientation: streaming services play back at around
  -14 LUFS; a song at -9 LUFS is mastered considerably louder. The list
  shows the integrated loudness as a column of its own; the player
  matches it (see "Playback").
- **Three-band waveform**: bass (below 200 Hz), mids (200 Hz to 2 kHz) and
  highs (above 2 kHz), as in DJ software. Each band is drawn at its own
  height, the bass at the back, the highs at the front: where blue
  dominates the bass pushes, where the light colour stands out cymbals
  and voice hiss. The data comes from `/api/audio/analysis/<hash>`.
  While a measurement is still running, the row shows a baseline.

Both are derived and live in the same cache as the playable copies.
**Admin → Maintenance → Analyse audio** creates missing measurements,
retries failed ones (failed copies too, on the next playback) and
recalculates after an update if the measurement changed.
Permanent failures are listed under **Admin → Issues** (kind `audio`).

## Limits (current state)

- "Play all" takes at most the first 5000 songs of the list.
- Udio: the lineage (`ext v…`, `remix v…` in the file name) is not
  interpreted yet; searching the file name works (`file: "ext v"`).
- Sidecar files (such as YuE2's `request.json` or ACE-Step's JSON) are not
  read yet.
- Rankings compare only images and videos; songs are never part of them,
  not even with a cover or with `typ: audio`.
