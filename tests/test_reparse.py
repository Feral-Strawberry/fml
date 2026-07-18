"""Tests für die rückwirkende Interpretation über die DB (ADR 0004/0011)."""

from __future__ import annotations

import io

import pytest

from feral.db import connect, store_extraction, store_interpretations
from feral.extract import png
from feral.interpret import interpret_items, reparse_database
from feral.interpret.reparse import raw_items_for

from .pngbuild import build_png, exif_chunk, text_chunk

T0 = "2026-01-01T00:00:00+00:00"

A1111 = "a strawberry\nSteps: 30, Seed: 777, Model: flux1-dev"


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    yield conn
    conn.close()


def _store_png(conn, file_hash: str, *chunks) -> None:
    extraction = png.extract(io.BytesIO(build_png(*chunks)))
    store_extraction(
        conn, file_hash=file_hash, file_size=1, path=f"/{file_hash}.png",
        extraction=extraction, now=T0,
    )


def test_raw_items_roundtrip_through_db(db):
    _store_png(db, "h1", text_chunk("parameters", A1111), exif_chunk(b"MM\x00\x2a"))

    items = raw_items_for(db, "h1")

    assert [i.keyword for i in items] == ["parameters", None]
    assert items[0].text == A1111 and items[0].data is None
    assert items[1].data == b"MM\x00\x2a" and items[1].text is None


def test_reparse_interprets_previously_unparsed_items(db):
    # Nur Schicht 1 speichern — wie ein Bestand, der vor Schicht 2 gescannt wurde.
    _store_png(db, "h1", text_chunk("parameters", A1111))
    _store_png(db, "h2", text_chunk("title", "kein AI-Werkzeug"))

    report = reparse_database(db)

    assert report.items_total == 2
    assert report.items_interpreted == 1
    rows = db.execute(
        "SELECT field, value_text FROM interpreted_metadata WHERE file_hash='h1'"
    ).fetchall()
    fields = {r["field"]: r["value_text"] for r in rows}
    assert fields["seed"] == "777"
    assert fields["model"] == "flux1-dev"
    assert db.execute(
        "SELECT COUNT(*) FROM interpreted_metadata WHERE file_hash='h2'"
    ).fetchone()[0] == 0


def test_reparse_is_idempotent(db):
    _store_png(db, "h1", text_chunk("parameters", A1111))
    reparse_database(db)
    first = db.execute("SELECT COUNT(*) FROM interpreted_metadata").fetchone()[0]
    reparse_database(db)
    assert db.execute("SELECT COUNT(*) FROM interpreted_metadata").fetchone()[0] == first


def test_reparse_replaces_stale_interpretations(db):
    _store_png(db, "h1", text_chunk("parameters", A1111))
    # Veralteten Stand simulieren (z. B. von einer alten Parser-Version).
    stale = interpret_items(raw_items_for(db, "h1"))
    store_interpretations(db, file_hash="h1", interpretations=stale, now=T0)
    db.execute(
        "UPDATE interpreted_metadata SET value_text='veraltet' WHERE field='seed'"
    )
    db.commit()

    reparse_database(db)

    row = db.execute(
        "SELECT value_text FROM interpreted_metadata WHERE file_hash='h1' AND field='seed'"
    ).fetchone()
    assert row["value_text"] == "777"
