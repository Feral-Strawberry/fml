"""Database schema reference for the docs, generated from the real schema (Issue #147).

Migrates a fresh in-memory database, reads ``sqlite_master`` and the
``PRAGMA table_info`` / ``foreign_key_list`` of every table and renders a
Mermaid ER diagram plus one column table per table. The result is written
between the markers ``<!-- schema:start -->`` / ``<!-- schema:ende -->`` in
``docs/schema.md`` (German) and ``docs/en/schema.md`` (English); the prose
around the markers is hand-written. ``tests/test_schema_doc.py`` compares
the files with a fresh generation, so a migration turns the suite red until
this script has run once (same pattern as the translation manifest).

    python tools/schema_doc.py           # rewrite both files
    python tools/schema_doc.py --check   # exit 1 when a file is stale

Standard library only.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from feral.db.database import connect  # noqa: E402

START = "<!-- schema:start -->"
END = "<!-- schema:ende -->"

TARGETS = {"de": REPO_ROOT / "docs" / "schema.md", "en": REPO_ROOT / "docs" / "en" / "schema.md"}

# Groups in reading order; every table must be assigned (the test checks).
GROUPS = [
    ("hub", {"de": "Hub: Identität und Fundorte", "en": "Hub: identity and locations"},
     ["items", "file_locations"]),
    ("layer1", {"de": "Schicht 1: Roh-Extraktion", "en": "Layer 1: raw extraction"},
     ["raw_metadata"]),
    ("layer2", {"de": "Schicht 2: Interpretation", "en": "Layer 2: interpretation"},
     ["interpreted_metadata"]),
    ("manual", {"de": "Manuelle Schicht", "en": "Manual layer"},
     ["annotations", "tags", "item_tags", "time_comments", "covers", "smart_folders"]),
    ("rankings", {"de": "Ranking-Modul", "en": "Ranking module"},
     ["rankings", "ranking_duels", "ranking_scores"]),
    ("fts", {"de": "Volltextindex", "en": "Full-text index"},
     ["search_index"]),
    ("ops", {"de": "Betrieb", "en": "Operations"},
     ["blocked_hashes", "import_log", "scan_memory", "scan_issues", "app_state"]),
]

# Relationships that are deliberate references WITHOUT a foreign key: these
# rows must survive an item that leaves the catalog (block list, import log,
# watch memory, duel log). Rendered as dotted lines.
LOGICAL = [
    ("items", "ranking_scores", "|o..o{", "file_hash"),
    ("items", "ranking_duels", "|o..o{", "winner / loser"),
    ("items", "search_index", "|o..o|", "file_hash"),
    ("items", "blocked_hashes", "|o..o|", "file_hash"),
    ("items", "import_log", "|o..o{", "file_hash"),
    ("items", "scan_memory", "|o..o{", "file_hash"),
]

WORDS = {
    "de": {"col": "Spalte", "type": "Typ", "key": "Schlüssel", "nn": "Pflicht", "dflt": "Standard",
           "idx": "Indexe", "pk": "PK", "fk": "FK →", "fts": "FTS5-Tabelle (virtuell), Tokenizer",
           "unindexed": "nicht indiziert", "yes": "ja", "none": "keine"},
    "en": {"col": "Column", "type": "Type", "key": "Key", "nn": "Required", "dflt": "Default",
           "idx": "Indexes", "pk": "PK", "fk": "FK →", "fts": "FTS5 table (virtual), tokenizer",
           "unindexed": "unindexed", "yes": "yes", "none": "none"},
}


def read_schema(conn: sqlite3.Connection) -> dict:
    """Tables (without SQLite internals and FTS shadow tables) with columns,
    foreign keys, indexes and the FTS5 definition."""
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    fts = {r[0]: r[1] for r in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND sql LIKE 'CREATE VIRTUAL TABLE%'")}
    shadow = {n for n in names if any(n.startswith(f + "_") for f in fts)}
    tables: dict[str, dict] = {}
    for name in names:
        if name in shadow:
            continue
        cols = [{"name": c[1], "type": (c[2] or "").lower(), "notnull": bool(c[3]),
                 "default": c[4], "pk": bool(c[5])}
                for c in conn.execute(f"PRAGMA table_info('{name}')")]
        fks = {f[3]: (f[2], f[4]) for f in conn.execute(f"PRAGMA foreign_key_list('{name}')")}
        indexes = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL "
            "AND tbl_name = ? ORDER BY name", (name,))]
        tables[name] = {"columns": cols, "fks": fks, "indexes": indexes,
                        "fts": _fts_info(fts.get(name))}
    return {"version": conn.execute("PRAGMA user_version").fetchone()[0], "tables": tables}


def _fts_info(sql: str | None) -> dict | None:
    if not sql:
        return None
    body = sql[sql.index("(") + 1: sql.rindex(")")]
    unindexed, tokenizer = [], ""
    for raw in body.split("\n"):
        line = raw.split("--")[0].strip().rstrip(",")
        if not line:
            continue
        if line.startswith("tokenize"):
            tokenizer = line.split("=", 1)[1].strip().strip("'\"")
        elif line.endswith("UNINDEXED"):
            unindexed.append(line.split()[0])
    return {"unindexed": unindexed, "tokenizer": tokenizer}


def mermaid(schema: dict) -> str:
    lines = ["```mermaid", "erDiagram"]
    ordered = [t for _, _, ts in GROUPS for t in ts if t in schema["tables"]]
    for name in ordered:
        t = schema["tables"][name]
        lines.append(f"  {name} {{")
        for c in t["columns"]:
            keys = [k for k, on in (("PK", c["pk"]), ("FK", c["name"] in t["fks"])) if on]
            key = (" " + ", ".join(keys)) if keys else ""
            lines.append(f"    {c['type'] or 'any'} {c['name']}{key}")
        lines.append("  }")
    for name in ordered:
        t = schema["tables"][name]
        for col, (parent, _) in t["fks"].items():
            one_to_one = any(c["name"] == col and c["pk"] for c in t["columns"]) and \
                sum(c["pk"] for c in t["columns"]) == 1
            card = "||--o|" if one_to_one else "||--o{"
            lines.append(f'  {parent} {card} {name} : "{col}"')
    for parent, child, card, label in LOGICAL:
        if child in schema["tables"]:
            lines.append(f'  {parent} {card} {child} : "{label}"')
    lines.append("```")
    return "\n".join(lines)


def column_tables(schema: dict, lang: str) -> str:
    w = WORDS[lang]
    out: list[str] = []
    for _, titles, names in GROUPS:
        out.append(f"### {titles[lang]}\n")
        for name in names:
            if name not in schema["tables"]:
                continue
            t = schema["tables"][name]
            pk = [c["name"] for c in t["columns"] if c["pk"]]
            head = f"#### `{name}`"
            if t["fts"]:
                head += f" · {w['fts']} `{t['fts']['tokenizer']}`"
            elif pk:
                head += f" · {w['pk']} `{', '.join(pk)}`"
            out.append(head + "\n")
            out.append(f"| {w['col']} | {w['type']} | {w['key']} | {w['nn']} | {w['dflt']} |")
            out.append("| --- | --- | --- | --- | --- |")
            for c in t["columns"]:
                keys = []
                if c["pk"]:
                    keys.append(w["pk"])
                if c["name"] in t["fks"]:
                    parent, pcol = t["fks"][c["name"]]
                    keys.append(f"{w['fk']} `{parent}.{pcol}`")
                if t["fts"] and c["name"] in t["fts"]["unindexed"]:
                    keys.append(w["unindexed"])
                dflt = "" if c["default"] is None else f"`{c['default']}`"
                out.append(f"| `{c['name']}` | {c['type'] or ''} | {' · '.join(keys)} | "
                           f"{w['yes'] if c['notnull'] else ''} | {dflt} |")
            idx = ", ".join(f"`{i}`" for i in t["indexes"]) or w["none"]
            out.append(f"\n{w['idx']}: {idx}\n")
    return "\n".join(out).rstrip() + "\n"


def render(schema: dict, lang: str) -> str:
    return f"{START}\n{mermaid(schema)}\n\n{column_tables(schema, lang)}{END}"


def generate(lang: str) -> str:
    conn = connect(":memory:")
    try:
        return render(read_schema(conn), lang)
    finally:
        conn.close()


def current_block(text: str) -> str | None:
    a, b = text.find(START), text.find(END)
    if a < 0 or b < 0 or b < a:
        return None
    return text[a: b + len(END)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate the schema reference between the markers of docs/schema.md and docs/en/schema.md.")
    ap.add_argument("--check", action="store_true", help="only report stale files, exit 1 if any")
    args = ap.parse_args(argv)
    stale = 0
    for lang, path in TARGETS.items():
        text = path.read_text(encoding="utf-8")
        old = current_block(text)
        if old is None:
            print(f"{path.relative_to(REPO_ROOT)}: markers {START} / {END} missing")
            return 2
        new = generate(lang)
        if old == new:
            print(f"{path.relative_to(REPO_ROOT)}: up to date")
            continue
        stale += 1
        if args.check:
            print(f"{path.relative_to(REPO_ROOT)}: STALE — run python tools/schema_doc.py")
        else:
            path.write_text(text.replace(old, new), encoding="utf-8")
            print(f"{path.relative_to(REPO_ROOT)}: rewritten")
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    sys.exit(main())
