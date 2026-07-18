"""Rückwirkende Interpretation:  python -m feral.interpret --db ./feral.sqlite"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from ..db import connect
from . import comfyui, loras
from .registry import PARSERS, interpret_items
from .reparse import ReparseReport, raw_items_for, reparse_database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m feral.interpret",
        description=(
            "Lässt alle Schicht-2-Parser rückwirkend über die gespeicherten "
            "Roh-Metadaten laufen (kein Datei-Scan nötig)."
        ),
    )
    parser.add_argument(
        "--db",
        default="./feral.sqlite",
        help="Pfad zur SQLite-Datei (Standard: ./feral.sqlite)",
    )
    parser.add_argument("--quiet", action="store_true", help="keine Fortschrittsausgabe")
    parser.add_argument(
        "--lora-report",
        action="store_true",
        help=(
            "Nur Diagnose (schreibt nichts): Bei welchen Items steckt »lora« "
            "in den Roh-Blobs, ohne dass die Parser ein lora-Feld liefern? "
            "Listet die betroffenen Node-Typen — Grundlage für Parser-Ausbau."
        ),
    )
    parser.add_argument(
        "--prompt-report",
        action="store_true",
        help=(
            "Nur Diagnose (schreibt nichts): ComfyUI-Items OHNE erkannten "
            "prompt, klassifiziert nach Ursache (kein prompt-Blob / JSON "
            "kaputt / Text an unbekannten Knoten / Graph unter unerwartetem "
            "Keyword). Listet die textführenden Node-Typen samt Input-Namen."
        ),
    )
    args = parser.parse_args(argv)

    if args.lora_report or args.prompt_report:
        conn = connect(args.db)
        try:
            if args.lora_report:
                return _lora_report(conn)
            return _prompt_report(conn)
        finally:
            conn.close()

    names = ", ".join(f"{p.NAME} v{p.VERSION}" for p in PARSERS)
    print(f"Parser: {names}")

    def progress(report: ReparseReport) -> None:
        if not args.quiet and report.items_total % 1000 == 0:
            print(f"  … {report.items_total} Items", file=sys.stderr)

    conn = connect(args.db)
    try:
        report = reparse_database(conn, progress=progress)
    finally:
        conn.close()

    print("\nInterpretation abgeschlossen.")
    print(report.summary())
    return 0


def _lora_report(conn) -> int:
    """Abdeckungs-Diagnose: »lora« im Roh-Blob vs. erkanntes lora-Feld.

    Läuft rein lesend in-memory (schreibt NICHTS in die DB) und nutzt die
    aktuellen Parser — unabhängig davon, was gerade in
    ``interpreted_metadata`` steht. Ausgabe ist zum Einsenden gedacht.
    """
    hashes = [
        row[0]
        for row in conn.execute(
            """SELECT DISTINCT file_hash FROM raw_metadata
               WHERE value_text IS NOT NULL
                 AND LOWER(value_text) LIKE '%lora%'"""
        ).fetchall()
    ]
    print(f"Items mit »lora« irgendwo in den Roh-Blobs: {len(hashes)}")

    missed_nodes: Counter[str] = Counter()
    missed_keys: dict[str, set[str]] = {}
    missed_samples: dict[str, str] = {}
    inactive_nodes: Counter[str] = Counter()  # Bypass/Mute im workflow-Blob
    note_nodes = 0                            # Notizzettel, die »lora« erwähnen
    missed_a1111 = 0
    a1111_snippets: list[str] = []
    covered = 0
    examples: list[str] = []
    for index, file_hash in enumerate(hashes, start=1):
        items = raw_items_for(conn, file_hash)
        found = any(
            f.field == "lora"
            for interpretation in interpret_items(items)
            for f in interpretation.fields
        )
        if found:
            covered += 1
            continue
        if len(examples) < 10:
            examples.append(file_hash)
        for item in items:
            if not item.text or "lora" not in item.text.lower():
                continue
            if item.keyword == "parameters" and "<lora:" in item.text.lower():
                missed_a1111 += 1
                if len(a1111_snippets) < 3:
                    pos = item.text.lower().find("<lora:")
                    a1111_snippets.append(item.text[max(0, pos - 40): pos + 80])
                continue
            for node_type, keys, sample, state in _lora_node_types(item.text):
                if state == "note":
                    note_nodes += 1
                elif state in ("inaktiv", "leer"):
                    inactive_nodes[f"{node_type} ({state})"] += 1
                else:
                    missed_nodes[node_type] += 1
                    missed_keys.setdefault(node_type, set()).update(keys)
                    if sample and node_type not in missed_samples:
                        missed_samples[node_type] = sample
        if index % 1000 == 0:
            print(f"  … {index}/{len(hashes)} geprüft", file=sys.stderr)

    print(f"  davon liefern die Parser ein lora-Feld: {covered}")
    print(f"  davon OHNE lora-Feld: {len(hashes) - covered}")
    if missed_a1111:
        print(f"\nA1111-Infotexte mit <lora:>-Tag, aber ohne Feld: {missed_a1111}")
        for snippet in a1111_snippets:
            print(f"  … {snippet!r}")
    if missed_nodes:
        print("\nAKTIVE Node-Typen mit »lora« in nicht abgedeckten Items:")
        for node_type, count in missed_nodes.most_common(40):
            keys = ", ".join(sorted(missed_keys.get(node_type, set()))) or "–"
            print(f"  {node_type}  ·  {count}×  ·  [{keys}]")
            if node_type in missed_samples:
                print(f"    Beispielwerte: {missed_samples[node_type]}")
    if inactive_nodes:
        print("\nUnkritische LoRA-Knoten (»kein Feld« ist hier korrekt —"
              " leer = keine aktiven Slots, inaktiv = Bypass/Mute):")
        for node_type, count in inactive_nodes.most_common(10):
            print(f"  {node_type}  ·  {count}×")
    if note_nodes:
        print(f"\nNotiz-Knoten (Note/MarkdownNote), die »lora« nur im Text erwähnen: {note_nodes}× — Rauschen, kein Handlungsbedarf.")
    if examples:
        print("\nBeispiel-Hashes (für /api/item/<hash> bzw. Suche):")
        for h in examples:
            print(f"  {h}")
    if len(hashes) - covered == 0:
        print("\nAlles abgedeckt — kein Handlungsbedarf.")
    return 0


def _prompt_report(conn) -> int:
    """Prompt-Diagnose (Feral Strawberrys Krea-2-Befund, 2026-07-09: gleiche Workflows,
    mal mit, mal ohne erkannten Prompt): ComfyUI-Items ohne prompt-Feld nach
    Ursache klassifizieren. Rein lesend, nutzt die aktuellen Parser.

    Kategorien:
    - ``nur-workflow``      kein prompt-Blob eingebettet (nur der UI-Graph) —
                            der Saver hat den API-Graphen nicht mitgeschrieben
    - ``json-kaputt``       prompt-/workflow-Blob ist kein parsebares JSON
    - ``text-unerkannt``    Graph parsebar, aber der Text hängt an Knoten/
                            Inputs, die der Parser nicht kennt (werden gelistet)
    - ``fremdes-keyword``   ein Graph steckt in einem Roh-Eintrag mit anderem
                            Keyword (z. B. EXIF-Feld statt PNG-Chunk)
    """
    hashes = [
        row[0]
        for row in conn.execute(
            """SELECT DISTINCT file_hash FROM raw_metadata
               WHERE (LOWER(keyword) IN ('prompt', 'workflow')
                      AND value_text IS NOT NULL)
                  OR (value_text LIKE '%class_type%')"""
        ).fetchall()
    ]
    print(f"ComfyUI-verdächtige Items (prompt-/workflow-Blob oder Graph-JSON): {len(hashes)}")

    covered = 0
    categories: Counter[str] = Counter()
    category_examples: dict[str, list[str]] = {}
    text_nodes: Counter[str] = Counter()      # textführende (Node-Typ · Input)-Paare
    text_samples: dict[str, str] = {}
    foreign_keywords: Counter[str] = Counter()
    for index, file_hash in enumerate(hashes, start=1):
        items = raw_items_for(conn, file_hash)
        found = any(
            f.field == "prompt" and f.value.strip()
            for interpretation in interpret_items(items)
            for f in interpretation.fields
        )
        if found:
            covered += 1
            continue

        prompt_text = next(
            (i.text for i in items
             if i.keyword and i.keyword.lower() == "prompt" and i.text), None)
        workflow_text = next(
            (i.text for i in items
             if i.keyword and i.keyword.lower() == "workflow" and i.text), None)

        if prompt_text is not None:
            graph = _try_json(prompt_text)
            if not (isinstance(graph, dict)
                    and any(isinstance(n, dict) and "class_type" in n
                            for n in graph.values())):
                category = "json-kaputt"
            else:
                category = "text-unerkannt"
                for label, sample in _prose_nodes_prompt(graph):
                    text_nodes[label] += 1
                    text_samples.setdefault(label, sample)
        elif workflow_text is not None:
            graph = _try_json(workflow_text)
            if graph is None:
                category = "json-kaputt"
            else:
                category = "nur-workflow"
                for label, sample in _prose_nodes_workflow(graph):
                    text_nodes[label] += 1
                    text_samples.setdefault(label, sample)
        else:
            # Graph-JSON unter fremdem Keyword (Auswahl traf über class_type).
            category = "fremdes-keyword"
            for item in items:
                if item.text and "class_type" in item.text:
                    foreign_keywords[f"{item.source} · {item.keyword or '?'}"] += 1
        categories[category] += 1
        category_examples.setdefault(category, [])
        if len(category_examples[category]) < 8:
            category_examples[category].append(file_hash)
        if index % 1000 == 0:
            print(f"  … {index}/{len(hashes)} geprüft", file=sys.stderr)

    print(f"  davon mit erkanntem prompt-Feld: {covered}")
    print(f"  davon OHNE prompt: {len(hashes) - covered}")
    for category, count in categories.most_common():
        print(f"\n[{category}] {count}×")
        for h in category_examples.get(category, []):
            print(f"  {h}")
    if text_nodes:
        print("\nTextführende Knoten in den Fehlfällen (Node-Typ · Input) —"
              " Kandidaten für den nächsten Parser-Ausbau:")
        for label, count in text_nodes.most_common(30):
            print(f"  {label}  ·  {count}×")
            if label in text_samples:
                print(f"    Beispieltext: {text_samples[label]!r}")
    if foreign_keywords:
        print("\nGraph-JSON unter fremdem Keyword (Quelle · Keyword):")
        for label, count in foreign_keywords.most_common(10):
            print(f"  {label}  ·  {count}×")
    if len(hashes) - covered == 0:
        print("\nAlles abgedeckt — kein Handlungsbedarf.")
    return 0


def _try_json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None


def _looks_like_prose(value) -> bool:
    """Grober Prosa-Filter: mehrwortiger Text, kein JSON/Dateiname/BBOX."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    return (len(text) >= 15 and " " in text
            and not text.startswith(("{", "["))
            and not loras.looks_like_model_file(text))


