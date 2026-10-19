"""Thumbnail-Pipeline (Stufe 2, ADR 0013).

Im Grid werden **nie** Originaldateien gezeigt, sondern vorab generierte
Thumbnails fester Größe (Projektziel: flüssiges Scrollen): einmal generiert, als JPEG im
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

import heapq
import io
import itertools
import logging
import os
import sqlite3
import subprocess
import threading
from concurrent.futures import CancelledError, Future, ProcessPoolExecutor, wait
from pathlib import Path

from .db.manual import has_embedded_picture
from .extract import jxr, pcd, psd
from .messages import dump as msg_dump
from .processes import ffmpeg_quiet_args
from .tools import NO_WINDOW, find_binary, media_input
from PIL import Image, UnidentifiedImageError
from PIL.PngImagePlugin import PngInfo

log = logging.getLogger(__name__)

DEFAULT_SIZE = 320

# Obergrenze für die Frame-Extraktion — ffmpeg liest nur den Anfang der Datei.
_FFMPEG_TIMEOUT = 60

# PSD ohne „Maximale Kompatibilität": kein flachgerechneter Composite, Pillow
# läse nur weiß (ADR 0052). Ehrlich als Fehlschlag behandeln statt Weiß zeigen.
# Als Meldungs-JSON (Block M.2, ADR 0054): der Grund landet in .fail-Markern,
# Scan-Problemen und im /api/preview-Fehler — übersetzt wird im Frontend.
_PSD_NO_COMPOSITE = msg_dump("thumbPsdNoComposite")
# JPEG XR dekodiert nur der Decoder von Windows (ADR 0104): auf anderen
# Systemen ist die Datei katalogisiert, aber ohne Bild.
_JXR_WINDOWS_ONLY = msg_dump("thumbJxrWindowsOnly")
JXR_MIME = "image/vnd.ms-photo"


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


def _thumb_worker_init(low_priority: bool = True, quiet: bool = False) -> None:  # pragma: no cover
    """Pool-Prozess einrichten: niedrige Priorität (Standard), mit
    ``low_priority=False`` volle („Vollgas-Modus": anmachen und vorm Krach
    zur Kaffeemaschine flüchten, Feral Strawberry 2026-07-07), mit ``quiet``
    Hintergrund für CPU, Platte und Speicher (Leise-Modus, ADR 0093)."""
    from .processes import init_pool_process

    init_pool_process(low_priority, quiet)   # keine Waisen (ADR 0067) + Priorität


class ThumbPool:
    """Parallele Thumbnail-Generierung über Prozesse (Block 4S, ADR 0020).

    Generierung ist CPU-/I/O-Arbeit ohne DB-Beteiligung — geschrieben wird nur
    in den Platten-Cache (atomar, ADR 0013), darum verträgt sich der Pool mit
    dem EINEN DB-Writer (ADR 0007). Der Executor entsteht lazy (Windows-spawn:
    kein Prozess-Start beim bloßen Import) und dedupliziert laufende Aufträge
    je Schlüssel, damit wiederholte Kachel-Anfragen keine Doppelarbeit machen.

    Vorrang (ADR 0093): Aufträge warten hier in einer Prioritäts-Schlange und
    gehen erst an den Executor, wenn ein Prozess frei ist — nie mehr als
    ``workers`` gleichzeitig. Kleinere ``priority`` zuerst (Kacheln 0,
    Analysen beim Blättern 1); mit einem Prozess stellen sich Analysen so
    hinter die sichtbaren Vorschaubilder, statt parallel zu starten.

    Größe: Automatik (``processes.default_workers``) oder ``[cache]
    thumbnail_workers``; ``reconfigure`` ändert Größe und Leise-Modus im
    laufenden Betrieb (neue Aufträge gehen an einen neuen Executor, der alte
    arbeitet seine angefangenen zu Ende).
    """

    def __init__(self, workers: int | None = None, *, low_priority: bool = True,
                 quiet: bool = False) -> None:
        from .processes import default_workers

        self.workers = workers or default_workers()
        self.low_priority = low_priority
        self.quiet = quiet
        self._executor: ProcessPoolExecutor | None = None
        self._pending: dict[str, Future] = {}
        self._queue: list = []          # Heap: (priority, seq, key, fn, args, kwargs, proxy)
        self._seq = itertools.count()
        self._active = 0                # an einen Executor übergeben, noch nicht fertig
        self._lock = threading.Lock()

    def submit(
        self, file_hash: str, source: str | Path, dest: Path,
        *, media_kind: str, size: int = DEFAULT_SIZE,
        tone: jxr.Tone = jxr.Tone(), preview_cache: str | Path | None = None,
    ) -> Future:
        """Reihe die Generierung ein (oder liefere die schon laufende Future).
        ``tone``/``preview_cache`` betreffen nur JXR (``generate_thumbnail``)."""
        return self.submit_call(file_hash, generate_thumbnail, str(source), dest,
                                media_kind=media_kind, size=size, tone=tone,
                                preview=jxr_preview_file(preview_cache, file_hash, tone))

    def submit_call(self, key: str, fn, *args, priority: int = 0, **kwargs) -> Future:
        """Beliebige reine Cache-Arbeit (picklebare Modulfunktion) einreihen,
        dedupliziert über ``key`` — auch die Audio-Analyse und der
        Wiedergabe-Proxy (A4, ADR 0086) laufen über diesen Pool."""
        with self._lock:
            running = self._pending.get(key)
            if running is not None and not running.done():
                return running
            proxy: Future = Future()
            self._pending[key] = proxy
            heapq.heappush(self._queue, (priority, next(self._seq), key, fn, args, kwargs, proxy))
        self._pump()
        return proxy

    def _pump(self) -> None:
        """Wartende Aufträge an den Executor geben, solange Prozesse frei sind."""
        while True:
            with self._lock:
                if not self._queue or self._active >= self.workers:
                    return
                _prio, _seq, key, fn, args, kwargs, proxy = heapq.heappop(self._queue)
                if not proxy.set_running_or_notify_cancel():
                    self._drop(key, proxy)
                    continue
                if self._executor is None:
                    self._executor = ProcessPoolExecutor(
                        max_workers=self.workers, initializer=_thumb_worker_init,
                        initargs=(self.low_priority, self.quiet),
                    )
                try:
                    inner = self._executor.submit(fn, *args, **kwargs)
                except Exception as exc:   # Pool kaputt: ehrlich melden, nicht hängen
                    self._drop(key, proxy)
                    proxy.set_exception(exc)
                    continue
                self._active += 1
            inner.add_done_callback(lambda f, k=key, p=proxy: self._done(k, p, f))

    def _drop(self, key: str, proxy: Future) -> None:
        if self._pending.get(key) is proxy:
            del self._pending[key]

    def _done(self, key: str, proxy: Future, inner: Future) -> None:
        with self._lock:
            self._active -= 1
            self._drop(key, proxy)
        if inner.cancelled():
            proxy.set_exception(CancelledError())
        elif inner.exception() is not None:
            proxy.set_exception(inner.exception())
        else:
            proxy.set_result(inner.result())
        self._pump()

    def reconfigure(self, workers: int, *, quiet: bool, low_priority: bool | None = None) -> None:
        """Größe/Leise-Modus sofort ändern (ADR 0093)."""
        with self._lock:
            low = self.low_priority if low_priority is None else low_priority
            if (workers, quiet, low) == (self.workers, self.quiet, self.low_priority):
                return
            self.workers, self.quiet, self.low_priority = workers, quiet, low
            old, self._executor = self._executor, None
        if old is not None:
            old.shutdown(wait=False, cancel_futures=False)
        self._pump()

    def shutdown(self) -> None:
        with self._lock:
            executor, self._executor = self._executor, None
            queued, self._queue = self._queue, []
            self._pending.clear()
        for item in queued:
            item[-1].cancel()
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)


def generate_thumbnail(
    source: str | Path, dest: Path, *, media_kind: str, size: int = DEFAULT_SIZE,
    tone: jxr.Tone = jxr.Tone(), preview: Path | None = None,
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
            ok, reason = _image_thumbnail(source, tmp, size, tone, preview)
        elif media_kind in ("video", "audio"):
            # Audio (#165): das eingebettete Cover — ffmpeg führt es als
            # einzige Bildspur, der „erste Frame" ist das Bild.
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


def jxr_preview_file(preview_cache: str | Path | None, file_hash: str,
                     tone: jxr.Tone) -> Path | None:
    """Wo das Anzeigebild einer JXR liegt (``None`` ohne Vorschau-Cache)."""
    if not preview_cache:
        return None
    return preview_cache_file(preview_cache, file_hash, tone.variant())


def _render_jxr(source: str | Path, tone: jxr.Tone, preview: Path | None = None,
                ) -> tuple[Image.Image | None, str]:
    """JXR als SDR-Bild (ADR 0104); ``(None, grund)``, wenn es nicht geht.

    Mit ``preview`` (Platz des Anzeigebilds im Vorschau-Cache) wird nur EINMAL
    gerechnet: Liegt das PNG schon dort, kommt das Bild von dort; sonst wird
    es nach dem Rechnen dort abgelegt. Vorschaubild und Einzelansicht teilen
    sich so eine Dekodierung (ADR 0104 Punkt 6)."""
    if preview is not None and preview.is_file():
        try:
            with Image.open(preview) as cached:
                cached.load()
                return cached.convert("RGB"), ""
        except (UnidentifiedImageError, OSError, ValueError):
            pass                            # kaputtes Cache-Bild: neu rechnen
    try:
        img = jxr.render(source, tone)
    except jxr.JxrUnsupported:
        return None, _JXR_WINDOWS_ONLY
    except (jxr.JxrError, OSError, MemoryError) as exc:
        return None, f"JPEG XR: {exc.__class__.__name__}: {exc}"
    if preview is not None:
        try:
            # Cache-Dateien heißen <hash>[.<variante>].png.
            _save_jxr_png(img, source, preview, tone, preview.name.split(".", 1)[0])
        except OSError as exc:              # Cache voll o. Ä.: das Bild gibt es trotzdem
            log.warning("jxr: preview not stored: %s", exc)
    return img, ""


def _save_jxr_png(img: Image.Image, source: str | Path, dest: Path, tone: jxr.Tone,
                  file_hash: str | None) -> None:
    """Anzeigebild als PNG ablegen (atomar), mit seiner Herkunft als
    Textfeldern."""
    info = PngInfo()
    for key, value in jxr.provenance(source, file_hash, tone).items():
        info.add_text(key, value)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + f".tmp{os.getpid()}")
    try:
        img.save(tmp, "PNG", compress_level=3, pnginfo=info)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def _image_thumbnail(source: str | Path, tmp: Path | io.BytesIO, size: int,
                     tone: jxr.Tone = jxr.Tone(), preview: Path | None = None,
                     quality: int = 85) -> tuple[bool, str]:
    if jxr.is_jxr_file(source):
        img, reason = _render_jxr(source, tone, preview)
        if img is None:
            return False, reason
        img.thumbnail((size, size))
        img.save(tmp, "JPEG", quality=quality)
        return True, ""
    try:
        with Image.open(source) as img:
            if img.format == "PSD" and not psd.has_real_composite(source):
                return False, _PSD_NO_COMPOSITE
            if img.format == "PCD":
                # Base (768×512) genügt bis zu dieser Kantenlänge, größere
                # Thumbnails dekodieren 16Base (#208).
                img = pcd.render(source, max_factor=1 if size <= pcd.BASE_W else 4)
            # Animierte Formate: Frame 0 ist der Poster-Frame.
            img.thumbnail((size, size))
            img.convert("RGB").save(tmp, "JPEG", quality=quality)
        return True, ""
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        return False, f"Pillow: {exc.__class__.__name__}: {exc}"


COVER_SIZE = 1200   # längste Kante des Covers in einer exportierten Kopie (ADR 0107)


def cover_jpeg(source: str | Path, *, size: int = COVER_SIZE,
               tone: jxr.Tone = jxr.Tone()) -> tuple[bytes | None, str]:
    """Coverbild für die Kopie eines Songs (ADR 0107 Punkt 7): JPEG,
    längste Kante ``size``, nie vergrößert, Qualität 90 — dieselbe Strecke
    wie die Thumbnails (PSD, Photo CD, JXR inklusive). ``(None, grund)``
    bei Fehlschlag, wirft nicht."""
    buf = io.BytesIO()
    ok, reason = _image_thumbnail(source, buf, size, tone, quality=90)
    return (buf.getvalue(), "") if ok else (None, reason)


def render_preview(source: str | Path, *,
                   tone: jxr.Tone = jxr.Tone()) -> tuple[bytes | None, str]:
    """Bilddatei in voller Größe als JPEG rendern (TIFF/PSD/PCD-Anzeige, ADR 0052).

    Gibt ``(jpeg_bytes, "")`` bei Erfolg zurück, ``(None, grund)`` bei
    Fehlschlag — wirft nicht (defensiv wie die Thumbnail-Strecke). Bei PSD
    liefert Pillow das eingebettete Composite, CMYK/Lab werden nach RGB
    konvertiert.
    """
    if jxr.is_jxr_file(source):
        img, reason = _render_jxr(source, tone)
        if img is None:
            return None, reason
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        return buf.getvalue(), ""
    try:
        with Image.open(source) as img:
            if img.format == "PSD" and not psd.has_real_composite(source):
                return None, _PSD_NO_COMPOSITE
            if img.format == "PCD":
                img = pcd.render(source)    # 16Base statt Pillows Base (#208)
            img.load()
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "JPEG", quality=90)
        return buf.getvalue(), ""
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        return None, f"Pillow: {exc.__class__.__name__}: {exc}"


# Anzeigebilder, deren Rendern spürbar dauert (Photo CD 16Base ≈ 1,6 s,
# JXR in 4K ≈ 1,8 s), werden einmal verlustfrei als PNG abgelegt (#208,
# ADR 0104) — TIFF/PSD rendern schnell genug on the fly.
PREVIEW_CACHED_MIMES = frozenset({"image/x-photo-cd", JXR_MIME})


def preview_variant(container_or_mime: str | None, tone: jxr.Tone) -> str:
    """Zusatz im Cache-Schlüssel für Formate, deren Anzeigebild von einer
    Einstellung abhängt: bei JXR Papierweiß und Knie, sonst leer."""
    return tone.variant() if container_or_mime in ("jxr", JXR_MIME) else ""


def preview_cache_file(cache_dir: str | Path, file_hash: str, variant: str = "") -> Path:
    """``<cache>/<hash[:2]>/<hash>[.<variante>].png`` (sharded wie die
    Thumbnails)."""
    name = f"{file_hash}.{variant}.png" if variant else f"{file_hash}.png"
    return Path(cache_dir) / file_hash[:2] / name


def write_preview(source: str | Path, dest: Path, *,
                  tone: jxr.Tone = jxr.Tone(), file_hash: str | None = None) -> str:
    """Anzeigebild einmal verlustfrei ablegen (PNG, atomar); ``""`` bei
    Erfolg, sonst der Grund. Läuft im Thumbnail-Pool (picklebar). Ein
    JXR-Bild trägt als Textfelder, woraus es entstand (``file_hash``)."""
    if jxr.is_jxr_file(source):
        img, reason = _render_jxr(source, tone)
        if img is None:
            return reason
        try:
            _save_jxr_png(img, source, dest, tone, file_hash)
        except OSError as exc:
            return f"JPEG XR: {exc.__class__.__name__}: {exc}"
        return ""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + f".tmp{os.getpid()}")
    try:
        with Image.open(source) as img:
            if img.format == "PCD":
                img = pcd.render(source)
            img.convert("RGB").save(tmp, "PNG", compress_level=3)
        os.replace(tmp, dest)
        return ""
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        return f"Pillow: {exc.__class__.__name__}: {exc}"
    finally:
        tmp.unlink(missing_ok=True)


def _video_thumbnail(source: str | Path, tmp: Path, size: int) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [
                find_binary("ffmpeg") or "ffmpeg", "-v", "error", "-y",
                *ffmpeg_quiet_args(),   # Leise: ein Thread (ADR 0093)
                *media_input(source),
                "-frames:v", "1",
                "-vf", f"scale='min({size},iw)':-2",
                "-f", "image2", str(tmp),
            ],
            capture_output=True,
            timeout=_FFMPEG_TIMEOUT,
            **NO_WINDOW,
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
    if row["media_kind"] == "audio" and not has_embedded_picture(conn, file_hash):
        # Audio hat kein eigenes Vorschaubild (ADR 0083); nur ein
        # eingebettetes Cover wird eins (#165, fürs Detailpanel) — ohne
        # Bild auch kein Fehlschlag-Marker.
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
    tone: jxr.Tone = jxr.Tone(),
    preview_cache: str | Path | None = None,
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
            WHERE i.media_kind != 'audio'   -- kein Vorschaubild (ADR 0083)
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
                ok=generate_thumbnail(source, dest, media_kind=media_kind, size=size,
                                      tone=tone, preview=jxr_preview_file(
                                          preview_cache, file_hash, tone)),
            )
            done += 1
            report()
            conn.commit()
        else:
            batch.append((pool.submit(file_hash, source, dest, media_kind=media_kind, size=size,
                                      tone=tone, preview_cache=preview_cache),
                          file_hash, issue_path))
            # Schubgröße je Runde neu: Leise/Normal wirkt mitten im Lauf (ADR 0093).
            if len(batch) >= pool.workers * 2:
                drain_batch()
    if batch:
        drain_batch()
    conn.commit()
    if progress is not None:
        progress(total, total, created, skipped, failed)
    return {"total": total, "created": created, "skipped": skipped, "failed": failed}
