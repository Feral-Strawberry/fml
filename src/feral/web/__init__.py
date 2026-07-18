"""Web-Oberfläche (FastAPI) — lokale GUI für Scan-Steuerung und Bestand.

Erster Teil des in ADR 0001 geplanten Browser-Frontends. Bewusst klein gehalten:
ein Ordner-Browser, manueller Scan, einfacher Auto-Watch und eine simple Suche.
Das große virtualisierte Grid (Stufe 2) kommt darauf aufbauend.

Start:  ``python -m feral.web --db ./feral.sqlite``
"""

from __future__ import annotations

from .app import create_app

__all__ = ["create_app"]
