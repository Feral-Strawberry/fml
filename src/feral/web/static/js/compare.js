// compare.js - A/B-Vergleichsansicht (Issue #38): zwei markierte Bilder
// deckungsgleich übereinander, B wird per Wischkante (Slider) freigelegt.
//
// Warum: Varianten aus Edit-Workflows unterscheiden sich oft nur in Details
// (ein Finger, eine Kante) - nebeneinander sieht man das nicht, übereinander
// mit Wischkante sofort. Die Entscheidung „welches behalten" fällt direkt
// hier: jede Seite hat Rating-Punkte und Ablehnen (ADR 0041).
//
// Bauform wie singleview.js (ADR 0015: eigenes Overlay, Bus-Events,
// Tastatur-Guards in ALLEN Richtungen): Öffnen über 'compare-open'
// {hashes: [a, b]}, den Knopf ⇆ in der Galerie-Kopfzeile oder Taste C bei
// genau zwei markierten Medien. Zoom rechnet wie die Einzelbildansicht in
// echten Pixeln (ADR 0059) und teilt sich deren Zoom-Gedächtnis.
// Erste Version nur Bilder - Videos zeigen einen Hinweis statt Frames.
//
// Tastatur (solange offen, alle Tasten gehören dem Vergleich):
//   ←/→ Wischkante (Shift = grob) · Pos1/Ende = ganz links/rechts
//   Space = Dreifachumschalter Wisch → nur A → nur B (Blinkvergleich ohne
//           Tausch, das Bewertungsziel A bleibt dabei stehen)
//   Tab = A und B tauschen · 1–5/0 bewerten A · Entf lehnt A ab
//   Mausrad/+/− zoomen · Doppelklick = Anpassen ↔ 100 % · Esc/Enter schließen

import { STRINGS } from "./strings.js";
import { displayUrl, getItem, scopeSignal, abortScope, isAbort } from "./api.js";
import { dotsHtml, rate, openRejectDialog } from "./curate.js";
import { emit, on } from "./main.js";

const ZOOM_MIN = 0.05;
const ZOOM_MAX = 8;
const ZOOM_KEY = "feral-zoom";   // geteilt mit singleview.js (ADR 0059, Nachtrag)
const STEP = 2;                  // ←/→ in Prozent der Bildbreite
const STEP_COARSE = 10;          // mit Shift