def _prose_nodes_prompt(graph: dict) -> list[tuple[str, str]]:
    """(«class_type · input», Beispieltext) aller Prosa-Strings im API-Graphen."""
    out: list[tuple[str, str]] = []
    for node in graph.values():
        if not (isinstance(node, dict) and isinstance(node.get("inputs"), dict)):
            continue
        for key, value in node["inputs"].items():
            if _looks_like_prose(value):
                out.append((f"{node.get('class_type', '?')} · {key}", value[:120]))
    return out


def _prose_nodes_workflow(graph) -> list[tuple[str, str]]:
    """Wie oben für den UI-Graphen (widgets_values sind positionslos)."""
    out: list[tuple[str, str]] = []
    for nodes in comfyui._workflow_node_lists(graph):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            state = " (inaktiv)" if node.get("mode") in (2, 4) else ""
            node_type = str(node.get("type", "?"))
            if node_type.lower() in _NOTE_TYPES:
                continue
            widgets = node.get("widgets_values")
            for widget in widgets if isinstance(widgets, list) else []:
                if _looks_like_prose(widget):
                    out.append((f"workflow:{node_type}{state}", widget[:120]))
    return out


_NOTE_TYPES = {"note", "markdownnote"}


def _lora_node_types(text: str) -> list[tuple[str, list[str], str, str]]:
    """(Node-Typ, lora-Input-Schlüssel, Beispielwerte, Status) aller Knoten
    eines JSON-Blobs, die irgendwo »lora« enthalten — für prompt- (API) und
    workflow-Blobs (UI, inkl. Subgraphen). Status: "aktiv" | "inaktiv"
    (Bypass/Mute) | "note" (Notizzettel)."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    out: list[tuple[str, list[str], str, str]] = []
    if isinstance(data.get("nodes"), list):  # workflow-Blob (UI-Graph)
        node_lists = [data["nodes"]]
        definitions = data.get("definitions")
        if isinstance(definitions, dict) and isinstance(definitions.get("subgraphs"), list):
            for sub in definitions["subgraphs"]:
                if isinstance(sub, dict) and isinstance(sub.get("nodes"), list):
                    node_lists.append(sub["nodes"])
        for nodes in node_lists:
            for node in nodes:
                if not (isinstance(node, dict) and "lora" in json.dumps(node).lower()):
                    continue
                node_type = str(node.get("type", "?"))
                if node_type.lower() in _NOTE_TYPES:
                    state = "note"
                elif node.get("mode") in (2, 4):
                    state = "inaktiv"
                elif not _workflow_node_has_active_lora(node):
                    state = "leer"
                else:
                    state = "aktiv"
                sample = json.dumps(node.get("widgets_values"), ensure_ascii=False)[:160]
                out.append((f"workflow:{node_type}", [], sample, state))
    else:  # prompt-Blob (API-Graph)
        for node in data.values():
            if not (isinstance(node, dict) and "class_type" in node):
                continue
            if "lora" not in json.dumps(node).lower():
                continue
            inputs = node.get("inputs")
            keys: list[str] = []
            sample = ""
            state = "aktiv"
            if isinstance(inputs, dict):
                keys = sorted(k for k in inputs if "lora" in k.lower())
                sample = json.dumps(
                    {k: inputs[k] for k in keys}, ensure_ascii=False
                )[:160]
                if not _prompt_node_has_active_lora(inputs):
                    state = "leer"
            out.append((str(node["class_type"]), keys, sample, state))
    return out


def _prompt_node_has_active_lora(inputs: dict) -> bool:
    """Ob ein API-Graph-Knoten einen AKTIVEN LoRA-Namen trägt, den ein Parser
    hätte finden müssen — leere Power-Loader (nur Header + »Add Lora«) und
    deaktivierte Slots melden sonst falschen Alarm."""
    for key, value in inputs.items():
        key_lower = key.lower()
        if isinstance(value, dict):
            name = value.get("lora") or value.get("lora_name") or value.get("content")
            if (isinstance(name, str) and loras.is_real(name)
                    and comfyui._slot_on(value)):
                return True
        elif isinstance(value, str) and "lora" in key_lower:
            if (loras.is_real(value)
                    and (loras.looks_like_model_file(value)
                         or comfyui._LORA_STRING_KEY.match(key_lower))
                    and comfyui._stack_slot_enabled(inputs, key_lower)):
                return True
        elif isinstance(value, list) and "lora" in key_lower and len(value) == 2:
            return True  # Link — könnte einen Namen halten, lieber melden
    return False


def _workflow_node_has_active_lora(node: dict) -> bool:
    """Wie oben, für UI-Graph-Knoten (widgets_values)."""
    widgets = node.get("widgets_values")
    if not isinstance(widgets, list):
        return False
    node_type = str(node.get("type", "")).lower()
    for widget in widgets:
        if isinstance(widget, dict):
            name = widget.get("lora")
            if (isinstance(name, str) and loras.is_real(name)
                    and comfyui._slot_on(widget)):
                return True
        elif (isinstance(widget, str) and "lora" in node_type
                and loras.looks_like_model_file(widget)):
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
