"""Tests für die Schicht-2-Parser und ihre Registry (ADR 0004/0011)."""

from __future__ import annotations

import json

from feral.extract.types import RawMetadataItem
from feral.interpret import interpret_items
from feral.interpret import a1111, comfyui


def text_item(keyword: str, text: str, *, source: str = "png:tEXt") -> RawMetadataItem:
    return RawMetadataItem(
        source=source, keyword=keyword, text=text, data=None, encoding="latin-1"
    )


# --- A1111 -------------------------------------------------------------------

A1111_FULL = (
    "a majestic strawberry,\nphotorealistic\n"
    "Negative prompt: blurry, low quality\n"
    'Steps: 28, Sampler: DPM++ 2M, Schedule type: Karras, CFG scale: 6.5, '
    'Seed: 3126547890, Size: 832x1216, Model hash: 1a2b3c4d, '
    'Model: juggernautXL_v9, Denoising strength: 0.4, '
    'Lora hashes: "detail: aabbcc, style: ddeeff", Version: v1.9.0'
)


def _fields(interpretation):
    out: dict[str, list[str]] = {}
    for f in interpretation.fields:
        out.setdefault(f.field, []).append(f.value)
    return out


def test_a1111_full_infotext():
    result = a1111.parse([text_item("parameters", A1111_FULL)])

    assert result is not None and result.parser == "a1111"
    fields = _fields(result)
    assert fields["tool"] == ["a1111"]
    assert fields["prompt"] == ["a majestic strawberry,\nphotorealistic"]
    assert fields["negative_prompt"] == ["blurry, low quality"]
    assert fields["steps"] == ["28"]
    assert fields["sampler"] == ["DPM++ 2M"]
    assert fields["scheduler"] == ["Karras"]
    assert fields["cfg_scale"] == ["6.5"]
    assert fields["seed"] == ["3126547890"]
    assert fields["size"] == ["832x1216"]
    assert fields["model"] == ["juggernautXL_v9"]
    assert fields["model_hash"] == ["1a2b3c4d"]
    assert fields["denoise"] == ["0.4"]


def test_a1111_prompt_only():
    result = a1111.parse([text_item("parameters", "just a prompt, no settings")])
    fields = _fields(result)
    assert fields["prompt"] == ["just a prompt, no settings"]
    assert "seed" not in fields


def test_a1111_not_applicable_without_parameters_keyword():
    assert a1111.parse([text_item("title", "nur ein Titel")]) is None


# --- ComfyUI -----------------------------------------------------------------

COMFY_GRAPH = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 863155, "steps": 25, "cfg": 7.5,
            "sampler_name": "euler_ancestral", "scheduler": "normal",
            "denoise": 1.0,
            "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
            "latent_image": ["5", 0],
        },
    },
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "flux1-dev.safetensors"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a feral strawberry", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry", "clip": ["4", 1]}},
    "10": {"class_type": "LoraLoader", "inputs": {"lora_name": "detail.safetensors", "model": ["4", 0]}},
}


def test_comfyui_prompt_graph():
    result = comfyui.parse(
        [text_item("prompt", json.dumps(COMFY_GRAPH), source="png:iTXt")]
    )

    assert result is not None and result.parser == "comfyui"
    fields = _fields(result)
    assert fields["tool"] == ["comfyui"]
    assert fields["seed"] == ["863155"]
    assert fields["steps"] == ["25"]
    assert fields["cfg_scale"] == ["7.5"]
    assert fields["sampler"] == ["euler_ancestral"]
    assert fields["scheduler"] == ["normal"]
    assert fields["model"] == ["flux1-dev.safetensors"]
    assert fields["lora"] == ["detail"]  # normalisiert (Pfad/Endung weg)
    assert fields["prompt"] == ["a feral strawberry"]
    assert fields["negative_prompt"] == ["blurry"]


