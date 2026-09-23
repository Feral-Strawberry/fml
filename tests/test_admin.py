"""Tests für den Admin-Bereich (Stufe 2A, ADR 0014)."""

from __future__ import annotations

import io
from pathlib import Path

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


# --- Übersicht (ADR 0074 Nachtrag) ---------------------------------------------

def test_overview_stats_kinds_years_growth_and_disks(db, db_path, tmp_path):
    from datetime import datetime, timedelta, timezone

    _store(db, "h1", "/a.png")
    _store(db, "h2", "/b.png")
    _store(db, "h3", "/c.png")
    db.execute("UPDATE items SET media_kind = 'video', file_size = 500 WHERE file_hash = 'h3'")
    db.execute("UPDATE items SET media_date = '2024-05-01 10:00:00' WHERE file_hash = 'h1'")
    db.execute("UPDATE items SET media_date = '2026-01-02 10:00:00' WHERE file_hash = 'h2'")
    old = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.execute("UPDATE items SET first_seen_at = ? WHERE file_hash = 'h3'", (old,))
    db.commit()

    o = admin.overview_stats(db, db_path=db_path, library_root=tmp_path)
    kinds = {k["kind"]: k for k in o["by_kind"]}
    assert kinds["image"]["count"] == 2 and kinds["video"] == {"kind": "video", "count": 1, "bytes": 500}
    years = {y["year"]: y["count"] for y in o["by_year"]}
    assert years == {"2024": 1, "2026": 1, None: 1}          # None = ohne Datum
    assert len(o["growth"]) == 30
    assert sum(g["count"] for g in o["growth"]) == 2          # h3 liegt außerhalb der 30 Tage
    assert o["growth"][-1]["day"] == datetime.now(timezone.utc).date().isoformat()
    assert o["growth"][-1]["count"] == 2
    # DB und Library liegen hier auf demselben Laufwerk → nur EINE Platte
    assert len(o["disks"]) == 1 and o["disks"][0]["for"] == "db"
    assert o["disks"][0]["total"] > 0 and o["disks"][0]["free"] >= 0
    # ohne Library: nur die DB-Platte, keine Ausnahme
    assert len(admin.overview_stats(db, db_path=db_path, library_root=None)["disks"]) == 1


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
    # Teure Zähler sind KEIN Teil des Seitenladens mehr (#118): ohne
    # gemerkten Stand ehrlich „noch nie gezählt", kein Platten-Lauf.
    assert info["orphans"] is None and info["cache"] is None and info["checking"] == []
    assert "thumb_count" not in info and "orphan_locations" not in info
    assert isinstance(info["ffprobe"], bool)
    assert {p["name"] for p in info["parsers"]} >= {"a1111", "comfyui"}

    slow = admin.SlowCounts(db_path, cache)
    slow.count_cache()
    slow.count_orphans(db)
    info = admin.admin_info(db, db_path=db_path, thumb_cache=cache, slow=slow)
    assert info["cache"]["count"] == 1 and info["cache"]["bytes"] == 9
    assert info["orphans"]["count"] == 1          # /a.png existiert nicht
    assert info["orphans"]["at"].endswith("Z") and info["cache"]["at"].endswith("Z")


# --- Gemerkter Stand der teuren Zähler (#118, ADR 0077) ------------------------

def test_slow_counts_remember_set_and_background_refresh(db, db_path, tmp_path):
    _store(db, "h1", "/weg.png")
    db.commit()
    cache = tmp_path / "cache"
    (cache / "ab").mkdir(parents=True)
    (cache / "ab" / "x.jpg").write_bytes(b"12345")
    slow = admin.SlowCounts(db_path, cache)
    assert slow.snapshot() == admin.SlowCounts.EMPTY

    # Direkt setzen (Ergebnis liegt vor: Cache leeren, Aufräumen überall).
    slow.set_cache(0, 0)
    slow.set_orphans(0)
    snap = slow.snapshot()
    assert snap["cache"]["count"] == 0 and snap["orphans"]["count"] == 0 and snap["checking"] == []

    # Hintergrund (nach Aufgaben): eigene Verbindung, checking sichtbar,
    # Doppelwunsch während des Laufs löst genau eine Nachrunde aus.
    slow.refresh_later("orphans", "cache")
    slow.refresh_later("orphans")
    assert slow.wait_idle()
    snap = slow.snapshot()
    assert snap["orphans"]["count"] == 1 and snap["cache"] == {**snap["cache"], "count": 1, "bytes": 5}
    assert snap["checking"] == []
    with pytest.raises(ValueError):
        slow.refresh_later("unsinn")


