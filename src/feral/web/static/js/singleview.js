// singleview.js - Einzelbildansicht (Arbeitsansicht): echtes Zoomen
// (Anpassen/50/100/200 %, Mausrad, Ziehen, Doppelklick = Anpassen↔100 %)
// plus das komplette Metadaten-Panel als breite Spalte rechts.
//
// Das Panel wird beim Öffnen ADOPTIERT (dasselbe DOM-Element wandert aus der
// Shell hierher und beim Schließen zurück) - Bewerten, Tags, Modell und
// Notizen funktionieren dadurch ohne zweite Implementierung, und künftige
// Werkzeuge (Metadaten-Bearbeitung, Push-to-ComfyUI) haben hier ihren Platz.
// Blättern läuft wie in der Lupe über den Seiten-Cache der Galerie und zieht
// die Auswahl mit - Esc/Enter/✕ führen zur Galerie mit dem zuletzt
// betrachteten Bild zurück.

import { STRINGS } from "./strings.js";
import { displayUrl, getItem, mediaUrl, thumbUrl, wireImageFallback, wireReveal } from "./api.js";
import { galleryItemAt, galleryTotal } from "./gallery.js";
import { emit, on } from "./main.js";

const ZOOM_MIN = 0.05;
const ZOOM_MAX = 8;

