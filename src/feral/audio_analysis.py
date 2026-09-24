"""Abgeleitete Audio-Daten (A4 #161, ADR 0083 Punkt 10, ADR 0086).

Muster Thumbnails (ADR 0013/0020): hash-basiert im Platten-Cache, einmal
erzeugt, immer wiederverwendet, jederzeit neu erzeugbar (Rescan-Prinzip).
Es wird **nie** in die DB und **nie** in die Originaldatei geschrieben.

- **Analyse** (``<cache>/<hash[:2]>/<hash>.json``): Lautheit nach EBU R128
  (integriert, LRA, True Peak — ``ebur128=peak=true``, nicht ``loudnorm``,
  das rechnet intern mit 192 kHz und ist 6× langsamer; Recherche §11) und
  eine **dreibandige Wellenform** (Bass/Mitten/Höhen wie DJ-Software) als
  Min/Max-Buckets. Beides in EINEM ffmpeg-Lauf: ``asplit`` → ein Zweig
  misst, der andere wird Mono/22 kHz, per Tief-/Band-/Hochpass zerlegt und
  als 3-Kanal-PCM gestreamt. Die Buckets entstehen streamend über
  ``array('h')`` (ohne numpy), der Speicher bleibt auch bei Stunden klein.
- **Wiedergabe-Proxy** (``<hash>.flac``): verlustfreies FLAC für Formate,
  die Browser nicht abspielen (AIFF und ALAC nur Safari, CAF keiner;
  Recherche §10) — erst beim ersten Abspielen und nur, wenn der
  abspielende Browser das Format nicht selbst kann (ADR 0086). Nur die
  erste Tonspur, ohne Metadaten und Cover — der Proxy ist Wiedergabe,
  nicht Archiv; die Metadaten stehen im Original.

Defensiv wie die Thumbnail-Strecke: geschrieben wird atomar (Tempdatei +
rename), ein Fehlschlag hinterlässt eine ``.fail``-Markerdatei mit dem
Grund (Meldungs-JSON oder roher Werkzeug-Text), damit kaputte Dateien
nicht bei jedem Aufruf erneut probiert werden.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from array import array
from pathlib import Path
from typing import Any

from .messages import dump as msg_dump
from .tools import find_binary, media_input

# Format-Version der Analyse-Datei. Anheben, wenn sich Inhalt oder Form
# ändern: ältere Dateien gelten dann als fehlend und werden neu erzeugt.
ANALYSIS_VERSION = 1

# Zielauflösung der Wellenform (Recherche §11). Kürzere Stücke behalten
# ihre feinere Rohauflösung nicht — auf der gemeinsamen Zeitachse der
# Liste (ADR 0083 Punkt 5) ist ein kurzes Stück ohnehin schmal.
BUCKETS = 1000

# Bänder (Name, ffmpeg-Filter) — Übergänge bei 200 Hz und 2 kHz: Bass/Kick
# unten, Stimme und Harmonie in der Mitte, Becken/Zischlaute oben.
BANDS: tuple[tuple[str, str], ...] = (
    ("low", "lowpass=f=200"),
    ("mid", "highpass=f=200,lowpass=f=2000"),
    ("high", "highpass=f=2000"),
)
_RATE = 22050      # Nyquist 11 kHz: genug Höhen für die Anzeige, ein Viertel der Daten von 48 kHz
_FINE = 256        # Frames je Rohbucket (≈ 12 ms)

# Formate, die ein Browser nicht (überall) abspielt → Proxy. Container aus
# der Magic-Byte-Erkennung, Codec aus dem audio-Parser (Schicht 2). Der
# Name ist zugleich das, was ein Browser per ``?native=`` als „kann ich
# selbst" meldet (Safari: aiff, alac; CAF spielt keiner).
_PROXY_CONTAINERS = frozenset({"aiff", "caf"})
_PROXY_CODECS = frozenset({"alac"})

_TIMEOUT = 600     # Sekunden je Datei; eine Stunde Aufnahme braucht auf dem Heimserver ~1 min


def cache_path(cache_dir: str | Path, file_hash: str, suffix: str) -> Path:
    """``<cache>/<hash[:2]>/<hash><suffix>`` (sharded wie die Thumbnails)."""
    return Path(cache_dir) / file_hash[:2] / f"{file_hash}{suffix}"


def analysis_path(cache_dir: str | Path, file_hash: str) -> Path:
    return cache_path(cache_dir, file_hash, ".json")


def proxy_path(cache_dir: str | Path, file_hash: str) -> Path:
    return cache_path(cache_dir, file_hash, ".flac")


def fail_marker(dest: Path) -> Path:
    """Marker neben dem Produkt: ``<hash>.json.fail`` bzw. ``<hash>.flac.fail``
    — Analyse und Proxy scheitern unabhängig voneinander."""
    return dest.with_name(dest.name + ".fail")


def fail_reason(dest: Path) -> str | None:
    marker = fail_marker(dest)
    if marker.is_file():
        return marker.read_text(encoding="utf-8", errors="replace").strip() or "?"
    return None


def proxy_format(container: str | None, codec: str | None) -> str | None:
    """Das Format, dessentwegen ein Item einen Proxy braucht (``aiff``,
    ``caf``, ``alac``) — ``None``, wenn jeder Browser das Original spielt."""
    if container in _PROXY_CONTAINERS:
        return container
    codec = (codec or "").lower()
    return codec if codec in _PROXY_CODECS else None


def needs_proxy(container: str | None, codec: str | None,
                native: frozenset[str] | set[str] = frozenset()) -> bool:
    """Braucht dieses Audio-Item einen Wiedergabe-Proxy — für einen Browser,
    der die Formate in ``native`` selbst abspielt?"""
    fmt = proxy_format(container, codec)
    return fmt is not None and fmt not in native


def read_analysis(dest: Path) -> dict[str, Any] | None:
    """Gültige Analyse aus dem Cache — ``None`` bei fehlend, kaputt oder
    veralteter Version (dann wird neu erzeugt)."""
    try:
        data = json.loads(dest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("version") == ANALYSIS_VERSION else None


# -- Lautheit ------------------------------------------------------------------

_NUM = r"(-?\d+(?:\.\d+)?|-?inf)"
_RE_I = re.compile(r"^\s*I:\s+" + _NUM + r"\s+LUFS", re.M)
_RE_LRA = re.compile(r"^\s*LRA:\s+" + _NUM + r"\s+LU\b", re.M)
_RE_PEAK = re.compile(r"^\s*Peak:\s+" + _NUM + r"\s+dBFS", re.M)


def _num(match: re.Match | None) -> float | None:
    if match is None or "inf" in match.group(1):
        return None
    return float(match.group(1))


def parse_ebur128(stderr: str) -> dict[str, float | None] | None:
    """Den ``Summary:``-Block von ``ebur128`` lesen (letzter Block zählt).

    ``-inf`` (Stille) wird ``None``. ``None`` insgesamt, wenn kein Block da
    ist (ffmpeg brach vorher ab)."""
    at = stderr.rfind("Summary:")
    if at < 0:
        return None
    block = stderr[at:]
    return {
        "integrated": _num(_RE_I.search(block)),
        "lra": _num(_RE_LRA.search(block)),
        "true_peak": _num(_RE_PEAK.search(block)),
    }


# -- Wellenform ----------------------------------------------------------------

class _Buckets:
    """Streamender Min/Max-Sammler über interleavte s16-Frames je Band."""

    def __init__(self, bands: int) -> None:
        self.bands = bands
        self.mins = [array("h") for _ in range(bands)]
        self.maxs = [array("h") for _ in range(bands)]
        self.frames = 0
        self._rest = b""
        self._swap = sys.byteorder != "little"

    def feed(self, data: bytes) -> None:
        step = self.bands * 2 * _FINE
        data = self._rest + data
        whole = len(data) - len(data) % step
        self._rest = data[whole:]
        if whole:
            self._consume(data[:whole])

    def close(self) -> None:
        # Angebrochener letzter Bucket (nur ganze Frames).
        frame = self.bands * 2
        tail = self._rest[: len(self._rest) - len(self._rest) % frame]
        self._rest = b""
        if tail:
            self._consume(tail)

    def _consume(self, data: bytes) -> None:
        samples = array("h")
        samples.frombytes(data)
        if self._swap:
            samples.byteswap()
        n = self.bands
        span = n * _FINE
        for start in range(0, len(samples), span):
            chunk = samples[start:start + span]
            for b in range(n):
                s = chunk[b::n]
                self.mins[b].append(min(s))
                self.maxs[b].append(max(s))
        self.frames += len(samples) // n


def reduce_buckets(mins: array, maxs: array, buckets: int = BUCKETS) -> tuple[list[int], list[int]]:
    """Rohbuckets auf höchstens ``buckets`` verdichten (Min der Mins, Max der Maxs)."""
    n = len(mins)
    if n <= buckets:
        return list(mins), list(maxs)
    out_min, out_max = [], []
    for i in range(buckets):
        lo, hi = i * n // buckets, (i + 1) * n // buckets
        out_min.append(min(mins[lo:hi]))
        out_max.append(max(maxs[lo:hi]))
    return out_min, out_max


def _filter_graph() -> str:
    names = [name for name, _ in BANDS]
    split = "".join(f"[{n}]" for n in names)
    bands = ";".join(f"[{n}]{flt}[{n}o]" for n, flt in BANDS)
    merged = "".join(f"[{n}o]" for n in names)
    return (
        "[0:a:0]asplit=2[meter][wave];"
        "[meter]ebur128=peak=true:framelog=quiet,anullsink;"
        f"[wave]aformat=channel_layouts=mono,aresample={_RATE},asplit={len(BANDS)}{split};"
        f"{bands};"
        # join statt amerge: drei Mono-Eingänge hätten gleiche Layouts, die
        # amerge nicht zuordnen kann; join legt sie fest auf FL/FR/FC.
        f"{merged}join=inputs={len(BANDS)}:channel_layout=3.0:map=0.0-FL|1.0-FR|2.0-FC,"
        "aformat=sample_fmts=s16[out]"
    )


def analyze(source: str | Path) -> tuple[dict[str, Any] | None, str]:
    """Lautheit + dreibandige Wellenform einer Audiodatei in einem ffmpeg-Lauf.

    ``(daten, "")`` bei Erfolg, ``(None, grund)`` bei Fehlschlag — wirft nicht.
    """
    cmd = [
        find_binary("ffmpeg") or "ffmpeg", "-nostdin", "-hide_banner", "-nostats",
        "-v", "info", *media_input(source),
        "-filter_complex", _filter_graph(),
        "-map", "[out]", "-f", "s16le", "-c:a", "pcm_s16le", "pipe:1",
    ]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        return None, msg_dump("thumbNoFfmpeg")

    # stderr parallel leeren — sonst blockiert ffmpeg bei vielen Warnungen,
    # während hier auf stdout gewartet wird.
    err_parts: list[bytes] = []
    reader = threading.Thread(target=lambda: err_parts.append(proc.stderr.read()), daemon=True)
    reader.start()
    timed_out = threading.Event()

    def kill() -> None:
        timed_out.set()
        proc.kill()

    timer = threading.Timer(_TIMEOUT, kill)
    timer.start()
    buckets = _Buckets(len(BANDS))
    try:
        while True:
            data = proc.stdout.read(len(BANDS) * 2 * _FINE * 64)
            if not data:
                break
            buckets.feed(data)
        buckets.close()
        proc.wait()
    finally:
        timer.cancel()
        reader.join(timeout=5)
    stderr = b"".join(err_parts).decode("utf-8", errors="replace")

    if timed_out.is_set():
        return None, msg_dump("thumbFfmpegTimeout", seconds=_TIMEOUT)
    loudness = parse_ebur128(stderr)
    if proc.returncode != 0 or loudness is None:
        tail = "\n".join(line for line in stderr.strip().splitlines()[-3:])
        return None, f"ffmpeg: {tail}" if tail else msg_dump("audioAnalysisFailed")

    waveform: dict[str, Any] = {}
    for b, (name, _) in enumerate(BANDS):
        lo, hi = reduce_buckets(buckets.mins[b], buckets.maxs[b])
        waveform[name] = {"min": lo, "max": hi}
    count = len(waveform[BANDS[0][0]]["min"])
    duration = buckets.frames / _RATE
    return {
        "version": ANALYSIS_VERSION,
        "duration": round(duration, 3),
        "loudness": loudness,
        "waveform": {
            "buckets": count,
            "seconds_per_bucket": round(duration / count, 6) if count else 0,
            "bands": [name for name, _ in BANDS],
            "crossover_hz": [200, 2000],
            **waveform,
        },
    }, ""


# -- Erzeugen (atomar, mit Fehlschlag-Marker) ----------------------------------------

def _write_atomic(dest: Path, produce) -> bool:
    """``produce(tmp) -> (ok, grund)`` schreibt nach ``tmp``; Erfolg wird
    per rename veröffentlicht, Fehlschlag als Marker festgehalten."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + f".tmp{os.getpid()}")
    try:
        ok, reason = produce(tmp)
        if ok:
            os.replace(tmp, dest)     # atomar — halbe Dateien gibt es nie
            fail_marker(dest).unlink(missing_ok=True)
            return True
        fail_marker(dest).write_text(reason, encoding="utf-8")
        return False
    finally:
        tmp.unlink(missing_ok=True)


