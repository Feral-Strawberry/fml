// gallery.js — virtualisiertes Grid mit Sortierung und Dichte-Umschalter.
//
// Portiert die bewährte Virtualisierungs-Logik der alten Seite (Seiten à 200
// im Cache, on-demand-Nachladen, rAF-gedrosseltes Rendern, Klick-Delegation),
// aber mit neuer Platzierungsstrategie: **zeilenbasiertes Windowing** statt
// absoluter Positionierung. Nur die sichtbaren Zeilen (+ Puffer) liegen als
// Kacheln in DOM-Reihenfolge in #grid; das CSS-Grid übernimmt die Platzierung
// (gestreckte, randfüllende Kacheln). #gridspacer bekommt die Gesamthöhe des
// Bestands, #grid wird per translateY an die erste gerenderte Zeile geschoben.
// Zeilenhöhe wird an einer echten Kachel GEMESSEN (neu bei Resize und
// Dichte-Wechsel), die Spaltenzahl kommt aus dem berechneten Grid-Layout.

import { STRINGS } from "./strings.js";
import { getItems, loadThumb } from "./api.js";
import { emit, on } from "./main.js";

const PAGE = 200;              // Items pro API-Seite (wie alte Seite)
const BUFFER_ROWS = 3;         // Pufferzeilen ober-/unterhalb des Sichtfensters
const DENSITY_KEY = "feral-density";
const DENSITIES = ["s", "m", "l"];
const SORT_KEY = "feral-sort"; // zuletzt im Menü gewählte Sortierung (ADR 0057)

// Gemerkte Sortierung als SITZUNGS-STANDARD (ADR 0057): gilt überall, wo der
// Suchzustand keinen sort:-Chip trägt. Chips/Grammatik bleiben kanonisch —
// „added" ist weiterhin der chip-lose Schlüssel, nur der Rückfallwert ohne
// Chip ist jetzt die gemerkte statt der eingebauten Standardsortierung.
function storedSort() {
  const v = localStorage.getItem(SORT_KEY);
  if (!v) return "added";
  const base = v.split("-")[0];
  return STRINGS.sortOptions.some((o) => o.key === base) ? v : "added";
}

// -- Reine Zeilenmathe ---------------------------------------------------------
//
// Bewusst ohne DOM-Zugriff, damit sie in Node prüfbar bleibt. Alle Maße in px:
// `padTop` ist das obere Padding des Scroll-Containers (das Raster beginnt
// erst dahinter), `rowH` die gemessene Kachelhöhe, `gap` der Zeilenabstand.
export function computeWindow({ scrollTop, viewportH, padTop, rowH, gap, cols, total, buffer = BUFFER_ROWS }) {
  const stride = rowH + gap;                       // eine Zeile + ein Abstand
  const rows = Math.ceil(total / cols);
  const seen = Math.max(0, scrollTop - padTop);    // Scrollweg innerhalb des Rasters
  // Klemmen auch nach oben (rows - 1): scrollTop kann übergangsweise hinter das
  // Inhaltsende zeigen (z. B. Dichte-Wechsel L→S weit unten, bevor der Browser
  // den Scrollstand an die geschrumpfte Spacer-Höhe anpasst).
  const firstRow = Math.max(0, Math.min(Math.floor(seen / stride) - buffer, rows - 1));
  const lastRow = Math.min(rows, Math.ceil((seen + viewportH) / stride) + buffer);
  return {
    firstRow,
    first: firstRow * cols,                        // erster gerenderter Item-Index
    last: Math.min(total, lastRow * cols),         // exklusiv
    offsetY: firstRow * stride,                    // translateY fürs #grid
    spacerH: rows > 0 ? rows * stride - gap : 0,   // Gesamthöhe des Bestands
  };
}

