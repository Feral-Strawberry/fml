"""Hintergrund-Modus, Pause, überlebende Warteschlange, Watch-Vorrang
(ADR 0093; Issues #226, #223, #225, #229 Punkt 3)."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from feral import processes
from feral.processes import CTRL_HALT, CTRL_QUIET, HALT_YIELD
from feral.thumbs import ThumbPool
from feral.web import idle, tasks, worker
from feral.web.engine import ScanEngine, _Queued

from .pngbuild import build_png, text_chunk


def _wait(pred, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return
        time.sleep(0.02)
    raise TimeoutError


# -- Prozesszahl (#225) -----------------------------------------------------------


@pytest.mark.parametrize("cores, expected", [(2, 1), (4, 1), (8, 6), (None, 1)])
def test_default_workers_small_machines_get_one(monkeypatch, cores, expected):
    monkeypatch.setattr(processes.os, "cpu_count", lambda: cores)
    assert processes.default_workers() == expected


def test_effective_workers_quiet_is_one():
    assert processes.effective_workers(8, True) == 1
    assert processes.effective_workers(8, False) == 8


def test_one_core_mask_takes_last_core():
    """Windows-Kernfestlegung im Leise-Modus: der letzte logische Kern."""
    assert processes.one_core_mask(0b11111111) == 0b10000000
    assert processes.one_core_mask(0b1) == 0b1
    assert processes.one_core_mask(0) == 1


def test_ffmpeg_single_thread_only_when_quiet(monkeypatch):
    monkeypatch.setattr(processes, "_quiet", False)
    assert processes.ffmpeg_quiet_args() == []
    monkeypatch.setattr(processes, "_quiet", True)
    assert processes.ffmpeg_quiet_args()[:2] == ["-threads", "1"]


# -- Vorrang im Pool (ADR 0093 Punkt 2) -------------------------------------------


def test_thumbpool_runs_higher_priority_first_and_reconfigures():
    """Ein Prozess: nach dem Blocker kommt die Kachel (0) vor der zuvor
    eingereihten Analyse (1) — nie mehr Aufträge im Executor als Prozesse."""
    pool = ThumbPool(workers=1)
    order: list[str] = []
    try:
        blocker = pool.submit_call("blocker", time.sleep, 0.5)
        low = pool.submit_call("analyse", time.sleep, 0, priority=1)
        high = pool.submit_call("kachel", time.sleep, 0, priority=0)
        low.add_done_callback(lambda _f: order.append("analyse"))
        high.add_done_callback(lambda _f: order.append("kachel"))
        for f in (blocker, low, high):
            f.result(timeout=60)
        assert order == ["kachel", "analyse"]
        # Umbau im laufenden Betrieb: neue Aufträge gehen an den neuen Pool.
        pool.reconfigure(2, quiet=False)
        assert pool.workers == 2
        assert pool.submit_call("danach", time.sleep, 0).result(timeout=60) is None
    finally:
        pool.shutdown()


# -- Fortsetzung an der Dateigrenze (#223) ----------------------------------------


def test_scan_continuation_carries_only_remaining_files(tmp_path):
    from feral.db import connect

    files = []
    for i in range(3):
        f = tmp_path / f"{i}.png"
        f.write_bytes(build_png(text_chunk("parameters", f"p{i}")))
        files.append(str(f))
    conn = connect(tmp_path / "t.sqlite")
    calls = 0

    def progress(*, report=None, current=None):
        nonlocal calls
        if current is not None:
            calls += 1
            if calls == 1:
                raise tasks.TaskPaused()

    with pytest.raises(tasks.TaskPaused) as exc:
        tasks.TASKS["scan_files"](conn, {"files": files, "rules": None}, progress, None)
    assert exc.value.params == {"files": files[1:], "rules": None}
    conn.close()


def test_worker_context_follows_control_block(monkeypatch):
    """Leise im Steuerblock ⇒ ein Prozess; zurück ⇒ konfigurierte Zahl.
    Die Priorität des Testprozesses selbst bleibt unangetastet."""
    seen = []
    monkeypatch.setattr(worker, "set_process_priority", lambda **kw: seen.append(kw))
    control = [0, 1, 4, 1]
    ctx = worker.WorkerContext(pool_workers=4, thumb_workers=4, thumb_low_priority=True,
                               control=control)
    assert ctx.pool_workers == 1 and seen == [{"quiet": True, "low": False}]
    control[CTRL_QUIET] = 0
    ctx.sync()
    assert ctx.pool_workers == 4 and seen[-1] == {"quiet": False, "low": False}


# -- Engine: Pause, Vorrang, Persistenz --------------------------------------------


@pytest.fixture
def engine(tmp_path):
    eng = ScanEngine(tmp_path / "feral.sqlite", persist_queue=True)
    yield eng
    eng.shutdown()


def test_pause_halts_at_boundary_and_resumes(engine):
    engine.enqueue("_sleep", {"seconds": 30, "steps": 300}, {"key": "long"})
    _wait(lambda: engine.status()["running"])
    engine.set_background(quiet=True, paused=True)
    _wait(lambda: not engine.status()["running"])
    s = engine.status()
    assert s["paused"] and s["queue_pending"] == 1 and s["history"] == []
    assert idle.is_busy(s) is False            # pausiert = Leerlauf (--exit-when-idle)
    time.sleep(0.3)
    assert not engine.status()["running"]      # bleibt stehen
    engine.set_background(paused=False)        # Fortsetzen behält die Leistung
    _wait(lambda: engine.status()["running"])
    assert engine.status()["quiet"] is True and engine.status()["paused"] is False


def test_watch_batch_goes_first_and_asks_resumable_task_to_yield(engine):
    engine.set_background(paused=True)          # nichts zustellen, nur ordnen
    engine.enqueue("_sleep", {"n": 1}, {"key": "a"})
    engine.enqueue("_sleep", {"n": 2}, {"key": "b"})
    engine.enqueue("_sleep", {"n": 3}, {"key": "watch1"}, priority=True)
    engine.enqueue("_sleep", {"n": 4}, {"key": "watch2"}, priority=True)
    assert [q["key"] for q in engine.status()["queue"]] == ["watch1", "watch2", "a", "b"]
    # Läuft eine fortsetzbare Aufgabe ohne Vorrang, soll sie abgeben.
    with engine._lock:
        engine._running = _Queued(id=99, name="audio_warm", params={}, label={"key": "x"},
                                  key="audio_warm")
    engine.enqueue("_sleep", {"n": 5}, {"key": "watch3"}, priority=True)
    assert engine._control[CTRL_HALT] == HALT_YIELD
    with engine._lock:
        engine._running = None
        engine._control[CTRL_HALT] = 0


def test_queue_survives_restart_in_order(tmp_path):
    db = tmp_path / "feral.sqlite"
    first = ScanEngine(db, persist_queue=True, paused=True)
    first.enqueue("_sleep", {"n": 1}, {"key": "a"})
    first.enqueue("_sleep", {"n": 2}, {"key": "b"})
    first.shutdown()                            # sichert die Schlange
    second = ScanEngine(db, persist_queue=True, paused=True)
    try:
        assert second.restore_queue() == 2
        assert [q["key"] for q in second.status()["queue"]] == ["a", "b"]
        # Weitere Änderungen landen als Differenz in der Tabelle.
        second.enqueue("_sleep", {"n": 3}, {"key": "c"})
        assert second.persist_queue()
        rows = sqlite3.connect(db).execute("SELECT name, ord FROM task_queue ORDER BY ord").fetchall()
        assert [r[1] for r in rows] == [0, 1, 2]
    finally:
        second.shutdown()


def test_shutdown_pauses_running_task_and_keeps_it(tmp_path):
    """Beenden = Pause (ADR 0093): kein Fehler-Eintrag, die Aufgabe steht
    nach dem Neustart wieder in der Schlange und läuft von selbst an."""
    db = tmp_path / "feral.sqlite"
    first = ScanEngine(db, persist_queue=True)
    first.enqueue("_sleep", {"seconds": 30, "steps": 300}, {"key": "long"})
    _wait(lambda: first.status()["running"])
    started = time.time()
    first.shutdown()
    assert time.time() - started < 5
    assert first.status()["history"] == []
    second = ScanEngine(db, persist_queue=True)
    try:
        assert second.restore_queue() == 1
        _wait(lambda: second.status()["running"])
        assert second.status()["label"] == {"key": "long"}
    finally:
        second.shutdown()


def test_restored_move_import_imports_instead_of_sorting_into_fehler(tmp_path):
    """Ein Import, der einen Neustart in der Warteschlange überlebt, läuft
    danach wie ohne Neustart. Vorher kam ``min_date`` als Text zurück, jede
    Datei scheiterte, und „verschieben" schob die Quelle nach ``_fehler/``."""
    from datetime import datetime, timezone

    db = tmp_path / "feral.sqlite"
    source, library = tmp_path / "quelle" / "sub", tmp_path / "library"
    source.mkdir(parents=True)
    library.mkdir()
    picture = source / "bild.png"
    picture.write_bytes(build_png(text_chunk("parameters", "x")))
    first = ScanEngine(db, persist_queue=True, paused=True)
    first.enqueue_import(source.parent, target_root=library, source_mode="loeschen",
                         min_date=datetime(2015, 1, 1, tzinfo=timezone.utc))
    first.shutdown()
    second = ScanEngine(db, persist_queue=True)
    try:
        assert second.restore_queue() == 1
        _wait(lambda: second.status()["history"])
        assert second.status()["history"][0]["ok"]
        assert not (source.parent / "_fehler").exists()
        assert not picture.exists()                       # verschoben = aus der Quelle gelöscht
        assert [p.name for p in library.rglob("*.png")] == ["bild.png"]
    finally:
        second.shutdown()


