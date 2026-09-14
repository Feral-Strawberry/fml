"""Tests für den rekursiven Verzeichnis-Scanner (Stufe 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from feral.db import connect
from feral.scan import scan_directory

from .pngbuild import build_png, itxt_chunk, text_chunk

COMFY_PNG = build_png(
    text_chunk("parameters", "a strawberry\nSteps: 30, Seed: 777"),
    itxt_chunk("workflow", '{"nodes":[{"id":1}]}'),
)
PDF_STUB = b"%PDF-1.4\n%%EOF\n"  # erkannt, aber ohne Extraktor (gestrichen, ADR 0051)


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "feral.sqlite")
    yield conn
    conn.close()


@pytest.fixture
def media_tree(tmp_path):
    """Baut einen kleinen, gemischten Medienbaum auf der Platte."""
    root = tmp_path / "media"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir(parents=True)
    (root / "a" / "comfy.png").write_bytes(COMFY_PNG)
    (root / "a" / "dup.png").write_bytes(COMFY_PNG)        # bit-identische Dublette
    (root / "b" / "papier.pdf").write_bytes(PDF_STUB)      # erkannt, kein Extraktor
    (root / "b" / "notes.txt").write_bytes(b"nur text")    # unbekannt -> übersprungen
    return root


def test_scan_counts(db, media_tree):
    report = scan_directory(db, media_tree)

    assert report.scanned_files == 4
    assert report.media_files == 3          # 2x png + 1x pdf
    assert report.new_items == 2            # comfy-hash + pdf-hash
    assert report.known_items == 1          # die Dublette
    assert report.with_metadata == 2        # beide PNGs hatten Metadaten
    assert report.interpreted == 2          # beide PNGs: Schicht 2 fand Felder
    assert report.pending_extractor == 1    # das PDF
    assert report.skipped_unknown == 1      # die .txt
    assert report.failed == []


def test_scan_writes_expected_db_state(db, media_tree):
    scan_directory(db, media_tree)

    # Zwei einzigartige Items (PNG-Inhalt + PDF), nicht drei (Dublette zählt einmal).
    assert db.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2

    # Der PNG-Inhalt liegt an zwei Fundorten.
    png_hash = db.execute(
        "SELECT file_hash FROM items WHERE container='png'"
    ).fetchone()[0]
    locs = db.execute(
        "SELECT path FROM file_locations WHERE file_hash=? ORDER BY path", (png_hash,)
    ).fetchall()
    assert len(locs) == 2
    assert locs[0]["path"].endswith("comfy.png")
    assert locs[1]["path"].endswith("dup.png")

    # PNG hat zwei Roh-Metadaten-Einträge, das PDF (kein Extraktor) keine.
    assert db.execute(
        "SELECT COUNT(*) FROM raw_metadata WHERE file_hash=?", (png_hash,)
    ).fetchone()[0] == 2
    pdf_hash = db.execute(
        "SELECT file_hash FROM items WHERE container='pdf'"
    ).fetchone()[0]
    assert db.execute(
        "SELECT COUNT(*) FROM raw_metadata WHERE file_hash=?", (pdf_hash,)
    ).fetchone()[0] == 0

    # Schicht 2 lief beim Scan mit: A1111-Parser fand Prompt/Steps/Seed.
    fields = {
        row["field"]: row["value_text"]
        for row in db.execute(
            "SELECT field, value_text FROM interpreted_metadata WHERE file_hash=?",
            (png_hash,),
        ).fetchall()
    }
    assert fields["prompt"] == "a strawberry"
    assert fields["seed"] == "777"


def test_scan_is_idempotent(db, media_tree):
    first = scan_directory(db, media_tree)
    second = scan_directory(db, media_tree)

    # Beim zweiten Lauf ist alles bereits bekannt — keine neuen Items, keine Dubletten.
    assert second.new_items == 0
    assert second.media_files == first.media_files
    assert db.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM file_locations").fetchone()[0] == 3


def test_scan_records_unreadable_file_as_failed(db, tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    (root / "ok.png").write_bytes(COMFY_PNG)
    # Hängender Symlink -> beim Öffnen FileNotFoundError -> 'failed'.
    # Windows erlaubt Symlinks nur mit Adminrechten/Entwicklermodus
    # (WinError 1314) — dann ehrlich überspringen (Issue #50).
    try:
        (root / "broken.png").symlink_to(tmp_path / "does-not-exist.png")
    except OSError as exc:
        pytest.skip(f"Symlinks auf diesem System nicht erlaubt: {exc}")

    report = scan_directory(db, root)

    assert report.new_items == 1
    assert len(report.failed) == 1
    assert "broken.png" in report.failed[0][0]
    # Nicht einmal stat-bar (Symlink ins Leere) ⇒ bewusst KEIN Gedächtnis —
    # über die Datei wissen wir nichts Wiedererkennbares.
    assert db.execute("SELECT COUNT(*) FROM scan_memory").fetchone()[0] == 0


def test_scan_memory_for_non_catalogued(db, media_tree, tmp_path):
    """ADR-0042-Ergänzung (Migration 0019): Unbekanntes und Gesperrtes bekommt
    ein Stat-Gedächtnis, Katalogisiertes NICHT (file_locations übernimmt) —
    und Katalogisieren räumt einen etwaigen Alt-Eintrag des Pfads ab."""
    from feral.hashing import hash_file

    # Gesperrter Inhalt (abgelehnt): comfy.png + dup.png tragen denselben Hash.
    blocked_hash = hash_file(media_tree / "a" / "comfy.png")
    db.execute(
        "INSERT INTO blocked_hashes (file_hash, reason, blocked_at) VALUES (?, 'abgelehnt', 'T0')",
        (blocked_hash,),
    )
    # Veralteter Gedächtnis-Eintrag für eine Datei, die gleich katalogisiert wird.
    db.execute(
        """INSERT INTO scan_memory (path, file_size, mtime_ns, outcome, last_seen_at)
           VALUES (?, 1, 1, 'fehlgeschlagen', 'T0')""",
        (str(media_tree / "b" / "papier.pdf"),),
    )
    db.commit()

    scan_directory(db, media_tree)

    rows = {
        r["path"]: (r["outcome"], r["file_hash"])
        for r in db.execute("SELECT path, outcome, file_hash FROM scan_memory")
    }
    by_name = {Path(p).name: v for p, v in rows.items()}
    assert by_name["notes.txt"] == ("unbekannt", None)
    assert by_name["comfy.png"] == ("gesperrt", blocked_hash)
    assert by_name["dup.png"] == ("gesperrt", blocked_hash)
    assert "papier.pdf" not in by_name   # katalogisiert ⇒ Alt-Eintrag weg

    # Der Watcher lädt das Gedächtnis mit ⇒ Neustart liest nichts davon neu.
    sizes = {
        r["path"]: r["file_size"] for r in db.execute("SELECT path, file_size FROM scan_memory")
    }
    for path, size in sizes.items():
        assert Path(path).stat().st_size == size


def test_progress_callback_is_invoked(db, media_tree):
    seen = []
    scan_directory(db, media_tree, progress=lambda rep, p: seen.append(p.name))
    assert len(seen) == 4


# -- Import-Regeln beim Katalogisieren (ADR 0046) -----------------------------------


def test_scan_respects_import_rules(db, tmp_path):
    from .pngbuild import build_png, ihdr, text_chunk
    root = tmp_path / "laufwerk"
    root.mkdir()
    (root / "mini.png").write_bytes(
        build_png(ihdr(64, 64), text_chunk("parameters", "p"), include_ihdr=False))
    (root / "ok.png").write_bytes(
        build_png(ihdr(512, 512), text_chunk("parameters", "p"), include_ihdr=False))
    (root / "foto.arw").write_bytes(b"II\x2a\x00" + b"\x00" * 64)

    report = scan_directory(
        db, root, rules={"min_kante": 240, "max_kante": 0, "formate": ["arw"]})

    assert report.ausgefiltert == 2 and report.new_items == 1
    assert db.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
    # Stat-Gedächtnis (ADR 0042): Ausgefiltertes wird beim nächsten Watcher-
    # Lauf nicht neu gelesen.
    outcomes = {r["path"]: r["outcome"] for r in db.execute(
        "SELECT path, outcome FROM scan_memory")}
    assert outcomes[str(root / "mini.png")] == "ausgefiltert"
    assert outcomes[str(root / "foto.arw")] == "ausgefiltert"


def test_scan_date_rule_uses_configured_min_date(db, tmp_path):
    """Datumsregel beim Katalogisieren (ADR 0075, #113): ein Stempel vor
    min_date wird ausgefiltert statt mit leerem Datum katalogisiert; mit
    gesenktem min_date (Config → rules) kommt die Datei datiert herein."""
    import os
    from .pngbuild import build_png, text_chunk
    root = tmp_path / "laufwerk"
    root.mkdir()
    old = root / "uralt.png"
    old.write_bytes(build_png(text_chunk("parameters", "p")))
    os.utime(old, (0, 0))   # 1.1.1970

    report = scan_directory(db, root, rules={"min_kante": 0, "max_kante": 0, "formate": []})
    assert report.ausgefiltert == 1 and report.new_items == 0
    assert db.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0
    assert db.execute("SELECT outcome FROM scan_memory").fetchone()[0] == "ausgefiltert"

    report = scan_directory(
        db, root, rules={"min_kante": 0, "max_kante": 0, "formate": [],
                         "min_date": "1970-01-01"})
    assert report.new_items == 1
    assert db.execute("SELECT media_date FROM items").fetchone()[0] == "1970-01-01 00:00:00"


# -- Nicht abspielbare Codecs (Issue #71, ADR 0070) --------------------------------

def _stream_items(codec: str, pix_fmt: str):
    from feral.extract.types import RawMetadataItem

    def fact(keyword, text):
        return RawMetadataItem(source="isobmff:stream0", keyword=keyword, text=text,
                               data=None, encoding="utf-8")
    return [fact("codec_type", "video"), fact("codec_name", codec), fact("pix_fmt", pix_fmt)]


def _fake_extract(codec: str, pix_fmt: str):
    from feral.extract.types import ContainerExtraction

    def extract(path):
        return ContainerExtraction(container="isobmff", items=_stream_items(codec, pix_fmt))
    return extract


def test_scan_records_playback_issue_for_prores_and_resolves_after_recode(db, tmp_path, monkeypatch):
    from feral import scan as scan_mod

    root = tmp_path / "vids"
    root.mkdir()
    clip = root / "topaz.mov"
    clip.write_bytes(b"\x00" * 32)

    monkeypatch.setattr(scan_mod.container, "extract", _fake_extract("prores", "yuv422p10le"))
    scan_directory(db, root)

    rows = db.execute(
        "SELECT kind, message, resolved FROM scan_issues WHERE path = ?", (str(clip),)
    ).fetchall()
    assert [(r["kind"], r["resolved"]) for r in rows] == [("playback", 0)]
    assert '"key": "issueUnplayable"' in rows[0]["message"]
    assert '"codec": "prores"' in rows[0]["message"]
    # Schicht 2 trägt das Feld — der Chip »video_codec: prores« findet die Datei.
    assert db.execute(
        "SELECT value_text FROM interpreted_metadata WHERE field = 'video_codec'"
    ).fetchone()[0] == "prores"

    # Re-Scan mit unverändertem Codec: bleibt offen (ein Problem, kein Duplikat).
    scan_directory(db, root)
    assert db.execute("SELECT COUNT(*) FROM scan_issues WHERE resolved = 0").fetchone()[0] == 1

    # Datei inzwischen als H.264 8-bit neu geschrieben: Problem quittiert sich selbst.
    clip.write_bytes(b"\x01" * 32)
    monkeypatch.setattr(scan_mod.container, "extract", _fake_extract("h264", "yuv420p"))
    scan_directory(db, root)
    assert db.execute("SELECT COUNT(*) FROM scan_issues WHERE resolved = 0").fetchone()[0] == 0


def test_scan_hevc_is_limited_not_unplayable(db, tmp_path, monkeypatch):
    from feral import scan as scan_mod

    root = tmp_path / "vids"
    root.mkdir()
    (root / "clip.mp4").write_bytes(b"\x00" * 32)
    monkeypatch.setattr(scan_mod.container, "extract", _fake_extract("hevc", "yuv420p10le"))
    scan_directory(db, root)
    row = db.execute("SELECT kind, message FROM scan_issues").fetchone()
    assert row["kind"] == "playback" and '"key": "issueLimitedPlayback"' in row["message"]
