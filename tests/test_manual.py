"""Tests für die manuelle Schicht: Rating, Notizen, Tags (Stufe 3.1, ADR 0017)."""

from __future__ import annotations

import pytest

from feral.db import connect, manual, store_extraction
from feral.extract.types import ContainerExtraction

T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-02T12:00:00+00:00"

HASH = "ab" * 32
OTHER = "cd" * 32


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    for file_hash in (HASH, OTHER):
        store_extraction(
            conn,
            file_hash=file_hash,
            file_size=123,
            path=tmp_path / f"{file_hash[:6]}.png",
            extraction=ContainerExtraction(container="png"),
            now=T0,
        )
    yield conn
    conn.close()


# -- Manuelles Modell (ADR 0022) ---------------------------------------------------


def test_set_model_and_clear(db):
    manual.set_model(db, HASH, "Midjourney V5", now=T0)
    assert manual.annotations_for(db, HASH)["model"] == "Midjourney V5"

    manual.set_model(db, HASH, "  ", now=T1)   # leer = löschen
    assert manual.annotations_for(db, HASH)["model"] is None
    # Zeile ohne Rating/Notizen/Modell wird aufgeräumt.
    assert db.execute("SELECT COUNT(*) FROM annotations").fetchone()[0] == 0


def test_model_keeps_row_alive_without_rating(db):
    manual.set_model(db, HASH, "Midjourney V5", now=T0)
    manual.set_rating(db, HASH, 0, now=T1)     # Rating löschen ≠ Modell löschen
    assert manual.annotations_for(db, HASH)["model"] == "Midjourney V5"


# -- Rating ----------------------------------------------------------------------


def test_set_and_update_rating(db):
    manual.set_rating(db, HASH, 4, now=T0)
    assert manual.annotations_for(db, HASH)["rating"] == 4

    manual.set_rating(db, HASH, 5, now=T1)
    a = manual.annotations_for(db, HASH)
    assert a["rating"] == 5
    assert a["updated_at"] == T1  # jede Änderung trägt Zeitstempel (ADR 0003)


def test_rating_zero_clears_and_prunes_empty_row(db):
    manual.set_rating(db, HASH, 3, now=T0)
    manual.set_rating(db, HASH, 0, now=T1)
    assert manual.annotations_for(db, HASH)["rating"] is None
    # Zeile ohne Rating und Notizen verschwindet komplett.
    assert db.execute("SELECT COUNT(*) FROM annotations").fetchone()[0] == 0


def test_rating_validation(db):
    with pytest.raises(ValueError):
        manual.set_rating(db, HASH, 6)
    with pytest.raises(ValueError):
        manual.set_rating(db, "00" * 32, 3)  # unbekanntes Item


# -- Notizen ---------------------------------------------------------------------


def test_notes_set_and_clear(db):
    manual.set_notes(db, HASH, "  Favorit fürs Portfolio  ", now=T0)
    assert manual.annotations_for(db, HASH)["notes"] == "Favorit fürs Portfolio"

    manual.set_notes(db, HASH, "", now=T1)
    assert manual.annotations_for(db, HASH)["notes"] is None
    assert db.execute("SELECT COUNT(*) FROM annotations").fetchone()[0] == 0


def test_notes_keep_rating_row_alive(db):
    manual.set_rating(db, HASH, 2, now=T0)
    manual.set_notes(db, HASH, None, now=T1)  # Notizen löschen ≠ Rating löschen
    assert manual.annotations_for(db, HASH)["rating"] == 2


# -- Tags ------------------------------------------------------------------------


def test_add_tag_is_idempotent_and_case_insensitive(db):
    a = manual.add_tag(db, HASH, "Portrait", now=T0)
    b = manual.add_tag(db, HASH, "portrait", now=T1)  # gleicher Tag, andere Schreibung
    assert a == b
    assert manual.annotations_for(db, HASH)["tags"] == ["Portrait"]
    assert db.execute("SELECT COUNT(*) FROM tags").fetchone()[0] == 1


def test_tags_are_shared_between_items(db):
    manual.add_tag(db, HASH, "flux", now=T0)
    manual.add_tag(db, OTHER, "flux", now=T0)
    counts = {t["name"]: t["count"] for t in manual.list_tags(db)}
    assert counts == {"flux": 2}


def test_remove_tag_keeps_vocabulary(db):
    manual.add_tag(db, HASH, "Experiment", now=T0)
    assert manual.remove_tag(db, HASH, "experiment") is True
    assert manual.remove_tag(db, HASH, "experiment") is False  # schon weg
    assert manual.annotations_for(db, HASH)["tags"] == []
    # Tag bleibt als Vokabular erhalten (Zähler 0).
    assert manual.list_tags(db) == [
        {"id": 1, "name": "Experiment", "count": 0}
    ]


def test_empty_tag_name_rejected(db):
    with pytest.raises(ValueError):
        manual.add_tag(db, HASH, "   ")


# -- Trennung der Schichten (ADR 0005) ---------------------------------------------


def test_manual_layer_touches_no_extracted_tables(db):
    manual.set_rating(db, HASH, 5, now=T0)
    manual.add_tag(db, HASH, "check", now=T0)
    assert db.execute("SELECT COUNT(*) FROM raw_metadata").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM interpreted_metadata").fetchone()[0] == 0
