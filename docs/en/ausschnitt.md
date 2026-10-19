# Clip from a song or video

With the **Clip** module the Feral Media Library (fml) cuts a piece out
of a song or video and puts it as a new file into the export folder: ten
seconds of a song as a reference for a workflow, a few seconds of a video
as source material.

The original is only read. Nothing changes in the library, the ratings
or the tags, and the clip does not appear in the library. If you want it
there, catalog it like any other file.

## Set up once

1. Switch on **Admin → Configuration → Modules → Clip module** and save.
   The module ships switched off.
2. Enter an **export folder** if none is set up yet (see
   [Exporting copies](export.md)). Clips go to the same folder as copies.

The module needs **ffmpeg**. For video clips this ffmpeg must be able to
encode H.264 (libx264); the common packages can. If something is missing,
the switch in the configuration says so: without H.264 only sound clips
work, without ffmpeg none.

## Opening a clip

Select a video or a song. In the panel on the right, next to the rating
dots, there is the button **✂ Clip**. It is available wherever the panel
is: in the gallery, in the audio view and in the single view.

The button is locked when the browser cannot play the file (ProRes, for
example) or its duration is unknown. Without picture and sound to check,
cutting makes little sense.

## Marking the range

The view shows the video (for songs the cover) and below it a timeline
over the whole length, for songs with the waveform. The marked range is
tinted and has a handle on the left and on the right.

- **Dragging a handle** changes the start or the end.
- **Dragging the middle** moves the whole range. The length stays.
- **A click without dragging** (outside or inside the range) only sets
  the playhead. This is how you look for a spot without changing the
  range. A click on the picture plays or pauses.
- **Start**, **End** and **Length** can be typed, in seconds (`72.5`) or
  as a time (`1:12.5`). The grid is tenths of a second.
- **here** next to start and end sets that edge to the playhead. If the
  spot is behind the end (or before the start), the whole range moves
  along.

**Fixed length:** type the length, for example `10`, then drag the range
by its middle to the right place.

When opened, the range starts where the song currently stands in the
player or the video in the single view, and is ten seconds long. If the
player has an A–B loop for this song, the loop is taken over.

## Listening

**▶** or the space bar plays. When the playhead reaches the end of the
range it jumps back to the start: the range loops. Outside the range,
playback simply continues.

After each change the playhead jumps to where the change matters: to the
new start, or two seconds before the new end.

While the view is open the player pauses, and other videos in the window
stop.

## Keys

| Key | Effect |
| --- | --- |
| Space bar | play and pause |
| I | start at the playhead |
| O | end at the playhead |
| ← → | move the handle touched last by 0.1 s, with Shift by 1 s |
| Esc | close the view |

## Exporting

**Output** says what is written:

- **Song:** always **sound (WAV)**.
- **Video:** tick **video with sound**, **video only**, **sound (WAV)**.
  Each tick is a file of its own; the choice is remembered for next time.
  A video without an audio track only provides the picture.

**Export** writes the files. This usually takes seconds and has priority
over running background work; while background work is paused, the clip
waits until it carries on. Below, a button **📂 file name** appears
for each file and shows it in the file manager. The view stays open, so
the next piece can be cut from the same file right away.

If the export is locked, the reason is next to the button: no export
folder set up, folder or source file not reachable, or ffmpeg missing.

## What is written

```
<export folder>/2026-10-11/song 0m12s-0m22s.wav
<export folder>/2026-10-11/take 0m03s-0m07.5s.mp4
<export folder>/2026-10-11/take 0m03s-0m07.5s mute.mp4     video only
```

The folder is the day of the export, the same as for copies without a
package name. The file name is the name of the source plus the time
range; "video only" gets the suffix `mute`. The same clip a second time
does not create a second file.

| Output | Format |
| --- | --- |
| Sound | WAV, 16 bit, sample rate and channels of the source |
| Video | MP4 with H.264 in high quality, resolution and frame rate of the source |
| Sound in the video | AAC |

The clip is re-encoded so that the cut sits exactly at the marked spot.
Embedded metadata of the source (title, workflows) is not in the clip.

## Limits

- No fades, no further formats, no quality controls.
- The timeline has no zoom. For long files the range becomes exact
  through the fields and the arrow keys.
- A clip belongs to exactly one file; there is no bulk action.
- For videos with an odd width or height one line of pixels is dropped.
