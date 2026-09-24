// advanced.js — Advanced Mode (Block S5, ADR 0038): „+ Kriterium"-Popover
// und Tipphilfe im Suchfeld.
//
// Beide erzeugen NUR 'chip-toggle'-Events — search.js legt den Chip an,
// erweitert ihn zum ODER oder entfernt den Wert (derselbe Weg wie die
// Sidebar; Mehrfachauswahl im Popover ergibt so automatisch ODER-Chips).
// Die Wertelisten zählen im aktuellen Kontext: dieselben Endpunkte wie die
// Sidebar (?filter= mit serverseitigem Gruppen-Ausschluss, ADR 0037);
// 0-Einträge werden gedimmt statt versteckt.

import { STRINGS } from "./strings.js";
import { getSidebar, libraryView } from "./api.js";
import { viewKinds } from "./libview.js";
import { emit, on } from "./main.js";
import { looksLikeExpr, parseTypedValue } from "./search.js";
import { displayModelName, modelChipValues, modelTitle } from "./sidebar.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Aktiv-Schlüssel wie in sidebar.js — Werte im Suchzustand werden markiert.
const akeyOf = (p) =>
  `${p.negated ? "-" : ""}${p.kind}:${p.field || ""}:${p.values[0].value}`;

// Vollständiges Prädikat-Dict (Form von /api/filter/parse).
const pred = (kind, value, extra = {}) => ({
  kind, negated: false, field: "", op: "=",
  values: [{ value: String(value), exact: false }], ...extra,
});
const exactField = (field, value) =>
  pred("field", value, { field, values: [{ value, exact: true }] });

// Medienart (ADR 0084): Audio nur mit Modul (Schalter meldet die Sidebar
// über 'audio-enabled'); vorhandene Arten + Zähler kommen vom Server.
let audioEnabled = false;
const mediaKinds = (d) =>
  (d.facets.media_kinds || []).filter((m) => m.typ !== "audio" || audioEnabled);
// Wörter, die eine Medienart GENAU treffen: kanonischer Wert, Anzeigename
// und die Grammatik-Aliasse (filters._TYPE_ALIASES: image → bild).
const TYPE_ALIASES = { bild: ["image"] };
const typeWords = (typ) => [typ, (STRINGS.mediaKindLabels[typ] ?? typ).toLowerCase(),
                            ...(TYPE_ALIASES[typ] || [])];

// Sortier-Schlüssel des Popovers = die Galerie-Optionen (seit Block S6
// inkl. created — EINE Liste in strings.de.js, kein Sonderfall mehr).
const SORT_OPTIONS = STRINGS.sortOptions;

