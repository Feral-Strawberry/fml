"""Manuelles Datum + Tag-Jahr in der Datums-Kaskade (#220, ADR 0096)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from feral import importer
from feral.db import connect, manual, store_extraction
from feral.db.store import store_interpretations
from feral.extract.types import ContainerExtraction, RawMetadataItem
from feral.interpret import reparse_database
from feral.interpret.types import InterpretedField, Interpretation
from feral.messages import UserError
from feral.web import bulk, library

UTC = timezone.utc


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    yield conn
    conn.close()


def _put(db, tmp_path, h, *, kind="image", container="png", mtime=None):
    path = tmp_path / f"{h[:4]}.{container}"
    path.write_bytes(b"x")
    if mtime is not None:
        os.utime(path, (mtime.timestamp(), mtime.timestamp()))
    store_extraction(db, file_hash=h, file_size=1, path=str(path),
                     extraction=ContainerExtraction(container=container, media_kind=kind))
    return path


def _date(db, h):
    return db.execute("SELECT media_date FROM items WHERE file_hash = ?", (h,)).fetchone()[0]


@pytest.mark.parametrize("text, stored", [
    ("1997", "1997"), ("1997-5", "1997-05"), ("1997-05-12", "1997-05-12"),
    ("12.5.1997", "1997-05-12"), ("05.1997", "1997-05"), (" 1987 ", "1987"),
])
def test_parse_manual_date_keeps_precision(text, stored):
    assert manual.parse_manual_date(text) == stored


@pytest.mark.parametrize("text", ["97", "1997-13", "1997-02-30", "2999", "gestern", "999"])
def test_parse_manual_date_rejects(text):
    with pytest.raises(UserError):
        manual.parse_manual_date(text)


def test_manual_date_wins_and_clearing_restores_derived(db, tmp_path):
    h = "a" * 64
    _put(db, tmp_path, h, mtime=datetime(2024, 3, 1, 12, tzinfo=UTC))
    importer.set_media_date(db, h, datetime(2024, 3, 1, 12, tzinfo=UTC), "dateisystem")
    assert manual.set_media_date(db, h, "1997") == "1997"
    assert _date(db, h) == "1997"
    assert manual.annotations_for(db, h)["media_date"] == "1997"
    # Keine Kaskade überschreibt das manuelle Datum.
    importer.set_media_date(db, h, datetime(2025, 1, 1, tzinfo=UTC), "metadaten")
    assert _date(db, h) == "1997"
    assert importer.backfill_media_dates(db)["total"] == 0
    # Leeren: zurück zum abgeleiteten Datum, die leere Annotation verschwindet.
    assert manual.set_media_date(db, h, "") == "2024-03-01 12:00:00"
    assert db.execute("SELECT COUNT(*) FROM annotations").fetchone()[0] == 0


def test_tag_year_in_import_cascade_only_for_audio_and_plausible():
    items = [RawMetadataItem("id3v2:TYER", None, "2019", None, "utf-8")]
    stat = SimpleNamespace(st_mtime=datetime(2026, 9, 1, tzinfo=UTC).timestamp())
    song = ContainerExtraction(container="mp3", media_kind="audio", items=items)
    assert importer.determine_date(song, stat) == (datetime(2019, 1, 1, tzinfo=UTC), "tagjahr")
    # Vor min_date (Standard 2015) unplausibel → Dateistempel.
    old = ContainerExtraction(container="mp3", media_kind="audio",
                              items=[RawMetadataItem("id3v2:TYER", None, "1987", None, "utf-8")])
    assert importer.determine_date(old, stat)[1] == "dateisystem"
    low = datetime(1950, 1, 1, tzinfo=UTC)
    assert importer.determine_date(old, stat, min_date=low) == (
        datetime(1987, 1, 1, tzinfo=UTC), "tagjahr")


def test_tag_year_stored_as_year_and_counted_in_year_facet(db, tmp_path):
    h = "b" * 64
    _put(db, tmp_path, h, kind="audio", container="mp3")
    importer.set_media_date(db, h, datetime(1987, 1, 1, tzinfo=UTC), importer.TAG_YEAR)
    assert _date(db, h) == "1987"
    years = library.year_counts(db)["years"]
    assert years == [{"year": "1987", "count": 1, "months": []}]
    ctx = library.facets_payload(db, filter_expr="typ: audio")
    assert ctx["years"][0]["count"] == 1
    assert {i["file_hash"] for i in library.list_items(db, filter_expr="year: 1987")["items"]} == {h}


def test_reparse_brings_tag_year_and_clear_uses_it(db, tmp_path):
    h = "c" * 64
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    store_extraction(db, file_hash=h, file_size=1, path=str(path), extraction=ContainerExtraction(
        container="mp3", media_kind="audio",
        items=[RawMetadataItem("id3v2:TYER", None, "2016", None, "utf-8")]))
    db.execute("UPDATE items SET media_date = '2026-09-01 00:00:00' WHERE file_hash = ?", (h,))
    db.commit()
    reparse_database(db)
    assert _date(db, h) == "2016"
    manual.set_media_date(db, h, "2001-02")
    assert manual.set_media_date(db, h, None) == "2016"


def test_bulk_sets_date_for_all_hits(db, tmp_path):
    for h in ("d" * 64, "e" * 64):
        _put(db, tmp_path, h, kind="audio", container="mp3")
    out = bulk.apply_bulk(db, filter_expr="typ: audio", media_date="05.1983")
    assert out["date_set"] == 2
    assert {_date(db, h) for h in ("d" * 64, "e" * 64)} == {"1983-05"}
    with pytest.raises(UserError):
        bulk.apply_bulk(db, filter_expr="", media_date="1983-13")
