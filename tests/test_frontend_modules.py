"""Node-Unit-Tests der JavaScript-Module aus pytest heraus (ADR 0064, Issue #22).

Die ES-Module unter src/feral/web/static/js/ laufen in Node gegen einen
winzigen DOM-Stub (tests/js/dom.mjs) und eine fetch-Attrappe — ohne npm,
ohne Browser. Jede Datei tests/js/*.test.mjs ist ein eigener Node-Prozess
(Module halten Zustand auf Modulebene; frische Prozesse statt Aufräumen).
Fehlt Node auf dem Rechner, werden diese Tests ÜBERSPRUNGEN (sichtbar in
der pytest-Zusammenfassung) — die Python-Suite bleibt davon unberührt.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS_DIR = ROOT / "tests" / "js"
SETUP = JS_DIR / "setup.mjs"
MAIN_JS = ROOT / "src" / "feral" / "web" / "static" / "js" / "main.js"
TEST_FILES = sorted(JS_DIR.glob("*.test.mjs"))
MIN_NODE = (20, 6)   # module.register() — Loader-Hook für ./main.js → bus.mjs

NODE = shutil.which("node")


def _node_version() -> tuple[int, ...] | None:
    if not NODE:
        return None
    out = subprocess.run([NODE, "--version"], capture_output=True, text=True, check=False)
    m = re.match(r"v(\d+)\.(\d+)\.(\d+)", out.stdout.strip())
    return tuple(int(x) for x in m.groups()) if m else None


def _require_node() -> None:
    if NODE is None:
        pytest.skip("node nicht installiert — Frontend-Modultests übersprungen (docs/tests.md)")
    version = _node_version()
    if version is None or version[:2] < MIN_NODE:
        pytest.skip(f"node >= {MIN_NODE[0]}.{MIN_NODE[1]} nötig, gefunden: {version}")


def test_js_suite_present() -> None:
    """Die vier Rauchtest-Bereiche aus Issue #22 existieren als Node-Suiten."""
    names = {p.name for p in TEST_FILES}
    assert {"overlays.test.mjs", "gallery.test.mjs", "picker.test.mjs", "dom.test.mjs"} <= names


def test_bus_stub_matches_main_js() -> None:
    """tests/js/bus.mjs ersetzt main.js im Loader — die drei Bus-Exporte müssen
    wortgleich mit dem Original bleiben, sonst testen wir einen anderen Bus."""
    main = MAIN_JS.read_text(encoding="utf-8")
    stub = (JS_DIR / "bus.mjs").read_text(encoding="utf-8")
    for line in (
        "export const bus = new EventTarget();",
        "export const emit = (type, detail) => bus.dispatchEvent(new CustomEvent(type, { detail }));",
        "export const on = (type, fn) => {",
        "  const h = (e) => fn(e.detail);",
        "  bus.addEventListener(type, h);",
        "  return h;",
    ):
        assert line in main, f"main.js: Bus-Zeile verändert: {line}"
        assert line in stub, f"bus.mjs hinkt main.js hinterher: {line}"


@pytest.mark.parametrize("test_file", TEST_FILES, ids=lambda p: p.name.removesuffix(".test.mjs"))
def test_frontend_module(test_file: Path) -> None:
    """Eine Node-Testdatei = ein Prozess; Exit-Code 0 heißt: alle Tests grün
    (erwartet-rote Tests zählen als grün, bis ihr Issue behoben ist)."""
    _require_node()
    proc = subprocess.run(
        [NODE, "--import", SETUP.as_uri(), str(test_file)],
        # Node schreibt UTF-8 (✔/✖, Umlaute); ohne encoding= nähme Windows
        # die Konsolen-Codepage und die Ausgabe würde unlesbar.
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT, timeout=120, check=False,
    )
    if proc.returncode != 0:
        pytest.fail(
            f"Node-Tests rot: {test_file.name}\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}",
            pytrace=False,
        )