// Kategorien des Popovers (Design-Doc §3.3), seit ADR 0084 in Sidebar-
// Reihenfolge, danach was nur hier steht (Popover = alles). `rows(data)` liefert Wertezeilen
// {label, count, pred, title?}; count === null = kein Zähler (z. B. sort).
// `neg: true` = Kategorie bekommt den „ausschließen"-Schalter; Zeilen mit
// eigenem negated (z. B. „ohne Eingangsbild") sind davon ausgenommen.
const CATS = [
  { key: "rating", label: STRINGS.groupByRating, rows: (d) => [
    ...d.ratings.ratings.map((r) => ({
      label: "★".repeat(r.rating), count: r.count,
      pred: pred("rating", r.rating),
    })),
    { label: STRINGS.chipUnrated, count: null, title: "rating=0", pred: pred("rating", 0) },
  ]},
  // Medienart (ADR 0084): nur vorhandene Arten, Audio nur mit Modul.
  // `scope` (ADR 0084 Punkt 5): Medienarten, für die die Kategorie Sinn
  // ergibt — sichtbar, wenn sie sich mit dem Grundbereich der Ansicht
  // schneiden (visibleCats). Ohne scope: überall.
  { key: "typ", label: STRINGS.groupByMediaKind, neg: true, scope: ["bild", "video"], rows: (d) =>
    mediaKinds(d).map((m) => ({
      label: STRINGS.mediaKindLabels[m.typ] ?? m.typ, count: m.count,
      title: `typ: ${m.typ}`, pred: pred("typ", m.typ),
    })),
  },
  // Songtext (ADR 0084): Gesang (has: lyrics) oder instrumental; nur Audio.
  { key: "lyrics", label: STRINGS.groupByLyrics, scope: ["audio"], rows: (d) => [
    { label: STRINGS.lyricsWith, count: d.facets.lyrics?.mit ?? 0,
      title: "has: lyrics", pred: pred("has", "lyrics") },
    { label: STRINGS.lyricsWithout, count: d.facets.lyrics?.ohne ?? 0,
      title: "-has: lyrics", pred: pred("has", "lyrics", { negated: true }) },
  ]},
  { key: "tool", label: STRINGS.groupByGenerator, neg: true, rows: (d) =>
    (d.facets.tools || []).map((x) => ({
      label: Object.hasOwn(STRINGS.generatorLabels, x.tool) ? STRINGS.generatorLabels[x.tool] : x.tool,
      count: x.count, title: `tool: ${x.tool}`, pred: exactField("tool", x.tool),
    })),
  },
  { key: "model", label: STRINGS.groupByModel, neg: true, rows: (d) => [
    ...d.models.models.map((x) => ({
      label: displayModelName(x.model), count: x.count, title: modelTitle(x),
      // WAN-2.2-Bündel (Block N): alle Roh-Varianten in EINEM Prädikat.
      pred: pred("field", x.model, { field: "model", values: modelChipValues(x) }),
    })),
    ...(d.models.unknown_total ?? d.models.unknown ? [{
      label: STRINGS.modelUnknown, count: d.models.unknown, title: "-has: model",
      pred: pred("has", "model", { negated: true }),
    }] : []),
  ]},
  { key: "lora", label: STRINGS.groupByLora, neg: true, scope: ["bild", "video"], rows: (d) =>
    (d.facets.loras || []).map((x) => ({
      label: x.lora, count: x.count, pred: exactField("lora", x.lora),
    })),
  },
  { key: "year", label: STRINGS.groupByYear, neg: true, rows: (d) => [
    ...d.facets.years.map((y) => ({
      label: String(y.year), count: y.count, pred: pred("year", y.year),
    })),
    ...((d.facets.undated_total ?? d.facets.undated) ? [{
      label: STRINGS.yearUnknown, count: d.facets.undated, pred: pred("year", "unbekannt"),
    }] : []),
  ]},
  { key: "container", label: STRINGS.groupByContainer, neg: true, rows: (d) =>
    d.facets.containers.map((c) => ({
      label: c.container.toUpperCase(), count: c.count, pred: pred("container", c.container),
    })),
  },
  { key: "format", label: STRINGS.groupByFormat, neg: true, scope: ["bild", "video"], rows: (d) =>
    Object.entries(STRINGS.formatLabels).map(([key, label]) => ({
      label, count: d.facets.formats[key] ?? 0, pred: pred("format", key),
    })),
  },
  { key: "mp", label: STRINGS.groupByMegapixels, neg: true, scope: ["bild", "video"], rows: (d) =>
    Object.entries(STRINGS.megapixelLabels).map(([key, label]) => ({
      label, count: d.facets.megapixels?.[key] ?? 0, pred: pred("mp", key),
    })),
  },
  { key: "inputimage", label: STRINGS.groupByInputImage, scope: ["bild", "video"], rows: (d) => [
    { label: STRINGS.inputImageWith, count: d.facets.input_image?.mit ?? 0,
      title: "has: input_image", pred: pred("has", "input_image") },
    { label: STRINGS.inputImageWithout, count: d.facets.input_image?.ohne ?? 0,
      title: "-has: input_image", pred: pred("has", "input_image", { negated: true }) },
  ]},
  // Fundort (ADR 0041, I2): nur mit konfigurierter Library — ohne Root gibt
  // es keine Werte (leere Kategorie zeigt ehrlich „Keine Werte vorhanden").
  { key: "fundort", label: STRINGS.groupByFundort, rows: (d) => d.facets.fundort ? [
    { label: STRINGS.fundortLibrary, count: d.facets.fundort.library,
      title: STRINGS.gramFundortLibrary, pred: pred("fundort", "library") },
    { label: STRINGS.fundortExtern, count: d.facets.fundort.extern,
      title: STRINGS.gramFundortExtern, pred: pred("fundort", "extern") },
  ] : []},
  { key: "tag", label: STRINGS.acCatTags, neg: true, rows: (d) =>
    (d.facets.tags || []).map((x) => ({
      label: x.tag, count: x.count,
      pred: pred("tag", x.tag, { values: [{ value: x.tag, exact: true }] }),
    })),
  },
  { key: "text", label: STRINGS.acCatText, input: true,
    placeholder: STRINGS.acTextPlaceholder, hint: STRINGS.acTextHint, kind: "text" },
  // Dauer (ADR 0083/0084): Eingabe wie dauer: — gilt für Audio und Video.
  { key: "dauer", label: STRINGS.acCatDuration, input: true,
    placeholder: STRINGS.acDurationPlaceholder, hint: STRINGS.acDurationHint, kind: "dauer" },
  { key: "metric", label: STRINGS.acCatMetrics, metric: true },
  { key: "raw", label: STRINGS.acCatRaw, input: true,
    placeholder: STRINGS.acRawPlaceholder, hint: STRINGS.acRawHint, kind: "raw" },
  // Dateiname der Fundorte (Feral Strawberry, 2026-07-16): Freitext-Eingabe wie raw.
  { key: "datei", label: STRINGS.acCatDatei, input: true,
    placeholder: STRINGS.acDateiPlaceholder, hint: STRINGS.acDateiHint, kind: "datei" },
  { key: "sort", label: STRINGS.acCatSort, rows: () =>
    SORT_OPTIONS.map((o) => ({
      label: o.label, count: null, title: `sort: ${o.key}`, pred: pred("sort", o.key),
    })),
  },
];

