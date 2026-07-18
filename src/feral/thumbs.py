"""Thumbnail-Pipeline (Stufe 2, ADR 0013).

Im Grid werden **nie** Originaldateien gezeigt, sondern vorab generierte
Thumbnails fester Größe (Steckbrief §4): einmal generiert, als JPEG im
Platten-Cache abgelegt (Dateiname = Datei-Hash, sharded), immer wiederverwendet.

- Bilder (auch animiertes WEBP/GIF): **Pillow**, erster Frame als Poster-Frame.
  PSD läuft mit (ADR 0052): Pillow liest das eingebettete Composite.
- Videos: **ffmpeg** (System-Binary wie ffprobe) zieht den ersten Frame.
- PDF/Fehlschläge: kein Thumbnail — das Frontend zeigt ein generisches Icon.

Dazu ``render_preview`` (ADR 0052): volle Ansicht als JPEG für Bild-Container,
die der Browser nicht nativ rendert (TIFF/PSD) — dieselbe Pillow-Strecke wie
die Thumbnails, nur ohne Verkleinerung und ohne Platten-Cache (der Browser
cacht die hash-adressierte Antwort selbst).

Defensiv und nebenläufigkeitsfest: geschrieben wird atomar (Tempdatei + rename),
ein Fehlschlag hinterlässt eine ``.fail``-Markerdatei, damit kaputte Dateien
nicht bei jedem Seitenaufruf erneut probiert werden. Es wird **nie** in die DB
geschrieben — der Cache lebt komplett auf der Platte.
"""

from __future__ import annotations

import io
import os
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import Future, ProcessPoolExecutor, wait
from pathlib import Path

from .extract import psd
from .messages import dump as msg_dump
from .tools import find_binary
from PIL import Image, UnidentifiedImageError

DEFAULT_SIZE = 320

# Obergrenze für die Frame-Extraktion — ffmpeg liest nur den Anfang der Datei.
_FFMPEG_TIMEOUT = 60

# PSD ohne „Maximale Kompatibilität": kein flachgerechneter Composite, Pillow
# läse nur weiß (ADR 0052). Ehrlich als Fehlschlag behandeln statt Weiß zeigen.
# Als Meldungs-JSON (Block M.2, ADR 0054): der Grund landet in .fail-Markern,
# Scan-Problemen und im /api/preview-Fehler — übersetzt wird im Frontend.
_PSD_NO_COMPOSITE = msg_dump("thumbPsdNoComposite")


def thumb_path(cache_dir: str | Path, file_hash: str) -> Path:
    """Cache-Pfad eines Thumbnails: ``<cache>/<hash[:2]>/<hash>.jpg`` (sharded,
    damit nicht zehntausende Dateien in einem Ordner liegen)."""
    return Path(cache_dir) / file_hash[:2] / f"{file_hash}.jpg"


def _fail_marker(dest: Path) -> Path:
    return dest.with_suffix(".fail")


def fail_reason(cache_dir: str | Path, file_hash: str) -> str | None:
    """Grund des letzten endgültigen Fehlschlags — ``None``, wenn keiner vorliegt."""
    marker = _fail_marker(thumb_path(cache_dir, file_hash))
    if marker.is_file():
        return marker.read_text(encoding="utf-8", errors="replace").strip() or "unbekannter Grund"
    return None


def _thumb_worker_init(low_priority: bool = True) -> None:  # pragma: no cover
    """Worker auf niedrige Priorität setzen (leiser Betrieb, Standard) —
    oder mit ``low_priority=False`` volle Priorität („Vollgas-Modus":
    anmachen und vorm Krach zur Kaffeemaschine flüchten, Feral Strawberry 2026-07-07)."""
    if not low_priority:
        return
    try:
        if sys.platform == "win32":
            import ctypes

            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetPriorityClass(handle, 0x00004000)  # BELOW_NORMAL
        else:
            os.nice(10)
    except Exception:
        pass  # Priorität ist Komfort, kein Muss


