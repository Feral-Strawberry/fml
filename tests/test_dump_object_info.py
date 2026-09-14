"""tools/dump_object_info.py (Issue #47): object_info → {Typ: [Widget-Namen]}."""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("dump_object_info", REPO_ROOT / "tools" / "dump_object_info.py")
doi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doi)


def test_reduce_keeps_widget_inputs_in_order_and_adds_control_after_generate():
    info = {
        "KSampler": {"input": {"required": {
            "model": ["MODEL"],
            "seed": ["INT", {"default": 0, "min": 0, "control_after_generate": True}],
            "steps": ["INT", {"default": 20}],
            "cfg": ["FLOAT", {"default": 8.0}],
            "sampler_name": [["euler", "dpmpp_2m"]],
            "scheduler": [["normal", "karras"]],
            "positive": ["CONDITIONING"], "negative": ["CONDITIONING"], "latent_image": ["LATENT"],
            "denoise": ["FLOAT", {"default": 1.0}],
        }}},
        "VAEDecode": {"input": {"required": {"samples": ["LATENT"], "vae": ["VAE"]}}},
        "LoadImage": {"input": {"required": {"image": [["a.png", "b.png"], {"image_upload": True}]},
                                "optional": {"note": ["STRING", {"multiline": True}]}}},
        "Weird": {"input": {}},
    }
    out = doi.reduce_object_info(info)
    assert out["KSampler"] == ["seed", "control_after_generate", "steps", "cfg", "sampler_name", "scheduler", "denoise"]
    assert "VAEDecode" not in out                      # nur Verbindungen → kein Eintrag
    assert out["LoadImage"] == ["image", "note"]       # required vor optional
    assert "Weird" not in out


def test_reduce_tolerates_garbage_specs():
    info = {"X": {"input": {"required": {"a": None, "b": [], "c": "STRING", "d": [42]}}}}
    assert doi.reduce_object_info(info) == {}
