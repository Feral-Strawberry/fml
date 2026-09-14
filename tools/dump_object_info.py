"""Widget names for the workflow preview from your own ComfyUI (Issue #47).

ComfyUI stores widget values in the workflow JSON positionally (a bare list).
To label them ("seed 1234 · steps 20 · cfg 7") the preview needs the widget
names per node type. fml ships a built-in table for the core nodes
(web/static/js/widgetnames.js); this script extends it with EVERY node of
your installation, custom nodes included, by reading ``GET /object_info``
of a running ComfyUI and reducing it to ``{type: [widget names]}``.

    python tools/dump_object_info.py                       # http://127.0.0.1:8188
    python tools/dump_object_info.py --url http://host:8188

Writes ``src/feral/web/static/widgets.json`` (gitignored: data of your
installation, not code). The preview loads it once; if it is missing, only the
built-in table applies. Standard library only, no dependencies.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

WIDGET_TYPES = {"STRING", "INT", "FLOAT", "BOOLEAN", "COMBO"}
# INT seeds carry an extra "control_after_generate" widget right after them.
SEED_NAMES = {"seed", "noise_seed"}
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "src" / "feral" / "web" / "static" / "widgets.json"


def _is_widget(spec) -> bool:
    """An input spec is a widget if its type is a list (COMBO) or a primitive."""
    if not isinstance(spec, (list, tuple)) or not spec:
        return False
    kind = spec[0]
    if isinstance(kind, list):
        return True                       # COMBO: list of choices
    if isinstance(kind, str):
        if kind in WIDGET_TYPES:
            return True
        # Connection types are uppercase identifiers like MODEL, CLIP, IMAGE …
        return False
    return False


def reduce_object_info(info: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for node_type, meta in info.items():
        inputs = meta.get("input") or {}
        names: list[str] = []
        for section in ("required", "optional"):
            for name, spec in (inputs.get(section) or {}).items():
                if _is_widget(spec):
                    names.append(name)
                    opts = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
                    if name in SEED_NAMES or opts.get("control_after_generate"):
                        names.append("control_after_generate")
        if names:
            out[node_type] = names
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", default="http://127.0.0.1:8188", help="ComfyUI base URL")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output JSON path")
    args = ap.parse_args(argv)
    url = args.url.rstrip("/") + "/object_info"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            info = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Could not read {url}: {exc}", file=sys.stderr)
        print("Is ComfyUI running? Pass --url if it listens elsewhere.", file=sys.stderr)
        return 1
    table = reduce_object_info(info)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(table, indent=1, sort_keys=True), encoding="utf-8")
    print(f"{len(table)} node types with widgets -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
