"""Tests für den generierten A1111→ComfyUI-Graphen (Block N, ADR 0044)."""

from __future__ import annotations

from feral.interpret import a1111_graph


def _fields(**overrides):
    base = {
        "tool": ["a1111"],
        "prompt": ["ein wilder wald, meisterwerk"],
        "negative_prompt": ["unscharf"],
        "steps": ["30"],
        "sampler": ["DPM++ 2M Karras"],
        "cfg_scale": ["6.5"],
        "seed": ["1234567890"],
        "size": ["832x1216"],
        "model": ["juggernautXL_v9"],
    }
    base.update(overrides)
    return base


def _node(wf, type_, index=0):
    hits = [n for n in wf["nodes"] if n["type"] == type_]
    return hits[index] if hits else None


def _links_ok(wf):
    """Jeder Link zeigt auf existierende Knoten/Slots, Buchführung stimmt."""
    by_id = {n["id"]: n for n in wf["nodes"]}
    for link_id, src, out_slot, dst, in_slot, _t in wf["links"]:
        assert link_id in [n_l for n in wf["nodes"]
                           for o in n["outputs"] for n_l in o["links"]]
        assert by_id[src]["outputs"][out_slot]["links"].count(link_id) == 1
        assert by_id[dst]["inputs"][in_slot]["link"] == link_id


def test_builds_minimal_graph_with_valid_links():
    wf = a1111_graph.build_workflow(_fields())
    types = [n["type"] for n in wf["nodes"]]
    for expected in ("CheckpointLoaderSimple", "CLIPTextEncode", "EmptyLatentImage",
                     "KSampler", "VAEDecode", "SaveImage"):
        assert expected in types
    assert types.count("CLIPTextEncode") == 2
    assert wf["last_node_id"] == len(wf["nodes"])
    assert wf["last_link_id"] == len(wf["links"])
    assert wf["extra"]["fml"]["generated_from"] == "a1111"
    _links_ok(wf)


def test_sampler_and_scheduler_mapping():
    wf = a1111_graph.build_workflow(_fields(sampler=["DPM++ 2M Karras"]))
    widgets = _node(wf, "KSampler")["widgets_values"]
    # [seed, control, steps, cfg, sampler, scheduler, denoise]
    assert widgets[0] == 1234567890
    assert widgets[2] == 30
    assert widgets[3] == 6.5
    assert widgets[4] == "dpmpp_2m"
    assert widgets[5] == "karras"
    assert widgets[6] == 1.0


def test_schedule_type_field_wins_over_suffix():
    wf = a1111_graph.build_workflow(
        _fields(sampler=["Euler a"], scheduler=["Exponential"]))
    widgets = _node(wf, "KSampler")["widgets_values"]
    assert widgets[4] == "euler_ancestral"
    assert widgets[5] == "exponential"


def test_unknown_sampler_passes_through_sanitized():
    wf = a1111_graph.build_workflow(_fields(sampler=["Fancy Sampler X"]))
    assert _node(wf, "KSampler")["widgets_values"][4] == "fancy_sampler_x"


def test_size_lands_in_latent():
    wf = a1111_graph.build_workflow(_fields())
    assert _node(wf, "EmptyLatentImage")["widgets_values"] == [832, 1216, 1]


def test_inline_lora_tags_become_loaders_and_leave_prompt():
    wf = a1111_graph.build_workflow(_fields(
        prompt=["wald <lora:baumstil:0.7>, meisterwerk"],
        lora=["baumstil"],
    ))
    lora = _node(wf, "LoraLoader")
    assert lora["widgets_values"] == ["baumstil.safetensors", 0.7, 0.7]
    positive = _node(wf, "CLIPTextEncode")
    assert "<lora:" not in positive["widgets_values"][0]
    # Kette: Checkpoint → Lora → (Encodes + Sampler)
    _links_ok(wf)


def test_lora_fields_without_inline_tags_get_weight_one():
    wf = a1111_graph.build_workflow(_fields(lora=["stil_a", "stil_b"]))
    assert _node(wf, "LoraLoader", 0)["widgets_values"][1] == 1.0
    assert _node(wf, "LoraLoader", 1)["widgets_values"][0] == "stil_b.safetensors"


def test_vae_field_adds_loader():
    wf = a1111_graph.build_workflow(_fields(vae=["sdxl_vae.safetensors"]))
    vae = _node(wf, "VAELoader")
    assert vae["widgets_values"] == ["sdxl_vae.safetensors"]
    decode = _node(wf, "VAEDecode")
    link_id = decode["inputs"][1]["link"]
    src = next(l for l in wf["links"] if l[0] == link_id)[1]
    assert src == vae["id"]


def test_without_vae_decode_uses_checkpoint():
    wf = a1111_graph.build_workflow(_fields())
    decode = _node(wf, "VAEDecode")
    ckpt = _node(wf, "CheckpointLoaderSimple")
    link = next(l for l in wf["links"] if l[0] == decode["inputs"][1]["link"])
    assert link[1] == ckpt["id"] and link[2] == 2


def test_non_a1111_fields_yield_none():
    assert a1111_graph.build_workflow({"tool": ["comfyui"]}) is None
    assert a1111_graph.build_workflow({}) is None


def test_defensive_defaults_on_garbage_values():
    wf = a1111_graph.build_workflow(_fields(
        steps=["viele"], seed=[""], cfg_scale=["?"], size=["riesig"]))
    widgets = _node(wf, "KSampler")["widgets_values"]
    assert widgets[0] == 0 and widgets[2] == 20 and widgets[3] == 7.0
    assert _node(wf, "EmptyLatentImage")["widgets_values"] == [512, 512, 1]
