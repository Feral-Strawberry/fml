// wf_fixture.mjs — realistischer ComfyUI-Workflow im LiteGraph-Speicherformat
// (Flux-Text-zu-Bild mit LoRA, Gruppe, eingeklapptem Node, Bypass, Notiz und
// einem Subgraph „Upscale") — programmatisch, keine Binärdaten (Projektregel).
// Auch die Vorher/Nachher-Vergleichsseite zu #47 rendert genau diesen Graphen.

export const SUB_ID = "8f1c2e4a-1b2c-4d5e-9f00-0123456789ab";

const node = (id, type, pos, size, extra = {}) => ({ id, type, pos, size, flags: {}, order: id, mode: 0, ...extra });

export const WORKFLOW = {
  version: 0.4, last_node_id: 12, last_link_id: 14,
  nodes: [
    node(1, "UNETLoader", [40, 120], [315, 82], {
      outputs: [{ name: "MODEL", type: "MODEL", links: [1] }],
      widgets_values: ["flux1-dev.safetensors", "default"] }),
    node(2, "DualCLIPLoader", [40, 260], [315, 106], {
      outputs: [{ name: "CLIP", type: "CLIP", links: [2] }],
      widgets_values: ["t5xxl_fp16.safetensors", "clip_l.safetensors", "flux", "default"] }),
    node(3, "VAELoader", [40, 420], [315, 58], {
      outputs: [{ name: "VAE", type: "VAE", links: [8] }],
      widgets_values: ["ae.safetensors"] }),
    node(4, "LoraLoaderModelOnly", [400, 120], [80, 30], {
      flags: { collapsed: true },
      inputs: [{ name: "model", type: "MODEL", link: 1 }],
      outputs: [{ name: "MODEL", type: "MODEL", links: [3] }],
      widgets_values: ["detail-tweaker.safetensors", 0.8] }),
    node(5, "CLIPTextEncode", [400, 260], [420, 180], {
      title: "Positive Prompt", color: "#232", bgcolor: "#353",
      inputs: [{ name: "clip", type: "CLIP", link: 2 }],
      outputs: [{ name: "CONDITIONING", type: "CONDITIONING", links: [4] }],
      widgets_values: ["a red fox sitting in fresh snow, golden hour, shallow depth of field, 85mm, film grain"] }),
    node(6, "FluxGuidance", [860, 260], [240, 58], {
      inputs: [{ name: "conditioning", type: "CONDITIONING", link: 4 }],
      outputs: [{ name: "CONDITIONING", type: "CONDITIONING", links: [5] }],
      widgets_values: [3.5] }),
    node(7, "EmptySD3LatentImage", [400, 500], [315, 106], {
      outputs: [{ name: "LATENT", type: "LATENT", links: [6] }],
      widgets_values: [1024, 1024, 1] }),
    node(8, "KSampler", [1140, 120], [315, 262], {
      inputs: [{ name: "model", type: "MODEL", link: 3 }, { name: "positive", type: "CONDITIONING", link: 5 },
               { name: "negative", type: "CONDITIONING", link: null }, { name: "latent_image", type: "LATENT", link: 6 }],
      outputs: [{ name: "LATENT", type: "LATENT", links: [7] }],
      widgets_values: [123456789, "randomize", 20, 1, "euler", "simple", 1] }),
    node(9, "VAEDecode", [1500, 120], [210, 46], {
      inputs: [{ name: "samples", type: "LATENT", link: 7 }, { name: "vae", type: "VAE", link: 8 }],
      outputs: [{ name: "IMAGE", type: "IMAGE", links: [9, 12] }] }),
    node(10, "SaveImage", [1760, 120], [315, 270], {
      inputs: [{ name: "images", type: "IMAGE", link: 9 }],
      widgets_values: ["fml/fox"] }),
    node(11, "Note", [860, 420], [240, 120], {
      color: "#432", bgcolor: "#653",
      widgets_values: ["Guidance 3.5 works best for photos.\nTry 2.0 for illustration."] }),
    node(12, SUB_ID, [1500, 260], [260, 80], {
      inputs: [{ name: "image", type: "IMAGE", link: 12 }],
      outputs: [{ name: "IMAGE", type: "IMAGE", links: [] }] }),
    node(13, "PreviewImage", [1760, 440], [210, 58], { mode: 4,
      inputs: [{ name: "images", type: "IMAGE", link: null }] }),
    node(14, "ImageSharpen", [1760, 540], [210, 106], { mode: 2,
      inputs: [{ name: "image", type: "IMAGE", link: null }],
      outputs: [{ name: "IMAGE", type: "IMAGE", links: [] }],
      widgets_values: [1, 1, 0.2] }),
  ],
  links: [
    [1, 1, 0, 4, 0, "MODEL"], [2, 2, 0, 5, 0, "CLIP"], [3, 4, 0, 8, 0, "MODEL"],
    [4, 5, 0, 6, 0, "CONDITIONING"], [5, 6, 0, 8, 1, "CONDITIONING"], [6, 7, 0, 8, 3, "LATENT"],
    [7, 8, 0, 9, 0, "LATENT"], [8, 3, 0, 9, 1, "VAE"], [9, 9, 0, 10, 0, "IMAGE"], [12, 9, 0, 12, 0, "IMAGE"],
  ],
  groups: [{ title: "Loader", bounding: [20, 40, 360, 470], color: "#3f789e" }],
  definitions: {
    subgraphs: [{
      id: SUB_ID, name: "Upscale 2x", version: 1,
      inputNode: { id: -10, bounding: [20, 60, 140, 60] },
      outputNode: { id: -20, bounding: [760, 60, 140, 60] },
      inputs: [{ id: "i1", name: "image", type: "IMAGE", linkIds: [101] }],
      outputs: [{ id: "o1", name: "IMAGE", type: "IMAGE", linkIds: [103] }],
      nodes: [
        node(101, "UpscaleModelLoader", [200, 60], [300, 58], {
          outputs: [{ name: "UPSCALE_MODEL", type: "UPSCALE_MODEL", links: [102] }],
          widgets_values: ["4x_NMKD-Siax_200k.pth"] }),
        node(102, "ImageUpscaleWithModel", [200, 180], [300, 78], {
          inputs: [{ name: "upscale_model", type: "UPSCALE_MODEL", link: 102 }, { name: "image", type: "IMAGE", link: 101 }],
          outputs: [{ name: "IMAGE", type: "IMAGE", links: [103] }] }),
      ],
      links: [
        { id: 101, origin_id: -10, origin_slot: 0, target_id: 102, target_slot: 1, type: "IMAGE" },
        { id: 102, origin_id: 101, origin_slot: 0, target_id: 102, target_slot: 0, type: "UPSCALE_MODEL" },
        { id: 103, origin_id: 102, origin_slot: 0, target_id: -20, target_slot: 0, type: "IMAGE" },
      ],
      groups: [],
    }],
  },
  extra: {},
};
