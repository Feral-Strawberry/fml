"""Startlogik von ``python -m feral.web`` (I5-Nachbesserung, ADR 0041):

Der Browser-Öffner wartet auf den echten Port statt blind loszulegen —
start.bat rechnet den Port nicht mehr nach (cmds Anführungszeichen-Regeln
zerlegten den Nachrechen-Einzeiler, der Browser landete immer auf 8765).
"""

from __future__ import annotations

import socket

from feral.web.__main__ import _open_browser_when_ready


def test_open_browser_waits_for_listening_port(monkeypatch) -> None:
    """Server nimmt den Port an ⇒ genau eine Browser-Öffnung mit der URL."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    opened: list[str] = []
    monkeypatch.setattr("feral.web.__main__.webbrowser.open", opened.append)
    try:
        _open_browser_when_ready(
            f"http://127.0.0.1:{port}", "127.0.0.1", port, attempts=5, delay=0.01)
    finally:
        server.close()
    assert opened == [f"http://127.0.0.1:{port}"]


def test_open_browser_gives_up_without_server(monkeypatch) -> None:
    """Kommt der Server nie hoch (Port belegt/Absturz): kein Browser ins Leere."""
    # Einen garantiert unbelegten Port ermitteln und sofort wieder freigeben.
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    opened: list[str] = []
    monkeypatch.setattr("feral.web.__main__.webbrowser.open", opened.append)
    _open_browser_when_ready(
        f"http://127.0.0.1:{port}", "127.0.0.1", port, attempts=3, delay=0.01)
    assert opened == []
