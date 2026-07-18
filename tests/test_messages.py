"""Tests für die Meldungs-Mechanik (Block M.2, ADR 0054).

Serverseitige Texte sind Schlüssel + Parameter; übersetzt wird nur im
Frontend. Hier abgesichert: das Dict-/JSON-Format, die Übergangsregel für
Alt-Einträge (roh durchreichen), die ``UserError``-Brücke — und dass JEDER
im Backend benutzte Meldungs-Schlüssel in ``strings.de.js`` unter ``server``
existiert (das Gegenstück zum Schlüsselmengen-Test aus M.1: der vergleicht
die Sprachen untereinander, dieser den Code gegen die Quelle der Wahrheit).
"""

from __future__ import annotations

import re
from pathlib import Path

from feral import messages
from feral.messages import UserError, dump, error_payload, load, msg
from tests.test_strings_i18n import load_strings


def test_msg_mit_und_ohne_parameter() -> None:
    assert msg("taskVacuum") == {"key": "taskVacuum"}
    assert msg("taskScan", root="/x") == {"key": "taskScan", "params": {"root": "/x"}}


def test_dump_load_roundtrip() -> None:
    text = dump("issueReadError", error="kaputt")
    assert load(text) == {"key": "issueReadError", "params": {"error": "kaputt"}}


def test_load_uebergangsregel_alt_eintraege_bleiben_roh() -> None:
    # Alt-Einträge aus der Zeit vor M.2 (deutsche Sätze) und beliebige rohe
    # Fehlertexte gehen unverändert durch — nichts bricht (ADR 0054).
    assert load("Lesefehler: kaputt") == "Lesefehler: kaputt"
    assert load('{"kein": "meldungsformat"}') == '{"kein": "meldungsformat"}'
    assert load("{kein json") == "{kein json"
    assert load(None) is None
    assert load("") == ""


def test_usererror_ist_valueerror_mit_meldung() -> None:
    exc = UserError("filterEmpty")
    assert isinstance(exc, ValueError)
    assert error_payload(exc) == {"key": "filterEmpty"}
    # Debug-Form für Logs/Tests trägt den Schlüssel.
    assert "filterEmpty" in str(exc)
    # Ohne Meldung: ehrlich der rohe Text.
    assert error_payload(ValueError("roh")) == "roh"


def _backend_keys() -> set[str]:
    """Alle im Backend benutzten Meldungs-Schlüssel (msg/dump/UserError)."""
    src = Path(messages.__file__).parent
    pattern = re.compile(
        r'(?:\bmsg|\bmsg_dump|\bdump|UserError)\(\s*["\']([A-Za-z0-9]+)["\']'
    )
    keys: set[str] = set()
    for py in src.rglob("*.py"):
        if py.name == "messages.py":
            continue
        keys |= set(pattern.findall(py.read_text(encoding="utf-8")))
    return keys


def test_alle_backend_schluessel_in_strings_de() -> None:
    server = load_strings("strings.de.js")["server"]
    missing = sorted(_backend_keys() - set(server))
    assert not missing, f"Schlüssel fehlen in strings.de.js server: {missing}"
