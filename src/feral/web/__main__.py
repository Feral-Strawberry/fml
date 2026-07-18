"""Start der Web-Oberfläche:  python -m feral.web --db ./feral.sqlite"""

from __future__ import annotations

import argparse
import os
import socket
import threading
import time
import webbrowser

import uvicorn

from ..config import (
    database_path,
    import_min_date,
    library_root,
    load_config,
    thumbnail_cache_path,
    thumbnail_low_priority,
    thumbnail_size,
    thumbnail_workers,
    web_port,
)
from .app import create_app


def _open_browser_when_ready(url: str, host: str, port: int,
                             attempts: int = 60, delay: float = 0.25) -> None:
    """Browser öffnen, sobald der Server den Port wirklich angenommen hat.

    Läuft als Daemon-Thread neben uvicorn (I5-Nachbesserung, ADR 0041):
    Vorher hat start.bat den Config-Port selbst nachgerechnet und nach
    fester Wartezeit blind geöffnet — cmds Anführungszeichen-Regeln
    zerlegten den Nachrechen-Einzeiler, der Browser landete immer auf
    8765. Hier kennt Python den effektiven Port aus der kompletten
    Vorrang-Kette; kommt der Server nicht hoch (z. B. Port belegt),
    öffnet sich auch kein Browser ins Leere.
    """
    for _ in range(attempts):
        try:
            with socket.create_connection((host, port), timeout=0.5):
                pass
        except OSError:
            time.sleep(delay)
            continue
        webbrowser.open(url)
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m feral.web",
        description="Startet die lokale Web-Oberfläche (Scan-Steuerung & Bestand).",
    )
    parser.add_argument("--config", default="config.toml", help="Pfad zur config.toml")
    parser.add_argument("--db", default=None, help="SQLite-Datei (überschreibt die Config)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind-Adresse (Standard: localhost)")
    # Port-Vorrang (ADR 0041/I5): --port > $PORT > [web] port > 8765.
    # $PORT vor der Config, weil Dev-Werkzeuge (Preview-Launcher) Ports
    # dynamisch zuweisen — deren Proxy bräche, wenn die Config gewönne.
    parser.add_argument(
        "--port", type=int, default=None,
        help="Port (Standard: $PORT, sonst [web] port aus der Config, sonst 8765)",
    )
    parser.add_argument(
        "--browser", action="store_true",
        help="Browser öffnen, sobald der Server erreichbar ist (nutzt start.bat)",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.port is not None:
        port = args.port
    else:
        port = int(os.environ.get("PORT") or 0) or web_port(config) or 8765
    db = args.db or database_path(config)
    thumb_cache = thumbnail_cache_path(config, db)

    # Host-Wächter (ADR 0058): Beim Standard-Binding an Loopback bleiben nur
    # localhost/127.0.0.1/::1 als Host-Header erlaubt (DNS-Rebinding-Abwehr).
    # Wer per --host bewusst weiter bindet (z. B. Tailscale-Adresse), erreicht
    # den Server unter unbekannten Namen — dann bleibt die Liste offen.
    loopback = args.host in ("127.0.0.1", "localhost", "::1", "[::1]")
    app = create_app(
        db,
        thumb_cache=thumb_cache,
        thumb_size=thumbnail_size(config),
        thumb_workers=thumbnail_workers(config),
        thumb_low_priority=thumbnail_low_priority(config),
        config_path=args.config,
        import_target=library_root(config),
        import_min_date=import_min_date(config),
        allowed_hosts=None if loopback else ["*"],
    )
    print(f"\n🍓 Feral Media Library läuft auf http://{args.host}:{port}")
    print(f"   Datenbank:  {db}")
    print(f"   Thumbnails: {thumb_cache}")
    print(f"   Config:     {args.config}\n")
    if args.browser:
        # An 0.0.0.0/:: kann man sich nicht verbinden — dann localhost prüfen.
        probe_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
        threading.Thread(
            target=_open_browser_when_ready,
            args=(f"http://{probe_host}:{port}", probe_host, port),
            daemon=True,
        ).start()
    uvicorn.run(app, host=args.host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
