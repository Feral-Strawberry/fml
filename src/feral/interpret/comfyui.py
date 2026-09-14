"""Schicht-2-Parser: ComfyUI-Prompt-Graph (Keywords ``prompt``/``workflow``).

ComfyUI bettet zwei JSON-Blöcke ein (laut ComfyUI-Dokumentation):

- ``prompt``:   der ausgeführte API-Graph — ``{node_id: {"class_type": …,
                "inputs": {…}}}``. Inputs sind Literale oder Links
                ``[node_id, slot]``. Das ist die verlässliche Quelle.
- ``workflow``: der UI-Graph (Knoten-Positionen etc.) — für uns nur ein
                Erkennungsmerkmal, nicht Parse-Quelle.

Die Keywords werden **case-insensitiv** verglichen: bei PNG heißen die Chunks
``prompt``/``workflow``, in Video-Containern landen dieselben Blöcke aber je
nach Muxer als ``PROMPT``/``WORKFLOW`` (Matroska normalisiert Tag-Namen auf
Großschreibung) bzw. klein bei MP4.

**Positiv vs. Negativ** (essentiell, siehe DESIGN-Feedback von Feral Strawberry): Die
Zuordnung folgt den ``positive``/``negative``-Links — und zwar **rekursiv**,
denn zwischen Sampler und Text-Knoten liegen oft Zwischenknoten (``CFGGuider``,
``LTXVConditioning``, Crop/Combine-Conditioning, …). Auch der Text selbst darf
ein Link sein (Prompt-Enhancer, ``PrimitiveStringMultiline``); dann wird die
String-Quelle weiterverfolgt. Nur Text-Knoten, die über **keinen** solchen Pfad
erreichbar sind, werden als unklarer ``prompt``-Kandidat geführt (Schicht 2
darf unvollständig sein — aber sie darf Negativ nie als Positiv ausgeben).
"""

from __future__ import annotations

import json
import re
from typing import Any, Sequence

from ..extract.types import RawMetadataItem
from . import loras
from .types import InterpretedField, Interpretation

NAME = "comfyui"
VERSION = 11  # v11: Sampling-Einstellungen aus Split-Bauformen und Subgraphen
# (Issue #29, ADR 0068): BasicScheduler/LTXVScheduler/KSamplerSelect/CFGGuider
# tragen steps/scheduler/sampler/cfg ohne seed; ManualSigmas → steps aus der
# Sigma-Liste; Sampler-Knoten ohne sampler_name → Name aus der Klasse;
# verlinkte Skalare (PrimitiveInt am Subgraph-Rand) werden aufgelöst;
# Hauptpass zuerst bei mehreren Durchgängen; LLM-Seed ist kein Bild-Seed;
# workflow-Rückfall liest Sampler-Widgets inkl. promoteter Subgraph-Werte.
# (v10: Prompt-Enhancer-Ketten (Feral Strawberrys Ernie-Image-/Krea-2-Befund
# 2026-07-17): Boolean-Switches (on_true/on_false) werden aufgelöst und dem
# gewählten Zweig gefolgt; TextGenerate-Zweige (Core-LLM-Enhancer) haben am
# Switch die niedrigste Priorität — ihr prompt-Input ist dort die
# Systemprompt-Schablone, der Roh-Prompt hängt am anderen Zweig;
# feature: prompt_enhancer, wenn ein Generator aktiv war (geführter
# Prompt = Vor-Enhancement-Text);
# PreviewAny-Durchreicher (source); ConditioningZeroOut beendet den
# Polaritäts-Pfad (leeres Negativ, nie der Positiv-Text). → ADR 0050
# (v9: String-Ketten vollständig auflösen — suffigierte String-Keys
#  (string_a, text1, text_g, any_01), Verkettungen zusammengesetzt,
#  nicht erreichte Encoder über Links, Graph unter fremdem Keyword;
#  v8: Prompt-Builder-Substrat + feature prompt_builder/bbox;
#  v7: LoRA-Namen auch hinter Links auflösen (Subgraph-Inputs);
#  v6: generische LoRA-Erkennung + Workflow-Blob-Fallback + Eingangsbild;
#  v5: Stacker/rgthree + Modell-Rückverfolgung; v4: Generator-/API-Knoten;
#  v2: Keywords case-insensitiv für Video-Container)

# Sampler-Inputs → kanonisches Feld.
_SAMPLER_INPUTS = {
    "seed": "seed",
    "noise_seed": "seed",
    "steps": "steps",
    "cfg": "cfg_scale",
    "sampler_name": "sampler",
    "scheduler": "scheduler",
    "denoise": "denoise",
}

# Loader-Inputs, die ein Checkpoint/UNet als Modell tragen (für die
# Rückfall-Suche, wenn die Modell-Rückverfolgung vom Sampler nichts findet).
_MODEL_INPUTS = ("ckpt_name", "unet_name")

# Knoten, die Sampling-Einstellungen tragen, ohne selbst Sampler mit Seed zu
# sein (v11): Split-Bauformen moderner Templates — BasicScheduler/
# LTXVScheduler (steps, scheduler, denoise), KSamplerSelect (sampler_name),
# CFGGuider/SamplerCustom (cfg), ManualSigmas (Sigma-Liste). Erkannt am
# Klassennamen PLUS einem Sampler-Input.
_SAMPLING_CLASS_HINTS = ("sampler", "scheduler", "sigmas", "guider")

# Wert-Halter hinter verlinkten Skalar-Inputs (PrimitiveInt/Float/Combo,
# Int-/Number-Knoten): in Subgraphen kommen steps/cfg/seed oft als Link vom
# Subgraph-Rand herein statt als Literal.
_SCALAR_KEYS = ("value", "int", "float", "number", "string")

# Reihenfolge der Sampler-Felder je Durchgang (stabil für Anzeige/ordinal).
_PASS_FIELDS = ("seed", "steps", "cfg_scale", "sampler", "scheduler", "denoise")

# Sampler-Knoten ohne sampler_name (SamplerEulerAncestral, SamplerDPMPP_2M_SDE,
# SamplerLMS …): der Name steckt im Klassennamen — CamelCase → snake_case.
# Die Container SamplerCustom(Advanced) sind keine Sampler-Wahl.
_CAMEL_1 = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_2 = re.compile(r"([a-z])([A-Z])")  # Ziffer→Groß bleibt zusammen (2M, 3M)
_SAMPLER_CONTAINERS = ("samplercustom", "samplercustomadvanced")

