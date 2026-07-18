// detail.js — permanentes Metadaten-Panel rechts (Leitbild: Panel + Loupe).
//
// Reagiert auf 'selection-changed', lädt /api/item/{hash} und zeigt alle
// Schichten getrennt (Vorrangregel in docs/DESIGN.md): interpretierte Felder
// (Schicht 2, mit Parser-Herkunft) klar getrennt von Roh-Metadaten (Schicht 1,
// byte-treu mit Quell-Label) und Fundorten. Klick auf die Vorschau öffnet die
// Loupe. Rating/Tags bekommen ihren Platz im Kopf erst mit Block 3.1.

import { STRINGS } from "./strings.js";
import { displayUrl, getItem, getTags, getModels, mediaUrl, wireImageFallback, workflowUrl } from "./api.js";
import { applyModel, applyRating, applyTag, note, tagRemove } from "./curate.js";
import { emit, on } from "./main.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Kanonische Felder (interpret/types.py) → Darstellung im GENERATION-Block.
const BLOCK_FIELDS = ["prompt", "negative_prompt", "description"]; // mehrzeilig
const CHIP_FIELDS = ["sampler", "steps", "cfg_scale", "scheduler", "size", "denoise", "model_hash"];
const FIELD_LABELS = {
  prompt: "PROMPT", negative_prompt: "NEGATIVE", description: "BESCHREIBUNG",
  sampler: "SAMPLER", steps: "STEPS", cfg_scale: "CFG SCALE", scheduler: "SCHEDULER",
  size: "SIZE", denoise: "DENOISE", model_hash: "MODEL HASH", seed: "SEED",
  model: "CHECKPOINT / MODEL", lora: "LORAS", tool: "TOOL", vae: "VAE",
  credit: "CREDIT", ai_source_type: "AI-KENNZEICHNUNG", creator_tool: "CREATOR TOOL",
  rating: "RATING (EINGEBETTET)", job_id: "JOB-ID",
  feature: "FEATURES", input_image: "EINGANGSBILD",
};
const label = (f) => FIELD_LABELS[f] || f.toUpperCase();

function fmtBytes(n) {
  if (n >= 1e9) return (n / 1e9).toFixed(2) + " GB";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + " MB";
  return Math.round(n / 1024) + " KB";
}

// Seed-Varianten (Feral Strawberry, 2026-07-16): exakte Suche nach derselben Generierung
// — alles Reproduzierbare, nur der Seed variiert (Aufräumen/Vergleichen von
// Seed-Serien). Beim Modell gewinnt das manuell gesetzte (ADR 0022, wie das
// model:-Prädikat matcht). Werte mit Anführungszeichen trägt die Grammatik
// seit dem Escaping-Nachtrag zu ADR 0035 (Verdopplung in serialize/parse) —
// das frühere stille Weglassen solcher Felder machte die Suche ausgerechnet
// bei Prompts mit Zitaten unbrauchbar (nur Negativ-Prompt blieb übrig).
const SIBLING_FIELDS = ["prompt", "negative_prompt", "model", "lora",
                        "sampler", "scheduler", "steps", "cfg_scale", "size"];

function siblingPredicates(d) {
  const preds = [];
  const manualModel = (d.manual.model || "").trim();
  for (const field of SIBLING_FIELDS) {
    let values = d.interpreted.filter((f) => f.field === field).map((f) => f.value);
    if (field === "model" && manualModel) values = [manualModel];
    for (const v of new Set(values)) {
      if (!String(v).trim()) continue;
      preds.push({ kind: "field", negated: false, field, op: "=",
                   values: [{ value: String(v), exact: true }] });
    }
  }
  return preds;
}

const sechead = (title, right = "") => `
  <div class="sechead"><span class="dot"></span><span class="mlabel">${title}</span>
    <span class="secright">${right}</span></div>`;

