"""Serverseitige Meldungen als Schlüssel + Parameter (Block M.2, ADR 0054).

Alle serverseitig erzeugten, in der UI sichtbaren Texte (Engine-Labels,
Fortschritt, Zusammenfassungen, HTTP-Fehler-Details, Scan-Probleme) sind
**Meldungs-Dicts** ``{"key": ..., "params": {...}}`` — übersetzt wird
ausschließlich im Frontend (``strings.<lang>.js``, Abschnitt ``server``;
Renderer ``servermsg.js``). Parameter dürfen Zahlen, Strings, verschachtelte
Meldungen oder Listen von Meldungen sein (Listen joint der Renderer mit
« · ») — damit lassen sich zusammengesetzte Zusammenfassungen wie
„Import: 3 neu · 2 Dubletten" ohne Textbausteine im Backend bauen.

Persistiert (``scan_issues.message``, ``blocked_hashes.reason``) wird die
Meldung als JSON-Text (``dump``); beim Ausliefern macht ``load`` daraus
wieder ein Dict. Übergangsregel (ADR 0054): Alt-Einträge und rohe
Fehlertexte, die kein Meldungs-JSON sind, bleiben unverändert Strings und
werden im Frontend roh angezeigt — nichts bricht.
"""

from __future__ import annotations

import json
from typing import Any


def msg(key: str, **params: Any) -> dict[str, Any]:
    """Eine übersetzbare Meldung: Schlüssel + Parameter."""
    return {"key": key, "params": params} if params else {"key": key}


def dump(key: str, **params: Any) -> str:
    """Meldung als JSON-Text für die Persistenz (deterministisch —
    ``ON CONFLICT``-Dedupe über die message-Spalte funktioniert weiter)."""
    return json.dumps(msg(key, **params), ensure_ascii=False, sort_keys=True)


def load(text: str | None) -> dict[str, Any] | str | None:
    """Persistierten Meldungstext für die API aufbereiten: Meldungs-JSON →
    Dict; alles andere (Alt-Einträge, rohe Fehlertexte) bleibt String."""
    if not text or not text.startswith("{"):
        return text
    try:
        parsed = json.loads(text)
    except ValueError:
        return text
    if isinstance(parsed, dict) and isinstance(parsed.get("key"), str):
        return parsed
    return text


class UserError(ValueError):
    """ValueError mit übersetzbarer Meldung.

    Bleibt bewusst ein ``ValueError``, damit alle bestehenden
    ``except ValueError``-Stellen (Routen, Facetten, Smart-Folder-Zähler)
    unverändert greifen. ``str()`` liefert nur eine technische Debug-Form
    für Logs/Tests — angezeigt wird immer die Übersetzung im Frontend.
    """

    def __init__(self, key: str, **params: Any) -> None:
        self.message = msg(key, **params)
        detail = " ".join(f"{k}={v!r}" for k, v in params.items())
        super().__init__(f"{key}({detail})" if detail else key)


def error_payload(exc: Exception) -> dict[str, Any] | str:
    """``detail``-/``error``-Feld einer Exception für die API: die
    übersetzbare Meldung, falls vorhanden — sonst ehrlich der rohe Text."""
    return exc.message if isinstance(exc, UserError) else str(exc)
