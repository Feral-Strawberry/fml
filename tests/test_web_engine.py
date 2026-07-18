"""Tests für die ScanEngine (ein Writer-Thread) und den Watcher."""

from __future__ import annotations

import time

import pytest

from feral.db import connect
from feral.web.engine import HotfolderWatcher, ScanEngine

from .pngbuild import build_png, itxt_chunk, text_chunk

PNG_A = build_png(text_chunk("parameters", "alpha\nSeed: 1"))
PNG_B = build_png(itxt_chunk("workflow", '{"id":2}'))


def _wait_idle(engine: ScanEngine, timeout: float = 5.0, *, until_label: str | None = None) -> dict:
    """Warte, bis der Worker fertig ist (nichts läuft, Queue leer, mind. 1 Job fertig).

    Mit `until_label` zusätzlich: bis der Job mit diesem Meldungs-Schlüssel
    (Block M.2, ADR 0054) der zuletzt beendete ist (robust gegen die Lücke
    zwischen zwei Queue-Jobs).
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = engine.status()
        idle = not s["running"] and s["queue_pending"] == 0 and s["last_finished"]
        if idle and (until_label is None or (s["last_finished"] or {}).get("key") == until_label):
            return s
        time.sleep(0.02)
    raise TimeoutError(f"Engine nicht idle: {engine.status()}")


@pytest.fixture
def engine(tmp_path):
    eng = ScanEngine(tmp_path / "feral.sqlite")
    yield eng
    eng.shutdown()


@pytest.fixture
def media(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    (root / "a.png").write_bytes(PNG_A)
    (root / "b.png").write_bytes(PNG_B)
    return root


def test_engine_scans_folder(engine, media, tmp_path):
    count = engine.enqueue_folder(media)
    assert count == 2

    s = _wait_idle(engine)
    assert s["report"]["media_files"] == 2
    assert s["report"]["new_items"] == 2

    # In der DB nachsehen (eigene Leseverbindung).
    conn = connect(tmp_path / "feral.sqlite")
    try:
        assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2
    finally:
        conn.close()


def test_watch_source_management(engine, media):
    """Watch-Quellen-Modell (ADR 0030): mehrere überwachte Ordner, je Modus;
    Start/Stopp je Pfad, idempotent, im Status sichtbar."""
    assert engine.status()["watchers"] == []

    engine.start_watch_source(
        {"name": "Output A", "path": str(media), "modus": "kopieren",
         "quiet_seconds": 999, "poll_seconds": 999},
        lambda files: None,
    )
    assert engine.is_watching(media)
    watchers = engine.status()["watchers"]
    assert len(watchers) == 1
    assert watchers[0]["name"] == "Output A"
    assert watchers[0]["modus"] == "kopieren"

    # Gleicher Pfad erneut starten ersetzt statt zu duplizieren.
    engine.start_watch_source({"path": str(media), "modus": "verschieben"}, lambda f: None)
    watchers = engine.status()["watchers"]
    assert len(watchers) == 1
    assert watchers[0]["modus"] == "verschieben"

    assert engine.stop_watch_source(media) is True
    assert engine.status()["watchers"] == []
    assert engine.stop_watch_source(media) is False   # war schon weg


# --- Wartungsaufgaben (Stufe 2A) -----------------------------------------------

def test_run_write_executes_in_worker_and_returns(engine):
    result = engine.run_write(
        {"key": "testWriter"},
        lambda conn, _p: {"who": __import__("threading").current_thread().name},
    )
    assert result["who"] == "feral-writer"  # lief wirklich im Writer-Thread


def test_admin_task_reports_last_result(engine, media):
    engine.enqueue_folder(media)
    engine.enqueue_reparse()
    s = _wait_idle(engine, until_label="taskReparse")
    # Der Scan hat interpretiert; der Reparse-Lauf meldet seine Zusammenfassung.
    assert s["last_result"]["key"] == "sumReparse"


def test_failing_task_does_not_kill_worker(engine, media):
    def boom(conn, _p):
        raise RuntimeError("kaputt")

    engine._submit({"key": "boom"}, boom)
    engine.enqueue_folder(media)          # muss danach trotzdem laufen
    s = _wait_idle(engine, until_label="taskScan")
    assert s["report"]["media_files"] == 2
    assert s["last_result"]["key"] == "sumFailed"


def test_rescan_only_touches_existing_paths(engine, media, tmp_path):
    engine.enqueue_folder(media)
    _wait_idle(engine)
    (media / "a.png").unlink()            # ein Fundort verschwindet

    engine.enqueue_rescan()
    s = _wait_idle(engine, until_label="taskRescan")
    assert s["report"]["scanned_files"] == 1   # nur die noch existierende Datei


# -- Hotfolder (Block 4.2, ADR 0025) -----------------------------------------------


def test_hotfolder_quiet_detection(tmp_path):
    """Ruhe-Erkennung: erst wenn (Größe, mtime) über quiet_seconds stabil
    sind, wird die Datei gemeldet — und danach nicht doppelt."""
    batches = []
    w = HotfolderWatcher(tmp_path, batches.append, quiet_seconds=5.0, clock=lambda: 0)

    f = tmp_path / "bild.png"
    f.write_bytes(build_png(text_chunk("parameters", "x")))
    assert w.poll_once(now=0.0) == []          # gerade erst gesehen
    assert w.poll_once(now=3.0) == []          # noch nicht lange genug ruhig
    assert w.poll_once(now=6.0) == [f]         # stabil ≥ 5 s → reif
    assert w.poll_once(now=7.0) == []          # eingereiht → nicht doppelt
    assert w.status()["enqueued_total"] == 1

    # Datei wächst weiter (halbe Kopie): Uhr beginnt neu.
    f2 = tmp_path / "kopie.png"
    f2.write_bytes(b"x")
    w.poll_once(now=10.0)
    f2.write_bytes(b"xx" * 100)                # Größe ändert sich
    assert w.poll_once(now=16.0) == []         # Signatur neu → wieder warten
    assert w.poll_once(now=22.0) == [f2]

    # Verarbeitete (verschwundene) Dateien werden vergessen.
    f.unlink(); f2.unlink()
    w.poll_once(now=23.0)
    assert w.status()["pending"] == 0


def test_hotfolder_import_verschieben_loescht_quelle(engine, tmp_path):
    """Reife Dateien laufen durch den Import-Kern; im Verschiebe-Modus ist
    der Hotfolder danach leer (Quelle gelöscht, Kopie im Bestand)."""
    import os

    from datetime import datetime, timezone

    hot = tmp_path / "hot"; hot.mkdir()
    bestand = tmp_path / "bestand"; bestand.mkdir()
    f = hot / "neu.png"
    f.write_bytes(build_png(text_chunk("parameters", "hotfolder-test")))
    os.utime(f, (1714560000, 1714560000))

    engine.enqueue_import_files(
        [f], source_root=hot, target_root=bestand,
        min_date=datetime(2015, 1, 1, tzinfo=timezone.utc), source_mode="loeschen",
    )
    for _ in range(100):
        st = engine.status()
        if not st["running"] and st["queue_pending"] == 0 and st["last_finished"]:
            break
        time.sleep(0.05)

    assert not f.exists()                       # Quelle gelöscht (ADR 0025)
    assert not (hot / "_importiert").exists()   # kein Erfolgs-Ordner nötig
    assert (bestand / "2024" / "05" / "01" / "neu.png").is_file()
    conn = connect(engine.db_path)
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
    conn.close()
    summary = engine.status()["last_result"]
    assert summary["key"] == "sumHotfolderImport"
    assert {"key": "sumImportNew", "params": {"n": 1}} in summary["params"]["parts"]


def test_vacuum_truncates_wal(engine, media, tmp_path):
    """Nach VACUUM darf keine DB-große WAL-Datei liegen bleiben — sonst zeigt
    „DB (+WAL)" scheinbar das Doppelte (Feral Strawberrys 1,1→2,21-GB-Befund)."""
    engine.enqueue_folder(media)
    _wait_idle(engine)

    engine.enqueue_vacuum()
    s = _wait_idle(engine, until_label="taskVacuum")

    assert s["last_result"]["key"] == "sumVacuum"
    wal = tmp_path / "feral.sqlite-wal"
    db = tmp_path / "feral.sqlite"
    assert not wal.exists() or wal.stat().st_size < db.stat().st_size / 10