# workflow-Blob (Rückfall ohne prompt): widgets_values sind positionslos —
# feste Widget-Layouts der Core-Knoten in Frontend-Reihenfolge (None =
# übersprungen, z. B. control_after_generate/add_noise).
_WIDGET_LAYOUTS: dict[str, tuple[str | None, ...]] = {
    "ksampler": ("seed", None, "steps", "cfg", "sampler_name", "scheduler", "denoise"),
    "ksampleradvanced": (None, "noise_seed", None, "steps", "cfg", "sampler_name", "scheduler"),
    "basicscheduler": ("scheduler", "steps", "denoise"),
    "ksamplerselect": ("sampler_name",),
    "randomnoise": ("noise_seed",),
    "cfgguider": ("cfg",),
    "samplercustom": (None, "noise_seed", None, "cfg"),
    "ltxvscheduler": ("steps",),
    "manualsigmas": ("sigmas",),
}
# Subgraph-Pseudoknoten im workflow-Blob: -10 = Eingänge des Subgraphen.
_SUBGRAPH_INPUT_NODE = -10
# Subgraph-Input-Typen, die am Instanzknoten als Widget (Wert) erscheinen.
_WIDGET_TYPES = ("STRING", "INT", "FLOAT", "BOOLEAN", "COMBO", "NUMBER")

# Klassische LoRA-Inputs mit String-Wert: lora, lora_name, lora_name_1, lora_01 …
_LORA_STRING_KEY = re.compile(r"lora(?:_name)?(?:_\d+)?$")
_TRAILING_INDEX = re.compile(r"_(\d+)$")

# Bild-/Video-Lade-Knoten (img2img/i2v-Erkennung): Klassenname-Hinweise und
# Input-Schlüssel, hinter denen der Dateiname steckt (Core LoadImage: "image";
# VHS_LoadVideo: "video"; WAS Image Load: "image_path"; …).
_IMAGE_LOADER_HINTS = (
    "loadimage", "load image", "loadvideo", "load video",
    "image load", "video load",
)
_IMAGE_INPUT_KEYS = (
    "image", "video", "image_path", "video_path", "path", "file",
    "filename", "url", "directory",
)
_MEDIA_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff",
    ".mp4", ".webm", ".mov", ".avi", ".mkv",
)

# LiteGraph-Node-Modi im workflow-Blob: 2 = muted (NEVER), 4 = bypassed.
# (Der prompt-Blob braucht keinen Modus-Check: graphToPrompt lässt solche
# Knoten beim Queuen weg bzw. verdrahtet Bypässe durch.)
_INACTIVE_MODES = (2, 4)

# ComfyUI-Ordner-Annotation an Dateinamen ("bild.png [output]") — abstreifen.
_PATH_ANNOTATION = re.compile(r"\s*\[(input|output|temp)\]$")

# Input-Namen, hinter denen bei String-Quellknoten der Text steckt.
# Reihenfolge = Priorität; "high_level_description" deckt Prompt-Builder ab
# (z. B. Ideogram4PromptBuilderKJ, dessen prompt-Ausgang zur Laufzeit
# entsteht — die Beschreibung ist das beste eingebettete Substrat);
# "source" ist der Durchreicher-Input von PreviewAny (Krea-2-Template legt
# ihn mitten in die Prompt-Kette).
_STRING_KEYS = (
    "text", "prompt", "positive_prompt", "caption", "user_prompt",
    "high_level_description", "string", "value", "source",
)

# Boolean-Quellen für Switch-Auflösung (PrimitiveBoolean: "value"; der
# Switch-Input selbst kann ebenfalls verlinkt sein).
_BOOL_KEYS = ("value", "boolean", "switch", "state")

# Suffigierte String-Keys (v9, aus dem --prompt-report auf Feral Strawberrys Bestand):
# StringConcatenate (string_a/string_b), TextBox1 (text1), SDXL-Encoder
# (text_g/text_l), rgthree Any Switch (any_01 — nur auf Text-Pfaden
# erreichbar, daher unkritisch). Buchstaben-Suffixe brauchen einen Trenner
# ("values" ist KEIN string_s), nackte Ziffern nicht (text1).
_SUFFIXED_STRING_KEY = re.compile(
    r"^(?:text|prompt|string|value|caption|any)(?:[_ ]\w{1,2}|\d{1,2})$"
)

# Prompt-Inputs, die Generator-/API-Knoten direkt tragen (Krea 2 Turbo,
# Ideogram 4, andere Partner-/API-Knoten): kein Sampler, kein CLIPTextEncode —
# der Prompt hängt als String oder Link am Generator selbst.
_GENERATOR_PROMPT_INPUTS = (
    ("prompt", "prompt"),
    ("positive_prompt", "prompt"),
    ("caption", "prompt"),
    ("negative_prompt", "negative_prompt"),
)


def _is_switch(node: dict[str, Any]) -> bool:
    """Boolean-Switch (Core ``ComfySwitchNode`` & baugleiche): strukturell
    erkannt an ``on_true``+``on_false`` — klassennamen-unabhängig."""
    inputs = node["inputs"]
    return "on_true" in inputs and "on_false" in inputs


def _is_llm_generator(node: dict[str, Any]) -> bool:
    """LLM-Text-Generator (Core ``TextGenerate``, ``TextGenerateLTX2Prompt``):
    ``generated_text`` entsteht erst zur Laufzeit. Der ``prompt``-Input kann
    der Roh-Prompt sein (LTX-Video-Template — dann lohnt das Auflösen) oder
    eine Systemprompt-Schablone (Ernie Image/Krea 2 — dann hat der Zweig am
    Switch die niedrigste Priorität und der Roh-Prompt-Zweig gewinnt)."""
    class_type = str(node.get("class_type", "")).lower().replace("_", "").replace(" ", "")
    return "textgenerate" in class_type


def _resolve_bool(nodes: dict[str, Any], value: Any, visited: set[str]) -> bool:
    """Löse einen Boolean-Input auf: Literal oder Link-Kette bis zum
    Wert-Halter (``PrimitiveBoolean``). Unauflösbar → False, damit Switches
    auf ``on_false`` fallen (in den Templates der Roh-Prompt-Zweig)."""
    if isinstance(value, bool):
        return value
    node_id = _link_target(value)
    if node_id is None or node_id in visited:
        return False
    visited.add(node_id)
    node = nodes.get(node_id)
    if node is None:
        return False
    for key in _BOOL_KEYS:
        v = node["inputs"].get(key)
        if isinstance(v, bool):
            return v
        if isinstance(v, list):
            return _resolve_bool(nodes, v, visited)
    return False


