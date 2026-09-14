"""Advisory-Check über die Pins (Issue #42, ADR 0080): OSV-Abfrage mit
Attrappe statt Netz — Parsing der Pins, Treffer-Zeilen, Offline-Fehler und
der Wächter in tools/publish.py."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ca = _load("check_advisories")


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _opener_with(vulns_by_index):
    """Attrappe für urllib.request.urlopen: merkt sich die Anfrage und
    antwortet je Query mit den angegebenen Advisory-IDs."""
    calls = []

    def opener(req, timeout=None):
        body = json.loads(req.data.decode("utf-8"))
        calls.append(body)
        results = [{"vulns": [{"id": i} for i in vulns_by_index.get(k, [])]}
                   for k in range(len(body["queries"]))]
        return _Response(json.dumps({"results": results}).encode("utf-8"))

    opener.calls = calls
    return opener


def _repo(tmp_path, req="fastapi==0.141.1\nPillow==12.3.0  # kommentar\n",
          dev="pytest~=9.1\n"):
    (tmp_path / "requirements.txt").write_text(req, encoding="utf-8")
    (tmp_path / "requirements-dev.txt").write_text(dev, encoding="utf-8")
    return tmp_path


def test_pins_werden_gelesen_tilde_ueber_installierte_version(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "_installed", lambda name: "9.1.1" if name == "pytest" else None)
    assert ca.pinned_packages(_repo(tmp_path)) == [
        ("fastapi", "0.141.1"), ("Pillow", "12.3.0"), ("pytest", "9.1.1")]


def test_tilde_pin_ohne_installation_wird_uebersprungen(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "_installed", lambda name: None)
    assert ca.pinned_packages(_repo(tmp_path)) == [("fastapi", "0.141.1"), ("Pillow", "12.3.0")]


def test_query_osv_fragt_pypi_und_liefert_ids_je_paket():
    opener = _opener_with({1: ["GHSA-x", "CVE-2026-1"]})
    out = ca.query_osv([("fastapi", "0.141.1"), ("pytest", "8.4.2")], opener=opener)
    assert out == {("fastapi", "0.141.1"): [], ("pytest", "8.4.2"): ["CVE-2026-1", "GHSA-x"]}
    q = opener.calls[0]["queries"]
    assert q[0] == {"package": {"name": "fastapi", "ecosystem": "PyPI"}, "version": "0.141.1"}


def test_check_advisories_meldet_nur_treffer_als_zeilen(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "_installed", lambda name: "8.4.2")
    opener = _opener_with({2: ["PYSEC-2026-1845"]})
    lines = ca.check_advisories(_repo(tmp_path), include_installed=False, opener=opener)
    assert lines == ["pytest==8.4.2: PYSEC-2026-1845"]


def test_check_advisories_sauber_ist_leer(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "_installed", lambda name: "9.1.1")
    assert ca.check_advisories(_repo(tmp_path), include_installed=False,
                               opener=_opener_with({})) == []


def test_offline_ist_fehler_kein_stilles_gruen(tmp_path):
    def opener(req, timeout=None):
        raise OSError("no network")
    with pytest.raises(ca.AdvisoryError):
        ca.check_advisories(_repo(tmp_path), include_installed=False, opener=opener)


def test_unerwartete_antwort_ist_fehler(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "_installed", lambda name: "9.1.1")

    def opener(req, timeout=None):
        return _Response(b'{"results": []}')   # zu wenige Ergebnisse
    with pytest.raises(ca.AdvisoryError):
        ca.check_advisories(_repo(tmp_path), include_installed=False, opener=opener)


def test_installierte_pakete_sind_eindeutig_und_haben_versionen():
    pkgs = ca.installed_packages()
    names = [n.lower() for n, _ in pkgs]
    assert len(names) == len(set(names))
    assert all(v for _, v in pkgs)
    assert "pytest" in names
    assert "pip" not in names, "Installer-Werkzeuge zählen nicht (nicht ausgeliefert)"


def _load_publish():
    # tools/publish.py ist nicht Teil des Public-Snapshots (es trägt die
    # Verbotsliste): dort werden die zwei Export-Tests übersprungen.
    if not (REPO_ROOT / "tools" / "publish.py").is_file():
        pytest.skip("tools/publish.py is not part of the public snapshot")
    return _load("publish")


def test_publish_bricht_bei_advisory_ab_und_ignore_ist_notausgang(monkeypatch, capsys):
    pub = _load_publish()
    monkeypatch.setattr(pub, "_check_manifest", lambda root: [])
    monkeypatch.setattr(pub, "_check_advisories", lambda root: ["pytest==8.4.2: PYSEC-2026-1845"])
    assert pub.main(["--check"]) == 1
    assert "ABBRUCH" in capsys.readouterr().out
    # Notausgang: nur melden, Probelauf läuft weiter (baut den echten Baum).
    assert pub.main(["--check", "--ignore-advisories"]) == 0
    out = capsys.readouterr().out
    assert "WARNUNG" in out and "PYSEC-2026-1845" in out


def test_publish_offline_ist_abbruch(monkeypatch, capsys):
    pub = _load_publish()
    monkeypatch.setattr(pub, "_check_manifest", lambda root: [])

    def boom(root):
        raise ca.AdvisoryError("OSV not reachable")
    monkeypatch.setattr(pub, "_check_advisories", boom)
    assert pub.main(["--check"]) == 1
    assert "nicht möglich" in capsys.readouterr().out