export function initCompare() {
  const root = document.getElementById("compare");
  root.innerHTML = `
    <div class="lphead">
      <span class="vmono">${STRINGS.cmpTitle}</span>
      <span id="cmpDims" class="lpmeta cmpdims" hidden>${STRINGS.cmpDimsDiffer}</span>
      <div class="lpspacer"></div>
      <div class="lpseg" id="cmpZoom">
        <button type="button" data-zoom="fit" class="active">${STRINGS.svFit}</button>
        <button type="button" data-zoom="fit1" title="${STRINGS.svFit1Title}">${STRINGS.svFit1}</button>
        <button type="button" data-zoom="0.5">50 %</button>
        <button type="button" data-zoom="1">100 %</button>
        <button type="button" data-zoom="2">200 %</button>
      </div>
      <span id="cmpPct" class="lpmeta"></span>
      <button type="button" id="cmpWipe" title="${STRINGS.cmpWipeTitle}">${STRINGS.cmpViewWipe}</button>
      <button type="button" id="cmpSwap" title="${STRINGS.cmpSwapTitle}">${STRINGS.cmpSwap}</button>
      <button type="button" id="cmpClose" title="${STRINGS.cmpClose}">✕</button>
    </div>
    <div class="cmpsides">
      ${["a", "b"].map((side) => `
      <div class="cmpside" data-side="${side}">
        <b class="cmpletter">${side.toUpperCase()}</b>
        <span class="cmpname"></span>
        <span class="lpmeta cmpmeta"></span>
        <span class="ratedots cmprate" title="${STRINGS.curateRateTitle}"></span>
        <button type="button" class="cmpreject">${STRINGS.cmpReject}</button>
      </div>`).join("")}
    </div>
    <div class="cmpstage fit" id="cmpStage">
      <div class="cmpframe" id="cmpFrame">
        <img class="cmpa" alt="" draggable="false">
        <div class="cmpclip"><img class="cmpb" alt="" draggable="false"></div>
        <div class="cmpdivider"><span class="cmphandle"></span></div>
      </div>
    </div>
    <div class="lpfoot"><div>${STRINGS.cmpHint}</div></div>`;

  const stage = root.querySelector("#cmpStage");
  const frame = root.querySelector("#cmpFrame");
  const imgA = frame.querySelector(".cmpa");
  const imgB = frame.querySelector(".cmpb");
  const clip = frame.querySelector(".cmpclip");
  const divider = frame.querySelector(".cmpdivider");
  const zoomBar = root.querySelector("#cmpZoom");
  const pct = root.querySelector("#cmpPct");
  const dimsHint = root.querySelector("#cmpDims");
  const wipeBtn = root.querySelector("#cmpWipe");
  const sides = [...root.querySelectorAll(".cmpside")];

  // Knopf in der Galerie-Kopfzeile: nur bei GENAU zwei markierten Medien.
  const compareBtn = document.getElementById("compareBtn");
  compareBtn.textContent = STRINGS.cmpBtn;
  compareBtn.title = STRINGS.cmpBtnTitle;

  let open = false;
  let items = [];       // [A, B] Detailobjekte (Index 0 = links = Tastaturziel)
  let selection = [];   // Hashes der aktuellen Galerie-Auswahl
  let pos = 50;         // Wischkante in Prozent der Bildbreite
  let view = "wipe";    // "wipe" | "a" | "b" - Dreifachumschalter (Space/Knopf)
  let zoom = "fit";     // "fit" | "fit1" | Zahl (1 = 100 %, echte Pixel)
  const isFitLike = (z) => z === "fit" || z === "fit1";   // Issue #30, wie singleview.js
  let seq = 0;

  // -- Zoom (ADR 0059: 1.0 = 1 Bildpixel auf 1 Gerätepixel) ----------------------

  const dpr = () => window.devicePixelRatio || 1;

  function storedZoom() {
    const v = localStorage.getItem(ZOOM_KEY);
    if (isFitLike(v)) return v;
    const n = parseFloat(v);
    return Number.isFinite(n) && n > 0 ? n : "fit";
  }

  function watchDpr() {
    matchMedia(`(resolution: ${dpr()}dppx)`).addEventListener(
      "change", () => { if (open) applyZoom(); watchDpr(); }, { once: true });
  }
  watchDpr();

  /** Natürliche Maße von A: erst das geladene Bild, sonst die Katalogwerte. */
  function naturalA() {
    const w = imgA.naturalWidth || items[0]?.width || 0;
    const h = imgA.naturalHeight || items[0]?.height || 0;
    return w && h ? { w, h } : null;
  }

  // Der Rahmen bekommt die Maße von A; B wird auf dieselbe BREITE gebracht
  // (Issue #38: bei ungleichen Maßen an Breite anpassen) und oben-links
  // deckungsgleich gelegt. Absolut positionierte Kinder brauchen eine
  // explizite Rahmengröße - „Anpassen" wird deshalb hier gerechnet, nicht
  // per CSS max-width.
  function applyZoom() {
    stage.classList.toggle("fit", isFitLike(zoom));
    for (const b of zoomBar.querySelectorAll("button")) {
      b.classList.toggle("active", String(zoom) === b.dataset.zoom);
    }
    const nat = naturalA();
    if (!nat) { pct.textContent = ""; return; }
    let width;
    if (isFitLike(zoom)) {
      const sw = stage.clientWidth, sh = stage.clientHeight;
      if (!sw || !sh) return;   // noch nicht layoutet - nächster Resize/Load zieht nach
      width = Math.min(sw, sh * (nat.w / nat.h));
      if (zoom === "fit1") width = Math.min(width, nat.w / dpr());   // höchstens 100 %
    } else {
      width = (nat.w * zoom) / dpr();
    }
    width = Math.max(1, Math.round(width));
    frame.style.width = `${width}px`;
    frame.style.height = `${Math.round(width * (nat.h / nat.w))}px`;
    imgB.style.width = `${width}px`;
    const scale = isFitLike(zoom) ? (width * dpr()) / nat.w : zoom;
    pct.textContent = `${Math.round(scale * 100)} %`;
  }

  function setZoom(z) {
    zoom = isFitLike(z) ? z : Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));
    applyZoom();
  }

  function effectiveScale() {
    const nat = naturalA();
    const w = parseFloat(frame.style.width);
    return nat && w ? (w * dpr()) / nat.w : 1;
  }

  zoomBar.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-zoom]");
    if (!b) return;
    localStorage.setItem(ZOOM_KEY, b.dataset.zoom);
    setZoom(isFitLike(b.dataset.zoom) ? b.dataset.zoom : parseFloat(b.dataset.zoom));
  });
  stage.addEventListener("wheel", (e) => {
    if (!items.length) return;
    e.preventDefault();
    const base = isFitLike(zoom) ? effectiveScale() : zoom;
    setZoom(base * (e.deltaY < 0 ? 1.25 : 0.8));
  }, { passive: false });
  frame.addEventListener("dblclick", () => setZoom(isFitLike(zoom) ? 1 : "fit"));
  window.addEventListener("resize", () => { if (open) applyZoom(); });
  imgA.addEventListener("load", applyZoom);

  // -- Wischkante -----------------------------------------------------------------

  function applyPos() {
    pos = Math.max(0, Math.min(100, pos));
    if (view === "wipe") clip.style.left = `${pos}%`;
    divider.style.left = `${pos}%`;
  }

  // Dreifachumschalter (Feral Strawberry, 2026-09-07): Wisch → nur A → nur B → Wisch.
  // „nur A"/„nur B" zeigen ein Bild ganz - der Blinkvergleich per Space,
  // ohne dass Tab das Bewertungsziel A mitdreht.
  const VIEWS = ["wipe", "a", "b"];
  const VIEW_LABELS = { wipe: STRINGS.cmpViewWipe, a: STRINGS.cmpViewA, b: STRINGS.cmpViewB };
  function setView(v) {
    view = v;
    root.classList.toggle("nowipe", view !== "wipe");
    root.classList.toggle("onlyb", view === "b");
    clip.style.left = view === "b" ? "0%" : `${pos}%`;
    wipeBtn.textContent = VIEW_LABELS[view];
    wipeBtn.classList.toggle("active", view !== "wipe");
  }
  const cycleView = () => setView(VIEWS[(VIEWS.indexOf(view) + 1) % VIEWS.length]);

  // Ziehen irgendwo im Rahmen setzt die Kante (Maus und Touch: Pointer-Events).
  let dragging = false;
  const posFromEvent = (e) => {
    const r = frame.getBoundingClientRect();
    if (!r.width) return;
    pos = ((e.clientX - r.left) / r.width) * 100;
    applyPos();
  };
  frame.addEventListener("pointerdown", (e) => {
    if (view !== "wipe" || e.button) return;
    dragging = true;
    try { frame.setPointerCapture(e.pointerId); } catch { /* synthetische Pointer */ }
    posFromEvent(e);
  });
  frame.addEventListener("pointermove", (e) => { if (dragging) posFromEvent(e); });
  frame.addEventListener("pointerup", () => { dragging = false; });
  frame.addEventListener("pointercancel", () => { dragging = false; });

  // -- Seitenköpfe: Name, Maße, Rating, Ablehnen ------------------------------------

  const nameOf = (d) => d.locations.length
    ? d.locations[0].path.split("/").pop().split("\\").pop()
    : d.file_hash.slice(0, 16) + "…";

  function renderSides() {
    sides.forEach((el, i) => {
      const d = items[i];
      el.dataset.hash = d ? d.file_hash : "";
      el.querySelector(".cmpname").textContent = d ? nameOf(d) : "";
      el.querySelector(".cmpmeta").textContent = d
        ? `${d.width ? `${d.width}×${d.height} · ` : ""}${d.container.toUpperCase()}`
        : "";
      el.querySelector(".cmprate").innerHTML = d ? dotsHtml(d.manual.rating) : "";
    });
  }

  /** Hinweis statt Bilder (Video dabei, Datei nicht mehr auffindbar). */
  function showNote(text) {
    frame.hidden = true;
    let note = stage.querySelector(".nopreview");
    if (!note) {
      note = document.createElement("div");
      note.className = "nopreview";
      stage.appendChild(note);
    }
    note.textContent = text;
    imgA.removeAttribute("src");
    imgB.removeAttribute("src");
    pct.textContent = "";
  }

  function renderImages() {
    const [a, b] = items;
    if (items.some((d) => d.media_kind === "video")) { showNote(STRINGS.cmpVideoUnsupported); return; }
    stage.querySelector(".nopreview")?.remove();
    frame.hidden = false;
    imgA.src = displayUrl(a);
    imgB.src = displayUrl(b);
    applyZoom();
  }
  // Fehlender Fundort (ADR 0052-Muster): dezenter Hinweis statt leerer Bühne.
  for (const img of [imgA, imgB]) {
    img.addEventListener("error", () => { if (open && img.getAttribute("src")) showNote(STRINGS.noPreview); });
  }

  function render() {
    renderSides();
    renderImages();
    applyPos();
  }

  /** Rating-Toggle wie im Panel: gleiche Zahl löscht (0). */
  function rateSide(i, n) {
    const d = items[i];
    if (!d) return;
    rate(d.file_hash, n !== 0 && n === d.manual.rating ? 0 : n);
  }

  root.querySelector(".cmpsides").addEventListener("click", (e) => {
    const side = e.target.closest(".cmpside");
    if (!side) return;
    const i = sides.indexOf(side);
    const dot = e.target.closest(".rdot");
    if (dot) { rateSide(i, parseInt(dot.dataset.n, 10)); return; }
    if (e.target.closest(".cmpreject") && items[i]) openRejectDialog([items[i].file_hash]);
  });

  function swap() {
    if (items.length < 2) return;
    items.reverse();
    render();
  }

  // -- Öffnen / Schließen -----------------------------------------------------------

  async function openView(hashes) {
    if (!hashes || hashes.length !== 2) return;
    const mySeq = ++seq;
    let loaded;
    try { loaded = await Promise.all(hashes.map((h) => getItem(h, { signal: scopeSignal("compare") }))); }
    catch (err) { if (!isAbort(err)) console.warn(err); return; }
    if (mySeq !== seq) return;
    items = loaded;
    open = true;
    root.hidden = false;
    emit("view-changed", { view: "compare", open: true });
    zoom = storedZoom();
    pos = 50;
    setView("wipe");
    const [a, b] = items;
    dimsHint.hidden = a.width === b.width && a.height === b.height;
    render();
  }

  function close() {
    if (!open) return;
    open = false;
    seq++;                 // ein noch laufendes Öffnen verfällt
    abortScope("compare"); // laufende Anfragen der Ansicht verfallen (ADR 0069)
    root.hidden = true;
    emit("view-changed", { view: "compare", open: false });
    items = [];
    frame.hidden = false;
    stage.querySelector(".nopreview")?.remove();
    imgA.removeAttribute("src");
    imgB.removeAttribute("src");
  }

  // -- Verdrahtung ------------------------------------------------------------------

  root.querySelector("#cmpClose").addEventListener("click", close);
  root.querySelector("#cmpSwap").addEventListener("click", swap);
  wipeBtn.addEventListener("click", cycleView);
  compareBtn.addEventListener("click", () => emit("compare-open", { hashes: selection }));

  on("compare-open", (d) => openView(d.hashes));
  on("selection-changed", (d) => {
    selection = d.hashes ?? (d.hash ? [d.hash] : []);
    compareBtn.hidden = selection.length !== 2;
  });
  on("items-reloaded", () => { selection = []; compareBtn.hidden = true; close(); });
  on("items-rejected", () => close());     // eine Seite ist weg - Vergleich beendet
  on("loupe-open", () => close());         // nie zwei Overlays (Muster singleview.js)
  on("single-open", () => close());
  on("annotation-changed", (d) => {
    const i = items.findIndex((it) => it.file_hash === d.hash);
    if (i < 0) return;
    items[i].manual = d.manual;
    sides[i].querySelector(".cmprate").innerHTML = dotsHtml(d.manual.rating);
  });

  const overlayOpen = () =>
    ["loupe", "single", "rankings"].some((id) => !document.getElementById(id).hidden);

  // CAPTURE-Phase am window: Solange der Vergleich offen ist, gehört die
  // Tastatur ihm - sonst blättern ←/→ unsichtbar die Galerie, Space öffnet
  // die Lupe und 1–5 bewerten per curate.js die GANZE Zweier-Auswahl statt
  // nur A. window statt document, weil der Ablehnen-Dialog (curate.js) Esc
  // in der Capture-Phase am document abfängt: stopPropagation() hält nur
  // NACHFOLGENDE Knoten an, nicht Listener am selben Knoten - wir müssen
  // also VOR ihm laufen und bei sichtbarem Dialog aussteigen (Esc, Enter
  // auf dem fokussierten Knopf: alles gehört dann dem Dialog).
  const rejectDialogOpen = () => document.getElementById("rejectdlg")?.hidden === false;
  window.addEventListener("keydown", (e) => {
    if (!open || rejectDialogOpen()) return;
    const typing = e.target instanceof Element && e.target.matches("input, textarea, select");
    if (typing) return;
    e.stopPropagation();
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    switch (e.key) {
      case "Escape": case "Enter": e.preventDefault(); close(); return;
      case "ArrowLeft": e.preventDefault(); if (view === "wipe") { pos -= e.shiftKey ? STEP_COARSE : STEP; applyPos(); } return;
      case "ArrowRight": e.preventDefault(); if (view === "wipe") { pos += e.shiftKey ? STEP_COARSE : STEP; applyPos(); } return;
      case "Home": e.preventDefault(); pos = 0; applyPos(); return;
      case "End": e.preventDefault(); pos = 100; applyPos(); return;
      case "Tab": e.preventDefault(); swap(); return;
      case " ": e.preventDefault(); cycleView(); return;
      case "+": setZoom((isFitLike(zoom) ? effectiveScale() : zoom) * 1.25); return;
      case "-": setZoom((isFitLike(zoom) ? effectiveScale() : zoom) * 0.8); return;
      case "Delete":
        e.preventDefault();
        if (items[0]) openRejectDialog([items[0].file_hash]);
        return;
      default:
        if (e.key >= "0" && e.key <= "5") { e.preventDefault(); rateSide(0, parseInt(e.key, 10)); }
    }
  }, true);

  // Taste C in der Galerie: genau zwei markierte Medien vergleichen.
  document.addEventListener("keydown", (e) => {
    if (open || (e.key !== "c" && e.key !== "C")) return;
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    const typing = e.target instanceof Element && e.target.matches("input, textarea, select");
    if (typing || overlayOpen() || selection.length !== 2) return;
    e.preventDefault();
    emit("compare-open", { hashes: selection });
  });
}
