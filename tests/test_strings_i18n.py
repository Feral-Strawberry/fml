"""Tests für die Mehrsprachigkeit (Block M.1, ADR 0054).

Deutsch (strings.de.js) ist die Quelle der Wahrheit; dieser Test erzwingt,
dass keine Sprachdatei unbemerkt hinter ihr zurückfällt: identische
Schlüsselmengen/Struktur (inkl. Array-Längen) und unübersetzte kanonische
Werte (sortOptions key/dir). Der Mini-Parser liest die JS-Objektliterale
string-, escape- und kommentar-bewusst ein — die Sprachdateien enthalten
bewusst nur einfache Literale (keine Template-Strings, keine Ausdrücke).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import feral

JS_DIR = Path(feral.__file__).parent / "web" / "static" / "js"


# -- Mini-Parser für die STRINGS-Objektliterale --------------------------------

def _skip_ws(s: str, i: int) -> int:
    while i < len(s):
        if s[i] in " \t\r\n":
            i += 1
        elif s.startswith("//", i):
            nl = s.find("\n", i)
            i = len(s) if nl < 0 else nl + 1
        elif s.startswith("/*", i):
            i = s.index("*/", i) + 2
        else:
            break
    return i


def _parse_string(s: str, i: int) -> tuple[str, int]:
    quote = s[i]
    i += 1
    out: list[str] = []
    while s[i] != quote:
        if s[i] == "\\":
            out.append(s[i + 1])
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out), i + 1


def _parse_value(s: str, i: int):
    i = _skip_ws(s, i)
    c = s[i]
    if c == "{":
        return _parse_object(s, i)
    if c == "[":
        return _parse_array(s, i)
    if c in "\"'":
        return _parse_string(s, i)
    j = i  # Skalar (Zahl/Bool): bis zum nächsten Trenner
    while s[j] not in ",}]":
        j += 1
    return s[i:j].strip(), j


def _parse_object(s: str, i: int) -> tuple[dict, int]:
    obj: dict = {}
    i += 1  # über "{"
    while True:
        i = _skip_ws(s, i)
        if s[i] == "}":
            return obj, i + 1
        if s[i] == ",":
            i += 1
            continue
        if s[i] in "\"'":
            key, i = _parse_string(s, i)
        else:
            j = s.index(":", i)
            key, i = s[i:j].strip(), j
        i = _skip_ws(s, i)
        assert s[i] == ":", f"':' erwartet bei Position {i}"
        obj[key], i = _parse_value(s, i + 1)


def _parse_array(s: str, i: int) -> tuple[list, int]:
    arr: list = []
    i += 1  # über "["
    while True:
        i = _skip_ws(s, i)
        if s[i] == "]":
            return arr, i + 1
        if s[i] == ",":
            i += 1
            continue
        val, i = _parse_value(s, i)
        arr.append(val)


def load_strings(filename: str) -> dict:
    text = (JS_DIR / filename).read_text(encoding="utf-8")
    start = text.index("{", text.index("export const STRINGS"))
    obj, _ = _parse_object(text, start)
    return obj


def key_paths(node, prefix: str = "") -> set[str]:
    """Rekursive Schlüsselpfade; Arrays gehen mit Länge + Element-Struktur ein."""
    paths: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{prefix}.{k}" if prefix else k
            paths.add(p)
            paths |= key_paths(v, p)
    elif isinstance(node, list):
        paths.add(f"{prefix}[len={len(node)}]")
        for idx, v in enumerate(node):
            paths |= key_paths(v, f"{prefix}[{idx}]")
    return paths


def _language_files() -> list[str]:
    """Alle Sprachdateien laut LANGUAGES-Registry im Sprachlader (strings.js)."""
    loader = (JS_DIR / "strings.js").read_text(encoding="utf-8")
    codes = re.findall(r'code:\s*"([a-z-]+)"', loader)
    assert codes, "keine LANGUAGES-Registry in strings.js gefunden"
    return [f"strings.{code}.js" for code in codes]


# -- Tests ---------------------------------------------------------------------

def test_registry_dateien_existieren() -> None:
    """Jede in LANGUAGES registrierte Sprache hat ihre strings.<code>.js."""
    for filename in _language_files():
        assert (JS_DIR / filename).is_file(), f"{filename} fehlt"


@pytest.mark.parametrize("filename", [f for f in _language_files() if f != "strings.de.js"])
def test_schluesselmengen_identisch(filename: str) -> None:
    """Schlüsselmenge + Struktur jeder Sprache == Deutsch (Quelle der Wahrheit)."""
    de = key_paths(load_strings("strings.de.js"))
    other = key_paths(load_strings(filename))
    missing = sorted(de - other)
    extra = sorted(other - de)
    assert not missing and not extra, (
        f"{filename} weicht von strings.de.js ab —"
        f" fehlt: {missing or '—'} · zu viel: {extra or '—'}"
    )


@pytest.mark.parametrize("filename", [f for f in _language_files() if f != "strings.de.js"])
def test_kanonische_werte_unuebersetzt(filename: str) -> None:
    """sortOptions key/dir sind API-Werte (ADR 0039) und in allen Sprachen gleich."""
    de = load_strings("strings.de.js")["sortOptions"]
    other = load_strings(filename)["sortOptions"]
    for d, o in zip(de, other):
        assert (d["key"], d["dir"]) == (o["key"], o["dir"]), (
            f"{filename}: sortOptions[{d['key']}] muss key/dir kanonisch lassen"
        )
        assert o["dir"] in {"auf", "ab"}