/** 5 Rating-Punkte; data-n trägt den Wert, Klick übernimmt curate.rate(). */
const dotsHtml = (rating) =>
  [1, 2, 3, 4, 5].map((n) =>
    `<span class="rdot${rating && n <= rating ? " on" : ""}" data-n="${n}" title="${n}★"></span>`,
  ).join("");

function generationHtml(d) {
  if (!d.interpreted.length) {
    return `<div class="section">
      <div class="callout">
        <b>${STRINGS.panelNoInterpretation}</b>
        <div>${STRINGS.panelNoInterpretationHint}</div>
      </div></div>`;
  }
  const parsers = [...new Set(d.interpreted.map((f) => f.parser))];
  const by = new Map(); // field -> [values]
  for (const f of d.interpreted) {
    if (!by.has(f.field)) by.set(f.field, []);
    by.get(f.field).push(f.value);
  }
  // Negativ-Prompt unterdrücken, wenn er 1:1 dem Prompt entspricht (Feral Strawberry,
  // 2026-07-16): manche Workflows lassen sich Positiv und Negativ nicht
  // auseinanderhalten, dann steht zweimal derselbe Text da — reines Rauschen.
  // NUR Anzeige; Daten (Schicht 2) und Suche bleiben unberührt.
  const norm = (s) => String(s).replace(/\s+/g, " ").trim();
  if (by.has("negative_prompt") && by.has("prompt")) {
    const prompts = new Set(by.get("prompt").map(norm));
    if (by.get("negative_prompt").every((v) => prompts.has(norm(v)))) {
      by.delete("negative_prompt");
    }
  }
  let html = "";
  if (by.has("model")) {
    html += `<div class="kvblock"><div class="klabel">${label("model")}</div>
      <div class="vmodel">${by.get("model").map(esc).join("<br>")}</div></div>`;
  }
  const chips = CHIP_FIELDS.filter((f) => by.has(f))
    .map((f) => `<div><div class="klabel">${label(f)}</div>
      <div class="vmono">${esc(by.get(f).join(" · "))}</div></div>`);
  if (by.has("seed")) {
    chips.push(`<div><div class="klabel">${label("seed")}</div>
      <div class="vmono seedcopy" data-seed="${esc(by.get("seed")[0])}" title="${STRINGS.panelCopy}">
        ${esc(by.get("seed").join(" · "))} <span class="copyhint">${STRINGS.panelCopy}</span></div></div>`);
  }
  if (chips.length) html += `<div class="kvgrid">${chips.join("")}</div>`;
  for (const f of BLOCK_FIELDS) {
    if (!by.has(f)) continue;
    html += by.get(f).map((v) => `
      <div class="kvblock"><div class="klabel">${label(f)}</div>
        <div class="vblock${f === "negative_prompt" ? " vdim" : ""}">${esc(v)}</div></div>`).join("");
  }
  if (by.has("lora")) {
    html += `<div class="kvblock"><div class="klabel">${label("lora")}</div>
      <div class="chiprow">${by.get("lora").map((v) => `<span class="badgechip">${esc(v)}</span>`).join("")}</div></div>`;
  }
  const misc = [...by.keys()].filter((f) =>
    !["model", "seed", "lora", "tool", ...CHIP_FIELDS, ...BLOCK_FIELDS].includes(f));
  if (misc.length) {
    html += `<div class="kvgrid">${misc.map((f) => `
      <div><div class="klabel">${label(f)}</div>
        <div class="vmono">${esc(by.get(f).join(" · "))}</div></div>`).join("")}</div>`;
  }
  // Seed-Varianten (Feral Strawberry, 2026-07-16): nur anbieten, wenn es etwas
  // Exaktes zu suchen gibt — sonst wäre die Suche beliebig.
  if (by.has("prompt") || by.has("model")) {
    html += `<button type="button" class="accentbtn" id="pSiblings"
      title="${STRINGS.siblingsTitle}">🎲 ${STRINGS.siblingsBtn}</button>`;
  }
  const toolBadge = by.has("tool") ? `<span class="badgechip origin-interpretiert">${esc(by.get("tool")[0])}</span>` : "";
  const parserBadge = `<span class="badgechip" title="${STRINGS.panelParserTitle}">${esc(parsers.join(", "))}</span>`;
  return `<div class="section">${sechead(STRINGS.sectionGeneration, toolBadge + " " + parserBadge)}${html}</div>`;
}

