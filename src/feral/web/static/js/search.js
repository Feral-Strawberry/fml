// search.js — EIN Suchzustand aus Chips (Großbaustelle S, Block S3, ADR 0035).
//
// Der Zustand ist die Filtergrammatik: kanonischer Text = einzige Wahrheit
// und Speicherformat; geparst/serialisiert wird ausschließlich serverseitig
// (/api/filter/parse + /api/filter/build — EIN Parser, EIN Serialisierer,
// keine zweite Grammatik in JavaScript). Chips sind die Ansicht der
// Prädikate im Breadcrumb-Bereich:
//
//   [ Modell: flux | krea ✕ ] [ Text: wüste ✕ ] [ ★ ≥ 4 ✕ ]  ☆ Speichern
//
// Wege in den Zustand: Sidebar-Klick ('chip-toggle' — zweiter Wert derselben
// Gruppe erweitert zum ODER, aktiver Wert togglet weg), Texteingabe (filtert
// das Grid LIVE, Enter macht text:-Chips) und getippte Grammatik-Ausdrücke
// (werden zu Chips zerlegt). Die frühere Snippet-Trefferliste ist ersatzlos
// weg — das Thumbnail-Grid ist die Antwort. Die Dubletten-Ansicht bleibt
// eine Spezialansicht außerhalb des Chip-Zustands.

import { STRINGS } from "./strings.js";
import { parseFilter, buildFilter } from "./api.js";
import { emit, on } from "./main.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Sieht die Eingabe wie ein Grammatik-Ausdruck aus (feld:/tag:/rating>=)?
// Auch von der Tipphilfe genutzt (advanced.js): bei Ausdrücken keine Vorschläge.
export const looksLikeExpr = (s) =>
  /(^|\s)-?[a-zA-Z_]+\s*:/.test(s)
  || /(^|\s)-?(rating|width|height|fps)\s*(>=|<=|=)/.test(s);

// Begriffe der Texteingabe: "…" hält Wortfolgen zusammen (FTS-Phrase).
const splitTerms = (s) => s.match(/"[^"]*"|\S+/g) || [];

// Gruppenschlüssel fürs Zusammenlegen: gleiche Art + Feld + Negation = ein
// Chip, weitere Werte werden ODER (ADR 0035).
const groupKey = (p) => `${p.negated ? "-" : ""}${p.kind}:${p.field || ""}`;

// -- Chip-Beschriftung (auch vom Speicherdialog genutzt, Block S7) ---------------

const OPS = { ">=": "≥", "<=": "≤", "=": "=" };

function chipLabel(p) {
  if (p.kind === "field") {
    return STRINGS.chipFieldLabels[p.field] || p.field;
  }
  return STRINGS.chipKindLabels[p.kind] || p.kind;
}

export function chipText(p) {
  if (p.kind === "rating") {
    const n = parseInt(p.values[0]?.value ?? "0", 10);
    if (p.op === "=" && n === 0) return STRINGS.chipUnrated;
    return `★ ${OPS[p.op] || p.op} ${n}`;
  }
  if (p.kind === "metric") {
    return `${p.field} ${OPS[p.op] || p.op} ${p.values[0]?.value ?? ""}`;
  }
  if (p.kind === "sort") {
    // Deutsches Label statt rohem Schlüssel („Erstellt", nicht „created");
    // unbekannte Schlüssel erscheinen roh (ehrlich statt geraten).
    // Richtungs-Suffix -auf/-ab (ADR 0039) wird als Pfeil gezeigt.
    const key = p.values[0]?.value ?? "";
    const [base, richtung] = [key.split("-")[0], key.split("-")[1]];
    const opt = STRINGS.sortOptions.find((o) => o.key === base);
    if (!opt) return `${chipLabel(p)}: ${key}`;
    const dir = richtung || opt.dir;
    return `${chipLabel(p)}: ${opt.label} ${dir === "auf" ? "↑" : "↓"}`;
  }
  const vals = p.values.map((v) => v.value).join(" | ");
  return `${chipLabel(p)}: ${vals}`;
}

