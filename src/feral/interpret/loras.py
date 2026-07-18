"""Gemeinsame LoRA-Hilfen für die Schicht-2-Parser (ADR 0026).

LoRAs tauchen in ganz unterschiedlichen Formen auf:

- **ComfyUI**: als Loader-Input (``lora_name`` auf ``LoraLoader``), als nummerierte
  Stacker-Inputs (``lora_name_1`` … auf efficiency-/CR-Stackern) oder als Dict pro
  Slot (rgthree *Power Lora Loader*: ``lora_1 = {"on": true, "lora": "x.safetensors"}``).
- **A1111**: als **Inline-Tag im Prompt** (``<lora:name:0.8>``, ``<lyco:…>``) und als
  ``Lora hashes: "name: hash, …"``-Zeile.

Damit ComfyUI (``subdir/detail.safetensors``) und A1111 (``detail``) auf denselben
``lora``-Wert abbilden — Voraussetzung für werkzeugübergreifende Suche —, werden die
Namen **normalisiert**: Pfad und bekannte Endung weg, nur der Kern-Name bleibt
(Feral Strawberrys Entscheidung 2026-07-08: nur Name, kein Gewicht).
"""

from __future__ import annotations

import re

# Endungen, die ein LoRA-Dateiname tragen kann (klein verglichen).
_LORA_EXTENSIONS = (".safetensors", ".ckpt", ".pt", ".pth", ".lora", ".bin")

# Inline-LoRA-Tags im A1111-Prompt: <lora:name:gewicht> / <lyco:name:gewicht>.
# Der Name ist alles bis zum nächsten ':' oder '>'; das Gewicht ignorieren wir.
_INLINE = re.compile(r"<(?:lora|lyco):([^:>]+)", re.IGNORECASE)

# Platzhalter für „kein LoRA gewählt" (Stacker setzen deaktivierte Slots so).
_PLACEHOLDERS = {"", "none"}


def normalize_name(raw: str) -> str:
    """Reduziere einen LoRA-Bezeichner auf den vergleichbaren Kern-Namen.

    ``subdir/detail.safetensors`` → ``detail``; ``detail`` bleibt ``detail``.
    Backslashes (Windows-Pfade in ComfyUI) werden mitbehandelt.
    """
    name = raw.strip().replace("\\", "/").rsplit("/", 1)[-1]
    low = name.lower()
    for ext in _LORA_EXTENSIONS:
        if low.endswith(ext):
            return name[: -len(ext)]
    return name


def is_real(raw: str) -> bool:
    """``True``, wenn der Wert ein echter LoRA-Name ist (nicht leer / ``None``)."""
    return raw.strip().lower() not in _PLACEHOLDERS


def looks_like_model_file(raw: str) -> bool:
    """``True``, wenn der String wie eine Modell-/LoRA-Datei aussieht
    (bekannte Endung) — Grundlage der generischen ComfyUI-Erkennung: bei
    unbekannten Node-Klassen zählt ein Input nur, wenn der Wert eine echte
    Modelldatei benennt (nie „On"/„simple"/Zahlen als LoRA raten)."""
    return raw.strip().lower().endswith(_LORA_EXTENSIONS)


def inline_loras(text: str) -> list[str]:
    """Alle Inline-LoRA-Namen aus einem A1111-Prompttext, in Fundreihenfolge."""
    return [match.group(1).strip() for match in _INLINE.finditer(text)]


def dedup_normalized(raw_names: list[str]) -> list[str]:
    """Normalisiere, wirf Platzhalter weg, dedupliziere case-insensitiv.

    Reihenfolge bleibt erhalten; die erste Schreibweise gewinnt.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_names:
        if not is_real(raw):
            continue
        name = normalize_name(raw)
        key = name.lower()
        if key and key not in seen:
            seen.add(key)
            out.append(name)
    return out