def test_comfyui_video_graph_resolves_polarity_through_intermediates():
    # Nachgebaut nach echten LTX-/Wan-Video-Workflows: Sampler → Guider →
    # Conditioning-Zwischenknoten → Text; Positiv-Text kommt zusätzlich über
    # eine String-Kette (Prompt-Enhancer → Primitive). Negativ ist Literal.
    graph = {
        "215": {"class_type": "SamplerCustomAdvanced", "inputs": {"guider": ["213", 0]}},
        "213": {"class_type": "CFGGuider",
                "inputs": {"positive": ["212", 0], "negative": ["212", 1], "cfg": 3.0}},
        "212": {"class_type": "LTXVCropGuides",
                "inputs": {"positive": ["239", 0], "negative": ["239", 1]}},
        "239": {"class_type": "LTXVConditioning",
                "inputs": {"positive": ["240", 0], "negative": ["247", 0]}},
        "240": {"class_type": "CLIPTextEncode", "inputs": {"text": ["274", 0]}},
        "247": {"class_type": "CLIPTextEncode",
                "inputs": {"text": "pc game, cartoon, childish, ugly"}},
        "274": {"class_type": "TextGenerateLTX2Prompt",
                "inputs": {"prompt": ["266", 0], "max_length": 256}},
        "266": {"class_type": "PrimitiveStringMultiline",
                "inputs": {"value": "cinematic machinery self-assembling, 8K"}},
        "300": {"class_type": "RandomNoise", "inputs": {"noise_seed": 731987174230470}},
    }
    result = comfyui.parse([text_item("PROMPT", json.dumps(graph), source="matroska:format.tag")])

    fields = _fields(result)
    assert fields["negative_prompt"] == ["pc game, cartoon, childish, ugly"]
    assert fields["prompt"] == ["cinematic machinery self-assembling, 8K"]
    assert fields["seed"] == ["731987174230470"]
    # Der Negativ-Text darf NIE als Positiv-Kandidat auftauchen.
    assert "pc game, cartoon, childish, ugly" not in fields["prompt"]


def test_comfyui_polarity_cycle_does_not_hang():
    graph = {
        "1": {"class_type": "CFGGuider", "inputs": {"positive": ["2", 0]}},
        "2": {"class_type": "ConditioningCombine", "inputs": {"positive": ["1", 0]}},
    }
    result = comfyui.parse([text_item("prompt", json.dumps(graph))])
    assert _fields(result)["tool"] == ["comfyui"]  # terminiert, kein Text gefunden


def test_comfyui_workflow_only_yields_tool_field():
    result = comfyui.parse(
        [text_item("workflow", '{"nodes": [], "links": []}', source="png:iTXt")]
    )
    assert result is not None
    assert _fields(result)["tool"] == ["comfyui"]


def test_comfyui_unlinked_text_nodes_become_prompt_candidates():
    graph = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "orphan prompt"}},
    }
    result = comfyui.parse([text_item("prompt", json.dumps(graph))])
    assert _fields(result)["prompt"] == ["orphan prompt"]


def test_comfyui_uppercase_video_tags():
    # Matroska normalisiert Tag-Namen auf Großschreibung: PROMPT/WORKFLOW.
    result = comfyui.parse(
        [text_item("PROMPT", json.dumps(COMFY_GRAPH), source="matroska:format.tag")]
    )
    assert result is not None
    fields = _fields(result)
    assert fields["prompt"] == ["a feral strawberry"]
    assert fields["model"] == ["flux1-dev.safetensors"]


def test_comfyui_not_applicable_for_foreign_metadata():
    assert comfyui.parse([text_item("parameters", "Steps: 20")]) is None


def test_comfyui_broken_json_is_not_a_crash():
    result = comfyui.parse([text_item("prompt", "{kein json")])
    assert result is None  # weder Graph noch workflow → nicht zuständig


# --- Registry ----------------------------------------------------------------

def test_registry_runs_all_applicable_parsers():
    items = [
        text_item("parameters", A1111_FULL),
        text_item("workflow", '{"nodes": []}'),
    ]
    results = interpret_items(items)
    assert {r.parser for r in results} == {"a1111", "comfyui"}


def test_registry_empty_input_yields_nothing():
    assert interpret_items([]) == []


# -- v4: Generator-/API-Knoten (Krea 2, Ideogram 4) + generische Text-Encoder -------


def _comfy_items(graph: dict) -> list:
    import json as _json

    from feral.extract.types import RawMetadataItem

    return [RawMetadataItem(source="png:tEXt", keyword="prompt",
                            text=_json.dumps(graph), data=None, encoding="utf-8")]


def test_generator_node_with_direct_prompt_string():
    """Krea-2-Turbo-artiger API-Knoten: Prompt hängt direkt am Generator."""
    from feral.interpret import comfyui

    graph = {
        "1": {"class_type": "Krea2ImageNode", "inputs": {
            "prompt": "crystal fox in a neon forest",
            "seed": 42, "aspect_ratio": "1:1",
        }},
        "2": {"class_type": "LoraLoaderModelOnly", "inputs": {
            "lora_name": "krea-style.safetensors", "strength_model": 0.8,
        }},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
    }
    fields = {f.field: f.value for f in comfyui.parse(_comfy_items(graph)).fields}
    assert fields["prompt"] == "crystal fox in a neon forest"
    assert fields["seed"] == "42"
    assert fields["lora"] == "krea-style"  # normalisiert


