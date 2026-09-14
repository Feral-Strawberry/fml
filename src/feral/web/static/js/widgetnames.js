// widgetnames.js — Widget-Beschriftung für die Workflow-Vorschau (Issue #47).
//
// ComfyUI speichert Widget-Werte im Workflow-JSON POSITIONAL (`widgets_values`
// = Liste ohne Namen; Reihenfolge = `object_info` "required", dann "optional",
// nur Widget-Eingänge, plus `control_after_generate` direkt hinter Seed-INTs).
// Um „seed 1234 · steps 20 · cfg 7" statt nackter Zahlen zu zeigen, braucht
// die Vorschau die Namen. Drei Quellen, in dieser Reihenfolge:
//
//   1. `widgets_values_named` im Node (neuere Frontends schreiben es mit) —
//      Objekt Name → Wert, autoritativ.
//   2. Ein Auszug aus der EIGENEN ComfyUI-Instanz: `python tools/dump_object_info.py`
//      schreibt `web/static/widgets.json` ({Typ: [Name, …]}) — Daten, keine
//      Abhängigkeit (§0.1). Deckt Custom-Nodes ab. Wird einmal geladen; fehlt
//      die Datei (404), gilt nur Quelle 3.
//   3. Diese eingebaute Tabelle der ComfyUI-Kernknoten (Stand der Kern-
//      `nodes.py` und `comfy_extras`, 2026-09). Für Werte, die kein Name
//      erreicht, bleibt der nackte Wert stehen — ehrlich, nie geraten.
//
// Anzeigenamen (`NODE_DISPLAY_NAME_MAPPINGS`) für die Titelzeile, wenn der
// Node keinen eigenen Titel trägt — ComfyUI zeigt „Load Checkpoint", nicht
// „CheckpointLoaderSimple".

const SEED = ["seed", "control_after_generate"];
const NOISE_SEED = ["noise_seed", "control_after_generate"];