# -- Stat-Gedächtnis: Watcher-Neustart ohne Voll-Rescan (ADR 0042) -------------


def test_hotfolder_known_stats_skips_unchanged(tmp_path):
    """Pfade mit unverändertem (Größe, mtime_ns) gelten als katalogisiert und
    werden NIE gemeldet — geänderte oder unbekannte Dateien laufen den
    normalen Weg (Ruhe-Erkennung)."""
    known = tmp_path / "bekannt.png"
    known.write_bytes(PNG_A)
    st = known.stat()
    fresh = tmp_path / "neu.png"
    fresh.write_bytes(PNG_B)

    batches = []
    w = HotfolderWatcher(
        tmp_path, batches.append, quiet_seconds=5.0, clock=lambda: 0,
        known_stats={str(known): (st.st_size, st.st_mtime_ns)},
    )
    assert w.poll_once(now=0.0) == []
    assert w.poll_once(now=6.0) == [fresh]     # nur die unbekannte Datei
    assert w.status()["pending"] == 0          # bekannt zählt nicht als wartend

    # Bekannte Datei ändert sich → Gedächtnis passt nicht mehr → normaler Weg.
    known.write_bytes(PNG_A + b"\x00")
    assert w.poll_once(now=10.0) == []         # wieder in Bewegung
    assert w.poll_once(now=16.0) == [known]