export function initSingleView() {
  const root = document.getElementById("single");
  root.innerHTML = `
    <div class="lphead">
      <span id="svTitle" class="vmono"></span>
      <span id="svMeta" class="lpmeta"></span>
      <div class="lpspacer"></div>
      <div class="lpseg" id="svZoom">
        <button type="button" data-zoom="fit" class="active">${STRINGS.svFit}</button>
        <button type="button" data-zoom="0.5">50 %</button>
        <button type="button" data-zoom="1">100 %</button>
        <button type="button" data-zoom="2">200 %</button>
      </div>
      <span id="svPct" class="lpmeta"></span>
      <span id="svCounter" class="lpmeta"></span>
      <button type="button" id="svReveal" title="${STRINGS.revealTitle}">📂</button>
      <button type="button" id="svClose" title="${STRINGS.svClose}">✕</button>
    </div>
    <div class="svbody">
      <div class="lpnav" id="svPrev" title="←"><span>‹</span></div>
      <div class="svstage" id="svStage"></div>
      <div class="lpnav" id="svNext" title="→"><span>›</span></div>
      <aside class="svpanel">
        <div class="svnav" id="svNav" hidden><img alt=""><div class="svnavrect" id="svNavRect"></div></div>
        <div id="svPanel" style="flex:1; min-height:0; display:flex; overflow:hidden;"></div>
      </aside>
    </div>
    <div class="lpfoot"><div>${STRINGS.svHint}</div></div>`;

  const stage = root.querySelector("#svStage");
  const navBox = root.querySelector("#svNav");
  const navImg = navBox.querySelector("img");
  const navRect = root.querySelector("#svNavRect");
  const zoomBar = root.querySelector("#svZoom");
  const pct = root.querySelector("#svPct");
  const panelSlot = root.querySelector("#svPanel");

  let open = false;
  let cur = null;             // {hash, index|null}
  let zoom = "fit";           // "fit" | Zahl (1 = 100 %)

  // Zoom-Gedächtnis (ADR-0059-Nachtrag, Muster ADR 0057): NUR die explizite
  // Wahl in der Zoomleiste stempelt und gilt dann für jedes weitere Bild.
  // Gesten (Mausrad, ±, Doppelklick) erzeugen bildabhängige Zwischenwerte —
  // flüchtiges Hinschauen, wird bewusst NICHT gemerkt.
  const ZOOM_KEY = "feral-zoom";
  function storedZoom() {
    const v = localStorage.getItem(ZOOM_KEY);
    if (v === "fit") return "fit";
    const n = parseFloat(v);
    return Number.isFinite(n) && n > 0 ? n : "fit";
  }
  let media = null;           // aktuelles <img>/<video>
  let seq = 0;
  let panelHome = null;       // Kommentar-Platzhalter am Ursprungsort des Panels

  // -- Panel adoptieren / zurückgeben ------------------------------------------

  // Solange das Panel hier wohnt, darf seine (versteckte) Video-Vorschau
  // NIE spielen - das Panel rendert sich beim Blättern asynchron neu, und
  // je nach Wettlauf startete jedes zweite Mal ein frisches Autoplay-Video
  // (Feral Strawberrys "exakt jeder zweite Eintrag"). Ein MutationObserver pausiert
  // deterministisch alles, was auftaucht.
  let panelObserver = null;
  const stopPanelVideos = () =>
    panelSlot.querySelectorAll("video").forEach((v) => v.pause());

  function adoptPanel() {
    const panel = document.getElementById("panel");
    if (!panel || panel.parentElement === panelSlot) return;
    panelHome = document.createComment("panel-home");
    panel.replaceWith(panelHome);
    panelSlot.appendChild(panel);
    stopPanelVideos();
    panelObserver = new MutationObserver(stopPanelVideos);
    panelObserver.observe(panel, { childList: true, subtree: true });
  }

  function returnPanel() {
    panelObserver?.disconnect();
    panelObserver = null;
    const panel = document.getElementById("panel");
    if (panel && panelHome) {
      panelHome.replaceWith(panel);
      panelHome = null;
      // Zurück in der Galerie darf die Panel-Vorschau wieder laufen.
      panel.querySelector(".ppreview video")?.play().catch(() => {});
    }
  }

  // -- Zoom ----------------------------------------------------------------------
  // Zoom rechnet in ECHTEN Pixeln (ADR 0059): 1.0 heißt 1 Bildpixel =
  // 1 Gerätepixel. devicePixelRatio bündelt OS-Skalierung (Windows 150 %,
  // Retina 2×) und Browser-Zoom — CSS-Größen werden dadurch geteilt.

  const dpr = () => window.devicePixelRatio || 1;

  // dpr ist nicht statisch (Fenster auf anderen Monitor, Strg+/−): die
  // Media-Query gilt genau für den aktuellen Wert, ihr change-Event
  // meldet den Wechsel — dann Zoom neu anwenden und neu lauschen.
  function watchDpr() {
    matchMedia(`(resolution: ${dpr()}dppx)`).addEventListener(
      "change", () => { if (open) applyZoom(); watchDpr(); }, { once: true });
  }
  watchDpr();

  function effectiveScale() {
    if (!media || !media.naturalWidth) return null;
    return (media.getBoundingClientRect().width * dpr()) / media.naturalWidth;
  }

  function applyZoom() {
    if (!media) return;
    const natural = media.naturalWidth || media.videoWidth || 0;
    stage.classList.toggle("fit", zoom === "fit");
    if (zoom === "fit" || !natural) {
      media.style.width = "";
    } else {
      media.style.width = `${Math.round((natural * zoom) / dpr())}px`;
    }
    for (const b of zoomBar.querySelectorAll("button")) {
      b.classList.toggle("active", String(zoom) === b.dataset.zoom);
    }
    const scale = zoom === "fit" ? effectiveScale() : zoom;
    pct.textContent = scale ? `${Math.round(scale * 100)} %` : "";
    updateNavigator();
  }

  // Navigator (Lightroom-Muster): Mini-Übersicht mit Ausschnitt-Rechteck,
  // Klick/Ziehen darin verschiebt den sichtbaren Bereich der großen Ansicht.
  function updateNavigator() {
    if (!media) { navBox.hidden = true; return; }
    navBox.hidden = false;
    const mw = media.offsetWidth, mh = media.offsetHeight;
    if (!stage.clientWidth || !mw) return;   // noch nicht layoutet - nächster Scroll/Zoom zieht nach
    const overflow = mw > stage.clientWidth + 1 || mh > stage.clientHeight + 1;
    navRect.hidden = !overflow;
    if (!overflow || !mw || !mh) return;
    const nw = navImg.offsetWidth, nh = navImg.offsetHeight;
    // Das Navigator-Bild ist im Kasten ZENTRIERT (Hochkant: Balken links/
    // rechts) - das Rechteck muss um dessen Versatz mitwandern.
    navRect.style.left = `${navImg.offsetLeft + (stage.scrollLeft / mw) * nw}px`;
    navRect.style.top = `${navImg.offsetTop + (stage.scrollTop / mh) * nh}px`;
    navRect.style.width = `${Math.min(1, stage.clientWidth / mw) * nw}px`;
    navRect.style.height = `${Math.min(1, stage.clientHeight / mh) * nh}px`;
  }
  stage.addEventListener("scroll", updateNavigator);
  window.addEventListener("resize", updateNavigator);

  function navGoto(e) {
    if (!media) return;
    const r = navImg.getBoundingClientRect();
    const fx = (e.clientX - r.left) / r.width;
    const fy = (e.clientY - r.top) / r.height;
    stage.scrollLeft = fx * media.offsetWidth - stage.clientWidth / 2;
    stage.scrollTop = fy * media.offsetHeight - stage.clientHeight / 2;
  }
  let navDrag = false;
  navBox.addEventListener("pointerdown", (e) => {
    navDrag = true; navBox.setPointerCapture(e.pointerId); navGoto(e);
  });
  navBox.addEventListener("pointermove", (e) => { if (navDrag) navGoto(e); });
  navBox.addEventListener("pointerup", () => { navDrag = false; });

  function setZoom(z) {
    zoom = z === "fit" ? "fit" : Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));
    applyZoom();
  }

  zoomBar.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-zoom]");
    if (!b) return;
    localStorage.setItem(ZOOM_KEY, b.dataset.zoom);
    setZoom(b.dataset.zoom === "fit" ? "fit" : parseFloat(b.dataset.zoom));
  });

  // Mausrad = Zoomen (Bildbetrachter-Konvention); startet aus „Anpassen" an
  // der aktuellen effektiven Größe, damit nichts springt.
  stage.addEventListener("wheel", (e) => {
    if (!media) return;
    e.preventDefault();
    const base = zoom === "fit" ? (effectiveScale() || 1) : zoom;
    setZoom(base * (e.deltaY < 0 ? 1.25 : 0.8));
  }, { passive: false });

  // Doppelklick im Bild: Anpassen ↔ 100 % (der Alltagsgriff).
  stage.addEventListener("dblclick", (e) => {
    if (e.target === media) setZoom(zoom === "fit" ? 1 : "fit");
  });

  // Ziehen zum Verschieben (native Scrollbars übernehmen den Rest).
  let drag = null;
  stage.addEventListener("pointerdown", (e) => {
    if (e.target !== media || zoom === "fit") return;
    drag = { x: e.clientX, y: e.clientY, left: stage.scrollLeft, top: stage.scrollTop };
    stage.setPointerCapture(e.pointerId);
  });
  stage.addEventListener("pointermove", (e) => {
    if (!drag) return;
    stage.scrollLeft = drag.left - (e.clientX - drag.x);
    stage.scrollTop = drag.top - (e.clientY - drag.y);
  });
  stage.addEventListener("pointerup", () => { drag = null; });

  // -- Anzeigen / Blättern ---------------------------------------------------------

  function renderCounter() {
    const total = galleryTotal();
    root.querySelector("#svCounter").textContent =
      cur && cur.index !== null ? `${cur.index + 1} / ${total}` : `- / ${total}`;
  }

  async function show(hash, index) {
    const mySeq = ++seq;
    let d;
    try { d = await getItem(hash); }
    catch (err) { console.warn(err); return; }
    if (mySeq !== seq || !open) return;

    cur = { hash, index };
    zoom = storedZoom();
    const name = d.locations.length
      ? d.locations[0].path.split("/").pop().split("\\").pop()
      : d.file_hash.slice(0, 16) + "…";
    root.querySelector("#svTitle").textContent = name;
    root.querySelector("#svMeta").textContent =
      `${d.width ? `${d.width}×${d.height} · ` : ""}${d.container.toUpperCase()}`
      + `${d.media_kind === "video" ? " · VIDEO" : ""}`;
    renderCounter();

    // Bilder: Original als Navigator-Quelle (liegt für die große Ansicht
    // ohnehin im Cache und bleibt bei jeder Leistenbreite scharf).
    // Videos UND animierbare Formate (WEBP/GIF sind <img> - da gibt es kein
    // pause(), das Original würde im Navigator mitanimieren): Thumbnail
    // als statischer Poster-Frame.
    const animatable = d.media_kind === "video" || ["webp", "gif"].includes(d.container);
    navImg.src = animatable ? thumbUrl(hash) : displayUrl(d);
    navImg.onload = updateNavigator;
    stage.innerHTML = "";
    if (d.media_kind === "video") {
      media = document.createElement("video");
      media.src = mediaUrl(hash);
      media.controls = true;
      media.loop = true;
      media.autoplay = true;   // die große Ansicht spielt (Panel-Vorschau nicht)
      media.addEventListener("loadedmetadata", applyZoom, { once: true });
    } else {
      media = document.createElement("img");
      media.alt = "";
      media.src = displayUrl(d);
      media.addEventListener("load", applyZoom, { once: true });
    }
    stage.appendChild(media);
    wireImageFallback(stage, STRINGS.noPreview);
    applyZoom();
  }

  async function navTo(i) {
    const item = await galleryItemAt(i);
    if (!item) return;
    emit("selection-changed", { hash: item.file_hash, index: i });
    show(item.file_hash, i);
  }

  const nav = (delta) => { if (cur && cur.index !== null) navTo(cur.index + delta); };

  function openView(hash, index) {
    open = true;
    root.hidden = false;
    adoptPanel();
    show(hash, index ?? null);
    // Das Panel zeigt evtl. noch ein anderes Item - Auswahl nachziehen.
    emit("selection-changed", { hash, index: index ?? null });
  }

  function close() {
    if (!open) return;
    open = false;
    root.hidden = true;
    stage.innerHTML = "";   // stoppt laufende Videos
    media = null;
    returnPanel();
  }

  // -- Verdrahtung ------------------------------------------------------------------

  root.querySelector("#svClose").addEventListener("click", close);
  wireReveal(root.querySelector("#svReveal"), () => cur && cur.hash);
  root.querySelector("#svPrev").addEventListener("click", () => nav(-1));
  root.querySelector("#svNext").addEventListener("click", () => nav(1));

  on("single-open", (d) => {
    const index = d.index !== undefined ? d.index : (cur && cur.hash === d.hash ? cur.index : null);
    openView(d.hash, index);
  });
  // Lupe geht auf (z. B. „Node-Graph ansehen" im Panel): Einzelbildansicht
  // schließen statt sie darüber hängen zu lassen - symmetrisch zum
  // „Einzelbild"-Segment in der Lupe.
  on("loupe-open", () => { if (open) close(); });
  on("selection-changed", (d) => {
    if (!open) cur = d.hash ? { hash: d.hash, index: d.index } : null;
  });
  on("items-reloaded", () => { if (open) close(); else cur = null; });
  on("items-rejected", () => { if (open) close(); });

  document.addEventListener("keydown", (e) => {
    const typing = e.target instanceof Element && e.target.matches("input, textarea, select");
    if (typing) return;
    if (open) {
      if (e.key === "Escape" || e.key === "Enter") { e.preventDefault(); close(); return; }
      if (e.key === "ArrowRight") { e.preventDefault(); nav(1); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); nav(-1); }
      else if (e.key === "Home") { e.preventDefault(); navTo(0); }
      else if (e.key === "End") { e.preventDefault(); navTo(galleryTotal() - 1); }
      else if (e.key === "+") { setZoom((zoom === "fit" ? (effectiveScale() || 1) : zoom) * 1.25); }
      else if (e.key === "-") { setZoom((zoom === "fit" ? (effectiveScale() || 1) : zoom) * 0.8); }
      return;
    }
    // Enter in der Galerie öffnet die Auswahl in der Einzelbildansicht
    // (nur wenn weder Lupe noch Admin noch Arena offen sind — in der Arena
    // gehört Enter dem Durchsehen; rankings.js öffnet dort selbst).
    if (e.key === "Enter" && cur
        && document.getElementById("loupe").hidden
        && document.getElementById("admin").hidden
        && document.getElementById("rankings").hidden) {
      e.preventDefault();
      openView(cur.hash, cur.index);
    }
  });
}