def generate_analysis(source: str | Path, dest: Path) -> bool:
    """Analyse nach ``dest`` (JSON). Pool-tauglich (Modulfunktion, picklebar)."""
    def produce(tmp: Path) -> tuple[bool, str]:
        data, reason = analyze(source)
        if data is None:
            return False, reason
        tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        return True, ""
    return _write_atomic(dest, produce)


def generate_proxy(source: str | Path, dest: Path) -> bool:
    """Verlustfreien FLAC-Proxy nach ``dest``. Pool-tauglich."""
    def produce(tmp: Path) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                [find_binary("ffmpeg") or "ffmpeg", "-nostdin", "-v", "error", "-y",
                 *media_input(source), "-map", "0:a:0", "-map_metadata", "-1",
                 "-c:a", "flac", "-f", "flac", str(tmp)],
                capture_output=True, timeout=_TIMEOUT,
            )
        except FileNotFoundError:
            return False, msg_dump("thumbNoFfmpeg")
        except subprocess.TimeoutExpired:
            return False, msg_dump("thumbFfmpegTimeout", seconds=_TIMEOUT)
        if proc.returncode != 0 or not tmp.is_file():
            stderr = proc.stderr.decode("utf-8", errors="replace").strip()
            return False, f"ffmpeg: {stderr}" if stderr else msg_dump("audioProxyFailed")
        return True, ""
    return _write_atomic(dest, produce)


