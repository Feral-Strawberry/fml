# Exporting copies

With the export, the Feral Media Library (fml) puts **copies** of media
into a folder that another program picks them up from: a batch of images
for video editing, the songs for a CD, a selection for somebody else.

The export is always a copy. The originals stay where they are, and
nothing changes in the library, the ratings or the tags.

## Set up once: the export folder

**Admin → Configuration → Media library → Export folder**: enter a folder
or pick one with 📁, then save. In `config.toml` this is `[export] root`.

The folder must not be inside the media library, a watch folder or the
cache, and none of those may be inside it. Otherwise fml would read its
own exports back in. Saving refuses such folders with a message.

Without an export folder, the button in the bulk action is locked and
its box says why. The same applies while the folder is not reachable, for
example because the drive is not connected.

The export also works in read-only mode, that is without library
management: it only reads the originals and writes to the export folder
alone.

## Exporting

1. Select media or narrow down a search (images, videos or, in the audio
   view, songs).
2. Open **⚡ Bulk action**. If something is selected, "selection (N)" or
   "all hits (M)" can be chosen at the top.
3. In the lower section **Export** (it changes nothing in the library),
   click **Export copies …** in the "Copies" box.
4. The small dialog shows the number of files, their size, the target
   folder and the free space. To set:
   - **Package name** (optional): appended to the folder name. Characters
     a file system does not allow are removed.
   - **Layout**: **flat** (all files directly in the folder, the default)
     or **year/month/day** (subfolders like in the media library, by the
     date of the medium; media without a date go to `ohne-datum`).
   - **Converted formats** (only shown when there are any): see below.
   - **Manual details: write into the copy** (only shown when songs with
     details, lyrics or a cover set by hand are included, and ticked): see
     [Manual details in the copy](#manual-details-in-the-copy).
5. **Export** queues the export as a task. The dialog names the target
   folder; the background widget on the left shows the progress, and the
   result is shown there and under Admin → Overview afterwards.

If the free space is not enough for all files, the export does not start
and says how much is missing.

## Where the copies go

```
<export folder>/2026-10-09/               without a package name
<export folder>/2026-10-09 Music video/   with package name "Music video"
```

The date is the day of the export. A second export on the same day with
the same name adds to the same folder.

Every file keeps its name. If the folder already holds a file of that
name, the content decides:

- **same content:** the file is skipped ("already there"). The same
  export twice therefore creates no duplicate files.
- **different content:** the new file is called `name (1).ext`,
  `name (2).ext` and so on, as in a file manager.

## What exactly is copied

Always the original, bit for bit, with all the metadata it carries and
its modification date. Every copy is checked against the original after
writing. fml adds nothing and converts nothing. Only a write protection
(for example on files that come from a CD) is not carried over.

**The first exception** are formats that fml itself can only show through a
computed image, currently Kodak Photo CD (`.pcd`). The raw file is of
little use outside fml, so here the converted version leaves as **PNG**
(`image.pcd` becomes `image.png`). If you want the raw file, choose
**original** under "Converted formats" in the dialog.

If fml has shown the image at full size before, the converted version is
in the preview cache. The PNG export takes it from there and then also
works while the raw file is missing (drive not connected, file moved).
The raw file itself, of course, cannot be exported without the raw file.

Songs leave as the original, even where fml uses a version of its own
for playback in the browser. The second exception are songs with manual
details when the checkbox is ticked (next section).

## Manual details in the copy

What you maintain by hand in fml lives only in fml. But whoever passes a
file on passes on the file, not the database. With the checkbox **Manual
details: write into the copy**, fml therefore writes into the **copy** of
a song:

- the [music details by hand](audio.md#music-details-by-hand) (title,
  artist, album artist, album, track number, disc, year, genre),
- the [lyrics by hand](audio.md#lyrics-by-hand), with times per line if
  every line has one,
- the [cover](audio.md#cover-finished-songs-in-the-gallery), scaled down
  to at most 1200 pixels on the longest edge (JPEG). It carries a mark by
  which another fml recognises it as chosen by hand; there it appears as a
  display picture, also for songs from Suno.

Where something is set by hand, it replaces the value in the file;
everything else in the file stays as it is. The original is never
touched.

**Formats:** MP3 and M4A. Other songs with manual details leave
unchanged; the result counts them as "without details (format)".

- **MP3:** fml writes the details into the ID3 tag; all other entries in
  it are kept, including the Suno identifier and provenance data. The lyrics
  go into `USLT`, with times additionally into `SYLT`.
- **M4A:** fml repackages the file with ffmpeg without touching the
  audio. The lyrics go into the lyrics tag, with times additionally as a
  subtitle track as with Suno V6.
  ffmpeg does not carry over custom entries of other programs (iTunes
  freeform tags); the server log names them (`export: tags dropped`).
  M4A needs ffmpeg.

Such a copy is no longer bit-identical. Instead, fml checks that the
**audio** is unchanged, and only then does the file appear in the folder.
The "already there" check does not apply to these copies: a second
export puts `name (1).ext` next to it. If the cover image is not
reachable at the moment, the copy gets the other details without the
cover.

If the song carries a provenance signature (C2PA, for example from Suno),
it stays in the file but no longer holds for the changed copy.

## The result

After the run there is a line like
`Export: 118 copied · 4 already there · 2 not reachable → <folder>`:

- **copied:** new in the folder; **of them with manual details**: songs
  whose copy fml wrote the details into.
- **without details (format):** songs with manual details in a format fml
  does not write to; they lie in the folder unchanged.
- **already there:** was there with the same content.
- **not reachable:** fml found the file at none of its locations. For
  the first case the result names the reason: the **file is missing**
  (drive not connected, file moved or deleted), or a **different file**
  now lies at the location (another size than in the catalog, for example
  after editing it in another program). All cases are in the server log
  (`export: unreachable`). The export carries on regardless. Re-scanning
  the folder brings the catalog back in line with the disk.
- **errors:** the copy could not be written or did not match the
  original; the file is then missing in the folder. The result names the
  first error with file and reason; all others are in the server log
  (Admin → Server log, lines with `export:`).

Like every task, the export can be paused and resumed
([Background: power and pause](admin.md#background-power-and-pause)).

## Limits

- No ZIP packages, no file name templates, no list of earlier exports.
- No conversion to other formats or sizes (apart from the exceptions
  above).
- fml never tidies up the export folder. What lies there belongs to the
  file manager.
