"""Optionaler Hilfe-Ordner (``--help-dir``, ADR 0091)."""

from __future__ import annotations

import pytest

from feral.web.app import create_app


def _mounts(app):
    return {getattr(r, "path", None) for r in app.routes}


@pytest.fixture
def make_app(tmp_path):
    apps = []

    def make(**kwargs):
        app = create_app(tmp_path / "t.sqlite", **kwargs)
        apps.append(app)
        return app

    yield make
    for app in apps:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


def test_help_folder_with_index_is_served(make_app, tmp_path):
    help_dir = tmp_path / "hilfe"
    help_dir.mkdir()
    (help_dir / "index.html").write_text("<h1>Anleitung</h1>", encoding="utf-8")
    assert "/hilfe" in _mounts(make_app(help_dir=help_dir))


def test_without_index_or_switch_nothing_is_served(make_app, tmp_path):
    empty = tmp_path / "leer"
    empty.mkdir()
    assert "/hilfe" not in _mounts(make_app(help_dir=empty))
    assert "/hilfe" not in _mounts(make_app())