export function initSearch() {
  const q = document.getElementById("q");
  const crumb = document.getElementById("crumb");
  // Fest verankerte Kopfzeilen-Knöpfe rechts (Feral Strawberry, 2026-07-11 — die
  // Chip-Leiste war zu voll): Speichern + Filter zurücksetzen + Sammel-Aktion.
  // Seit 2026-07-16 als EINE Gruppe: reicht die Breite nicht, rutschen alle
  // drei gemeinsam unter die Chips (layoutHead); unter FullHD-Breite zeigen
  // Zurücksetzen/Sammel-Aktion nur noch ihr Icon (.btnlabel, app.css).
  const head = document.getElementById("midhead");
  const tools = document.getElementById("midtools");
  const saveBtn = document.getElementById("saveBtn");
  const resetBtn = document.getElementById("filterReset");
  const bulkBtn = document.getElementById("bulkBtn");
  // Icon und Text als getrennte Spans (Flex, app.css): Symbol-Glyphen
  // (☆/✕/⚡) kommen je Plattform aus anderen Fonts (Windows: Segoe UI
  // Symbol/Emoji) mit größeren Vertikal-Metriken — auf EINER Baseline
  // zogen sie den Text 1–2 px nach unten (Feral Strawberrys Opera/Win11-Befund).
  // ︎ erzwingt beim ⚡ die Text-Darstellung (sonst Farb-Emoji).
  saveBtn.innerHTML = `<span class="btnicon">☆</span><span>${esc(STRINGS.folderSave)}</span>`;
  saveBtn.title = STRINGS.folderSaveTitle;
  resetBtn.innerHTML = `<span class="btnicon">✕</span><span class="btnlabel">${esc(STRINGS.filterReset)}</span>`;
  resetBtn.title = STRINGS.filterResetTitle;
  bulkBtn.innerHTML = `<span class="btnicon">⚡︎</span><span class="btnlabel">${esc(STRINGS.bulkOpen)}</span>`;
  bulkBtn.title = STRINGS.bulkOpenTitle;

  // Passt die Chip-Zeile MIT der Knopf-Gruppe in eine Zeile? Gemessen wird
  // die Chip-Breite ohne Umbruch (.measure schaltet flex-wrap kurz ab) —
  // wenn nicht, wandert die Gruppe geschlossen unter die Chips (.stacked).
  function layoutHead() {
    head.classList.remove("stacked");
    crumb.classList.add("measure");
    const need = crumb.offsetWidth;
    crumb.classList.remove("measure");
    const cs = getComputedStyle(head);
    const avail = head.clientWidth
      - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    if (tools.offsetWidth && need + 10 + tools.offsetWidth > avail) {
      head.classList.add("stacked");
    }
  }
  new ResizeObserver(layoutHead).observe(head);

  let state = { expression: "", predicates: [], sort: null };
  let dupes = false;        // Spezialansicht außerhalb des Chip-Zustands
  let liveTerms = [];       // getippte, noch nicht festgemachte Begriffe
  let galleryTotal = 0;
  let stateSeq = 0;         // entwertet überholte Server-Antworten
  let editorIndex = null;   // offener Chip-Editor (Index in predicates)

  // -- Zustand anwenden ---------------------------------------------------------

  // Live-Begriffe hängen als flüchtige text:-Prädikate am Ausdruck — das Grid
  // filtert beim Tippen, ohne dass der Chip-Zustand sich ändert.
  const effectiveExpression = () =>
    [state.expression, ...liveTerms.map((t) => `text: ${t}`)]
      .filter(Boolean).join(" ");

  function announce() {
    emit("search-state-changed", {
      expression: effectiveExpression(),
      predicates: state.predicates,
      sort: state.sort,
    });
  }

  function setState(d) {
    state = d;
    dupes = false;
    hideError();
    renderChips();
    announce();
  }

  /** Getippten/gespeicherten Ausdruck übernehmen (ersetzt den Zustand). */
  async function loadExpression(expr) {
    const seq = ++stateSeq;
    if (!expr.trim()) {
      setState({ expression: "", predicates: [], sort: null });
      return true;
    }
    try {
      const d = await parseFilter(expr);
      if (seq !== stateSeq) return false;
      liveTerms = [];
      setState(d);
      return true;
    } catch (err) {
      if (seq === stateSeq) showError(err.message);
      return false;
    }
  }

  /** Chip-Zustand (bearbeitete Prädikate) serverseitig kanonisieren. */
  async function setPredicates(preds) {
    const seq = ++stateSeq;
    if (!preds.length) {
      setState({ expression: "", predicates: [], sort: null });
      return;
    }
    try {
      const d = await buildFilter(preds);
      if (seq !== stateSeq) return;
      setState(d);
    } catch (err) {
      if (seq === stateSeq) showError(err.message);
    }
  }

  // -- Chips rendern --------------------------------------------------------------

  function renderChips() {
    // Präfix als eigenes Element: unter FullHD-Breite ausgeblendet (app.css).
    const parts = [`<span class="crumbroot">${STRINGS.crumbLibrary} /</span>`];
    if (dupes) {
      parts.push(`<b>${esc(STRINGS.dupes)}</b>`);
    } else if (!state.predicates.length) {
      parts.push(`<b>${esc(STRINGS.allMedia)}</b>`);
    } else {
      parts.push(state.predicates.map((p, i) => `
        <span class="chip${p.negated ? " neg" : ""}${p.kind === "sort" ? " sort" : ""}" data-i="${i}">
          ${p.negated ? `<span class="chipneg" title="${STRINGS.chipEditNegate}">${STRINGS.chipNegated}</span>` : ""}
          <span class="chiptext">${esc(chipText(p))}</span>
          <button type="button" class="chipx" title="${STRINGS.chipRemove}">✕</button>
        </span>`).join(""));
    }
    parts.push(`<span class="crumbcount">· ${galleryTotal.toLocaleString(STRINGS.locale)}</span>`);
    if (!dupes) {
      // „+ Kriterium" (Block S5): advanced.js öffnet das Popover (Bus).
      parts.push(`<button type="button" class="crumbadd" title="${STRINGS.addCriterionTitle}">+ ${STRINGS.addCriterion}</button>`);
    }
    parts.push(`<span class="chiperr" hidden></span>`);
    crumb.innerHTML = parts.join(" ");
    // Speichern + Sammel-Aktion (Großbaustelle K) + Filter zurücksetzen
    // sitzen als EINE Gruppe in #midtools statt im Chip-Fluss.
    saveBtn.hidden = !(state.expression && !dupes);
    bulkBtn.hidden = dupes || galleryTotal <= 0;
    resetBtn.hidden = !(state.predicates.length || liveTerms.length || dupes);
    layoutHead();
    if (editorIndex !== null) positionEditor();
  }

  function showError(message) {
    const el = crumb.querySelector(".chiperr");
    if (el) {
      el.textContent = `⚠ ${message}`;
      el.hidden = false;
    }
  }
  function hideError() {
    const el = crumb.querySelector(".chiperr");
    if (el) el.hidden = true;
  }

  // -- Chip-Editor (Werte ergänzen/entfernen, Negation) ---------------------------

  const editor = document.createElement("div");
  editor.id = "chipeditor";
  editor.hidden = true;
  document.body.appendChild(editor);

  // Werte lassen sich nur bei Werte-Prädikaten ergänzen; Vergleiche und die
  // Sortier-Direktive haben genau einen Wert (Grammatik, ADR 0035).
  const canAddValues = (p) => !["rating", "metric", "sort"].includes(p.kind);

  function openEditor(i) {
    editorIndex = i;
    renderEditor();
    positionEditor();
  }

  function closeEditor() {
    editorIndex = null;
    editor.hidden = true;
  }

  function renderEditor() {
    const p = state.predicates[editorIndex];
    if (!p) { closeEditor(); return; }
    editor.innerHTML = `
      <div class="cevalues">
        ${p.values.map((v, k) => `
          <span class="cechip">${esc(v.exact ? `"${v.value}"` : v.value)}
            <button type="button" class="cevx" data-k="${k}" title="${STRINGS.chipEditRemoveValue}">✕</button>
          </span>`).join("")}
      </div>
      ${canAddValues(p) ? `<input type="text" class="ceadd" placeholder="${STRINGS.chipEditAddValue}">` : ""}
      ${p.kind !== "sort" ? `
        <label class="ceneg"><input type="checkbox" class="cenegbox"${p.negated ? " checked" : ""}>
          ${STRINGS.chipEditNegate}</label>` : ""}
      <button type="button" class="cedel">${STRINGS.chipEditDelete}</button>`;
    editor.hidden = false;
  }

  function positionEditor() {
    const el = crumb.querySelector(`.chip[data-i="${editorIndex}"]`);
    if (!el) { closeEditor(); return; }
    const r = el.getBoundingClientRect();
    editor.style.left = `${Math.min(r.left, window.innerWidth - 300)}px`;
    editor.style.top = `${r.bottom + 6}px`;
  }

  /** Kopie der Prädikate für Mutationen (Server liefert den neuen Zustand). */
  const clonePreds = () =>
    state.predicates.map((p) => ({ ...p, values: p.values.map((v) => ({ ...v })) }));

  editor.addEventListener("click", async (e) => {
    const p0 = state.predicates[editorIndex];
    if (!p0) return;
    const vx = e.target.closest(".cevx");
    if (vx) {
      const preds = clonePreds();
      preds[editorIndex].values.splice(parseInt(vx.dataset.k, 10), 1);
      // Letzter Wert weg = Chip weg — dann zeigt der Index auf den NÄCHSTEN
      // Chip, also Editor schließen statt fremde Werte anzuzeigen.
      const chipRemoved = !preds[editorIndex].values.length;
      if (chipRemoved) preds.splice(editorIndex, 1);
      await setPredicates(preds);
      chipRemoved ? closeEditor() : renderEditor();
      return;
    }
    if (e.target.closest(".cedel")) {
      const preds = clonePreds();
      preds.splice(editorIndex, 1);
      closeEditor();
      await setPredicates(preds);
    }
  });
  editor.addEventListener("change", async (e) => {
    if (!e.target.matches(".cenegbox")) return;
    const preds = clonePreds();
    preds[editorIndex].negated = e.target.checked;
    await setPredicates(preds);
    state.predicates[editorIndex] ? renderEditor() : closeEditor();
  });
  editor.addEventListener("keydown", async (e) => {
    if (e.key !== "Enter" || !e.target.matches(".ceadd")) return;
    const raw = e.target.value.trim();
    if (!raw) return;
    const exact = raw.startsWith('"') && raw.endsWith('"') && raw.length > 1;
    const preds = clonePreds();
    preds[editorIndex].values.push({ value: exact ? raw.slice(1, -1) : raw, exact });
    await setPredicates(preds);
    state.predicates[editorIndex] ? renderEditor() : closeEditor();
  });
  document.addEventListener("click", (e) => {
    if (editorIndex !== null && !e.target.closest("#chipeditor") && !e.target.closest(".chip")) {
      closeEditor();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && editorIndex !== null) closeEditor();
  });

  // -- Chip-Leiste: Klicks ----------------------------------------------------------

  crumb.addEventListener("click", async (e) => {
    const x = e.target.closest(".chipx");
    if (x) {
      const i = parseInt(x.closest(".chip").dataset.i, 10);
      closeEditor();
      const preds = clonePreds();
      preds.splice(i, 1);
      await setPredicates(preds);
      return;
    }
    const chip = e.target.closest(".chip");
    if (chip) {
      openEditor(parseInt(chip.dataset.i, 10));
      return;
    }
  });

  // Speicherdialog (Block S7, savedialog.js) — er kennt aus 'state-load'
  // selbst, ob gerade eine gespeicherte Suche bearbeitet wird.
  saveBtn.addEventListener("click", () => {
    if (!state.expression) return;
    emit("save-dialog-open", {
      expression: state.expression,
      predicates: state.predicates,
      sort: state.sort,
      total: galleryTotal,
    });
  });

  // -- Kopfzeilen-Knöpfe: Filter zurücksetzen + Sammel-Aktion --------------------------

  // Alles leeren — Klick auf „Filter zurücksetzen"/„Alle Medien" oder Esc.
  // setState → announce lässt auch die Dubletten-Spezialansicht hinter sich
  // (dupes wird in setState zurückgesetzt, das Grid lädt neutral).
  function clearAll() {
    q.value = "";
    liveTerms = [];
    closeEditor();
    setState({ expression: "", predicates: [], sort: null });
  }

  resetBtn.addEventListener("click", clearAll);
  bulkBtn.addEventListener("click", () => {
    emit("bulk-dialog-open", {
      expression: effectiveExpression(),
      predicates: state.predicates,
      liveTerms,
      total: galleryTotal,
    });
  });

  // Esc = Filter zurücksetzen (Feral Strawberry, 2026-07-11) — aber NUR, wenn Esc
  // gerade nichts anderes bedeutet: kein Overlay/Popover/Dialog offen,
  // niemand tippt (das Suchfeld leert sich mit Esc selbst). Die Overlays
  // behalten ihre eigenen Esc-Handler; hier wird nur geprüft, nicht geschlossen.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (e.target instanceof Element && e.target.matches("input, textarea, select")) return;
    if (!document.getElementById("loupe").hidden) return;
    if (!document.getElementById("single").hidden) return;
    if (!document.getElementById("admin").hidden) return;
    if (editorIndex !== null) return;                                  // Chip-Editor
    if (document.querySelector(".pickoverlay:not([hidden])")) return;  // Theme-Dialoge
    if (!(document.getElementById("sortmenu")?.hidden ?? true)) return;
    if (!(document.getElementById("addcrit")?.hidden ?? true)) return; // + Kriterium
    if (!(document.getElementById("typeahead")?.hidden ?? true)) return;
    if (!(state.predicates.length || liveTerms.length || dupes)) return;
    clearAll();
  });

  // -- Suchfeld: live filtern, Enter macht Chips --------------------------------------

  let liveTimer = null;
  q.addEventListener("input", () => {
    clearTimeout(liveTimer);
    const text = q.value.trim();
    if (looksLikeExpr(text)) return;   // Ausdrücke erst komplett tippen (Enter)
    liveTimer = setTimeout(() => {
      // Erst ab 3 Zeichen (Feral Strawberry, 2026-07-07): zwei Buchstaben treffen bei
      // 250k praktisch alles und machen nur Last.
      const next = text.length >= 3 ? splitTerms(text) : [];
      if (next.join("\n") === liveTerms.join("\n")) return;
      liveTerms = next;
      renderChips();
      announce();
    }, 350);
  });

  q.addEventListener("keydown", async (e) => {
    if (e.key === "Escape" && q.value) {
      q.value = "";
      if (liveTerms.length) { liveTerms = []; renderChips(); announce(); }
      return;
    }
    if (e.key !== "Enter") return;
    clearTimeout(liveTimer);
    const text = q.value.trim();
    if (!text) return;
    // Grammatik-Ausdruck ODER Begriffe → beides landet als Chips im EINEN
    // Zustand (additiv zum Bestehenden — Eingaben werfen den Kontext nicht weg).
    const addition = looksLikeExpr(text)
      ? text
      : splitTerms(text).map((t) => `text: ${t}`).join(" ");
    if (await loadExpression([state.expression, addition].filter(Boolean).join(" "))) {
      q.value = "";
    }
  });

  // -- Bus: Sidebar & Co. --------------------------------------------------------------

  // Sidebar-Klick: Wert togglen — neuer Wert derselben Gruppe erweitert den
  // Chip zum ODER, aktiver Wert fliegt raus (leerer Chip verschwindet).
  on("chip-toggle", async (d) => {
    const pred = d.pred;
    const preds = clonePreds();
    // Gegensätzliche has:-Zeilen derselben Facette (Block S4, „mit/ohne
    // Eingangsbild") ersetzen einander — beide zusammen wären immer 0 Treffer.
    if (pred.kind === "has" && pred.values.length === 1) {
      const opposite = preds.findIndex((p) =>
        p.kind === "has" && p.negated !== pred.negated
        && p.values.length === 1 && p.values[0].value === pred.values[0].value);
      if (opposite >= 0) preds.splice(opposite, 1);
    }
    const hit = preds.find((p) => groupKey(p) === groupKey(pred));
    if (!hit) {
      preds.push(pred);
    } else if (pred.kind === "rating" || pred.kind === "metric" || pred.kind === "sort") {
      // Vergleiche und sort: kennen kein ODER (ADR 0035): gleicher Wert = weg,
      // anderer Wert = ersetzen.
      if (hit.values[0]?.value === pred.values[0].value && hit.op === pred.op) {
        preds.splice(preds.indexOf(hit), 1);
      } else {
        hit.values = pred.values;
        hit.op = pred.op;
      }
    } else {
      // Werte-Bündel (z. B. WAN-2.2 High/Low, Block N) togglen als EINHEIT:
      // sind alle Werte aktiv, fliegen alle raus — sonst fehlende ergänzen.
      // Für Ein-Wert-Prädikate ist das exakt das alte Verhalten.
      const present = pred.values.filter((v) =>
        hit.values.some((h) => h.value === v.value));
      if (present.length === pred.values.length) {
        hit.values = hit.values.filter((h) =>
          !pred.values.some((v) => v.value === h.value));
        if (!hit.values.length) preds.splice(preds.indexOf(hit), 1);
      } else {
        for (const v of pred.values) {
          if (!hit.values.some((h) => h.value === v.value)) hit.values.push(v);
        }
      }
    }
    closeEditor();
    await setPredicates(preds);
  });

  // Sortier-Dropdown der Galerie (Block S6): setzt statt zu togglen — eine
  // <select>-Auswahl ist eine Setz-Operation. Der Standard (added) heißt
  // „keine sort:-Direktive" (Chip verschwindet, gespeicherte Ausdrücke
  // bleiben clean); alles andere ersetzt den einen sort:-Chip.
  on("sort-changed", async (d) => {
    const preds = clonePreds().filter((p) => p.kind !== "sort");
    if (d.sort && d.sort !== "added") {
      preds.push({ kind: "sort", negated: false, field: "", op: "=",
                   values: [{ value: d.sort, exact: false }] });
    }
    closeEditor();
    await setPredicates(preds);
  });

  // Gespeicherte Suche laden: Ausdruck → Chips (alles wird bearbeitbar).
  on("state-load", (d) => { closeEditor(); loadExpression(d.expression); });

  // Fertige Prädikate übernehmen (Seed-Varianten aus dem Detail-Panel,
  // Feral Strawberry 2026-07-16): ERSETZT den Zustand — die Chips machen die Suche
  // transparent und per Chip-Löschen lockerbar. Validierung wie immer
  // serverseitig über /api/filter/build (EIN Parser, ADR 0035).
  on("predicates-load", async (d) => {
    q.value = "";
    liveTerms = [];
    closeEditor();
    await setPredicates(d.predicates);
  });

  // „Alle Medien": Zustand leeren.
  on("state-clear", () => {
    q.value = "";
    liveTerms = [];
    closeEditor();
    setState({ expression: "", predicates: [], sort: null });
  });

  // Dubletten: Spezialansicht außerhalb des Chip-Zustands (gallery filtert).
  on("source-changed", (d) => {
    if (d?.kind !== "dupes") return;
    q.value = "";
    liveTerms = [];
    closeEditor();
    state = { expression: "", predicates: [], sort: null };
    dupes = true;
    renderChips();
  });

  on("items-reloaded", (d) => {
    galleryTotal = d.total;
    renderChips();
  });
  // Schonender Refresh (ADR 0057): nur die Trefferzahl nachziehen — die
  // Zustands-Resets der items-reloaded-Konsumenten sollen hier NICHT feuern.
  on("items-refreshed", (d) => {
    galleryTotal = d.total;
    renderChips();
  });

  renderChips();
}