def test_slow_counts_survive_restart_only_with_matching_stamp(db, db_path, tmp_path):
    """ADR-0077-Nachtrag: gesetzte Stände gehen mit Herkunftsstempel nach
    app_state; ein neuer SlowCounts (Neustart) nimmt sie zurück — außer der
    Stempel passt nicht (anderer Rechner / anderer Cache-Ordner)."""
    cache = tmp_path / "cache"
    cache.mkdir()

    def persist(key, value):
        admin.write_app_state(db, key, value)
        db.commit()

    slow = admin.SlowCounts(db_path, cache, persist=persist)
    slow.set_orphans(4)
    slow.set_cache(7, 900)
    stored = admin.read_app_state(db, "slow.cache")
    assert stored["count"] == 7 and stored["stamp"] == slow.stamp()

    again = admin.SlowCounts(db_path, cache)
    again.load(db)
    snap = again.snapshot()
    assert snap["orphans"]["count"] == 4 and snap["cache"]["bytes"] == 900
    assert "stamp" not in snap["cache"]

    foreign = admin.SlowCounts(db_path, tmp_path / "anderer-cache")
    foreign.load(db)
    assert foreign.snapshot() == admin.SlowCounts.EMPTY

    # Unlesbarer oder fremder Eintrag stört nicht.
    db.execute("UPDATE app_state SET value = 'kaputt' WHERE key = 'slow.orphans'")
    db.commit()
    assert admin.read_app_state(db, "slow.orphans") is None
    again = admin.SlowCounts(db_path, cache)
    again.load(db)
    assert again.snapshot()["orphans"] is None and again.snapshot()["cache"]["count"] == 7


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
    # Item bleibt erhalten — nur die Pfad-Buchhaltung ist weg.
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


def test_import_rules_date_rule_hits_undated_items(db):
    """Datumsregel im Bestandswerkzeug (ADR 0075, #113): Items ohne
    plausibles Datum (media_date NULL nach dem Backfill) zählen mit und
    werden abgelehnt — damit verschwinden sie aus Katalog UND Start-Trigger."""
    _store_sized(db, "a1" * 32, "/ohne-datum.png", width=1024, height=1024)
    _store_sized(db, "b2" * 32, "/datiert.png", width=1024, height=1024)
    db.execute("UPDATE items SET media_date = '2024-01-01 10:00:00' WHERE file_hash = ?",
               ("b2" * 32,))
    db.commit()

    rules = {"min_kante": 0, "max_kante": 0, "formate": [], "min_date": "2015-01-01"}
    preview = admin.import_rules_overview(db, rules)
    assert preview["active"] is True
    assert preview["counts"] == {"datum": 1} and preview["total"] == 1
    assert admin.apply_import_rules(db, rules, thumb_cache=None) == 1
    left = {r[0] for r in db.execute("SELECT file_hash FROM items")}
    assert left == {"b2" * 32}
    assert db.execute("SELECT COUNT(*) FROM blocked_hashes").fetchone()[0] == 1


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


# --- Sperrliste seitenweise + Suche (A3 #107, schließt #66) -----------------------


def _block(db, n, *, path_prefix="/Volumes/Archiv/IMG_"):
    import json

    db.executemany(
        "INSERT INTO blocked_hashes(file_hash, reason, blocked_at, last_paths) VALUES (?, ?, ?, ?)",
        [(f"{i:064x}", json.dumps({"key": "blockedRejected"}), f"2026-09-{1 + i % 28:02d}T10:00:00",
          json.dumps([f"{path_prefix}{i:05d}.jpg"])) for i in range(n)])
    db.commit()


def test_blocked_page_counts_honestly_and_pages(db):
    """Zähler = echter COUNT(*), Seite = offset/limit, neueste zuerst."""
    _block(db, 250)
    page = admin.blocked_page(db, offset=0, limit=100)
    assert page["total"] == page["total_all"] == 250
    assert len(page["blocked"]) == 100
    assert page["blocked"][0]["blocked_at"] >= page["blocked"][-1]["blocked_at"]
    last = admin.blocked_page(db, offset=200, limit=100)
    assert len(last["blocked"]) == 50 and last["offset"] == 200
    assert admin.blocked_page(db, offset=1000, limit=100)["blocked"] == []
    # Kurzform für den Importer bleibt eine Liste.
    assert len(admin.blocked_list(db, limit=5)) == 5


def test_blocked_page_search_over_path_hash_and_reason(db):
    """Suche per LIKE über gemerkte Pfade, Hash und Grund — Platzhalterzeichen
    im Suchtext sind Zeichen, keine Jokerzeichen."""
    _block(db, 30)
    db.execute("INSERT INTO blocked_hashes(file_hash, reason, blocked_at, last_paths) VALUES (?, 'abgelehnt', '2026-09-30', ?)",
               ("ab" * 32, '["/x/50%_off.png"]'))
    db.commit()
    by_path = admin.blocked_page(db, q="IMG_0001")
    assert by_path["total"] == 10 and by_path["total_all"] == 31
    assert all("IMG_0001" in b["last_paths"][0] for b in by_path["blocked"])
    assert admin.blocked_page(db, q="abab")["total"] == 1
    assert admin.blocked_page(db, q="abgelehnt")["total"] == 1
    assert admin.blocked_page(db, q="50%_off")["total"] == 1
    assert admin.blocked_page(db, q="50%")["total"] == 1
    assert admin.blocked_page(db, q="5_%")["total"] == 0, "Unterstrich ist kein Joker"
    assert admin.blocked_page(db, q="gibtsnicht")["blocked"] == []


