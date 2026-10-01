"""Manuelle Reihenfolge einer gespeicherten Suche (#218, ADR 0095)."""

from __future__ import annotations

import pytest

from feral.db import connect, folders, manual, store_extraction
from feral.extract.types import ContainerExtraction
from feral.messages import UserError
from feral.web import filters, library
from feral.web.cache import EpochCache

AUDIO = (filters.view_predicate("audio"),)


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    yield conn
    conn.close()


def _seed(db):
    """Fünf Songs, a–d mit Tag „rc", in Hinzufüge-Reihenfolge a < b < c < d < e."""
    for k, c in enumerate("abcde"):
        store_extraction(db, file_hash=c * 64, file_size=1, path=f"/m/{c}.mp3",
                         extraction=ContainerExtraction(container="mp3", media_kind="audio"),
                         now=f"2026-09-0{k + 1}T00:00:00+00:00")
        if c != "e":
            manual.add_tag(db, c * 64, "rc")
    return folders.create(db, "Playlist", "tag: rc")


def _order(db, folder_id, sort="manual", **kw):
    items = library.list_items(db, sort=sort, filter_expr="tag: rc", view_preds=AUDIO,
                               folder=folder_id, **kw)["items"]
    return "".join(i["file_hash"][0] for i in items)


def test_manual_without_positions_is_added_order_and_needs_folder(db):
    fid = _seed(db)
    assert _order(db, fid) == "abcd"
    # Ohne Ordner fällt „manuell" auf „Hinzugefügt" (neueste zuerst) zurück.
    assert _order(db, None) == "dcba"


def test_move_before_after_and_new_hits_append(db):
    fid = _seed(db)
    assert library.move_in_folder(db, fid, "d" * 64, before="a" * 64, view_preds=AUDIO) == 0
    assert _order(db, fid) == "dabc"
    library.move_in_folder(db, fid, "a" * 64, after="c" * 64, view_preds=AUDIO)
    assert _order(db, fid) == "dbca"
    assert _order(db, fid, sort="manual-ab") == "acbd"
    # Neu getaggt: hängt sich hinten an; Tag weg: fällt heraus, Position bleibt still.
    manual.add_tag(db, "e" * 64, "rc")
    manual.remove_tag(db, "b" * 64, "rc")
    assert _order(db, fid) == "dcae"
    manual.add_tag(db, "b" * 64, "rc")
    assert _order(db, fid) == "dbcae"


def test_sort_directive_and_cache(db, tmp_path):
    fid = _seed(db)
    library.move_in_folder(db, fid, "c" * 64, before="a" * 64, view_preds=AUDIO)
    items = library.list_items(db, filter_expr="tag: rc sort: manual", view_preds=AUDIO,
                               folder=fid, cache=EpochCache(tmp_path / "feral.sqlite"))["items"]
    assert "".join(i["file_hash"][0] for i in items) == "cabd"
    assert library.item_position(db, "a" * 64, sort="manual", filter_expr="tag: rc",
                                 view_preds=AUDIO, folder=fid) == 1


def test_invalid_moves_and_cascade_on_folder_delete(db):
    fid = _seed(db)
    with pytest.raises(UserError):
        library.move_in_folder(db, fid, "e" * 64, before="a" * 64, view_preds=AUDIO)
    with pytest.raises(UserError):
        library.move_in_folder(db, fid, "a" * 64, view_preds=AUDIO)
    with pytest.raises(UserError):
        library.move_in_folder(db, 999, "a" * 64, before="b" * 64, view_preds=AUDIO)
    library.move_in_folder(db, fid, "b" * 64, before="a" * 64, view_preds=AUDIO)
    assert db.execute("SELECT COUNT(*) FROM folder_order").fetchone()[0] == 4
    folders.delete(db, fid)
    assert db.execute("SELECT COUNT(*) FROM folder_order").fetchone()[0] == 0