export const CORE_WIDGETS = {
  KSampler: [...SEED, "steps", "cfg", "sampler_name", "scheduler", "denoise"],
  KSamplerAdvanced: ["add_noise", ...NOISE_SEED, "steps", "cfg", "sampler_name", "scheduler",
                     "start_at_step", "end_at_step", "return_with_leftover_noise"],
  SamplerCustom: ["add_noise", ...NOISE_SEED, "cfg"],
  RandomNoise: NOISE_SEED,
  KSamplerSelect: ["sampler_name"],
  BasicScheduler: ["scheduler", "steps", "denoise"],
  KarrasScheduler: ["steps", "sigma_max", "sigma_min", "rho"],
  ExponentialScheduler: ["steps", "sigma_max", "sigma_min"],
  SplitSigmas: ["step"],
  CFGGuider: ["cfg"],
  DualCFGGuider: ["cfg_conds", "cfg_cond2_negative"],
  CheckpointLoaderSimple: ["ckpt_name"],
  CheckpointLoader: ["config_name", "ckpt_name"],
  ImageOnlyCheckpointLoader: ["ckpt_name"],
  unCLIPCheckpointLoader: ["ckpt_name"],
  DiffusersLoader: ["model_path"],
  UNETLoader: ["unet_name", "weight_dtype"],
  VAELoader: ["vae_name"],
  CLIPLoader: ["clip_name", "type", "device"],
  DualCLIPLoader: ["clip_name1", "clip_name2", "type", "device"],
  TripleCLIPLoader: ["clip_name1", "clip_name2", "clip_name3"],
  QuadrupleCLIPLoader: ["clip_name1", "clip_name2", "clip_name3", "clip_name4"],
  CLIPVisionLoader: ["clip_name"],
  CLIPVisionEncode: ["crop"],
  StyleModelLoader: ["style_model_name"],
  StyleModelApply: ["strength", "strength_type"],
  LoraLoader: ["lora_name", "strength_model", "strength_clip"],
  LoraLoaderModelOnly: ["lora_name", "strength_model"],
  ControlNetLoader: ["control_net_name"],
  DiffControlNetLoader: ["control_net_name"],
  ControlNetApply: ["strength"],
  ControlNetApplyAdvanced: ["strength", "start_percent", "end_percent"],
  UpscaleModelLoader: ["model_name"],
  GLIGENLoader: ["gligen_name"],
  GLIGENTextBoxApply: ["text", "width", "height", "x", "y"],
  CLIPTextEncode: ["text"],
  CLIPTextEncodeSDXL: ["width", "height", "crop_w", "crop_h", "target_width", "target_height", "text_g", "text_l"],
  CLIPTextEncodeSDXLRefiner: ["ascore", "width", "height", "text"],
  CLIPTextEncodeFlux: ["clip_l", "t5xxl", "guidance"],
  CLIPTextEncodeHunyuanDiT: ["bert", "mt5xl"],
  TextEncodeQwenImageEdit: ["prompt"],
  CLIPSetLastLayer: ["stop_at_clip_layer"],
  ConditioningAverage: ["conditioning_to_strength"],
  ConditioningSetArea: ["width", "height", "x", "y", "strength"],
  ConditioningSetAreaPercentage: ["width", "height", "x", "y", "strength"],
  ConditioningSetMask: ["strength", "set_cond_area"],
  ConditioningSetTimestepRange: ["start", "end"],
  unCLIPConditioning: ["strength", "noise_augmentation"],
  FluxGuidance: ["guidance"],
  ModelSamplingFlux: ["max_shift", "base_shift", "width", "height"],
  ModelSamplingSD3: ["shift"],
  ModelSamplingAuraFlow: ["shift"],
  ModelSamplingDiscrete: ["sampling", "zsnr"],
  ModelSamplingContinuousEDM: ["sampling", "sigma_max", "sigma_min"],
  RescaleCFG: ["multiplier"],
  FreeU: ["b1", "b2", "s1", "s2"],
  FreeU_V2: ["b1", "b2", "s1", "s2"],
  PerturbedAttentionGuidance: ["scale"],
  EmptyLatentImage: ["width", "height", "batch_size"],
  EmptySD3LatentImage: ["width", "height", "batch_size"],
  EmptyHunyuanLatentVideo: ["width", "height", "length", "batch_size"],
  EmptyLTXVLatentVideo: ["width", "height", "length", "batch_size"],
  EmptyMochiLatentVideo: ["width", "height", "length", "batch_size"],
  EmptyCosmosLatentVideo: ["width", "height", "length", "batch_size"],
  WanImageToVideo: ["width", "height", "length", "batch_size"],
  WanFunControlToVideo: ["width", "height", "length", "batch_size"],
  WanVaceToVideo: ["width", "height", "length", "batch_size", "strength"],
  LTXVConditioning: ["frame_rate"],
  LTXVScheduler: ["steps", "max_shift", "base_shift", "stretch", "terminal"],
  LatentUpscale: ["upscale_method", "width", "height", "crop"],
  LatentUpscaleBy: ["upscale_method", "scale_by"],
  LatentFromBatch: ["batch_index", "length"],
  RepeatLatentBatch: ["amount"],
  LatentComposite: ["x", "y", "feather"],
  LatentBlend: ["blend_factor"],
  LatentRotate: ["rotation"],
  LatentFlip: ["flip_method"],
  LatentCrop: ["width", "height", "x", "y"],
  VAEEncodeForInpaint: ["grow_mask_by"],
  VAEDecodeTiled: ["tile_size", "overlap", "temporal_size", "temporal_overlap"],
  VAEEncodeTiled: ["tile_size", "overlap", "temporal_size", "temporal_overlap"],
  SaveImage: ["filename_prefix"],
  SaveAnimatedWEBP: ["filename_prefix", "fps", "lossless", "quality", "method"],
  SaveAnimatedPNG: ["filename_prefix", "fps", "compress_level"],
  SaveLatent: ["filename_prefix"],
  LoadLatent: ["latent"],
  LoadImage: ["image", "upload"],
  LoadImageMask: ["image", "channel", "upload"],
  LoadImageOutput: ["image"],
  LoadVideo: ["file"],
  SaveVideo: ["filename_prefix", "format", "codec"],
  CreateVideo: ["fps"],
  ImageScale: ["upscale_method", "width", "height", "crop"],
  ImageScaleBy: ["upscale_method", "scale_by"],
  ImageScaleToTotalPixels: ["upscale_method", "megapixels"],
  ImageCrop: ["width", "height", "x", "y"],
  ImagePadForOutpaint: ["left", "top", "right", "bottom", "feathering"],
  ImageSharpen: ["sharpen_radius", "sigma", "alpha"],
  ImageBlur: ["blur_radius", "sigma"],
  ImageQuantize: ["colors", "dither"],
  Canny: ["low_threshold", "high_threshold"],
  PrimitiveNode: ["value", "control_after_generate"],
  PrimitiveInt: ["value", "control_after_generate"],
  PrimitiveFloat: ["value"],
  PrimitiveString: ["value"],
  PrimitiveStringMultiline: ["value"],
  PrimitiveBoolean: ["value"],
  Note: ["text"],
  MarkdownNote: ["text"],
  VHS_VideoCombine: ["frame_rate", "loop_count", "filename_prefix", "format", "pingpong", "save_output"],
  VHS_LoadVideo: ["video", "force_rate", "force_size", "custom_width", "custom_height",
                  "frame_load_cap", "skip_first_frames", "select_every_nth"],
};

