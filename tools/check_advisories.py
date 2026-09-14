"""Advisory-Check über die Abhängigkeiten (Issue #42, ADR 0080).

Fragt https://api.osv.dev (Open Source Vulnerabilities, Google/OpenSSF)
nach bekannten Schwachstellen für genau die Versionen, die fml ausliefert:
die Pins aus ``requirements.txt`` / ``requirements-dev.txt`` und dazu
alles, was im laufenden venv installiert ist (transitive Pakete wie
starlette/pydantic). Reine Standardbibliothek (``urllib``), kein
pip-audit im Projekt-venv (Projektregel: Standardbibliothek bevorzugen).

Aufruf:
    python tools/check_advisories.py            # Exit 1 bei offener Advisory
    python tools/check_advisories.py --json     # Rohantwort je Paket

``tools/publish.py`` ruft die Prüfung vor jedem Snapshot-Export auf;
``--ignore-advisories`` ist dort der Notausgang.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from importlib import metadata
from pathlib import Path
from typing import Callable, Iterable

OSV_URL = "https://api.osv.dev/v1/querybatch"
TIMEOUT = 20
REQUIREMENTS = ("requirements.txt", "requirements-dev.txt")
_PIN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(==|~=)\s*([A-Za-z0-9.*+!-]+)")


class AdvisoryError(RuntimeError):
    """OSV nicht erreichbar oder Antwort unbrauchbar (offline?)."""


def _installed(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def pinned_packages(root: Path) -> list[tuple[str, str]]:
    """(Name, Version) je Pin. ``==`` nimmt die Zeile wörtlich; ``~=`` ist
    keine feste Version — dann zählt, was im venv installiert ist (fehlt es,
    wird der Pin übersprungen: er ist nicht prüfbar)."""
    out: list[tuple[str, str]] = []
    for filename in REQUIREMENTS:
        path = root / filename
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            m = _PIN.match(line.split("#", 1)[0])
            if not m:
                continue
            name, op, version = m.groups()
            if op == "~=":
                version = _installed(name)
                if version is None:
                    continue
            out.append((name, version))
    return out


# Installer-Werkzeuge des venv: nicht Teil dessen, was fml ausliefert oder
# voraussetzt (der Nutzer installiert mit SEINEM pip) — sonst blockiert ein
# altes lokales pip jeden Export.
TOOLING = frozenset({"pip", "setuptools", "wheel"})


def installed_packages() -> list[tuple[str, str]]:
    """Alle Distributionen des laufenden Interpreters (transitive Deps),
    ohne die Installer-Werkzeuge aus ``TOOLING``."""
    found: dict[str, tuple[str, str]] = {}
    for dist in metadata.distributions():
        name = (dist.metadata["Name"] or "").strip()
        if name and name.lower() not in TOOLING:
            found.setdefault(name.lower(), (name, dist.version))
    return [found[k] for k in sorted(found)]


def _dedupe(packages: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out = []
    for name, version in packages:
        key = (name.lower().replace("_", "-"), version)
        if key not in seen:
            seen.add(key)
            out.append((name, version))
    return out


def query_osv(packages: list[tuple[str, str]], *,
              opener: Callable = urllib.request.urlopen) -> dict[tuple[str, str], list[str]]:
    """Advisory-IDs je (Name, Version) — leere Liste = sauber."""
    if not packages:
        return {}
    body = {"queries": [{"package": {"name": n, "ecosystem": "PyPI"}, "version": v}
                        for n, v in packages]}
    req = urllib.request.Request(OSV_URL, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with opener(req, timeout=TIMEOUT) as resp:
            payload = json.load(resp)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise AdvisoryError(f"OSV not reachable: {exc}") from exc
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or len(results) != len(packages):
        raise AdvisoryError("OSV answer has an unexpected shape")
    out: dict[tuple[str, str], list[str]] = {}
    for pkg, res in zip(packages, results):
        ids = [v.get("id", "?") for v in (res or {}).get("vulns", []) or []]
        out[pkg] = sorted(ids)
    return out


def check_advisories(root: Path, *, include_installed: bool = True,
                     opener: Callable = urllib.request.urlopen) -> list[str]:
    """Zeilen ``name==version: ID, ID`` je betroffenem Paket; leer = sauber.
    Wirft ``AdvisoryError``, wenn OSV nicht antwortet."""
    packages = pinned_packages(root)
    if include_installed:
        packages = packages + installed_packages()
    hits = query_osv(_dedupe(packages), opener=opener)
    return [f"{name}=={version}: {', '.join(ids)}"
            for (name, version), ids in hits.items() if ids]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pins-only", action="store_true",
                        help="only the requirements pins, not the installed venv")
    parser.add_argument("--json", action="store_true", help="print the raw result per package")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    packages = pinned_packages(root)
    if not args.pins_only:
        packages = packages + installed_packages()
    packages = _dedupe(packages)
    try:
        result = query_osv(packages)
    except AdvisoryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({f"{n}=={v}": ids for (n, v), ids in result.items()}, indent=2))
    hits = [(pkg, ids) for pkg, ids in result.items() if ids]
    print(f"{len(packages)} packages checked against OSV, {len(hits)} with open advisories.")
    for (name, version), ids in hits:
        print(f"  - {name}=={version}: {', '.join(ids)}")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