/** Kategorien, die im Grundbereich der aktuellen Ansicht Sinn ergeben. */
export const visibleCats = (view = libraryView()) =>
  CATS.filter((c) => !c.scope || c.scope.some((k) => viewKinds(view).includes(k)));

/** Navigationszeile der Tipphilfe (ADR 0084 Punkt 3): trifft das Wort eine
 *  Medienart GENAU, die außerhalb des Grundbereichs liegt („audio" in der
 *  Galerie), bietet die Liste den Wechsel der Ansicht an statt eines Chips
 *  — der Suchzustand bleibt unberührt. Audio nur mit Modul. */
export function navSuggestion(term, view = libraryView(), audioOn = audioEnabled) {
  const t = term.toLowerCase();
  const inside = viewKinds(view);
  for (const typ of Object.keys(STRINGS.mediaKindLabels)) {
    if (inside.includes(typ) || (typ === "audio" && !audioOn)) continue;
    if (!typeWords(typ).includes(t)) continue;
    const goto = typ === "audio" ? "audio" : "galerie";
    return { nav: goto, catLabel: STRINGS.taView,
             label: goto === "audio" ? STRINGS.gotoAudio : STRINGS.gotoGallery };
  }
  return null;
}

export function initAdvanced() {
  const q = document.getElementById("q");

  // -- Gemeinsamer Daten-Cache (Popover + Tipphilfe) ------------------------------
  // Ein Satz Facetten-Antworten je Ausdruck; Engine-/Kuratier-Ereignisse
  // entwerten ihn (dieselben Trigger wie der Sidebar-Refresh).

  let filter = "";                 // aktiver Ausdruck (inkl. Live-Begriffe)
  let activeKeys = new Set();      // aktive Werte für die Markierung
  let cache = { forFilter: null, promise: null };

  function facetData() {
    if (cache.forFilter !== filter) {
      const f = filter || undefined;
      cache = {
        forFilter: filter,
        promise: getSidebar(f),   // {models, facets, ratings} aus EINEM Lauf (#99)
      };
    }
    return cache.promise;
  }
  const invalidate = () => { cache = { forFilter: null, promise: null }; };
  on("engine-idle", invalidate);
  on("annotation-changed", invalidate);
  on("model-changed", invalidate);
  on("items-rejected", invalidate);
  on("audio-enabled", (d) => { audioEnabled = !!d?.enabled; });
  // Ansichtswechsel (ADR 0085): andere Zähl-Basis, andere Kategorien.
  on("library-view-changed", () => {
    invalidate();
    if (!visibleCats().some((c) => c.key === activeCat)) activeCat = visibleCats()[0].key;
    if (!pop.hidden) renderShell();
  });

  on("search-state-changed", (d) => {
    activeKeys = new Set();
    for (const p of d.predicates || []) {
      for (const v of p.values || []) {
        activeKeys.add(`${p.negated ? "-" : ""}${p.kind}:${p.field || ""}:${v.value}`);
      }
    }
    if (filter !== (d.expression || "")) {
      filter = d.expression || "";
      invalidate();
    }
    if (!pop.hidden) renderPane();       // Zähler + Markierungen nachziehen
  });

  // -- „+ Kriterium"-Popover -------------------------------------------------------

  const pop = document.createElement("div");
  pop.id = "addcrit";
  pop.hidden = true;
  document.body.appendChild(pop);

  let activeCat = CATS[0].key;
  let negMode = false;            // „ausschließen"-Schalter der aktiven Kategorie
  let paneSeq = 0;                // entwertet überholte Daten-Antworten

  function openPopover(anchor) {
    const r = anchor.getBoundingClientRect();
    pop.hidden = false;
    pop.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - 480))}px`;
    pop.style.top = `${Math.max(8, r.bottom + 6)}px`;
    renderShell();
  }
  function closePopover() { pop.hidden = true; }

  function renderShell() {
    pop.innerHTML = `
      <div class="accats">
        ${visibleCats().map((c) => `
          <button type="button" class="accat${c.key === activeCat ? " active" : ""}"
                  data-cat="${c.key}">${esc(c.label)}</button>`).join("")}
      </div>
      <div class="acpane"></div>`;
    renderPane();
  }

  const rowHtml = (v, withNeg) => {
    // Zeilen mit fest eingebautem negated (unbekanntes Modell, „ohne
    // Eingangsbild") ignorieren den Schalter — sonst hebt er sie auf.
    const p = withNeg && !v.pred.negated ? { ...v.pred, negated: negMode } : v.pred;
    return `
      <div class="acrow${v.count === 0 ? " dim" : ""}${activeKeys.has(akeyOf(p)) ? " active" : ""}"
           data-pred="${esc(JSON.stringify(p))}" title="${esc(v.title ?? v.label)}">
        <span class="aclabel">${esc(v.label)}</span>
        ${v.count === null ? "" : `<span class="account">${v.count.toLocaleString(STRINGS.locale)}</span>`}
      </div>`;
  };

  async function renderPane() {
    const pane = pop.querySelector(".acpane");
    if (!pane) return;
    const cat = CATS.find((c) => c.key === activeCat);
    if (cat.input) {
      pane.innerHTML = `
        <input type="text" class="acinput" data-kind="${cat.kind}" placeholder="${esc(cat.placeholder)}">
        <label class="acneg"><input type="checkbox" class="acnegbox"${negMode ? " checked" : ""}> ${STRINGS.acNegate}</label>
        <div class="achint">${esc(cat.hint)}</div>`;
      pane.querySelector(".acinput").focus();
      return;
    }
    if (cat.metric) {
      pane.innerHTML = `
        <div class="acmetric">
          <select class="acmfield">${Object.entries(STRINGS.metricLabels).map(([k, l]) =>
            `<option value="${k}">${esc(l)}</option>`).join("")}</select>
          <select class="acmop"><option>&gt;=</option><option>&lt;=</option><option>=</option></select>
          <input type="number" class="acmvalue" min="0" step="any">
          <button type="button" class="acmadd">${STRINGS.acMetricAdd}</button>
        </div>
        <div class="achint">${esc(STRINGS.acMetricHint)}</div>`;
      pane.querySelector(".acmvalue").focus();
      return;
    }
    const seq = ++paneSeq;
    pane.innerHTML = `<div class="achint">${STRINGS.acLoading}</div>`;
    let data;
    try { data = await facetData(); }
    catch (err) { console.warn(err); pane.innerHTML = `<div class="achint">${STRINGS.serverUnreachable}</div>`; return; }
    if (seq !== paneSeq || pop.hidden) return;
    const rows = cat.rows(data);
    pane.innerHTML = `
      ${cat.neg ? `<label class="acneg"><input type="checkbox" class="acnegbox"${negMode ? " checked" : ""}> ${STRINGS.acNegate}</label>` : ""}
      <div class="acrows">${rows.length ? rows.map((v) => rowHtml(v, cat.neg)).join("")
        : `<div class="achint">${STRINGS.acEmpty}</div>`}</div>`;
  }

  pop.addEventListener("click", (e) => {
    const catBtn = e.target.closest(".accat");
    if (catBtn) {
      activeCat = catBtn.dataset.cat;
      negMode = false;
      renderShell();
      return;
    }
    const row = e.target.closest(".acrow");
    if (row) {
      // Popover bleibt offen: Mehrfachauswahl = ODER (chip-toggle merged).
      emit("chip-toggle", { pred: JSON.parse(row.dataset.pred) });
      return;
    }
    if (e.target.closest(".acmadd")) {
      const field = pop.querySelector(".acmfield").value;
      const op = pop.querySelector(".acmop").value;
      const value = pop.querySelector(".acmvalue").value.trim();
      if (!value) return;
      emit("chip-toggle", { pred: pred("metric", value, { field, op }) });
    }
  });
  pop.addEventListener("change", (e) => {
    if (e.target.matches(".acnegbox")) {
      negMode = e.target.checked;
      renderPane();
    }
  });
  pop.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    if (e.target.matches(".acinput")) {
      const raw = e.target.value.trim();
      if (!raw) return;
      const typed = parseTypedValue(raw);
      if (!typed.value) return;
      emit("chip-toggle", { pred: {
        ...pred(e.target.dataset.kind, typed.value), negated: negMode,
        values: [typed],
      }});
      e.target.value = "";
    } else if (e.target.matches(".acmvalue")) {
      pop.querySelector(".acmadd").click();
    }
  });

  // Öffnen über den Knopf in der Chip-Leiste (search.js rendert ihn neu —
  // deshalb Delegation); Klick daneben schließt. Capture-Phase: der
  // Kategorie-Klick ersetzt das Popover-DOM synchron — beim Bubbling wäre
  // das Target schon detached und closest("#addcrit") liefe ins Leere.
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".crumbadd");
    if (btn) {
      pop.hidden ? openPopover(btn) : closePopover();
      return;
    }
    if (!pop.hidden && !e.target.closest("#addcrit")) closePopover();
  }, true);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !pop.hidden) closePopover();
  });

  // -- Tipphilfe im Suchfeld --------------------------------------------------------

  const ta = document.createElement("div");
  ta.id = "typeahead";
  ta.hidden = true;
  document.body.appendChild(ta);

  let suggestions = [];
  let selIndex = -1;

  // Vorschläge aus den Facetten-Daten: Kategorie-Reihenfolge = Priorität,
  // innerhalb einer Kategorie Präfix-Treffer vor Teilstring-Treffern, dann
  // nach Zähler. Bewusst einfach — hier lässt sich später nach Gefühl
  // nachschärfen (z. B. Kategorien umgewichten), ohne etwas zu zerbrechen.
  // Medienart (ADR 0084): trifft das Wort eine Art GENAU (Wert, Name oder
  // Alias), steht diese Zeile vorn und ist vorausgewählt (Enter = typ:);
  // unten folgt dann die Zeile „Volltext" — sichtbar, was Enter sonst täte.
  // Liefert {rows, sel}.
  function buildSuggestions(term, data) {
    const t = term.toLowerCase();
    const out = [];
    let exact = null;
    const push = (catLabel, label, count, p) => {
      const l = label.toLowerCase();
      if (!l.includes(t)) return;
      out.push({ catLabel, label, count, pred: p, prefix: l.startsWith(t) });
    };
    for (const m of mediaKinds(data)) {
      const row = { catLabel: STRINGS.chipKindLabels.typ, label: STRINGS.mediaKindLabels[m.typ] ?? m.typ,
                    count: m.count, pred: pred("typ", m.typ) };
      if (typeWords(m.typ).includes(t)) exact = row;
      else push(row.catLabel, row.label, row.count, row.pred);
    }
    for (const x of data.models.models) {
      push(STRINGS.chipFieldLabels.model, displayModelName(x.model), x.count,
           pred("field", x.model, { field: "model", values: modelChipValues(x) }));
    }
    for (const x of data.facets.loras || []) {
      push(STRINGS.chipFieldLabels.lora, x.lora, x.count, exactField("lora", x.lora));
    }
    for (const x of data.facets.tags || []) {
      push(STRINGS.chipKindLabels.tag, x.tag, x.count,
           pred("tag", x.tag, { values: [{ value: x.tag, exact: true }] }));
    }
    for (const c of data.facets.containers) {
      push(STRINGS.chipKindLabels.container, c.container.toUpperCase(), c.count,
           pred("container", c.container));
    }
    for (const [key, label] of Object.entries(STRINGS.formatLabels)) {
      push(STRINGS.chipKindLabels.format, label, data.facets.formats[key] ?? 0,
           pred("format", key));
    }
    for (const y of data.facets.years) {
      push(STRINGS.chipKindLabels.year, String(y.year), y.count, pred("year", y.year));
    }
    out.sort((a, b) => (b.prefix - a.prefix) || (b.count - a.count));
    if (!exact) exact = navSuggestion(term);
    if (!exact) return { rows: out.slice(0, 8), sel: -1 };
    return { rows: [exact, ...out.slice(0, 7), { fulltext: true, catLabel: STRINGS.taFulltext, label: term }],
             sel: 0 };
  }

  function hideTa() { ta.hidden = true; suggestions = []; selIndex = -1; }

  function renderTa() {
    if (!suggestions.length) { hideTa(); return; }
    const r = q.getBoundingClientRect();
    ta.style.left = `${r.left}px`;
    ta.style.top = `${r.bottom + 4}px`;
    ta.style.minWidth = `${r.width}px`;
    ta.innerHTML = suggestions.map((s, i) => `
      <div class="tarow${i === selIndex ? " active" : ""}${s.count === 0 ? " dim" : ""}${s.fulltext ? " tafull" : ""}" data-i="${i}">
        <span class="tacat">${esc(s.catLabel)}:</span>
        <span class="talabel">${esc(s.label)}</span>
        ${s.fulltext || s.nav ? "" : `<span class="tacount">${s.count.toLocaleString(STRINGS.locale)}</span>`}
      </div>`).join("")
      + `<div class="tahint">${STRINGS.taHint}</div>`;
    ta.hidden = false;
  }

  function applySuggestion(i) {
    const s = suggestions[i];
    if (!s) return;
    if (s.nav) {
      // Navigation, kein Chip: das Wort verschwindet, die Ansicht wechselt.
      q.value = "";
      q.dispatchEvent(new Event("input", { bubbles: true }));
      hideTa();
      emit("library-view-set", { view: s.nav });
      return;
    }
    if (s.fulltext) {
      // „Volltext": derselbe Weg wie Enter ohne Auswahl (search.js macht
      // text:-Chips) — Liste zu, dann Enter am Suchfeld.
      hideTa();
      q.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
      return;
    }
    emit("chip-toggle", { pred: s.pred });
    q.value = "";
    q.dispatchEvent(new Event("input", { bubbles: true }));  // Live-Begriffe leeren
    hideTa();
    q.focus();
  }

  let taTimer = null;
  q.addEventListener("input", () => {
    clearTimeout(taTimer);
    const term = q.value.trim();
    if (term.length < 2 || looksLikeExpr(term)) { hideTa(); return; }
    taTimer = setTimeout(async () => {
      let data;
      try { data = await facetData(); } catch { return; }
      // Eingabe kann sich während des Requests geändert haben.
      if (q.value.trim() !== term) return;
      ({ rows: suggestions, sel: selIndex } = buildSuggestions(term, data));
      renderTa();
    }, 250);
  });

  // Capture auf document: läuft VOR dem Enter-/Escape-Handler von search.js —
  // eine markierte Zeile fängt Enter ab, sonst macht Enter wie gehabt
  // text:-Chips (Design §3.3).
  document.addEventListener("keydown", (e) => {
    if (ta.hidden || e.target !== q) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      const step = e.key === "ArrowDown" ? 1 : -1;
      selIndex = (selIndex + step + suggestions.length) % suggestions.length;
      renderTa();
      e.preventDefault();
    } else if (e.key === "Enter" && selIndex >= 0 && !suggestions[selIndex].fulltext) {
      applySuggestion(selIndex);
      e.preventDefault();
      e.stopPropagation();
    } else if (e.key === "Enter" || e.key === "Escape") {
      hideTa();
      if (e.key === "Escape") e.stopPropagation();  // erst Dropdown, dann Feld leeren
    }
  }, true);

  ta.addEventListener("click", (e) => {
    const row = e.target.closest(".tarow");
    if (row) applySuggestion(parseInt(row.dataset.i, 10));
  });
  document.addEventListener("click", (e) => {
    if (!ta.hidden && e.target !== q && !e.target.closest("#typeahead")) hideTa();
  });
}
