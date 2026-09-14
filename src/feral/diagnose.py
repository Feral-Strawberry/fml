"""Diagnose-Kommandos über den Bestand — ohne Dateisuche, ohne Neu-Scan.

    python -m feral.diagnose video-codecs --db ./feral.sqlite [--min-size 1G]
    python -m feral.diagnose video-codecs --db ./feral.sqlite --from-db

``video-codecs`` (Issue #71, ADR 0070) beantwortet „welcher Codec steckt in
meinen Videos?" für den ganzen Bestand auf einmal: Es läuft über die
Fundorte aller Videos, ruft ``ffprobe`` NUR auf den Header (``-show_streams
-select_streams v:0`` — auch bei 4 GB unter einer Sekunde) und druckt eine
Tabelle Codec · Profil · Pixelformat · Browser · Anzahl · Beispielpfad.
Nichts wird in die DB geschrieben. ``--from-db`` liest stattdessen die
Schicht-2-Felder (``video_codec`` …), sobald der Bestand einmal neu gescannt
ist — dann ohne ffprobe und in Sekundenbruchteilen.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .db import connect
from .extract.video_ffprobe import video_stream_facts
from .interpret.video import browser_support
from .tools import find_binary

_TIMEOUT_SECONDS = 30
_SIZE_UNITS = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}


def parse_size(text: str) -> int:
    """``1G`` / ``500M`` / ``2048`` → Bytes (Suffix k/m/g/t, groß/klein egal)."""
    t = text.strip().lower().rstrip("b")
    unit = t[-1] if t and t[-1] in _SIZE_UNITS else ""
    number = t[:-1] if unit else t
    try:
        return int(float(number) * _SIZE_UNITS[unit])
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"ungültige Größe: {text!r}") from exc


@dataclass
class CodecGroup:
    codec: str
    profile: str
    pix_fmt: str
    count: int = 0
    example: str = ""

    @property
    def browser(self) -> str:
        return browser_support(self.codec, self.profile, self.pix_fmt)


@dataclass
class CodecReport:
    groups: dict[tuple[str, str, str], CodecGroup] = field(default_factory=dict)
    videos_total: int = 0
    probed: int = 0
    missing: int = 0          # kein Fundort auf der Platte
    failed: list[tuple[str, str]] = field(default_factory=list)   # (pfad, grund)

    def add(self, facts: dict[str, str], path: str) -> None:
        key = (facts.get("codec_name", "?"), facts.get("profile", ""), facts.get("pix_fmt", ""))
        group = self.groups.get(key)
        if group is None:
            group = self.groups[key] = CodecGroup(*key, example=path)
        group.count += 1

    def sorted_groups(self) -> list[CodecGroup]:
        return sorted(self.groups.values(), key=lambda g: (-g.count, g.codec, g.profile, g.pix_fmt))

    def table(self) -> str:
        """Tabelle als Text — Browser-Spalte: ok / limited / NO."""
        rows = [("Codec", "Profile", "Pixel format", "Browser", "Files", "Example")]
        label = {"ok": "ok", "limited": "limited", "none": "NO"}
        for g in self.sorted_groups():
            rows.append((g.codec, g.profile or "-", g.pix_fmt or "-", label[g.browser],
                         str(g.count), g.example))
        widths = [max(len(r[i]) for r in rows) for i in range(5)]
        lines = []
        for n, r in enumerate(rows):
            cells = [r[i].ljust(widths[i]) for i in range(5)] + [r[5]]
            lines.append("  ".join(cells).rstrip())
            if n == 0:
                lines.append("  ".join("-" * w for w in widths) + "  " + "-" * 8)
        return "\n".join(lines)

    def summary(self) -> str:
        parts = [f"videos in the catalog: {self.videos_total}", f"probed: {self.probed}"]
        if self.missing:
            parts.append(f"without reachable location: {self.missing}")
        if self.failed:
            parts.append(f"ffprobe errors: {len(self.failed)}")
        return " · ".join(parts)


def _video_items(conn: sqlite3.Connection, min_size: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT file_hash, file_size FROM items
            WHERE media_kind = 'video' AND COALESCE(file_size, 0) >= ?
            ORDER BY file_size DESC""",
        (min_size,),
    ).fetchall()


def _first_existing_location(conn: sqlite3.Connection, file_hash: str) -> str | None:
    for row in conn.execute(
        "SELECT path FROM file_locations WHERE file_hash = ? ORDER BY id", (file_hash,)
    ):
        try:
            if Path(row["path"]).is_file():
                return row["path"]
        except OSError:
            continue
    return None


