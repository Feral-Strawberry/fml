"""FastAPI-App: dünne HTTP-Hülle um Engine und Datenfunktionen.

Schreibende Aktionen (Scan, Watch) gehen an die `ScanEngine` (ein Worker-Thread,
ADR 0007). Lesende Endpunkte öffnen je Anfrage eine kurzlebige DB-Verbindung.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from typing import Any
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..messages import error_payload as _err, load as msg_load, msg
from ..config import (
    watch_sources as cfg_watch_sources,
    import_min_date as cfg_import_min_date,
    import_rules as cfg_import_rules,
    model_sort as cfg_model_sort,
    thumbnail_low_priority as cfg_thumb_low_priority,
    thumbnail_workers as cfg_thumb_workers,
    ui_show_dupes as cfg_show_dupes,
    library_root as cfg_library_root,
    library_verwaltung as cfg_library_verwaltung,
    instance_accent as cfg_instance_accent,
    instance_name as cfg_instance_name,
    rankings_enabled as cfg_rankings_enabled,
    web_port as cfg_web_port,
    load_config,
    thumbnail_size,
    update_config_file,
)
from ..db import connect, folders as folders_db, manual
from ..db import rankings as rankings_db
from ..interpret import a1111_graph
from .. import reveal
from ..thumbs import DEFAULT_SIZE, ThumbPool, fail_reason, render_preview, thumb_path
from . import admin as admin_lib
from . import bulk as bulk_lib
from . import filters, library
from .cache import EpochCache
from . import rankings as rankings_lib
from .engine import ScanEngine

_STATIC = Path(__file__).parent / "static"

# Item-IDs sind SHA-256-Hexstrings — alles andere ist keine gültige Anfrage.
_HASH = re.compile(r"^[0-9a-f]{64}$")


class ScanRequest(BaseModel):
    path: str


class ImportRequest(BaseModel):
    """Einmal-Import eines Ordners; ``modus`` wie bei Watchordnern (ADR 0030):
    ``verschieben`` leert die Quelle nach erfolgreichem Import (ADR 0025)."""

    path: str
    modus: str = "kopieren"                     # "kopieren" | "verschieben"
    leere_ordner_entfernen: bool = False        # ADR 0033, nur bei verschieben


class WatchRef(BaseModel):
    """Verweis auf eine Watch-Quelle (Start/Stopp) über ihren Pfad."""

    path: str


class MoveoutRequest(BaseModel):
    """Rausverschiebe-Dialog (I3, ADR 0041): Zielordner des Pauschalwegs
    („alle Abgelehnten aus der Library rausverschieben")."""

    target: str


class PruneRequest(BaseModel):
    """Verwaiste Fundorte aufräumen (ADR 0033): ``under`` beschränkt auf
    Pfade unterhalb eines Ordners — None räumt überall (Vorsicht bei
    ausgehängten Platten: „weg“ und „gerade offline“ sehen gleich aus)."""

    under: str | None = None


class WatchSourceModel(BaseModel):
    """Eine überwachte Quelle (ADR 0030) aus der GUI."""

    name: str = ""
    path: str
    modus: str = "kopieren"                     # "kopieren" | "verschieben"
    quiet_seconds: float | None = None
    poll_seconds: float | None = None
    leere_ordner_entfernen: bool = False        # ADR 0033, nur bei verschieben


class WatchSaveRequest(BaseModel):
    """Komplette Watch-Liste aus der Inline-Verwaltung im Dashboard."""

    sources: list[WatchSourceModel]


class LocationModel(BaseModel):
    name: str
    path: str


class ConfigUpdate(BaseModel):
    # locations (Browser-Lesezeichen) sind seit dem Watchordner-Block (Feral Strawberry,
    # 2026-07-09) kein GUI-Konzept mehr; None = [[scan.locations]] unangetastet.
    locations: list[LocationModel] | None = None
    thumbnail_size: int
    library_root: str | None = None
    verwaltung: bool | None = None              # Library-Verwaltung (ADR 0041, I4)
    import_min_date: str | None = None
    # Import-Regeln (ADR 0046): 0 = Regel aus; None = unangetastet.
    import_min_kante: int | None = None
    import_max_kante: int | None = None
    import_formate_ausschliessen: list[str] | None = None
    watch: list[WatchSourceModel] | None = None
    thumbnail_low_priority: bool | None = None
    thumbnail_workers: int | None = None       # 0 = Automatik
    show_dupes: bool | None = None
    model_sort_order: str | None = None
    # Instanz-Komfort (ADR 0041, I5): 0/leer = Eintrag entfernen (Standard).
    web_port: int | None = None
    instanz_name: str | None = None
    akzentfarbe: str | None = None
    # Ranking-Modul (ADR 0045): None = Eintrag unangetastet lassen.
    rankings_enabled: bool | None = None


class RatingUpdate(BaseModel):
    rating: int | None = None  # 0/None löscht, 1–5 setzt (ADR 0017)


class NotesUpdate(BaseModel):
    notes: str | None = None


class TagRequest(BaseModel):
    name: str


class FolderRequest(BaseModel):
    name: str
    expression: str


class RankingRequest(BaseModel):
    """Arena des Ranking-Moduls (ADR 0045): Name + Population als
    Filterausdruck; leer = ganze Bibliothek."""
    name: str
    expression: str = ""


class DuelRequest(BaseModel):
    """Duell-Wertung (ADR 0045): outcome 'sieg' (winner schlägt loser) oder
    'beide_verloren' (Ergänzung 2026-07-13; Reihenfolge der Hashes egal)."""
    winner: str
    loser: str
    outcome: str = "sieg"


class FilterBuildRequest(BaseModel):
    """Chip-Zustand der Suche (Block S3, ADR 0035): Prädikat-Dicts, wie sie
    /api/filter/parse liefert — Validierung läuft über serialize()+parse()."""
    predicates: list[dict]


class BatchAnnotateRequest(BaseModel):
    """Sammel-Aktion für die Multiselect-Auswahl (ADR 0022).

    Nur gesendete Aktionen werden ausgeführt: ``rating`` (0 löscht),
    ``add_tag`` (hängt an), ``model`` ("" löscht das manuelle Modell).
    """

    hashes: list[str]
    rating: int | None = None
    add_tag: str | None = None
    model: str | None = None


class BulkApplyRequest(BaseModel):
    """Sammel-Aktion auf das ganze Suchergebnis (Großbaustelle K, ADR 0040).

    ``hashes`` (Multiselect-Scope) gewinnt über ``filter`` (Suchzustand;
    leer = alle Items). Semantik: ``rating`` füllt nur Unbewertete (1–5),
    ``add_tag`` hängt an, ``note`` hängt an, ``model`` setzt. ``reject``
    (ADR 0041, ersetzt Löschen) läuft allein: Item raus + Hash gesperrt,
    die Datei bleibt unangetastet.
    """

    filter: str = ""
    hashes: list[str] | None = None
    rating: int | None = None
    add_tag: str | None = None
    model: str | None = None
    note: str | None = None
    reject: bool = False


# -- Host-Wächter (ADR 0058) ---------------------------------------------------
#
# fml bindet standardmäßig nur an 127.0.0.1 — aber DNS-Rebinding hebelt das
# im Browser aus: Eine bösartige Webseite biegt ihre Domain per DNS auf
# 127.0.0.1 um, und schon gelten ihre Requests als same-origin gegen die
# fml-API. Die Abwehr ist der Host-Header: Er trägt weiterhin den fremden
# Domainnamen. Requests, deren Host nicht zur erlaubten Liste passt, enden
# als 400. Bewusst Eigenbau statt Starlettes TrustedHostMiddleware: die
# zerlegt IPv6-Literale („[::1]:8765") falsch, und wir wollen in derselben
# Middleware `X-Content-Type-Options: nosniff` auf alle Antworten setzen.
# Der 400-Text bleibt roh englisch — ihn sehen nur Angreifer/Fehlkonfigs,
# nie die UI (deshalb auch kein Meldungs-Schlüssel nach ADR 0054).

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _host_only(header: str) -> str:
    """Hostname aus einem Host-Header, Port abgetrennt, IPv6-tauglich."""
    value = header.strip().lower()
    if value.startswith("["):                # IPv6-Literal: [::1]:8765
        return value.partition("]")[0].lstrip("[")
    return value.rsplit(":", 1)[0] if ":" in value else value


class _HostGuard:
    """Reine ASGI-Middleware: Host-Allowlist + nosniff-Header."""

    def __init__(self, app: Any, allowed_hosts: list[str] | None = None) -> None:
        self.app = app
        hosts = _LOOPBACK_HOSTS if allowed_hosts is None else {h.lower() for h in allowed_hosts}
        self.allowed: frozenset[str] | None = None if "*" in hosts else frozenset(hosts)

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_nosniff(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", [])]
                if not any(k.lower() == b"x-content-type-options" for k, _ in headers):
                    headers.append((b"x-content-type-options", b"nosniff"))
                message = {**message, "headers": headers}
            await send(message)

        if self.allowed is not None:
            raw = next((v for k, v in scope.get("headers", []) if k == b"host"), b"")
            if _host_only(raw.decode("latin-1")) not in self.allowed:
                reject = PlainTextResponse("Invalid host header", status_code=400)
                return await reject(scope, receive, send_with_nosniff)
        await self.app(scope, receive, send_with_nosniff)


def create_app(
    db_path: str | Path,
    *,
    thumb_cache: str | Path | None = None,
    thumb_size: int = DEFAULT_SIZE,
    thumb_workers: int | None = None,
    thumb_low_priority: bool = True,
    config_path: str | Path | None = None,
    import_target: str | Path | None = None,
    import_min_date: str = "2015-01-01",
    allowed_hosts: list[str] | None = None,
) -> FastAPI:
    db_path = str(db_path)
    engine = ScanEngine(db_path)
    thumb_cache = Path(thumb_cache) if thumb_cache else Path(db_path).resolve().parent / "cache" / "thumbnails"
    # Ein Prozess-Pool für ALLE Thumbnail-Generierung (ADR 0020) — On-Demand
    # aus /api/thumb und der Warmer teilen ihn sich; entsteht lazy.
    thumb_pool = ThumbPool(workers=thumb_workers, low_priority=thumb_low_priority)

    def configured_import() -> tuple[str | None, str]:
        # Bestands-Wurzel + min_date je Anfrage frisch (wie die Scan-Orte) —
        # GUI-Änderungen am Import-Ziel wirken sofort, ohne Neustart.
        if config_path is not None:
            cfg = load_config(config_path)
            return cfg_library_root(cfg), cfg_import_min_date(cfg)
        return (str(import_target) if import_target else None), import_min_date

    def configured_rules() -> dict[str, Any] | None:
        # Import-Regeln (ADR 0046) je Aufruf frisch — Config-Änderungen wirken
        # auf den nächsten Import/Scan/Watch-Batch, ohne Neustart.
        if config_path is not None:
            return cfg_import_rules(load_config(config_path))
        return None

    # Übersichtsmodus vs. Library-Verwaltung (ADR 0041, I4): Ab Werk sind ALLE
    # dateischreibenden Wege gesperrt (kopieren/verschieben-Import, Watch-
    # Quellen mit diesen Modi, Rausverschieben) — katalogisieren, Ablehnen und
    # Kuratieren bleiben frei. Je Aufruf frisch aus der Config gelesen, damit
    # der Schalter sofort wirkt. Ohne Config-Datei gilt ein explizit
    # übergebenes import_target als bewusste Einrichtung (Migrations-Regel).
    def verwaltung_enabled() -> bool:
        if config_path is not None:
            return cfg_library_verwaltung(load_config(config_path))
        return import_target is not None

    def _require_verwaltung() -> None:
        if not verwaltung_enabled():
            raise HTTPException(status_code=403, detail=msg("errOverviewMode"))

    # fundort:-Prädikat + Library/Extern-Zahlen (ADR 0041, I2): filters darf
    # config nicht importieren — die Root kommt über diesen Provider, je
    # Aufruf frisch aus der Config (Modul-Zustand: die zuletzt erzeugte App
    # gewinnt — pro Prozess läuft genau eine, ADR 0001).
    filters.library_root_provider = lambda: configured_import()[0]

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Windows/Proactor meldet abgerissene Browser-Verbindungen als lauten
        # ConnectionResetError-Traceback (WinError 10054) — passiert bei jedem
        # gekappten Keep-Alive und ist für uns bedeutungslos (Feral Strawberrys Konsole
        # war voll damit). Nur DIESEN Fall stumm schalten, alles andere geht
        # unverändert an den bisherigen Handler.
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()

        def quiet_connection_reset(loop, context):
            if isinstance(context.get("exception"), ConnectionResetError):
                return
            if previous is not None:
                previous(loop, context)
            else:
                loop.default_exception_handler(context)

        loop.set_exception_handler(quiet_connection_reset)
        yield
        engine.shutdown()  # Watcher + Worker-Thread sauber beenden
        thumb_pool.shutdown()
        hits_cache.close()
        models_cache.close()

    app = FastAPI(title="Feral Media Library", lifespan=lifespan)
    # Host-Allowlist + nosniff (ADR 0058). Standard: nur Loopback-Namen;
    # wer per --host bewusst weiter bindet (z. B. Tailscale), bekommt vom
    # Startskript allowed_hosts=["*"] durchgereicht.
    app.add_middleware(_HostGuard, allowed_hosts=allowed_hosts)

    @app.exception_handler(TimeoutError)
    async def engine_busy(_request, _exc):
        # Kurze Schreibgriffe warten auf den EINEN Writer (ADR 0007). Läuft
        # dort gerade ein Langläufer (Import, VACUUM, …), gibt es eine
        # ehrliche 503 statt eines anonymen Serverfehlers.
        label = engine.status().get("label") or msg("taskGeneric")
        return JSONResponse(
            status_code=503,
            content={"detail": msg("engineBusy", label=label)},
        )
    app.state.engine = engine
    app.state.thumb_pool = thumb_pool

    # Beim Start automatisch nachziehen: Erstelldaten (ADR 0021 — die manuelle
    # Re-Scan-Pflicht war eine Stolperfalle) und der FTS5-Suchindex (ADR 0024 —
    # Alt-Bestand vor Migration 0013 bzw. Drift).
    with contextlib.closing(connect(db_path)) as boot_conn:
        undated = boot_conn.execute(
            "SELECT EXISTS(SELECT 1 FROM items WHERE media_date IS NULL)"
        ).fetchone()[0]
        index_drift = boot_conn.execute(
            """SELECT (SELECT COUNT(*) FROM items)
                    != (SELECT COUNT(*) FROM search_index)
                OR (SELECT COUNT(*) FROM search_index)
                    != (SELECT COUNT(*) FROM search_index_map)"""
        ).fetchone()[0]
    if undated:
        engine.enqueue_media_date_backfill()
    if index_drift:
        engine.enqueue_search_reindex()

    @contextlib.contextmanager
    def read_conn():
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    # Schreib-Epochen-Caches (ADR 0048): Trefferlisten fürs Galerie-Scrollen
    # und die Modell-Basisliste der Sidebar. Zwei getrennte Instanzen, damit
    # Scroll-Zustände die Basisliste nicht aus dem kleinen LRU verdrängen.
    hits_cache = EpochCache(db_path)
    models_cache = EpochCache(db_path)

    # Shell-Module/CSS: immer revalidieren (ETag/304). Ohne das klebt der
    # Browser nach Updates an alten Modulen — bei einer lokalen App fatal,
    # weil niemand an Shift-Reload denkt. 304-Antworten kosten praktisch nichts.
    @app.middleware("http")
    async def static_revalidate(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    # -- Seite -------------------------------------------------------------

    @app.get("/")
    def index() -> FileResponse:
        # Kein Caching: die Seite ändert sich in der Entwicklung laufend, und der
        # eingebettete Browser (CMUX) würde sonst eine alte Version festhalten.
        return FileResponse(
            _STATIC / "index.html",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    # -- Ordner-Browser ----------------------------------------------------
    # (Die früheren „Festen Scan-Orte" — /api/locations aus [[scan.locations]] —
    # sind als GUI-Konzept gestrichen: sie standen als konkurrierende Ordner-
    # Liste neben den Watchordnern, Feral Strawberry 2026-07-09. Einstiegspunkte sind
    # jetzt immer die Wurzeln: Projektordner, Home, Laufwerke.)

    @app.get("/api/roots")
    def roots() -> dict:
        return {"roots": library.list_roots()}

    @app.get("/api/browse")
    def browse(path: str = Query(...)) -> dict:
        try:
            return library.browse_directory(path)
        except (NotADirectoryError, FileNotFoundError):
            raise HTTPException(status_code=400,
                                detail=msg("errNotADirectory", path=path))

    # -- Bestand -----------------------------------------------------------

    @app.get("/api/stats")
    def stats() -> dict:
        with read_conn() as conn:
            payload = library.library_stats(conn)
        # I4 (ADR 0041): das Topbar-Badge zeigt den Übersichtsmodus — Stats
        # lädt die Shell ohnehin beim Boot, kein eigener Endpunkt nötig.
        payload["verwaltung"] = verwaltung_enabled()
        # I5 (ADR 0041): Instanzname + Akzentfarbe fürs Frontend (Badge,
        # Tab-Titel, Favicon) — je Aufruf frisch, wirkt ohne Neustart.
        cfg = load_config(config_path) if config_path is not None else {}
        payload["instanz"] = {
            "name": cfg_instance_name(cfg),
            "farbe": cfg_instance_accent(cfg),
        }
        # Modul-Schalter Rankings (ADR 0045): steuert NUR die Sidebar-Gruppe —
        # inaktiv stellt die UI keine Ranking-Queries.
        payload["rankings"] = cfg_rankings_enabled(cfg)
        return payload

    @app.get("/api/models")
    def models(filter: str | None = Query(None)) -> dict:
        # Mitfilternde Zähler (Block S4): ?filter= = aktiver Suchzustand;
        # der Gruppen-Ausschluss (eigene Chips raus) passiert serverseitig.
        with read_conn() as conn:
            order = (cfg_model_sort(load_config(config_path))
                     if config_path is not None else "zuletzt")
            try:
                return library.models_facet(conn, order=order, filter_expr=filter,
                                            cache=models_cache)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=_err(exc))

    @app.get("/api/facets")
    def facets(filter: str | None = Query(None)) -> dict:
        # Sidebar-Gruppen Dateityp/Format/Auflösung/Jahr + LoRA/Eingangsbild —
        # ein Endpunkt, ein Request beim Sidebar-Refresh; je Gruppe zählt der
        # Kontext der ANDEREN Chips (Block S4, ADR 0037).
        with read_conn() as conn:
            try:
                payload = library.facets_payload(conn, filter_expr=filter)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=_err(exc))
            # UI-Schalter: Dubletten-Zeile ausblendbar (Konfiguration).
            payload["show_dupes"] = (cfg_show_dupes(load_config(config_path))
                                     if config_path is not None else True)
            return payload

    @app.get("/api/items")
    def items(
        limit: int = Query(200, ge=1, le=500),
        offset: int = Query(0, ge=0),
        sort: str = Query("added"),
        model: str | None = Query(None),
        rating: int | None = Query(None, ge=1, le=5),
        filter: str | None = Query(None),
        dupes: bool = Query(False),
        total: bool = Query(True),
    ) -> dict:
        with read_conn() as conn:
            try:
                return library.list_items(
                    conn, limit=limit, offset=offset, sort=sort,
                    model=model, rating=rating, filter_expr=filter, dupes=dupes,
                    with_total=total, cache=hits_cache,
                )
            except ValueError as exc:   # ungültiger Filterausdruck (ADR 0018)
                raise HTTPException(status_code=400, detail=_err(exc))

    @app.get("/api/ratings")
    def ratings(filter: str | None = Query(None)) -> dict:
        with read_conn() as conn:
            try:
                return {"ratings": library.ratings_facet(conn, filter_expr=filter)}
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=_err(exc))

    @app.get("/api/item/{file_hash}")
    def item(file_hash: str) -> dict:
        _require_hash(file_hash)
        with read_conn() as conn:
            detail = library.item_detail(conn, file_hash)
        if detail is None:
            raise HTTPException(status_code=404, detail=msg("errUnknownItem"))
        return detail

    @app.post("/api/item/{file_hash}/reveal")
    def reveal_endpoint(file_hash: str) -> dict:
        """„Im Dateimanager anzeigen" (I6, ADR 0041): der Server öffnet
        Explorer/Finder mit der ersten noch existierenden Fundort-Datei —
        im localhost-Normalbetrieb (ADR 0001) der Rechner des Anwenders.
        Reine Anzeige, darum keine Übersichtsmodus-Sperre (I4)."""
        _require_hash(file_hash)
        with read_conn() as conn:
            resolved = library.resolve_media(conn, file_hash)
        if resolved is None:
            raise HTTPException(status_code=404, detail=msg("errNoLocation"))
        path = Path(resolved[0])
        try:
            reveal.show_in_file_manager(path)
        except OSError as exc:
            raise HTTPException(status_code=500,
                                detail=msg("errRevealFailed", error=str(exc)))
        return {"revealed": str(path)}

    # -- Manuelle Schicht: Rating, Notizen, Tags (Stufe 3.2, ADR 0017) --------
    # Kurze Schreibgriffe laufen synchron durch den EINEN Writer (ADR 0007);
    # Validierung passiert vorab, weil der Worker Fehler nur als Text meldet.

    def _require_item(file_hash: str) -> None:
        _require_hash(file_hash)
        with read_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM items WHERE file_hash = ?", (file_hash,)
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=msg("errUnknownItem"))

    def _manual_state(file_hash: str) -> dict:
        with read_conn() as conn:
            return {"manual": manual.annotations_for(conn, file_hash)}

    # -- Smart Folders (Stufe 3.3, ADR 0018) ----------------------------------

    @app.get("/api/folders")
    def folders_endpoint() -> dict:
        # Zähler live mitliefern; ein (nach Grammatik-Änderung) ungültiger
        # Ausdruck macht die Liste nicht kaputt, sondern trägt den Fehler.
        with read_conn() as conn:
            result = []
            for f in folders_db.list_folders(conn):
                entry = dict(f)
                try:
                    entry["count"] = library.list_items(
                        conn, limit=1, filter_expr=f["expression"]
                    )["total"]
                    entry["error"] = None
                except ValueError as exc:
                    entry["count"] = None
                    entry["error"] = _err(exc)
                result.append(entry)
            return {"folders": result}

    @app.post("/api/folders")
    def create_folder(req: FolderRequest) -> dict:
        try:
            filters.parse(req.expression)   # Grammatik vorab prüfen (ADR 0018)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_err(exc))
        try:
            folder_id = engine.run_write(
                msg("taskFolderCreate"),
                lambda conn, _p: {"id": folders_db.create(conn, req.name, req.expression)},
            )
        except Exception as exc:  # pragma: no cover — Namenskonflikt u. Ä.
            raise HTTPException(status_code=400, detail=_err(exc))
        if "id" not in folder_id:
            raise HTTPException(status_code=400,
                                detail=folder_id.get("summary") or msg("errCreateFailed"))
        return folder_id

    @app.put("/api/folders/{folder_id}")
    def update_folder(folder_id: int, req: FolderRequest) -> dict:
        # Überschreiben/Umbenennen aus dem Speicherdialog (Block S7).
        try:
            filters.parse(req.expression)   # Grammatik vorab prüfen (ADR 0018)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_err(exc))
        # Fehler aus der Lambda (Namenskonflikt, unbekannte ID) kommen als
        # result["summary"] zurück, nicht als Exception (engine._worker).
        result = engine.run_write(
            msg("taskFolderUpdate"),
            lambda conn, _p: (
                folders_db.update(conn, folder_id, req.name, req.expression),
                {"id": folder_id},
            )[1],
        )
        if "id" not in result:
            raise HTTPException(status_code=400,
                                detail=result.get("summary") or msg("errUpdateFailed"))
        return result

    @app.delete("/api/folders/{folder_id}")
    def delete_folder(folder_id: int) -> dict:
        return engine.run_write(
            msg("taskFolderDelete"),
            lambda conn, _p: {"deleted": folders_db.delete(conn, folder_id)},
        )

    # -- Ranking-Modul (Großbaustelle R, ADR 0045) -----------------------------
    #
    # Die Endpunkte existieren unabhängig vom Modul-Schalter; der Schalter
    # steuert nur die UI (Sidebar-Gruppe, Block R2) — inaktiv ruft sie niemand.

    def _validate_arena_expression(expression: str) -> None:
        # Leer = ganze Bibliothek (ADR 0040/0045); sonst Grammatik vorab prüfen.
        if expression and expression.strip():
            try:
                filters.parse(expression)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=_err(exc))

    def _require_ranking(conn, ranking_id: int) -> dict:
        ranking = rankings_db.get(conn, ranking_id)
        if ranking is None:
            raise HTTPException(status_code=404, detail=msg("arenaGone"))
        return ranking

    @app.get("/api/rankings")
    def rankings_endpoint() -> dict:
        # Populations-Zähler live mitliefern; ein ungültig gewordener Ausdruck
        # macht die Liste nicht kaputt, sondern trägt den Fehler (Muster
        # /api/folders).
        with read_conn() as conn:
            result = []
            for r in rankings_db.list_rankings(conn):
                entry = dict(r)
                try:
                    # Leerer Ausdruck = ganze Bibliothek (ADR 0045) — der
                    # Parser lehnt Leeres ab, also gar nicht erst filtern.
                    entry["population"] = library.list_items(
                        conn, limit=1, filter_expr=r["expression"] or None
                    )["total"]
                    entry["error"] = None
                except ValueError as exc:
                    entry["population"] = None
                    entry["error"] = _err(exc)
                result.append(entry)
            return {"rankings": result}

    @app.post("/api/rankings")
    def create_ranking(req: RankingRequest) -> dict:
        _validate_arena_expression(req.expression)
        result = engine.run_write(
            msg("taskArenaCreate"),
            lambda conn, _p: {"id": rankings_db.create(conn, req.name, req.expression)},
        )
        if "id" not in result:
            raise HTTPException(status_code=400,
                                detail=result.get("summary") or msg("errCreateFailed"))
        return result

    @app.put("/api/rankings/{ranking_id}")
    def update_ranking(ranking_id: int, req: RankingRequest) -> dict:
        _validate_arena_expression(req.expression)
        result = engine.run_write(
            msg("taskArenaUpdate"),
            lambda conn, _p: (
                rankings_db.update(conn, ranking_id, req.name, req.expression),
                {"id": ranking_id},
            )[1],
        )
        if "id" not in result:
            raise HTTPException(status_code=400,
                                detail=result.get("summary") or msg("errUpdateFailed"))
        return result

    @app.delete("/api/rankings/{ranking_id}")
    def delete_ranking(ranking_id: int) -> dict:
        # Bewusster Akt (ADR 0045): CASCADE räumt Duelle + Scores mit ab;
        # die Bestätigung ist Sache der UI (R2).
        return engine.run_write(
            msg("taskArenaDelete"),
            lambda conn, _p: {"deleted": rankings_db.delete(conn, ranking_id)},
        )

    @app.get("/api/rankings/{ranking_id}/pair")
    def ranking_pair(ranking_id: int) -> dict:
        with read_conn() as conn:
            ranking = _require_ranking(conn, ranking_id)
            try:
                pair = rankings_lib.next_pair(conn, ranking)
            except ValueError as exc:   # Ausdruck ungültig geworden
                raise HTTPException(status_code=400, detail=_err(exc))
        if pair is None:
            raise HTTPException(status_code=409, detail=msg("errArenaTooSmall"))
        return pair

    @app.post("/api/rankings/{ranking_id}/duel")
    def ranking_duel(ranking_id: int, req: DuelRequest) -> dict:
        _require_hash(req.winner)
        _require_hash(req.loser)
        if req.outcome not in (rankings_db.WIN, rankings_db.BOTH_LOST):
            raise HTTPException(status_code=400,
                                detail=msg("duelUnknownOutcome", outcome=repr(req.outcome)))
        result = engine.run_write(
            msg("taskDuel"),
            lambda conn, _p: {
                "scores": rankings_db.record_duel(
                    conn, ranking_id, req.winner, req.loser, outcome=req.outcome
                )
            },
        )
        if "scores" not in result:
            raise HTTPException(status_code=400,
                                detail=result.get("summary") or msg("errDuelFailed"))
        return result

    @app.get("/api/rankings/{ranking_id}/leaderboard")
    def ranking_leaderboard(
        ranking_id: int,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> dict:
        with read_conn() as conn:
            ranking = _require_ranking(conn, ranking_id)
            try:
                return rankings_lib.leaderboard(conn, ranking, limit=limit, offset=offset)
            except ValueError as exc:   # Ausdruck ungültig geworden
                raise HTTPException(status_code=400, detail=_err(exc))

    @app.post("/api/admin/rankings/recompute")
    def rankings_recompute() -> dict:
        # „Scores neu berechnen" (Rescan-Prinzip, ADR 0045): Replay über das
        # Duell-Log aller Arenen — deterministisch, ersetzt den Bestand.
        return engine.run_write(
            msg("taskRankScores"),
            lambda conn, _p: {"replayed": rankings_db.recompute_scores(conn)},
        )

    @app.get("/api/tags")
    def tags_endpoint() -> dict:
        with read_conn() as conn:
            return {"tags": manual.list_tags(conn)}

    @app.post("/api/item/{file_hash}/rating")
    def set_rating_endpoint(file_hash: str, req: RatingUpdate) -> dict:
        _require_item(file_hash)
        if req.rating is not None and not 0 <= req.rating <= 5:
            raise HTTPException(status_code=400, detail=msg("ratingRange"))
        engine.run_write(
            msg("taskRatingSet"),
            lambda conn, _p: (manual.set_rating(conn, file_hash, req.rating), {})[1],
        )
        return _manual_state(file_hash)

    @app.post("/api/item/{file_hash}/notes")
    def set_notes_endpoint(file_hash: str, req: NotesUpdate) -> dict:
        _require_item(file_hash)
        engine.run_write(
            msg("taskNotesSet"),
            lambda conn, _p: (manual.set_notes(conn, file_hash, req.notes), {})[1],
        )
        return _manual_state(file_hash)

    @app.post("/api/item/{file_hash}/tags")
    def add_tag_endpoint(file_hash: str, req: TagRequest) -> dict:
        _require_item(file_hash)
        if not req.name.strip():
            raise HTTPException(status_code=400, detail=msg("tagEmpty"))
        engine.run_write(
            msg("taskTagAdd"),
            lambda conn, _p: {"tag_id": manual.add_tag(conn, file_hash, req.name)},
        )
        return _manual_state(file_hash)

    @app.post("/api/item/{file_hash}/tags/remove")
    def remove_tag_endpoint(file_hash: str, req: TagRequest) -> dict:
        _require_item(file_hash)
        engine.run_write(
            msg("taskTagRemove"),
            lambda conn, _p: {"removed": manual.remove_tag(conn, file_hash, req.name)},
        )
        return _manual_state(file_hash)

    @app.post("/api/batch/annotate")
    def batch_annotate(req: BatchAnnotateRequest) -> dict:
        # Multiselect-Sammelaktion (ADR 0022): EIN Durchlauf durch den einen
        # Writer für Bewertung/Tag/manuelles Modell der ganzen Auswahl.
        if not req.hashes or len(req.hashes) > 2000:
            raise HTTPException(status_code=400, detail=msg("errBatchSize"))
        for file_hash in req.hashes:
            _require_hash(file_hash)
        if req.rating is None and req.add_tag is None and req.model is None:
            raise HTTPException(status_code=400, detail=msg("errNoAction"))
        if req.rating is not None and req.rating not in range(6):
            raise HTTPException(status_code=400, detail=msg("ratingRange"))

        def fn(conn, _p):
            updated = 0
            for file_hash in req.hashes:
                try:
                    if req.rating is not None:
                        manual.set_rating(conn, file_hash, req.rating)
                    if req.add_tag is not None and req.add_tag.strip():
                        manual.add_tag(conn, file_hash, req.add_tag)
                    if req.model is not None:
                        manual.set_model(conn, file_hash, req.model)
                    updated += 1
                except ValueError:
                    continue   # unbekanntes Item: überspringen, Rest anwenden
            return {
                "updated": updated,
                # Frischer Stand des ersten Hashs — das Panel zeigt ihn an.
                "manual": manual.annotations_for(conn, req.hashes[0]),
            }

        return engine.run_write(msg("taskBatch", n=len(req.hashes)), fn,
                                timeout=60.0)

    @app.post("/api/batch/apply")
    def batch_apply(req: BulkApplyRequest) -> dict:
        # Sammel-Aktion auf das ganze Suchergebnis (ADR 0040): der Server
        # materialisiert die Treffermenge selbst — das Frontend hält nie
        # Hash-Listen des ganzen Ergebnisses. Multiselect-Scope über hashes.
        if req.hashes is not None:
            if not req.hashes or len(req.hashes) > 2000:
                raise HTTPException(status_code=400, detail=msg("errBatchSize"))
            for file_hash in req.hashes:
                _require_hash(file_hash)
        # Alles VOR dem Writer prüfen — run_write verpackt Aufgaben-Fehler in
        # ein summary-Dict statt zu werfen (Muster create_folder).
        if req.reject and any(
            v is not None for v in (req.rating, req.add_tag, req.model, req.note)
        ):
            raise HTTPException(status_code=400, detail=msg("errRejectExclusive"))
        if not req.reject and all(
            v is None for v in (req.rating, req.add_tag, req.model, req.note)
        ):
            raise HTTPException(status_code=400, detail=msg("errNoAction"))
        if req.rating is not None and req.rating not in (1, 2, 3, 4, 5):
            raise HTTPException(status_code=400, detail=msg("errBaseRating"))
        try:
            if req.filter.strip():
                filters.parse(req.filter)
        except ValueError as err:
            raise HTTPException(status_code=400, detail=_err(err))

        def fn(conn, _p):
            return bulk_lib.apply_bulk(
                conn,
                filter_expr=req.filter,
                hashes=req.hashes,
                rating=req.rating,
                add_tag=req.add_tag,
                model=req.model,
                note=req.note,
                reject=req.reject,
                thumb_cache=thumb_cache,
            )

        # Gemessen (ADR 0040): 20k Treffer ≈ 0,4–1,3 s je nach Aktion — auch
        # 250k bleiben deutlich unter dem Timeout.
        result = engine.run_write(msg("taskBulk"), fn, timeout=300.0)
        if "matched" not in result:
            raise HTTPException(status_code=500,
                                detail=result.get("summary") or msg("errBulkFailed"))
        return result

    @app.get("/api/admin/blocked")
    def admin_blocked() -> dict:
        with read_conn() as conn:
            return {"blocked": admin_lib.blocked_list(conn)}

    @app.post("/api/admin/blocked/remove")
    def admin_unblock(file_hash: str | None = Query(None)) -> dict:
        if file_hash is not None:
            _require_hash(file_hash)
        return engine.run_write(
            msg("taskUnblock"),
            lambda conn, _p: {"removed": admin_lib.unblock(conn, file_hash)},
        )

    # -- Rausverschiebe-Dialog (I3, ADR 0041) --------------------------------
    # Der EINZIGE Datei-Bewegungsweg neben dem Import: abgelehnte Dateien
    # unter library.root in einen Zielordner verschieben (Datumsstruktur +
    # Protokoll wie beim Import). Braucht eine konfigurierte Library.

    @app.get("/api/admin/moveout")
    def admin_moveout_overview() -> dict:
        from ..moveout import overview

        root, _ = configured_import()
        locked = not verwaltung_enabled()   # I4: Dialog erklärt die Sperre
        if not root:
            return {"available": False, "locked": locked}
        with read_conn() as conn:
            return {"available": True, "locked": locked,
                    "library_root": root, **overview(conn, root)}

    @app.post("/api/admin/moveout")
    def admin_moveout(req: MoveoutRequest) -> dict:
        _require_verwaltung()   # I4: Rausverschieben ist dateischreibend
        root, min_date_str = configured_import()
        if not root:
            raise HTTPException(status_code=400, detail=msg("errNoLibrary"))
        target = (req.target or "").strip()
        if not target:
            raise HTTPException(status_code=400, detail=msg("errNoTarget"))
        # Ziel in der Library wäre kein „raus": die Dateien blieben Library-
        # Bestand (und der nächste Lauf fände sie erneut).
        if Path(target).resolve().is_relative_to(Path(root).resolve()):
            raise HTTPException(status_code=400, detail=msg("errTargetInLibrary"))
        from datetime import datetime, timezone

        min_date = datetime.fromisoformat(min_date_str).replace(tzinfo=timezone.utc)
        engine.enqueue_moveout(library_root=root, target_root=target, min_date=min_date)
        return {"queued": True, "target": target}

    @app.get("/api/thumb/{file_hash}")
    def thumb(file_hash: str) -> Response:
        _require_hash(file_hash)
        # Schnellpfad: existierendes Thumbnail direkt ausliefern — ohne
        # DB-Verbindung. Bei tausenden Kacheln macht das den Unterschied
        # zwischen „tröpfelt sofort rein" und sekundenlangem Stau.
        cached = thumb_path(thumb_cache, file_hash)
        if cached.is_file():
            return FileResponse(cached, media_type="image/jpeg",
                                headers={"Cache-Control": "public, max-age=31536000, immutable"})
        if fail_reason(thumb_cache, file_hash) is not None:
            raise HTTPException(status_code=404, detail=msg("errNoThumb"))
        # Fehlt noch: Generierung in den Prozess-Pool einreihen und SOFORT mit
        # 202 antworten (ADR 0020) — der Handler blockiert nie, die ~6
        # Browser-Verbindungen bleiben für Item-Daten und Status-Polls frei.
        # Das Frontend versucht es mit Backoff erneut.
        with read_conn() as conn:
            row = conn.execute(
                "SELECT media_kind FROM items WHERE file_hash = ?", (file_hash,)
            ).fetchone()
            source = None
            if row is not None:
                # resolve_media statt eigener Pfad-Suche: derselbe Größen-
                # Wächter wie /api/media (ADR 0049) — sonst könnte ein
                # Thumbnail aus fremden Bytes entstehen und unter diesem
                # Hash dauerhaft im Cache kleben.
                resolved = library.resolve_media(conn, file_hash)
                source = resolved[0] if resolved else None
        if row is None or source is None:
            raise HTTPException(status_code=404, detail=msg("errNoThumb"))
        thumb_pool.submit(file_hash, source, cached,
                          media_kind=row["media_kind"], size=thumb_size)
        return Response(status_code=202, headers={"Cache-Control": "no-store", "Retry-After": "1"})

    @app.get("/api/workflow/{file_hash}")
    def workflow(file_hash: str) -> Response:
        _require_hash(file_hash)
        with read_conn() as conn:
            text = library.workflow_json(conn, file_hash)
            fields = None if text else library.a1111_fields(conn, file_hash)
        if text is not None:
            # Roh-Blob unverändert durchreichen (Schicht 1) — auch als Download
            # per Drag&Drop wieder in ComfyUI ladbar.
            return Response(content=text, media_type="application/json")
        # A1111-Items haben keinen eingebetteten Workflow: aus den
        # interpretierten Feldern einen minimalen, echten ComfyUI-Graphen
        # erzeugen (Block N, ADR 0044) — Anzeige UND Download laufen über
        # denselben JSON.
        graph = a1111_graph.build_workflow(fields) if fields else None
        if graph is None:
            raise HTTPException(status_code=404, detail=msg("errNoWorkflow"))
        return JSONResponse(content=graph)

    @app.get("/api/media/{file_hash}")
    def media(file_hash: str) -> FileResponse:
        _require_hash(file_hash)
        with read_conn() as conn:
            resolved = library.resolve_media(conn, file_hash)
        if resolved is None:
            raise HTTPException(status_code=404, detail=msg("errNoLocation"))
        path, mime = resolved
        # Hash-adressiert ⇒ Inhalt ändert sich nie: aggressiv cachen macht das
        # Blättern in der Detailansicht (Pfeiltasten) nach dem ersten Mal instant.
        return FileResponse(path, media_type=mime,
                            headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @app.get("/api/preview/{file_hash}")
    def preview(file_hash: str) -> Response:
        """Gerenderte JPEG-Ansicht für Container ohne Browser-Unterstützung
        (TIFF/PSD, ADR 0052). /api/media bleibt die Originalbytes; hier wird
        on-the-fly über Pillow gerendert — hash-adressiert und damit genauso
        aggressiv cachebar, der Browser hält das Ergebnis selbst vor.
        """
        _require_hash(file_hash)
        with read_conn() as conn:
            resolved = library.resolve_media(conn, file_hash)
        if resolved is None:
            raise HTTPException(status_code=404, detail=msg("errNoLocation"))
        data, reason = render_preview(resolved[0])
        if data is None:
            # reason kann Meldungs-JSON sein (PSD ohne Composite) — als
            # verschachtelte Meldung übergeben, dann übersetzt das Frontend.
            raise HTTPException(status_code=404,
                                detail=msg("errPreviewFailed",
                                           reason=msg_load(reason)))
        return Response(content=data, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})

    # -- Chip-Suche (Block S3, ADR 0035) -----------------------------------
    #
    # Die frühere Snippet-Trefferliste (/api/search) ist ersatzlos entfallen —
    # die Textsuche filtert das Grid (text:-Prädikate über den kuratierten
    # FTS-Index, ADR 0036). Diese beiden Endpunkte sind die einzige Brücke
    # zwischen Chips und Grammatik: EIN Parser, EIN Serialisierer.

    @app.get("/api/filter/parse")
    def filter_parse(expr: str = Query("")) -> dict:
        """Ausdruck → kanonischer Text + Prädikat-Dicts + Sortierschlüssel."""
        try:
            return filters.parse_for_api(expr)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=_err(e))

    @app.post("/api/filter/build")
    def filter_build(req: FilterBuildRequest) -> dict:
        """Chip-Zustand → kanonischer Text (validiert über serialize+parse)."""
        try:
            preds = [filters.predicate_from_dict(d) for d in req.predicates]
            return filters.parse_for_api(filters.serialize(preds))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=_err(e))

    # -- Scan & Watch ------------------------------------------------------

    @app.post("/api/import")
    def import_endpoint(req: ImportRequest) -> dict:
        # Import-Kern (Stufe 4.1, ADR 0019): braucht die Bestands-Wurzel.
        if req.modus not in ("kopieren", "verschieben", "katalogisieren"):
            raise HTTPException(status_code=400, detail=msg("errBadModus"))
        if req.modus == "katalogisieren":
            # ADR 0031: am Ort aufnehmen — reiner Scan, keine Media Library nötig.
            if not Path(req.path).is_dir():
                raise HTTPException(status_code=400,
                                    detail=msg("errNotADirectory", path=req.path))
            return {"queued_files": engine.enqueue_folder(req.path, configured_rules()),
                    "target": req.path}
        _require_verwaltung()   # I4: kopieren/verschieben legen Dateien an
        target, min_date_str = configured_import()
        if not target:
            raise HTTPException(status_code=400, detail=msg("errNoLibrary"))
        if not Path(req.path).is_dir():
            raise HTTPException(status_code=400,
                                detail=msg("errNotADirectory", path=req.path))
        if Path(target).resolve() == Path(req.path).resolve():
            raise HTTPException(status_code=400, detail=msg("errSourceIsLibrary"))
        from datetime import datetime, timezone

        min_date = datetime.fromisoformat(min_date_str).replace(tzinfo=timezone.utc)
        # ADR 0031: kopieren fasst die Quelle NIE an; verschieben leert sie.
        count = engine.enqueue_import(
            req.path, target_root=target, min_date=min_date,
            source_mode="loeschen" if req.modus == "verschieben" else "belassen",
            remove_empty=req.leere_ordner_entfernen and req.modus == "verschieben",
            rules=configured_rules(),
        )
        # Direkt danach Thumbnails vorwärmen (Warteschlange = läuft nach dem
        # Import) — sonst erwürgt der erste Grid-Besuch die Oberfläche mit
        # zehntausenden On-Demand-Generierungen.
        if thumb_cache is not None:
            engine.enqueue_thumb_warm(thumb_cache, thumb_size, pool=thumb_pool)
        return {"queued_files": count, "target": str(target)}

    @app.post("/api/scan")
    def scan(req: ScanRequest) -> dict:
        if not Path(req.path).is_dir():
            raise HTTPException(status_code=400,
                                detail=msg("errNotADirectory", path=req.path))
        count = engine.enqueue_folder(req.path, configured_rules())
        return {"queued_files": count}

    @app.get("/api/status")
    def status() -> dict:
        return engine.status()

    # -- Watch-Quellen (ADR 0030) -------------------------------------------
    # Mehrere überwachte Quellordner, je Modus kopieren/verschieben; alle
    # speisen dieselbe Import-Pipeline (ADR 0019). Zustand lebt in der Config
    # ([[watch]]) + der Laufzeit-Engine; hier nur die HTTP-Hülle.

    def _configured_watch_sources() -> list[dict]:
        if config_path is not None:
            return cfg_watch_sources(load_config(config_path))
        return []

    def _find_watch_source(path: str) -> dict | None:
        key = engine.watch_key(path)
        for src in _configured_watch_sources():
            if engine.watch_key(src["path"]) == key:
                return src
        return None

    def _start_watch_source(source: dict) -> None:
        """Eine Quelle validieren und überwachen. Wirft HTTPException bei
        Fehlkonfiguration (fehlender Ordner / fehlendes Import-Ziel)."""
        from datetime import datetime, timezone

        root = Path(source["path"])
        if not root.is_dir():
            raise HTTPException(status_code=400,
                                detail=msg("errNotADirectory", path=source["path"]))

        if source["modus"] == "katalogisieren":
            # ADR 0031: am Ort aufnehmen — weder kopieren noch bewegen.
            # Braucht keine Media Library (es entsteht keine Kopie).
            name = source.get("name") or root.name

            def on_scan_ready(files: list[Path]) -> None:
                # Regeln je Batch frisch lesen (ADR 0046) — der Watcher läuft
                # lange, die Config kann sich zwischendurch ändern.
                engine.enqueue_files(files,
                                     label=msg("taskWatchBatch", name=name,
                                               n=len(files)),
                                     rules=configured_rules())
                if thumb_cache is not None:
                    engine.enqueue_thumb_warm(thumb_cache, thumb_size, pool=thumb_pool)

            engine.start_watch_source(source, on_scan_ready)
            return

        _require_verwaltung()   # I4: kopieren/verschieben legen Dateien an
        target, min_date_str = configured_import()
        if not target:
            raise HTTPException(status_code=400, detail=msg("errWatchNeedsLibrary"))
        min_date = datetime.fromisoformat(min_date_str).replace(tzinfo=timezone.utc)
        # ADR 0031: kopieren fasst die Quelle NIE an; verschieben leert sie.
        source_mode = "loeschen" if source["modus"] == "verschieben" else "belassen"
        # ADR 0033: Leerordner-Aufräumen nur, wo wir die Quelle auch leeren.
        remove_empty = (
            bool(source.get("leere_ordner_entfernen"))
            and source["modus"] == "verschieben"
        )

        def on_ready(files: list[Path]) -> None:
            engine.enqueue_import_files(
                files, source_root=root, target_root=Path(target),
                min_date=min_date, source_mode=source_mode,
                remove_empty=remove_empty, rules=configured_rules(),
            )
            if thumb_cache is not None:
                engine.enqueue_thumb_warm(thumb_cache, thumb_size, pool=thumb_pool)

        engine.start_watch_source(source, on_ready)

    @app.get("/api/watch")
    def watch_list() -> dict:
        """Konfigurierte Quellen, angereichert um den Live-Zustand (überwacht?).

        Enthält auch ``quiet_seconds``/``poll_seconds``, damit die GUI die
        Liste vollständig round-trippen kann (Inline-Verwaltung im Dashboard
        speichert die GANZE Liste über /api/watch/save)."""
        live = {engine.watch_key(w["root"]): w for w in engine.status()["watchers"]}
        sources = []
        for src in _configured_watch_sources():
            w = live.get(engine.watch_key(src["path"]))
            sources.append({
                "name": src["name"], "path": src["path"], "modus": src["modus"],
                "quiet_seconds": src["quiet_seconds"],
                "poll_seconds": src["poll_seconds"],
                "leere_ordner_entfernen": src["leere_ordner_entfernen"],
                "exists": Path(src["path"]).is_dir(),
                "watching": w is not None,
                "pending": w["pending"] if w else 0,
                "enqueued_total": w["enqueued_total"] if w else 0,
            })
        target, _ = configured_import()
        return {"sources": sources, "has_library": bool(target),
                "verwaltung": verwaltung_enabled()}

    def _validate_watch_payload(sources: list[WatchSourceModel]) -> list[dict]:
        """Watch-Liste aus der GUI prüfen und in Config-Einträge übersetzen."""
        payload: list[dict] = []
        for src in sources:
            if not src.path.strip():
                raise HTTPException(status_code=400, detail=msg("errWatchNeedsPath"))
            if src.modus not in ("kopieren", "verschieben", "katalogisieren"):
                raise HTTPException(status_code=400, detail=msg("errBadModus"))
            if src.quiet_seconds is not None and not (0.2 <= src.quiet_seconds <= 3600):
                raise HTTPException(status_code=400, detail=msg("errQuietSeconds"))
            payload.append({
                "name": src.name.strip(), "path": src.path.strip(), "modus": src.modus,
                "quiet_seconds": src.quiet_seconds, "poll_seconds": src.poll_seconds,
                "leere_ordner_entfernen": src.leere_ordner_entfernen,
            })
        return payload

    @app.post("/api/watch/save")
    def watch_save(req: WatchSaveRequest) -> dict:
        """Die komplette Watch-Liste speichern (Inline-Verwaltung im Dashboard,
        ADR 0029-Nachtrag): schreibt [[watch]] in die config.toml und setzt
        alle Watcher neu auf — Änderungen wirken sofort."""
        if config_path is None:
            raise HTTPException(status_code=400, detail=msg("errNoConfig"))
        update_config_file(config_path, watch=_validate_watch_payload(req.sources))
        _start_all_watches()
        return watch_list()

    @app.post("/api/watch/start")
    def watch_start(req: WatchRef) -> dict:
        source = _find_watch_source(req.path)
        if source is None:
            raise HTTPException(status_code=404, detail=msg("errWatchUnknown"))
        _start_watch_source(source)
        return {"watching": source["path"]}

    @app.post("/api/watch/stop")
    def watch_stop(req: WatchRef) -> dict:
        engine.stop_watch_source(req.path)
        return {"watching": None}

    def _start_all_watches() -> None:
        """Alle konfigurierten, existierenden Quellen überwachen (Autostart /
        nach Config-Änderung). Fehlkonfigurierte Quellen werden still übersprungen."""
        engine.stop_all_watches()
        for src in _configured_watch_sources():
            with contextlib.suppress(HTTPException):
                _start_watch_source(src)

    # Autostart beim App-Start.
    _start_all_watches()

    # -- Admin & Wartung (Stufe 2A, ADR 0014) --------------------------------
    # Lange Aufgaben laufen asynchron über die Engine-Warteschlange (Fortschritt
    # unter /api/status, Ergebnis in `last_result`); kurze Schreibgriffe synchron
    # über engine.run_write() — beides landet im EINEN Writer-Thread (ADR 0007).

    @app.get("/api/admin/info")
    def admin_info() -> dict:
        with read_conn() as conn:
            return admin_lib.admin_info(conn, db_path=db_path, thumb_cache=thumb_cache)

    @app.get("/api/admin/issues")
    def admin_issues(per_kind: int = Query(20, ge=1, le=200)) -> dict:
        # Block N: gruppiert nach Fehlerart mit ehrlicher Gesamtzahl — die
        # flache 200er-Liste verschluckte bei >2000 Fehlern still den Rest.
        with read_conn() as conn:
            return admin_lib.issue_overview(conn, per_kind=per_kind)

    @app.post("/api/admin/issues/resolve")
    def admin_issues_resolve(
        issue_id: int | None = None, kind: str | None = None
    ) -> dict:
        count = engine.run_write(
            msg("taskIssueResolve"),
            lambda conn, _p: {
                "resolved": admin_lib.resolve_issues(conn, issue_id=issue_id, kind=kind)
            },
        )
        return count

    @app.get("/api/admin/orphans")
    def admin_orphans() -> dict:
        with read_conn() as conn:
            return {"orphans": admin_lib.orphan_locations(conn)}

    @app.post("/api/admin/prune")
    def admin_prune(req: PruneRequest | None = None) -> dict:
        under = req.under if req is not None and req.under else None
        return engine.run_write(
            msg("taskPrune"),
            lambda conn, _p: {"pruned": admin_lib.prune_orphan_locations(conn, under=under)},
            timeout=120,
        )

    @app.get("/api/admin/import-rules")
    def admin_import_rules_preview() -> dict:
        # Vorschau (ADR 0046): wie viele Bestand-Items träfen die Regeln?
        with read_conn() as conn:
            return admin_lib.import_rules_overview(conn, configured_rules())

    @app.post("/api/admin/import-rules/apply")
    def admin_import_rules_apply() -> dict:
        # Langläufer (kann tausende Items ablehnen) → Warteschlange statt
        # run_write; Ergebnis erscheint als last_result im Dashboard.
        rules = configured_rules()
        with read_conn() as conn:
            preview = admin_lib.import_rules_overview(conn, rules)
        if not preview["active"]:
            raise HTTPException(status_code=400, detail=msg("errNoImportRules"))

        def fn(conn, _progress) -> dict:
            n = admin_lib.apply_import_rules(conn, rules, thumb_cache)
            return {"summary": msg("sumImportRules", n=n)}

        engine.enqueue_task(msg("taskImportRules"), fn)
        return {"queued": "Import-Regeln auf den Bestand", "expected": preview["total"]}

    @app.post("/api/admin/reparse")
    def admin_reparse() -> dict:
        engine.enqueue_reparse()
        return {"queued": "Neu interpretieren (Schicht 2)"}

    @app.post("/api/admin/backfill-dates")
    def admin_backfill_dates() -> dict:
        engine.enqueue_media_date_backfill()
        return {"queued": "Erstelldaten nachtragen"}

    @app.post("/api/admin/reindex")
    def admin_reindex() -> dict:
        engine.enqueue_search_reindex()
        return {"queued": "Suchindex aufbauen"}

    @app.post("/api/admin/rescan")
    def admin_rescan() -> dict:
        engine.enqueue_rescan()
        return {"queued": "Re-Scan aller bekannten Fundorte"}

    @app.post("/api/admin/integrity")
    def admin_integrity() -> dict:
        engine.enqueue_integrity_check()
        return {"queued": "Integritätscheck"}

    @app.post("/api/admin/vacuum")
    def admin_vacuum() -> dict:
        engine.enqueue_vacuum()
        return {"queued": "VACUUM"}

    @app.post("/api/admin/thumbwarm")
    def admin_thumbwarm() -> dict:
        if thumb_cache is None:
            raise HTTPException(status_code=400, detail=msg("errNoThumbCache"))
        # Der Admin-Knopf ist der EINZIGE Weg mit Retry-Prinzip (bewusste
        # Aktion, z. B. nach ffmpeg-Installation) — die Automatik-Läufe
        # nach Import/Watch erzeugen nur Fehlende (ADR-0042-Ergänzung).
        engine.enqueue_thumb_warm(thumb_cache, thumb_size, pool=thumb_pool, retry_failed=True)
        return {"queued": "Thumbnails vorwärmen"}

    @app.post("/api/admin/thumbcache/clear")
    def admin_thumbcache_clear() -> dict:
        # Reiner Platten-Cache, keine DB — braucht den Writer-Thread nicht.
        return {"deleted": admin_lib.clear_thumb_cache(thumb_cache)}

    # -- Config aus der GUI ---------------------------------------------------

    @app.get("/api/admin/config")
    def admin_config() -> dict:
        if config_path is None:
            return {"editable": False}
        p = Path(config_path)
        config = load_config(p)
        return {
            "editable": True,
            "path": str(p.resolve()),
            "exists": p.is_file(),
            "thumbnail_size": thumbnail_size(config),
            "library_root": cfg_library_root(config),
            "verwaltung": cfg_library_verwaltung(config),
            "import_min_date": cfg_import_min_date(config),
            "import_rules": cfg_import_rules(config),
            "watch": cfg_watch_sources(config),
            "thumbnail_low_priority": cfg_thumb_low_priority(config),
            "thumbnail_workers": cfg_thumb_workers(config),
            "show_dupes": cfg_show_dupes(config),
            "model_sort": cfg_model_sort(config),
            "web_port": cfg_web_port(config),
            "instanz_name": cfg_instance_name(config),
            "akzentfarbe": cfg_instance_accent(config),
            "rankings_enabled": cfg_rankings_enabled(config),
            "raw": p.read_text(encoding="utf-8") if p.is_file() else "",
        }

    @app.post("/api/admin/config")
    def admin_config_save(update: ConfigUpdate) -> dict:
        if config_path is None:
            raise HTTPException(status_code=400, detail=msg("errNoConfig"))
        if not (16 <= update.thumbnail_size <= 2048):
            raise HTTPException(status_code=400, detail=msg("errThumbSize"))
        for loc in (update.locations or []):
            if not loc.name.strip() or not loc.path.strip():
                raise HTTPException(status_code=400, detail=msg("errLocationFields"))
        if update.import_min_date and update.import_min_date.strip():
            from datetime import datetime

            try:
                datetime.fromisoformat(update.import_min_date.strip())
            except ValueError:
                raise HTTPException(status_code=400, detail=msg("errMinDate"))
        if update.thumbnail_workers is not None and not (0 <= update.thumbnail_workers <= 128):
            raise HTTPException(status_code=400, detail=msg("errThumbWorkers"))
        for label, kante in (("min_kante", update.import_min_kante),
                             ("max_kante", update.import_max_kante)):
            if kante is not None and not (0 <= kante <= 1_000_000):
                raise HTTPException(status_code=400,
                                    detail=msg("errKante", label=label))
        if (update.import_min_kante and update.import_max_kante
                and update.import_min_kante > update.import_max_kante):
            raise HTTPException(status_code=400, detail=msg("errKanteOrder"))
        # Instanz (ADR 0041, I5): 0/leer = zurück zum Standard.
        if update.web_port is not None and update.web_port != 0 and not (
            1 <= update.web_port <= 65535
        ):
            raise HTTPException(status_code=400, detail=msg("errPort"))
        if update.akzentfarbe is not None and update.akzentfarbe.strip() and not re.match(
            r"^#[0-9a-fA-F]{6}$", update.akzentfarbe.strip()
        ):
            raise HTTPException(status_code=400, detail=msg("errAccent"))
        # Watch-Liste kommt normalerweise über /api/watch/save (Inline-
        # Verwaltung im Dashboard); wird sie hier mitgeschickt, gilt dieselbe
        # Prüfung. None = [[watch]] in der Datei unangetastet lassen.
        watch_payload = (
            _validate_watch_payload(update.watch) if update.watch is not None else None
        )
        update_config_file(
            config_path,
            locations=(
                [{"name": l.name.strip(), "path": l.path.strip()} for l in update.locations]
                if update.locations is not None else None
            ),
            thumbnail_size=update.thumbnail_size,
            library_root=update.library_root,
            verwaltung=update.verwaltung,
            import_min_date=update.import_min_date,
            import_min_kante=update.import_min_kante,
            import_max_kante=update.import_max_kante,
            import_formate_ausschliessen=update.import_formate_ausschliessen,
            watch=watch_payload,
            thumbnail_low_priority=update.thumbnail_low_priority,
            thumbnail_workers=update.thumbnail_workers,
            show_dupes=update.show_dupes,
            model_sort_order=update.model_sort_order,
            web_port=update.web_port,
            instance_name=update.instanz_name,
            instance_accent=update.akzentfarbe,
            rankings_enabled=update.rankings_enabled,
        )
        # Watch-Quellen übernehmen Änderungen sofort: alle neu aufsetzen
        # (entfernte Quellen fallen dabei weg). Fehler hier ≠ Speicher-Fehler.
        _start_all_watches()
        return {"saved": True, "hint": msg("cfgSavedHint")}

    # -- Statische Dateien (CSS/JS der neuen Shell, Block 3.0) ---------------

    app.mount("/static", StaticFiles(directory=_STATIC), name="static")

    return app


def _require_hash(file_hash: str) -> None:
    if not _HASH.match(file_hash):
        raise HTTPException(status_code=400, detail=msg("errBadItemId"))
