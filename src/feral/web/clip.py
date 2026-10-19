"""Modul „Ausschnitt" (ADR 0105): einen Abschnitt aus einem Song oder Video
als neue Datei in den Export-Ordner schreiben.

Die erste Stelle, an der fml Medien für den Anwender neu kodiert. Das
Original wird nur gelesen; der Ausschnitt landet im Tagesordner des
Export-Ordners (``<root>/<JJJJ-MM-TT>/``, wie eine flache Kopie nach
ADR 0103) und wird nicht katalogisiert.

Je Ausgabe eine Datei:

- ``av``    Video mit Ton, MP4 (H.264 + AAC)
- ``video`` nur Video, MP4 (H.264), Namenszusatz ``mute``
- ``audio`` Ton, WAV (PCM 16 Bit, Abtastrate und Kanäle der Quelle)

Es wird neu kodiert, damit der Schnitt auf die Stelle genau sitzt (eine
Kopie des Datenstroms könnte nur an Schlüsselbildern schneiden). Werkzeug
ist das vorhandene ffmpeg, nur mit lokalen Dateien (``tools.media_input``).

Rein auf Verbindungs-Ebene; die Aufgabe steht in ``tasks.py``, die
Endpunkte in ``app.py``.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..hashing import hash_file
from ..processes import ffmpeg_quiet_args
from ..tools import NO_WINDOW, find_binary, media_input
from . import library
from .export import _free_name, _has_hash, temp_file

log = logging.getLogger(__name__)

OUTPUTS = ("av", "video", "audio")
MIN_LENGTH = 0.1            # Sekunden
_EXT = {"av": ".mp4", "video": ".mp4", "audio": ".wav"}
_MUTE = " mute"             # fester Zusatz für „nur Video", sprachunabhängig
_H264 = re.compile(r"^\s*V\S*\s+libx264\s", re.MULTILINE)
_encoder_cache: dict[str, str] = {}


@dataclass
class ClipReport:
    """Ergebnis eines Laufs: geschriebene und schon vorhandene Dateien."""

    geschrieben: list[str] = field(default_factory=list)
    schon_da: list[str] = field(default_factory=list)
    fehler: int = 0
    erster_fehler: str = ""


# -- Was dieses ffmpeg kann ---------------------------------------------------------

def encoder_state() -> str:
    """``"ok"``, ``"no-h264"`` (ffmpeg ohne libx264: Ton geht, Video nicht)
    oder ``"no-ffmpeg"``. Je ffmpeg-Pfad einmal gefragt."""
    ffmpeg = find_binary("ffmpeg")
    if ffmpeg is None:
        return "no-ffmpeg"
    if ffmpeg not in _encoder_cache:
        try:
            proc = subprocess.run(
                [ffmpeg, "-hide_banner", "-encoders"],
                capture_output=True, timeout=20, **NO_WINDOW)
            listing = proc.stdout.decode("utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired):
            return "no-ffmpeg"
        _encoder_cache[ffmpeg] = "ok" if _H264.search(listing) else "no-h264"
    return _encoder_cache[ffmpeg]


def allowed_outputs(media_kind: str, has_audio: bool) -> tuple[str, ...]:
    """Welche Ausgaben ein Item hergibt: Songs nur Ton; Videos alle drei,
    ohne Tonspur nur das Bild."""
    if media_kind == "audio":
        return ("audio",)
    if media_kind == "video":
        return OUTPUTS if has_audio else ("video",)
    return ()


def has_audio_stream(conn: sqlite3.Connection, file_hash: str) -> bool:
    """Trägt das Item eine Tonspur? Aus den Roh-Eckwerten von ffprobe
    (Schicht 1), ohne die Datei anzufassen."""
    return conn.execute(
        """SELECT 1 FROM raw_metadata
            WHERE file_hash = ? AND keyword = 'codec_type' AND value_text = 'audio'
            LIMIT 1""", (file_hash,)).fetchone() is not None


# -- Namen --------------------------------------------------------------------------

def time_label(seconds: float) -> str:
    """Stelle für den Dateinamen: ``0m12s``, ``1m05.5s``, ``1h02m03s``. Die
    Zehntel stehen nur da, wenn sie nicht null sind."""
    tenths = round(seconds * 10)
    whole, frac = divmod(tenths, 10)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    sec = f"{secs:02d}.{frac}" if frac else f"{secs:02d}"
    return f"{hours}h{minutes:02d}m{sec}s" if hours else f"{minutes}m{sec}s"


def clip_name(source_name: str, start: float, end: float, output: str) -> str:
    """Name der Quelle plus Zeitbereich (ADR 0105 Punkt 8), z. B.
    ``song 0m12s-0m22s.wav``; „nur Video" bekommt den Zusatz ``mute``."""
    stem = Path(source_name).stem
    extra = _MUTE if output == "video" else ""
    return f"{stem} {time_label(start)}-{time_label(end)}{extra}{_EXT[output]}"


