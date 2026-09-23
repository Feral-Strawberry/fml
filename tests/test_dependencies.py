"""Wächter: keine nicht benannte Abhängigkeit (ADR 0082).

requirements.txt / requirements-dev.txt sind ein vollständiger Lock mit
Hashes. Diese Tests machen die Suite rot, wenn
- Code ein Fremdpaket importiert, das keine direkte Abhängigkeit ist
  (so wäre der ungepinnte starlette-Import aufgefallen),
- ein Lock-Eintrag keine feste Version oder keinen Hash hat,
- ein gelocktes Paket nicht in DEPENDENCIES.md dokumentiert ist,
- das installierte venv etwas enthält, das nicht im Lock steht, oder eine
  andere Version als gepinnt,
- die Startskripte am Hash-Prüfmodus vorbei installieren.
"""

from __future__ import annotations

import ast
import re
import sys
from importlib import metadata
from pathlib import Path

from pip._vendor.packaging.markers import Marker

from feral.web import admin

ROOT = Path(__file__).resolve().parents[1]
LOCKS = ("requirements.txt", "requirements-dev.txt")
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)\s*(?:;\s*([^\\]+?))?\s*\\?\s*$")
# Das Projekt selbst (ältere venvs: editable-Installation) ist keine Abhängigkeit.
SELF = {"feral-media-library"}


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_lock(path: Path) -> list[dict]:
    """Einträge ``{name, version, marker, hashes, direct}`` einer Lock-Datei."""
    entries: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("-r "):
            continue
        if line.startswith("--hash=sha256:"):
            entries[-1]["hashes"].append(line.split(":", 1)[1].rstrip(" \\"))
            continue
        if line.startswith("#"):
            if entries and line.startswith("# direct:"):
                entries[-1]["direct"] = True
            continue
        m = _PIN.match(line)
        assert m, f"{path.name}: keine exakte Pin-Zeile: {line!r}"
        entries.append({"name": m.group(1), "version": m.group(2),
                        "marker": (m.group(3) or "").strip(), "hashes": [], "direct": False})
    return entries


def _all_entries() -> list[dict]:
    return [e for f in LOCKS for e in parse_lock(ROOT / f)]


# Projekteigene Top-Level-Namen: das Test-Paket und seine Hilfsmodule.
LOCAL = {"tests"} | {p.stem for p in (ROOT / "tests").glob("*.py")}


def _third_party_imports(folder: Path) -> dict[str, str]:
    """Top-Level-Modul -> erste Fundstelle, für alle Nicht-Stdlib-Importe."""
    found: dict[str, str] = {}
    for p in sorted(folder.rglob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for n in names:
                top = n.split(".")[0]
                if top not in sys.stdlib_module_names and top not in LOCAL | {"feral", "__future__"}:
                    found.setdefault(top, str(p.relative_to(ROOT)))
    return found


def test_jeder_eintrag_ist_exakt_gepinnt_und_gehasht():
    for f in LOCKS:
        entries = parse_lock(ROOT / f)
        assert entries, f
        for e in entries:
            assert e["hashes"], f"{f}: {e['name']} ohne --hash"
            assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in e["hashes"]), e["name"]
    names = [norm(e["name"]) for e in _all_entries()]
    assert len(names) == len(set(names)), "Paket doppelt im Lock"


def test_fremd_importe_sind_direkte_abhaengigkeiten():
    """src/feral und tests/ importieren nur, was als ``# direct`` im Lock
    steht. Ein Import über ein transitives Paket (starlette war der Fall)
    macht die Suite rot."""
    direct = {norm(e["name"]) for e in _all_entries() if e["direct"]}
    dists = metadata.packages_distributions()
    missing = []
    for folder in (ROOT / "src" / "feral", ROOT / "tests"):
        for module, where in _third_party_imports(folder).items():
            owners = {norm(d) for d in dists.get(module, [])}
            if not owners:
                missing.append(f"{module} ({where}): keinem installierten Paket zuzuordnen")
            elif not owners & direct:
                missing.append(f"{module} ({where}) gehört zu {sorted(owners)}, "
                               "das ist keine direkte Abhängigkeit")
    assert not missing, "\n".join(missing)


def test_jedes_gelockte_paket_ist_dokumentiert():
    doc = norm((ROOT / "DEPENDENCIES.md").read_text(encoding="utf-8"))
    undocumented = [e["name"] for e in _all_entries() if norm(e["name"]) not in doc]
    assert not undocumented, f"in DEPENDENCIES.md nachtragen: {undocumented}"


def test_installierte_umgebung_entspricht_dem_lock():
    """Nichts installiert, was nicht im Lock steht; alles für diese Plattform
    Gelockte ist in genau der gepinnten Version da."""
    lock = {norm(e["name"]): e for e in _all_entries()}
    installed = {norm(d.metadata["Name"]): d.version for d in metadata.distributions()}
    unnamed = sorted(n for n in installed if n not in lock and n not in SELF)
    assert not unnamed, f"installiert, aber nicht im Lock: {unnamed}"
    for name, e in lock.items():
        if e["marker"] and not Marker(e["marker"]).evaluate():
            continue
        assert installed.get(name) == e["version"], (
            f"{e['name']}: installiert {installed.get(name)}, gepinnt {e['version']} "
            "(python -m pip install --require-hashes -r requirements-dev.txt)")


def test_admin_zeigt_die_direkten_laufzeit_pakete():
    direct = [norm(e["name"]) for e in parse_lock(ROOT / "requirements.txt")
              if e["direct"] and norm(e["name"]) != "pip"]
    assert sorted(direct) == sorted(norm(n) for n in admin.RUNTIME_PACKAGES)


def test_startskripte_installieren_nur_den_lock():
    for name in ("start.sh", "start.bat"):
        text = (ROOT / name).read_text(encoding="utf-8")
        installs = [l for l in text.splitlines() if "pip install" in l and not l.strip().startswith(("#", "REM"))]
        assert installs, name
        for line in installs:
            assert "--require-hashes" in line and "--only-binary=:all:" in line, (name, line)
            assert "-e ." not in line and "--upgrade" not in line, (name, line)
