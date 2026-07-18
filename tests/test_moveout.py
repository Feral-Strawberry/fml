"""Tests für den Rausverschiebe-Weg (I3, ADR 0041)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

from feral import moveout
from feral.db import connect
from feral.hashing import hash_file

from .pngbuild import build_png, text_chunk

MTIME_2024 = datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc).timestamp()


@pytest.fixture
def env(tmp_path):
    library = tmp_path / "bestand"
    target = tmp_path / "aussortiert"
    library.mkdir()
    target.mkdir()
    conn = connect(tmp_path / "feral.sqlite")
    yield conn, library, target
    conn.close()


def _png(path, text="ein prompt", mtime=MTIME_2024):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_png(text_chunk("parameters", text)))
    os.utime(path, (mtime, mtime))
    return path


def _reject(conn, *paths, file_hash=None):
    """Sperrlisten-Eintrag wie ihn bulk._apply_reject hinterlässt (I1)."""
    file_hash = file_hash or hash_file(paths[0])
    conn.execute(
        "INSERT OR REPLACE INTO blocked_hashes (file_hash, reason, blocked_at, last_paths)"
        " VALUES (?, 'abgelehnt', '2026-07-11T00:00:00Z', ?)",
        (file_hash, json.dumps([str(p) for p in paths])),
    )
    conn.commit()
    return file_hash


def _log_actions(conn):
    return [r["action"] for r in conn.execute(
        "SELECT action FROM import_log ORDER BY id")]


# -- Pauschalweg: verschieben mit Datumsstruktur -----------------------------------


def test_move_lands_in_date_structure(env):
    conn, library, target = env
    path = _png(library / "2024" / "05" / "01" / "bild.png")
    file_hash = _reject(conn, path)

    report = moveout.move_out(conn, library_root=library, target_root=target)

    destination = target / "2024" / "05" / "01" / "bild.png"
    assert report.verschoben == 1 and report.fehler == 0
    assert destination.is_file() and not path.exists()
    assert hash_file(destination) == file_hash
    assert _log_actions(conn) == ["rausverschoben"]
    row = conn.execute("SELECT target_path FROM import_log").fetchone()
    assert row["target_path"] == str(destination)


def test_last_paths_point_to_new_location(env):
    conn, library, target = env
    path = _png(library / "bild.png")
    file_hash = _reject(conn, path)

    moveout.move_out(conn, library_root=library, target_root=target)

    raw = conn.execute(
        "SELECT last_paths FROM blocked_hashes WHERE file_hash = ?", (file_hash,)
    ).fetchone()[0]
    (stored,) = json.loads(raw)
    assert stored == str(target / "2024" / "05" / "01" / "bild.png")


def test_embedded_date_wins_over_mtime(env):
    conn, library, target = env
    path = library / "bild.png"
    path.write_bytes(build_png(
        text_chunk("DateTimeOriginal", "2022:03:15 10:00:00"),
        text_chunk("parameters", "prompt"),
    ))
    os.utime(path, (MTIME_2024, MTIME_2024))
    _reject(conn, path)

    moveout.move_out(conn, library_root=library, target_root=target)

    assert (target / "2022" / "03" / "15" / "bild.png").is_file()


def test_unknown_container_falls_back_to_mtime(env):
    conn, library, target = env
    path = library / "kein-medium.bin"
    path.write_bytes(b"kein containerformat")
    os.utime(path, (MTIME_2024, MTIME_2024))
    _reject(conn, path)

    report = moveout.move_out(conn, library_root=library, target_root=target)

    assert report.verschoben == 1
    assert (target / "2024" / "05" / "01" / "kein-medium.bin").is_file()


def test_collision_gets_suffix(env):
    conn, library, target = env
    path = _png(library / "bild.png", text="neu")
    _png(target / "2024" / "05" / "01" / "bild.png", text="liegt schon da")
    _reject(conn, path)

    report = moveout.move_out(conn, library_root=library, target_root=target)

    assert report.verschoben == 1
    assert (target / "2024" / "05" / "01" / "bild__2.png").is_file()


# -- Sicherheiten: Verifikation vor jedem Anfassen ---------------------------------


def test_missing_file_reported_not_touched(env):
    conn, library, target = env
    _reject(conn, library / "weg.png", file_hash="0" * 64)

    report = moveout.move_out(conn, library_root=library, target_root=target)

    assert report.fehlt == 1 and report.verschoben == 0
    assert _log_actions(conn) == ["rausverschieben_fehlt"]


def test_changed_content_reported_not_touched(env):
    conn, library, target = env
    path = _png(library / "bild.png")
    _reject(conn, path)
    path.write_bytes(b"inzwischen etwas anderes")   # von Hand ersetzt

    report = moveout.move_out(conn, library_root=library, target_root=target)

    assert report.veraendert == 1 and report.verschoben == 0
    assert path.is_file()                            # nicht angefasst
    assert _log_actions(conn) == ["rausverschieben_veraendert"]


def test_external_paths_are_never_candidates(env, tmp_path):
    conn, library, target = env
    outside = _png(tmp_path / "extern" / "bild.png")
    _reject(conn, outside)

    report = moveout.move_out(conn, library_root=library, target_root=target)

    assert report.verschoben == 0 and outside.is_file()
    assert _log_actions(conn) == []


def test_entries_without_paths_are_skipped(env):
    conn, library, target = env
    # Alt-Eintrag (ADR 0023, vor Migration 0017): kein Pfad-Wissen.
    conn.execute(
        "INSERT INTO blocked_hashes (file_hash, reason, blocked_at)"
        " VALUES (?, 'aus der GUI gelöscht', '2026-01-01T00:00:00Z')",
        ("1" * 64,),
    )
    conn.commit()

    report = moveout.move_out(conn, library_root=library, target_root=target)

    assert report.verschoben == 0 and report.fehler == 0


# -- Vorschau (Dialog) --------------------------------------------------------------


def test_overview_counts_honestly(env, tmp_path):
    conn, library, target = env
    a = _png(library / "a.png", text="a")
    b = _png(library / "b.png", text="b")
    _reject(conn, a)
    _reject(conn, b)
    _reject(conn, library / "weg.png", file_hash="2" * 64)      # verschwunden
    _reject(conn, _png(tmp_path / "extern.png", text="c"))       # extern

    ov = moveout.overview(conn, library, sample=1)

    assert ov["total_blocked"] == 4
    assert ov["movable"] == 2 and ov["missing"] == 1
    assert ov["bytes"] == a.stat().st_size + b.stat().st_size
    assert len(ov["sample"]) == 1


def test_two_library_copies_both_move(env):
    conn, library, target = env
    first = _png(library / "a" / "bild.png")
    second = library / "b" / "bild.png"
    second.parent.mkdir()
    second.write_bytes(first.read_bytes())
    os.utime(second, (MTIME_2024, MTIME_2024))
    _reject(conn, first, second)

    report = moveout.move_out(conn, library_root=library, target_root=target)

    assert report.verschoben == 2
    assert not first.exists() and not second.exists()
    day = target / "2024" / "05" / "01"
    assert (day / "bild.png").is_file() and (day / "bild__2.png").is_file()