# -- ffmpeg -------------------------------------------------------------------------

def ffmpeg_args(ffmpeg: str, source: str | Path, dest: str | Path, *,
                start: float, end: float, output: str) -> list[str]:
    """Der eine ffmpeg-Aufruf je Ausgabe. ``-ss``/``-t`` vor der Eingabe:
    ffmpeg sucht das Schlüsselbild davor und verwirft bis zur Stelle, der
    Schnitt sitzt beim Neukodieren genau. Metadaten der Quelle reisen nicht
    mit (eingebettete Workflows gehören nicht in ein Arbeitsstück)."""
    head = [ffmpeg, "-nostdin", "-v", "error", "-y", *ffmpeg_quiet_args(),
            "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", *media_input(source),
            "-map_metadata", "-1", "-map_chapters", "-1"]
    out = "file:" + str(Path(dest).absolute())   # nie als Option oder Protokoll gelesen
    if output == "audio":
        return head + ["-map", "0:a:0", "-vn", "-c:a", "pcm_s16le", "-f", "wav", out]
    # yuv420p spielt überall; H.264 braucht dafür gerade Kanten (der Zuschnitt
    # ist bei geraden Maßen wirkungslos, sonst fällt eine Pixelzeile weg).
    video = ["-map", "0:v:0", "-c:v", "libx264", "-preset", "medium", "-crf", "17",
             "-pix_fmt", "yuv420p", "-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2"]
    sound = ["-map", "0:a:0", "-c:a", "aac", "-b:a", "256k"] if output == "av" else ["-an"]
    return head + video + sound + ["-movflags", "+faststart", "-f", "mp4", out]


def _timeout(length: float) -> float:
    return max(300.0, 120.0 * length)


def write_clip(source: Path, directory: Path, *, start: float, end: float,
               output: str) -> tuple[Path, bool]:
    """Eine Ausgabe nach ``directory`` schreiben: unter vorläufigem Namen
    kodieren, dann umbenennen. Liefert ``(Datei, neu)``; liegt unter dem
    Namen schon derselbe Inhalt, bleibt es bei der vorhandenen Datei
    (``neu = False``), sonst ``name (1).ext`` wie beim Kopie-Export."""
    ffmpeg = find_binary("ffmpeg")
    if ffmpeg is None:
        raise OSError("ffmpeg not found")
    name = clip_name(source.name, start, end, output)
    temp = temp_file(directory, name)
    try:
        try:
            proc = subprocess.run(
                ffmpeg_args(ffmpeg, source, temp, start=start, end=end, output=output),
                capture_output=True, timeout=_timeout(end - start), **NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise OSError("ffmpeg timed out") from None
        if proc.returncode != 0 or not temp.is_file() or temp.stat().st_size == 0:
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            raise OSError(f"ffmpeg: {stderr[-400:]}" if stderr else "ffmpeg wrote nothing")
        clip_hash = hash_file(temp)
        present: list[Path] = []

        def same(candidate: Path) -> bool:
            if _has_hash(candidate, clip_hash):
                present.append(candidate)
                return True
            return False

        destination = _free_name(directory, name, same)
        if destination is None:
            return present[0], False
        temp.replace(destination)
        return destination, True
    finally:
        temp.unlink(missing_ok=True)


def export_clip(
    conn: sqlite3.Connection, file_hash: str, *, target: str | Path,
    start: float, end: float, outputs: list[str],
    roots: tuple[str | None, list[str]] = (None, []),
) -> ClipReport | None:
    """Die gewählten Ausgaben eines Items nach ``target`` (der Tagesordner)
    schreiben. ``None`` = kein Fundort der Quelle erreichbar. Fehler einer
    Ausgabe töten die anderen nicht."""
    row = conn.execute(
        "SELECT file_size FROM items WHERE file_hash = ?", (file_hash,)).fetchone()
    locations = [] if row is None else library.ordered_locations(
        conn, file_hash, row[0], roots=roots)
    usable = [loc for loc in locations if loc["usable"]]
    if not usable:
        log.warning("clip: unreachable %s", file_hash[:12])
        return None
    source, target = Path(usable[0]["path"]), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    report = ClipReport()
    for output in outputs:
        try:
            path, new = write_clip(source, target, start=start, end=end, output=output)
        except Exception as exc:  # Einzelfehler: die anderen Ausgaben laufen weiter
            report.fehler += 1
            if not report.erster_fehler:
                report.erster_fehler = (
                    f"{clip_name(source.name, start, end, output)}: {exc}")[:400]
            log.warning("clip: %s (%s): %s: %s", source, output, exc.__class__.__name__, exc)
            continue
        (report.geschrieben if new else report.schon_da).append(str(path))
    return report