def test_engine_stat_memory_roundtrip(engine, media, tmp_path):
    """Scan schreibt das Stat-Gedächtnis (Migration 0018); _load_stat_memory
    liefert es je Wurzel; ein damit gestarteter Watcher reiht nichts ein —
    das war Feral Strawberrys Neustart-Voll-Rescan."""
    engine.enqueue_folder(media)
    _wait_idle(engine)

    memory = engine._load_stat_memory(media)
    assert set(memory) == {str(media / "a.png"), str(media / "b.png")}
    for path, (size, mtime_ns) in memory.items():
        from pathlib import Path

        st = Path(path).stat()
        assert (size, mtime_ns) == (st.st_size, st.st_mtime_ns)
    # Fremde Wurzel: leeres Gedächtnis (Pfad-Präfix filtert).
    assert engine._load_stat_memory(tmp_path / "anderswo") == {}

    # „Neustart": frischer Watcher mit DB-Gedächtnis meldet NICHTS.
    batches = []
    w = HotfolderWatcher(
        media, batches.append, quiet_seconds=0.0, clock=lambda: 0,
        known_stats=memory,
    )
    assert w.poll_once(now=100.0) == []
    assert batches == []


def test_engine_stat_memory_includes_scan_memory(engine, media):
    """ADR-0042-Ergänzung (Migration 0019): auch Nicht-Katalogisiertes
    (gescheitert/unbekannt/gesperrt) gehört ins Watcher-Gedächtnis — sonst
    liest jeder Neustart genau diese Dateien neu und macht quittierte
    Scan-Probleme wieder auf (Feral Strawberrys 2600er)."""
    from feral.db import connect

    kaputt = media / "kaputt.dat"
    kaputt.write_bytes(b"x" * 7)
    st = kaputt.stat()
    conn = connect(engine.db_path)
    conn.execute(
        """INSERT INTO scan_memory (path, file_size, mtime_ns, outcome, last_seen_at)
           VALUES (?, ?, ?, 'unbekannt', 'T0')""",
        (str(kaputt), st.st_size, st.st_mtime_ns),
    )
    conn.commit()
    conn.close()

    memory = engine._load_stat_memory(media)
    assert memory[str(kaputt)] == (st.st_size, st.st_mtime_ns)

    # Frischer Watcher („Neustart"): die gemerkte kaputte Datei bleibt still.
    batches = []
    w = HotfolderWatcher(
        media, batches.append, quiet_seconds=0.0, clock=lambda: 0,
        known_stats=memory,
    )
    ready = w.poll_once(now=100.0)
    assert str(kaputt) not in {str(p) for p in ready}