def _is_prompt_builder(node: dict[str, Any]) -> bool:
    """Prompt-Builder-Knoten (Ideogram4PromptBuilderKJ & Co.): der eigentliche
    Prompt entsteht erst zur Laufzeit (JSON aus BBOXen, ggf. KI-Anreicherung).
    Erkennung über den Klassennamen oder das charakteristische
    ``high_level_description``-Feld."""
    class_type = str(node.get("class_type", "")).lower().replace("_", "").replace(" ", "")
    return "promptbuilder" in class_type or "high_level_description" in node["inputs"]


def _looks_like_bboxes(value: Any) -> bool:
    """Ob ein String das BBOX-JSON eines Region-Editors trägt (Ideogram 4
    Editor: gezeichnete Regionen mit ``x``/``y``/``w``/``h`` + Beschreibung).
    Strenger Struktur-Check — nie aus bloßem „sieht aus wie JSON" raten."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text.startswith("[") or '"x"' not in text[:200]:
        return False
    try:
        boxes = json.loads(text)
    except ValueError:
        return False
    return (
        isinstance(boxes, list)
        and len(boxes) > 0
        and all(
            isinstance(b, dict) and {"x", "y", "w", "h"} <= b.keys() for b in boxes
        )
    )


def parse(items: Sequence[RawMetadataItem]) -> Interpretation | None:
    """Interpretiere den ComfyUI-Graphen, falls vorhanden.

    Gibt ``None`` zurück, wenn weder ``prompt``- noch ``workflow``-Eintrag
    vorhanden ist. Ein ``workflow`` ohne parsebaren ``prompt``-Graphen ergibt
    nur das ``tool``-Feld — besser als nichts, Rest bleibt roh (Schicht 1).
    """
    prompt_graph = _load_json(items, keyword="prompt")
    has_workflow = any(
        i.keyword and i.keyword.lower() == "workflow" and i.text for i in items
    )

    graph_ok = _is_prompt_graph(prompt_graph)
    if not graph_ok:
        # v9: Manche Muxer legen den Graphen unter fremdem Keyword ab (im
        # Bestand gefunden: MP4-``comment``-Tag). Ein API-Graph ist an seiner
        # Struktur eindeutig erkennbar — Keyword-unabhängig nachsehen.
        for item in items:
            if (item.text and '"class_type"' in item.text
                    and (item.keyword or "").lower() not in ("prompt", "workflow")):
                candidate = _try_json(item.text)
                if _is_prompt_graph(candidate):
                    prompt_graph, graph_ok = candidate, True
                    break
    if not graph_ok and not has_workflow:
        return None

    fields: list[InterpretedField] = [InterpretedField("tool", NAME)]
    if graph_ok:
        fields.extend(_fields_from_graph(prompt_graph))
    elif has_workflow:
        # Kein parsebares prompt-Blob (manche Saver betten nur den UI-Graphen
        # ein): LoRAs/Eingangsbilder aus dem workflow-Blob ziehen — dort mit
        # Bypass/Mute-Filter, denn der UI-Graph enthält auch inaktive Knoten.
        workflow = _load_json(items, keyword="workflow")
        fields.extend(_fields_from_workflow(workflow))
    return Interpretation(parser=NAME, parser_version=VERSION, fields=fields)


def _load_json(items: Sequence[RawMetadataItem], *, keyword: str) -> Any | None:
    text = next(
        (i.text for i in items if i.keyword and i.keyword.lower() == keyword and i.text),
        None,
    )
    return _try_json(text) if text is not None else None


def _try_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except ValueError:
        return None


def _is_prompt_graph(data: Any) -> bool:
    """Ob ``data`` ein API-Graph ist: dict aus Knoten mit ``class_type``."""
    return isinstance(data, dict) and any(
        isinstance(n, dict) and "class_type" in n for n in data.values()
    )


def _fields_from_graph(graph: dict[str, Any]) -> list[InterpretedField]:
    fields: list[InterpretedField] = []
    seen: set[tuple[str, str]] = set()

    def add(field: str, value: Any) -> None:
        text = str(value).strip()
        if text and (field, text) not in seen:
            seen.add((field, text))
            fields.append(InterpretedField(field, text))

    nodes = {
        node_id: node
        for node_id, node in graph.items()
        if isinstance(node, dict) and isinstance(node.get("inputs"), dict)
    }

    resolved_text_nodes: set[str] = set()  # über Positiv/Negativ-Pfade erreicht
    # Sampling-Durchgänge und vom Sampler aus zurückverfolgte Checkpoints,
    # jeweils als (Rang, Reihenfolge, Wert) — Hauptpass zuerst (_pass_rank).
    passes: list[tuple[int, int, dict[str, Any]]] = []
    used_models: list[tuple[int, int, str]] = []

    for index, node in enumerate(nodes.values()):
        inputs = node["inputs"]

        # Sampler-/Noise-/Scheduler-Knoten (v11 auch Split-Bauformen; Subgraph-
        # IDs „30:3" sind gewöhnliche Schlüssel): skalare Einstellungen je
        # Durchgang sammeln und das tatsächlich benutzte Modell über den
        # model-Link zurückverfolgen.
        if _is_sampling_node(node):
            settings = _sampling_settings(nodes, node)
            rank = _pass_rank(settings)
            if settings:
                passes.append((rank, index, settings))
            model = _resolve_model(nodes, inputs.get("model"), set())
            if model is not None:
                used_models.append((rank, index, model))

        # Positiv/Negativ: von JEDEM Knoten mit solchen Links aus auflösen
        # (Sampler, CFGGuider, Conditioning-Zwischenknoten, …).
        for link_name, canonical in (("positive", "prompt"), ("negative", "negative_prompt")):
            if link_name in inputs:
                text = _resolve_prompt(
                    nodes, inputs[link_name], link_name, set(), resolved_text_nodes
                )
                if text is not None:
                    add(canonical, text)

        # LoRAs (alle Loader-Bauformen, generisch) und VAE.
        for name in _collect_loras(inputs, str(node.get("class_type", "")), nodes):
            add("lora", name)
        vae = inputs.get("vae_name")
        if isinstance(vae, str):
            add("vae", vae)

        # Eingangsbild/-video (img2img, image-to-video): Lade-Knoten mit
        # Dateinamen-Input. Vorhandensein = kein reines text-to-image.
        image = _input_image(node)
        if image is not None:
            add("input_image", image)

        # Prompt-Builder (Ideogram 4 KJ & Co., Feral Strawberry 2026-07-08): der finale
        # Prompt entsteht erst zur Laufzeit und die Auflösungskette reißt an
        # Konkatenier-/Enhancer-Zwischenknoten ab — die allgemeine Szenen-
        # beschreibung ist das beste eingebettete Substrat und wird direkt
        # geführt; feature: prompt_builder macht die Herkunft sichtbar.
        if _is_prompt_builder(node):
            add("feature", "prompt_builder")
            # Szenenbeschreibung zuerst (das „erste Feld" des Builders),
            # sonst die übliche String-Key-Kaskade.
            for key in ("high_level_description", *_STRING_KEYS):
                value = inputs.get(key)
                if isinstance(value, list):
                    value = _resolve_string(nodes, value, set())
                if isinstance(value, str) and value.strip():
                    add("prompt", value)
                    break

        # BBOX-Regionen (Ideogram 4 Editor): als Hinweislabel führen — der
        # eigentliche Regionen-Prompt ist Laufzeit-JSON, kein Lesetext.
        if any(_looks_like_bboxes(v) for v in inputs.values()):
            add("feature", "bbox")

        # Generator-/API-Knoten (Krea 2, Ideogram 4, …): Prompt direkt am
        # Knoten — als String-Literal oder als Link auf einen Quell-/Builder-
        # Knoten (dann über die String-Kette auflösen). Text-Encoder sind hier
        # ausgenommen, die laufen über die Positiv/Negativ-Pfade oben;
        # LLM-Generatoren ebenfalls (v10): ihr prompt-Input ist je nach
        # Template die Systemprompt-Schablone — der User-Prompt kommt dort
        # über die Encoder-/Switch-Pfade herein.
        if not _is_text_encoder(node) and not _is_llm_generator(node):
            for input_name, canonical in _GENERATOR_PROMPT_INPUTS:
                value = inputs.get(input_name)
                if isinstance(value, str) and value.strip():
                    add(canonical, value)
                elif isinstance(value, list):
                    text = _resolve_string(nodes, value, set())
                    if text is not None:
                        add(canonical, text)

    # Sampler-Felder in Durchgangs-Reihenfolge: Hauptpass zuerst, dann
    # Hires-/Upscale-Pässe — alle Werte bleiben als eigene Zeilen erhalten
    # (ordinal = Index), die Anzeige zeigt den ersten prominent (Issue #29).
    for _rank, _index, settings in sorted(passes, key=lambda p: p[:2]):
        for canonical in _PASS_FIELDS:
            if canonical in settings:
                add(canonical, settings[canonical])

    # Prompt-Enhancer-Flag (v10, Feral Strawberrys Wunsch): war ein LLM-Generator aktiv,
    # ist der geführte Prompt der VOR-Enhancement-Text — sichtbar machen.
    # Aktiv = der Switch-Zweig, der auf ihn zeigt, ist gewählt; oder kein
    # Switch bewacht ihn (LTX-Muster: Generator hängt direkt in der Kette).
    generators = {
        node_id for node_id, node in nodes.items() if _is_llm_generator(node)
    }
    if generators:
        gated: set[str] = set()
        active = False
        for node in nodes.values():
            if not _is_switch(node):
                continue
            inputs = node["inputs"]
            chosen = "on_true" if _resolve_bool(nodes, inputs.get("switch"), set()) else "on_false"
            for key in ("on_true", "on_false"):
                target = _link_target(inputs.get(key))
                if target in generators:
                    gated.add(target)
                    active = active or key == chosen
        if active or generators - gated:
            add("feature", "prompt_enhancer")

    # Modell: bevorzugt die vom Sampler zurückverfolgten Checkpoints. Nur wenn
    # keine Rückverfolgung griff (kein Sampler, unbekannte Loader-Klasse), als
    # Rückfall alle Checkpoint-/UNet-Loader im Graphen führen (besser als nichts).
    if used_models:
        for _rank, _index, model in sorted(used_models, key=lambda m: m[:2]):
            add("model", model)
    else:
        for node in nodes.values():
            for input_name in _MODEL_INPUTS:
                value = node["inputs"].get(input_name)
                if isinstance(value, str):
                    add("model", value)

    # Text-Knoten, die KEIN Positiv/Negativ-Pfad zuordnen konnte: als
    # unklare Prompt-Kandidaten führen (nie als negative_prompt raten).
    # v9: auch hier Links auflösen — reißt der Conditioning-Pfad an einem
    # unbekannten Zwischenknoten ab, hängt der Text trotzdem oft als
    # Kette (Primitive/Concatenate) am Encoder.
    for node_id, node in nodes.items():
        if node_id not in resolved_text_nodes and _is_text_encoder(node):
            text = _node_string(nodes, node, set())
            if text is not None:
                add("prompt", text)

    return fields


def _collect_loras(
    inputs: dict[str, Any], class_type: str, nodes: dict[str, Any] | None = None
) -> list[str]:
    """Alle LoRA-Namen eines Knotens, normalisiert und ohne Platzhalter.

    Bewusst **generisch** (Feral Strawberry, 2026-07-08 — es gibt zu viele Loader-Packs,
    um jeden einzeln zu kennen). Abgedeckte Bauformen:

    - String-Inputs ``lora``/``lora_name``/``lora_name_1``/``lora_01`` …
      (Core-Loader, „Load Lora (Model and Clip)", efficiency-/CR-Stacker);
      Slot-Schalter (``switch_i``, ``lora_on_i``, ``lora_count``) respektiert.
    - Dict-Inputs mit LoRA-Schlüssel: rgthree *Power Lora Loader*
      (``lora_1 = {"on": …, "lora": …}``) und pysssss-Loader
      (``lora_name = {"content": …}``); ``on: false`` = Slot aus.
    - Unbekannte Knoten: Klassenname **oder** Input-Name enthält „lora" und
      der Wert sieht wie eine Modelldatei aus (Endung) → zählt. Nie raten,
      wenn der Wert keine Datei benennt („On", Zahlen, Modi …).
    """
    raw_names: list[str] = []
    lora_class = "lora" in class_type.lower()
    for key, value in inputs.items():
        key_lower = key.lower()
        if isinstance(value, dict):
            if "lora" not in key_lower and not lora_class:
                continue
            name = value.get("lora") or value.get("lora_name") or value.get("content")
            if isinstance(name, str) and _slot_on(value):
                raw_names.append(name)
        elif isinstance(value, str):
            # Inline-Tags in Text-Inputs (rgthree Power Prompt & Co. wenden
            # <lora:name:1.0> aus dem Prompt-String an — wie A1111).
            raw_names.extend(_inline_tags(value))
            if _LORA_STRING_KEY.match(key_lower):
                if _stack_slot_enabled(inputs, key_lower):
                    raw_names.append(value)
            elif (lora_class or "lora" in key_lower) and loras.looks_like_model_file(value):
                raw_names.append(value)
        elif isinstance(value, list) and nodes is not None:
            # LoRA-Name als LINK statt Literal: Subgraph-Ränder reichen den
            # Widget-Wert als Verbindung durch (Krea-2-Template: lora_name
            # kommt vom Subgraph-Input). NUR lora-benannten Inputs folgen —
            # model/clip-Links eines LoraLoaders führen zum Checkpoint!
            if _LORA_STRING_KEY.match(key_lower) or "lora" in key_lower:
                resolved = _resolve_lora_link(nodes, value, set())
                if resolved is not None and _stack_slot_enabled(inputs, key_lower):
                    raw_names.append(resolved)
    return loras.dedup_normalized(raw_names)


def _resolve_lora_link(nodes: dict[str, Any], link: Any, visited: set[str]) -> str | None:
    """Folge einem Link bis zu einem String, der eine Modelldatei benennt.

    Quellknoten sind Wert-Halter (Subgraph-Input, Primitive, Combo): erst die
    klassischen LoRA-Schlüssel prüfen, dann jeden String-Input mit Datei-
    Endung, dann Link-Ketten weiterverfolgen (zyklenfest)."""
    node_id = _link_target(link)
    if node_id is None or node_id in visited:
        return None
    visited.add(node_id)
    node = nodes.get(node_id)
    if node is None:
        return None
    inputs = node["inputs"]
    for key, value in inputs.items():
        if isinstance(value, str) and _LORA_STRING_KEY.match(key.lower()):
            if loras.is_real(value):
                return value
    for value in inputs.values():
        if isinstance(value, str) and loras.looks_like_model_file(value):
            return value
    for value in inputs.values():
        if isinstance(value, list):
            resolved = _resolve_lora_link(nodes, value, visited)
            if resolved is not None:
                return resolved
    return None


def _inline_tags(value: str) -> list[str]:
    lowered = value.lower()
    if "<lora:" not in lowered and "<lyco:" not in lowered:
        return []
    return loras.inline_loras(value)


def _slot_on(slot: dict[str, Any]) -> bool:
    """Ob ein Dict-Slot aktiv ist: rgthree ``on: false`` = aus; Stärke 0 ohne
    CLIP-Anteil (``strengthTwo``) wird vom rgthree-Backend ebenfalls
    übersprungen — wir auch."""
    if slot.get("on", True) is False or slot.get("enabled", True) is False:
        return False
    if slot.get("strength") == 0 and not slot.get("strengthTwo"):
        return False
    return True


def _stack_slot_enabled(inputs: dict[str, Any], lora_key: str) -> bool:
    """Ob der Stacker-Slot zu ``…_i`` aktiv ist (Schalter respektieren):
    ``switch_i`` („Off", comfyroll), ``lora_on_i`` (False), ``lora_count``
    (Slots oberhalb der Zahl sind serialisiert, aber inaktiv — efficiency)
    und Gewicht 0 (``strength_i``/``lora_wt_i``, rgthree Lora Loader Stack).

    Der Suffix wird **wörtlich** übernommen (rgthree padded: ``lora_01`` →
    ``strength_01``), nur der `lora_count`-Vergleich ist numerisch.
    """
    match = _TRAILING_INDEX.search(lora_key)
    if match is None:
        return True
    suffix = match.group(1)
    count = inputs.get("lora_count")
    if isinstance(count, (int, float)) and int(suffix) > int(count):
        return False
    switch = inputs.get(f"switch_{suffix}")
    if isinstance(switch, str) and switch.strip().lower() == "off":
        return False
    toggle = inputs.get(f"lora_on_{suffix}")
    if isinstance(toggle, bool) and not toggle:
        return False
    for weight_key in (f"strength_{suffix}", f"lora_wt_{suffix}"):
        weight = inputs.get(weight_key)
        if isinstance(weight, (int, float)) and weight == 0:
            return False
    return True


def _input_image(node: dict[str, Any]) -> str | None:
    """Der Dateiname eines Bild-/Video-Lade-Knotens (oder None).

    Längen-/Zeilen-Guard: manche Knoten tragen Base64-Bilddaten statt eines
    Namens — die sind kein sinnvoller Feldwert."""
    class_type = str(node.get("class_type", "")).lower()
    if not any(hint in class_type for hint in _IMAGE_LOADER_HINTS):
        return None
    for key in _IMAGE_INPUT_KEYS:
        value = node["inputs"].get(key)
        if (isinstance(value, str) and value.strip()
                and len(value) <= 260 and "\n" not in value):
            return _PATH_ANNOTATION.sub("", value.strip())
    return None


def _is_sampling_node(node: dict[str, Any]) -> bool:
    """Ob ein Knoten Sampling-Einstellungen trägt: klassische Sampler-/Noise-/
    Generator-Knoten (``sampler_name``/``seed``/``noise_seed``) oder — v11 —
    Split-Bauformen, die der Klassenname verrät (BasicScheduler,
    KSamplerSelect, CFGGuider, ManualSigmas …). LLM-Generatoren haben einen
    eigenen ``seed`` — das ist nicht der Bild-Seed."""
    if _is_llm_generator(node):
        return False
    inputs = node["inputs"]
    if "sampler_name" in inputs or "seed" in inputs or "noise_seed" in inputs:
        return True
    class_type = str(node.get("class_type", ""))
    if _sampler_from_class(class_type) is not None:
        return True  # Sampler-Wahl per Klasse (SamplerEulerAncestral …)
    class_key = _class_key(class_type)
    return any(hint in class_key for hint in _SAMPLING_CLASS_HINTS) and (
        any(key in inputs for key in _SAMPLER_INPUTS) or "sigmas" in inputs
    )


def _class_key(class_type: str) -> str:
    return class_type.lower().replace("_", "").replace(" ", "")


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (int, float, str)) and not isinstance(value, bool)


def _sampling_settings(nodes: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """Die skalaren Sampler-Felder eines Knotens (kanonische Namen) — Literale
    und (v11) Links auf Wert-Halter. Ohne ``steps``: aus der Sigma-Liste
    ableiten (LTX-2-Templates: ``ManualSigmas`` mit 9 Werten = 8 Schritte);
    ohne ``sampler_name``: aus dem Klassennamen eines Sampler-Knotens."""
    inputs = node["inputs"]
    settings: dict[str, Any] = {}
    for input_name, canonical in _SAMPLER_INPUTS.items():
        value = inputs.get(input_name)
        if isinstance(value, list):
            value = _resolve_scalar(nodes, value, set())
        if _is_scalar(value):
            settings[canonical] = value
    class_type = str(node.get("class_type", ""))
    if "steps" not in settings:
        _apply_sigmas(settings, class_type, inputs.get("sigmas"))
    if "sampler" not in settings:
        sampler = _sampler_from_class(class_type)
        if sampler is not None:
            settings["sampler"] = sampler
    return settings


def _resolve_scalar(nodes: dict[str, Any], link: Any, visited: set[str]) -> Any:
    """Folge einem verlinkten Skalar-Input bis zum Wert-Halter (Primitive,
    Int/Number-Knoten); Rechenknoten ohne Literal → None (nie raten)."""
    node_id = _link_target(link)
    if node_id is None or node_id in visited:
        return None
    visited.add(node_id)
    node = nodes.get(node_id)
    if node is None:
        return None
    for key in _SCALAR_KEYS:
        value = node["inputs"].get(key)
        if _is_scalar(value):
            return value
        if isinstance(value, list):
            resolved = _resolve_scalar(nodes, value, visited)
            if resolved is not None:
                return resolved
    return None


def _parse_sigmas(class_type: str, sigmas: Any) -> list[float] | None:
    """Die Sigma-Liste eines Sigma-Knotens (``ManualSigmas``: „1., 0.99, …,
    0.0"); nur bei Sigma-Knoten und String-Literal, mindestens zwei Werte."""
    if "sigmas" not in class_type.lower() or not isinstance(sigmas, str):
        return None
    try:
        values = [float(part) for part in re.split(r"[,\s]+", sigmas.strip()) if part]
    except ValueError:
        return None
    return values if len(values) >= 2 else None


def _apply_sigmas(settings: dict[str, Any], class_type: str, sigmas: Any) -> None:
    """Steps aus einer Sigma-Liste (n Werte = n−1 Schritte). Beginnt die
    Liste unter 1,0, ist es ein Verfeinerungspass (LTX-2-Zweitstufe: Schwanz
    der ersten Liste, 0.909 → 0) — als Teilpass markieren, damit der
    Hauptpass unabhängig von der Knotenreihenfolge vorn steht."""
    values = _parse_sigmas(class_type, sigmas)
    if values is None:
        return
    settings["steps"] = len(values) - 1
    if values[0] < 1.0:
        settings["_partial"] = True  # interner Marker, wird nie ausgegeben


def _sampler_from_class(class_type: str) -> str | None:
    """Sampler-Name aus dem Klassennamen eines Sampler-Wahl-Knotens:
    ``SamplerEulerAncestral`` → ``euler_ancestral``, ``SamplerDPMPP_2M_SDE`` →
    ``dpmpp_2m_sde``. Container (SamplerCustom*) sind keine Wahl."""
    if not class_type.startswith("Sampler") or _class_key(class_type) in _SAMPLER_CONTAINERS:
        return None
    rest = class_type[len("Sampler"):]
    if not rest:
        return None
    name = _CAMEL_2.sub(r"\1_\2", _CAMEL_1.sub(r"\1_\2", rest)).lower()
    return re.sub(r"_+", "_", name).strip("_") or None


def _pass_rank(settings: dict[str, Any]) -> int:
    """Hauptpass zuerst (Issue #29): Durchgänge mit ``steps`` und vollem
    Denoise (fehlend oder ≥ 1) vor Teil-Denoise (Hires-Fix/Upscale-Pass) vor
    Knoten ohne ``steps`` (Noise-/Sampler-Wahl allein)."""
    if "steps" not in settings:
        return 2
    if settings.get("_partial"):
        return 1
    denoise = settings.get("denoise")
    try:
        return 0 if denoise is None or float(denoise) >= 1.0 else 1
    except (TypeError, ValueError):
        return 0


def _fields_from_workflow(workflow: Any) -> list[InterpretedField]:
    """Rückfall ohne prompt-Blob: LoRAs, Eingangsbilder + Prompt-Builder-
    Substrat aus dem UI-Graphen.

    Der workflow-Blob enthält ALLE Knoten — auch stummgeschaltete/umgangene
    (LiteGraph ``mode`` 2/4), die werden übersprungen. Werte stecken
    positionslos in ``widgets_values``; deshalb nur, was sich sicher erkennen
    lässt: Modelldateien an LoRA-Knoten, Mediendateien an Lade-Knoten,
    rgthree-Slot-Dicts. Subgraph-Definitionen (neues Frontend-Format) werden
    mit durchsucht.
    """
    graphs = _workflow_graphs(workflow)
    fields: list[InterpretedField] = _sampling_fields_from_workflow(graphs)
    node_lists = [graph["nodes"] for graph in graphs]
    raw_loras: list[str] = []
    images: list[str] = []
    prompts: list[str] = []
    features: list[str] = []
    for nodes in node_lists:
        for node in nodes:
            if not isinstance(node, dict) or node.get("mode") in _INACTIVE_MODES:
                continue
            node_type = str(node.get("type", "")).lower()
            widgets = node.get("widgets_values")
            widget_list = widgets if isinstance(widgets, list) else []
            for widget in widget_list:
                if isinstance(widget, dict):
                    name = widget.get("lora")
                    if isinstance(name, str) and _slot_on(widget):
                        raw_loras.append(name)
                elif isinstance(widget, str):
                    raw_loras.extend(_inline_tags(widget))
                    if "lora" in node_type and loras.looks_like_model_file(widget):
                        raw_loras.append(widget)
            if any(hint in node_type for hint in _IMAGE_LOADER_HINTS):
                for widget in widget_list:
                    if not (isinstance(widget, str) and widget.strip()):
                        continue
                    cleaned = _PATH_ANNOTATION.sub("", widget.strip())
                    if cleaned.lower().endswith(_MEDIA_EXTENSIONS):
                        images.append(cleaned)
                        break
            # Prompt-Builder (v8): Widgets sind positionslos — der erste
            # nicht-leere String, der weder BBOX-JSON noch Datei ist, ist
            # beim Builder die allgemeine Szenenbeschreibung (Feral Strawberrys Wunsch).
            if "promptbuilder" in node_type.replace("_", "").replace(" ", ""):
                features.append("prompt_builder")
                for widget in widget_list:
                    if (isinstance(widget, str) and widget.strip()
                            and not _looks_like_bboxes(widget)
                            and not loras.looks_like_model_file(widget)):
                        prompts.append(widget.strip())
                        break
            if any(_looks_like_bboxes(w) for w in widget_list):
                features.append("bbox")
    for name in loras.dedup_normalized(raw_loras):
        fields.append(InterpretedField("lora", name))
    seen: set[tuple[str, str]] = set()
    for kind, values in (("prompt", prompts), ("feature", features), ("input_image", images)):
        for value in values:
            if (kind, value) not in seen:
                seen.add((kind, value))
                fields.append(InterpretedField(kind, value))
    return fields


def _workflow_graphs(workflow: Any) -> list[dict[str, Any]]:
    """Alle Graphen eines workflow-Blobs: Hauptgraph + Subgraph-Definitionen.
    ``definitions.subgraphs`` ist FLACH — ein Subgraph im Subgraph ist dort
    ein weiterer Eintrag, referenziert über seine UUID als Knotentyp."""
    if not isinstance(workflow, dict):
        return []
    graphs: list[dict[str, Any]] = []
    if isinstance(workflow.get("nodes"), list):
        graphs.append(workflow)
    definitions = workflow.get("definitions")
    if isinstance(definitions, dict):
        subgraphs = definitions.get("subgraphs")
        if isinstance(subgraphs, list):
            graphs.extend(
                sub for sub in subgraphs
                if isinstance(sub, dict) and isinstance(sub.get("nodes"), list)
            )
    return graphs


def _sampling_fields_from_workflow(graphs: list[dict[str, Any]]) -> list[InterpretedField]:
    """Sampler-Felder aus dem UI-Graphen (v11): feste Widget-Layouts der
    Core-Knoten, Subgraphen inklusive, ohne stummgeschaltete/umgangene
    Knoten. Promotete Widgets (Wert steht am Subgraph-Knoten des
    Elterngraphen) werden aufgelöst. Rangfolge wie im prompt-Blob."""
    passes: list[tuple[int, int, dict[str, Any]]] = []
    index = 0
    for graph in graphs:
        for node in graph["nodes"]:
            index += 1
            if not isinstance(node, dict) or node.get("mode") in _INACTIVE_MODES:
                continue
            node_type = str(node.get("type", ""))
            settings: dict[str, Any] = {}
            for position, input_name in enumerate(_WIDGET_LAYOUTS.get(_class_key(node_type), ())):
                if input_name is None:
                    continue
                value = _widget_value(graphs, graph, node, input_name, position, 0)
                if input_name == "sigmas":
                    _apply_sigmas(settings, node_type, value)
                elif _is_scalar(value):
                    settings[_SAMPLER_INPUTS[input_name]] = value
            sampler = _sampler_from_class(node_type)
            if sampler is not None:
                settings.setdefault("sampler", sampler)
            if settings:
                passes.append((_pass_rank(settings), index, settings))
    fields: list[InterpretedField] = []
    seen: set[tuple[str, str]] = set()
    for _rank, _index, settings in sorted(passes, key=lambda p: p[:2]):
        for canonical in _PASS_FIELDS:
            text = str(settings.get(canonical, "")).strip()
            if text and (canonical, text) not in seen:
                seen.add((canonical, text))
                fields.append(InterpretedField(canonical, text))
    return fields


def _widget_value(
    graphs: list[dict[str, Any]], graph: dict[str, Any], node: dict[str, Any],
    input_name: str, position: int, depth: int,
) -> Any:
    """Der wirksame Widget-Wert eines Knotens: ist das Widget verlinkt, der
    Wert am anderen Ende (Primitive im selben Graphen oder — promotet — der
    Subgraph-Knoten im Elterngraphen); sonst das Literal in
    ``widgets_values`` an der Layout-Position."""
    for entry in node.get("inputs") or []:
        if not isinstance(entry, dict) or entry.get("link") is None:
            continue
        widget = entry.get("widget")
        name = widget.get("name") if isinstance(widget, dict) else entry.get("name")
        if name == input_name:
            resolved = _resolve_workflow_link(graphs, graph, entry["link"], depth)
            if resolved is not None:
                return resolved
            break
    widgets = node.get("widgets_values")
    if isinstance(widgets, list) and position < len(widgets):
        return widgets[position]
    return None


def _resolve_workflow_link(
    graphs: list[dict[str, Any]], graph: dict[str, Any], link_id: Any, depth: int,
) -> Any:
    """Wert hinter einem Link im UI-Graphen: Primitive-Knoten (erstes Widget)
    oder Subgraph-Eingang (-10) → Instanzknoten im Elterngraphen — dort das
    Widget in Reihenfolge der Subgraph-Inputs oder ein weiterer Link
    (verschachtelte Subgraphen; Tiefe begrenzt, zyklenfest)."""
    if depth > 8:
        return None
    origin_id, origin_slot = _workflow_link_origin(graph, link_id)
    if origin_id is None:
        return None
    if origin_id == _SUBGRAPH_INPUT_NODE:
        sub_inputs = graph.get("inputs") if isinstance(graph.get("inputs"), list) else []
        if origin_slot >= len(sub_inputs) or not isinstance(sub_inputs[origin_slot], dict):
            return None
        input_name = sub_inputs[origin_slot].get("name")
        widget_index = sum(
            1 for i in sub_inputs[:origin_slot]
            if isinstance(i, dict) and str(i.get("type", "")).upper() in _WIDGET_TYPES
        )
        for parent in graphs:
            for instance in parent["nodes"]:
                if not isinstance(instance, dict) or instance.get("type") != graph.get("id"):
                    continue
                for entry in instance.get("inputs") or []:
                    if (isinstance(entry, dict) and entry.get("name") == input_name
                            and entry.get("link") is not None):
                        value = _resolve_workflow_link(graphs, parent, entry["link"], depth + 1)
                        if value is not None:
                            return value
                widgets = instance.get("widgets_values")
                if isinstance(widgets, list) and widget_index < len(widgets):
                    return widgets[widget_index]
        return None
    origin = next(
        (n for n in graph["nodes"] if isinstance(n, dict) and n.get("id") == origin_id), None
    )
    if origin is None or not str(origin.get("type", "")).lower().startswith("primitive"):
        return None
    widgets = origin.get("widgets_values")
    return widgets[0] if isinstance(widgets, list) and widgets and _is_scalar(widgets[0]) else None


def _workflow_link_origin(graph: dict[str, Any], link_id: Any) -> tuple[Any, int]:
    """Ursprung (Knoten-ID, Slot) eines Links. Hauptgraph: Arrays
    ``[id, origin_id, origin_slot, target_id, target_slot, type]``;
    Subgraph-Definitionen: Dicts mit benannten Schlüsseln."""
    for link in graph.get("links") or []:
        if isinstance(link, dict) and link.get("id") == link_id:
            return link.get("origin_id"), int(link.get("origin_slot") or 0)
        if isinstance(link, list) and len(link) >= 3 and link[0] == link_id:
            return link[1], int(link[2] or 0)
    return None, 0


def _resolve_model(nodes: dict[str, Any], link: Any, visited: set[str]) -> str | None:
    """Folge dem ``model``-Link eines Samplers bis zum Checkpoint/UNet-Loader.

    Zwischenknoten (``LoraLoader``, ``ModelSamplingFlux``, … — alle mit eigenem
    ``model``-Input) werden durchlaufen; der erste Knoten mit ``ckpt_name`` bzw.
    ``unet_name`` liefert den tatsächlich benutzten Modellnamen.
    """
    node_id = _link_target(link)
    if node_id is None or node_id in visited:
        return None
    visited.add(node_id)
    node = nodes.get(node_id)
    if node is None:
        return None
    inputs = node["inputs"]
    for input_name in _MODEL_INPUTS:
        value = inputs.get(input_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if _is_switch(node):
        # Modell-Switch (Krea-2-Template: enable_lora?): gewählter Zweig
        # zuerst, der andere als Rückfall — beide enden am selben Loader.
        selected = _resolve_bool(nodes, inputs.get("switch"), set())
        for key in ("on_true", "on_false") if selected else ("on_false", "on_true"):
            model = _resolve_model(nodes, inputs.get(key), visited)
            if model is not None:
                return model
    return _resolve_model(nodes, inputs.get("model"), visited)


def _resolve_prompt(
    nodes: dict[str, Any],
    link: Any,
    polarity: str,
    visited: set[str],
    resolved_text_nodes: set[str],
) -> str | None:
    """Folge einem ``positive``/``negative``-Link bis zum Text.

    Zwischenknoten werden **polaritätstreu** durchlaufen: bei einem Knoten mit
    eigenem ``positive``/``negative`` wird nur der zur gesuchten Polarität
    passende Zweig verfolgt; generische Durchreicher folgen ``conditioning``.
    """
    node_id = _link_target(link)
    if node_id is None or node_id in visited:
        return None
    visited.add(node_id)
    node = nodes.get(node_id)
    if node is None:
        return None
    inputs = node["inputs"]

    # ConditioningZeroOut nullt sein Conditioning: das Negativ ist per
    # Konstruktion leer — NICHT zum (positiven) Encoder durchlaufen, sonst
    # erschiene der Prompt fälschlich auch als negative_prompt (v10).
    if "zeroout" in str(node.get("class_type", "")).lower().replace("_", ""):
        return None

    if _is_text_encoder(node):
        resolved_text_nodes.add(node_id)
        return _node_string(nodes, node, set())

    for key in (polarity, "conditioning"):
        if key in inputs:
            text = _resolve_prompt(nodes, inputs[key], polarity, visited, resolved_text_nodes)
            if text is not None:
                return text
    return None


def _resolve_string(nodes: dict[str, Any], link: Any, visited: set[str]) -> str | None:
    """Folge einer Link-Kette bis zum Text (Prompt-Enhancer,
    ``PrimitiveStringMultiline``, Verkettungs-/Switch-Knoten, …)."""
    node_id = _link_target(link)
    if node_id is None or node_id in visited:
        return None
    visited.add(node_id)
    node = nodes.get(node_id)
    if node is None:
        return None
    return _node_string(nodes, node, visited)


def _node_string(nodes: dict[str, Any], node: dict[str, Any], visited: set[str]) -> str | None:
    """Der Text eines Knotens: exakte String-Keys zuerst (Literal oder Link),
    dann suffigierte (v9 — ``string_a``/``string_b``, ``text1``, ``text_g``,
    ``any_01``). Mehrere suffigierte Teile werden **zusammengesetzt** statt
    abgerissen (StringConcatenate: Szene + Stil-Suffix; ``delimiter``-Input
    wird respektiert); identische Teile nur einmal (SDXL: text_g == text_l).
    """
    inputs = node["inputs"]
    if _is_switch(node):
        # v10: dem gewählten Zweig folgen, der andere ist Rückfall. Zweige,
        # die direkt in einem LLM-Generator münden, kommen zuletzt: dessen
        # Text entsteht zur Laufzeit — aufgelöst erschiene nur die
        # Systemprompt-Schablone statt des Roh-Prompts am anderen Zweig.
        selected = _resolve_bool(nodes, inputs.get("switch"), set())
        order = ("on_true", "on_false") if selected else ("on_false", "on_true")
        deferred: list[str] = []
        for pass_deferred in (False, True):
            for key in deferred if pass_deferred else order:
                value = inputs.get(key)
                if not pass_deferred:
                    target = nodes.get(_link_target(value) or "")
                    if target is not None and _is_llm_generator(target):
                        deferred.append(key)
                        continue
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, list):
                    text = _resolve_string(nodes, value, visited)
                    if text is not None:
                        return text
        return None
    for key in _STRING_KEYS:
        value = inputs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            text = _resolve_string(nodes, value, visited)
            if text is not None:
                return text
    parts: list[str] = []
    for key in sorted(inputs):
        if not _SUFFIXED_STRING_KEY.match(key.lower()):
            continue
        value = inputs[key]
        text = None
        if isinstance(value, str) and value.strip():
            text = value.strip()
        elif isinstance(value, list):
            text = _resolve_string(nodes, value, visited)
        if text and text not in parts:
            parts.append(text)
    if parts:
        delimiter = inputs.get("delimiter")
        return (delimiter if isinstance(delimiter, str) else " ").join(parts)
    return None


def _link_target(value: Any) -> str | None:
    """Die Ziel-Knoten-ID eines Graph-Links ``[node_id, slot]`` (oder None)."""
    if isinstance(value, list) and len(value) == 2:
        return str(value[0])
    return None


def _is_text_encoder(node: dict[str, Any]) -> bool:
    # CLIPTextEncode*, TextEncodeQwenImage, … — moderne Templates (Krea 2
    # Turbo als Subgraph) bringen eigene Encoder-Klassen mit.
    return "textencode" in str(node.get("class_type", "")).lower()