class ThumbPool:
    """Parallele Thumbnail-Generierung über Prozesse (Block 4S, ADR 0020).

    Generierung ist CPU-/I/O-Arbeit ohne DB-Beteiligung — geschrieben wird nur
    in den Platten-Cache (atomar, ADR 0013), darum verträgt sich der Pool mit
    dem EINEN DB-Writer (ADR 0007). Der Executor entsteht lazy (Windows-spawn:
    kein Prozess-Start beim bloßen Import) und dedupliziert laufende Aufträge
    je Datei-Hash, damit wiederholte Kachel-Anfragen keine Doppelarbeit machen.

    Standard-Größe: Kerne−2 — moderne Vielkerner sollen den Rückstand mit
    voller Kraft aufholen (Feral Strawberry, 2026-07-07: Drosselung brachte nichts);
    die niedrige Prozess-Priorität hält den Rechner dabei bedienbar.
    Anders gewünscht? ``[cache] thumbnail_workers`` in der config.toml.
    """

    def __init__(self, workers: int | None = None, *, low_priority: bool = True) -> None:
        self.workers = workers or max(2, (os.cpu_count() or 4) - 2)
        self.low_priority = low_priority
        self._executor: ProcessPoolExecutor | None = None
        self._pending: dict[str, Future] = {}
        self._lock = threading.Lock()

    def submit(
        self, file_hash: str, source: str | Path, dest: Path,
        *, media_kind: str, size: int = DEFAULT_SIZE,
    ) -> Future:
        """Reihe die Generierung ein (oder liefere die schon laufende Future)."""
        with self._lock:
            running = self._pending.get(file_hash)
            if running is not None and not running.done():
                return running
            if self._executor is None:
                self._executor = ProcessPoolExecutor(
                    max_workers=self.workers, initializer=_thumb_worker_init,
                    initargs=(self.low_priority,),
                )
            future = self._executor.submit(
                generate_thumbnail, str(source), dest, media_kind=media_kind, size=size,
            )
            self._pending[file_hash] = future
        future.add_done_callback(lambda _f, h=file_hash: self._forget(h))
        return future

    def _forget(self, file_hash: str) -> None:
        with self._lock:
            self._pending.pop(file_hash, None)

    def shutdown(self) -> None:
        with self._lock:
            executor, self._executor = self._executor, None
            self._pending.clear()
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)


