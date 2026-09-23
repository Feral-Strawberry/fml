"""tools/lock_deps.py (ADR 0082): Direkt-Einträge lesen, Abschluss über die
Plattform-Matrix bilden, Marker vergeben, rendern. PyPI und venv werden
durch Attrappen ersetzt (kein Netz im Test)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("lock_deps", REPO_ROOT / "tools" / "lock_deps.py")
ld = importlib.util.module_from_spec(_spec)
sys.modules["lock_deps"] = ld   # dataclasses brauchen das Modul in sys.modules
_spec.loader.exec_module(ld)

# Kleine Welt: app -> lib (überall), lib -> winonly (nur Windows),
# app -> old (nur Python < 3.11, also nie), app -> shared, lib -> shared
REQUIRES = {
    ("app", "1.0"): ["lib>=2", "old; python_version < '3.11'", "shared", "fancy; extra == 'x'"],
    ("lib", "2.1"): ["winonly; platform_system == 'Windows'", "shared>=1.2"],
    ("winonly", "0.4.6"): [],
    ("shared", "1.5"): [],
    ("shared", "1.0"): [],
}
INSTALLED = {"app": "1.0", "lib": "2.1", "shared": "1.5"}   # winonly fehlt (macOS)
RELEASES = {"winonly": {"0.4.5": [{"yanked": False}], "0.4.6": [{"yanked": False}],
                        "0.5.0b1": [{"yanked": False}]}}


def _fetch(url: str) -> dict:
    parts = url.rstrip("/").split("/")
    if parts[-1] == "json" and len(parts) == 7:           # /pypi/<name>/<version>/json
        name, version = parts[-3], parts[-2]
        return {"urls": [{"packagetype": "bdist_wheel", "digests": {"sha256": f"{name}{version}".ljust(64, "0")[:64]}}],
                "info": {"requires_dist": REQUIRES[(name, version)]}}
    return {"releases": RELEASES[parts[-2]]}


def _resolve(direct, **kw):
    return ld.resolve(direct, ld.Index(fetch=_fetch),
                      installed=lambda n: INSTALLED.get(ld.norm(n)),
                      installed_requires=lambda n, v: None, **kw)


def test_read_direct_inline_und_als_folgekommentar(tmp_path):
    f = tmp_path / "r.txt"
    f.write_text("app==1.0  # direct: src/x.py\n"
                 "lib==2.1 \\\n    --hash=sha256:" + "a" * 64 + "\n    # direct: src/y.py\n    # via app\n"
                 "shared==1.5 \\\n    --hash=sha256:" + "b" * 64 + "\n    # via lib\n", encoding="utf-8")
    direct = ld.read_direct(f)
    assert {k: e.direct for k, e in direct.items()} == {"app": "src/x.py", "lib": "src/y.py"}


def test_abschluss_mit_markern_und_ohne_unpassende_zweige():
    entries = _resolve({"app": ld.Entry("app", "1.0", "src/x.py")})
    assert sorted(entries) == ["app", "lib", "shared", "winonly"]   # kein old, kein fancy
    assert entries["winonly"].marker == 'platform_system == "Windows"'
    assert entries["winonly"].version == "0.4.6"                     # neueste stabile, nicht die Beta
    assert entries["shared"].marker == "" and entries["shared"].via == {"app", "lib"}
    assert all(e.hashes for e in entries.values())


def test_exclude_laesst_bereits_gelockte_pakete_weg():
    entries = _resolve({"app": ld.Entry("app", "1.0", "x")}, exclude={"shared"})
    assert "shared" not in entries


def test_verletzte_versionsgrenze_bricht_ab():
    INSTALLED["shared"] = "1.0"            # lib verlangt shared>=1.2
    try:
        with pytest.raises(SystemExit, match="shared==1.0 violates"):
            _resolve({"app": ld.Entry("app", "1.0", "x")})
    finally:
        INSTALLED["shared"] = "1.5"


def test_render_ist_pip_compile_artig():
    entries = _resolve({"app": ld.Entry("app", "1.0", "src/x.py")})
    text = ld.render(ld.RUNTIME, entries)
    assert "winonly==0.4.6 ; platform_system == \"Windows\" \\\n    --hash=sha256:" in text
    assert "app==1.0 \\\n    --hash=sha256:" in text and "    # direct: src/x.py" in text
    assert "    # via app, lib" in text
