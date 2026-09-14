"""Tests für den StaticFiles-Mount der Web-App (Block 3.0, UI-Umbau).

Hinweis: `fastapi.testclient` braucht httpx, das bewusst nicht in den
Abhängigkeiten ist (§0.1). Getestet wird deshalb auf der Ebene, die ohne
HTTP-Client erreichbar ist: Routen-Objekte der App und der Inhalt des
gemounteten Verzeichnisses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from feral.db import connect
from feral.web.app import create_app


@pytest.fixture
def app(tmp_path):
    application = create_app(tmp_path / "t.sqlite")
    yield application
    # create_app startet die ScanEngine (Worker-Thread); ohne laufenden Server
    # feuert lifespan nicht — daher hier von Hand aufräumen.
    application.state.engine.shutdown()
    application.state.thumb_pool.shutdown()


def _static_mount(app):
    for route in app.routes:
        if getattr(route, "name", None) == "static":
            return route
    return None


def test_static_mount_exists(app) -> None:
    """Die App mountet /static als StaticFiles-Route."""
    mount = _static_mount(app)
    assert mount is not None, "kein Mount namens 'static' in app.routes"
    assert mount.path == "/static"


def test_static_mount_serves_main_js(app) -> None:
    """Im gemounteten Verzeichnis liegt js/main.js (Einstiegspunkt der Shell)."""
    mount = _static_mount(app)
    assert mount is not None, "kein Mount namens 'static' in app.routes"
    directory = Path(mount.app.directory)
    assert (directory / "js" / "main.js").is_file()


def test_static_mount_unknown_file_absent(app) -> None:
    """Gegenprobe: eine nicht existierende Datei liegt nicht im Verzeichnis."""
    mount = _static_mount(app)
    assert mount is not None, "kein Mount namens 'static' in app.routes"
    directory = Path(mount.app.directory)
    assert not (directory / "does-not-exist.js").exists()


def test_index_still_serves_no_store(app) -> None:
    """Regressionsschutz: GET / liefert weiterhin index.html ohne Caching."""
    index_route = next(
        route for route in app.routes if getattr(route, "path", None) == "/"
    )
    response = index_route.endpoint()
    assert Path(response.path).name == "index.html"
    assert Path(response.path).is_file()
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"


def test_index_is_new_shell(app) -> None:
    """Seit Block 3.0 Task 12 ist die Startseite die Drei-Spalten-Shell
    (ES-Module-Einstieg statt Inline-Skript der alten Seite)."""
    index_route = next(
        route for route in app.routes if getattr(route, "path", None) == "/"
    )
    html = Path(index_route.endpoint().path).read_text(encoding="utf-8")
    assert '<script type="module" src="/static/js/main.js">' in html
    assert 'id="sidebar"' in html and 'id="panel"' in html and 'id="loupe"' in html


def test_admin_routes_serve_admin_shell(app) -> None:
    """ADR 0074: /admin und /admin/<seite> liefern dasselbe eigene Dokument
    (admin.html) ohne Caching; der Seiten-Slug wird im Browser gelesen."""
    paths = {getattr(r, "path", None): r for r in app.routes}
    assert "/admin" in paths and "/admin/{page}" in paths
    for path in ("/admin", "/admin/{page}"):
        response = paths[path].endpoint(page="logs") if "{" in path else paths[path].endpoint()
        assert Path(response.path).name == "admin.html"
        assert Path(response.path).is_file()
        assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    html = Path(paths["/admin"].endpoint().path).read_text(encoding="utf-8")
    assert '<script type="module" src="/static/js/admin/main.js">' in html
    assert 'id="adnav"' in html and 'id="adpage"' in html


def test_blocked_endpoint_reports_true_total(tmp_path) -> None:
    """#66/#107: der Endpunkt liefert eine Seite (Standard 100) mit echtem
    COUNT(*) als Zähler; Suche und Offset laufen über Query-Parameter."""
    from feral.db import connect

    db = tmp_path / "t.sqlite"
    app = create_app(db)
    try:
        conn = connect(db)
        conn.executemany(
            "INSERT INTO blocked_hashes(file_hash, reason, blocked_at) VALUES (?, 'rejected', '2026-09-12')",
            [(f"{i:064x}",) for i in range(503)])
        conn.commit()
        endpoint = next(r for r in app.routes if getattr(r, "path", None) == "/api/admin/blocked").endpoint
        d = endpoint(q=None, offset=0, limit=100)
        assert d["total"] == d["total_all"] == 503
        assert len(d["blocked"]) == 100
        d = endpoint(q="1f", offset=0, limit=100)
        assert 0 < d["total"] < 503 and d["total_all"] == 503
        assert endpoint(q=None, offset=500, limit=100)["blocked"].__len__() == 3
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


# --- Sammel-Aktion für Multiselect (ADR 0022) ------------------------------------


def test_batch_annotate_endpoint(tmp_path) -> None:
    """Rating + manuelles Modell für mehrere Items in EINEM Writer-Durchlauf."""
    from feral.db import connect, manual, store_extraction
    from feral.extract.types import ContainerExtraction
    from feral.web.app import BatchAnnotateRequest

    db = tmp_path / "t.sqlite"
    app = create_app(db)
    try:
        conn = connect(db)
        hashes = ["aa" * 32, "bb" * 32, "cc" * 32]
        for h in hashes:
            store_extraction(conn, file_hash=h, file_size=1, path=tmp_path / f"{h[:4]}.png",
                             extraction=ContainerExtraction(container="png"))
        endpoint = next(
            route for route in app.routes
            if getattr(route, "path", None) == "/api/batch/annotate"
        ).endpoint

        result = endpoint(BatchAnnotateRequest(
            hashes=hashes, rating=4, model="Midjourney V5"))
        assert result["updated"] == 3
        assert result["manual"]["rating"] == 4
        assert result["manual"]["model"] == "Midjourney V5"
        for h in hashes:
            a = manual.annotations_for(conn, h)
            assert a["rating"] == 4 and a["model"] == "Midjourney V5"
        conn.close()
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


# --- /api/workflow: A1111-Graph wird erzeugt (Block N, ADR 0044) -----------------


def test_workflow_endpoint_generates_a1111_graph(tmp_path) -> None:
    """Ohne eingebetteten Workflow, aber mit a1111-Feldern: erzeugter Graph;
    ohne beides ehrliche 404."""
    import json

    from fastapi import HTTPException
    from feral.db import connect, store_extraction, store_interpretations
    from feral.extract.types import ContainerExtraction
    from feral.interpret import Interpretation, InterpretedField

    db = tmp_path / "t.sqlite"
    app = create_app(db)
    try:
        conn = connect(db)
        store_extraction(conn, file_hash="aa" * 32, file_size=1,
                         path=tmp_path / "a.png",
                         extraction=ContainerExtraction(container="png"))
        store_interpretations(conn, file_hash="aa" * 32, interpretations=[
            Interpretation(parser="a1111", parser_version=3, fields=[
                InterpretedField("tool", "a1111"),
                InterpretedField("prompt", "ein wald"),
                InterpretedField("model", "sdxl_base"),
                InterpretedField("sampler", "Euler a"),
            ]),
        ])
        store_extraction(conn, file_hash="bb" * 32, file_size=1,
                         path=tmp_path / "b.png",
                         extraction=ContainerExtraction(container="png"))
        conn.close()

        endpoint = next(
            route for route in app.routes
            if getattr(route, "path", None) == "/api/workflow/{file_hash}"
        ).endpoint

        graph = json.loads(endpoint("aa" * 32).body)
        assert graph["extra"]["fml"]["generated_from"] == "a1111"
        assert any(n["type"] == "KSampler" for n in graph["nodes"])

        with pytest.raises(HTTPException) as exc:
            endpoint("bb" * 32)
        assert exc.value.status_code == 404
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


# --- /api/thumb blockiert nie mehr (Block 4S, ADR 0020) --------------------------


def _thumb_endpoint(app):
    return next(
        route for route in app.routes
        if getattr(route, "path", None) == "/api/thumb/{file_hash}"
    ).endpoint


def test_thumb_endpoint_202_then_200(tmp_path) -> None:
    """Fehlendes Thumbnail: sofort 202 (Pool generiert), danach 200 mit JPEG —
    der Handler hält nie eine Browser-Verbindung für die Generierung fest."""
    import time

    from fastapi import HTTPException
    from PIL import Image

    from feral.db import connect, store_extraction
    from feral.extract import png as png_extract

    db = tmp_path / "t.sqlite"
    app = create_app(db, thumb_cache=tmp_path / "cache")
    try:
        src = tmp_path / "bild.png"
        Image.new("RGB", (32, 32), (10, 200, 90)).save(src, "PNG")
        conn = connect(db)
        store_extraction(conn, file_hash="ab" * 32, file_size=src.stat().st_size,
                         path=src, extraction=png_extract.extract(src))
        conn.close()
        endpoint = _thumb_endpoint(app)

        first = endpoint("ab" * 32)
        assert first.status_code == 202
        assert first.headers["cache-control"] == "no-store"

        # Der Pool generiert im Hintergrund — auf das fertige JPEG warten.
        deadline = time.monotonic() + 60
        while True:
            response = endpoint("ab" * 32)
            if response.status_code == 200:
                assert Path(response.path).is_file()
                break
            assert response.status_code == 202
            assert time.monotonic() < deadline, "Thumbnail wurde nie fertig"
            time.sleep(0.1)

        # Unbekannter Hash: ehrliche 404, nichts wird eingereiht.
        with pytest.raises(HTTPException) as exc:
            endpoint("ff" * 32)
        assert exc.value.status_code == 404
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


# --- Watch-Liste speichern (ADR 0029/0030, Inline-Verwaltung im Dashboard) --------


def test_watch_save_endpoint_writes_config_and_returns_list(tmp_path) -> None:
    """POST /api/watch/save schreibt [[watch]] in die config.toml und liefert
    die neue Liste (inkl. quiet_seconds für den GUI-Round-Trip) zurück."""
    from fastapi import HTTPException

    from feral.config import load_config, watch_sources
    from feral.web.app import WatchSaveRequest, WatchSourceModel

    cfg = tmp_path / "config.toml"
    # as_posix(): Backslash ist in TOML-Basic-Strings ein Escape — ein roher
    # Windows-Pfad wäre ungültiges TOML (Issue #50).
    cfg.write_text('[library]\nroot = "%s"\n' % (tmp_path / "lib").as_posix(), encoding="utf-8")
    quelle = tmp_path / "quelle"
    quelle.mkdir()
    app = create_app(tmp_path / "t.sqlite", config_path=cfg)
    try:
        endpoint = next(
            route for route in app.routes
            if getattr(route, "path", None) == "/api/watch/save"
        ).endpoint

        result = endpoint(WatchSaveRequest(sources=[
            WatchSourceModel(name="Quelle", path=str(quelle), modus="verschieben",
                             quiet_seconds=12),
        ]))
        # Antwort = Liste mit Live-Zustand + round-trip-fähigen Feldern.
        assert result["sources"][0]["modus"] == "verschieben"
        assert result["sources"][0]["quiet_seconds"] == 12.0
        # Persistiert in der Datei (ADR 0030).
        saved = watch_sources(load_config(cfg))
        assert [s["path"] for s in saved] == [str(quelle)]
        assert saved[0]["modus"] == "verschieben"

        # Leere Liste räumt die Sektion wieder weg.
        assert endpoint(WatchSaveRequest(sources=[]))["sources"] == []
        assert "watch" not in load_config(cfg)

        # Ungültiger Modus → ehrliche 400, Datei bleibt unangetastet.
        with pytest.raises(HTTPException) as exc:
            endpoint(WatchSaveRequest(sources=[
                WatchSourceModel(path=str(quelle), modus="anheften"),
            ]))
        assert exc.value.status_code == 400
        assert "watch" not in load_config(cfg)
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


# --- Workflow-Renderer: Koordinaten aus fremdem JSON sind numerisch (ADR 0032) ---


def test_workflow_coords_are_coerced_to_numbers(app) -> None:
    """Regressionsschutz gegen DOM-XSS: der Workflow-Graph stammt aus einem
    eingebetteten (fremden) ComfyUI-Chunk. Der einzige Geometrie-Zugriff `_n`
    muss Koordinaten zu einer ENDLICHEN ZAHL normalisieren — ein String-Wert
    würde sonst ungefiltert in ein SVG-Attribut interpoliert und könnte aus dem
    Markup ausbrechen. Kein JS-Runtime im Projekt (§0.1) → statische Zusicherung."""
    mount = _static_mount(app)
    assert mount is not None
    src = (Path(mount.app.directory) / "js" / "workflow.js").read_text(encoding="utf-8")
    assert "Number.isFinite" in src, "_n() normalisiert Koordinaten nicht mehr numerisch"
    assert "v[i] || 0" not in src, "unsichere Kurzform in _n() ist zurückgekehrt"


# --- Übersichtsmodus sperrt dateischreibende Wege (ADR 0041, I4) ---------------

def test_uebersichtsmodus_locks_file_writing_paths(tmp_path) -> None:
    """Ohne Library-Verwaltung: kopieren/verschieben-Import und Rausverschieben
    liefern eine ehrliche 403; katalogisieren bleibt frei. Der Schalter wirkt
    ohne Neustart (Config wird je Aufruf gelesen)."""
    from fastapi import HTTPException

    from feral.web.app import ImportRequest, MoveoutRequest

    cfg = tmp_path / "config.toml"
    lib = tmp_path / "lib"
    lib.mkdir()
    quelle = tmp_path / "quelle"
    quelle.mkdir()
    # root gesetzt, aber Schalter explizit aus — Übersichtsmodus gewinnt.
    cfg.write_text(
        f'[library]\nroot = "{lib.as_posix()}"\nverwaltung = false\n', encoding="utf-8"
    )
    app = create_app(tmp_path / "t.sqlite", config_path=cfg)
    try:
        ep = {r.path: r.endpoint for r in app.routes if hasattr(r, "endpoint")}

        with pytest.raises(HTTPException) as exc:
            ep["/api/import"](ImportRequest(path=str(quelle), modus="kopieren"))
        assert exc.value.status_code == 403
        assert exc.value.detail == {"key": "errOverviewMode"}

        with pytest.raises(HTTPException) as exc:
            ep["/api/admin/moveout"](MoveoutRequest(target=str(tmp_path / "raus")))
        assert exc.value.status_code == 403

        # katalogisieren ist reine DB-Arbeit — bleibt erlaubt.
        result = ep["/api/import"](ImportRequest(path=str(quelle), modus="katalogisieren"))
        assert result["target"] == str(quelle)

        # Flags für Badge (Stats) und Admin-Dialoge.
        assert ep["/api/stats"](_req())["verwaltung"] is False
        moveout_get = next(
            r.endpoint for r in app.routes
            if getattr(r, "path", None) == "/api/admin/moveout"
            and "GET" in getattr(r, "methods", set())
        )
        assert moveout_get()["locked"] is True

        # Schalter umlegen wirkt sofort — kein Neustart nötig.
        cfg.write_text(
            f'[library]\nroot = "{lib.as_posix()}"\nverwaltung = true\n', encoding="utf-8"
        )
        assert ep["/api/stats"](_req())["verwaltung"] is True
        # Als Pfad vergleichen: die Config trägt den Ordner in POSIX-Schreibweise,
        # unter Windows käme er mit Schrägstrichen zurück (Issue #50).
        assert Path(ep["/api/import"](ImportRequest(path=str(quelle), modus="kopieren"))[
            "target"
        ]) == lib
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()
        # create_app setzt den Modul-globalen fundort:-Provider (ADR 0041, I2)
        # auf DIESE Config — für Folgetests auf den Standard zurück.
        from feral.web import filters

        filters.library_root_provider = lambda: None


# --- Instanz-Komfort: Name/Farbe in Stats, Config-Validierung (ADR 0041, I5) ---

def test_instanz_in_stats_and_config_roundtrip(tmp_path) -> None:
    """/api/stats trägt Name + Akzentfarbe (je Aufruf frisch aus der Config);
    /api/admin/config validiert Port und Farbe und schreibt [web] zurück."""
    from fastapi import HTTPException

    from feral.web.app import ConfigUpdate

    cfg = tmp_path / "config.toml"
    cfg.write_text('[web]\nname = "Archiv"\nakzentfarbe = "#3b82f6"\n', encoding="utf-8")
    app = create_app(tmp_path / "t.sqlite", config_path=cfg)
    try:
        ep = {r.path: r.endpoint for r in app.routes if hasattr(r, "endpoint")}

        inst = ep["/api/stats"](_req())["instanz"]
        assert inst == {"name": "Archiv", "farbe": "#3b82f6"}

        # Ungültige Eingaben: ehrliche 400 statt kaputter Config.
        with pytest.raises(HTTPException) as exc:
            ep["/api/admin/config"](ConfigUpdate(thumbnail_size=320, web_port=70000))
        assert exc.value.status_code == 400
        with pytest.raises(HTTPException) as exc:
            ep["/api/admin/config"](ConfigUpdate(thumbnail_size=320, akzentfarbe="rot"))
        assert exc.value.status_code == 400

        # Speichern wirkt sofort: Stats liest die Config je Aufruf frisch.
        ep["/api/admin/config"](ConfigUpdate(
            thumbnail_size=320, web_port=9001, instanz_name="Kuration", akzentfarbe="",
        ))
        inst = ep["/api/stats"](_req())["instanz"]
        assert inst == {"name": "Kuration", "farbe": None}

        from feral.config import load_config, slow_request_ms, web_port
        assert web_port(load_config(cfg)) == 9001

        # Langsam-Schwelle (#110): GET liefert sie, POST validiert, schreibt
        # [performance] und setzt sie SOFORT im App-Zustand (Middleware liest dort).
        assert _get_ep(app, "/api/admin/config")()["slow_request_ms"] == 250
        assert app.state.slow_request_ms == 250.0
        with pytest.raises(HTTPException) as exc:
            ep["/api/admin/config"](ConfigUpdate(thumbnail_size=320, slow_request_ms=-1))
        assert exc.value.status_code == 400
        ep["/api/admin/config"](ConfigUpdate(thumbnail_size=320, slow_request_ms=1500))
        assert app.state.slow_request_ms == 1500.0
        assert slow_request_ms(load_config(cfg)) == 1500.0
        assert _get_ep(app, "/api/admin/config")()["slow_request_ms"] == 1500
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()
        from feral.web import filters

        filters.library_root_provider = lambda: None


def _get_ep(app, path):
    """GET-Endpunkt zu einem Pfad, den auch ein POST teilt (/api/folders)."""
    return next(r.endpoint for r in app.routes
                if getattr(r, "path", None) == path and "GET" in getattr(r, "methods", set()))


def _req():
    """Request-Attrappe für Endpunkte, die den ASGI-Scope nur für die
    Kalt-Markierung des Epochen-Caches brauchen (ADR 0071)."""
    from types import SimpleNamespace
    return SimpleNamespace(scope={})


# --- Smart-Folder-/Arena-Zähler aus dem Epochen-Cache, Liste vor Zahlen (#69) ---

def test_folders_and_rankings_counts_cached_and_optional(tmp_path) -> None:
    from feral.db import folders as folders_db
    from feral.db import rankings as rankings_db
    from feral.web.cache import COLD_KEY

    db_path = tmp_path / "t.sqlite"
    app = create_app(db_path)
    try:
        ep = {r.path: r.endpoint for r in app.routes if hasattr(r, "endpoint")}
        ep["/api/folders"] = _get_ep(app, "/api/folders")
        ep["/api/rankings"] = _get_ep(app, "/api/rankings")
        conn = connect(db_path)
        with conn:
            folders_db.create(conn, "PNGs", "container: png")
            folders_db.create(conn, "Kaputt", "container: png")
            conn.execute("UPDATE smart_folders SET expression = 'unbekannt:: (' WHERE name = 'Kaputt'")
            rankings_db.create(conn, "Alle", "")
        conn.close()

        # Liste vor Zahlen: ohne Zähler kommt kein count-Schlüssel.
        bare = ep["/api/folders"](_req(), counts=False)["folders"]
        assert [f["name"] for f in bare] == ["Kaputt", "PNGs"]   # Liste sortiert nach Name
        assert all("count" not in f and "error" not in f for f in bare)

        # Mit Zählern: erste Anfrage rechnet (kalt, Grund "start"), die
        # zweite kommt aus dem Cache (keine Markierung).
        req = _req()
        full = ep["/api/folders"](req, counts=True)["folders"]
        assert (full[1]["count"], full[1]["error"]) == (0, None)
        assert full[0]["count"] is None and full[0]["error"]["key"]
        assert req.scope[COLD_KEY] == "start"
        req = _req()
        assert ep["/api/folders"](req, counts=True)["folders"] == full
        assert COLD_KEY not in req.scope

        # Arenen: leerer Ausdruck = ganze Bibliothek, gleicher Zähl-Pfad.
        bare = ep["/api/rankings"](_req(), counts=False)["rankings"]
        assert "population" not in bare[0]
        full = ep["/api/rankings"](_req(), counts=True)["rankings"]
        assert (full[0]["population"], full[0]["error"]) == (0, None)

        # Facetten/Bewertungen: ungefiltert gecacht (Boot-Schwung), gefiltert
        # je Ausdruck gerechnet — keine Markierung.
        for path, kwargs in (("/api/facets", {}), ("/api/ratings", {})):
            req = _req()
            cold = ep[path](req, filter=None)
            assert req.scope[COLD_KEY] == "start"
            req = _req()
            assert ep[path](req, filter=None) == cold
            assert COLD_KEY not in req.scope
            req = _req()
            ep[path](req, filter="container: png")
            assert COLD_KEY not in req.scope

        # Stats: EIN gecachtes Ergebnis, Zusatzfelder je Aufruf frisch.
        req = _req()
        first = ep["/api/stats"](req)
        assert req.scope[COLD_KEY] == "start" and first["total_items"] == 0
        req = _req()
        assert ep["/api/stats"](req)["total_items"] == 0
        assert COLD_KEY not in req.scope
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


# --- Sidebar-Zähler: EIN Endpunkt, je Suchzustand gecacht (#99, ADR 0073) ---------

def test_sidebar_endpoint_cached_per_filter_and_cold_marked(tmp_path) -> None:
    from feral.web.cache import COLD_KEY
    from fastapi import HTTPException

    db_path = tmp_path / "t.sqlite"
    app = create_app(db_path)
    try:
        ep = {r.path: r.endpoint for r in app.routes if hasattr(r, "endpoint")}
        sidebar = _get_ep(app, "/api/sidebar")

        # Ungefiltert: aus den bestehenden Caches zusammengesetzt (Boot-Schwung).
        req = _req()
        plain = sidebar(req, filter=None)
        assert set(plain) == {"models", "facets", "ratings"}
        assert req.scope[COLD_KEY] == "start"
        assert plain["facets"]["show_dupes"] is True
        assert plain["ratings"] == ep["/api/ratings"](_req(), filter=None)
        req = _req()
        assert sidebar(req, filter=None) == plain and COLD_KEY not in req.scope

        # Gefiltert: erste Anfrage rechnet (kalt), die zweite mit demselben
        # Ausdruck ist ein Speichergriff; Inhalt = die drei Einzelendpunkte.
        req = _req()
        first = sidebar(req, filter="container: png")
        assert req.scope[COLD_KEY] == "start"
        assert first["models"] == ep["/api/models"](_req(), filter="container: png")
        assert first["facets"] == ep["/api/facets"](_req(), filter="container: png")
        assert first["ratings"] == ep["/api/ratings"](_req(), filter="container: png")
        req = _req()
        assert sidebar(req, filter="container: png") == first
        assert COLD_KEY not in req.scope
        # Nur die Sortier-Direktive = kein Filter: derselbe Weg wie ungefiltert.
        req = _req()
        assert sidebar(req, filter="sort: name") == plain and COLD_KEY not in req.scope

        # Ein Schreibvorgang irgendeiner Verbindung entwertet den Eintrag.
        conn = connect(db_path)
        with conn:
            conn.execute("INSERT INTO tags (name, created_at) VALUES ('neu', '2026-01-01T00:00:00Z')")
        conn.close()
        req = _req()
        again = sidebar(req, filter="container: png")
        assert req.scope[COLD_KEY] == "write"
        assert again["facets"] == ep["/api/facets"](_req(), filter="container: png")

        with pytest.raises(HTTPException) as exc:
            sidebar(_req(), filter="unbekannt:: (")
        assert exc.value.status_code == 400
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


def test_orphans_endpoint_counts_scope_and_samples(tmp_path) -> None:
    """A3 #107: Vorschau der Aufräum-Karte — ehrliche Zahl im Bereich (ADR 0033)
    plus gedeckelte Beispielpfade; ``under`` schränkt auf einen Ordner ein."""
    from feral.db import connect, store_extraction
    from feral.extract.types import ContainerExtraction

    db = tmp_path / "t.sqlite"
    app = create_app(db)
    try:
        conn = connect(db)
        existing = tmp_path / "da.png"
        existing.write_bytes(b"x")
        store_extraction(conn, file_hash="aa" * 32, file_size=1, path=existing,
                         extraction=ContainerExtraction(container="png"))
        for i, p in enumerate(("/weg/a.png", "/weg/b.png", "/anderswo/c.png")):
            store_extraction(conn, file_hash=f"{i + 1:02d}" * 32, file_size=1, path=p,
                             extraction=ContainerExtraction(container="png"))
        conn.commit()
        endpoint = next(r for r in app.routes if getattr(r, "path", None) == "/api/admin/orphans").endpoint
        d = endpoint(under=None, sample=2)
        assert d["total"] == 3 and len(d["sample"]) == 2 and d["under"] is None
        d = endpoint(under="/weg", sample=20)
        assert d["total"] == 2 and sorted(d["sample"]) == ["/weg/a.png", "/weg/b.png"]
        assert d["under"] == "/weg"
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()


def test_slow_counts_endpoints_remember_stand(tmp_path) -> None:
    """#118 (ADR 0077): /api/admin/info zählt nichts mehr auf der Platte;
    „Fundorte prüfen" (überall) und „Cache zählen" setzen den gemerkten
    Stand, Cache leeren setzt ihn auf 0, Aufräumen im Teilbereich zählt im
    Hintergrund nach."""
    from feral.db import connect, store_extraction
    from feral.extract.types import ContainerExtraction
    from feral.web.app import PruneRequest

    db = tmp_path / "t.sqlite"
    cache = tmp_path / "cache"
    (cache / "ab").mkdir(parents=True)
    (cache / "ab" / "x.jpg").write_bytes(b"jpegdaten")
    app = create_app(db, thumb_cache=cache)
    try:
        conn = connect(db)
        for i, p in enumerate(("/weg/a.png", "/weg/b.png", "/anderswo/c.png")):
            store_extraction(conn, file_hash=f"{i + 1:02d}" * 32, file_size=1, path=p,
                             extraction=ContainerExtraction(container="png"))
        conn.commit()
        conn.close()
        info = _get_ep(app, "/api/admin/info")
        assert info()["orphans"] is None and info()["cache"] is None

        orphans = _get_ep(app, "/api/admin/orphans")
        orphans(under="/weg", sample=5)                      # Teilbereich: kein Stand
        assert info()["orphans"] is None
        orphans(under=None, sample=5)                        # überall: Stand gemerkt
        assert info()["orphans"]["count"] == 3

        assert _get_ep(app, "/api/admin/thumbcache")()["count"] == 1
        assert info()["cache"]["bytes"] == 9
        clear = next(r.endpoint for r in app.routes
                     if getattr(r, "path", None) == "/api/admin/thumbcache/clear")
        assert clear()["deleted"] == 1
        assert info()["cache"] == {**info()["cache"], "count": 0, "bytes": 0}

        prune = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/api/admin/prune")
        assert prune(PruneRequest(under="/weg"))["pruned"] == 2
        assert app.state.slow_counts.wait_idle()
        assert info()["orphans"]["count"] == 1 and info()["checking"] == []
        assert prune(None)["pruned"] == 1
        assert info()["orphans"]["count"] == 0
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()

    # Neustart (ADR-0077-Nachtrag): der Stand kommt aus app_state zurück.
    app = create_app(db, thumb_cache=cache)
    try:
        info = _get_ep(app, "/api/admin/info")()
        assert info["orphans"]["count"] == 0 and info["cache"]["count"] == 0
        assert "stamp" not in info["cache"]
    finally:
        app.state.engine.shutdown()
        app.state.thumb_pool.shutdown()
