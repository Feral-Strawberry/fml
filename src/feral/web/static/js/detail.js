// detail.js — permanentes Metadaten-Panel rechts (Leitbild: Panel + Loupe).
//
// Reagiert auf 'selection-changed', lädt /api/item/{hash} und zeigt alle
// Schichten getrennt (Vorrangregel des Design-Leitbilds): interpretierte Felder
// (Schicht 2, mit Parser-Herkunft) klar getrennt von Roh-Metadaten (Schicht 1,
// byte-treu mit Quell-Label) und Fundorten. Klick auf die Vorschau öffnet die
// Loupe. Rating/Tags bekommen ihren Platz im Kopf erst mit Block 3.1.

import { STRINGS } from "./strings.js";
import { wireReveal, removeCover, loadThumb, getAudioAnalysis, fmtLoudness, getItem, getTags, getModels, mediaUrl, openLocation, releaseVideos, wireMediaFallback, workflowUrl, thumbUrl, canPlay, mediaHtml, kindLabel as mediaKindLabel, fmtDuration, wireUnplayable, mediaFallbackLabel, codecLabel, videoCodecFacts } from "./api.js";
import { applyModel, applyRating, applyTag, note, tagRemove } from "./curate.js";
import { mountCommentSection } from "./comments.js";
import { emit, on } from "./main.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Kanonische Felder (interpret/types.py) → Darstellung im GENERATION-Block.
const BLOCK_FIELDS = ["prompt", "negative_prompt", "description", "lyrics"]; // mehrzeilig
const CHIP_FIELDS = ["steps", "sampler", "cfg_scale", "scheduler", "size", "denoise", "model_hash"]; // Steps zuerst (Issue #29)
const FIELD_LABELS = {
  prompt: "PROMPT", negative_prompt: "NEGATIVE", description: "BESCHREIBUNG",
  sampler: "SAMPLER", steps: "STEPS", cfg_scale: "CFG SCALE", scheduler: "SCHEDULER",
  size: "SIZE", denoise: "DENOISE", model_hash: "MODEL HASH", seed: "SEED",
  model: "CHECKPOINT / MODEL", lora: "LORAS", tool: "TOOL", vae: "VAE",
  credit: "CREDIT", ai_source_type: "AI-KENNZEICHNUNG", creator_tool: "CREATOR TOOL",
  rating: "RATING (EINGEBETTET)", job_id: "JOB-ID",
  feature: "FEATURES", input_image: "EINGANGSBILD",
  topaz_version: "TOPAZ VERSION", topaz_model: "TOPAZ MODEL", upscale_factor: "UPSCALE",
  source_size: "SOURCE SIZE", topaz_settings: "TOPAZ SETTINGS",
  claim_generator: "CLAIM GENERATOR", software_agent: "SOFTWARE AGENT",
  video_codec: "VIDEO CODEC", video_profile: "CODEC PROFILE", pixel_format: "PIXEL FORMAT",
};
// Neuere Felder (Audio, #160) mehrsprachig aus den Strings.
const label = (f) => STRINGS.panelFieldLabels?.[f] || FIELD_LABELS[f] || f.toUpperCase();

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
  // Exaktes zu suchen gibt — sonst wäre die Suche beliebig — UND einen Seed:
  // ohne ihn gibt es keine Seed-Serie (Suno, Midjourney, ChatGPT, Gemini …
  // schreiben keinen; Befund beim Test von #159).
  if (by.has("seed") && (by.has("prompt") || by.has("model"))) {
    html += `<button type="button" class="accentbtn" id="pSiblings"
      title="${STRINGS.siblingsTitle}">🎲 ${STRINGS.siblingsBtn}</button>`;
  }
  const toolBadge = by.has("tool") ? `<span class="badgechip origin-interpretiert">${esc(by.get("tool")[0])}</span>` : "";
  const parserBadge = `<span class="badgechip" title="${STRINGS.panelParserTitle}">${esc(parsers.join(", "))}</span>`;
  return `<div class="section">${sechead(STRINGS.sectionGeneration, toolBadge + " " + parserBadge)}${html}</div>`;
}

/** Fundort als Breadcrumb (ADR-0041-Nachtrag, Issue #37): jedes Ordner-
 *  Segment öffnet GENAU diesen Ordner (ohne Markierung — anders als der
 *  📂-Knopf), der Dateiname die Datei im zugeordneten Programm. Optisch
 *  bleibt es eine Pfadzeile: Trenner wie gespeichert, Unterstrich nur beim
 *  Überfahren. Laufwerkswurzel „D:" wird zu „D:\" (sonst öffnet Explorer das
 *  aktuelle Verzeichnis des Laufwerks); UNC-Leerpräfixe (\\nas\share) bleiben
 *  im Pfad, werden aber nicht als Segment gezeigt. Datei nur klickbar, wenn
 *  sie brauchbar ist (existiert, Größe stimmt). */
