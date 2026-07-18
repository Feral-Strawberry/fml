"""Tests für den Admin-Bereich (Stufe 2A, ADR 0014)."""

from __future__ import annotations

import io

import pytest

from feral.db import connect, store_extraction
from feral.extract import png
from feral.scan import scan_directory
from feral.web import admin

from .pngbuild import build_png, text_chunk


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "feral.sqlite"


@pytest.fixture
def db(db_path):
    conn = connect(db_path)
    yield conn
    conn.close()


def _store(db, file_hash, path):
    extraction = png.extract(io.BytesIO(build_png(text_chunk("parameters", "x"))))
    store_extraction(db, file_hash=file_hash, file_size=1, path=path, extraction=extraction)


# --- admin_info ---------------------------------------------------------------

def test_admin_info_reports_counts_and_tools(db, db_path, tmp_path):
    _store(db, "h1", "/a.png")
    cache = tmp_path / "cache"
    (cache / "ab").mkdir(parents=True)
    (cache / "ab" / "x.jpg").write_bytes(b"jpegdaten")

    info = admin.admin_info(db, db_path=db_path, thumb_cache=cache)

    assert info["schema_version"] >= 3
    assert info["tables"]["items"] == 1
    assert info["tables"]["raw_metadata"] == 1
    assert info["thumb_count"] == 1 and info["thumb_bytes"] == 9
    assert info["orphan_locations"] == 1          # /a.png existiert nicht
    assert isinstance(info["ffprobe"], bool)
    assert {p["name"] for p in info["parsers"]} >= {"a1111", "comfyui"}


# --- Scan-Probleme --------------------------------------------------------------

def test_scan_records_and_resolves_issues(db, tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    bad = root / "kaputt.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\xff" * 8)   # Signatur ok, Rest Müll

    scan_directory(db, root)
    issues = admin.list_issues(db)
    assert len(issues) >= 1
    assert issues[0]["path"] == str(bad)
    assert issues[0]["kind"] == "warning"

    # Erneuter Scan derselben kaputten Datei erzeugt KEINE Duplikate.
    scan_directory(db, root)
    assert len(admin.list_issues(db)) == len(issues)

    # Datei reparieren -> sauberer Re-Scan quittiert die offenen Probleme.
    bad.write_bytes(build_png(text_chunk("parameters", "jetzt ok")))
    scan_directory(db, root)
    assert admin.list_issues(db) == []


