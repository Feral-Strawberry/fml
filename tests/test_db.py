"""Tests für die Persistenz-Schicht (ADR 0010)."""

from __future__ import annotations

import io

import pytest

from feral.db import connect, media_kind_for, schema_version, store_extraction
from feral.extract import png
from feral.extract.types import ContainerExtraction, RawMetadataItem

from .pngbuild import build_png, exif_chunk, itxt_chunk, text_chunk

T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-02T12:00:00+00:00"

A1111 = "masterpiece\nSteps: 20, Seed: 12345"
WORKFLOW = '{"nodes": [{"id": 1}]}'


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    yield conn
    conn.close()


def _sample_extraction() -> ContainerExtraction:
    data = build_png(text_chunk("parameters", A1111), itxt_chunk("workflow", WORKFLOW))
    return png.extract(io.BytesIO(data))


def test_schema_version_is_set(db):
    assert db.execute("PRAGMA user_version").fetchone()[0] == schema_version()


def test_media_kind_mapping():
    assert media_kind_for("png") == "image"
    assert media_kind_for("matroska") == "video"
    assert media_kind_for("pdf") == "document"
    assert media_kind_for("nonsense") == "unknown"


def test_store_and_read_back(db):
    extraction = _sample_extraction()
    store_extraction(
        db,
        file_hash="hash-a",
        file_size=4242,
        path="/media/2026/a.png",
        extraction=extraction,
        now=T0,
    )

    item = db.execute("SELECT * FROM items WHERE file_hash='hash-a'").fetchone()
    assert item["file_size"] == 4242
    assert item["container"] == "png"
    assert item["media_kind"] == "image"
    assert item["image_hash"] is None
    assert item["first_seen_at"] == T0 and item["updated_at"] == T0

    loc = db.execute("SELECT * FROM file_locations WHERE file_hash='hash-a'").fetchone()
    assert loc["path"] == "/media/2026/a.png"

    rows = db.execute(
        "SELECT * FROM raw_metadata WHERE file_hash='hash-a' ORDER BY ordinal"
    ).fetchall()
    assert [r["keyword"] for r in rows] == ["parameters", "workflow"]
    assert rows[0]["value_text"] == A1111
    # value_raw ist byte-exakt und entspricht dem zurückkodierten Text.
    assert bytes(rows[0]["value_raw"]) == A1111.encode("latin-1")
    assert bytes(rows[1]["value_raw"]) == WORKFLOW.encode("utf-8")


def test_value_raw_byte_exact_for_unicode(db):
    text = "Prompt mit Ümläüt und 🍓"
    extraction = png.extract(io.BytesIO(build_png(itxt_chunk("prompt", text))))
    store_extraction(
        db, file_hash="h", file_size=1, path="/x.png", extraction=extraction, now=T0
    )
    row = db.execute("SELECT * FROM raw_metadata WHERE file_hash='h'").fetchone()
    assert row["value_text"] == text
    assert bytes(row["value_raw"]) == text.encode("utf-8")


def test_binary_item_has_null_text_but_raw_bytes(db):
    raw = b"MM\x00\x2a\x00\x00\x00\x08exifbytes"
    extraction = png.extract(io.BytesIO(build_png(exif_chunk(raw))))
    store_extraction(
        db, file_hash="h", file_size=1, path="/x.png", extraction=extraction, now=T0
    )
    row = db.execute("SELECT * FROM raw_metadata WHERE file_hash='h'").fetchone()
    assert row["source"] == "png:eXIf"
    assert row["value_text"] is None
    assert bytes(row["value_raw"]) == raw
    assert row["encoding"] == "binary"


def test_rescan_is_idempotent(db):
    extraction = _sample_extraction()
    store_extraction(db, file_hash="h", file_size=10, path="/a.png", extraction=extraction, now=T0)
    store_extraction(db, file_hash="h", file_size=10, path="/a.png", extraction=extraction, now=T1)

    # Genau ein Item, ein Fundort, gleiche Anzahl Roh-Einträge (keine Duplikate).
    assert db.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM file_locations").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM raw_metadata WHERE file_hash='h'").fetchone()[0] == 2

    item = db.execute("SELECT * FROM items WHERE file_hash='h'").fetchone()
    assert item["first_seen_at"] == T0  # bleibt
    assert item["updated_at"] == T1     # wandert mit


def test_same_hash_second_path_adds_location(db):
    extraction = _sample_extraction()
    store_extraction(db, file_hash="h", file_size=10, path="/a.png", extraction=extraction, now=T0)
    store_extraction(db, file_hash="h", file_size=10, path="/copy/a.png", extraction=extraction, now=T1)

    paths = {
        r["path"]
        for r in db.execute("SELECT path FROM file_locations WHERE file_hash='h'").fetchall()
    }
    assert paths == {"/a.png", "/copy/a.png"}


def test_new_hash_at_known_path_replaces_stale_location(db):
    """Fundort-Eindeutigkeit (ADR 0049): ein Pfad enthält genau EINE Datei.

    Umsortieren mit Namens-Kollision (Krea2_00013_.png an neuer Stelle):
    liegt an einem katalogisierten Pfad ein neuer Hash, muss die alte
    Fundort-Zeile weichen — andere Fundorte des alten Hashes bleiben.
    """
    extraction = _sample_extraction()
    store_extraction(db, file_hash="alt", file_size=10, path="/w/bild.png", extraction=extraction, now=T0)
    store_extraction(db, file_hash="alt", file_size=10, path="/archiv/bild.png", extraction=extraction, now=T0)
    store_extraction(db, file_hash="neu", file_size=11, path="/w/bild.png", extraction=extraction, now=T1)

    locs = [
        (r["file_hash"], r["path"])
        for r in db.execute("SELECT file_hash, path FROM file_locations ORDER BY id").fetchall()
    ]
    assert locs == [("alt", "/archiv/bild.png"), ("neu", "/w/bild.png")]


def test_image_hash_stored_and_preserved_on_rescan(db):
    extraction = _sample_extraction()
    store_extraction(
        db, file_hash="h", file_size=10, path="/a.png",
        extraction=extraction, image_hash="pixelhash", now=T0,
    )
    # Re-Scan ohne image_hash darf den vorhandenen nicht löschen (COALESCE).
    store_extraction(
        db, file_hash="h", file_size=10, path="/a.png", extraction=extraction, now=T1
    )
    item = db.execute("SELECT image_hash FROM items WHERE file_hash='h'").fetchone()
    assert item["image_hash"] == "pixelhash"


def test_foreign_key_cascade_deletes_children(db):
    extraction = _sample_extraction()
    store_extraction(db, file_hash="h", file_size=10, path="/a.png", extraction=extraction, now=T0)

    with db:
        db.execute("DELETE FROM items WHERE file_hash='h'")

    assert db.execute("SELECT COUNT(*) FROM raw_metadata WHERE file_hash='h'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM file_locations WHERE file_hash='h'").fetchone()[0] == 0


def test_warnings_do_not_block_storage(db):
    # Eine Extraktion mit Warnung, aber gültigen Items, wird trotzdem gespeichert.
    extraction = ContainerExtraction(
        container="png",
        items=[
            RawMetadataItem(
                source="png:tEXt", keyword="k", text="v", data=None, encoding="latin-1"
            )
        ],
        warnings=["irgendeine Warnung"],
    )
    store_extraction(db, file_hash="h", file_size=1, path="/a.png", extraction=extraction, now=T0)
    assert db.execute("SELECT COUNT(*) FROM raw_metadata").fetchone()[0] == 1
