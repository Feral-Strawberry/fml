"""Auslieferung von Mediendateien: Range-Requests, Abbruch, eigener Thread-Pool.

Warum nicht Starlettes ``FileResponse`` (Befund aus dem Anfragen-Log, 2026-09-11, ADR 0069
Nachtrag): Sie liest nach einem Range-Request die Datei in 64-KB-Häppchen bis
zum Ende, auch wenn der Browser die Verbindung längst getrennt hat. uvicorn
(spec_version 2.3) wirft beim getrennten Client keinen Fehler, sondern
verwirft die Daten still. Ein abgebrochenes 4-GB-Video hielt den Server so
minutenlang beim Lesen, jedes Häppchen über denselben Pool von 40 Threads,
den auch die Datenbank-Endpunkte brauchen. Dreißig tote Streams, und die
Oberfläche steht.

Hier deshalb:

- **Abbruch:** ein Wächter lauscht auf ``http.disconnect`` und bricht das
  Streamen ab; die Anfrage endet innerhalb eines Häppchens und wird im
  Anfragen-Log als „abgebrochen" geführt (``scope[ABORTED_KEY]``).
- **1-MiB-Häppchen** statt 64 KB: ein 4-GB-Video sind 4.000 Thread-Wechsel
  statt 68.000.
- **Eigener Thread-Pool** (``MEDIA_THREADS``): Medienströme konkurrieren
  nie mit ``/api/stats``, ``/api/items`` & Co. um die Standard-Threads.
- **Range:** genau ein Bereich (``bytes=a-b``, ``bytes=a-``, ``bytes=-n``);
  mehrere Bereiche oder ein unlesbarer Header werden ignoriert und die
  Datei komplett geliefert (HTTP erlaubt das), nicht erfüllbare Bereiche
  enden mit 416. ``If-Range`` mit fremdem Validator liefert ebenfalls
  komplett.
- **ETag und Last-Modified byte-gleich wie Starlettes ``FileResponse``**
  (md5 über ``mtime-size``): Browser cachen ``/api/media`` ein Jahr als
  unveränderlich und schicken bei jedem weiteren Range-Request
  ``If-Range`` mit dem gespeicherten Validator. Ein anderer ETag hieße:
  jedes je gesehene Video wird einmal komplett statt bereichsweise
  geladen (bei 4 GB minutenlang, alle Browser-Verbindungen belegt).
"""

from __future__ import annotations

import hashlib
import os
from email.utils import formatdate
from pathlib import Path
from typing import Any

import anyio
from starlette.datastructures import Headers
from starlette.responses import Response

CHUNK_SIZE = 1024 * 1024
MEDIA_THREADS = 8
ABORTED_KEY = "feral.aborted"

_limiter = anyio.CapacityLimiter(MEDIA_THREADS)


