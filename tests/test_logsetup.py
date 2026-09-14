"""Serverlog-Schwanz mit Level-Filter (Admin → Logs, ADR 0074)."""

from __future__ import annotations

import logging

import pytest

from feral.logsetup import filter_level, tail
from feral.web.app import create_app

LINES = [
    "Traceback-Rest vom Dateianfang (angeschnitten)",
    "2026-09-12 16:49:20,001 INFO    feral.web: Start taskScan",
    "2026-09-12 16:49:21,002 WARNING feral.web: slow: /api/items 612 ms",
    "2026-09-12 16:49:22,003 ERROR   feral.web.worker: Error in reparse",
    "Traceback (most recent call last):",
    '  File "x.py", line 1, in <module>',
    "ValueError: kaputt",
    "2026-09-12 16:49:23,004 INFO    feral.web: Done reparse",
]


def test_filter_level_keeps_continuation_lines_with_their_entry() -> None:
    out = filter_level(LINES, logging.WARNING)
    assert out == [LINES[2], LINES[3], LINES[4], LINES[5], LINES[6]]
    assert filter_level(LINES, logging.ERROR) == LINES[3:7]
    # INFO-Schwelle: alles außer dem kopflosen Dateianfang
    assert filter_level(LINES, logging.INFO) == LINES[1:]


def test_tail_with_min_level_filters_before_cutting(tmp_path) -> None:
    path = tmp_path / "fml-web.log"
    path.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    assert tail(path, 2) == LINES[-2:]
    # Der Filter läuft über die ganze Datei, DANN wird geschnitten: die
    # letzten zwei Warnungs-Zeilen sind Traceback-Folgezeilen des ERROR.
    assert tail(path, 2, min_level=logging.WARNING) == LINES[5:7]
    assert tail(path, 100, min_level=logging.WARNING) == LINES[2:7]
    assert tail(tmp_path / "fehlt.log", 10, min_level=logging.WARNING) == []


@pytest.fixture
def app(tmp_path):
    application = create_app(tmp_path / "t.sqlite", log_dir=tmp_path / "logs")
    yield application
    application.state.engine.shutdown()
    application.state.thumb_pool.shutdown()


def test_admin_log_endpoint_level_parameter(app, tmp_path) -> None:
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "logs" / "fml-web.log").write_text("\n".join(LINES) + "\n", encoding="utf-8")
    endpoint = next(r for r in app.routes if getattr(r, "path", None) == "/api/admin/log").endpoint
    plain = endpoint(lines=100)
    web = next(f for f in plain["files"] if f["name"] == "fml-web.log")
    assert web["lines"] == LINES
    only_warn = endpoint(lines=100, level="warning")
    web = next(f for f in only_warn["files"] if f["name"] == "fml-web.log")
    assert web["lines"] == LINES[2:7]
    worker = next(f for f in only_warn["files"] if f["name"] == "fml-worker.log")
    assert worker["lines"] == [] and worker["bytes"] == 0
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        endpoint(lines=100, level="laut")
    # ?file=: nur eine Datei (die Logs-Seite lädt je Datei getrennt)
    only_web = endpoint(lines=3, file="web")
    assert [f["name"] for f in only_web["files"]] == ["fml-web.log"]
    assert only_web["files"][0]["lines"] == LINES[-3:]
    with pytest.raises(HTTPException):
        endpoint(lines=3, file="all")


# -- Log-Härtung (#138, ADR-0067-Nachtrag) ----------------------------------

def test_formatter_makes_newlines_and_controls_visible(tmp_path) -> None:
    """Ein Dateiname mit Zeilenumbruch, ANSI-Sequenz und Bidi-Override
    erzeugt KEINE zweite Logzeile und keine Steuerzeichen in der Datei."""
    import logging as _logging
    from feral.logsetup import setup_logging
    path = setup_logging(tmp_path, "t.log")
    assert path is not None
    evil = "bild\n2026-01-01 00:00:00,000 ERROR feral: fake\x1b[31m\u202eeuq.png\r"
    _logging.getLogger("feral.test").warning("Scan problem at %s", evil)
    for h in list(_logging.getLogger().handlers):
        h.flush()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, lines
    line = lines[0]
    assert "\\n2026-01-01 00:00:00,000 ERROR feral: fake" in line
    assert "\\x1b" in line and "\\u202e" in line and "\\r" in line
    assert "\x1b" not in line and "\u202e" not in line
    setup_logging(None, "t.log")   # Datei-Handler wieder abhängen


def test_formatter_keeps_tracebacks_multiline(tmp_path) -> None:
    import logging as _logging
    from feral.logsetup import setup_logging
    path = setup_logging(tmp_path, "t.log")
    try:
        raise ValueError("boom")
    except ValueError:
        _logging.getLogger("feral.test").exception("task failed")
    for h in list(_logging.getLogger().handlers):
        h.flush()
    text = path.read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in text
    assert "ValueError: boom" in text
    assert text.count("\n") >= 3
    setup_logging(None, "t.log")


def test_tail_sanitizes_older_files_on_display(tmp_path) -> None:
    from feral.logsetup import tail
    p = tmp_path / "old.log"
    p.write_text("2026-01-01 00:00:00,000 INFO feral: a \x1b[2J b \u202e c\n", encoding="utf-8")
    (line,) = tail(p, 10)
    assert "\x1b" not in line and "\u202e" not in line
    assert "\\x1b[2J" in line and "\\u202e" in line
