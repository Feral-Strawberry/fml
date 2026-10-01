"""Tests für den Host-Wächter + nosniff (ADR 0058) und die Herkunftsprüfung
ändernder Anfragen (ADR 0100).

Ohne HTTP-Client (httpx ist bewusst keine Abhängigkeit, §0.1): Die App wird
direkt als ASGI-Callable mit einem handgebauten Scope aufgerufen — genau die
Ebene, auf der die Middleware arbeitet.
"""

from __future__ import annotations

import asyncio

import pytest

from feral.web.app import _host_only, _origin_matches, create_app


def _asgi_get(app, path: str, host: str) -> tuple[int, dict[str, str]]:
    """GET über die ASGI-Schnittstelle; liefert (Status, Header-Dict)."""
    messages: list[dict] = []

    async def run() -> None:
        scope = {
            "type": "http", "http_version": "1.1", "method": "GET",
            "scheme": "http", "path": path, "raw_path": path.encode(),
            "query_string": b"", "root_path": "",
            "headers": [(b"host", host.encode())],
            "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8765),
        }

        async def receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict) -> None:
            messages.append(message)

        await app(scope, receive, send)

    asyncio.run(run())
    start = next(m for m in messages if m["type"] == "http.response.start")
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    return start["status"], headers


@pytest.fixture
def app(tmp_path):
    application = create_app(tmp_path / "t.sqlite")
    yield application
    application.state.engine.shutdown()
    application.state.thumb_pool.shutdown()


def test_host_only_zerlegt_header_varianten():
    assert _host_only("localhost") == "localhost"
    assert _host_only("127.0.0.1:8765") == "127.0.0.1"
    assert _host_only("LOCALHOST:8765") == "localhost"
    assert _host_only("[::1]:8765") == "::1"     # IPv6-Literal mit Port
    assert _host_only("[::1]") == "::1"
    assert _host_only("evil.example:80") == "evil.example"
    assert _host_only("") == ""


def test_loopback_hosts_erlaubt_und_nosniff(app):
    for host in ("127.0.0.1:8765", "localhost:8765", "[::1]:8765"):
        status, headers = _asgi_get(app, "/api/stats", host=host)
        assert status == 200, host
        assert headers.get("x-content-type-options") == "nosniff", host


def test_fremder_host_wird_abgewiesen(app):
    """DNS-Rebinding-Abwehr: fremder Host-Header ⇒ 400, kein API-Zugriff."""
    status, headers = _asgi_get(app, "/api/stats", host="rebind.evil.example")
    assert status == 400
    assert headers.get("x-content-type-options") == "nosniff"


def test_fehlender_host_wird_abgewiesen(app):
    messages: list[dict] = []

    async def run() -> None:
        scope = {"type": "http", "http_version": "1.1", "method": "GET",
                 "scheme": "http", "path": "/api/stats", "raw_path": b"/api/stats",
                 "query_string": b"", "root_path": "", "headers": [],
                 "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8765)}

        async def receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict) -> None:
            messages.append(message)

        await app(scope, receive, send)

    asyncio.run(run())
    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 400


def test_wildcard_oeffnet_die_liste(tmp_path):
    """--host jenseits von Loopback (z. B. Tailscale) ⇒ allowed_hosts=['*']."""
    application = create_app(tmp_path / "t.sqlite", allowed_hosts=["*"])
    try:
        status, headers = _asgi_get(application, "/api/stats", host="beliebig.example")
        assert status == 200
        assert headers.get("x-content-type-options") == "nosniff"
    finally:
        application.state.engine.shutdown()
        application.state.thumb_pool.shutdown()


# -- Herkunftsprüfung ändernder Anfragen (ADR 0100) ----------------------------------


def _asgi_post(app, path: str, *, host: str = "127.0.0.1:8765", query: str = "",
               method: str = "POST", **extra: str) -> int:
    """Body-lose Anfrage über die ASGI-Schnittstelle; ``extra`` sind weitere
    Kopfzeilen (Unterstrich statt Bindestrich). Liefert den Status."""
    messages: list[dict] = []

    async def run() -> None:
        headers = [(b"host", host.encode())]
        headers += [(k.replace("_", "-").encode(), v.encode()) for k, v in extra.items()]
        scope = {
            "type": "http", "http_version": "1.1", "method": method,
            "scheme": "http", "path": path, "raw_path": path.encode(),
            "query_string": query.encode(), "root_path": "", "headers": headers,
            "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8765),
        }

        async def receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict) -> None:
            messages.append(message)

        await app(scope, receive, send)

    asyncio.run(run())
    return next(m for m in messages if m["type"] == "http.response.start")["status"]


RESOLVE = "/api/admin/issues/resolve"     # ändernd, ohne Body: der Fall, um den es geht


def test_origin_matches_vergleicht_host_samt_port():
    assert _origin_matches("http://127.0.0.1:8765", "127.0.0.1:8765")
    assert _origin_matches("HTTP://LocalHost:8765", "localhost:8765")
    assert _origin_matches("http://[::1]:8765", "[::1]:8765")
    assert not _origin_matches("http://localhost:3000", "localhost:8765")     # anderer Port
    assert not _origin_matches("https://evil.example", "127.0.0.1:8765")
    assert not _origin_matches("null", "127.0.0.1:8765")                      # Sandbox, Datei
    assert not _origin_matches("", "127.0.0.1:8765")


def test_eigene_seite_und_skripte_duerfen_aendern(app):
    assert _asgi_post(app, RESOLVE, query="kind=x", origin="http://127.0.0.1:8765") == 200
    assert _asgi_post(app, RESOLVE, query="kind=x") == 200                     # curl: kein Origin
    assert _asgi_post(app, RESOLVE, query="kind=x", sec_fetch_site="same-origin") == 200


def test_fremde_seite_kann_nichts_aendern(app):
    """Ein Formular auf einer fremden Seite erreicht den Server (kein Preflight),
    trägt aber deren Origin: 403, die Route läuft nie."""
    for origin in ("https://evil.example", "http://localhost:3000", "null"):
        assert _asgi_post(app, RESOLVE, query="kind=x", origin=origin) == 403, origin
    assert _asgi_post(app, RESOLVE, query="kind=x", sec_fetch_site="cross-site") == 403
    assert _asgi_post(app, "/api/admin/cache/clear", query="kind=thumbs",
                      origin="https://evil.example") == 403
    assert _asgi_post(app, "/api/item/" + "ab" * 32 + "/comments", method="DELETE",
                      origin="https://evil.example") == 403


def test_lesen_bleibt_von_ueberall_moeglich(app):
    """GET ändert nichts; ein fremder Origin-Kopf stört dort nicht."""
    assert _asgi_post(app, "/api/stats", method="GET", origin="https://evil.example") == 200


def test_herkunft_gilt_auch_bei_geoeffneter_host_liste(tmp_path):
    application = create_app(tmp_path / "t.sqlite", allowed_hosts=["*"])
    try:
        host = "fml.tailnet.example:8765"
        assert _asgi_post(application, RESOLVE, query="kind=x", host=host,
                          origin="http://fml.tailnet.example:8765") == 200
        assert _asgi_post(application, RESOLVE, query="kind=x", host=host,
                          origin="https://evil.example") == 403
    finally:
        application.state.engine.shutdown()
        application.state.thumb_pool.shutdown()