def test_qwen_style_text_encoder_is_recognized():
    """Krea 2 Turbo lokal (Subgraph geflattet): eigener Text-Encoder statt
    CLIPTextEncode — Klassenname enthält 'TextEncode'."""
    from feral.interpret import comfyui

    graph = {
        "30:6": {"class_type": "TextEncodeQwenImage", "inputs": {
            "clip": ["30:5", 0], "prompt": "misty harbor at dawn",
        }},
        "30:3": {"class_type": "KSampler", "inputs": {
            "seed": 7, "steps": 8, "cfg": 1.0, "sampler_name": "euler",
            "scheduler": "simple", "denoise": 1.0,
            "positive": ["30:6", 0], "negative": ["30:7", 0],
            "model": ["30:1", 0], "latent_image": ["30:5", 0],
        }},
        "30:7": {"class_type": "TextEncodeQwenImage", "inputs": {
            "clip": ["30:5", 0], "prompt": "blurry, lowres",
        }},
    }
    fields = {f.field: f.value for f in comfyui.parse(_comfy_items(graph)).fields}
    assert fields["prompt"] == "misty harbor at dawn"
    assert fields["negative_prompt"] == "blurry, lowres"


def test_ideogram4_prompt_builder_chain():
    """Ideogram 4 (KJ): Generator bekommt den Prompt als Link vom
    Ideogram4PromptBuilderKJ — dessen high_level_description ist das beste
    eingebettete Substrat des BBOX/JSON-Prompts."""
    from feral.interpret import comfyui

    graph = {
        "1": {"class_type": "Ideogram4PromptBuilderKJ", "inputs": {
            "width": 1024, "height": 1024,
            "high_level_description": "a lighthouse on a cliff, poster style",
            "background": "stormy sea", "style": "art_style",
        }},
        "2": {"class_type": "IdeogramV4", "inputs": {
            "prompt": ["1", 0], "resolution": "1024x1024", "seed": 99,
        }},
        "3": {"class_type": "SaveImage", "inputs": {"images": ["2", 0]}},
    }
    fields = {f.field: f.value for f in comfyui.parse(_comfy_items(graph)).fields}
    assert fields["prompt"] == "a lighthouse on a cliff, poster style"
    assert fields["seed"] == "99"


# -- v5: LoRA-Sammler (Stacker/rgthree) + Modell-Rückverfolgung ---------------


def test_comfyui_rgthree_power_lora_loader():
    """rgthree Power Lora Loader: pro Slot ein Dict; ausgeschaltete zählen nicht."""
    graph = {
        "5": {"class_type": "Power Lora Loader (rgthree)", "inputs": {
            "model": ["4", 0], "clip": ["4", 1],
            "lora_1": {"on": True, "lora": "styles/detail.safetensors", "strength": 1.0},
            "lora_2": {"on": False, "lora": "aus.safetensors", "strength": 0.5},
            "lora_3": {"on": True, "lora": "char\\hero.safetensors", "strength": 0.8},
        }},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["lora"] == ["detail", "hero"]  # normalisiert, "aus" ist off


def test_comfyui_lora_stacker_respects_switches():
    """LoRA-Stacker: lora_name_1…N; deaktivierte Slots (switch/None) fallen raus."""
    graph = {
        "9": {"class_type": "LoRA Stacker", "inputs": {
            "lora_count": 3,
            "lora_name_1": "one.safetensors", "switch_1": "On",
            "lora_name_2": "None", "switch_2": "On",
            "lora_name_3": "three.safetensors", "switch_3": "Off",
        }},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["lora"] == ["one"]  # None übersprungen, three ist Off


def test_comfyui_model_traced_through_lora_chain():
    """Das benutzte Modell wird durch LoraLoader hindurch verfolgt; ein
    Nebenzweig-Checkpoint (Upscale) taucht NICHT als model auf."""
    graph = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "base.safetensors"}},
        "2": {"class_type": "LoraLoader",
              "inputs": {"lora_name": "x.safetensors", "model": ["1", 0]}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": 1, "sampler_name": "euler", "model": ["2", 0],
            "positive": ["5", 0], "negative": ["6", 0],
        }},
        "4": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "upscale-only.safetensors"}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry"}},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["model"] == ["base.safetensors"]  # nicht upscale-only
    assert fields["lora"] == ["x"]


def test_comfyui_model_fallback_when_no_sampler_trace():
    """Ohne verfolgbaren Sampler-Link bleibt der Rückfall: alle Loader-Modelle."""
    graph = {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "solo.safetensors"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "a lone prompt"}},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["model"] == ["solo.safetensors"]


