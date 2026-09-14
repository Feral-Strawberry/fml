"""Eltern-Wächter (ADR 0067): Kindprozesse enden mit ihrem Elternprozess."""

from __future__ import annotations

import multiprocessing as mp
import os
import time

from feral.processes import exit_when_parent_dies


def _grandchild(q) -> None:
    exit_when_parent_dies()
    q.put(os.getpid())
    time.sleep(30)              # würde ohne Wächter 30 s leben


def _child(q) -> None:
    ctx = mp.get_context("spawn")
    p = ctx.Process(target=_grandchild, args=(q,))
    p.start()
    q.get(timeout=20)           # Enkel läuft und hat den Wächter gesetzt
    os._exit(0)                 # harter Tod des Elternprozesses (wie kill -9)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_child_exits_when_parent_dies_hard():
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    child = ctx.Process(target=_child, args=(q,))
    child.start()
    grandchild_pid = q.get(timeout=30)
    q.put(grandchild_pid)       # das Kind wartet auf genau diesen Wert
    child.join(timeout=30)
    assert child.exitcode == 0
    deadline = time.time() + 10
    while time.time() < deadline and _alive(grandchild_pid):
        time.sleep(0.1)
    assert not _alive(grandchild_pid), "Enkel lebt ohne Elternprozess weiter"