# -- Vorwärmen (Worker-Aufgabe audio_warm) ----------------------------------------

def audio_items(conn) -> dict[str, tuple[str, str | None, list[str]]]:
    """Alle Audio-Items: Hash → (Container, Codec, Fundorte), neueste zuerst.
    Der Codec kommt aus Schicht 2 (``audio_codec`` des audio-Parsers)."""
    rows = conn.execute(
        """SELECT i.file_hash, i.container, l.path,
                  (SELECT m.value_text FROM interpreted_metadata m
                    WHERE m.file_hash = i.file_hash AND m.field = 'audio_codec'
                    ORDER BY m.id LIMIT 1) AS codec
             FROM items i
             LEFT JOIN file_locations l ON l.file_hash = i.file_hash
            WHERE i.media_kind = 'audio'
            ORDER BY i.first_seen_at DESC, l.id"""
    ).fetchall()
    out: dict[str, tuple[str, str | None, list[str]]] = {}
    for r in rows:
        _c, _k, paths = out.setdefault(r["file_hash"], (r["container"], r["codec"], []))
        if r["path"]:
            paths.append(r["path"])
    return out


def warm_audio(conn, cache_dir: str | Path, *, progress=None, pool=None,
               retry_failed: bool = False) -> dict[str, int]:
    """Fehlende Analysen erzeugen (Muster ``warm_thumbnails``).

    Proxies entstehen hier NICHT: nur beim ersten Abspielen in einem
    Browser, der das Format nicht kann (ADR 0086) — keine Kopie von etwas,
    das nie oder nur in Safari gehört wird.

    ``retry_failed=False`` (Automatik nach Import/Watch/Einschalten): nur
    Fehlendes ohne Marker. ``retry_failed=True`` (Admin-Knopf): Marker weg,
    erneut versuchen — bei Proxies nur den Marker, der nächste Abspielversuch
    erzeugt neu; dauerhafte Analyse-Fehlschläge werden Scan-Probleme der Art
    ``audio``, Erfolge quittieren sie. Veraltete Analyse-Versionen gelten
    immer als fehlend. Mit ``pool`` parallel in kleinen Schüben.
    """
    from concurrent.futures import wait

    from .scan import _record_issue

    cache = Path(cache_dir)
    items = audio_items(conn)
    jobs: list[tuple[str, str | None, str, Path, Any]] = []   # (hash, source, issue_path, dest, fn)
    skipped = 0
    for file_hash, (_container, _codec, paths) in items.items():
        if retry_failed:
            fail_marker(proxy_path(cache, file_hash)).unlink(missing_ok=True)
        dest = analysis_path(cache, file_hash)
        if read_analysis(dest) is not None:
            skipped += 1
            continue
        if retry_failed:
            fail_marker(dest).unlink(missing_ok=True)
        elif fail_marker(dest).is_file():
            skipped += 1
            continue
        source = next((p for p in paths if Path(p).is_file()), None)
        jobs.append((file_hash, source, source or (paths[0] if paths else file_hash),
                     dest, generate_analysis))

    total = len(jobs) + skipped
    created = failed = 0
    index = skipped

    def report() -> None:
        if progress is not None and (index % 10 == 0 or index == total):
            progress(index, total, created, skipped, failed)

    def finish(issue_path: str, ok: bool, reason: str | None = None) -> None:
        nonlocal created, failed, index
        index += 1
        if ok:
            created += 1
            conn.execute("UPDATE scan_issues SET resolved = 1 WHERE path = ? AND kind = 'audio'",
                         (str(issue_path),))
        else:
            failed += 1
            if retry_failed:   # Automatik zählt nur (sonst öffnete jeder Schub Probleme neu)
                _record_issue(conn, Path(issue_path), "audio", reason or msg_dump("thumbNoLocation"))
        report()

    batch: list[tuple[Any, str, Path]] = []
    batch_size = (pool.workers * 2) if pool is not None else 1

    def drain() -> None:
        wait([f for f, _p, _d in batch])
        for future, issue_path, dest in batch:
            ok = bool(future.result())
            finish(issue_path, ok, None if ok else fail_reason(dest))
        conn.commit()
        batch.clear()

    report()
    for file_hash, source, issue_path, dest, fn in jobs:
        if source is None:
            finish(issue_path, False)   # kein Fundort: kein Versuch, kein Marker
            continue
        if pool is None:
            ok = fn(source, dest)
            finish(issue_path, ok, None if ok else fail_reason(dest))
            conn.commit()
        else:
            key = f"{dest.suffix}:{file_hash}"
            batch.append((pool.submit_call(key, fn, source, dest), issue_path, dest))
            if len(batch) >= batch_size:
                drain()
    if batch:
        drain()
    conn.commit()
    if progress is not None:
        progress(total, total, created, skipped, failed)
    return {"total": total, "created": created, "skipped": skipped, "failed": failed}