# --- Wartungskarten (A3 #107) ---------------------------------------------------


def test_maintenance_stats_parsers_undated_and_counts(db, tmp_path):
    from feral.db import store_interpretations
    from feral.interpret.types import InterpretedField, Interpretation

    _store(db, "a1" * 32, tmp_path / "a.png")
    _store(db, "b2" * 32, tmp_path / "b.png")
    for h in ("a1" * 32, "b2" * 32):
        store_interpretations(db, file_hash=h, interpretations=[Interpretation(
            parser="a1111", parser_version=3,
            fields=[InterpretedField(field="prompt", value="x"), InterpretedField(field="seed", value="1")])])
    db.execute("UPDATE items SET media_date = NULL WHERE file_hash = ?", ("a1" * 32,))
    db.execute("UPDATE items SET media_date = '2026-01-01' WHERE file_hash = ?", ("b2" * 32,))
    db.execute("INSERT INTO scan_issues(path, kind, message, first_seen_at, last_seen_at) VALUES ('/x', 'failed', 'm', '2026', '2026')")
    db.commit()
    st = admin.maintenance_stats(db)
    by = {p["parser"]: p for p in st["parsers"]}
    assert by["a1111"]["items"] == 2, "ordinal 0 = ein Treffer je Item, nicht je Feld"
    assert by["a1111"]["version"] is not None
    assert by["comfyui"]["items"] == 0, "registrierte Parser ohne Treffer stehen mit 0 drin"
    assert st["undated"] == 1
    assert st["open_issues"] == 1 and st["blocked_count"] == 0
    assert isinstance(st["dbstat"], bool)
    assert st["dbstat"] == admin.dbstat_available(db)


def test_db_breakdown_groups_by_content(db, tmp_path):
    """dbstat aggregiert: Gruppen decken die Datei ab; ohne dbstat ehrlich
    nicht verfügbar (hier nur der Positivpfad — der Build hat dbstat)."""
    import sqlite3

    _store(db, "a1" * 32, tmp_path / "a.png")
    db.commit()
    try:
        db.execute("SELECT 1 FROM dbstat LIMIT 1")
    except sqlite3.OperationalError:
        pytest.skip("SQLite-Build ohne dbstat")
    d = admin.db_breakdown(db)
    assert d["available"] is True
    keys = [g["key"] for g in d["groups"]]
    assert keys == ["raw", "items", "interpreted", "search", "other"]
    total = sum(g["bytes"] for g in d["groups"])
    assert total > 0 and d["free_bytes"] >= 0 and d["index_bytes"] >= 0
    assert dict((g["key"], g["bytes"]) for g in d["groups"])["items"] > 0


def test_package_versions_compare_installed_with_pins(tmp_path, monkeypatch):
    """Instanz-Kachel (#42, ADR 0080): installierte Version je Laufzeit-Paket
    neben dem Pin; Drift und fehlendes Paket werden ehrlich gemeldet."""
    req = tmp_path / "requirements.txt"
    req.write_text("Pillow==12.3.0\nfastapi==0.141.1  # web\nuvicorn==0.52.4\n", encoding="utf-8")
    installed = {"pillow": "12.3.0", "fastapi": "0.136.3"}

    def fake_version(name):
        try:
            return installed[name.lower()]
        except KeyError:
            raise admin.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(admin.metadata, "version", fake_version)
    rows = admin.package_versions(req, names=("Pillow", "fastapi", "uvicorn"))
    assert rows == [
        {"name": "Pillow", "installed": "12.3.0", "pinned": "12.3.0", "ok": True},
        {"name": "fastapi", "installed": "0.136.3", "pinned": "0.141.1", "ok": False},
        {"name": "uvicorn", "installed": None, "pinned": "0.52.4", "ok": False},
    ]
    # Ohne requirements.txt (fremder Aufruf): installiert = ok, kein Pin.
    assert admin.package_versions(tmp_path / "nope.txt", names=("Pillow",))[0] == {
        "name": "Pillow", "installed": "12.3.0", "pinned": None, "ok": True}


def test_package_versions_real_environment_matches_requirements():
    """Im Entwicklungs-venv müssen alle direkten Laufzeit-Pakete installiert sein
    und dem Pin entsprechen — sonst testet die Suite gegen einen anderen
    Stand, als ausgeliefert wird."""
    root = Path(__file__).resolve().parents[1]
    rows = admin.package_versions(root / "requirements.txt")
    assert [r["name"] for r in rows] == list(admin.RUNTIME_PACKAGES)
    assert all(r["ok"] for r in rows), rows
