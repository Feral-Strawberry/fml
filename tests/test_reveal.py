"""„Im Dateimanager anzeigen" (I6, ADR 0041): Kommando-Bauer + Endpunkt.

Der Prozessstart selbst wird nicht getestet (würde echte Fenster öffnen) —
`reveal_command` ist pur, der Endpunkt bekommt einen aufzeichnenden Ersatz.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from feral import reveal


# --- Kommando-Bauer (pur, je Plattform) ------------------------------------------


def test_reveal_command_windows_selects_file() -> None:
    """explorer erwartet /select, und Pfad als EIN Argument."""
    cmd = reveal.reveal_command(Path(r"C:\medien\bild.png"), platform="win32")
    assert cmd == ["explorer", r"/select,C:\medien\bild.png"]


def test_reveal_command_macos_reveals_in_finder() -> None:
    cmd = reveal.reveal_command(Path("/medien/bild.png"), platform="darwin")
    assert cmd == ["open", "-R", "/medien/bild.png"]


def test_reveal_command_other_opens_parent_folder() -> None:
    """Ohne Markier-Fähigkeit (Linux u. a.): Fallback öffnet den Ordner."""
    cmd = reveal.reveal_command(Path("/medien/bild.png"), platform="linux")
    assert cmd == ["xdg-open", "/medien"]


# --- Endpunkt POST /api/item/{hash}/reveal ---------------------------------------


def _reveal_endpoint(app):
    return next(
        route for route in app.routes
        if getattr(route, "path", None) == "/api/item/{file_hash}/reveal"
    ).endpoint


def test_reveal_endpoint_opens_first_existing_location(tmp_path, monkeypatch) -> None:
    from feral.db import connect, store_extraction
    from feral.extract.types import ContainerExtraction
    from feral.web.app import create_app

    media = tmp_path / "bild.png"
    media.write_bytes(b"png")
    file_hash = "ab" * 32

    app = create_app(tmp_path / "t.sqlite")
    try:
        conn = connect(tmp_path / "t.sqlite")
        store_extraction(conn, file_hash=file_hash, file_size=3, path=media,
                         extraction=ContainerExtraction(container="png"))
        conn.close()

        opened: list[Path] = []
        monkeypatch.setattr(reveal, "show_in_file_manager", opened.append)

        result = _reveal_endpoint(app)(file_hash)
        assert opened == [media]
        assert result == {"revealed": str(media)}
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


def test_reveal_endpoint_404_without_existing_location(tmp_path, monkeypatch) -> None:
    """Fundort-Datei weg ⇒ ehrliche 404, es wird kein Prozess gestartet."""
    from feral.db import connect, store_extraction
    from feral.extract.types import ContainerExtraction
    from feral.web.app import create_app

    file_hash = "cd" * 32
    app = create_app(tmp_path / "t.sqlite")
    try:
        conn = connect(tmp_path / "t.sqlite")
        store_extraction(conn, file_hash=file_hash, file_size=3,
                         path=tmp_path / "verschwunden.png",
                         extraction=ContainerExtraction(container="png"))
        conn.close()

        def boom(_path: Path) -> None:  # pragma: no cover - darf nie laufen
            raise AssertionError("Dateimanager darf ohne Fundort nicht starten")

        monkeypatch.setattr(reveal, "show_in_file_manager", boom)
        with pytest.raises(HTTPException) as exc:
            _reveal_endpoint(app)(file_hash)
        assert exc.value.status_code == 404
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()
