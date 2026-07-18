// sidebar.js — linke Quellen-Spalte: Gruppe „Bibliothek" (Alle Medien) und
// Facetten-Gruppen (Modell/LoRA/Bewertung/Jahr/Dateityp/Format/Auflösung/
// Eingangsbild).
//
// Kommuniziert nur über den Bus. Seit Block S3 (ADR 0035) füttern die
// Facetten-Zeilen den EINEN Suchzustand: Klick = 'chip-toggle' (ein weiterer
// Wert derselben Gruppe wird ODER, ein aktiver Wert fliegt raus); aktive
// Werte werden aus 'search-state-changed' markiert. Gespeicherte Suchen
// laden ihren Ausdruck als Chips ('state-load'), „Alle Medien" leert den
// Zustand ('state-clear'), Dubletten bleiben eine Spezialansicht
// ('source-changed'). Unten ein Bestands-Footer (Items · Gesamtgröße).
//
// Seit Block S4 (ADR 0037) FILTERN die Zähler MIT: der aktive Suchzustand
// geht als ?filter= an die Endpunkte, jede Gruppe zählt im Kontext der
// ANDEREN Chips (den Gruppen-Ausschluss macht der Server), 0-Einträge
// werden gedimmt statt versteckt — sichtbar bleibt, was es gäbe.

import { STRINGS } from "./strings.js";
import { getStats, getModels, getFacets, getRatings, getFolders, deleteFolder, getRankings } from "./api.js";
import { emit, on } from "./main.js";
import { serverMsg } from "./servermsg.js";

// TODO(Feral Strawberry) — bewusst offengehalten:
// Roh-Modellwerte aus den Metadaten (z. B. "sd_xl_base_1.0.safetensors")
// auf lesbare Sidebar-Namen mappen. Vorschlag: Liste von [RegExp, Label]-
// Paaren durchprobieren; unbekannte Werte unverändert zurückgeben.
// Erster Schritt (Feral Strawberry, 2026-07-09): Modelldatei-Endungen abstreifen —
// ComfyUI führt ".safetensors" & Co. mit, A1111 nicht; ohne Anzeigewert.
// Varianten-Mapping bewusst NICHT (ein Buchstabe Unterschied ist oft
// bedeutsam bei ~60 Checkpoints). Nur Anzeige: Tooltip (title) und
// Filter (data-value) behalten den Rohwert.
// Export: auch das „+ Kriterium"-Popover und die Tipphilfe (advanced.js)
// zeigen Modellnamen ohne Datei-Endung an (Block S5).
export function displayModelName(raw) {
  return raw.replace(/\.(safetensors|sft|ckpt|pt|pth|gguf)$/i, "");
}

// WAN-2.2-Bündel (Block N, ADR 0043): gefaltete Facetten-Einträge tragen die
// Roh-Namen als `variants` — der Chip filtert exakt über ALLE Rohwerte
// (model: high | low), nie über den kanonischen Anzeigenamen (den gibt es
// als Rohwert nicht). Auch von advanced.js genutzt.
export const modelChipValues = (x) =>
  (x.variants || [x.model]).map((v) => ({ value: v, exact: true }));
