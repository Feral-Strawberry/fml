"""Tests für die ScanEngine (Warteschlange + Worker-Prozess, ADR 0067) und den Watcher.

Die Engine-Tests laufen gegen den ECHTEN Worker-Prozess (spawn) — kein
Inline-Modus (Entscheidung 2, ADR 0067): Protokoll, Pickling und Statusleitung
werden mitgeprüft."""

from __future__ import annotations

import time

import pytest

from feral.db import connect
from feral.web.engine import AlreadyQueued, HotfolderWatcher, ScanEngine

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

def _wait_running(engine: ScanEngine, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = engine.status()
        if s["running"]:
            return s
        time.sleep(0.02)
    raise TimeoutError(f"Aufgabe läuft nicht an: {engine.status()}")


def test_run_write_works_from_changing_pool_threads(engine):
    """Issue #72: FastAPI führt synchrone Routen auf wechselnden Threads aus.
    Die gemeinsame Schreibverbindung darf daran nicht scheitern — vorher kam
    ab dem zweiten Thread »SQLite objects created in a thread can only be
    used in that same thread« als sumFailed zurück, der Schreibgriff war weg."""
    import threading

    def write(tag):
        return engine.run_write(
            {"key": "x"},
            lambda conn, _p: {"ok": conn.execute("SELECT 1").fetchone()[0], "tag": tag},
        )

    results = {}
    for tag in ("t1", "t2", "t3"):
        t = threading.Thread(target=lambda tag=tag: results.__setitem__(tag, write(tag)))
        t.start(); t.join()
    results["main"] = write("main")
    assert all(r.get("ok") == 1 for r in results.values()), results
    assert not any("summary" in r for r in results.values()), results


def test_run_write_runs_in_web_process_while_worker_is_busy(engine):
    """Kurze Schreibgriffe schreibt der Web-Prozess selbst (ADR 0007, Nachtrag):
    sie warten NICHT hinter einem Langläufer im Worker."""
    engine.enqueue("_sleep", {"seconds": 1.5, "steps": 15}, {"key": "sleep"})
    _wait_running(engine)
    t0 = time.time()
    result = engine.run_write(
        {"key": "testWriter"},
        lambda conn, _p: {
            "who": __import__("threading").current_thread().name,
            "n": conn.execute("SELECT COUNT(*) FROM items").fetchone()[0],
        },
    )
    assert time.time() - t0 < 1.0           # nicht auf den Langläufer gewartet
    assert result["who"] == "MainThread"    # im Aufrufer-Thread des Web-Prozesses
    assert result["n"] == 0
    assert engine.status()["running"] is True
    # Fehler in fn kommen als summary zurück, nicht als Exception (Routen-Vertrag).
    failed = engine.run_write({"key": "x"}, lambda conn, _p: 1 / 0)
    assert failed["summary"]["key"] == "sumFailed"
    _wait_idle(engine, until_label="sleep")


def test_status_shows_queue_and_rejects_duplicates(engine):
    """Mehrfachklick (ADR 0067): gleiche Aufgabe (Name + Parameter) läuft oder
    wartet schon → AlreadyQueued; die Warteschlange ist im Status sichtbar."""
    engine.enqueue("_sleep", {"seconds": 0.8, "steps": 8}, {"key": "sleepA"})
    _wait_running(engine)
    with pytest.raises(AlreadyQueued) as info:
        engine.enqueue("_sleep", {"seconds": 0.8, "steps": 8}, {"key": "sleepA"})
    assert info.value.running is True
    engine.enqueue("_sleep", {"seconds": 0.1}, {"key": "sleepB"})
    with pytest.raises(AlreadyQueued) as info:
        engine.enqueue("_sleep", {"seconds": 0.1}, {"key": "sleepB"})
    assert info.value.running is False
    s = engine.status()
    assert s["running"] and s["label"] == {"key": "sleepA"}
    assert s["queue_pending"] == 1 and s["queue"] == [{"key": "sleepB"}]
    assert s["worker_alive"] is True
    assert s["elapsed"] is not None and s["started_at"]
    # dedupe="pending": ein laufender Lauf blockiert den Nachläufer nicht.
    engine.enqueue("_sleep", {"seconds": 0.8, "steps": 8}, {"key": "sleepA"}, dedupe="pending")
    assert engine.status()["queue_pending"] == 2
    s = _wait_idle(engine, until_label="sleepA", timeout=10)
    assert s["last_result"]["key"] == "sumTest"
    assert s["queue"] == []
    assert s["finished_seq"] == 3        # drei Aufgaben fertig — das Frontend zählt, statt Labels zu vergleichen


def test_on_finished_hook_gets_task_name_and_ok(engine):
    """#118 (ADR 0077): nach jeder erledigten Aufgabe ruft die Engine ihre
    Haken mit (Aufgabenname, ok) — außerhalb der Sperre; ein kaputter Haken
    stört weder Engine noch die anderen Haken."""
    seen: list[tuple[str, bool]] = []
    engine.on_finished.append(lambda name, ok: 1 / 0)
    engine.on_finished.append(lambda name, ok: seen.append((name, ok)))
    engine.enqueue("_sleep", {"seconds": 0.05}, {"key": "sleepA"})
    engine.enqueue("_boom", {}, {"key": "boomA"})
    _wait_idle(engine, until_label="boomA", timeout=10)
    assert seen == [("_sleep", True), ("_boom", False)]
    assert engine.status()["finished_seq"] == 2


def test_worker_death_is_reported_and_worker_restarts(engine, media):
    """Aufsicht (ADR 0067): stirbt der Worker, meldet der Status die Aufgabe
    als fehlgeschlagen; der nächste Auftrag startet einen neuen Worker."""
    engine.enqueue("_die", {}, {"key": "die"})
    deadline = time.time() + 10
    while time.time() < deadline:
        s = engine.status()
        if (s["last_finished"] or {}).get("key") == "die":
            break
        time.sleep(0.05)
    else:
        raise TimeoutError(engine.status())
    assert s["last_result"]["key"] == "sumWorkerDied"
    assert s["worker_alive"] is False and s["running"] is False

    engine.enqueue_folder(media)      # startet den Worker neu
    s = _wait_idle(engine, until_label="taskScan", timeout=10)
    assert s["report"]["media_files"] == 2
    assert s["worker_alive"] is True


def test_worker_logs_tasks_to_rotating_file(tmp_path, media):
    """Serverlog (#64): der Worker schreibt Start/Ende jeder Aufgabe nach
    logs/fml-worker.log."""
    eng = ScanEngine(tmp_path / "feral.sqlite", log_dir=tmp_path / "logs")
    try:
        eng.enqueue_folder(media)
        eng.enqueue_reparse()
        _wait_idle(eng, until_label="taskReparse", timeout=15)
    finally:
        eng.shutdown()
    text = (tmp_path / "logs" / "fml-worker.log").read_text(encoding="utf-8")
    assert "Start taskScan" in text
    assert "Done reparse" in text and "sumReparse" in text


def test_admin_task_reports_last_result(engine, media):
    engine.enqueue_folder(media)
    engine.enqueue_reparse()
    s = _wait_idle(engine, until_label="taskReparse")
    # Der Scan hat interpretiert; der Reparse-Lauf meldet seine Zusammenfassung.
    assert s["last_result"]["key"] == "sumReparse"
    # Verlauf (ADR 0074 Nachtrag): jüngste zuerst, mit Dauer und Ergebnis.
    hist = s["history"]
    assert [h["label"]["key"] for h in hist] == ["taskReparse", "taskScan"]
    assert hist[0]["result"]["key"] == "sumReparse" and hist[0]["ok"] is True
    assert hist[0]["elapsed"] is not None and hist[0]["elapsed"] >= 0
    assert hist[0]["finished_at"].endswith("Z")


def test_history_marks_failed_tasks_and_is_capped(engine):
    engine.enqueue("_boom", {"text": "kaputt"}, {"key": "boom"})
    for i in range(engine.HISTORY_MAX + 2):
        engine.enqueue("_sleep", {"seconds": 0.01, "n": i}, {"key": "sleepA"}, dedupe="pending")
    deadline = time.time() + 20
    while time.time() < deadline:
        s = engine.status()
        if s["finished_seq"] == engine.HISTORY_MAX + 3 and not s["running"]:
            break
        time.sleep(0.02)
    else:
        raise TimeoutError(engine.status())
    assert len(s["history"]) == engine.HISTORY_MAX
    assert all(h["ok"] for h in s["history"])          # boom ist bereits rausgerutscht
    # Der Fehlschlag steht mit ok=False im Verlauf, solange er drin ist.
    engine.enqueue("_boom", {"text": "nochmal"}, {"key": "boom"})
    deadline = time.time() + 10
    while time.time() < deadline:
        s = engine.status()
        if s["history"][0]["label"]["key"] == "boom":
            break
        time.sleep(0.02)
    assert s["history"][0]["ok"] is False and s["history"][0]["result"]["key"] == "sumFailed"


def test_failing_task_does_not_kill_worker(engine, media):
    engine.enqueue("_boom", {"text": "kaputt"}, {"key": "boom"})
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


def test_rescan_uses_configured_min_date(engine, media, tmp_path):
    """#113: Der Re-Scan bekommt die Import-Regeln (min_date) aus der Config —
    ein 1970er-Stempel ist mit dem Standard ausgefiltert, mit gesenktem
    min_date wird er erneut katalogisiert (und datiert)."""
    import os
    engine.enqueue_folder(media)
    _wait_idle(engine)
    os.utime(media / "a.png", (0, 0))

    engine.enqueue_rescan()
    s = _wait_idle(engine, until_label="taskRescan")
    assert s["report"]["ausgefiltert"] == 1 and s["report"]["known_items"] == 1

    engine.enqueue_rescan({"min_kante": 0, "max_kante": 0, "formate": [],
                           "min_date": "1970-01-01"})
    s = _wait_idle(engine, until_label="taskRescan")
    assert s["report"]["ausgefiltert"] == 0 and s["report"]["known_items"] == 2


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


def test_status_never_waits_for_worker_start(tmp_path, monkeypatch):
    """Der Worker-Start (spawn + Importe, unter Windows 10–30 s) läuft im
    Dispatcher-Thread ohne Sperre: /api/status antwortet währenddessen
    sofort — sonst füllt der 700-ms-Poll den Request-Threadpool und mit ihm
    stehen alle Bildanfragen (Feral Strawberrys 30-s-Hänger, 2026-09-07)."""
    eng = ScanEngine(tmp_path / "feral.sqlite")
    original = eng._start_worker

    def slow_start():
        time.sleep(1.5)
        original()

    monkeypatch.setattr(eng, "_start_worker", slow_start)
    try:
        eng.enqueue("_sleep", {"seconds": 0.1}, {"key": "sleep"})
        worst = 0.0
        for _ in range(10):
            t0 = time.perf_counter()
            s = eng.status()
            worst = max(worst, time.perf_counter() - t0)
            assert s["queue_pending"] + int(s["running"]) >= 0
            time.sleep(0.1)
        assert worst < 0.1, f"status() hat auf den Worker-Start gewartet: {worst:.2f}s"
        _wait_idle(eng, until_label="sleep", timeout=10)
    finally:
        eng.shutdown()