class RangeNotSatisfiable(Exception):
    """Der angeforderte Bereich liegt hinter dem Dateiende (HTTP 416)."""


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Einen ``Range``-Header in ``(start, end_exklusiv)`` übersetzen.

    ``None`` heißt: kein oder nicht verwertbarer Header (mehrere Bereiche,
    falsche Einheit, unlesbare Zahlen, start > ende), die Datei wird dann
    komplett geliefert. Ein Bereich, der ganz hinter dem Dateiende liegt,
    wirft ``RangeNotSatisfiable``.
    """
    if not header:
        return None
    units, sep, spec = header.partition("=")
    if units.strip().lower() != "bytes" or not sep or "," in spec:
        return None
    first, dash, last = spec.strip().partition("-")
    if not dash:
        return None
    try:
        if not first:                       # bytes=-n: die letzten n Bytes
            n = int(last)
            if n <= 0:
                raise RangeNotSatisfiable
            return max(size - n, 0), size
        start = int(first)
        end = int(last) + 1 if last else size
    except ValueError:
        return None
    if start >= size:
        raise RangeNotSatisfiable
    if end <= start:
        return None
    return start, min(end, size)


class MediaFileResponse(Response):
    """Datei-Antwort mit Range-Unterstützung, Abbruch und eigenem Thread-Pool."""

    def __init__(self, path: str | os.PathLike[str], *, media_type: str,
                 cache_control: str | None = None) -> None:
        super().__init__(content=b"", media_type=media_type)
        self.path = Path(path)
        self.cache_control = cache_control

    @staticmethod
    def validators(st: os.stat_result) -> tuple[str, str]:
        """(ETag, Last-Modified) exakt wie Starlettes FileResponse — damit die
        Validatoren, die Browser aus früheren Antworten gespeichert haben,
        weiter passen (s. Modul-Docstring)."""
        etag_base = f"{st.st_mtime}-{st.st_size}"
        etag = '"' + hashlib.md5(etag_base.encode(), usedforsecurity=False).hexdigest() + '"'
        return etag, formatdate(st.st_mtime, usegmt=True)

    def _headers(self, size: int, length: int, etag: str, last_modified: str,
                 content_range: tuple[int, int] | None) -> list[tuple[bytes, bytes]]:
        out = [
            (b"content-type", (self.media_type or "application/octet-stream").encode("latin-1")),
            (b"content-length", str(length).encode("latin-1")),
            (b"accept-ranges", b"bytes"),
            (b"etag", etag.encode("latin-1")),
            (b"last-modified", last_modified.encode("latin-1")),
        ]
        if self.cache_control:
            out.append((b"cache-control", self.cache_control.encode("latin-1")))
        if content_range is not None:
            start, end = content_range
            out.append((b"content-range", f"bytes {start}-{end - 1}/{size}".encode("latin-1")))
        return out

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        st = await anyio.to_thread.run_sync(os.stat, self.path, limiter=_limiter)
        size = st.st_size
        etag, last_modified = self.validators(st)
        headers = Headers(scope=scope)
        if_range = headers.get("if-range")
        rng: tuple[int, int] | None = None
        if if_range is None or if_range in (etag, last_modified):
            try:
                rng = parse_range(headers.get("range"), size)
            except RangeNotSatisfiable:
                await send({"type": "http.response.start", "status": 416, "headers": [
                    (b"content-range", f"bytes */{size}".encode("latin-1")),
                    (b"content-length", b"0")]})
                await send({"type": "http.response.body", "body": b"", "more_body": False})
                return
        start, end = rng if rng is not None else (0, size)
        await send({"type": "http.response.start",
                    "status": 206 if rng is not None else 200,
                    "headers": self._headers(size, end - start, etag, last_modified, rng)})
        if scope.get("method", "GET").upper() == "HEAD" or end <= start:
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return

        async def watch_disconnect() -> None:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    break
            scope[ABORTED_KEY] = True
            tg.cancel_scope.cancel()

        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(watch_disconnect)
                try:
                    await self._stream(send, start, end)
                finally:
                    tg.cancel_scope.cancel()   # Wächter mit beenden
        except BaseExceptionGroup as group:
            # anyio 4 verpackt IMMER in eine Gruppe — den einen echten Fehler
            # (Netz, Platte) unverpackt weiterreichen, damit Middleware und
            # uvicorn ihn wie bisher erkennen.
            if len(group.exceptions) == 1:
                raise group.exceptions[0] from None
            raise

    async def _stream(self, send: Any, start: int, end: int) -> None:
        def open_at() -> Any:
            fp = open(self.path, "rb")   # noqa: SIM115 — bewusst außerhalb von with, Schließen unten
            fp.seek(start)
            return fp

        fp = await anyio.to_thread.run_sync(open_at, limiter=_limiter)
        try:
            pos = start
            while pos < end:
                chunk = await anyio.to_thread.run_sync(fp.read, min(CHUNK_SIZE, end - pos),
                                                       limiter=_limiter)
                if not chunk:
                    break   # Datei auf der Platte kürzer als beim stat — Länge stimmt nicht mehr
                pos += len(chunk)
                await send({"type": "http.response.body", "body": chunk, "more_body": pos < end})
        finally:
            fp.close()   # synchron: im Abbruchfall wäre ein Thread-Aufruf sofort abgebrochen
