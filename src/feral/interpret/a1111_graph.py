"""A1111-Infotext → minimaler, ECHTER ComfyUI-Graph (Block N, ADR 0044).

A1111-Bilder tragen keinen eingebetteten Workflow — aus den interpretierten
Feldern (Schicht 2) wird ein kleiner ComfyUI-Graph im LiteGraph-Speicherformat
gebaut: Checkpoint → (LoRA-Kette) → 2× Text-Encode → KSampler → VAE-Decode →
Save. Denselben JSON rendert die GUI mit dem bestehenden SVG-Renderer
(workflow.js), und der Download ist direkt in ComfyUI ladbar.

Best effort, ehrlich dokumentiert:
- Datei-Namen von Checkpoint/LoRAs bekommen eine Vermutungs-Endung
  ``.safetensors`` (A1111 führt keine Endungen) — ComfyUI zeigt beim Laden
  seine übliche Auswahl, wenn die Datei anders heißt.
- A1111-Sampler-Namen werden übersetzt (``Euler a`` → ``euler_ancestral``);
  ``… Karras``-Suffixe wandern in den Scheduler. Unbekannte Namen gehen
  kleingeschrieben durch (ehrlich statt geraten).
- Inline-``<lora:name:gewicht>``-Tags werden zu LoraLoader-Knoten und aus
  dem Prompt-Text entfernt (in ComfyUI wären sie toter Text).

Reine Funktion: Felder rein → Graph-Dict raus. Keine DB, kein I/O.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

# A1111-Sampler → ComfyUI ``sampler_name``.
_SAMPLER_MAP = {
    "euler a": "euler_ancestral",
    "euler": "euler",
    "lms": "lms",
    "heun": "heun",
    "dpm2": "dpm_2",
    "dpm2 a": "dpm_2_ancestral",
    "dpm++ 2s a": "dpmpp_2s_ancestral",
    "dpm++ 2m": "dpmpp_2m",
    "dpm++ sde": "dpmpp_sde",
    "dpm++ 2m sde": "dpmpp_2m_sde",
    "dpm++ 3m sde": "dpmpp_3m_sde",
    "dpm fast": "dpm_fast",
    "dpm adaptive": "dpm_adaptive",
    "ddim": "ddim",
    "ddpm": "ddpm",
    "unipc": "uni_pc",
    "uni pc": "uni_pc",
    "lcm": "lcm",
}

# Sampler-Suffixe, die in A1111 den Scheduler bezeichnen (ältere Infotexte
# ohne eigene "Schedule type:"-Angabe).
_SCHEDULER_SUFFIXES = (
    ("sgm uniform", "sgm_uniform"),
    ("exponential", "exponential"),
    ("karras", "karras"),
)

# A1111 "Schedule type" → ComfyUI ``scheduler``.
_SCHEDULER_MAP = {
    "automatic": "normal",
    "normal": "normal",
    "uniform": "simple",
    "simple": "simple",
    "karras": "karras",
    "exponential": "exponential",
    "sgm uniform": "sgm_uniform",
    "beta": "beta",
}

# Inline-LoRA-Tag im Prompt: <lora:name:gewicht[:clip-gewicht]>.
_LORA_TAG = re.compile(r"<lora:([^:>]+)(?::([\d.]+))?[^>]*>", re.IGNORECASE)

_KNOWN_EXTENSIONS = (".safetensors", ".sft", ".ckpt", ".pt", ".pth", ".gguf")


def _with_ext(name: str) -> str:
    """Vermutungs-Endung anhängen, wenn der Name keine Modell-Endung trägt."""
    return name if name.lower().endswith(_KNOWN_EXTENSIONS) else name + ".safetensors"


def _first(fields: Mapping[str, Sequence[str]], key: str, default: str = "") -> str:
    values = fields.get(key) or []
    return values[0] if values else default


def _num(value: str, default: float, *, as_int: bool = False) -> Any:
    try:
        n = float(value.replace(",", "."))
    except (ValueError, AttributeError):
        return int(default) if as_int else default
    return int(n) if as_int else n


def _map_sampler(sampler: str, schedule_type: str) -> tuple[str, str]:
    """(sampler_name, scheduler) für ComfyUI — Suffix-Scheduler beachten."""
    name = sampler.strip().lower()
    scheduler = _SCHEDULER_MAP.get(schedule_type.strip().lower(), "")
    for suffix, mapped in _SCHEDULER_SUFFIXES:
        if name.endswith(" " + suffix):
            name = name[: -len(suffix) - 1].strip()
            if not scheduler:
                scheduler = mapped
            break
    mapped_name = _SAMPLER_MAP.get(name)
    if mapped_name is None:
        # Unbekannter Sampler: kleingeschrieben/entschärft durchreichen —
        # der Graph bleibt ladbar, ComfyUI meldet den Namen dann selbst.
        mapped_name = re.sub(r"[^a-z0-9_]+", "_", name).strip("_") or "euler"
    return mapped_name, scheduler or "normal"


def _extract_loras(
    fields: Mapping[str, Sequence[str]], prompt: str, negative: str
) -> tuple[list[tuple[str, float]], str, str]:
    """LoRAs (Name, Gewicht) einsammeln; Inline-Tags aus den Texten entfernen.

    Inline-Tags tragen das Gewicht und gewinnen deshalb; ohne Inline-Tags
    fallen wir auf die interpretierten ``lora``-Felder (ADR 0026, normalisiert
    und ohne Gewicht) mit Gewicht 1.0 zurück.
    """
    loras: list[tuple[str, float]] = []
    seen: set[str] = set()
    for text in (prompt, negative):
        for match in _LORA_TAG.finditer(text):
            name = match.group(1).strip()
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            loras.append((name, _num(match.group(2) or "1", 1.0)))
    if not loras:
        for name in fields.get("lora") or []:
            if name.lower() not in seen:
                seen.add(name.lower())
                loras.append((name, 1.0))
    def clean(text: str) -> str:
        # Tag raus + Lücken glätten („wald , meister" → „wald, meister").
        text = _LORA_TAG.sub("", text)
        return re.sub(r"\s+([,.])", r"\1", re.sub(r"[ \t]{2,}", " ", text)).strip()

    return loras, clean(prompt), clean(negative)


class _Graph:
    """Kleiner LiteGraph-Bauer: Knoten + Links mit Slot-Buchführung."""

    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.links: list[list[Any]] = []

    def node(
        self,
        type_: str,
        pos: tuple[int, int],
        size: tuple[int, int],
        inputs: Sequence[tuple[str, str]],
        outputs: Sequence[tuple[str, str]],
        widgets: Sequence[Any],
        title: str | None = None,
    ) -> dict[str, Any]:
        nd: dict[str, Any] = {
            "id": len(self.nodes) + 1,
            "type": type_,
            "pos": list(pos),
            "size": list(size),
            "flags": {},
            "order": len(self.nodes),
            "mode": 0,
            "inputs": [{"name": n, "type": t, "link": None} for n, t in inputs],
            "outputs": [
                {"name": n, "type": t, "links": [], "slot_index": i}
                for i, (n, t) in enumerate(outputs)
            ],
            "properties": {},
            "widgets_values": list(widgets),
        }
        if title:
            nd["title"] = title
        self.nodes.append(nd)
        return nd

    def link(self, src: dict, out_slot: int, dst: dict, in_slot: int) -> None:
        link_id = len(self.links) + 1
        self.links.append([
            link_id, src["id"], out_slot, dst["id"], in_slot,
            src["outputs"][out_slot]["type"],
        ])
        src["outputs"][out_slot]["links"].append(link_id)
        dst["inputs"][in_slot]["link"] = link_id


def build_workflow(fields: Mapping[str, Sequence[str]]) -> dict[str, Any] | None:
    """Interpretierte a1111-Felder → ComfyUI-Workflow-Dict (oder ``None``).

    ``None``, wenn die Felder nicht vom a1111-Parser stammen — der Aufrufer
    entscheidet dann über 404 (kein Workflow verfügbar).
    """
    if "a1111" not in (fields.get("tool") or []):
        return None

    loras, prompt, negative = _extract_loras(
        fields, _first(fields, "prompt"), _first(fields, "negative_prompt")
    )
    size_match = re.match(r"(\d+)\s*x\s*(\d+)", _first(fields, "size"))
    width, height = (
        (int(size_match.group(1)), int(size_match.group(2)))
        if size_match else (512, 512)
    )
    sampler_name, scheduler = _map_sampler(
        _first(fields, "sampler", "Euler"), _first(fields, "scheduler")
    )

    g = _Graph()
    ckpt = g.node(
        "CheckpointLoaderSimple", (0, 200), (315, 98), (),
        (("MODEL", "MODEL"), ("CLIP", "CLIP"), ("VAE", "VAE")),
        [_with_ext(_first(fields, "model", "unbekannt"))],
    )

    # LoRA-Kette: model/clip laufen durch jeden Loader durch (Slots 0/1).
    model_src, model_slot = ckpt, 0
    clip_src, clip_slot = ckpt, 1
    for i, (name, weight) in enumerate(loras):
        lora = g.node(
            "LoraLoader", (360 + i * 340, 200), (315, 126),
            (("model", "MODEL"), ("clip", "CLIP")),
            (("MODEL", "MODEL"), ("CLIP", "CLIP")),
            [_with_ext(name), weight, weight],
        )
        g.link(model_src, model_slot, lora, 0)
        g.link(clip_src, clip_slot, lora, 1)
        model_src, model_slot = lora, 0
        clip_src, clip_slot = lora, 1

    base_x = 360 + len(loras) * 340
    positive = g.node(
        "CLIPTextEncode", (base_x, 40), (400, 180),
        (("clip", "CLIP"),), (("CONDITIONING", "CONDITIONING"),),
        [prompt], title="Prompt",
    )
    negative_node = g.node(
        "CLIPTextEncode", (base_x, 260), (400, 180),
        (("clip", "CLIP"),), (("CONDITIONING", "CONDITIONING"),),
        [negative], title="Negativ-Prompt",
    )
    latent = g.node(
        "EmptyLatentImage", (base_x, 480), (315, 106), (),
        (("LATENT", "LATENT"),), [width, height, 1],
    )
    sampler = g.node(
        "KSampler", (base_x + 440, 150), (315, 262),
        (("model", "MODEL"), ("positive", "CONDITIONING"),
         ("negative", "CONDITIONING"), ("latent_image", "LATENT")),
        (("LATENT", "LATENT"),),
        [
            _num(_first(fields, "seed"), 0, as_int=True), "fixed",
            _num(_first(fields, "steps"), 20, as_int=True),
            _num(_first(fields, "cfg_scale"), 7.0),
            sampler_name, scheduler,
            _num(_first(fields, "denoise"), 1.0),
        ],
    )
    decode = g.node(
        "VAEDecode", (base_x + 800, 150), (210, 46),
        (("samples", "LATENT"), ("vae", "VAE")), (("IMAGE", "IMAGE"),), (),
    )
    save = g.node(
        "SaveImage", (base_x + 800, 250), (315, 270),
        (("images", "IMAGE"),), (), ["fml"],
    )

    g.link(clip_src, clip_slot, positive, 0)
    g.link(clip_src, clip_slot, negative_node, 0)
    g.link(model_src, model_slot, sampler, 0)
    g.link(positive, 0, sampler, 1)
    g.link(negative_node, 0, sampler, 2)
    g.link(latent, 0, sampler, 3)
    g.link(sampler, 0, decode, 0)

    vae_name = _first(fields, "vae")
    if vae_name and vae_name.lower() not in ("automatic", "none"):
        vae = g.node(
            "VAELoader", (base_x + 440, 480), (315, 58), (),
            (("VAE", "VAE"),), [_with_ext(vae_name)],
        )
        g.link(vae, 0, decode, 1)
    else:
        g.link(ckpt, 2, decode, 1)
    g.link(decode, 0, save, 0)

    return {
        "last_node_id": len(g.nodes),
        "last_link_id": len(g.links),
        "nodes": g.nodes,
        "links": g.links,
        "groups": [],
        "config": {},
        # Marker für die GUI („aus dem Infotext erzeugt") — ComfyUI ignoriert
        # unbekannte extra-Schlüssel beim Laden.
        "extra": {"fml": {"generated_from": "a1111"}},
        "version": 0.4,
    }