def probe_video_stream(path: str, *, run: Callable[..., Any] = subprocess.run) -> dict[str, str] | None:
    """ffprobe nur auf den ersten Video-Stream; wirft ``RuntimeError`` mit
    Grund bei Fehlern (der Aufrufer sammelt sie, der Lauf bricht nicht ab)."""
    try:
        proc = run(
            [find_binary("ffprobe") or "ffprobe", "-v", "error", "-print_format", "json",
             "-show_streams", "-select_streams", "v:0", path],
            capture_output=True, timeout=_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe nicht gefunden (siehe DEPENDENCIES.md)") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ffprobe-Timeout nach {_TIMEOUT_SECONDS}s") from exc
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip() or "ffprobe-Fehler")
    try:
        data = json.loads(proc.stdout)
    except ValueError as exc:
        raise RuntimeError("ffprobe lieferte kein gültiges JSON") from exc
    return video_stream_facts(data)


def video_codec_report(
    conn: sqlite3.Connection, *, min_size: int = 0,
    progress: Callable[[CodecReport], None] | None = None,
    probe: Callable[[str], dict[str, str] | None] | None = None,
) -> CodecReport:
    """Codec-Überblick per ffprobe-Header-Lauf über alle Video-Fundorte.
    ``probe`` (Tests: Attrappe) — Standard ist ``probe_video_stream``, erst
    beim Aufruf aufgelöst, damit Monkeypatching greift."""
    probe = probe or probe_video_stream
    report = CodecReport()
    items = _video_items(conn, min_size)
    report.videos_total = len(items)
    for row in items:
        path = _first_existing_location(conn, row["file_hash"])
        if path is None:
            report.missing += 1
            continue
        try:
            facts = probe(path)
        except RuntimeError as exc:
            report.failed.append((path, str(exc)))
            if "nicht gefunden" in str(exc):
                break   # ohne ffprobe bringt jeder weitere Versuch dasselbe
            continue
        report.probed += 1
        if facts:
            report.add(facts, path)
        else:
            report.add({"codec_name": "(kein Video-Stream)"}, path)
        if progress is not None:
            progress(report)
    return report


def video_codec_report_from_db(conn: sqlite3.Connection, *, min_size: int = 0) -> CodecReport:
    """Derselbe Überblick aus den Schicht-2-Feldern — kein ffprobe, kein
    Dateizugriff; setzt einen Re-Scan nach der Extraktor-Erweiterung voraus.
    Videos ohne ``video_codec``-Feld landen in der Gruppe ``(unbekannt)``."""
    report = CodecReport()
    rows = conn.execute(
        """SELECT i.file_hash,
                  (SELECT value_text FROM interpreted_metadata m
                    WHERE m.file_hash = i.file_hash AND m.field = 'video_codec'
                    ORDER BY ordinal LIMIT 1) AS codec,
                  (SELECT value_text FROM interpreted_metadata m
                    WHERE m.file_hash = i.file_hash AND m.field = 'video_profile'
                    ORDER BY ordinal LIMIT 1) AS profile,
                  (SELECT value_text FROM interpreted_metadata m
                    WHERE m.file_hash = i.file_hash AND m.field = 'pixel_format'
                    ORDER BY ordinal LIMIT 1) AS pix_fmt,
                  (SELECT path FROM file_locations l
                    WHERE l.file_hash = i.file_hash ORDER BY id LIMIT 1) AS path
             FROM items i
            WHERE i.media_kind = 'video' AND COALESCE(i.file_size, 0) >= ?""",
        (min_size,),
    ).fetchall()
    report.videos_total = report.probed = len(rows)
    for r in rows:
        facts = {"codec_name": r["codec"] or "(unbekannt — Re-Scan nötig)",
                 "profile": r["profile"] or "", "pix_fmt": r["pix_fmt"] or ""}
        report.add(facts, r["path"] or "")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m feral.diagnose",
        description="Diagnostic commands over the catalog (writes nothing).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    vc = sub.add_parser(
        "video-codecs",
        help="codec/profile/pixel format of all videos, via an ffprobe header "
             "pass or (--from-db) from the layer-2 fields.",
    )
    vc.add_argument("--db", default="./feral.sqlite", help="path to the SQLite file")
    vc.add_argument("--min-size", type=parse_size, default=0,
                    help="only videos from this size on (e.g. 1G, 500M)")
    vc.add_argument("--from-db", action="store_true",
                    help="read from interpreted_metadata instead of calling ffprobe")
    vc.add_argument("--quiet", action="store_true", help="no progress output")
    args = parser.parse_args(argv)

    conn = connect(args.db)
    try:
        if args.from_db:
            report = video_codec_report_from_db(conn, min_size=args.min_size)
        else:
            def progress(r: CodecReport) -> None:
                if not args.quiet and r.probed % 100 == 0:
                    print(f"  … {r.probed}/{r.videos_total} videos", file=sys.stderr)
            report = video_codec_report(conn, min_size=args.min_size, progress=progress)
    finally:
        conn.close()

    print(report.table())
    print()
    print(report.summary())
    for path, reason in report.failed[:10]:
        print(f"  ! {path}: {reason}")
    if len(report.failed) > 10:
        print(f"  … and {len(report.failed) - 10} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
