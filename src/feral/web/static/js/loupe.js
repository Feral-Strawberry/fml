// loupe.js — Vollbild-Loupe: großes Medium, ←/→-Blättern mit Vorladen,
// Bild/Workflow-Umschalter, Tastatur (←/→, Pos1/Ende, Esc; Enter im Grid).
//
// Das schnelle Durchblättern ist essenziell (docs/DESIGN.md): Blättern läuft
// in Grid-Reihenfolge über den Seiten-Cache der Galerie, Nachbarbilder werden
// vorgeladen, /api/media ist immutable-gecacht — nach dem ersten Mal instant.
// Blättern zieht die Auswahl mit ('selection-changed'), damit Panel und
// Grid-Ring beim Schließen auf dem zuletzt betrachteten Item stehen.

import { STRINGS } from "./strings.js";
import { displayUrl, getItem, mediaUrl, wireImageFallback, wireReveal } from "./api.js";
import { galleryItemAt, galleryTotal } from "./gallery.js";
import { renderWorkflowInto } from "./workflow.js";
import { dotsHtml, rate } from "./curate.js";
import { emit, on } from "./main.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export function initLoupe() {
  const root = document.getElementById("loupe");
  root.innerHTML = `
    <div class="lphead">
      <span id="lpTitle" class="vmono"></span>
      <span id="lpMeta" class="lpmeta"></span>
      <div class="lpspacer"></div>
      <div id="lpSeg" class="lpseg">
        <button type="button" id="lpSegImg" class="active">${STRINGS.loupeSegImage}</button>
        <button type="button" id="lpSegWf">${STRINGS.loupeSegWorkflow}</button>
        <button type="button" id="lpSegSingle" title="${STRINGS.loupeSegSingleTitle}">${STRINGS.loupeSegSingle}</button>
      </div>
      <span id="lpCounter" class="lpmeta"></span>
      <button type="button" id="lpReveal" title="${STRINGS.revealTitle}">📂</button>
      <button type="button" id="lpClose" title="${STRINGS.loupeClose}">✕</button>
    </div>
    <div class="lpbody">
      <div class="lpnav" id="lpPrev" title="←"><span>‹</span></div>
      <div class="lpstage" id="lpStage"></div>
      <div class="lpnav" id="lpNext" title="→"><span>›</span></div>
    </div>
    <div class="lpfoot">
      <div class="lpdots" id="lpDots"></div>
      <div>${STRINGS.loupeHint}</div>
    </div>`;

  const stage = root.querySelector("#lpStage");
  const seg = root.querySelector("#lpSeg");
  const segImg = root.querySelector("#lpSegImg");
  const segWf = root.querySelector("#lpSegWf");

  let cur = null;         // {hash, index|null} — letzte bekannte Auswahl
  let open = false;
  let mode = "media";
  let hasWorkflow = false;
  let curRating = null;   // fürs Toggle der Rating-Punkte
  let seq = 0;            // entwertet überholte Antworten bei schnellem Blättern

  const lpDots = root.querySelector("#lpDots");
  function renderDots(rating) {
    curRating = rating;
    lpDots.innerHTML = dotsHtml(rating);
  }
  lpDots.addEventListener("click", (e) => {
    const dot = e.target.closest(".rdot");
    if (!dot || !cur) return;
    const n = parseInt(dot.dataset.n, 10);
    rate(cur.hash, n === curRating ? 0 : n);
  });

  function renderCounter() {
    const total = galleryTotal();
    root.querySelector("#lpCounter").textContent =
      cur && cur.index !== null ? `${cur.index + 1} / ${total}` : `– / ${total}`;
  }

  function renderMode() {
    segImg.classList.toggle("active", mode === "media");
    segWf.classList.toggle("active", mode === "workflow");
    if (mode === "workflow") {
      stage.innerHTML = `<div class="lpwf" id="lpWfBox"></div>`;
      renderWorkflowInto(stage.querySelector("#lpWfBox"), cur.hash);
    }
  }

  async function show(hash, index) {
    const mySeq = ++seq;
    let d;
    try { d = await getItem(hash); }
    catch (err) { console.warn(err); return; }
    if (mySeq !== seq || !open) return;

    cur = { hash, index };
    hasWorkflow = d.raw.some((r) => (r.keyword || "").toLowerCase() === "workflow" && r.text !== null)
      // A1111: Graph wird serverseitig aus dem Infotext erzeugt (Block N).
      || d.interpreted.some((f) => f.parser === "a1111");
    segWf.hidden = !hasWorkflow;
    if (!hasWorkflow) mode = "media";

    const name = d.locations.length
      ? d.locations[0].path.split("/").pop().split("\\").pop()
      : d.file_hash.slice(0, 16) + "…";
    root.querySelector("#lpTitle").textContent = name;
    root.querySelector("#lpMeta").textContent =
      `${d.width ? `${d.width}×${d.height} · ` : ""}${d.fps ? `${d.fps} fps · ` : ""}`
      + `${d.container.toUpperCase()}${d.media_kind === "video" ? " · VIDEO" : ""}`;
    renderCounter();
    renderDots(d.manual.rating);
    emit("annotation-loaded", { hash, rating: d.manual.rating });

    if (mode === "media") {
      stage.innerHTML = d.media_kind === "video"
        ? `<video src="${mediaUrl(hash)}" controls autoplay loop></video>`
        : `<img src="${displayUrl(d)}" alt="">`;
      wireImageFallback(stage, STRINGS.noPreview);
    } else {
      renderMode();
    }
    prefetchNeighbours();
  }

  async function prefetchNeighbours() {
    if (!cur || cur.index === null) return;
    for (const delta of [1, -1]) {
      const item = await galleryItemAt(cur.index + delta);
      if (item && item.media_kind === "image") {
        new Image().src = displayUrl(item);   // wärmt den Browser-Cache
      }
    }
  }

  async function nav(delta) {
    if (!cur || cur.index === null) return;
    const i = cur.index + delta;
    const item = await galleryItemAt(i);
    if (!item) return;
    emit("selection-changed", { hash: item.file_hash, index: i });
    show(item.file_hash, i);
  }

  async function navTo(i) {
    const item = await galleryItemAt(i);
    if (!item) return;
    emit("selection-changed", { hash: item.file_hash, index: i });
    show(item.file_hash, i);
  }

  function openLoupe(hash, index, wantedMode) {
    open = true;
    mode = wantedMode === "workflow" ? "workflow" : "media";
    root.hidden = false;
    show(hash, index ?? null);
  }

  function close() {
    open = false;
    root.hidden = true;
    stage.innerHTML = "";   // stoppt laufende Videos
  }

  // -- Verdrahtung -------------------------------------------------------------

  root.querySelector("#lpClose").addEventListener("click", close);
  wireReveal(root.querySelector("#lpReveal"), () => cur && cur.hash);
  root.querySelector("#lpPrev").addEventListener("click", () => nav(-1));
  root.querySelector("#lpNext").addEventListener("click", () => nav(1));
  segImg.addEventListener("click", () => { if (mode !== "media") { mode = "media"; show(cur.hash, cur.index); } });
  segWf.addEventListener("click", () => { if (mode !== "workflow") { mode = "workflow"; renderMode(); segImg.classList.remove("active"); segWf.classList.add("active"); } });
  root.querySelector("#lpSegSingle").addEventListener("click", () => {
    // In die Einzelbildansicht wechseln (Feral Strawberry, 2026-07-08) - gleiche Position.
    const target = cur;
    close();
    if (target) emit("single-open", { hash: target.hash, index: target.index });
  });

  on("loupe-open", (d) => {
    const index = d.index !== undefined ? d.index : (cur && cur.hash === d.hash ? cur.index : null);
    openLoupe(d.hash, index, d.mode);
  });
  on("selection-changed", (d) => {
    if (!open) cur = d.hash ? { hash: d.hash, index: d.index } : null;
  });
  on("annotation-changed", (d) => {
    if (open && cur && cur.hash === d.hash) renderDots(d.manual.rating);
  });
  on("items-reloaded", () => { if (!open) cur = null; });

  document.addEventListener("keydown", (e) => {
    const typing = e.target instanceof Element && e.target.matches("input, textarea, select");
    if (typing) return;
    if (open) {
      if (e.key === "Escape") { close(); return; }
      if (e.key === " ") { e.preventDefault(); close(); return; }   // Space = Toggle (Lightroom)
      if (e.key === "ArrowRight") { e.preventDefault(); nav(1); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); nav(-1); }
      else if (e.key === "Home") { e.preventDefault(); navTo(0); }
      else if (e.key === "End") { e.preventDefault(); navTo(galleryTotal() - 1); }
    } else if (e.key === " " && cur) {
      // In der Arena (Ranking-Modul) gehört Space dem Überspringen —
      // die Lupe darf sich nicht über das Duell legen.
      if (!document.getElementById("rankings").hidden) return;
      e.preventDefault();               // Space darf die Seite nicht scrollen
      openLoupe(cur.hash, cur.index);
    }
  });
}
