"""Zeitkommentare (Audio A6, #163, ADR 0088): manuelle Schicht, Suche,
Listenzeile, Detail und API."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from feral.db import connect, manual, store_extraction
from feral.extract.types import ContainerExtraction
from feral.messages import UserError
from feral.web import library

SONG = "a" * 64
OTHER = "b" * 64
T0 = "2026-09-24T10:00:00+00:00"
T1 = "2026-09-24T11:00:00+00:00"


def _put(db, h, name):
    store_extraction(db, file_hash=h, file_size=1, path=f"/lib/{name}.mp3",
                     extraction=ContainerExtraction(container="mp3", duration=200.0))


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    _put(conn, SONG, "regenzeit_a")
    _put(conn, OTHER, "regenzeit_b")
    yield conn
    conn.close()


def _hits(db, expr):
    return [i["file_hash"] for i in library.list_items(db, filter_expr=expr)["items"]]


def test_add_list_in_time_order(db):
    later = manual.add_comment(db, SONG, 95_500, "  Chorus  ", now=T0)
    first = manual.add_comment(db, SONG, 12_000, "Einsatz Stimme", now=T0)
    rows = manual.list_comments(db, SONG)
    assert [(c["id"], c["at_ms"], c["text"]) for c in rows] == [
        (first, 12_000, "Einsatz Stimme"), (later, 95_500, "Chorus")]
    assert rows[0]["created_at"] == rows[0]["updated_at"] == T0
    assert manual.list_comments(db, OTHER) == []


def test_update_and_delete(db):
    cid = manual.add_comment(db, SONG, 1000, "Chorus", now=T0)
    manual.update_comment(db, SONG, cid, text="Refrain", now=T1)
    manual.update_comment(db, SONG, cid, at_ms=2000, now=T1)
    (c,) = manual.list_comments(db, SONG)
    assert (c["text"], c["at_ms"], c["created_at"], c["updated_at"]) == ("Refrain", 2000, T0, T1)
    assert manual.delete_comment(db, OTHER, cid) is False     # gehört zu einem anderen Item
    assert manual.delete_comment(db, SONG, cid) is True
    assert manual.list_comments(db, SONG) == []


def test_validation(db):
    with pytest.raises(UserError):
        manual.add_comment(db, SONG, 0, "   ")
    with pytest.raises(UserError):
        manual.add_comment(db, SONG, -1, "Chorus")
    with pytest.raises(UserError):
        manual.add_comment(db, "f" * 64, 0, "Chorus")        # unbekanntes Item
    cid = manual.add_comment(db, SONG, 0, "Chorus")
    with pytest.raises(UserError):
        manual.update_comment(db, SONG, cid, text="")
    with pytest.raises(UserError):
        manual.update_comment(db, OTHER, cid, text="x")      # fremder Kommentar


def test_comments_are_searchable_and_follow_edits(db):
    cid = manual.add_comment(db, SONG, 95_000, "Chorus mit Streichern")
    assert _hits(db, "text:streichern") == [SONG]
    manual.update_comment(db, SONG, cid, text="Bridge")
    assert _hits(db, "text:streichern") == []
    assert _hits(db, "text:bridge") == [SONG]
    manual.delete_comment(db, SONG, cid)
    assert _hits(db, "text:bridge") == []


def test_cascade_with_the_item(db):
    manual.add_comment(db, SONG, 0, "Chorus")
    db.execute("DELETE FROM items WHERE file_hash = ?", (SONG,))
    db.commit()
    assert db.execute("SELECT COUNT(*) FROM time_comments").fetchone()[0] == 0


def test_grid_row_and_detail_carry_comments(db):
    manual.add_comment(db, SONG, 95_000, "Chorus")
    manual.add_comment(db, SONG, 10_000, "Intro")
    rows = {i["file_hash"]: i for i in library.list_items(db)["items"]}
    assert [(c["at_ms"], c["text"]) for c in rows[SONG]["comments"]] == [(10_000, "Intro"), (95_000, "Chorus")]
    assert "comments" not in rows[OTHER]                        # nur, wo es welche gibt
    detail = library.item_detail(db, SONG)
    assert [c["text"] for c in detail["comments"]] == ["Intro", "Chorus"]


def _route(app, path, method):
    return next(r for r in app.routes
                if getattr(r, "path", None) == path and method in r.methods).endpoint


def test_endpoints(tmp_path):
    from fastapi import HTTPException

    from feral.web.app import CommentCreate, CommentUpdate, create_app

    conn = connect(tmp_path / "t.sqlite")
    _put(conn, SONG, "regenzeit_a")
    conn.close()
    app = create_app(tmp_path / "t.sqlite")
    try:
        base, one = "/api/item/{file_hash}/comments", "/api/item/{file_hash}/comments/{comment_id}"
        add = _route(app, base, "POST")
        r = add(SONG, CommentCreate(at_ms=95_000, text="Chorus"))
        assert [c["text"] for c in r["comments"]] == ["Chorus"] and r["id"] == r["comments"][0]["id"]
        cid = r["id"]
        r = _route(app, one, "PUT")(SONG, cid, CommentUpdate(text="Refrain"))
        assert r["comments"][0]["text"] == "Refrain"
        assert _route(app, base, "GET")(SONG)["comments"][0]["at_ms"] == 95_000
        for call, status in ((lambda: add(SONG, CommentCreate(at_ms=0, text=" ")), 400),
                             (lambda: add(SONG, CommentCreate(at_ms=-5, text="x")), 400),
                             (lambda: _route(app, one, "PUT")(SONG, 999, CommentUpdate(text="x")), 404),
                             (lambda: _route(app, one, "DELETE")(SONG, 999), 404)):
            with pytest.raises(HTTPException) as exc:
                call()
            assert exc.value.status_code == status
        assert _route(app, one, "DELETE")(SONG, cid)["comments"] == []
        # Suche nach dem Kommentarwort über /api/items findet den Song.
        _route(app, base, "POST")(SONG, CommentCreate(at_ms=1000, text="Streicher"))
        page = _route(app, "/api/items", "GET")(
            SimpleNamespace(scope={}), limit=200, offset=0, sort="added", model=None,
            rating=None, filter="text:streicher", dupes=False, total=True, view="audio")
        assert [i["file_hash"] for i in page["items"]] == [SONG]
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()
