"""Schema-Referenz in der Doku (Issue #147): docs/schema.md und docs/en/schema.md
tragen zwischen zwei Markern einen generierten Block (Mermaid-ER-Diagramm +
Spaltentabellen). Der Helfer tools/schema_doc.py ist kein Paket-Modul, er wird
über den Dateipfad geladen. Nach einer Migration ist diese Suite rot, bis
``python tools/schema_doc.py`` einmal lief."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("schema_doc", REPO_ROOT / "tools" / "schema_doc.py")
sd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sd)


def _schema():
    conn = sd.connect(":memory:")
    try:
        return sd.read_schema(conn)
    finally:
        conn.close()


def test_alle_tabellen_sind_einer_gruppe_zugeordnet():
    schema = _schema()
    grouped = {t for _, _, ts in sd.GROUPS for t in ts}
    assert set(schema["tables"]) == grouped, (
        "neue/entfernte Tabelle: GROUPS in tools/schema_doc.py nachziehen: "
        f"{sorted(set(schema['tables']) ^ grouped)}")


def test_schattentabellen_und_interna_bleiben_draussen():
    schema = _schema()
    assert not any(n.startswith("search_index_") or n.startswith("sqlite_") for n in schema["tables"])
    assert schema["tables"]["search_index"]["fts"]["tokenizer"] == "unicode61"
    assert schema["tables"]["search_index"]["fts"]["unindexed"] == ["file_hash"]


def test_mermaid_enthaelt_fremdschluessel_und_logische_verweise():
    text = sd.mermaid(_schema())
    assert text.startswith("```mermaid\nerDiagram")
    assert '  items ||--o{ file_locations : "file_hash"' in text
    assert '  items ||--o| annotations : "file_hash"' in text        # 1:0..1 über den PK
    assert '  tags ||--o{ item_tags : "tag_id"' in text
    assert '  items |o..o| blocked_hashes : "file_hash"' in text     # bewusst ohne FK
    assert "    text file_hash PK, FK" in text                       # item_tags


def test_doku_ist_aktuell():
    """DoD-Regel wie beim Übersetzungs-Manifest: veraltete Schema-Referenz
    macht die Suite rot — ``python tools/schema_doc.py`` laufen lassen."""
    for lang, path in sd.TARGETS.items():
        text = path.read_text(encoding="utf-8")
        block = sd.current_block(text)
        assert block is not None, f"{path}: Marker fehlen"
        assert block == sd.generate(lang), (
            f"{path.relative_to(REPO_ROOT)} ist veraltet: python tools/schema_doc.py")


def test_check_modus_meldet_veraltet(tmp_path, monkeypatch):
    de = tmp_path / "schema.md"; en = tmp_path / "schema.en.md"
    de.write_text(f"Kopf\n{sd.START}\nalt\n{sd.END}\nFuß\n", encoding="utf-8")
    en.write_text(f"Head\n{sd.START}\nold\n{sd.END}\nFoot\n", encoding="utf-8")
    monkeypatch.setattr(sd, "TARGETS", {"de": de, "en": en})
    monkeypatch.setattr(sd, "REPO_ROOT", tmp_path)
    assert sd.main(["--check"]) == 1
    assert sd.main([]) == 0
    assert de.read_text(encoding="utf-8").startswith("Kopf\n" + sd.START + "\n```mermaid")
    assert de.read_text(encoding="utf-8").endswith(sd.END + "\nFuß\n")
    assert sd.main(["--check"]) == 0