def test_resolve_issues_single_and_all(db, tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    for name in ("a.png", "b.png"):
        (root / name).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\xff" * 8)
    scan_directory(db, root)

    issues = admin.list_issues(db)
    assert len(issues) == 2
    assert admin.resolve_issues(db, issue_id=issues[0]["id"]) == 1
    assert len(admin.list_issues(db)) == 1
    assert admin.resolve_issues(db) == 1     # Rest: alle quittieren
    assert admin.list_issues(db) == []


def test_issue_overview_groups_with_honest_totals(db):
    """Block N: gruppiert nach Fehlerart, Gesamtzahl ehrlich auch jenseits
    des per_kind-Deckels; Quittieren je Art trifft ALLE der Art."""
    from feral.db.store import now_iso

    ts = now_iso()
    rows = [(f"/w/{i}.png", "warning", "w", ts) for i in range(5)]
    rows += [(f"/f/{i}.png", "failed", "f", ts) for i in range(2)]
    db.executemany(
        """INSERT INTO scan_issues (path, kind, message, first_seen_at, last_seen_at)
           VALUES (?, ?, ?, ?, ?)""",
        [(p, k, m, t, t) for p, k, m, t in rows],
    )
    db.commit()

    ov = admin.issue_overview(db, per_kind=3)
    assert ov["total"] == 7
    assert [(k["kind"], k["count"], len(k["issues"])) for k in ov["kinds"]] == [
        ("warning", 5, 3),      # Deckel greift, Zähler bleibt ehrlich
        ("failed", 2, 2),
    ]

    assert admin.resolve_issues(db, kind="warning") == 5   # alle, nicht nur 3
    ov = admin.issue_overview(db)
    assert ov["total"] == 2 and ov["kinds"][0]["kind"] == "failed"


# --- Verwaiste Fundorte -----------------------------------------------------------

def test_orphan_locations_and_prune(db, tmp_path):
    real = tmp_path / "echt.png"
    real.write_bytes(build_png(text_chunk("parameters", "x")))
    _store(db, "h1", str(real))            # existiert
    _store(db, "h2", "/weg/fort.png")      # existiert nicht

    orphans = admin.orphan_locations(db)
    assert [o["path"] for o in orphans] == ["/weg/fort.png"]

    assert admin.prune_orphan_locations(db) == 1
    # Item bleibt erhalten — nur die Pfad-Buchhaltung ist weg (BAUPLAN 2A.1).
    assert db.execute("SELECT COUNT(*) FROM items WHERE file_hash='h2'").fetchone()[0] == 1
    assert db.execute(
        "SELECT COUNT(*) FROM file_locations WHERE file_hash='h2'"
    ).fetchone()[0] == 0
    assert admin.orphan_locations(db) == []


# --- Thumbnail-Cache ---------------------------------------------------------------

def test_clear_thumb_cache(tmp_path):
    cache = tmp_path / "cache"
    (cache / "ab").mkdir(parents=True)
    (cache / "ab" / "x.jpg").write_bytes(b"x")
    (cache / "ab" / "y.fail").write_text("kaputt")

    assert admin.clear_thumb_cache(cache) == 2
    assert not cache.exists()
    assert admin.clear_thumb_cache(cache) == 0  # idempotent


def test_prune_orphans_nur_unterhalb_pfad(db, tmp_path):
    """Pfad-bezogenes Aufräumen (ADR 0033): eine ausgehängte Platte sieht aus
    wie „weg" — der Scope schützt Fundorte außerhalb des gewählten Ordners."""
    _store(db, "h1", str(tmp_path / "quelle" / "a.png"))   # Waise im Scope
    _store(db, "h2", "/volumes/offline-platte/b.png")      # Waise außerhalb

    assert admin.prune_orphan_locations(db, under=str(tmp_path / "quelle")) == 1
    remaining = [r["path"] for r in db.execute("SELECT path FROM file_locations")]
    assert remaining == ["/volumes/offline-platte/b.png"]


# --- Import-Regeln auf den Bestand (ADR 0046) -----------------------------------

def _store_sized(db, file_hash, path, *, width, height, container="png"):
    extraction = png.extract(io.BytesIO(build_png(text_chunk("parameters", "x"))))
    store_extraction(db, file_hash=file_hash, file_size=1, path=path,
                     extraction=extraction)
    db.execute("UPDATE items SET width = ?, height = ?, container = ? "
               "WHERE file_hash = ?", (width, height, container, file_hash))
    db.commit()


def test_import_rules_overview_and_apply(db):
    _store_sized(db, "a1" * 32, "/mini.png", width=100, height=100)
    _store_sized(db, "b2" * 32, "/ok.png", width=1024, height=1024)
    _store_sized(db, "c3" * 32, "/kontaktbogen.png", width=30000, height=2000)
    _store_sized(db, "d4" * 32, "/foto.arw", width=None, height=None,
                 container="arw")

    rules = {"min_kante": 240, "max_kante": 8000, "formate": ["arw"]}
    preview = admin.import_rules_overview(db, rules)
    assert preview["active"] is True
    assert preview["counts"] == {"formate": 1, "min_kante": 1, "max_kante": 1}
    assert preview["total"] == 3

    rejected = admin.apply_import_rules(db, rules, thumb_cache=None)
    assert rejected == 3
    left = {r[0] for r in db.execute("SELECT file_hash FROM items")}
    assert left == {"b2" * 32}
    blocked = {r[0] for r in db.execute("SELECT file_hash FROM blocked_hashes")}
    assert blocked == {"a1" * 32, "c3" * 32, "d4" * 32}


def test_import_rules_overview_inactive_without_rules(db):
    _store_sized(db, "a1" * 32, "/mini.png", width=10, height=10)
    preview = admin.import_rules_overview(db, {"min_kante": 0, "max_kante": 0, "formate": []})
    assert preview["active"] is False and preview["total"] == 0
    assert admin.apply_import_rules(db, None, thumb_cache=None) == 0


def test_import_rules_hit_legacy_tiff_raws(db):
    # Alt-Bestand von VOR der RAW-Erkennung: .ARW steht noch als »tiff« im
    # Katalog (Feral Strawberrys Befund 2026-07-17) — der Format-Ausschluss »arw« muss
    # ihn per Dateiendung trotzdem treffen; echte TIFFs bleiben unberührt.
    _store_sized(db, "a1" * 32, "/alt/foto.ARW", width=None, height=None,
                 container="tiff")
    _store_sized(db, "b2" * 32, "/alt/scan.tif", width=800, height=600,
                 container="tiff")
    _store_sized(db, "c3" * 32, "/neu/foto2.arw", width=None, height=None,
                 container="arw")

    rules = {"min_kante": 0, "max_kante": 0, "formate": ["arw"]}
    preview = admin.import_rules_overview(db, rules)
    assert preview["counts"] == {"formate": 2}
    assert admin.apply_import_rules(db, rules, thumb_cache=None) == 2
    left = {r[0] for r in db.execute("SELECT file_hash FROM items")}
    assert left == {"b2" * 32}
