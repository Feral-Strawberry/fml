"""MediaFileResponse (ADR 0069 Nachtrag): Range, 416, HEAD, If-Range und vor
allem der Abbruch, wenn der Client die Verbindung trennt.

Getestet auf ASGI-Ebene (Scope/receive/send von Hand), ohne HTTP-Client
(§0.1: kein httpx)."""

from __future__ import annotations

import os

import anyio
import pytest

from feral.web.media import (
    ABORTED_KEY, CHUNK_SIZE, MediaFileResponse, RangeNotSatisfiable, parse_range,
)

SIZE = 3 * CHUNK_SIZE + 17


@pytest.fixture(scope="module")
def media_file(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "clip.webm"
    data = os.urandom(SIZE)
    path.write_bytes(data)
    return path, data


def _scope(method="GET", **headers):
    return {"type": "http", "method": method,
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}


def _run(response, scope, *, disconnect_after_bodies=None):
    """Antwort ausführen; Rückgabe (status, headers, body, sent_bodies).

    disconnect_after_bodies: nach so vielen Body-Nachrichten liefert
    receive() ein http.disconnect (wie uvicorn, wenn der Browser trennt).
    """
    out = {"status": None, "headers": {}, "body": bytearray(), "bodies": 0}
    gate = anyio.Event()

    async def receive():
        if disconnect_after_bodies is None:
            await anyio.sleep_forever()
        await gate.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            out["status"] = message["status"]
            out["headers"] = {k.decode(): v.decode() for k, v in message.get("headers", [])}
        else:
            out["body"] += message.get("body", b"")
            out["bodies"] += 1
            if disconnect_after_bodies is not None and out["bodies"] >= disconnect_after_bodies:
                gate.set()
                await anyio.sleep(0)   # dem Wächter die Chance, zu reagieren

    anyio.run(response, scope, receive, send)
    return out


def _response(path):
    return MediaFileResponse(path, media_type="video/webm",
                             cache_control="public, max-age=1, immutable")


# -- parse_range ----------------------------------------------------------------

@pytest.mark.parametrize("header, expected", [
    (None, None),
    ("", None),
    ("bytes=0-", (0, 100)),
    ("bytes=10-19", (10, 20)),
    ("bytes=10-999", (10, 100)),
    ("bytes=-30", (70, 100)),
    ("bytes=-500", (0, 100)),
    ("bytes=0-10, 20-30", None),      # mehrere Bereiche: ignorieren, komplett liefern
    ("items=0-10", None),
    ("bytes=abc", None),
    ("bytes=20-10", None),
    ("bytes=5", None),
])
def test_parse_range(header, expected):
    assert parse_range(header, 100) == expected


@pytest.mark.parametrize("header", ["bytes=100-", "bytes=150-200", "bytes=-0"])
def test_parse_range_unsatisfiable(header):
    with pytest.raises(RangeNotSatisfiable):
        parse_range(header, 100)


# -- Antworten --------------------------------------------------------------------

def test_full_file_without_range(media_file):
    path, data = media_file
    out = _run(_response(path), _scope())
    assert out["status"] == 200
    assert out["headers"]["content-length"] == str(SIZE)
    assert out["headers"]["accept-ranges"] == "bytes"
    etag, last_modified = MediaFileResponse.validators(os.stat(path))
    assert out["headers"]["etag"] == etag and out["headers"]["last-modified"] == last_modified
    assert out["headers"]["cache-control"].startswith("public")
    assert bytes(out["body"]) == data
    assert out["bodies"] == 4          # 3 volle Häppchen + Rest


def test_open_ended_range(media_file):
    path, data = media_file
    out = _run(_response(path), _scope(Range=f"bytes={CHUNK_SIZE}-"))
    assert out["status"] == 206
    assert out["headers"]["content-range"] == f"bytes {CHUNK_SIZE}-{SIZE - 1}/{SIZE}"
    assert out["headers"]["content-length"] == str(SIZE - CHUNK_SIZE)
    assert bytes(out["body"]) == data[CHUNK_SIZE:]


def test_suffix_and_closed_range(media_file):
    path, data = media_file
    out = _run(_response(path), _scope(Range="bytes=-17"))
    assert out["status"] == 206 and bytes(out["body"]) == data[-17:]
    out = _run(_response(path), _scope(Range="bytes=10-20"))
    assert out["status"] == 206 and bytes(out["body"]) == data[10:21]
    assert out["headers"]["content-range"] == f"bytes 10-20/{SIZE}"


def test_range_behind_end_is_416(media_file):
    path, _ = media_file
    out = _run(_response(path), _scope(Range=f"bytes={SIZE}-"))
    assert out["status"] == 416
    assert out["headers"]["content-range"] == f"bytes */{SIZE}"
    assert out["body"] == b""


def test_if_range_with_foreign_etag_serves_full_file(media_file):
    path, data = media_file
    out = _run(_response(path), _scope(**{"Range": "bytes=10-20", "If-Range": '"fremd"'}))
    assert out["status"] == 200 and bytes(out["body"]) == data


def test_validators_match_starlette_file_response(media_file):
    """Browser-Caches (ein Jahr, immutable) tragen die Validatoren der alten
    FileResponse — beide müssen weiter als If-Range durchgehen, sonst lädt
    jedes je gesehene Video einmal komplett statt bereichsweise."""
    from starlette.responses import FileResponse
    path, data = media_file
    legacy = FileResponse(path, media_type="video/webm", stat_result=os.stat(path))
    etag, last_modified = MediaFileResponse.validators(os.stat(path))
    assert legacy.headers["etag"] == etag
    assert legacy.headers["last-modified"] == last_modified
    for validator in (etag, last_modified):
        out = _run(_response(path), _scope(**{"Range": "bytes=10-20", "If-Range": validator}))
        assert out["status"] == 206 and bytes(out["body"]) == data[10:21]


def test_completed_stream_is_not_flagged_as_aborted(media_file):
    path, _ = media_file
    scope = _scope(Range="bytes=0-")
    out = _run(_response(path), scope)
    assert out["status"] == 206 and len(out["body"]) == SIZE
    assert ABORTED_KEY not in scope


def test_head_sends_headers_only(media_file):
    path, _ = media_file
    out = _run(_response(path), _scope(method="HEAD", Range="bytes=0-"))
    assert out["status"] == 206
    assert out["headers"]["content-length"] == str(SIZE)
    assert out["body"] == b"" and out["bodies"] == 1


def test_client_disconnect_stops_the_stream(media_file):
    """Der Kern von #23/#89: Browser trennt nach dem ersten Häppchen — der
    Server liest NICHT den Rest der Datei, sondern hört auf und markiert die
    Anfrage als abgebrochen (Anfragen-Log: „abgebrochen" statt „langsam")."""
    path, _ = media_file
    scope = _scope(Range="bytes=0-")
    out = _run(_response(path), scope, disconnect_after_bodies=1)
    assert out["status"] == 206
    assert out["bodies"] <= 2, "höchstens ein weiteres Häppchen nach dem Trennen"
    assert len(out["body"]) < SIZE
    assert scope.get(ABORTED_KEY) is True