# -- A1111 v2: LoRA-Erkennung -------------------------------------------------


def test_a1111_inline_lora_and_lyco_tags():
    text = (
        "a castle <lora:detail_xl:0.8> at dusk <lyco:subdir/style.safetensors:1>\n"
        "Negative prompt: blur <lora:badhands:0.5>\n"
        "Steps: 20, Sampler: Euler a"
    )
    fields = _fields(a1111.parse([text_item("parameters", text)]))
    assert fields["lora"] == ["detail_xl", "style", "badhands"]


def test_a1111_lora_hashes_and_dedup_with_inline():
    text = (
        "a fox <lora:detail:0.7>\n"
        "Steps: 20, Model: sdxl, "
        'Lora hashes: "detail: aabbcc, extra: ddeeff", Version: v1.9.0'
    )
    fields = _fields(a1111.parse([text_item("parameters", text)]))
    # inline "detail" + hashes "detail","extra" → einmal detail, plus extra
    assert fields["lora"] == ["detail", "extra"]
    assert fields["model"] == ["sdxl"]


def test_a1111_full_infotext_now_yields_lora_from_hashes():
    fields = _fields(a1111.parse([text_item("parameters", A1111_FULL)]))
    assert fields["lora"] == ["detail", "style"]  # aus der Lora-hashes-Zeile


# -- v6/v3: generische LoRA-Erkennung, Workflow-Fallback, Eingangsbild, Features


def test_comfyui_pysssss_lora_dict_with_content():
    """LoraLoader|pysssss serialisiert lora_name als Dict mit 'content'."""
    graph = {
        "1": {"class_type": "LoraLoader|pysssss", "inputs": {
            "lora_name": {"content": "chars/elf.safetensors", "image": None},
            "strength_model": 1.0,
        }},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["lora"] == ["elf"]


def test_comfyui_generic_lora_input_needs_model_extension():
    """Unbekannte Klassen: Input mit 'lora' im Namen zählt nur, wenn der Wert
    eine Modelldatei benennt — Modus-Strings werden nie als LoRA geraten."""
    graph = {
        "1": {"class_type": "SomeExoticLoader", "inputs": {
            "my_lora_file": "styles/neon.safetensors",
            "lora_mode": "simple",  # kein Dateiname → ignorieren
        }},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["lora"] == ["neon"]


def test_comfyui_efficiency_stacker_respects_lora_count():
    """efficiency-nodes serialisieren ALLE Slots; aktiv sind nur lora_count."""
    graph = {
        "1": {"class_type": "LoRA Stacker", "inputs": {
            "input_mode": "simple", "lora_count": 1,
            "lora_name_1": "one.safetensors",
            "lora_name_2": "leiche.safetensors",  # über lora_count → inaktiv
        }},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["lora"] == ["one"]


def test_comfyui_input_image_detected():
    """LoadImage/VHS_LoadVideo ⇒ input_image-Feld (img2img/i2v-Erkennung)."""
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "quelle.png", "upload": "image"}},
        "2": {"class_type": "VHS_LoadVideo", "inputs": {"video": "clip.mp4"}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": 5, "sampler_name": "euler", "denoise": 0.6,
            "positive": ["4", 0], "negative": ["4", 0], "model": ["9", 0],
        }},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": "x"}},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["input_image"] == ["quelle.png", "clip.mp4"]


def test_comfyui_pure_t2i_has_no_input_image():
    fields = _fields(comfyui.parse(_comfy_items(COMFY_GRAPH)))
    assert "input_image" not in fields


def test_comfyui_workflow_only_fallback_with_bypass():
    """Nur workflow-Blob (kein prompt): LoRAs aus widgets_values; Knoten mit
    mode 4 (bypassed) / 2 (muted) werden übersprungen."""
    workflow = {
        "nodes": [
            {"id": 1, "type": "Power Lora Loader (rgthree)", "mode": 0,
             "widgets_values": [
                 {"type": "PowerLoraLoaderHeaderWidget"},
                 {"on": True, "lora": "styles/glow.safetensors", "strength": 1.0},
                 {"on": False, "lora": "aus.safetensors", "strength": 1.0},
             ]},
            {"id": 2, "type": "LoraLoader", "mode": 4,  # bypassed
             "widgets_values": ["bypassed.safetensors", 1.0, 1.0]},
            {"id": 3, "type": "LoraLoader", "mode": 0,
             "widgets_values": ["aktiv.safetensors", 1.0, 1.0]},
            {"id": 4, "type": "LoadImage", "mode": 0,
             "widgets_values": ["eingang.png", "image"]},
            {"id": 5, "type": "LoadImage", "mode": 2,  # muted
             "widgets_values": ["stumm.png", "image"]},
        ],
        "links": [],
    }
    result = comfyui.parse([text_item("workflow", json.dumps(workflow))])
    fields = _fields(result)
    assert fields["lora"] == ["glow", "aktiv"]
    assert fields["input_image"] == ["eingang.png"]


