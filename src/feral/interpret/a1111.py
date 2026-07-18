"""Schicht-2-Parser: Automatic1111 / Forge / SD.Next ``parameters``-Text.

A1111 und seine Abkömmlinge schreiben ihre Generierungsparameter als einen
Textblock in den PNG-Chunk mit dem Keyword ``parameters`` (Format laut
A1111-Dokumentation, "infotext"):

    <prompt, ggf. mehrzeilig>
    Negative prompt: <negativ, ggf. mehrzeilig>
    Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 123, Size: 512x512,
    Model hash: abc123, Model: irgendein_modell, ...

Der Parser bildet die bekannten Schlüssel der Einstellungszeile auf das
kanonische Feldvokabular ab (`feral.interpret.types`). Unbekannte Schlüssel
werden bewusst ignoriert — sie bleiben ja verlustfrei in Schicht 1 erhalten
und können mit einer späteren Parser-Version nachgezogen werden (ADR 0004).
"""

from __future__ import annotations

import re
from typing import Sequence

from ..extract.types import RawMetadataItem
from . import loras
from .types import InterpretedField, Interpretation

NAME = "a1111"
VERSION = 3  # v3: Feature-Erkennung (ADetailer/Hires/ControlNet/Refiner)
# (v2: LoRA-Erkennung — Inline-<lora:>-Tags + "Lora hashes:")

# Schlüssel der Einstellungszeile → kanonisches Feld.
_KEY_MAP = {
    "steps": "steps",
    "sampler": "sampler",
    "schedule type": "scheduler",
    "cfg scale": "cfg_scale",
    "seed": "seed",
    "size": "size",
    "model": "model",
    "model hash": "model_hash",
    "denoising strength": "denoise",
    "vae": "vae",
}

# "Schlüssel: Wert"-Paare der Einstellungszeile; Werte dürfen in Anführungszeichen
# stehen und dann auch Kommas enthalten (z. B. Lora hashes: "a: b, c: d").
_PAIR = re.compile(r'\s*([\w .-]+?):\s*("(?:[^"\\]|\\.)*"|[^,]*)(?:,|$)')

# Schlüssel-Präfixe der Einstellungszeile, die die Nutzung eines relevanten
# Zusatzwerkzeugs verraten (Feral Strawberry, 2026-07-08) → Wert des `feature`-Felds.
# ADetailer schreibt "ADetailer model, ADetailer confidence, …", Hires fix
# "Hires upscale/steps/upscaler", ControlNet "ControlNet 0: …" je Unit.
_FEATURE_PREFIXES = (
    ("adetailer", "adetailer"),
    ("hires", "highres_fix"),
    ("controlnet", "controlnet"),
    ("refiner", "refiner"),
)


def parse(items: Sequence[RawMetadataItem]) -> Interpretation | None:
    """Interpretiere den ``parameters``-Text, falls vorhanden.

    Gibt ``None`` zurück, wenn kein Eintrag mit Keyword ``parameters`` dabei ist
    (Datei stammt dann nicht aus A1111-artigen Tools).
    """
    text = next(
        (i.text for i in items if i.keyword == "parameters" and i.text), None
    )
    if text is None:
        return None

    fields: list[InterpretedField] = [InterpretedField("tool", NAME)]
    prompt, negative, settings_line = _split_sections(text)
    if prompt:
        fields.append(InterpretedField("prompt", prompt))
    if negative:
        fields.append(InterpretedField("negative_prompt", negative))

    # LoRAs stehen als Inline-Tags im Prompt (<lora:name:gewicht>) und/oder in
    # der "Lora hashes:"-Zeile — beide sammeln, dann werkzeugübergreifend
    # normalisieren und deduplizieren.
    lora_names: list[str] = loras.inline_loras(prompt) + loras.inline_loras(negative)

    features: list[str] = []
    for raw_key, raw_value in _PAIR.findall(settings_line):
        key = raw_key.strip().lower()
        value = raw_value.strip().strip('"')
        if key == "lora hashes":
            lora_names.extend(_hash_names(value))
            continue
        for prefix, feature in _FEATURE_PREFIXES:
            if key.startswith(prefix) and feature not in features:
                features.append(feature)
        canonical = _KEY_MAP.get(key)
        if canonical and value:
            fields.append(InterpretedField(canonical, value))

    for name in loras.dedup_normalized(lora_names):
        fields.append(InterpretedField("lora", name))
    for feature in features:
        fields.append(InterpretedField("feature", feature))

    return Interpretation(parser=NAME, parser_version=VERSION, fields=fields)


def _hash_names(value: str) -> list[str]:
    """Namen aus einer ``Lora hashes: "name: hash, name2: hash2"``-Angabe."""
    return [pair.split(":", 1)[0].strip() for pair in value.split(",") if pair.strip()]


def _split_sections(text: str) -> tuple[str, str, str]:
    """Zerlege den Infotext in (Prompt, Negativ-Prompt, Einstellungszeile).

    Die Einstellungszeile ist die letzte Zeile, die mit ``Steps:`` beginnt;
    ``Negative prompt:`` markiert den Beginn des Negativ-Blocks. Fehlt beides,
    ist der gesamte Text der Prompt.
    """
    lines = text.split("\n")

    settings_index = None
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].startswith("Steps:"):
            settings_index = index
            break
    settings_line = lines[settings_index] if settings_index is not None else ""
    body = lines[:settings_index] if settings_index is not None else lines

    negative_index = None
    for index, line in enumerate(body):
        if line.startswith("Negative prompt:"):
            negative_index = index
            break

    if negative_index is None:
        prompt_lines, negative_lines = body, []
    else:
        prompt_lines = body[:negative_index]
        first = body[negative_index][len("Negative prompt:"):].lstrip()
        negative_lines = [first] + body[negative_index + 1:]

    return (
        "\n".join(prompt_lines).strip(),
        "\n".join(negative_lines).strip(),
        settings_line,
    )