def test_task_params_must_be_json(engine):
    """Die Warteschlange steht als JSON in der Datenbank (ADR 0093): was kein
    JSON ist, wird beim Einreihen abgewiesen statt nach dem Neustart verändert
    zurückzukommen."""
    from datetime import datetime

    with pytest.raises(TypeError, match="must be JSON"):
        engine.enqueue("_sleep", {"when": datetime(2026, 1, 1)}, {"key": "x"})


def test_watcher_takes_queued_paths_as_inflight(engine, tmp_path):
    root = tmp_path / "watch"
    root.mkdir()
    f = root / "x.png"
    f.write_bytes(build_png(text_chunk("parameters", "x")))
    engine.set_background(paused=True)
    engine.enqueue_files([f], {"key": "batch"})
    assert engine.queued_paths(root) == {str(f)}
    engine.start_watch_source({"path": str(root), "name": "w", "modus": "katalogisieren",
                               "quiet_seconds": 0, "poll_seconds": 3600}, lambda _files: None)
    watcher = engine._watchers[engine.watch_key(root)]
    assert watcher.poll_once(now=0) == [] and watcher.poll_once(now=10) == []


# -- Route + Startwert (App) --------------------------------------------------------


def test_background_route_and_config_start_value(tmp_path):
    from fastapi import HTTPException

    from feral.web.app import BackgroundRequest, ConfigUpdate, create_app
    from feral.config import background_default, load_config

    cfg = tmp_path / "config.toml"
    cfg.write_text('[performance]\nbackground = "quiet"\n', encoding="utf-8")
    app = create_app(tmp_path / "t.sqlite", config_path=cfg)
    try:
        ep = {r.path: r.endpoint for r in app.routes if hasattr(r, "endpoint")}
        assert app.state.engine.quiet is True            # Startwert aus der Config
        assert app.state.thumb_pool.workers == 1
        with pytest.raises(HTTPException):
            ep["/api/admin/config"](ConfigUpdate(thumbnail_size=320, background="laut"))
        # Zwei unabhängige Schalter: Anhalten lässt die Leistung stehen.
        assert ep["/api/background"](BackgroundRequest(paused=True)) == {"quiet": True, "paused": True}
        s = ep["/api/status"]()
        assert s["paused"] is True and s["quiet"] is True
        # Geänderter Startwert setzt auch die aktuelle Leistung.
        ep["/api/admin/config"](ConfigUpdate(thumbnail_size=320, background="normal"))
        assert app.state.engine.quiet is False and app.state.engine.paused is True
        assert app.state.thumb_pool.workers > 1 or processes.default_workers() == 1
        assert background_default(load_config(cfg)) == "normal"
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()
    # Die Stellung gehört dem Server: ein Neustart übernimmt sie (app_state).
    cfg.write_text('[performance]\nbackground = "quiet"\n', encoding="utf-8")
    app = create_app(tmp_path / "t.sqlite", config_path=cfg)
    try:
        assert app.state.engine.quiet is False and app.state.engine.paused is True
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


def test_restore_drops_file_writing_tasks_in_overview_mode(tmp_path):
    """Hände-weg-Garantie (ADR 0041) auch über den Neustart: ein gesicherter
    Import kommt im Übersichtsmodus nicht zurück, alles andere schon."""
    from feral.web.engine import FILE_WRITING_TASKS

    db = tmp_path / "feral.sqlite"
    source = tmp_path / "quelle"
    source.mkdir()
    first = ScanEngine(db, persist_queue=True, paused=True)
    first.enqueue_import(source, target_root=tmp_path / "library", min_date="2015-01-01",
                         source_mode="loeschen")
    first.enqueue("_sleep", {"n": 1}, {"key": "harmlos"})
    first.shutdown()
    second = ScanEngine(db, persist_queue=True, paused=True)
    try:
        assert second.restore_queue(skip=FILE_WRITING_TASKS) == 1
        assert second.status()["queue"] == [{"key": "harmlos"}]
        assert second.persist_queue()
        names = [r[0] for r in sqlite3.connect(db).execute("SELECT name FROM task_queue")]
        assert names == ["_sleep"]
    finally:
        second.shutdown()
