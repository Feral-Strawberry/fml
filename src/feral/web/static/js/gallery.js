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
import { getItemPosition, getItems, loadThumb, fmtDuration, kindLabel, libraryView } from "./api.js";
import { emit, on } from "./main.js";
import {
  CMP_MAX, CMP_MIN, listHeadHtml, paintRow, rowHtml, seekAt, seekTo, setTimeAxis, timeAxis, togglePlay,
} from "./audiolist.js";
import { pinTime } from "./comments.js";
import { onRepaint, playingHash } from "./player.js";
import { rate } from "./curate.js";
import { viewKinds } from "./libview.js";

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

/** Leer-Hinweis der Ansicht (ADR 0084 Punkt 2): steht ein positiver typ:-Chip,
 *  dessen Werte ALLE außerhalb des Grundbereichs liegen, zeigt die leere
 *  Ansicht, wo die Medien liegen — samt Wechsel-Knopf. Ein Chip schaltet
 *  nie selbst um. Liefert {text, goto} oder null. */
export function viewHint(predicates, view, audioEnabled) {
  if (!audioEnabled) return null;
  const inside = viewKinds(view);
  const typ = (predicates || []).find((p) => p.kind === "typ" && !p.negated);
  if (!typ || !typ.values?.length) return null;
  if (typ.values.some((v) => inside.includes(v.value))) return null;
  return view === "audio"
    ? { text: STRINGS.emptyInGallery, goto: "galerie", label: STRINGS.gotoGallery }
    : { text: STRINGS.emptyInAudioView, goto: "audio", label: STRINGS.gotoAudio };
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

/** Läuft gerade ein Vergleich in der Liste (A7)? Anzahl der Songs, sonst 0. */
export function listComparing() {
  return _access ? _access.comparing() : 0;
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
  // Audioansicht (ADR 0085): dieselbe Virtualisierung als Liste mit einer
  // Spalte — Zeilen statt Kacheln (audiolist.js), Kopfzeile #listhead.
  let listMode = libraryView() === "audio";
  let predicates = [];          // aktueller Suchzustand (Leer-Hinweis)
  let audioEnabled = false;
  const listHead = document.getElementById("listhead");
  // Vergleich in der Liste (A7, ADR 0089): die Liste zeigt nur die markierten
  // Songs, vergrößert. Der Stand der vollen Liste (Seiten-Cache, Gesamtzahl,
  // Scrollstelle, Zeitachse) wartet hier und kommt mit Esc unverändert zurück.
  let cmp = null;   // {items, loadedPages, total, scrollTop, axis, hashes, rejected, dirty}

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
      temp.className = listMode ? "tile arow" : "tile";
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
    const into = items;   // ein Vergleich tauscht items aus; die Seite gehört der vollen Liste
    try {
      // Gesamtzähler nur mit Seite 0 anfordern — der Filter-COUNT je
      // Folgeseite war beim Tief-Scrollen ein Prüf-Scan pro Anfrage.
      const d = await getItems({ limit: PAGE, offset: page * PAGE, sort: sortKey,
                                 total: page === 0 ? 1 : 0, ...filter });
      if (seq !== reloadSeq) return;   // inzwischen neu geladen (Sort/Quelle)
      if (into !== items) { d.items.forEach((it, k) => into.set(page * PAGE + k, it)); return; }
      if (d.total >= 0) total = d.total;
      if (page === 0 && listMode) setTimeAxis(d.max_duration);   // gemeinsame Zeitachse (ADR 0087)
      firstLoadDone = true;
      d.items.forEach((it, k) => items.set(page * PAGE + k, it));
      renderGrid();
    } catch (err) {
      if (seq === reloadSeq) loadedPages.delete(page);  // erneuter Versuch möglich
      console.warn(err);
    }
  }

  // keepSelection: false = „Alle Medien" in der Sidebar (Issue #33): oben
  // beginnen, keine Auswahl, kein Rücksprung. Standard true = jeder andere
  // Zustandswechsel (Chips, ✕, Esc, Sortierung) mit Rücksprung zum
  // ausgewählten Bild (ADR 0060).
  async function reloadGrid({ keepSelection = true } = {}) {
    dropCompare();                     // neue Treffermenge: der Vergleich ist vorbei
    const seq = ++reloadSeq;           // laufende Antworten alter Seiten entwerten
    firstLoadDone = false;             // „leer"-Hinweis erst NACH der Antwort
    total = 0;
    items = new Map();
    loadedPages = new Set();
    tiles.forEach((el) => el.remove());
    tiles = new Map();
    const keepHash = keepSelection ? selectedHash : null;  // Rücksprung-Anker (ADR 0060)
    selectedHash = null;               // alte Auswahl gehört zur alten Reihenfolge
    selectedIndex = null;
    selectedSet = new Set();           // sonst malt renderGrid alte Ringe nach (#33)
    wrap.scrollTop = 0;
    await loadPage(0);
    emit("items-reloaded", { total, reset: !keepSelection });
    // Zweiter Durchgang im nächsten Frame: Erst mit gesetzter Spacer-Höhe steht
    // fest, ob ein Scrollbalken erscheint (der die Spaltenbreite ändert).
    requestAnimationFrame(() => { measureLayout(); renderGrid(); });
    // Rücksprung (ADR 0060): War vor dem Zustandswechsel ein Bild ausgewählt
    // und ist es in der neuen Treffermenge noch enthalten, dorthin springen
    // statt oben neu zu beginnen — z. B. Esc aus der Seed-Varianten-Suche
    // führt so zum zuletzt angeklickten Bild zurück. Fehler sind unkritisch
    // (dann bleibt es beim Anfang der Galerie).
    if (!keepHash || !total) return;
    try {
      const pos = await getItemPosition({ hash: keepHash, sort: sortKey, ...filter });
      if (seq !== reloadSeq || selectedHash !== null) return;  // überholt/neu geklickt
      if (pos.index === null || pos.index === undefined) return;
      const it = await galleryItemAt(pos.index);
      if (seq !== reloadSeq || selectedHash !== null || !it) return;
      emit("selection-changed", { hash: it.file_hash, index: pos.index });
    } catch (err) {
      console.warn(err);
    }
  }

  // Schonender Refresh (ADR 0057): Daten neu laden, aber Scrollposition,
  // Kacheln und Auswahl BEHALTEN — im Gegensatz zu reloadGrid, das für neue
  // Filter/Sortierungen die Ansicht komplett zurücksetzt. Verschwindet das
  // ausgewählte Item (Ablehnen), rückt sein Nachfolger an derselben
  // Grid-Position nach — so lässt sich eine Serie ohne Fokusverlust
  // durchsortieren. Meldet 'items-refreshed' (Trefferzahl), bewusst NICHT
  // 'items-reloaded' — auf das reagieren Panel/Ansichten mit Zustands-Resets.
  //
  // Kein Leer-Zwischenstand (#32): Der alte Seiten-Cache bleibt bis zum
  // Eintreffen der neuen Seite stehen (ein Scroll währenddessen rendert
  // weiter die alten Kacheln) und wird dann in EINEM Schritt ersetzt. Die
  // Kacheln selbst zieht renderGrid per Hash nach — eingerückte neue Items
  // schieben die alten, statt alle Kacheln neu zu befüllen.
  async function refreshGrid() {
    let seq = ++reloadSeq;             // laufende Antworten alter Seiten entwerten
    const keepHash = selectedHash;
    const keepIndex = selectedIndex;
    // Anker: Seite der Auswahl, sonst die erste sichtbare Position.
    const anchorIndex = keepIndex ?? computeWindow({
      scrollTop: wrap.scrollTop, viewportH: wrap.clientHeight,
      padTop, rowH, gap, cols, total,
    }).first;
    const page = Math.floor(Math.max(0, anchorIndex) / PAGE);
    let d;
    try {
      d = await getItems({ limit: PAGE, offset: page * PAGE, sort: sortKey, total: 1, ...filter });
    } catch (err) {
      console.warn(err);               // alter Stand bleibt stehen, nächster Anlass lädt erneut
      return;
    }
    if (seq !== reloadSeq) return;     // inzwischen kam ein echter Reload
    // Tausch: Seiten, die während des Wartens noch in die ALTE Reihenfolge
    // geladen wurden, gehören nicht in den neuen Cache — zweite Entwertung.
    seq = ++reloadSeq;
    total = d.total;
    if (listMode) setTimeAxis(d.max_duration);
    firstLoadDone = true;
    items = new Map();
    loadedPages = new Set([page]);
    d.items.forEach((it, k) => items.set(page * PAGE + k, it));
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
      const hint = viewHint(predicates, libraryView(), audioEnabled);
      grid.innerHTML = !firstLoadDone ? ""
        : hint ? `<div class="gridempty">${esc(hint.text)} <button type="button" class="gotoview"
                    data-view="${hint.goto}">${esc(hint.label)}</button></div>`
        : `<div class="gridempty">${listMode ? STRINGS.listEmpty : STRINGS.galleryEmpty}</div>`;
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
    // … dann das Fenster in DOM-Reihenfolge auffüllen. Kacheln werden per
    // HASH wiederverwendet, nicht per Position (#32): rückt nach einem
    // Refresh oben Neues ein, wandert jedes Item um Positionen — sein
    // Kachel-Element (samt geladenem Thumb) zieht mit, statt dass jede
    // Position neu befüllt wird. Erst beanspruchen, dann den Rest aus
    // freien Kacheln decken oder neu anlegen, zuletzt die Reihenfolge
    // herstellen: die Zielposition von Index i ist immer Kind Nr. (i - first).
    const byHash = new Map();
    for (const el of tiles.values()) if (el.dataset.hash) byHash.set(el.dataset.hash, el);
    const next = new Map();
    for (let i = w.first; i < w.last; i++) {
      const page = Math.floor(i / PAGE);
      if (!loadedPages.has(page)) loadPage(page);
      const item = items.get(i);
      const el = item && byHash.get(item.file_hash);
      if (el) { next.set(i, el); byHash.delete(item.file_hash); }
    }
    const claimed = new Set(next.values());
    const spare = [...tiles.values()].filter((el) => !claimed.has(el));
    for (let i = w.first; i < w.last; i++) {
      if (next.has(i)) continue;
      let el = spare.pop();
      if (!el) { el = document.createElement("div"); el.className = "tile"; }
      next.set(i, el);
    }
    spare.forEach((el) => el.remove());
    tiles = next;
    for (let i = w.first, k = 0; i < w.last; i++, k++) {
      const el = tiles.get(i);
      el.dataset.index = i;
      if (grid.children[k] !== el) grid.insertBefore(el, grid.children[k] ?? null);
      if (listMode) fillRow(el, items.get(i), cmp ? undefined : items.get(i - 1));
      else fillTile(el, items.get(i));
    }
  }

  // Listenzeile der Audioansicht (ADR 0085). Die Signatur trägt die Vorzeile
  // mit: deren Name bestimmt den abgedunkelten gemeinsamen Anfang.
  function fillRow(el, item, prev) {
    el.classList.add("arow");
    el.classList.toggle("selected", !!item && selectedSet.has(item.file_hash));
    if (!item) {
      if (el.dataset.hash) { delete el.dataset.hash; delete el.dataset.sig; el.innerHTML = ""; }
      return;
    }
    const sig = `row:${item.file_hash}:${item.rating || 0}:${prev?.file_hash || ""}:${item.cover || ""}:${item.artwork ? 1 : 0}`;
    if (el.dataset.sig !== sig) {
      el.dataset.sig = sig;
      el.dataset.hash = item.file_hash;
      el.dataset.dur = item.duration ?? "";
      el.innerHTML = rowHtml(item, prev);
      // Miniatur: Cover finalisierter Songs (#165), sonst das eingebettete
      // Bild normaler Musik (#198) über das Vorschaubild des Songs selbst.
      const cov = el.querySelector(".rcov");
      if (cov) loadThumb(cov, item.cover || item.file_hash);
    }
    paintRow(el);
  }

  function fillTile(el, item) {
    el.classList.remove("arow", "playing");
    el.classList.toggle("selected", !!item && selectedSet.has(item.file_hash));
    if (!item) {
      // Seite noch unterwegs — leere Kachel als Platzhalter stehen lassen.
      if (el.dataset.hash) { delete el.dataset.hash; delete el.dataset.sig; el.innerHTML = ""; }
      return;
    }
    // Signatur statt nur Hash (ADR 0057): nach einem Soft-Refresh wird eine
    // Kachel nur neu gefüllt, wenn sich Item ODER Bewertung geändert hat —
    // unveränderte Kacheln flackern nicht.
    const sig = `${item.file_hash}:${item.rating || 0}:${item.cover || ""}`;
    if (el.dataset.sig === sig) return;   // schon aktuell gefüllt
    el.dataset.sig = sig;
    el.dataset.hash = item.file_hash;
    const chip = item.tool || item.container || "";
    // Platzhalter (Design-Muster: Maße mittig) liegt UNTER dem Bild — sichtbar
    // solange das Thumb lädt oder wenn keins existiert (kaputte Datei).
    // Audio (#158): ♪ als Platzhalter, Dauer statt Maßen. Ein finalisierter
    // Song (#165) zeigt das Vorschaubild seines Coverbilds — kein eigener
    // Thumbnail-Auftrag — mit ♪ + Dauer und ▶; ohne Cover keine Thumb-Anfrage.
    const audio = item.media_kind === "audio";
    const cover = audio ? item.cover : null;
    el.innerHTML = `
      <span class="ph${audio ? " audioph" : ""}">${audio ? "♪" : item.width ? `${item.width}×${item.height}` : esc(item.container || "?")}</span>
      ${audio && !cover ? "" : `<img alt="">`}
      ${item.width ? `<span class="tdim">${item.width}×${item.height}${item.fps ? ` · ${Math.round(item.fps)}fps` : ""}</span>`
        : audio && !cover && item.duration != null ? `<span class="tdim">${fmtDuration(item.duration)}</span>` : ""}
      ${cover ? `<span class="badge songbadge">♪ ${fmtDuration(item.duration)}</span>`
        : kindLabel(item) ? `<span class="badge">${kindLabel(item)}</span>` : ""}
      ${cover ? `<button type="button" class="tplay" title="${esc(STRINGS.audioPlay)}">▶</button>` : ""}
      ${chip ? `<span class="tchip">${esc(chip)}</span>` : ""}
      ${item.rating ? `<span class="trate">${"●".repeat(item.rating)}</span>` : ""}`;
    // Thumb asynchron mit Nachfassen — 202 heißt: Prozess-Pool generiert
    // gerade (ADR 0020); der Platzhalter oben bleibt solange sichtbar.
    if (!audio || cover) loadThumb(el.querySelector("img"), cover || item.file_hash);
    if (cover) paintTilePlay(el);
  }

  // ▶/❚❚ auf der Kachel eines finalisierten Songs (#165), nachgezogen vom Player.
  function paintTilePlay(el) {
    const btn = el.querySelector(".tplay");
    if (!btn) return;
    const on = playingHash() === el.dataset.hash;
    el.classList.toggle("playing", on);
    btn.textContent = on ? "❚❚" : "▶";
    btn.title = on ? STRINGS.audioPause : STRINGS.audioPlay;
  }
  onRepaint((hash) => {
    if (listMode) return;
    const sel = hash ? `#grid .tile[data-hash="${hash}"] .tplay` : "#grid .tile .tplay";
    document.querySelectorAll(sel).forEach((b) => paintTilePlay(b.closest(".tile")));
  });

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
    const go = e.target.closest(".gotoview");
    if (go) { emit("library-view-set", { view: go.dataset.view }); return; }
    const el = e.target.closest(".tile");
    if (!el || !el.dataset.hash) return;
    const hash = el.dataset.hash;
    const index = parseInt(el.dataset.index, 10);
    if (listMode) {
      const item = items.get(index);
      // Sterne in der Zeile: bewerten, ohne die Auswahl umzuwerfen; derselbe
      // Wert noch einmal nimmt ihn weg (wie im Detailpanel).
      const dot = e.target.closest(".rdot");
      if (dot && item) {
        const n = parseInt(dot.dataset.n, 10);
        rate(hash, item.rating === n ? 0 : n);
        return;
      }
      if (e.target.closest(".pbtn") && item) togglePlay(item);
      const wave = e.target.closest(".wv");
      if (wave && item) {
        const at = pinTime(e);   // Kommentar-Pin: genau an seine Stelle (#163)
        const r = wave.getBoundingClientRect();
        if (at !== null) seekAt(item, at);
        else if (r.width) seekTo(item, (e.clientX - r.left) / r.width);
      }
    } else if (e.target.closest(".tplay")) {
      togglePlay(items.get(index));   // finalisierter Song in der Galerie (#165)
    }
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
    if (!el || !el.dataset.hash) return;
    if (listMode) {
      // Liste: Doppelklick spielt (die Einzelansicht zeigt Songs nur mit
      // Cover, aus der Galerie — #165).
      if (!e.target.closest(".pbtn, .rdot, .wv")) togglePlay(items.get(parseInt(el.dataset.index, 10)));
      return;
    }
    emit("single-open", { hash: el.dataset.hash, index: parseInt(el.dataset.index, 10) });
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
    predicates = d.predicates || [];
    filter = d.expression ? { filter: d.expression } : {};
    // Knopf spiegelt den Zustand (S6): ohne sort:-Chip gilt der
    // Sitzungs-Standard (gemerkte Sortierung, ADR 0057).
    sortKey = d.sort || storedSort();
    renderSortButton();
    reloadGrid({ keepSelection: !d.reset });
  });
  // Ansichtswechsel (ADR 0085): Darstellung sofort umstellen und die alten
  // Kacheln räumen; GELADEN wird erst auf den Suchzustand hin, den search.js
  // danach (ggf. um unmögliche Medienart-Chips ausgedünnt) neu verkündet.
  function applyListMode() {
    grid.classList.toggle("list", listMode);
    listHead.hidden = !listMode;
    if (listMode) {
      listHead.innerHTML = listHeadHtml();
    }
  }
  on("library-view-changed", (d) => {
    dropCompare();
    listMode = d.view === "audio";
    reloadSeq++;                      // Antworten der alten Ansicht verwerfen
    firstLoadDone = false;
    total = 0;
    items = new Map();
    loadedPages = new Set();
    tiles.forEach((el) => el.remove());
    tiles = new Map();
    applyListMode();
    measureLayout();
    renderGrid();
  });
  on("audio-enabled", (d) => { audioEnabled = !!d?.enabled; if (!total) renderGrid(); });

  // Dubletten: Spezialansicht außerhalb des Chip-Zustands.
  on("source-changed", (d) => {
    if (d?.kind === "dupes") { filter = { dupes: 1 }; reloadGrid(); }
  });

  // Nach abgeschlossenen Engine-Aufgaben (Scan!), Ablehnen und Sammel-
  // Aktionen die Daten auffrischen — schonend (ADR 0057): Scrollposition
  // und Auswahl bleiben, statt die Ansicht komplett neu aufzubauen.
  // Im Vergleich wartet der Refresh bis Esc: er holte sonst die volle Liste
  // in die eingeengte.
  const refreshLater = () => { if (cmp) cmp.dirty = true; else refreshGrid(); };
  on("engine-idle", refreshLater);
  on("items-rejected", (d) => {      // Ablehnen (ADR 0041): Nachfolger rückt nach
    if (cmp) compareDrop(d.hashes || []); else refreshGrid();
  });
  on("bulk-applied", refreshLater);  // Sammel-Aktion (ADR 0040): Punkte frisch
  on("cover-changed", refreshLater); // Cover (#165): Song kommt in die Galerie oder geht

  // -- Vergleich in der Liste (A7, ADR 0089) ----------------------------------------------

  function announceCompare() {
    grid.classList.toggle("compare", !!cmp);
    grid.classList.toggle("pinlabels", !!cmp);   // Kommentartexte stehen (comments.js)
    document.body.classList.toggle("list-compare", !!cmp);   // Zeilen sind der Player: Leiste weg
    emit("list-compare-changed", { on: !!cmp, n: cmp ? total : 0 });
  }

  function showCompare(list, index) {
    items = new Map(list.map((it, k) => [k, it]));
    loadedPages = new Set([0]);        // nichts nachladen: die Auswahl ist komplett da
    total = list.length;
    setTimeAxis(Math.max(...list.map((it) => it.duration || 0)));   // Achse der Verglichenen
    announceCompare();
    measureLayout();
    renderGrid();
    const it = list[Math.min(index, list.length - 1)];
    // Nur EINE Zeile ist ausgewählt: 1–5, Entf und K treffen sie, nicht alle.
    emit("selection-changed", { hash: it.file_hash, index: list.indexOf(it) });
  }

  function enterCompare() {
    if (!listMode || cmp) return;
    const list = [...items.entries()]
      .filter(([, it]) => it && selectedSet.has(it.file_hash))
      .sort((a, b) => a[0] - b[0]).map(([, it]) => it);
    if (list.length < CMP_MIN || list.length > CMP_MAX) return;
    cmp = { items, loadedPages, total, scrollTop: wrap.scrollTop, axis: timeAxis(),
            hashes: list.map((it) => it.file_hash), rejected: new Set(), dirty: false };
    wrap.scrollTop = 0;
    const cur = list.findIndex((it) => it.file_hash === selectedHash);
    showCompare(list, Math.max(0, cur));
  }

  // Abgelehnte Songs verlassen den Vergleich; die Zeile darunter rückt nach.
  function compareDrop(hashes) {
    const gone = new Set(hashes);
    const before = [...items.values()];
    const list = before.filter((it) => !gone.has(it.file_hash));
    if (list.length === before.length) return;
    hashes.forEach((h) => cmp.rejected.add(h));
    cmp.dirty = true;
    if (!list.length) { exitCompare(); return; }
    showCompare(list, selectedIndex ?? 0);
  }

  // Esc: volle Liste mit derselben Scrollstelle; die übrigen Songs bleiben
  // markiert (C vergleicht sie erneut), die aktuelle Zeile bleibt die Auswahl.
  function exitCompare() {
    if (!cmp) return;
    const back = cmp;
    cmp = null;
    const cur = selectedHash && !back.rejected.has(selectedHash) ? selectedHash : null;
    items = back.items;
    loadedPages = back.loadedPages;
    total = back.total;
    setTimeAxis(back.axis);
    announceCompare();
    measureLayout();
    renderGrid();                      // Spacer-Höhe steht, bevor gescrollt wird
    wrap.scrollTop = back.scrollTop;
    let index = null;
    for (const [i, it] of items) if (it && it.file_hash === cur) { index = i; break; }
    const rest = back.hashes.filter((h) => !back.rejected.has(h));
    emit("selection-changed", cur
      ? { hash: cur, index, hashes: rest.includes(cur) ? rest : [cur, ...rest] }
      : { hash: null, index: null, hashes: [] });
    wrap.scrollTop = back.scrollTop;   // die Auswahl darf die Stelle nicht verschieben
    renderGrid();
    if (back.dirty) refreshGrid();     // Abgelehntes/Frisches erst jetzt nachziehen
  }

  // Ohne Rückweg verwerfen (neue Suche, Ansichtswechsel): der alte Stand ist ungültig.
  function dropCompare() {
    if (!cmp) return;
    cmp = null;
    announceCompare();
  }

  on("list-compare-set", (d) => (d?.on ? enterCompare() : exitCompare()));

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
    if (listMode) { renderGrid(); return; }   // Zeilen-Signatur trägt die Bewertung
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
    if (listMode) { renderGrid(); return; }
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
  // Zeile. Nur wenn keine Loupe offen ist und niemand tippt.
  document.addEventListener("keydown", async (e) => {
    const typing = e.target instanceof Element && e.target.matches("input, textarea, select");
    if (typing || !total) return;
    if (!document.getElementById("loupe").hidden) return;
    if (!document.getElementById("single").hidden) return;
    if (!document.getElementById("rankings").hidden) return;  // ←/→ werten dort Duelle
    const delta = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -cols, ArrowDown: cols }[e.key];
    if (delta === undefined) return;
    // Liste: nur ↑/↓ wechseln die Zeile; ←/→ gehören dem Sprung im Song (A5).
    if (listMode && (e.key === "ArrowLeft" || e.key === "ArrowRight")) return;
    e.preventDefault();   // Grid scrollt selbst (ensureVisible), nicht der Browser
    const target = selectedIndex === null
      ? 0
      : Math.max(0, Math.min(total - 1, selectedIndex + delta));
    const item = await galleryItemAt(target);
    if (item) emit("selection-changed", { hash: item.file_hash, index: target });
  });

  // -- Start ---------------------------------------------------------------------------
  applyListMode();
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
    comparing: () => (cmp ? total : 0),
  };
}