// -- HTML-Escaping (für Chip-Texte aus der DB) ----------------------------------
const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// -- Item-Zugriff für die Loupe (Blättern in Grid-Reihenfolge, Task 10) ---------
//
// Die Loupe blättert über denselben Seiten-Cache wie das Grid — Nachbarn sind
// dadurch meist schon da, fehlende Seiten werden nachgeladen (wie alte Seite).
let _access = null;

/** Item an Grid-Position i (lädt die Seite bei Bedarf nach); null außerhalb. */
export async function galleryItemAt(i) {
  return _access ? _access.itemAt(i) : null;
}

/** Gesamtzahl der Items in der aktuellen Grid-Reihenfolge. */
export function galleryTotal() {
  return _access ? _access.total() : 0;
}

// -- Modul-Einstieg --------------------------------------------------------------

export function initGallery() {
  const wrap = document.getElementById("gridwrap");     // Scroll-Container
  const spacer = document.getElementById("gridspacer"); // trägt die Gesamthöhe
  const grid = document.getElementById("grid");         // CSS-Grid, wird verschoben
  const sortSel = document.getElementById("sort");
  const densityBox = document.getElementById("density");

  let total = 0;
  let items = new Map();        // Item-Index -> Item (seitenweise befüllt)
  let loadedPages = new Set();  // bereits angefragte Seiten
  let tiles = new Map();        // Item-Index -> Kachel-Element (im DOM aufsteigend)
  let selectedHash = null;      // Primär-Auswahl (Panel zeigt dieses Item)
  let selectedIndex = null;     // Grid-Position der Auswahl (Pfeiltasten, Loupe)
  let selectedSet = new Set();  // Multiselect (Shift/Strg): alle markierten Hashes
  let filter = {};              // aktive Quelle: {model} | {rating_min} | {} (alle)
  let sortKey = storedSort();   // kanonischer Sortierschlüssel (ADR 0039/0057)
  let reloadSeq = 0;            // entwertet Antworten überholter Reloads (Sort-Wechsel)
  let firstLoadDone = false;    // Leer-Hinweis erst nach der ersten Antwort zeigen
  let needTotal = false;        // Soft-Refresh: Gesamtzahl mit der nächsten Seite neu holen

  // Layout-Messwerte — bei Resize und Dichte-Wechsel neu erhoben.
  let cols = 1;
  let rowH = 0;
  let gap = 0;
  let padTop = 0;

  function measureLayout() {
    const gs = getComputedStyle(grid);
    // getComputedStyle löst repeat(auto-fill, …) in konkrete Spuren auf.
    cols = Math.max(1, gs.gridTemplateColumns.split(" ").length);
    gap = parseFloat(gs.rowGap) || 0;
    padTop = parseFloat(getComputedStyle(wrap).paddingTop) || 0;
    // Zeilenhöhe an einer echten Kachel messen; ohne Bestand: Probekachel.
    let probe = grid.querySelector(".tile");
    let temp = null;
    if (!probe) {
      temp = document.createElement("div");
      temp.className = "tile";
      grid.appendChild(temp);
      probe = temp;
    }
    rowH = probe.getBoundingClientRect().height || 1;
    if (temp) temp.remove();
  }

  // -- Daten laden ---------------------------------------------------------------

  async function loadPage(page) {
    if (loadedPages.has(page)) return;
    loadedPages.add(page);
    const seq = reloadSeq;
    try {
      // Gesamtzähler nur mit Seite 0 anfordern — der Filter-COUNT je
      // Folgeseite war beim Tief-Scrollen ein Prüf-Scan pro Anfrage.
      const d = await getItems({ limit: PAGE, offset: page * PAGE, sort: sortKey,
                                 total: page === 0 || needTotal ? 1 : 0, ...filter });
      if (seq !== reloadSeq) return;   // inzwischen neu geladen (Sort/Quelle)
      if (d.total >= 0) { total = d.total; needTotal = false; }
      firstLoadDone = true;
      d.items.forEach((it, k) => items.set(page * PAGE + k, it));
      renderGrid();
    } catch (err) {
      if (seq === reloadSeq) loadedPages.delete(page);  // erneuter Versuch möglich
      console.warn(err);
    }
  }

  async function reloadGrid() {
    reloadSeq++;                       // laufende Antworten alter Seiten entwerten
    firstLoadDone = false;             // „leer"-Hinweis erst NACH der Antwort
    total = 0;
    items = new Map();
    loadedPages = new Set();
    tiles.forEach((el) => el.remove());
    tiles = new Map();
    selectedHash = null;               // alte Auswahl gehört zur alten Reihenfolge
    selectedIndex = null;
    wrap.scrollTop = 0;
    await loadPage(0);
    emit("items-reloaded", { total });
    // Zweiter Durchgang im nächsten Frame: Erst mit gesetzter Spacer-Höhe steht
    // fest, ob ein Scrollbalken erscheint (der die Spaltenbreite ändert).
    requestAnimationFrame(() => { measureLayout(); renderGrid(); });
  }

  // Schonender Refresh (ADR 0057): Daten neu laden, aber Scrollposition,
  // Kacheln und Auswahl BEHALTEN — im Gegensatz zu reloadGrid, das für neue
  // Filter/Sortierungen die Ansicht komplett zurücksetzt. Verschwindet das
  // ausgewählte Item (Ablehnen), rückt sein Nachfolger an derselben
  // Grid-Position nach — so lässt sich eine Serie ohne Fokusverlust
  // durchsortieren. Meldet 'items-refreshed' (Trefferzahl), bewusst NICHT
  // 'items-reloaded' — auf das reagieren Panel/Ansichten mit Zustands-Resets.
  async function refreshGrid() {
    const seq = ++reloadSeq;           // laufende Antworten alter Seiten entwerten
    items = new Map();
    loadedPages = new Set();
    needTotal = true;
    const keepHash = selectedHash;
    const keepIndex = selectedIndex;
    // Anker: Seite der Auswahl, sonst die erste sichtbare Position.
    const anchorIndex = keepIndex ?? computeWindow({
      scrollTop: wrap.scrollTop, viewportH: wrap.clientHeight,
      padTop, rowH, gap, cols, total,
    }).first;
    await loadPage(Math.floor(Math.max(0, anchorIndex) / PAGE));
    if (seq !== reloadSeq) return;     // inzwischen kam ein echter Reload
    emit("items-refreshed", { total });
    if (keepHash) {
      let found = null;
      for (const [i, it] of items) {
        if (it && it.file_hash === keepHash) { found = i; break; }
      }
      if (found !== null) {
        selectedIndex = found;         // Item noch da, evtl. verschoben — still nachziehen
      } else if (!total) {
        emit("selection-changed", { hash: null, index: null, hashes: [] });
      } else if (keepIndex !== null) {
        const idx = Math.min(keepIndex, total - 1);
        const it = await galleryItemAt(idx);
        if (seq !== reloadSeq) return;
        if (it) emit("selection-changed", { hash: it.file_hash, index: idx });
        else emit("selection-changed", { hash: null, index: null, hashes: [] });
      }
    }
    renderGrid();
  }

  // -- Rendern ---------------------------------------------------------------------

  function renderGrid() {
    if (!total) {
      tiles.forEach((el) => el.remove());
      tiles.clear();
      spacer.style.height = "";
      grid.style.transform = "";
      grid.innerHTML = firstLoadDone
        ? `<div class="gridempty">${STRINGS.galleryEmpty}</div>`
        : "";
      return;
    }
    const empty = grid.querySelector(".gridempty");
    if (empty) empty.remove();

    const w = computeWindow({
      scrollTop: wrap.scrollTop, viewportH: wrap.clientHeight,
      padTop, rowH, gap, cols, total,
    });
    spacer.style.height = w.spacerH + "px";
    grid.style.transform = `translateY(${w.offsetY}px)`;

    // Kacheln außerhalb des Fensters entfernen …
    for (const [i, el] of tiles) {
      if (i < w.first || i >= w.last) { el.remove(); tiles.delete(i); }
    }
    // … dann das Fenster in DOM-Reihenfolge auffüllen. Die verbleibenden
    // Kacheln sind ein lückenlos aufsteigender Ausschnitt; die Zielposition
    // von Index i ist daher immer Kind Nr. (i - first).
    for (let i = w.first; i < w.last; i++) {
      const page = Math.floor(i / PAGE);
      if (!loadedPages.has(page)) loadPage(page);
      let el = tiles.get(i);
      if (!el) {
        el = document.createElement("div");
        el.className = "tile";
        el.dataset.index = i;
        tiles.set(i, el);
        grid.insertBefore(el, grid.children[i - w.first] ?? null);
      }
      fillTile(el, items.get(i));
    }
  }

  function fillTile(el, item) {
    el.classList.toggle("selected", !!item && selectedSet.has(item.file_hash));
    if (!item) {
      // Seite noch unterwegs — leere Kachel als Platzhalter stehen lassen.
      if (el.dataset.hash) { delete el.dataset.hash; delete el.dataset.sig; el.innerHTML = ""; }
      return;
    }
    // Signatur statt nur Hash (ADR 0057): nach einem Soft-Refresh wird eine
    // Kachel nur neu gefüllt, wenn sich Item ODER Bewertung geändert hat —
    // unveränderte Kacheln flackern nicht.
    const sig = `${item.file_hash}:${item.rating || 0}`;
    if (el.dataset.sig === sig) return;   // schon aktuell gefüllt
    el.dataset.sig = sig;
    el.dataset.hash = item.file_hash;
    const chip = item.tool || item.container || "";
    // Platzhalter (Design-Muster: Maße mittig) liegt UNTER dem Bild — sichtbar
    // solange das Thumb lädt oder wenn keins existiert (kaputte Datei).
    el.innerHTML = `
      <span class="ph">${item.width ? `${item.width}×${item.height}` : esc(item.container || "?")}</span>
      <img alt="">
      ${item.width ? `<span class="tdim">${item.width}×${item.height}${item.fps ? ` · ${Math.round(item.fps)}fps` : ""}</span>` : ""}
      ${item.media_kind === "video" ? `<span class="badge">${STRINGS.badgeVideo}</span>` : ""}
      ${chip ? `<span class="tchip">${esc(chip)}</span>` : ""}
      ${item.rating ? `<span class="trate">${"●".repeat(item.rating)}</span>` : ""}`;
    // Thumb asynchron mit Nachfassen — 202 heißt: Prozess-Pool generiert
    // gerade (ADR 0020); der Platzhalter oben bleibt solange sichtbar.
    loadThumb(el.querySelector("img"), item.file_hash);
  }

  // -- Interaktion -------------------------------------------------------------------

  // Sorgt dafür, dass die Zeile von Item i im Sichtfenster liegt (Zeilenmathe
  // statt DOM: die Kachel existiert bei virtuellem Scrollen evtl. noch nicht).
  function ensureVisible(i) {
    if (!cols || !rowH) return;
    const stride = rowH + gap;
    const top = padTop + Math.floor(i / cols) * stride;
    const bottom = top + rowH;
    if (top < wrap.scrollTop) wrap.scrollTop = Math.max(0, top - 8);
    else if (bottom > wrap.scrollTop + wrap.clientHeight) {
      wrap.scrollTop = bottom - wrap.clientHeight + 8;
    }
  }

  // Klick-Delegation am Grid: Auswahl läuft komplett über den Bus —
  // der 'selection-changed'-Handler unten setzt Ringe, Index und Sichtbarkeit.
  // Multiselect (ADR 0022): Shift = Bereich ab Anker, Strg/Cmd = einzeln
  // dazu/weg; Sammel-Aktionen (Rating/Tag/Modell) wirken auf die Auswahl.
  grid.addEventListener("click", (e) => {
    const el = e.target.closest(".tile");
    if (!el || !el.dataset.hash) return;
    const hash = el.dataset.hash;
    const index = parseInt(el.dataset.index, 10);
    if (e.shiftKey && selectedIndex !== null) {
      const [a, b] = selectedIndex < index ? [selectedIndex, index] : [index, selectedIndex];
      const hashes = [hash];
      for (let i = a; i <= b; i++) {
        const it = items.get(i);           // nur geladene Seiten — im Sichtbereich immer da
        if (it && it.file_hash !== hash) hashes.push(it.file_hash);
      }
      // Anker (selectedIndex) bleibt für weitere Shift-Klicks stehen.
      emit("selection-changed", { hash, index: selectedIndex, hashes });
      return;
    }
    if (e.ctrlKey || e.metaKey) {
      const set = new Set(selectedSet);
      set.has(hash) ? set.delete(hash) : set.add(hash);
      if (!set.size) {
        // Auch das LETZTE Bild lässt sich abwählen (Feral Strawberry, 2026-07-11) —
        // vorher wurde es stattdessen wieder zur Einzelauswahl.
        return emit("selection-changed", { hash: null, index: null, hashes: [] });
      }
      const primary = set.has(hash) ? hash : [...set][set.size - 1];
      emit("selection-changed", { hash: primary, index, hashes: [...set] });
      return;
    }
    emit("selection-changed", { hash, index });
  });
  grid.addEventListener("dblclick", (e) => {
    // Doppelklick = Einzelbildansicht (Arbeitsansicht); Space bleibt Lupe.
    const el = e.target.closest(".tile");
    if (el && el.dataset.hash) {
      emit("single-open", { hash: el.dataset.hash, index: parseInt(el.dataset.index, 10) });
    }
  });

  // Scroll: höchstens ein Render pro Frame.
  let ticking = false;
  wrap.addEventListener("scroll", () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(() => { ticking = false; renderGrid(); });
  });
  window.addEventListener("resize", () => {
    requestAnimationFrame(() => { measureLayout(); renderGrid(); });
  });

  // Sortierung (Block S6 + ADR 0039): Theme-Knopf + eigenes Popover statt
  // <select> (das aufgeklappte System-Menü passte nicht ins Theme, Feral Strawberry).
  // Der Knopf schreibt den EINEN Suchzustand — search.js macht daraus den
  // sort:-Chip, und der wandert mit in gespeicherte Suchen. Klick auf den
  // aktiven Eintrag dreht die Richtung (Suffix -auf/-ab; die Standard-
  // richtung je Schlüssel bleibt suffixlos — kanonisch wie im Parser).
  // Nur die Dubletten-Spezialansicht liegt außerhalb des Zustands: dort
  // wirkt ?sort= direkt (Reihenfolge ändert sich komplett → Cache weg).
  const sortMenu = document.createElement("div");
  sortMenu.id = "sortmenu";
  sortMenu.hidden = true;
  document.body.appendChild(sortMenu);
  sortSel.title = STRINGS.sortTitle;

  const splitSort = (key) => {
    const [base, richtung] = [key.split("-")[0], key.split("-")[1]];
    const opt = STRINGS.sortOptions.find((o) => o.key === base) || STRINGS.sortOptions[0];
    return { base: opt.key, label: opt.label, dir: richtung || opt.dir };
  };

  function renderSortButton() {
    const s = splitSort(sortKey);
    sortSel.innerHTML = `${esc(s.label)} <span class="sortarrow">${s.dir === "auf" ? "↑" : "↓"}</span>`;
  }

  function renderSortMenu() {
    const active = splitSort(sortKey);
    sortMenu.innerHTML = STRINGS.sortOptions.map((o) => {
      const isActive = o.key === active.base;
      const dir = isActive ? active.dir : o.dir;
      return `
        <button type="button" class="sortrow${isActive ? " active" : ""}" data-key="${o.key}"
                title="${isActive ? STRINGS.sortTitle : ""}">
          <span>${esc(o.label)}</span>
          <span class="sortarrow">${dir === "auf" ? "↑" : "↓"}</span>
        </button>`;
    }).join("");
  }

  function setSort(key) {
    sortKey = key;
    // Explizite Wahl im Menü wird zum neuen Sitzungs-Standard (ADR 0057) —
    // Chips aus Grammatik/gespeicherten Suchen schreiben ihn NICHT um.
    localStorage.setItem(SORT_KEY, key);
    renderSortButton();
    if (filter.dupes) reloadGrid();
    else emit("sort-changed", { sort: key });
  }

  sortSel.addEventListener("click", () => {
    if (!sortMenu.hidden) { sortMenu.hidden = true; return; }
    renderSortMenu();
    const r = sortSel.getBoundingClientRect();
    sortMenu.style.top = `${r.bottom + 6}px`;
    sortMenu.style.right = `${window.innerWidth - r.right}px`;
    sortMenu.hidden = false;
  });
  sortMenu.addEventListener("click", (e) => {
    const row = e.target.closest(".sortrow");
    if (!row) return;
    const active = splitSort(sortKey);
    const opt = STRINGS.sortOptions.find((o) => o.key === row.dataset.key);
    if (opt.key === active.base) {
      // Aktiver Eintrag: Richtung drehen; die Standardrichtung bleibt ohne
      // Suffix (kanonischer Schlüssel wie aus filters.parse).
      const next = active.dir === "auf" ? "ab" : "auf";
      setSort(next === opt.dir ? opt.key : `${opt.key}-${next}`);
    } else {
      setSort(opt.key);
    }
    renderSortMenu();   // Menü bleibt offen: Richtungs-Klicks hintereinander
  });
  // Außenklick schließt — CAPTURE-Phase (Lehre aus Block S5: Klick-Handler,
  // die das DOM synchron neu rendern, lassen closest() sonst ins Leere laufen).
  document.addEventListener("click", (e) => {
    if (!sortMenu.hidden && !e.target.closest("#sortmenu") && !e.target.closest("#sort")) {
      sortMenu.hidden = true;
    }
  }, true);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !sortMenu.hidden) sortMenu.hidden = true;
  });

  // Dichte S/M/L: rein clientseitig (CSS-Klasse), Wahl überlebt in localStorage.
  function applyDensity(d) {
    const density = DENSITIES.includes(d) ? d : "m";
    DENSITIES.forEach((k) => grid.classList.toggle(`density-${k}`, k === density));
    localStorage.setItem(DENSITY_KEY, density);
    for (const btn of densityBox.querySelectorAll("button[data-density]")) {
      btn.classList.toggle("active", btn.dataset.density === density);
    }
    measureLayout();   // Kachelgröße hat sich geändert → neu messen
    renderGrid();
  }
  densityBox.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-density]");
    if (btn) applyDensity(btn.dataset.density);
  });

  // Der EINE Suchzustand (Block S3, ADR 0035): Chips/Live-Text kommen als
  // fertiger Grammatik-Ausdruck — das Grid kennt nur noch ?filter=
  // (interne Vereinheitlichung; ?model=/?rating= bleiben in der API).
  // Eine sort:-Direktive im Ausdruck gewinnt serverseitig über ?sort=.
  on("search-state-changed", (d) => {
    filter = d.expression ? { filter: d.expression } : {};
    // Knopf spiegelt den Zustand (S6): ohne sort:-Chip gilt der
    // Sitzungs-Standard (gemerkte Sortierung, ADR 0057).
    sortKey = d.sort || storedSort();
    renderSortButton();
    reloadGrid();
  });
  // Dubletten: Spezialansicht außerhalb des Chip-Zustands.
  on("source-changed", (d) => {
    if (d?.kind === "dupes") { filter = { dupes: 1 }; reloadGrid(); }
  });

  // Nach abgeschlossenen Engine-Aufgaben (Scan!), Ablehnen und Sammel-
  // Aktionen die Daten auffrischen — schonend (ADR 0057): Scrollposition
  // und Auswahl bleiben, statt die Ansicht komplett neu aufzubauen.
  on("engine-idle", refreshGrid);
  on("items-rejected", refreshGrid); // Ablehnen (ADR 0041): Nachfolger rückt nach
  on("bulk-applied", refreshGrid);   // Sammel-Aktion (ADR 0040): Punkte frisch

  // Auswahl-Änderung (eigener Klick, Pfeiltasten, Loupe-Blättern, Suche):
  // Ring nachziehen und die Zeile sichtbar machen — so landet man nach dem
  // Schließen der Loupe auf dem zuletzt betrachteten Bild.
  on("selection-changed", (d) => {
    selectedHash = d.hash;
    selectedIndex = d.index ?? null;
    selectedSet = new Set(d.hashes ?? (d.hash ? [d.hash] : []));
    for (const [i, el] of tiles) {
      el.classList.toggle("selected", selectedSet.has(items.get(i)?.file_hash));
    }
    if (selectedIndex !== null) ensureVisible(selectedIndex);
  });

  // Sammel-Rating (Multiselect): Punktreihen aller betroffenen Kacheln nachziehen.
  on("annotations-batch", (d) => {
    const set = new Set(d.hashes);
    for (const it of items.values()) {
      if (set.has(it.file_hash)) it.rating = d.rating;
    }
    for (const el of grid.querySelectorAll(".tile")) {
      if (!set.has(el.dataset.hash)) continue;
      el.querySelector(".trate")?.remove();
      if (d.rating) {
        el.insertAdjacentHTML("beforeend", `<span class="trate">${"●".repeat(d.rating)}</span>`);
      }
    }
  });

  // Rating geändert (Panel/Loupe/Tastatur): Kachel-Punkte live nachziehen.
  on("annotation-changed", (d) => {
    for (const it of items.values()) {
      if (it.file_hash === d.hash) it.rating = d.manual.rating;
    }
    const el = grid.querySelector(`.tile[data-hash="${d.hash}"]`);
    if (el) {
      el.querySelector(".trate")?.remove();
      if (d.manual.rating) {
        el.insertAdjacentHTML(
          "beforeend", `<span class="trate">${"●".repeat(d.manual.rating)}</span>`);
      }
    }
  });

  // Pfeiltasten in der Übersicht (Lightroom-Gefühl): ←/→ ein Item, ↑/↓ eine
  // Zeile. Nur wenn weder Loupe noch Admin offen sind und niemand tippt.
  document.addEventListener("keydown", async (e) => {
    const typing = e.target instanceof Element && e.target.matches("input, textarea, select");
    if (typing || !total) return;
    if (!document.getElementById("loupe").hidden) return;
    if (!document.getElementById("single").hidden) return;
    if (!document.getElementById("admin").hidden) return;
    if (!document.getElementById("rankings").hidden) return;  // ←/→ werten dort Duelle
    const delta = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -cols, ArrowDown: cols }[e.key];
    if (delta === undefined) return;
    e.preventDefault();   // Grid scrollt selbst (ensureVisible), nicht der Browser
    const target = selectedIndex === null
      ? 0
      : Math.max(0, Math.min(total - 1, selectedIndex + delta));
    const item = await galleryItemAt(target);
    if (item) emit("selection-changed", { hash: item.file_hash, index: target });
  });

  // -- Start ---------------------------------------------------------------------------
  applyDensity(localStorage.getItem(DENSITY_KEY));
  renderSortButton();
  reloadGrid();

  _access = {
    itemAt: async (i) => {
      if (i < 0 || i >= total) return null;
      if (!items.has(i)) await loadPage(Math.floor(i / PAGE));
      return items.get(i) || null;
    },
    total: () => total,
  };
}