export const modelTitle = (x) => (x.variants || [x.model]).join(" | ");

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export function initSidebar() {
  const nav = document.getElementById("sidebar");
  nav.innerHTML = `
    <div class="sbscroll">
      <div class="sbgroup" data-group="library">
        <div class="mlabel">${STRINGS.groupLibrary}</div>
        <div class="sbrow active" data-kind="all">
          <span class="sbdot" style="background:var(--faint)"></span>
          <span class="sblabel">${STRINGS.allMedia}</span>
          <span class="sbcount" id="sbAllCount"></span>
        </div>
        <div class="sbrow" data-kind="dupes">
          <span class="sbdot" style="background:#5b8def"></span>
          <span class="sblabel">${STRINGS.dupes}</span>
          <span class="sbcount" id="sbDupesCount"></span>
        </div>
      </div>
      <div class="sbgroup" data-group="folders">
        <div class="mlabel">${STRINGS.groupSmartFolders}</div>
        <div id="sbFolders"></div>
      </div>
      <div class="sbgroup" data-group="rankings" hidden>
        <div class="mlabel">${STRINGS.groupRankings}</div>
        <div id="sbRankings"></div>
      </div>
      <div class="sbgroup" data-group="rating">
        <div class="mlabel">${STRINGS.groupByRating}</div>
        <div id="sbRatings"></div>
      </div>
      <div class="sbgroup" data-group="model">
        <div class="mlabel">${STRINGS.groupByModel}</div>
        <div id="sbModels"></div>
      </div>
      <div class="sbgroup" data-group="lora">
        <div class="mlabel">${STRINGS.groupByLora}</div>
        <div id="sbLoras"></div>
      </div>
      <div class="sbgroup" data-group="year">
        <div class="mlabel">${STRINGS.groupByYear}</div>
        <div id="sbYears"></div>
      </div>
      <div class="sbgroup" data-group="container">
        <div class="mlabel">${STRINGS.groupByContainer}</div>
        <div id="sbContainers"></div>
      </div>
      <div class="sbgroup" data-group="format">
        <div class="mlabel">${STRINGS.groupByFormat}</div>
        <div id="sbFormats"></div>
      </div>
      <div class="sbgroup" data-group="megapixels">
        <div class="mlabel">${STRINGS.groupByMegapixels}</div>
        <div id="sbMegapixels"></div>
      </div>
      <div class="sbgroup" data-group="inputimage">
        <div class="mlabel">${STRINGS.groupByInputImage}</div>
        <div id="sbInputImage"></div>
      </div>
      <div class="sbgroup" data-group="fundort" hidden>
        <div class="mlabel">${STRINGS.groupByFundort}</div>
        <div id="sbFundort"></div>
      </div>
    </div>
    <div class="sbfooter">
      <div class="mlabel">${STRINGS.sidebarFooter}</div>
      <div id="sbTotals" class="sbtotals"></div>
    </div>`;

  const modelsBox = nav.querySelector("#sbModels");
  const lorasBox = nav.querySelector("#sbLoras");
  const ratingsBox = nav.querySelector("#sbRatings");
  const foldersBox = nav.querySelector("#sbFolders");
  const containersBox = nav.querySelector("#sbContainers");
  const formatsBox = nav.querySelector("#sbFormats");
  const megapixelsBox = nav.querySelector("#sbMegapixels");
  const inputImageBox = nav.querySelector("#sbInputImage");
  const fundortBox = nav.querySelector("#sbFundort");
  const yearsBox = nav.querySelector("#sbYears");

  // Gruppen ein-/ausklappbar (Feral Strawberry, 2026-07-07: „wird langsam voll"), Klick
  // auf die Überschrift; Zustand überlebt in localStorage.
  const COLLAPSED_KEY = "feral-sb-collapsed";
  const collapsed = new Set(JSON.parse(localStorage.getItem(COLLAPSED_KEY) || "[]"));
  const openMonths = new Set();   // aufgeklappte Jahre (Session-Gedächtnis)
  for (const group of nav.querySelectorAll(".sbgroup[data-group]")) {
    group.classList.toggle("collapsed", collapsed.has(group.dataset.group));
  }
  nav.addEventListener("click", (e) => {
    const label = e.target.closest(".mlabel");
    const group = label && label.closest(".sbgroup[data-group]");
    if (!group) return;
    const key = group.dataset.group;
    collapsed.has(key) ? collapsed.delete(key) : collapsed.add(key);
    group.classList.toggle("collapsed", collapsed.has(key));
    localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...collapsed]));
  });

  // Facetten-Zeile (Block S3): trägt ihr Ein-Wert-Prädikat als JSON
  // (data-chip) — Klick togglet den Wert im Suchzustand (chip-toggle) —
  // und einen Aktiv-Schlüssel (data-akey) fürs Markieren aktiver Werte.
  const akeyOf = (chip) =>
    `${chip.negated ? "-" : ""}${chip.kind}:${chip.field || ""}:${chip.values[0].value}`;
  // count 0 = im aktuellen Kontext leer → gedimmt, aber klickbar (Block S4).
  const chipRow = (chip, label, dot, count, title) => `
    <div class="sbrow${count === 0 ? " dim" : ""}" data-chip="${esc(JSON.stringify(chip))}"
         data-akey="${esc(akeyOf(chip))}" title="${esc(title ?? label)}">
      <span class="sbdot" style="background:${dot}"></span>
      <span class="sblabel">${esc(label)}</span>
      <span class="sbcount">${count.toLocaleString(STRINGS.locale)}</span>
    </div>`;
  // Kurzform für Werte-Prädikate ohne Feld (container/format/mp/year/month).
  const pred = (kind, value, extra = {}) =>
    ({ kind, negated: false, field: "", op: "=", values: [{ value: String(value), exact: false }], ...extra });

  async function loadFolders() {
    try {
      const d = await getFolders();
      foldersBox.innerHTML = d.folders.length
        ? d.folders.map((f) => `
            <div class="sbrow" data-kind="folder" data-value="${esc(f.expression)}"
                 data-id="${f.id}" title="${esc(f.expression)}${f.error ? " — " + esc(serverMsg(f.error)) : ""}">
              <span class="sbdot" style="background:#d9a441"></span>
              <span class="sblabel">${esc(f.name)}</span>
              <button type="button" class="sbdel" title="${STRINGS.folderDelete}">✕</button>
              <span class="sbcount">${f.count === null ? "⚠" : f.count.toLocaleString(STRINGS.locale)}</span>
            </div>`).join("")
        : `<div class="sbempty">${STRINGS.foldersEmpty}</div>`;
    } catch (err) { console.warn(err); }
  }

  // Ranking-Modul (ADR 0045): Gruppe NUR bei aktivem Modul-Schalter —
  // inaktiv stellt die Sidebar keine Ranking-Queries. Der Zähler ist die
  // Live-Population der Arena (Ausdruck kaputt geworden → ⚠ wie bei
  // gespeicherten Suchen); Duelle stehen im Tooltip.
  let rankingsEnabled = false;
  const rankingsBox = nav.querySelector("#sbRankings");
  async function loadArenas() {
    if (!rankingsEnabled) return;
    try {
      const d = await getRankings();
      rankingsBox.innerHTML = d.rankings.map((r) => `
          <div class="sbrow" data-kind="arena" data-id="${r.id}"
               data-name="${esc(r.name)}" data-expr="${esc(r.expression)}"
               title="${esc(r.expression || STRINGS.allMedia)} · ${r.duels} ${STRINGS.rankingDuels}${r.error ? " — " + esc(serverMsg(r.error)) : ""}">
            <span class="sbdot" style="background:#e05b8f"></span>
            <span class="sblabel">${esc(r.name)}</span>
            <span class="sbcount">${r.population === null ? "⚠" : r.population.toLocaleString(STRINGS.locale)}</span>
          </div>`).join("")
        + `<div class="sbrow" data-kind="arena-new">
            <span class="sbdot" style="background:var(--faint)"></span>
            <span class="sblabel vdim">${STRINGS.rankingNew}</span>
          </div>`;
    } catch (err) { console.warn(err); }
  }

  async function loadRatings() {
    try {
      const ratings = await getRatings(currentFilter || undefined);
      // Exakte Verteilung (= n Sterne): auch gezielt schlecht Bewertetes
      // filtern können (Feral Strawberry, 2026-07-08), beste zuerst. rating ist ein
      // Vergleich (kein ODER) — Klick ersetzt/entfernt den Wert (search.js).
      ratingsBox.innerHTML = ratings.ratings.length === 0
        ? `<div class="sbempty">${STRINGS.sidebarNoRatings}</div>`
        : ratings.ratings.map((r) =>
            chipRow(pred("rating", r.rating), "★".repeat(r.rating), "#d9a441", r.count)).join("");
      refreshHighlights();
    } catch (err) { console.warn(err); }
  }

  // Zähler-Refresh, robust (Feral Strawberrys 100-GB-Runde, 2026-07-08 — „Nach Jahr"
  // blieb nach Neustarts leer/alt): (1) die drei Endpunkte unabhängig
  // verarbeiten statt Alles-oder-nichts — ein einzelner Fehlschlag riss
  // vorher AUCH die Jahres-/Format-Gruppen mit ab; (2) veraltete Antworten
  // verwerfen (Sequenznummer — parallele Refreshes konnten sich sonst in
  // falscher Reihenfolge überschreiben); (3) wenn gar nichts ankam (Seite
  // öffnet, bevor der Server fertig gebootet hat — start.bat!), automatisch
  // mit Backoff nachfassen statt auf das nächste Zufalls-Event zu warten.
  let countsSeq = 0;
  let retryTimer = null;
  let retryDelay = 1000;
  // Aktiver Suchzustand (Block S4): geht als ?filter= an die Zähler-Endpunkte.
  let currentFilter = "";
  async function loadCounts() {
    const seq = ++countsSeq;
    clearTimeout(retryTimer);
    const filter = currentFilter || undefined;
    const [stats, models, facets] = await Promise.allSettled([
      getStats(), getModels(filter), getFacets(filter),
    ]);
    if (seq !== countsSeq) return;   // eine jüngere Anfrage läuft schon
    loadRatings();
    if (stats.status === "fulfilled") {
      const s = stats.value;
      nav.querySelector("#sbAllCount").textContent =
        s.total_items.toLocaleString(STRINGS.locale);
      nav.querySelector("#sbDupesCount").textContent =
        s.items_multi_location.toLocaleString(STRINGS.locale);
      const size = (b) => b >= 1e9
        ? `${(b / 1e9).toLocaleString(STRINGS.locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} GB`
        : `${Math.round(b / 1e6).toLocaleString(STRINGS.locale)} MB`;
      // Library vs. indiziert gesamt getrennt (ADR 0041, I2) — ohne
      // konfigurierte Library gibt es die Unterscheidung nicht.
      const items = s.total_items.toLocaleString(STRINGS.locale);
      nav.querySelector("#sbTotals").textContent = s.library_configured
        ? STRINGS.totalsLibrary.replace("{items}", items)
            .replace("{lib}", size(s.library_bytes)).replace("{total}", size(s.total_bytes))
        : STRINGS.totalsPlain.replace("{items}", items)
            .replace("{size}", size(s.total_bytes));
      // Ranking-Modul (ADR 0045): Gruppe nach dem Config-Schalter ein-/
      // ausblenden. Arenen nur beim Umschalten laden — loadCounts läuft
      // bei jedem Filterwechsel, die Populationen hängen davon nicht ab.
      if (rankingsEnabled !== !!s.rankings) {
        rankingsEnabled = !!s.rankings;
        nav.querySelector('.sbgroup[data-group="rankings"]').hidden = !rankingsEnabled;
        loadArenas();
      }
    }
    if (models.status === "fulfilled") {
      const m = models.value;
      // „(unbekanntes Modell)" — Items ohne Schicht-2-Modellfeld (Midjourney,
      // Gemini, ChatGPT, …) sollen sichtbar sein statt still herauszufallen.
      // Zeile bleibt, solange es sie GLOBAL gibt (unknown_total); der Zähler
      // ist der Kontext-Wert (0 = gedimmt, Block S4).
      const unknownRow = (m.unknown_total ?? m.unknown)
        ? chipRow(pred("has", "model", { negated: true }),
                  STRINGS.modelUnknown, "var(--faint)", m.unknown, "-has: model")
        : "";
      // Modell-Chips sind exakt ("…"): der Sidebar-Wert ist der volle
      // Rohwert, Teilstring-Matching wäre hier falsch (ADR 0022-Zähler).
      modelsBox.innerHTML = m.models.length || m.unknown
        ? m.models.map((x) => chipRow(
            { kind: "field", negated: false, field: "model", op: "=",
              values: modelChipValues(x) },
            displayModelName(x.model), "#4bbf82", x.count, modelTitle(x))).join("") + unknownRow
        : `<div class="sbempty">${STRINGS.sidebarNoModels}</div>`;
    }
    if (facets.status === "fulfilled") {
      const f = facets.value;
      // Dubletten-Zeile ausblendbar (Admin → Konfiguration → Oberfläche).
      nav.querySelector('.sbrow[data-kind="dupes"]').hidden = f.show_dupes === false;
      containersBox.innerHTML = f.containers.map((c) =>
        chipRow(pred("container", c.container), c.container.toUpperCase(), "#b06fd6", c.count)).join("");
      formatsBox.innerHTML = Object.entries(STRINGS.formatLabels).map(([key, label]) =>
        chipRow(pred("format", key), label, "#5bb8c9", f.formats[key] ?? 0)).join("");
      megapixelsBox.innerHTML = Object.entries(STRINGS.megapixelLabels).map(([key, label]) =>
        chipRow(pred("mp", key), label, "#8a9bd6", f.megapixels?.[key] ?? 0)).join("");
      // Nach LoRA + Eingangsbild (Block S4): LoRA-Werte sind exakt (voller
      // normalisierter Name, ADR 0026 — Teilstring-Matching wäre falsch);
      // Eingangsbild = has:-Chip (mit) bzw. dessen Negation (ohne).
      lorasBox.innerHTML = f.loras?.length
        ? f.loras.map((x) => chipRow(
            { kind: "field", negated: false, field: "lora", op: "=",
              values: [{ value: x.lora, exact: true }] },
            x.lora, "#6fbf9a", x.count, x.lora)).join("")
        : `<div class="sbempty">${STRINGS.sidebarNoLoras}</div>`;
      inputImageBox.innerHTML = f.input_image
        ? chipRow(pred("has", "input_image"), STRINGS.inputImageWith,
                  "#c9b45b", f.input_image.mit, "has: input_image")
          + chipRow(pred("has", "input_image", { negated: true }), STRINGS.inputImageWithout,
                    "var(--faint)", f.input_image.ohne, "-has: input_image")
        : "";
      // Fundort (ADR 0041, I2): Gruppe nur bei konfigurierter Library —
      // sonst wäre alles „nur extern" und die Facette ohne Aussage.
      nav.querySelector('.sbgroup[data-group="fundort"]').hidden = !f.fundort;
      fundortBox.innerHTML = f.fundort
        ? chipRow(pred("fundort", "library"), STRINGS.fundortLibrary,
                  "#4bbf82", f.fundort.library, STRINGS.gramFundortLibrary)
          + chipRow(pred("fundort", "extern"), STRINGS.fundortExtern,
                    "var(--faint)", f.fundort.extern, STRINGS.gramFundortExtern)
        : "";
      // Nach Jahr (ADR 0021): Jahreszeile filtert, das Caret davor klappt die
      // Monate auf. Der Aufklappzustand (openMonths) übersteht die Refreshes —
      // die Gruppe wird bei jedem Engine-Idle neu gerendert und klappte sonst
      // ständig wieder zu (Feral Strawberrys Windows-Runde 4).
      yearsBox.innerHTML = f.years.map((y) => `
        <div class="sbrow sbyear${y.count === 0 ? " dim" : ""}" data-chip="${esc(JSON.stringify(pred("year", y.year)))}"
             data-akey="year::${y.year}" title="year: ${y.year}">
          <button type="button" class="sbtwist" data-year="${y.year}">${openMonths.has(y.year) ? "▾" : "▸"}</button>
          <span class="sblabel">${y.year}</span>
          <span class="sbcount">${y.count.toLocaleString(STRINGS.locale)}</span>
        </div>
        <div class="sbmonths${openMonths.has(y.year) ? " open" : ""}" data-months="${y.year}">
          ${y.months.map((m) => chipRow(pred("month", m.month),
            STRINGS.monthNames[parseInt(m.month.slice(5), 10) - 1], "#c98a5b", m.count)).join("")}
        </div>`).join("")
        + ((f.undated_total ?? f.undated)
            ? chipRow(pred("year", "unbekannt"), STRINGS.yearUnknown, "var(--faint)", f.undated)
            : "");
    }
    refreshHighlights();
    const failures = [stats, models, facets].filter((r) => r.status === "rejected");
    if (failures.length) {
      console.warn(...failures.map((r) => r.reason));
      if (failures.length === 3) {
        modelsBox.innerHTML = `<div class="sbempty">${STRINGS.serverUnreachable}</div>`;
      }
      retryTimer = setTimeout(() => {
        if (seq === countsSeq) loadCounts();
      }, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 8000);
    } else {
      retryDelay = 1000;
    }
  }

  // Aktive Werte aus dem Suchzustand (Block S3): je Prädikat-Wert ein
  // Schlüssel wie in data-akey — Zeilen mit aktivem Wert sind markiert,
  // „Alle Medien" nur bei leerem Zustand.
  let activeKeys = new Set();
  let stateEmpty = true;
  let dupesActive = false;
  function refreshHighlights() {
    for (const row of nav.querySelectorAll(".sbrow")) {
      if (row.dataset.akey !== undefined) {
        row.classList.toggle("active", activeKeys.has(row.dataset.akey));
      } else if (row.dataset.kind === "all") {
        row.classList.toggle("active", stateEmpty && !dupesActive);
      } else if (row.dataset.kind === "dupes") {
        row.classList.toggle("active", dupesActive);
      } else {
        row.classList.remove("active");   // gespeicherte Suchen: kein Dauer-Aktiv
      }
    }
  }

  nav.addEventListener("click", async (e) => {
    // Monats-Aufklapper an der Jahreszeile (filtert NICHT).
    const twist = e.target.closest(".sbtwist");
    if (twist) {
      const months = nav.querySelector(`.sbmonths[data-months="${twist.dataset.year}"]`);
      const open = months.classList.toggle("open");
      twist.textContent = open ? "▾" : "▸";
      open ? openMonths.add(twist.dataset.year) : openMonths.delete(twist.dataset.year);
      return;
    }
    const del = e.target.closest(".sbdel");
    if (del) {
      // Zweistufig statt confirm() (Feral Strawberry, 2026-07-09 — keine System-
      // dialoge): erster Klick armiert, zweiter löscht; nach kurzer Zeit
      // fällt der Knopf von selbst zurück.
      const row = del.closest(".sbrow");
      if (del.dataset.armed) {
        try { await deleteFolder(row.dataset.id); } catch (err) { console.warn(err); }
        loadFolders();
      } else {
        del.dataset.armed = "1";
        del.textContent = STRINGS.folderDeleteArm;
        setTimeout(() => {
          if (del.isConnected) { delete del.dataset.armed; del.textContent = "✕"; }
        }, 2500);
      }
      return;
    }
    const row = e.target.closest(".sbrow");
    if (!row) return;
    if (row.dataset.chip) {
      // Facetten-Wert togglen — search.js legt den Chip an/erweitert/entfernt.
      emit("chip-toggle", { pred: JSON.parse(row.dataset.chip) });
    } else if (row.dataset.kind === "folder") {
      // Gespeicherte Suche: Ausdruck als Chips laden (bearbeitbar, ADR 0035).
      // `folder` merkt sich der Speicherdialog (Block S7): Überschreiben/
      // Umbenennen/Löschen beziehen sich dann auf DIESE Suche.
      emit("state-load", {
        expression: row.dataset.value,
        label: row.querySelector(".sblabel").textContent,
        folder: {
          id: parseInt(row.dataset.id, 10),
          name: row.querySelector(".sblabel").textContent,
        },
      });
    } else if (row.dataset.kind === "arena") {
      // Arena öffnen (Ranking-Modul): rankings.js zeigt Duell + Bestenliste.
      emit("arena-open", {
        id: parseInt(row.dataset.id, 10),
        name: row.dataset.name,
        expression: row.dataset.expr,
      });
    } else if (row.dataset.kind === "arena-new") {
      emit("arena-create", {});
    } else if (row.dataset.kind === "all") {
      emit("state-clear", {});
    } else if (row.dataset.kind === "dupes") {
      emit("source-changed", { kind: "dupes" });
    }
  });

  // Suchzustand nachziehen: aktive Werte markieren (auch von Chips, die
  // nicht aus der Sidebar kamen — getippt und geklickt ist dasselbe) und
  // die Zähler im neuen Kontext rechnen (Block S4). Entprellt: die
  // Live-Suche feuert je Tipp-Pause, der Facetten-Lauf ist der teurere Teil;
  // veraltete Antworten verwirft loadCounts über die Sequenznummer.
  let filterTimer = null;
  function applyFilter(filter) {
    if (filter === currentFilter) return;
    currentFilter = filter;
    clearTimeout(filterTimer);
    filterTimer = setTimeout(loadCounts, 250);
  }
  on("search-state-changed", (d) => {
    activeKeys = new Set();
    for (const p of d.predicates || []) {
      if (p.kind === "sort") continue;
      for (const v of p.values || []) {
        activeKeys.add(`${p.negated ? "-" : ""}${p.kind}:${p.field || ""}:${v.value}`);
      }
    }
    stateEmpty = !d.expression;
    dupesActive = false;
    refreshHighlights();
    applyFilter(d.expression || "");
  });
  on("source-changed", (d) => {
    if (d?.kind !== "dupes") return;
    activeKeys = new Set();
    stateEmpty = true;
    dupesActive = true;
    refreshHighlights();
    applyFilter("");   // Spezialansicht: Zähler wieder global
  });

  // Nach abgeschlossenen Engine-Aufgaben (Scan/Wartung) alles auffrischen.
  // Nach einem Rating-Klick NUR Bewertungs-Gruppe + Smart Folders — die
  // vollen Statistiken je Klick waren bei 1,4-GB-DBs der Frost-Auslöser.
  on("engine-idle", () => { loadCounts(); loadFolders(); loadArenas(); });
  // Nach Arena-Änderungen/Duellen (rankings.js) die Gruppe nachziehen.
  on("rankings-changed", loadArenas);
  on("annotation-changed", () => { loadRatings(); loadFolders(); });
  on("model-changed", () => { loadCounts(); loadFolders(); });  // ADR 0022
  on("items-rejected", () => { loadCounts(); loadFolders(); }); // ADR 0041
  on("folders-changed", loadFolders);
  // Sammel-Aktion (ADR 0040): kann Tags/Modelle/Bewertungen in Masse ändern.
  on("bulk-applied", () => { loadCounts(); loadRatings(); loadFolders(); });

  // Tab kommt zurück in den Vordergrund (z. B. nach einem Server-Neustart bei
  // offenem Browser): Zähler auffrischen — heilt veraltete Gruppen von selbst.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { loadCounts(); loadFolders(); }
  });

  loadCounts();
  loadFolders();
}