export const DISPLAY_NAMES = {
  KSampler: "KSampler", KSamplerAdvanced: "KSampler (Advanced)",
  CheckpointLoaderSimple: "Load Checkpoint", CheckpointLoader: "Load Checkpoint With Config (DEPRECATED)",
  VAELoader: "Load VAE", VAEDecode: "VAE Decode", VAEEncode: "VAE Encode",
  VAEEncodeForInpaint: "VAE Encode (for Inpainting)", VAEDecodeTiled: "VAE Decode (Tiled)",
  CLIPTextEncode: "CLIP Text Encode (Prompt)", CLIPSetLastLayer: "CLIP Set Last Layer",
  CLIPLoader: "Load CLIP", DualCLIPLoader: "DualCLIPLoader", UNETLoader: "Load Diffusion Model",
  LoraLoader: "Load LoRA", LoraLoaderModelOnly: "LoraLoaderModelOnly",
  EmptyLatentImage: "Empty Latent Image", EmptySD3LatentImage: "EmptySD3LatentImage",
  LatentUpscale: "Upscale Latent", LatentUpscaleBy: "Upscale Latent By",
  SaveImage: "Save Image", PreviewImage: "Preview Image", LoadImage: "Load Image",
  LoadImageMask: "Load Image (as Mask)", ImageScale: "Upscale Image", ImageScaleBy: "Upscale Image By",
  ImageUpscaleWithModel: "Upscale Image (using Model)", UpscaleModelLoader: "Load Upscale Model",
  ImageInvert: "Invert Image", ImagePadForOutpaint: "Pad Image for Outpainting",
  ControlNetLoader: "Load ControlNet Model", ControlNetApply: "Apply ControlNet (OLD)",
  ControlNetApplyAdvanced: "Apply ControlNet", CLIPVisionLoader: "Load CLIP Vision",
  CLIPVisionEncode: "CLIP Vision Encode", StyleModelLoader: "Load Style Model",
  StyleModelApply: "Apply Style Model", ConditioningCombine: "Conditioning (Combine)",
  ConditioningAverage: "Conditioning (Average)", ConditioningConcat: "Conditioning (Concat)",
  ConditioningSetArea: "Conditioning (Set Area)", ConditioningSetMask: "Conditioning (Set Mask)",
  ConditioningZeroOut: "ConditioningZeroOut", ConditioningSetTimestepRange: "ConditioningSetTimestepRange",
  SetLatentNoiseMask: "Set Latent Noise Mask", LatentComposite: "Latent Composite",
  LatentBlend: "Latent Blend", LatentRotate: "Rotate Latent", LatentFlip: "Flip Latent",
  LatentCrop: "Crop Latent", FluxGuidance: "FluxGuidance", ModelSamplingFlux: "ModelSamplingFlux",
  BasicScheduler: "BasicScheduler", KSamplerSelect: "KSamplerSelect", RandomNoise: "RandomNoise",
  BasicGuider: "BasicGuider", SamplerCustomAdvanced: "SamplerCustomAdvanced",
  PrimitiveNode: "Primitive", Note: "Note", MarkdownNote: "Markdown Note", Reroute: "Reroute",
  WanImageToVideo: "WanImageToVideo", VHS_VideoCombine: "Video Combine 🎥🅥🅗🅢",
  VHS_LoadVideo: "Load Video (Upload) 🎥🅥🅗🅢", SaveAnimatedWEBP: "SaveAnimatedWEBP",
};

// Quelle 2: Auszug aus der eigenen ComfyUI-Instanz, einmal geladen. Fehlt die
// Datei, bleibt die Tabelle leer — kein Fehler, keine Wiederholung.
let _instance = null;          // {Typ: [Namen]} oder {} nach Ladeversuch
let _instancePromise = null;

export function loadInstanceWidgets(fetchImpl = globalThis.fetch) {
  if (_instance) return Promise.resolve(_instance);
  if (!_instancePromise) {
    _instancePromise = (async () => {
      try {
        const r = await fetchImpl("/static/widgets.json", { cache: "force-cache" });
        _instance = r && r.ok ? (await r.json()) : {};
      } catch {
        _instance = {};
      }
      if (!_instance || typeof _instance !== "object") _instance = {};
      return _instance;
    })();
  }
  return _instancePromise;
}

/** Testhilfe/Reset: Instanz-Tabelle setzen (z. B. {} oder ein Dump). */
export function setInstanceWidgets(table) { _instance = table || {}; _instancePromise = null; }

/** Widget-Namen eines Node-Typs (Instanz-Dump vor Kern-Tabelle), oder null. */
export function widgetNamesFor(type) {
  const inst = _instance && _instance[type];
  if (Array.isArray(inst) && inst.length) return inst;
  return CORE_WIDGETS[type] || null;
}

/** Paare [Name|null, Wert] für einen Node: widgets_values_named gewinnt,
 *  sonst positional nach Namensliste; Überhang bleibt namenlos. */
export function labelWidgets(node) {
  const named = node.widgets_values_named;
  if (named && typeof named === "object" && !Array.isArray(named)) {
    return Object.entries(named).map(([k, v]) => [k, v]);
  }
  const values = Array.isArray(node.widgets_values) ? node.widgets_values
    : (node.widgets_values && typeof node.widgets_values === "object"
       ? Object.entries(node.widgets_values).map(([k, v]) => [k, v]) : null);
  if (!values) return [];
  if (values.length && Array.isArray(values[0]) && values[0].length === 2 && typeof values[0][0] === "string"
      && !Array.isArray(node.widgets_values)) {
    return values;   // Objektform (z. B. VHS_VideoCombine) → bereits Paare
  }
  const names = widgetNamesFor(node.type) || [];
  return values.map((v, i) => [names[i] ?? null, v]);
}

export function displayName(type) {
  return DISPLAY_NAMES[type] || type;
}