export function initDetail() {
  const panel = document.getElementById("panel");
  let seq = 0;
  let curHash = null;   // Hash des angezeigten Items (für annotation-changed)
  let curRating = null; // aktueller Stand fürs Toggle (gleiche Zahl löscht)
  let selCount = 1;     // Größe der aktuellen Auswahl (Multiselect-Hinweis)
  let curModel = "";    // angezeigtes manuelles Modell (Doppel-Submit vermeiden)

  function renderManual(manual) {
    curRating = manual.rating;
    const dots = panel.querySelector("#pRate");
    if (dots) dots.innerHTML = dotsHtml(manual.rating);
    curModel = manual.model || "";
    const model = panel.querySelector("#pModel");
    if (model && document.activeElement !== model) model.value = curModel;
    const tags = panel.querySelector("#pTags");
    if (tags) {
      tags.innerHTML = manual.tags.length
        ? manual.tags.map((t) =>
            `<span class="badgechip tagchip">${esc(t)}<button type="button" class="tagdel" data-tag="${esc(t)}" title="${STRINGS.curateTagRemove}">✕</button></span>`,
          ).join("")
        : `<span class="vdim">${STRINGS.curateNoTags}</span>`;
    }
    const notes = panel.querySelector("#pNotes");
    if (notes && document.activeElement !== notes) notes.value = manual.notes || "";
  }

  async function fillVocabulary() {
    try {
      const d = await getTags();
      const list = panel.querySelector("#tagVocab");
      if (list) {
        list.innerHTML = d.tags.map((t) => `<option value="${esc(t.name)}">`).join("");
      }
      // Modell-Vorschläge: alle effektiven Modelle des Bestands (ADR 0022).
      const models = await getModels();
      const vocab = panel.querySelector("#modelVocab");
      if (vocab) {
        vocab.innerHTML = models.models.map((m) => `<option value="${esc(m.model)}">`).join("");
      }
    } catch (err) { console.warn(err); }
  }

  function showEmpty() {
    panel.innerHTML = `<div class="panelempty">
      <img class="pe-icon" src="/static/img/feral-strawberry.png" alt="">
      <div class="pe-title">${STRINGS.emptySelection}</div>
      <div class="pe-hint">${STRINGS.emptySelectionHint}</div></div>`;
  }

  async function show(hash) {
    const mySeq = ++seq;
    let d;
    try { d = await getItem(hash); }
    catch (err) { console.warn(err); return; }
    if (mySeq !== seq) return;   // inzwischen weitergeklickt

    const name = d.locations.length
      ? d.locations[0].path.split("/").pop().split("\\").pop()
      : d.file_hash.slice(0, 16) + "…";
    const media = d.media_kind === "video"
      ? `<video src="${mediaUrl(d.file_hash)}" muted loop autoplay playsinline></video>`
      : `<img src="${displayUrl(d)}" alt="">`;
    const wfEmbedded = d.raw.some((r) => (r.keyword || "").toLowerCase() === "workflow" && r.text !== null);
    // A1111-Items bekommen den Graphen serverseitig aus dem Infotext erzeugt
    // (Block N, ADR 0044) — gleiche Ansicht, gleicher Download-Endpunkt.
    const hasWorkflow = wfEmbedded || d.interpreted.some((f) => f.parser === "a1111");
    const infotext = (d.raw.find((r) => r.keyword === "parameters" && r.text) || {}).text;

    const rawRows = d.raw.map((r) => `
      <tr><td class="k">${esc(r.source)}${r.keyword ? " · " + esc(r.keyword) : ""}</td>
        <td class="v"><div class="vscroll">${r.text !== null ? esc(r.text) : `<span class="vdim">${STRINGS.rawBinary.replace("{n}", r.binary_bytes)}</span>`}</div></td></tr>`).join("");
    const locRows = d.locations.map((l) => `
      <div class="locrowv${l.exists ? "" : " warn"}">${esc(l.path)}${l.exists ? "" : " " + STRINGS.panelLocationMissing}</div>`).join("");

    panel.innerHTML = `
      <div class="ppreview" title="${STRINGS.panelOpenLoupe}">${media}</div>
      <div class="phead">
        <div class="pname">${esc(name)}</div>
        <div class="pmeta">
          <span class="badgechip origin-interpretiert">${d.media_kind === "video" ? "VIDEO" : "IMAGE"}</span>
          <span class="vmono">${d.width ? `${d.width}×${d.height} · ` : ""}${d.fps ? `${d.fps} fps · ` : ""}${esc(d.container.toUpperCase())} · ${fmtBytes(d.file_size)}</span>
          <span class="ratedots" id="pRate" title="${STRINGS.curateRateTitle}">${dotsHtml(d.manual.rating)}</span>
        </div>
      </div>
      ${selCount > 1 ? `<div class="callout multihint">
        <b>${selCount} ${STRINGS.multiSelected}</b>
        <div>${STRINGS.multiSelectedHint}</div></div>` : ""}
      <div class="section" id="pCurate">${sechead(STRINGS.sectionCurate)}
        <div class="chiprow" id="pTags"></div>
        <input id="pTagInput" list="tagVocab" placeholder="${STRINGS.curateTagPlaceholder}">
        <datalist id="tagVocab"></datalist>
        <input id="pModel" list="modelVocab" placeholder="${STRINGS.curateModelPlaceholder}">
        <datalist id="modelVocab"></datalist>
        <textarea id="pNotes" rows="2" placeholder="${STRINGS.curateNotesPlaceholder}"></textarea>
      </div>
      ${generationHtml(d)}
      ${hasWorkflow ? `<div class="section">${sechead(STRINGS.sectionWorkflow, wfEmbedded ? "ComfyUI" : STRINGS.workflowGeneratedBadge)}
        <button type="button" class="accentbtn" id="pWfOpen">${STRINGS.panelViewGraph} →</button>
        <a class="wfdl" href="${workflowUrl(d.file_hash)}" download="workflow_${esc(d.file_hash.slice(0, 12))}.json">${STRINGS.workflowDownload}</a>
        ${infotext ? `<a class="wfdl" href="#" id="pInfoCopy">${STRINGS.infotextCopy}</a>` : ""}
      </div>` : ""}
      <div class="section">
        <details><summary>${STRINGS.sectionRawMetadata} (${d.raw.length})</summary>
          <table class="rawtable">${rawRows}</table></details>
        <details><summary>${STRINGS.sectionLocations} (${d.locations.length})</summary>
          <div class="locs">${locRows}</div></details>
      </div>
      <div class="section">${sechead(STRINGS.sectionFile)}
        <div class="filerows">
          <div><span>${STRINGS.fileFormat}</span><span class="vmono">${esc(d.container)}</span></div>
          <div><span>${STRINGS.fileSize}</span><span class="vmono">${fmtBytes(d.file_size)}</span></div>
          <div><span>${STRINGS.fileCreated}</span><span class="vmono">${esc(d.media_date || STRINGS.fileCreatedUnknown)}</span></div>
          <div><span>${STRINGS.fileAdded}</span><span class="vmono">${esc((d.first_seen_at || "").slice(0, 19).replace("T", " "))}</span></div>
          <div><span>SHA-256</span><span class="vmono" title="${esc(d.file_hash)}">${esc(d.file_hash.slice(0, 16))}…</span></div>
        </div>
      </div>`;

    curHash = d.file_hash;
    renderManual(d.manual);
    fillVocabulary();
    wireImageFallback(panel.querySelector(".ppreview"), STRINGS.noPreview);
    emit("annotation-loaded", { hash: d.file_hash, rating: d.manual.rating });

    // Rating/Tag/Modell wirken auf die AUSWAHL (Einzel oder Multiselect) —
    // curate.js entscheidet zwischen Einzel-Endpunkt und Sammel-Aktion.
    panel.querySelector("#pRate").addEventListener("click", (e) => {
      const dot = e.target.closest(".rdot");
      if (dot) applyRating(parseInt(dot.dataset.n, 10));
    });
    panel.querySelector("#pCurate").addEventListener("click", (e) => {
      const del = e.target.closest(".tagdel");
      if (del) tagRemove(d.file_hash, del.dataset.tag);
    });
    const tagInput = panel.querySelector("#pTagInput");
    const takeTag = () => {
      if (!tagInput.value.trim()) return;
      applyTag(tagInput.value.trim())?.then(() => fillVocabulary());
      tagInput.value = "";
    };
    tagInput.addEventListener("keydown", (e) => { if (e.key === "Enter") takeTag(); });
    // datalist-Auswahl per Maus feuert nur 'change' — auch da übernehmen.
    tagInput.addEventListener("change", takeTag);
    const modelInput = panel.querySelector("#pModel");
    const takeModel = () => {
      if (modelInput.value.trim() === curModel) return;
      applyModel(modelInput.value.trim())?.then(() => fillVocabulary());
    };
    modelInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { takeModel(); modelInput.blur(); }
    });
    modelInput.addEventListener("blur", takeModel);
    const notesEl = panel.querySelector("#pNotes");
    notesEl.addEventListener("blur", () => {
      if (notesEl.value !== (d.manual.notes || "")) note(d.file_hash, notesEl.value);
    });

    panel.querySelector(".ppreview").addEventListener("click", () =>
      emit("loupe-open", { hash: d.file_hash }));
    panel.querySelector("#pWfOpen")?.addEventListener("click", () =>
      emit("loupe-open", { hash: d.file_hash, mode: "workflow" }));
    // Seed-Varianten: ersetzt den Suchzustand durch die exakte Generierung —
    // die Galerie lädt neu, offene Vollbild-Ebenen schließen sich dabei
    // selbst (items-reloaded).
    panel.querySelector("#pSiblings")?.addEventListener("click", () => {
      const preds = siblingPredicates(d);
      if (preds.length) emit("predicates-load", { predicates: preds });
    });
    // A1111-Infotext 1:1 in die Zwischenablage (Block N — subsumiert den
    // Kopierknopf aus Block 5.2): der Roh-Text aus Schicht 1, unverändert.
    panel.querySelector("#pInfoCopy")?.addEventListener("click", (e) => {
      e.preventDefault();
      const el = e.currentTarget;
      navigator.clipboard?.writeText(infotext).then(() => {
        el.textContent = STRINGS.panelCopied;
        setTimeout(() => { el.textContent = STRINGS.infotextCopy; }, 1400);
      }).catch(() => {});
    });
    panel.querySelector(".seedcopy")?.addEventListener("click", (e) => {
      const el = e.currentTarget;
      navigator.clipboard?.writeText(el.dataset.seed).then(() => {
        el.querySelector(".copyhint").textContent = STRINGS.panelCopied;
        setTimeout(() => {
          const hint = el.querySelector(".copyhint");
          if (hint) hint.textContent = STRINGS.panelCopy;
        }, 1400);
      }).catch(() => {});
    });
  }

  on("selection-changed", (d) => {
    // Leere Auswahl (Strg+Klick wählt auch das letzte Bild ab): Leerzustand.
    if (!d.hash) { seq++; curHash = null; showEmpty(); return; }
    selCount = d.hashes?.length || 1;
    show(d.hash);
  });
  on("items-reloaded", () => { seq++; curHash = null; showEmpty(); });
  on("annotation-changed", (d) => {
    if (d.hash === curHash) renderManual(d.manual);
  });

  showEmpty();
}
