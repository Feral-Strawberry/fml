"""Tests für Sammel-Aktionen auf das Suchergebnis (Großbaustelle K, ADR 0040)."""

from __future__ import annotations

import pytest

from feral.db import connect, manual, store_extraction
from feral.extract.types import ContainerExtraction
from feral.web.bulk import apply_bulk

T0 = "2026-01-01T00:00:00+00:00"

A = "aa" * 32
B = "bb" * 32
C = "cc" * 32


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    for file_hash in (A, B, C):
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


def _fts_manuell(conn, file_hash):
    row = conn.execute(
        """SELECT s.manuell FROM search_index s
            JOIN search_index_map m ON m.fts_rowid = s.rowid
           WHERE m.file_hash = ?""",
        (file_hash,),
    ).fetchone()
    return row[0] if row else ""


# -- Bewertung: Basisbewertung füllt nur Unbewertete --------------------------------


def test_rating_fills_only_unrated(db):
    manual.set_rating(db, B, 5, now=T0)
    summary = apply_bulk(db, filter_expr="", rating=2, now=T0)
    assert summary["matched"] == 3
    assert summary["rating_set"] == 2          # A und C; B war schon bewertet
    assert manual.annotations_for(db, A)["rating"] == 2
    assert manual.annotations_for(db, B)["rating"] == 5   # unangetastet
    assert manual.annotations_for(db, C)["rating"] == 2


def test_rating_zero_rejected(db):
    with pytest.raises(ValueError):
        apply_bulk(db, filter_expr="", rating=0)


# -- Tag: idempotent für alle Treffer -------------------------------------------------


def test_tag_all_and_idempotent(db):
    manual.add_tag(db, A, "wip", now=T0)
    summary = apply_bulk(db, filter_expr="", add_tag="wip", now=T0)
    assert summary["tagged"] == 2               # A hatte ihn schon
    assert manual.annotations_for(db, B)["tags"] == ["wip"]
    assert "wip" in _fts_manuell(db, B)         # sofort findbar (ADR 0036)

    again = apply_bulk(db, filter_expr="", add_tag="WIP", now=T0)
    assert again["tagged"] == 0                 # case-insensitiv, nichts Neues


# -- Notiz: anhängen, nie überschreiben ------------------------------------------------


def test_note_appends(db):
    manual.set_notes(db, A, "alt", now=T0)
    summary = apply_bulk(db, filter_expr="", note="neu", now=T0)
    assert summary["noted"] == 3
    assert manual.annotations_for(db, A)["notes"] == "alt\nneu"
    assert manual.annotations_for(db, B)["notes"] == "neu"
    assert "neu" in _fts_manuell(db, A)


# -- Manuelles Modell: setzen wie Multiselect (ADR 0022) --------------------------------


def test_model_set_counts_changes(db):
    manual.set_model(db, A, "flux", now=T0)
    summary = apply_bulk(db, filter_expr="", model="flux", now=T0)
    assert summary["model_set"] == 2            # A stand schon auf flux
    assert manual.annotations_for(db, B)["model"] == "flux"
    assert "flux" in _fts_manuell(db, C)


# -- Scopes: Filterausdruck und Hash-Liste ---------------------------------------------


def test_filter_scope_limits_matches(db):
    manual.add_tag(db, A, "auswahl", now=T0)
    summary = apply_bulk(db, filter_expr="tag: auswahl", rating=3, now=T0)
    assert summary["matched"] == 1
    assert manual.annotations_for(db, A)["rating"] == 3
    assert manual.annotations_for(db, B)["rating"] is None


def test_hashes_scope_skips_unknown(db):
    summary = apply_bulk(db, hashes=[A, "ff" * 32], add_tag="x", now=T0)
    assert summary["matched"] == 1              # unbekannter Hash still übersprungen
    assert manual.annotations_for(db, A)["tags"] == ["x"]


def test_invalid_filter_raises(db):
    with pytest.raises(ValueError):
        apply_bulk(db, filter_expr="rating>>3", rating=1)


def test_no_action_raises(db):
    with pytest.raises(ValueError):
        apply_bulk(db, filter_expr="")


# -- Ablehnen (ADR 0041): Item raus + Sperre, Datei bleibt -------------------------------


def test_reject_blocks_and_keeps_files(db, tmp_path):
    source = tmp_path / f"{A[:6]}.png"
    source.write_bytes(b"nicht anfassen")
    manual.set_rating(db, A, 4, now=T0)

    summary = apply_bulk(db, hashes=[A], reject=True, now=T0)

    assert summary == {"matched": 1, "rejected": 1}
    assert source.read_bytes() == b"nicht anfassen"   # Original heilig
    assert db.execute("SELECT COUNT(*) FROM items WHERE file_hash = ?", (A,)).fetchone()[0] == 0
    blocked = db.execute(
        "SELECT reason, last_paths FROM blocked_hashes WHERE file_hash = ?", (A,)
    ).fetchone()
    assert blocked["reason"] == '{"key": "blockedRejected"}'
    assert str(source) in blocked["last_paths"]       # Pfad-Gedächtnis für I3
    assert _fts_manuell(db, A) == ""                  # FTS-Zeile weg
    assert db.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2   # B, C unberührt


def test_reject_removes_thumbs(db, tmp_path):
    from feral.thumbs import thumb_path

    cache = tmp_path / "cache"
    thumb = thumb_path(cache, B)
    thumb.parent.mkdir(parents=True)
    thumb.write_bytes(b"jpg")
    apply_bulk(db, hashes=[B], reject=True, thumb_cache=cache, now=T0)
    assert not thumb.exists()


def test_reject_runs_alone(db):
    with pytest.raises(ValueError):
        apply_bulk(db, filter_expr="", reject=True, add_tag="x")


def test_reject_writes_stat_memory_and_unblock_clears_it(db, tmp_path):
    """ADR-0042-Ergänzung (Migration 0019): Ablehnen übernimmt die bekannten
    Stats aus file_locations ins scan_memory — der Watcher hasht Abgelehnte
    nach Neustarts nicht mehr; Entsperren räumt per Hash wieder auf."""
    from feral.web.admin import unblock

    # A bekommt einen Fundort MIT Stat (wie ihn Scan/Import seit 0018 schreiben).
    db.execute(
        "UPDATE file_locations SET file_size = 123, mtime_ns = 456 WHERE file_hash = ?",
        (A,),
    )
    db.commit()

    apply_bulk(db, hashes=[A, B], reject=True, now=T0)

    rows = db.execute(
        "SELECT path, file_size, mtime_ns, outcome, file_hash FROM scan_memory"
    ).fetchall()
    # Nur A hatte Stats — B (Alt-Zeile ohne mtime_ns) bekommt bewusst keinen
    # Eintrag und läuft einmal den vollen Weg (der Scan schreibt ihn dann).
    assert len(rows) == 1
    assert rows[0]["outcome"] == "gesperrt" and rows[0]["file_hash"] == A
    assert (rows[0]["file_size"], rows[0]["mtime_ns"]) == (123, 456)

    unblock(db, A)
    assert db.execute("SELECT COUNT(*) FROM scan_memory").fetchone()[0] == 0
    assert db.execute(
        "SELECT COUNT(*) FROM blocked_hashes WHERE file_hash = ?", (A,)
    ).fetchone()[0] == 0
