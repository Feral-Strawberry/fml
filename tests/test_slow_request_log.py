"""Langsame/abgebrochene Anfragen landen im Web-Log (ASGI-Middleware)."""

from __future__ import annotations

import asyncio
import logging

from feral.web.app import _SlowRequestLog
from feral.web.cache import COLD_KEY
from feral.web.media import ABORTED_KEY


def _scope(path="/api/x"):
    return {"type": "http", "method": "GET", "path": path}


async def _slow_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200})
    await asyncio.sleep(0.03)
    await send({"type": "http.response.body", "body": b"x" * 10, "more_body": False})


async def _aborting_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200})
    raise ConnectionResetError("client weg")


def test_slow_request_is_logged_with_inflight_count(caplog):
    mw = _SlowRequestLog(_slow_app, threshold_ms=10)
    sent = []
    with caplog.at_level(logging.INFO, logger="feral.web"):
        asyncio.run(mw(_scope(), None, lambda m: _record(sent, m)))
    assert any("slow: GET /api/x" in r.message and "10 bytes" in r.message
               and "concurrent 1" in r.message for r in caplog.records)
    assert mw.inflight == 0


def test_client_abort_is_logged(caplog):
    mw = _SlowRequestLog(_aborting_app, threshold_ms=1000)
    with caplog.at_level(logging.INFO, logger="feral.web"):
        try:
            asyncio.run(mw(_scope("/api/media/abc"), None, lambda m: _record([], m)))
        except ConnectionResetError:
            pass
    assert any("aborted: GET /api/media/abc" in r.message for r in caplog.records)
    assert mw.inflight == 0


async def _stream_aborted_by_client(scope, receive, send):
    """media.py: der Wächter hat http.disconnect gesehen und den Stream beendet."""
    await send({"type": "http.response.start", "status": 206})
    await send({"type": "http.response.body", "body": b"x" * 5, "more_body": True})
    scope[ABORTED_KEY] = True


def test_stream_abort_flag_is_logged_as_aborted_not_slow(caplog):
    mw = _SlowRequestLog(_stream_aborted_by_client, threshold_ms=0)
    with caplog.at_level(logging.INFO, logger="feral.web"):
        asyncio.run(mw(_scope("/api/media/abc"), None, lambda m: _record([], m)))
    messages = [r.message for r in caplog.records]
    assert any("aborted: GET /api/media/abc" in m and "5 bytes (client gone)" in m for m in messages)
    assert not any(m.startswith("slow:") for m in messages)
    assert mw.inflight == 0


async def _record(store, message):
    store.append(message)


async def _cold_app(scope, receive, send):
    """Endpunkt, dessen Epochen-Cache neu rechnen musste (Issue #95)."""
    scope[COLD_KEY] = "start"
    await _slow_app(scope, receive, send)


def test_cold_request_is_info_cold_not_warning(caplog):
    # Erstberechnung nach Serverstart: echte DB-Arbeit, kein Fehler → INFO
    # „cold:" mit Grund statt WARNING „slow:" (Logtext immer englisch, #35).
    mw = _SlowRequestLog(_cold_app, threshold_ms=10)
    with caplog.at_level(logging.INFO, logger="feral.web"):
        asyncio.run(mw(_scope("/api/folders"), None, lambda m: _record([], m)))
    cold = [r for r in caplog.records if r.message.startswith("cold:")]
    assert len(cold) == 1
    assert cold[0].levelno == logging.INFO
    assert "cold: GET /api/folders" in cold[0].message
    assert "(first computation since server start)" in cold[0].message
    assert not any(r.message.startswith("slow:") for r in caplog.records)


def test_warm_slow_request_stays_warning(caplog):
    # Ohne Kalt-Markierung bleibt es die WARNING von bisher.
    mw = _SlowRequestLog(_slow_app, threshold_ms=10)
    with caplog.at_level(logging.INFO, logger="feral.web"):
        asyncio.run(mw(_scope("/api/folders"), None, lambda m: _record([], m)))
    slow = [r for r in caplog.records if r.message.startswith("slow:")]
    assert len(slow) == 1 and slow[0].levelno == logging.WARNING


def test_cold_but_fast_request_is_not_logged(caplog):
    mw = _SlowRequestLog(_cold_app, threshold_ms=10_000)
    with caplog.at_level(logging.INFO, logger="feral.web"):
        asyncio.run(mw(_scope("/api/stats"), None, lambda m: _record([], m)))
    assert not any(r.message.startswith(("cold:", "slow:")) for r in caplog.records)


async def _background_app(scope, receive, send):
    """Endpunkt, dessen Antwort der Client im Hintergrund vorholt (ADR-0072-Nachtrag)."""
    from feral.web.app import BACKGROUND_KEY
    scope[BACKGROUND_KEY] = True
    await _slow_app(scope, receive, send)


def test_prefetched_request_is_info_background_not_warning(caplog):
    # Vorgeholte Arena-Paarung: ein Filterlauf, auf den niemand wartet → INFO.
    mw = _SlowRequestLog(_background_app, threshold_ms=10)
    with caplog.at_level(logging.INFO, logger="feral.web"):
        asyncio.run(mw(_scope("/api/rankings/8/pair"), None, lambda m: _record([], m)))
    bg = [r for r in caplog.records if r.message.startswith("background:")]
    assert len(bg) == 1
    assert bg[0].levelno == logging.INFO
    assert "background: GET /api/rankings/8/pair" in bg[0].message
    assert "(prefetched, nobody waited)" in bg[0].message
    assert not any(r.message.startswith("slow:") for r in caplog.records)


class _State:
    def __init__(self, ms):
        self.slow_request_ms = ms


class _App:
    def __init__(self, ms):
        self.state = _State(ms)


def test_threshold_comes_from_app_state_and_zero_never_warns(caplog):
    """#110: die Schwelle steht in app.state.slow_request_ms (Konfiguration
    ändert sie ohne Neustart); 0 heißt „nie warnen" statt „alles langsam"."""
    mw = _SlowRequestLog(_slow_app, threshold_ms=10)
    with caplog.at_level(logging.INFO, logger="feral.web"):
        asyncio.run(mw({**_scope(), "app": _App(5000)}, None, lambda m: _record([], m)))
    assert not any(r.message.startswith("slow:") for r in caplog.records)

    # 0 = nie WARNING: ab dem Standardwert (250 ms) nur noch INFO in der Datei.
    async def _very_slow(scope, receive, send):
        await send({"type": "http.response.start", "status": 200})
        await asyncio.sleep(0.3)
        await send({"type": "http.response.body", "body": b"x", "more_body": False})
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="feral.web"):
        asyncio.run(_SlowRequestLog(_very_slow)({**_scope(), "app": _App(0)}, None,
                                                lambda m: _record([], m)))
    slow = [r for r in caplog.records if r.message.startswith("slow:")]
    assert len(slow) == 1 and slow[0].levelno == logging.INFO
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="feral.web"):
        asyncio.run(mw({**_scope(), "app": _App(0)}, None, lambda m: _record([], m)))
    assert not any(r.message.startswith("slow:") for r in caplog.records)   # 30 ms < 250

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="feral.web"):
        asyncio.run(mw({**_scope(), "app": _App(1)}, None, lambda m: _record([], m)))
    assert any(r.message.startswith("slow:") for r in caplog.records)
