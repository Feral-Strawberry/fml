"""Tests für das Selbst-Beenden bei Leerlauf (``--exit-when-idle``, ADR 0091)."""

from __future__ import annotations

import threading

import pytest

from feral.web.app import create_app
from feral.web.idle import MIN_IDLE_SECONDS, IdleWatch, is_busy, start_watchdog

IDLE = {"running": False, "queue_pending": 0}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_busy_means_running_or_waiting():
    assert not is_busy(IDLE)
    assert is_busy({"running": True, "queue_pending": 0})
    assert is_busy({"running": False, "queue_pending": 2})


def test_limit_is_never_shorter_than_browser_throttling():
    assert IdleWatch(5).idle_seconds == MIN_IDLE_SECONDS


def test_exits_only_after_the_limit_without_status_calls():
    clock = FakeClock()
    watch = IdleWatch(180, clock=clock)
    clock.now += 179
    assert not watch.should_exit(IDLE)
    clock.now += 1
    assert watch.should_exit(IDLE)


def test_a_status_call_starts_the_limit_again():
    clock = FakeClock()
    watch = IdleWatch(180, clock=clock)
    clock.now += 170
    watch.touch()
    clock.now += 170
    assert not watch.should_exit(IDLE)


def test_running_or_waiting_tasks_keep_the_server_alive():
    clock = FakeClock()
    watch = IdleWatch(180, clock=clock)
    clock.now += 10_000
    assert not watch.should_exit({"running": True, "queue_pending": 0})
    assert not watch.should_exit({"running": False, "queue_pending": 1})
    assert watch.should_exit(IDLE)


def test_watchdog_calls_stop_exactly_once():
    clock = FakeClock()
    watch = IdleWatch(180, clock=clock)
    clock.now += 200
    stopped = threading.Event()
    calls = []

    def stop():
        calls.append(1)
        stopped.set()

    thread = start_watchdog(watch, lambda: IDLE, stop, interval=0.01)
    assert stopped.wait(2)
    thread.join(2)
    assert calls == [1]


@pytest.fixture
def app(tmp_path):
    application = create_app(tmp_path / "t.sqlite")
    yield application
    application.state.engine.shutdown()
    application.state.thumb_pool.shutdown()


def _status_endpoint(app):
    return next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/api/status")


def test_status_route_is_the_heartbeat(app):
    clock = FakeClock()
    app.state.idle_watch = IdleWatch(180, clock=clock)
    clock.now += 170
    _status_endpoint(app)()
    clock.now += 170
    assert not app.state.idle_watch.should_exit(IDLE)


def test_without_the_switch_nothing_is_watched(app):
    assert app.state.idle_watch is None
    assert "queue_pending" in _status_endpoint(app)()