def generate_thumbnail(
    source: str | Path, dest: Path, *, media_kind: str, size: int = DEFAULT_SIZE
) -> bool:
    """Erzeuge das Thumbnail einer Mediendatei nach `dest` (atomar).

    Gibt ``True`` bei Erfolg zurück. Bei Fehlschlag (kaputte Datei, fehlendes
    ffmpeg, unbekannte Medienart) wird eine ``.fail``-Markerdatei mit dem Grund
    geschrieben und ``False`` zurückgegeben — kein Wurf, kein erneuter Versuch
    beim nächsten Aufruf von `ensure_thumbnail`.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + f".tmp{os.getpid()}")
    try:
        if media_kind == "image":
            ok, reason = _image_thumbnail(source, tmp, size)
        elif media_kind == "video":
            ok, reason = _video_thumbnail(source, tmp, size)
        else:
            ok, reason = False, msg_dump("thumbNoSupport", kind=media_kind)

        if ok:
            os.replace(tmp, dest)  # atomar — halbe Thumbnails gibt es nie
            return True
        _fail_marker(dest).write_text(reason, encoding="utf-8")
        return False
    finally:
        tmp.unlink(missing_ok=True)


def _image_thumbnail(source: str | Path, tmp: Path, size: int) -> tuple[bool, str]:
    try:
        with Image.open(source) as img:
            if img.format == "PSD" and not psd.has_real_composite(source):
                return False, _PSD_NO_COMPOSITE
            # Animierte Formate: Frame 0 ist der Poster-Frame (Steckbrief §4).
            img.thumbnail((size, size))
            img.convert("RGB").save(tmp, "JPEG", quality=85)
        return True, ""
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        return False, f"Pillow: {exc.__class__.__name__}: {exc}"


def render_preview(source: str | Path) -> tuple[bytes | None, str]:
    """Bilddatei in voller Größe als JPEG rendern (TIFF/PSD-Anzeige, ADR 0052).

    Gibt ``(jpeg_bytes, "")`` bei Erfolg zurück, ``(None, grund)`` bei
    Fehlschlag — wirft nicht (defensiv wie die Thumbnail-Strecke). Bei PSD
    liefert Pillow das eingebettete Composite, CMYK/Lab werden nach RGB
    konvertiert.
    """
    try:
        with Image.open(source) as img:
            if img.format == "PSD" and not psd.has_real_composite(source):
                return None, _PSD_NO_COMPOSITE
            img.load()
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "JPEG", quality=90)
        return buf.getvalue(), ""
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        return None, f"Pillow: {exc.__class__.__name__}: {exc}"


def _video_thumbnail(source: str | Path, tmp: Path, size: int) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [
                find_binary("ffmpeg") or "ffmpeg", "-v", "error", "-y",
                "-i", str(source),
                "-frames:v", "1",
                "-vf", f"scale='min({size},iw)':-2",
                "-f", "image2", str(tmp),
            ],
            capture_output=True,
            timeout=_FFMPEG_TIMEOUT,
        )
    except FileNotFoundError:
        return False, msg_dump("thumbNoFfmpeg")
    except subprocess.TimeoutExpired:
        return False, msg_dump("thumbFfmpegTimeout", seconds=_FFMPEG_TIMEOUT)
    if proc.returncode != 0 or not tmp.exists():
        # Mit stderr: roher Werkzeug-Text (Übergangsregel ADR 0054);
        # ohne: übersetzbarer Schlüssel statt festem deutschen Satz.
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        return False, (f"ffmpeg: {stderr}" if stderr
                       else msg_dump("thumbFfmpegNoFrame"))
    return True, ""


def ensure_thumbnail(
    conn: sqlite3.Connection,
    file_hash: str,
    cache_dir: str | Path,
    *,
    size: int = DEFAULT_SIZE,
) -> Path | None:
    """Liefere den Thumbnail-Pfad eines Items — generiere es bei Bedarf.

    Sucht einen noch existierenden Fundort der Datei und erzeugt das Thumbnail
    beim ersten Zugriff (on-demand). Gibt ``None`` zurück, wenn kein Thumbnail
    möglich ist (kein Fundort mehr, kaputte Datei, PDF, früherer Fehlschlag).
    Liest die DB nur — geschrieben wird ausschließlich in den Platten-Cache.
    """
    dest = thumb_path(cache_dir, file_hash)
    if dest.is_file():
        return dest
    if _fail_marker(dest).is_file():
        return None

    row = conn.execute(
        "SELECT media_kind FROM items WHERE file_hash = ?", (file_hash,)
    ).fetchone()
    if row is None:
        return None

    source = next(
        (
            path
            for (path,) in conn.execute(
                "SELECT path FROM file_locations WHERE file_hash = ? ORDER BY id",
                (file_hash,),
            )
            if Path(path).is_file()
        ),
        None,
    )
    if source is None:
        return None

    if generate_thumbnail(source, dest, media_kind=row["media_kind"], size=size):
        return dest
    return None


def warm_thumbnails(
    conn,
    cache_dir: str | Path,
    *,
    size: int = DEFAULT_SIZE,
    progress=None,
    pool: "ThumbPool | None" = None,
    retry_failed: bool = False,
) -> dict:
    """Fehlende Thumbnails erzeugen; Fehlgeschlagene nur auf Wunsch erneut.

    Läuft im Writer-Thread der Engine (schreibt Scan-Probleme!). Zwei Modi
    (ADR-0042-Ergänzung — der Automatik-Lauf machte sonst bei JEDEM
    Import-/Watch-Schub alle quittierten thumbnail-Probleme wieder auf):

    - ``retry_failed=False`` (Automatik nach Import/Watch): nur Items OHNE
      Thumbnail und OHNE ``.fail``-Marker; bekannte Fehlschläge und ihre
      quittierten Probleme bleiben unangetastet. Items ohne erreichbaren
      Fundort werden nur gezählt, nicht als Problem verbucht (sonst
      spammte jede Offline-Platte das Protokoll voll).
    - ``retry_failed=True`` (Admin-Knopf „Thumbnails erstellen"): vorhandene
      ``.fail``-Marker werden entfernt und neu versucht — wichtig, wenn
      ffmpeg erst nachträglich installiert wurde. Dauerhafte Fehlschläge
      landen mit Grund als Scan-Problem (kind ``thumbnail``), Erfolge
      quittieren sie.

    Mit ``pool`` (ADR 0020) läuft die Generierung parallel über Prozesse —
    in kleinen Schüben (2× Worker-Zahl), damit die Pool-Warteschlange kurz
    bleibt und On-Demand-Aufträge aus dem sichtbaren Grid schnell drankommen.
    Die DB-Arbeit bleibt hier beim Aufrufer (dem einen Writer, ADR 0007) und
    wird je Schub gebündelt committet.
    """
    from .scan import _record_issue

    cache = Path(cache_dir)
    rows = conn.execute(
        """SELECT i.file_hash, i.media_kind, l.path
             FROM items i
             LEFT JOIN file_locations l ON l.file_hash = i.file_hash
            ORDER BY i.first_seen_at DESC, l.id"""
    ).fetchall()
    # Fundorte je Item bündeln (Reihenfolge bleibt: neueste Items zuerst).
    candidates: dict[str, tuple[str, list[str]]] = {}
    for r in rows:
        kind, paths = candidates.setdefault(r["file_hash"], (r["media_kind"], []))
        if r["path"]:
            paths.append(r["path"])

    total = len(candidates)
    created = skipped = failed = 0
    done = 0

    def finish_one(file_hash: str, issue_path: str, ok: bool, *, record: bool = True) -> None:
        nonlocal created, failed
        if ok:
            created += 1
            conn.execute(
                "UPDATE scan_issues SET resolved = 1 WHERE path = ? AND kind = 'thumbnail'",
                (str(issue_path),),
            )
        else:
            failed += 1
            if record:
                reason = fail_reason(cache, file_hash) or msg_dump("thumbNoLocation")
                _record_issue(conn, Path(issue_path), "thumbnail", reason)

    def report() -> None:
        if progress is not None and (done % 25 == 0 or done == total):
            progress(done, total, created, skipped, failed)

    batch: list[tuple[Future, str, str]] = []   # (Future, hash, issue_path)
    batch_size = (pool.workers * 2) if pool is not None else 1

    def drain_batch() -> None:
        nonlocal done
        wait([f for (f, _h, _p) in batch])
        for future, file_hash, issue_path in batch:
            finish_one(file_hash, issue_path, bool(future.result()))
            done += 1
            report()
        conn.commit()
        batch.clear()

    for file_hash, (media_kind, paths) in candidates.items():
        dest = thumb_path(cache, file_hash)
        if dest.is_file():
            skipped += 1
            done += 1
            report()
            continue
        if retry_failed:
            _fail_marker(dest).unlink(missing_ok=True)   # erneuter Versuch (Admin-Knopf)
        elif _fail_marker(dest).is_file():
            skipped += 1   # bekannter Fehlschlag: Automatik lässt ihn in Ruhe
            done += 1
            report()
            continue
        source = next((p for p in paths if Path(p).is_file()), None)
        issue_path = source or (paths[0] if paths else file_hash)
        if source is None:
            # Kein Marker möglich (es gab keinen Versuch) — im Automatik-Lauf
            # nur zählen, sonst öffnete jeder Schub das Problem erneut.
            finish_one(file_hash, issue_path, ok=False, record=retry_failed)
            done += 1
            report()
            continue
        if pool is None:
            finish_one(
                file_hash, issue_path,
                ok=generate_thumbnail(source, dest, media_kind=media_kind, size=size),
            )
            done += 1
            report()
            conn.commit()
        else:
            batch.append((pool.submit(file_hash, source, dest, media_kind=media_kind, size=size),
                          file_hash, issue_path))
            if len(batch) >= batch_size:
                drain_batch()
    if batch:
        drain_batch()
    conn.commit()
    if progress is not None:
        progress(total, total, created, skipped, failed)
    return {"total": total, "created": created, "skipped": skipped, "failed": failed}