def test_a1111_feature_detection():
    text = (
        "portrait <lora:face:0.6>\n"
        "Steps: 30, Sampler: DPM++ 2M, Hires upscale: 2, Hires upscaler: 4x-UltraSharp, "
        'ADetailer model: face_yolov8n.pt, ADetailer confidence: 0.3, '
        'ControlNet 0: "Module: canny, Model: control_v11p_sd15_canny [d14c016b], Weight: 1", '
        "Refiner: sdxl_refiner [abc], Model: sdxl_base"
    )
    fields = _fields(a1111.parse([text_item("parameters", text)]))
    assert fields["feature"] == ["highres_fix", "adetailer", "controlnet", "refiner"]
    assert fields["lora"] == ["face"]
    assert fields["model"] == ["sdxl_base"]


def test_a1111_no_features_no_field():
    fields = _fields(a1111.parse([text_item("parameters", A1111_FULL)]))
    assert "feature" not in fields


def test_comfyui_rgthree_lora_stack_padded_keys_and_zero_strength():
    """Lora Loader Stack (rgthree): zero-gepaddete Keys lora_01…, Gewicht 0 = aus."""
    graph = {
        "1": {"class_type": "Lora Loader Stack (rgthree)", "inputs": {
            "lora_01": "a.safetensors", "strength_01": 1.0,
            "lora_02": "b.safetensors", "strength_02": 0,  # aus
            "lora_03": "None", "strength_03": 1.0,
            "lora_04": "d.safetensors", "strength_04": 0.6,
            "model": ["4", 0], "clip": ["4", 1],
        }},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["lora"] == ["a", "d"]


def test_comfyui_power_lora_zero_strength_slot_skipped():
    """rgthree-Backend überspringt strength==0 (ohne strengthTwo) — wir auch."""
    graph = {
        "5": {"class_type": "Power Lora Loader (rgthree)", "inputs": {
            "PowerLoraLoaderHeaderWidget": {"type": "PowerLoraLoaderHeaderWidget"},
            "lora_1": {"on": True, "lora": "tot.safetensors", "strength": 0},
            "lora_2": {"on": True, "lora": "cliponly.safetensors",
                       "strength": 0, "strengthTwo": 0.9},
            "➕ Add Lora": "",
            "model": ["1", 0],
        }},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["lora"] == ["cliponly"]


def test_comfyui_power_prompt_inline_tags():
    """rgthree Power Prompt: LoRAs als <lora:>-Tags im Prompt-String."""
    graph = {
        "1": {"class_type": "Power Prompt (rgthree)", "inputs": {
            "prompt": "castle at night <lora:gothic:0.9> <lyco:mist:0.4>",
            "opt_model": ["2", 0], "opt_clip": ["2", 1],
        }},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["lora"] == ["gothic", "mist"]


def test_comfyui_lora_name_behind_link_resolved():
    """Krea-2-Subgraph-Muster: lora_name kommt als Link vom Subgraph-Rand;
    der Quellknoten hält den Dateinamen. model/clip-Links werden NICHT
    verfolgt (sonst würde das Checkpoint zum LoRA)."""
    graph = {
        "30:15": {"class_type": "LoraLoaderModelOnly", "inputs": {
            "lora_name": ["30:99", 0], "strength_model": 0.8, "model": ["30:1", 0],
        }},
        "30:99": {"class_type": "PrimitiveCombo",
                  "inputs": {"value": "krea2_darkbrush.safetensors"}},
        "30:1": {"class_type": "UNETLoader",
                 "inputs": {"unet_name": "krea2_turbo_fp8_scaled.safetensors"}},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["lora"] == ["krea2_darkbrush"]


def test_comfyui_input_image_output_annotation_stripped():
    """LoadImageOutput annotiert den Dateinamen mit ' [output]' — abstreifen."""
    graph = {
        "1": {"class_type": "LoadImageOutput", "inputs": {"image": "gen_0042.png [output]"}},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["input_image"] == ["gen_0042.png"]


# -- v8: Prompt-Builder (Ideogram 4 KJ & Co.) als Substrat + Hinweislabel ------


def test_comfyui_prompt_builder_broken_chain_uses_description():
    """Feral Strawberrys Ideogram-4-Builder-Workflows (2026-07-08): der Weg vom Encoder
    zum Builder reißt an StringConcatenate/Enhancer-Knoten ab — die
    Szenenbeschreibung des Builders wird trotzdem als prompt geführt,
    markiert mit feature: prompt_builder (+ bbox bei Regionen-JSON)."""
    boxes = ('[{"x":0,"y":0.58,"w":1,"h":0.42,"type":"obj","text":"",'
             '"desc":"diner table","palette":[]}]')
    graph = {
        "1": {"class_type": "Ideogram4PromptBuilderKJ", "inputs": {
            "width": 1968, "height": 1024,
            "high_level_description": "a cinematic dining scene in an ancient barn",
            "background": "barn by night", "boxes": boxes,
        }},
        # Anreicherung: Builder → Concatenate (string_a/b — Kette reißt) → Encoder
        "2": {"class_type": "StringConcatenate", "inputs": {
            "string_a": ["1", 0], "string_b": "rewrite as JSON", "delimiter": " ",
        }},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": ["2", 0]}},
        "4": {"class_type": "KSampler", "inputs": {
            "seed": 5, "positive": ["3", 0], "model": ["9", 0],
        }},
        "9": {"class_type": "UNETLoader", "inputs": {"unet_name": "flux2.safetensors"}},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    # v9: Der Positiv-Pfad löst die Concatenate-Kette jetzt zusätzlich auf
    # (Szene + Anreicherungs-Suffix) — das Builder-Substrat bleibt vorn.
    assert fields["prompt"] == [
        "a cinematic dining scene in an ancient barn",
        "a cinematic dining scene in an ancient barn rewrite as JSON",
    ]
    assert fields["feature"] == ["prompt_builder", "bbox"]
    assert fields["model"] == ["flux2.safetensors"]


def test_comfyui_bbox_detection_is_strict():
    """Kein bbox-Label für beliebige JSON-Listen — nur x/y/w/h-Strukturen."""
    graph = {
        "1": {"class_type": "SomeNode", "inputs": {
            "data": '["a", "b"]', "other": '[{"x": 1}]',
        }},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert "feature" not in fields


def test_comfyui_workflow_fallback_prompt_builder():
    """Nur workflow-Blob: der erste Text-Widget des Builders (weder BBOX-JSON
    noch Datei) ist die Szenenbeschreibung; Labels wie im prompt-Pfad."""
    boxes = '[{"x":0,"y":0,"w":1,"h":1,"desc":"sky"}]'
    workflow = {
        "nodes": [
            {"id": 1, "type": "Ideogram4PromptBuilderKJ", "mode": 0,
             "widgets_values": [1968, 1024, "a lighthouse on a cliff",
                                "stormy sea", "photo", boxes, 63]},
        ],
        "links": [],
    }
    fields = _fields(comfyui.parse([text_item("workflow", json.dumps(workflow))]))
    assert fields["prompt"] == ["a lighthouse on a cliff"]
    assert fields["feature"] == ["prompt_builder", "bbox"]


# -- v9: String-Ketten (Feral Strawberrys Krea-2-Befund, --prompt-report 2026-07-09) ------


def test_comfyui_string_concatenate_chain_resolved():
    """Krea-2-Muster aus dem Report: Encoder → StringConcatenate →
    PrimitiveStringMultiline; Teile werden mit delimiter zusammengesetzt."""
    graph = {
        "10": {"class_type": "PrimitiveStringMultiline",
               "inputs": {"value": "a red fox sleeping in golden leaves"}},
        "11": {"class_type": "StringConcatenate", "inputs": {
            "string_a": ["10", 0], "string_b": "monochrome ink wash style",
            "delimiter": ", ",
        }},
        "12": {"class_type": "CLIPTextEncode", "inputs": {"text": ["11", 0]}},
        "13": {"class_type": "KSampler", "inputs": {
            "seed": 1, "positive": ["12", 0],
        }},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["prompt"] == [
        "a red fox sleeping in golden leaves, monochrome ink wash style"
    ]


def test_comfyui_unreached_encoder_resolves_links():
    """Reißt der Conditioning-Pfad an einem unbekannten Guider ab, wird der
    Encoder-Text trotzdem als Kandidat geführt — v9 auch hinter Links."""
    graph = {
        "1": {"class_type": "PrimitiveStringMultiline",
              "inputs": {"value": "misty harbor at dawn"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ["1", 0]}},
        # Guider mit unbekannten Input-Namen: Polaritäts-Pfad endet hier.
        "3": {"class_type": "ExoticGuider", "inputs": {"cond_pos": ["2", 0]}},
        "4": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise_seed": 7, "guider": ["3", 0],
        }},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["prompt"] == ["misty harbor at dawn"]


def test_comfyui_any_switch_on_text_path():
    """rgthree Any Switch zwischen Encoder und String-Quelle (any_01 …)."""
    graph = {
        "1": {"class_type": "PrimitiveStringMultiline",
              "inputs": {"value": "stormy coastline with dramatic clouds"}},
        "2": {"class_type": "Any Switch (rgthree)", "inputs": {
            "any_01": ["1", 0], "any_02": None,
        }},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": ["2", 0]}},
        "4": {"class_type": "KSampler", "inputs": {
            "seed": 3, "positive": ["3", 0],
        }},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["prompt"] == ["stormy coastline with dramatic clouds"]


def test_comfyui_numbered_textbox_and_sdxl_dedup():
    """TextBox1 (text1, aus dem Report) wird aufgelöst; SDXL-Encoder mit
    text_g == text_l liefert den Text nur EINMAL."""
    graph = {
        "1": {"class_type": "TextBox1",
              "inputs": {"text1": "a blonde woman with voluminous sidebuns"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ["1", 0]}},
        "3": {"class_type": "KSampler", "inputs": {"seed": 1, "positive": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncodeSDXL", "inputs": {
            "text_g": "castle on a hill", "text_l": "castle on a hill",
        }},
        "6": {"class_type": "KSampler", "inputs": {"seed": 2, "positive": ["5", 0]}},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["prompt"] == [
        "a blonde woman with voluminous sidebuns", "castle on a hill",
    ]


def test_comfyui_graph_under_foreign_keyword():
    """Graph im MP4-comment-Tag (Report: fremdes-keyword) — Struktur zählt,
    nicht das Keyword."""
    graph = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {"text": "neon alley"}},
        "2": {"class_type": "KSampler", "inputs": {"seed": 9, "positive": ["1", 0]}},
    }
    items = [RawMetadataItem(source="isobmff:format.tag", keyword="comment",
                             text=json.dumps(graph), data=None, encoding="utf-8")]
    fields = _fields(comfyui.parse(items))
    assert fields["tool"] == ["comfyui"]
    assert fields["prompt"] == ["neon alley"]


# -- v10: Prompt-Enhancer-Ketten (Ernie Image, Krea 2) — ADR 0050 -------------


def test_comfyui_enhancer_on_falls_back_to_user_prompt():
    """Ernie-Image-Muster (Enhancer AN): der gewählte Switch-Zweig endet im
    TextGenerate (Laufzeit-Text) — der Roh-Prompt-Zweig (on_false) liefert;
    die Systemprompt-Schablone der StringReplace-Kette bleibt außen vor."""
    graph = {
        "88:94": {"class_type": "PrimitiveStringMultiline",
                  "inputs": {"value": "A stylized cinematic side-profile"}},
        "88:93": {"class_type": "StringReplace", "inputs": {
            "string": "[SYSTEM_PROMPT]Du bist ein Prompt-Enhancer"
                      "[/SYSTEM_PROMPT][INST]{prompt}[/INST]",
            "find": "{prompt}", "replace": ["88:94", 0]}},
        "88:95": {"class_type": "TextGenerate", "inputs": {
            "clip": ["88:98", 0], "prompt": ["88:93", 0], "max_length": 2048}},
        "88:96": {"class_type": "PrimitiveBoolean", "inputs": {"value": True}},
        "88:97": {"class_type": "ComfySwitchNode", "inputs": {
            "on_false": ["88:94", 0], "on_true": ["88:95", 0],
            "switch": ["88:96", 0]}},
        "88:67": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["88:62", 0], "text": ["88:97", 0]}},
        "88:91": {"class_type": "ConditioningZeroOut",
                  "inputs": {"conditioning": ["88:67", 0]}},
        "88:66": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": "ernie-image-turbo.safetensors"}},
        "88:70": {"class_type": "KSampler", "inputs": {
            "seed": 42, "steps": 8, "positive": ["88:67", 0],
            "negative": ["88:91", 0], "model": ["88:66", 0]}},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["prompt"] == ["A stylized cinematic side-profile"]
    assert "negative_prompt" not in fields  # ZeroOut = leeres Negativ
    assert fields["model"] == ["ernie-image-turbo.safetensors"]
    assert fields["feature"] == ["prompt_enhancer"]  # Enhancer war AN


def test_comfyui_enhancer_off_yields_user_prompt_not_system_prompt():
    """Krea-2-Muster (Enhancer AUS): on_false-Zweig führt über PreviewAny und
    einen zweiten Switch zum User-Prompt; die Systemprompt-Konkatenation am
    TextGenerate wird nicht als Prompt geführt. Modell durch den
    enable_lora-Switch hindurch zurückverfolgt."""
    graph = {
        "30:18": {"class_type": "PrimitiveStringMultiline",
                  "inputs": {"value": "You are an expert prompt engineer"}},
        "30:19": {"class_type": "PrimitiveStringMultiline",
                  "inputs": {"value": "A vibrant cyberpunk bar scene"}},
        "30:17": {"class_type": "StringConcatenate", "inputs": {
            "string_a": ["30:18", 0], "string_b": ["30:19", 0],
            "delimiter": ""}},
        "30:16": {"class_type": "TextGenerate", "inputs": {
            "clip": ["30:11", 0], "prompt": ["30:17", 0], "max_length": 512}},
        "30:24": {"class_type": "PrimitiveBoolean", "inputs": {"value": False}},
        "30:21": {"class_type": "ComfySwitchNode", "inputs": {
            "on_false": ["30:19", 0], "on_true": ["30:16", 0],
            "switch": ["30:24", 0]}},
        "30:20": {"class_type": "PreviewAny", "inputs": {"source": ["30:21", 0]}},
        "30:27": {"class_type": "StringConcatenate", "inputs": {
            "string_a": ["30:20", 0], "string_b": "monochrome ink wash style",
            "delimiter": ", "}},
        "30:23": {"class_type": "PrimitiveBoolean", "inputs": {"value": False}},
        "30:28": {"class_type": "ComfySwitchNode", "inputs": {
            "on_false": ["30:20", 0], "on_true": ["30:27", 0],
            "switch": ["30:23", 0]}},
        "30:6": {"class_type": "CLIPTextEncode", "inputs": {
            "clip": ["30:11", 0], "text": ["30:28", 0]}},
        "30:51": {"class_type": "ConditioningKrea2Rebalance",
                  "inputs": {"conditioning": ["30:6", 0]}},
        "30:13": {"class_type": "ConditioningZeroOut",
                  "inputs": {"conditioning": ["30:6", 0]}},
        "30:10": {"class_type": "UNETLoader",
                  "inputs": {"unet_name": "krea2_turbo_bf16.safetensors"}},
        "30:15": {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["30:10", 0], "lora_name": "krea2_warmpastel.safetensors",
            "strength_model": 0.8}},
        "30:22": {"class_type": "ComfySwitchNode", "inputs": {
            "on_false": ["30:10", 0], "on_true": ["30:15", 0],
            "switch": ["30:23", 0]}},
        "30:3": {"class_type": "KSampler", "inputs": {
            "seed": 7, "steps": 8, "positive": ["30:51", 0],
            "negative": ["30:13", 0], "model": ["30:22", 0]}},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["prompt"] == ["A vibrant cyberpunk bar scene"]
    assert not any("prompt engineer" in v for vs in fields.values() for v in vs)
    assert "negative_prompt" not in fields
    assert fields["model"] == ["krea2_turbo_bf16.safetensors"]
    assert "feature" not in fields  # Enhancer war AUS — kein Flag


def test_comfyui_switch_with_literal_bool_and_string():
    """Switch mit Literal-Boolean und Literal-String-Zweigen (kein Link)."""
    graph = {
        "1": {"class_type": "ComfySwitchNode", "inputs": {
            "on_false": "plain harbor", "on_true": "harbor at golden hour",
            "switch": True}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ["1", 0]}},
        "3": {"class_type": "KSampler", "inputs": {"seed": 1, "positive": ["2", 0]}},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["prompt"] == ["harbor at golden hour"]


def test_comfyui_ungated_llm_generator_sets_enhancer_feature():
    """LTX-Muster: TextGenerate hängt OHNE Switch direkt in der Kette —
    Enhancer läuft immer, Prompt bleibt der Roh-Text, Flag wird gesetzt."""
    graph = {
        "1": {"class_type": "PrimitiveStringMultiline",
              "inputs": {"value": "cinematic machinery self-assembling"}},
        "2": {"class_type": "TextGenerateLTX2Prompt",
              "inputs": {"prompt": ["1", 0], "max_length": 256}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": ["2", 0]}},
        "4": {"class_type": "KSampler", "inputs": {"seed": 5, "positive": ["3", 0]}},
    }
    fields = _fields(comfyui.parse(_comfy_items(graph)))
    assert fields["prompt"] == ["cinematic machinery self-assembling"]
    assert fields["feature"] == ["prompt_enhancer"]
