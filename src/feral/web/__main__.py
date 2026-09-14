"""Start der Web-Oberfläche:  python -m feral.web --db ./feral.sqlite"""

from __future__ import annotations

import argparse
import os
import socket
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from ..config import (
    database_path,
    import_min_date,
    library_root,
    load_config,
    slow_request_ms,
    thumbnail_cache_path,
    thumbnail_low_priority,
    thumbnail_size,
    thumbnail_workers,
    web_port,
)
from ..logsetup import WEB_LOG, setup_logging
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
        description="Starts the local web interface (scan control & catalog).",
    )
    parser.add_argument("--config", default="config.toml", help="path to config.toml")
    parser.add_argument("--db", default=None, help="SQLite file (overrides the config)")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: localhost)")
    # Port-Vorrang (ADR 0041/I5): --port > $PORT > [web] port > 8765.
    # $PORT vor der Config, weil Dev-Werkzeuge (Preview-Launcher) Ports
    # dynamisch zuweisen — deren Proxy bräche, wenn die Config gewönne.
    parser.add_argument(
        "--port", type=int, default=None,
        help="port (default: $PORT, else [web] port from the config, else 8765)",
    )
    parser.add_argument(
        "--browser", action="store_true",
        help="open the browser once the server is reachable (used by start.bat)",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.port is not None:
        port = args.port
    else:
        port = int(os.environ.get("PORT") or 0) or web_port(config) or 8765
    db = args.db or database_path(config)
    thumb_cache = thumbnail_cache_path(config, db)
    # Serverlog (#64): logs/ neben der Datenbank, rotierend; Konsole nur
    # Warnungen. uvicorn bekommt keine eigene Log-Konfiguration mehr, seine
    # Warnungen laufen über den Root-Logger in dieselbe Datei.
    log_dir = Path(db).resolve().parent / "logs"
    log_file = setup_logging(log_dir, WEB_LOG)

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
        log_dir=log_dir,
        slow_request_ms=slow_request_ms(config),
    )
    print(f"\n🍓 Feral Media Library is running at http://{args.host}:{port}")
    print(f"   Database:   {db}")
    print(f"   Thumbnails: {thumb_cache}")
    print(f"   Config:     {args.config}")
    print(f"   Log:        {log_file or '(console only)'}\n")
    if args.browser:
        # An 0.0.0.0/:: kann man sich nicht verbinden — dann localhost prüfen.
        probe_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
        threading.Thread(
            target=_open_browser_when_ready,
            args=(f"http://{probe_host}:{port}", probe_host, port),
            daemon=True,
        ).start()
    uvicorn.run(app, host=args.host, port=port, log_level="warning", log_config=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