export function breadcrumbHtml(loc) {
  const sep = loc.path.includes("\\") ? "\\" : "/";
  const parts = loc.path.split(sep);
  const out = [];
  for (let i = 0; i < parts.length; i++) {
    const seg = parts[i];
    const last = i === parts.length - 1;
    if (!seg) { out.push(i === 0 && !last ? "" : sep); continue; }   // "" vor "/" bzw. "\\"
    if (i > 0) out.push(sep);
    let prefix = parts.slice(0, i + 1).join(sep);
    if (!last && i === 0 && /^[A-Za-z]:$/.test(seg)) prefix += sep;
    if (last) {
      out.push(loc.exists && loc.usable !== false
        ? `<a href="#" class="seg file" data-what="file" data-path="${esc(loc.path)}" title="${STRINGS.locOpenFileTitle}">${esc(seg)}</a>`
        : `<span class="seg file">${esc(seg)}</span>`);
    } else {
      out.push(`<a href="#" class="seg" data-what="folder" data-path="${esc(prefix)}" title="${STRINGS.locOpenFolderTitle}">${esc(seg)}</a>`);
    }
  }
  return `<span class="locpath">${out.join("")}</span>`;
}

export function initDetail() {
  const panel = document.getElementById("panel");
  let seq = 0;
  let curHash = null;   // Hash des angezeigten Items (für annotation-changed)
  let curManual = null;   // letzter Stand der manuellen Schicht (Tags für den Cover-Dialog)
  let curRating = null; // aktueller Stand fürs Toggle (gleiche Zahl löscht)
  let selCount = 1;     // Größe der aktuellen Auswahl (Multiselect-Hinweis)
  let curModel = "";    // angezeigtes manuelles Modell (Doppel-Submit vermeiden)

  function renderManual(manual) {
    curManual = manual;
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
    releaseVideos(panel);   // sonst lädt die Vorschau als Leiche weiter (#89-Lehre)
    panel.innerHTML = `<div class="panelempty">
      <img class="pe-icon" src="/static/img/feral-strawberry.png" alt="">
      <div class="pe-title">${STRINGS.emptySelection}</div>
      <div class="pe-hint">${STRINGS.emptySelectionHint}</div></div>`;
  }

  // Lautheit (A4 #161): kommt aus der Analyse im Hintergrund — erzeugt der
  // Server sie gerade, fragt getAudioAnalysis nach, bis sie da ist oder das
  // Panel längst ein anderes Item zeigt.
  async function showLoudness(hash, mySeq) {
    const stale = () => mySeq !== seq;
    let text;
    try {
      const a = await getAudioAnalysis(hash, { isStale: stale });
      if (!a) return;
      text = fmtLoudness(a.loudness);
    } catch (err) {
      text = `${STRINGS.loudnessFailed} (${err.message})`;
    }
    const el = stale() ? null : panel.querySelector("#pLoud");
    if (el) el.textContent = text;
  }

  // Cover (Audio A8, #165, ADR 0090): Das Cover ist das Gesicht des Songs und
  // steht oben wie das Vorschaubild eines Bildes (in .ppreview, aus
  // api.mediaHtml); direkt darunter diese Zeile zum Wählen/Ändern/Entfernen.
  // Das eingebettete Bild (Suno) ist eine Eigenschaft der Datei und steht
  // klein im Abschnitt „Datei" — es zählt nicht als Cover.
  function coverBarHtml(d) {
    return d.cover_item
      ? `<div class="pcoverbar has" id="pCover"><span class="cvstate" title="${esc(STRINGS.coverFinalHint)}">✓ ${STRINGS.coverFinal}</span>
          <button type="button" data-cover="pick">${STRINGS.coverChange}</button>
          <button type="button" data-cover="remove">${STRINGS.coverRemove}</button></div>`
      : `<div class="pcoverbar" id="pCover"><button type="button" class="accentbtn" data-cover="pick">🖼 ${STRINGS.coverPick}</button>
          <span class="cvhint">${STRINGS.coverNoneShort}</span></div>`;
  }

  function wireCover(d, name) {
    const sec = panel.querySelector("#pCover");
    if (!sec) return;
    const emb = panel.querySelector(".cvemb img");
    if (emb) loadThumb(emb, d.file_hash);   // Vorschaubild aus dem eingebetteten Bild
    sec.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-cover]");
      if (!b) return;
      if (b.dataset.cover === "pick") {
        emit("cover-pick", { hash: d.file_hash, name, tags: (curManual || d.manual).tags,
                             cover: (curManual || d.manual).cover });
        return;
      }
      b.disabled = true;
      try {
        const r = await removeCover(d.file_hash);
        emit("cover-changed", { hash: d.file_hash, manual: r.manual });
      } catch (err) { b.disabled = false; console.warn(err); }
    });
  }

  async function show(hash) {
    const mySeq = ++seq;
    let d;
    try { d = await getItem(hash); }
    catch (err) { console.warn(err); return; }
    if (mySeq !== seq) return;   // inzwischen weitergeklickt

    // Der Server liefert die Fundorte in Reveal-Reihenfolge (ADR-0062-
    // Nachtrag): der erste ist der bevorzugte, also auch der Anzeigename.
    const name = d.locations.length
      ? d.locations[0].path.split("/").pop().split("\\").pop()
      : d.file_hash.slice(0, 16) + "…";
    // Video-Vorschau: in der Galerie läuft sie stumm mit. Solange die
    // Einzelansicht offen ist (sie übernimmt das Panel), nur das Thumbnail
    // als Poster — sonst streamt dasselbe Video zweimal (#89, Firefox
    // schaffte bei 4-GB-Dateien das zweite Item nicht mehr). singleview
    // baut daraus beim Schließen wieder das Video (data-video).
    const singleOpen = !document.getElementById("single")?.hidden;
    // Codec, den dieser Browser nicht dekodiert (#71): Poster + Hinweis, kein
    // Player, kein Stream — auch nicht später beim Rückbau aus der Einzelansicht.
    // Medien-Weiche über den gemeinsamen Helfer (#158); nur der Video-
    // Poster bei offener Einzelansicht ist panel-eigen. Audio bekommt den
    // eigenen Player (A5 #162); er spielt nie von selbst.
    const media = d.media_kind === "video" && singleOpen && canPlay(d)
      ? `<img class="pposter" src="${thumbUrl(d.file_hash)}" data-video="${mediaUrl(d.file_hash)}" alt="">`
      : mediaHtml(d, { video: "muted loop autoplay playsinline" });
    const codec = d.media_kind === "video" ? codecLabel(videoCodecFacts(d)) : "";
    const wfEmbedded = d.raw.some((r) => (r.keyword || "").toLowerCase() === "workflow" && r.text !== null);
    // A1111-Items bekommen den Graphen serverseitig aus dem Infotext erzeugt
    // (Block N, ADR 0044) — gleiche Ansicht, gleicher Download-Endpunkt.
    const hasWorkflow = wfEmbedded || d.interpreted.some((f) => f.parser === "a1111");
    const infotext = (d.raw.find((r) => r.keyword === "parameters" && r.text) || {}).text;

    const rawRows = d.raw.map((r) => `
      <tr><td class="k">${esc(r.source)}${r.keyword ? " · " + esc(r.keyword) : ""}</td>
        <td class="v"><div class="vscroll">${r.text !== null ? esc(r.text) : `<span class="vdim">${STRINGS.rawBinary.replace("{n}", r.binary_bytes)}</span>`}</div></td></tr>`).join("");
    const kindLabel = { library: STRINGS.locKindLibrary, watch: STRINGS.locKindWatch, extern: STRINGS.locKindExtern };
    // Je Fundort: Herkunfts-Badge (Library/Quelle/extern), 📂 am Fundort, den
    // „Im Dateimanager anzeigen" öffnet; fehlende Datei bzw. fremder Inhalt
    // (Größe passt nicht, ADR 0049) werden ehrlich benannt.
    const locRows = d.locations.map((l) => {
      const state = !l.exists ? STRINGS.panelLocationMissing
        : (l.usable === false ? STRINGS.panelLocationForeign : "");
      return `
      <div class="locrowv${l.exists && l.usable !== false ? "" : " warn"}${l.preferred ? " preferred" : ""}"${l.preferred ? ` title="${STRINGS.panelLocationPreferredTitle}"` : ""}>` +
        (l.preferred && l.exists && l.usable !== false ? `<button type="button" class="locreveal" title="${esc(STRINGS.revealTitle)}">📂</button>` : "") +
        `<span class="lockind">${esc(kindLabel[l.kind] || "")}</span>${breadcrumbHtml(l)}${state ? ` <span class="locstate">${state}</span>` : ""}</div>`;
    }).join("");

    // Das vorige Panel-Video AUSDRÜCKLICH freigeben, bevor innerHTML es
    // ersetzt: ein so entferntes <video> lädt als Leiche weiter, bis der
    // Garbage Collector es einsammelt — mit autoplay+loop die ganze Datei.
    // Jeder Klick auf ein anderes Item war ein weiterer Zombie-Stream, nach
    // sechs davon hatte der Browser keine Verbindung mehr frei (#23, #89).
    releaseVideos(panel);
    panel.innerHTML = `
      <div class="ppreview"${d.media_kind === "audio" ? "" : ` title="${STRINGS.panelOpenLoupe}"`}>${media}</div>
      ${d.media_kind === "audio" ? coverBarHtml(d) : ""}
      <div class="phead">
        <div class="pname">${esc(name)}</div>
        <div class="pmeta">
          <span class="badgechip origin-interpretiert">${mediaKindLabel(d) || "IMAGE"}</span>
          <span class="vmono">${d.width ? `${d.width}×${d.height} · ` : ""}${d.fps ? `${d.fps} fps · ` : ""}${d.duration != null ? `${fmtDuration(d.duration)} · ` : ""}${esc(d.container.toUpperCase())}${codec ? ` · ${esc(codec)}` : ""} · ${fmtBytes(d.file_size)}</span>
          <span class="ratedots" id="pRate" title="${STRINGS.curateRateTitle}">${dotsHtml(d.manual.rating)}</span>
        </div>
      </div>
      ${selCount > 1 ? `<div class="callout multihint">
        <b>${selCount} ${STRINGS.multiSelected}</b>
        <div>${STRINGS.multiSelectedHint}</div></div>` : ""}
      ${d.media_kind === "audio" ? `<div class="section" id="pComs"></div>` : ""}
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
          ${d.media_kind === "audio" ? `<div><span>${STRINGS.fileLoudness}</span><span class="vmono" id="pLoud">${STRINGS.loudnessPending}</span></div>` : ""}
          ${d.embedded_picture ? `<div class="embrow"><span>${STRINGS.fileEmbeddedPicture}</span><span class="cvemb" title="${esc(STRINGS.coverEmbedded)}"><img alt=""></span></div>` : ""}
          <div><span>${STRINGS.fileCreated}</span><span class="vmono">${esc(d.media_date || STRINGS.fileCreatedUnknown)}</span></div>
          <div><span>${STRINGS.fileAdded}</span><span class="vmono">${esc((d.first_seen_at || "").slice(0, 19).replace("T", " "))}</span></div>
          <div><span>SHA-256</span><span class="vmono" title="${esc(d.file_hash)}">${esc(d.file_hash.slice(0, 16))}…</span></div>
        </div>
      </div>`;

    curHash = d.file_hash;
    renderManual(d.manual);
    fillVocabulary();
    wireMediaFallback(panel.querySelector(".ppreview"), mediaFallbackLabel(d), d);
    wireUnplayable(panel.querySelector(".ppreview"), d);   // 📂 im Codec-Hinweis (#71)
    emit("annotation-loaded", { hash: d.file_hash, rating: d.manual.rating });
    if (d.media_kind === "audio") showLoudness(d.file_hash, mySeq);
    if (d.media_kind === "audio") mountCommentSection(panel.querySelector("#pComs"), d, sechead);
    if (d.media_kind === "audio") wireCover(d, name);

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

    // 📂 am bevorzugten Fundort = derselbe Knopf wie in Lupe/Einzelansicht
    // (Datei markiert im Explorer/Finder) — für Songs der einzige, denn sie
    // haben keine Lupe und keine Einzelansicht (#162).
    const revealBtn = panel.querySelector(".locreveal");
    if (revealBtn) wireReveal(revealBtn, () => d.file_hash);
    panel.querySelector(".locs").addEventListener("click", async (e) => {
      const a = e.target.closest("a.seg");
      if (!a) return;
      e.preventDefault();
      const row = a.closest(".locrowv");
      try {
        await openLocation(d.file_hash, a.dataset.path, a.dataset.what);
      } catch (err) {
        console.warn(err);
        // Fehler an der Zeile selbst (⚠ + Meldung), klingt nach 4 s ab.
        let st = row.querySelector(".locstate");
        if (!st) { st = document.createElement("span"); st.className = "locstate"; row.appendChild(st); }
        const before = st.textContent;
        st.textContent = " ⚠ " + err.message;
        setTimeout(() => { st.textContent = before; if (!before) st.remove(); }, 4000);
      }
    });
    panel.querySelector(".ppreview").addEventListener("click", (e) => {
      // Audio hat keine Lupe (#162): die Liste mit Player kann mehr.
      if (d.media_kind === "audio") return;
      emit("loupe-open", { hash: d.file_hash });
    });
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
  // Cover gesetzt/entfernt: Vorschau und Abschnitt hängen am Coverbild — neu laden.
  on("cover-changed", (d) => { if (d.hash === curHash) show(d.hash); });

  showEmpty();
}
