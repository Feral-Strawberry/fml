// sidebar.js — linke Quellen-Spalte: Gruppe „Bibliothek" (Alle Medien) und
// Facetten-Gruppen. Seit ADR 0084: häufig Genutztes oben (Bewertung/
// Medienart/Generator/Modell/LoRA/Jahr), Seltenes im Sammelblock „Weitere
// Kriterien" (Dateityp/Format/Auflösung/Eingangsbild/Fundort, ab Werk zu).
//
// Kommuniziert nur über den Bus. Seit Block S3 (ADR 0035) füttern die
// Facetten-Zeilen den EINEN Suchzustand: Klick = 'chip-toggle' (Lightroom-
// Regel seit 2026-09-08: Klick ersetzt die Auswahl der Gruppe, Cmd/Strg-Klick
// erweitert zum ODER, Klick auf den aktiven Wert nimmt ihn heraus); aktive
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
import { getStats, getSidebar, getFolders, deleteFolder, getRankings } from "./api.js";
import { emit, on } from "./main.js";
import { serverMsg } from "./servermsg.js";
import { viewKinds } from "./libview.js";

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

// Punktfarben der Medienart-Zeilen (ADR 0084).
const MEDIA_KIND_DOTS = { bild: "#8a9bd6", video: "#e0915b", audio: "#b06fd6" };

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Zusatztaste für „hinzufügen (ODER)" je Plattform — Feral Strawberry (2026-09-08):
// Menschen lesen keine Doku, der Hinweis muss am Klickort stehen und die
// RICHTIGE Taste nennen. navigator.platform ist veraltet, aber überall
// gesetzt; userAgentData.platform als moderner Erstkandidat.
export function modKey(platform = detectPlatform()) {
  return /mac|iphone|ipad/i.test(platform) ? STRINGS.modKeyMac : STRINGS.modKeyOther;
}
function detectPlatform() {
  const nav = typeof navigator !== "undefined" ? navigator : null;
  return nav?.userAgentData?.platform || nav?.platform || "";
}
const clickHint = () => STRINGS.sidebarClickHint.replace("{mod}", modKey());
const rowHint = () => STRINGS.sidebarRowHint.replace("{mod}", modKey());

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
      <div class="sbgroup" data-group="rankings" data-scope="bild video" hidden>
        <div class="mlabel">${STRINGS.groupRankings}</div>
        <div id="sbRankings"></div>
      </div>
      <div class="sbgroup" data-group="rating">
        <div class="mlabel" title="${clickHint()}">${STRINGS.groupByRating}<span class="sbactive"></span></div>
        <div id="sbRatings"></div>
      </div>
      <div class="sbgroup" data-group="mediakind" data-scope="bild video" hidden>
        <div class="mlabel" title="${clickHint()}">${STRINGS.groupByMediaKind}<span class="sbactive"></span></div>
        <div id="sbMediaKinds"></div>
      </div>
      <div class="sbgroup" data-group="lyrics" data-scope="audio">
        <div class="mlabel">${STRINGS.groupByLyrics}<span class="sbactive"></span></div>
        <div id="sbLyrics"></div>
      </div>
      <div class="sbgroup" data-group="generator">
        <div class="mlabel" title="${clickHint()}">${STRINGS.groupByGenerator}<span class="sbactive"></span></div>
        <div id="sbTools"></div>
      </div>
      <div class="sbgroup" data-group="model">
        <div class="mlabel" title="${clickHint()}">${STRINGS.groupByModel}<span class="sbactive"></span></div>
        <div id="sbModels"></div>
      </div>
      <div class="sbgroup" data-group="lora" data-scope="bild video">
        <div class="mlabel" title="${clickHint()}">${STRINGS.groupByLora}<span class="sbactive"></span></div>
        <div id="sbLoras"></div>
      </div>
      <div class="sbgroup" data-group="year">
        <div class="mlabel" title="${clickHint()}">${STRINGS.groupByYear}<span class="sbactive"></span></div>
        <div id="sbYears"></div>
      </div>
      <div class="sbgroup sbmore" data-group="more">
        <div class="mlabel">${STRINGS.groupMore}<span class="sbactive"></span></div>
        <div class="sbmorebody">
          <div class="sbgroup" data-group="container">
            <div class="mlabel" title="${clickHint()}">${STRINGS.groupByContainer}<span class="sbactive"></span></div>
            <div id="sbContainers"></div>
          </div>
          <div class="sbgroup" data-group="format" data-scope="bild video">
            <div class="mlabel" title="${clickHint()}">${STRINGS.groupByFormat}<span class="sbactive"></span></div>
            <div id="sbFormats"></div>
          </div>
          <div class="sbgroup" data-group="megapixels" data-scope="bild video">
            <div class="mlabel" title="${clickHint()}">${STRINGS.groupByMegapixels}<span class="sbactive"></span></div>
            <div id="sbMegapixels"></div>
          </div>
          <div class="sbgroup" data-group="inputimage" data-scope="bild video">
            <div class="mlabel">${STRINGS.groupByInputImage}<span class="sbactive"></span></div>
            <div id="sbInputImage"></div>
          </div>
          <div class="sbgroup" data-group="fundort" hidden>
            <div class="mlabel">${STRINGS.groupByFundort}<span class="sbactive"></span></div>
            <div id="sbFundort"></div>
          </div>
        </div>
      </div>
    </div>
    <div class="sbfooter">
      <div class="mlabel">${STRINGS.sidebarFooter}</div>
      <div id="sbTotals" class="sbtotals"></div>
    </div>`;

  const modelsBox = nav.querySelector("#sbModels");
  const lorasBox = nav.querySelector("#sbLoras");
  const toolsBox = nav.querySelector("#sbTools");
  const ratingsBox = nav.querySelector("#sbRatings");
  const foldersBox = nav.querySelector("#sbFolders");
  const containersBox = nav.querySelector("#sbContainers");
  const formatsBox = nav.querySelector("#sbFormats");
  const megapixelsBox = nav.querySelector("#sbMegapixels");
  const inputImageBox = nav.querySelector("#sbInputImage");
  const fundortBox = nav.querySelector("#sbFundort");
  const yearsBox = nav.querySelector("#sbYears");
  const mediaKindsBox = nav.querySelector("#sbMediaKinds");
  const lyricsBox = nav.querySelector("#sbLyrics");

  // Geltungsbereich je Gruppe (ADR 0084 Punkt 5): data-scope nennt die
  // Medienarten, für die eine Gruppe Sinn ergibt; sichtbar ist sie, wenn
  // sich das mit dem Grundbereich der Ansicht schneidet (LoRA, Format …
  // nur Bild/Video, Songtext nur Audio). Eigene Klasse statt hidden — das
  // Attribut gehört den datengetriebenen Schaltern (Modul, Library-Root).
  function applyScope() {
    const kinds = viewKinds();
    for (const g of nav.querySelectorAll(".sbgroup[data-scope]")) {
      g.classList.toggle("offview", !g.dataset.scope.split(" ").some((k) => kinds.includes(k)));
    }
  }
  applyScope();

  // Gruppen ein-/ausklappbar (Feral Strawberry, 2026-07-07: „wird langsam voll"), Klick
  // auf die Überschrift; Zustand überlebt in localStorage. Der Sammelblock
  // „Weitere Kriterien" (ADR 0084) ist ab Werk zugeklappt — sein Zustand
  // steht deshalb unter eigenem Schlüssel als „aufgeklappt".
  const COLLAPSED_KEY = "feral-sb-collapsed";
  const MORE_OPEN_KEY = "feral-sb-more-open";
  const collapsed = new Set(JSON.parse(localStorage.getItem(COLLAPSED_KEY) || "[]"));
  if (localStorage.getItem(MORE_OPEN_KEY) !== "1") collapsed.add("more");
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
    if (key === "more") localStorage.setItem(MORE_OPEN_KEY, collapsed.has(key) ? "0" : "1");
    else localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...collapsed].filter((k) => k !== "more")));
    refreshActiveMarks();
  });

  // Aktiv-Marker (ADR 0084): eine zugeklappte Gruppe (oder der zugeklappte
  // Sammelblock) mit aktivem Wert zeigt „· N aktiv" im Kopf — kein Filter
  // ist unsichtbar aktiv. Gezählt wird aus dem Suchzustand, nicht aus den
  // Zeilen: auch ein Wert ohne eigene Zeile (negiert, getippt) zählt.
  let activePreds = [];
  const isField = (f) => (p) => (p.kind === "field" && p.field === f)
    || (p.kind === "has" && (p.values || []).every((v) => v.value === f));
  const GROUP_PREDS = {
    rating: (p) => p.kind === "rating",
    mediakind: (p) => p.kind === "typ",
    generator: isField("tool"),
    model: isField("model"),
    lora: isField("lora"),
    year: (p) => p.kind === "year" || p.kind === "month",
    container: (p) => p.kind === "container",
    format: (p) => p.kind === "format",
    megapixels: (p) => p.kind === "mp",
    inputimage: isField("input_image"),
    lyrics: isField("lyrics"),
    fundort: (p) => p.kind === "fundort",
  };
  const activeIn = (key) => {
    if (key === "more") {
      return [...nav.querySelectorAll(".sbmorebody .sbgroup[data-group]")]
        .reduce((n, g) => n + activeIn(g.dataset.group), 0);
    }
    const match = GROUP_PREDS[key];
    return match ? activePreds.filter(match).reduce((n, p) => n + (p.values?.length || 1), 0) : 0;
  };
  function refreshActiveMarks() {
    for (const group of nav.querySelectorAll(".sbgroup[data-group]")) {
      const head = [...group.children].find((c) => c.classList.contains("mlabel"));
      const mark = head?.querySelector(".sbactive");
      if (!mark) continue;
      const n = group.classList.contains("collapsed") ? activeIn(group.dataset.group) : 0;
      mark.textContent = n ? " " + STRINGS.sidebarActiveMark.replace("{n}", n) : "";
    }
  }

  // Facetten-Zeile (Block S3): trägt ihr Ein-Wert-Prädikat als JSON
  // (data-chip) — Klick togglet den Wert im Suchzustand (chip-toggle) —
  // und einen Aktiv-Schlüssel (data-akey) fürs Markieren aktiver Werte.
  const akeyOf = (chip) =>
    `${chip.negated ? "-" : ""}${chip.kind}:${chip.field || ""}:${chip.values[0].value}`;
  // count 0 = im aktuellen Kontext leer → gedimmt, aber klickbar (Block S4).
  // Tooltip = Grammatik des Chips + Tastenhinweis fürs ODER (nur bei Werte-
  // Facetten; Bewertung ersetzt ohnehin, has:-Paare schließen sich aus).
  const canOr = (chip) => chip.kind !== "rating" && chip.kind !== "has";
  const chipRow = (chip, label, dot, count, title) => `
    <div class="sbrow${count === 0 ? " dim" : ""}" data-chip="${esc(JSON.stringify(chip))}"
         data-akey="${esc(akeyOf(chip))}" title="${esc(title ?? label)}${canOr(chip) ? " · " + esc(rowHint()) : ""}">
      <span class="sbdot" style="background:${dot}"></span>
      <span class="sblabel">${esc(label)}</span>
      <span class="sbcount">${count.toLocaleString(STRINGS.locale)}</span>
    </div>`;
  // Lange Listen im Chip-Kontext (Konzeptrunde 2026-09-08): Zeilen mit Treffern
  // zuerst, im Kontext leere Zeilen (gedimmt, ADR 0037) gesammelt darunter —
  // getrennt durch die Zeile „keine Treffer mit diesem Filter" (erscheint
  // nur bei aktivem Chip — ohne Filter gibt es keine leeren Zeilen). Reihenfolge innerhalb der
  // Hälften bleibt (zuletzt/häufigste zuerst). Ohne leere Zeilen: unverändert.
  const byContext = (entries, render, noun) => {
    const live = entries.filter((x) => x.count !== 0);
    const empty = entries.filter((x) => x.count === 0);
    if (!live.length || !empty.length) return entries.map(render).join("");
    return live.map(render).join("")
      + `<div class="sbctx">${STRINGS.sidebarContextEmpty} · ${empty.length} ${noun}</div>`
      + empty.map(render).join("");
  };
  // Kurzform für Werte-Prädikate ohne Feld (container/format/mp/year/month).
  const pred = (kind, value, extra = {}) =>
    ({ kind, negated: false, field: "", op: "=", values: [{ value: String(value), exact: false }], ...extra });

  // Zähler-Text: fehlt (Liste vor Zahlen, noch nicht gerechnet) → „…",
  // null (Ausdruck ungültig geworden) → ⚠, sonst die Zahl.
  const countText = (n) =>
    n === undefined ? "…" : n === null ? "⚠" : n.toLocaleString(STRINGS.locale);

  // Liste vor Zahlen (Issue #69): erst die Liste ohne Zähler (Millisekunden),
  // dann die Zähler aus dem Epochen-Cache nachziehen. Nach einem Import ist
  // die Erstberechnung echte DB-Arbeit — die Ordner sind trotzdem sofort
  // klickbar. Ein Laufnummern-Wächter lässt bei überlappenden Aufrufen nur
  // den jüngsten zeichnen (sonst könnte eine ältere „…"-Liste die fertigen
  // Zahlen wieder überschreiben).
  let foldersSeq = 0;
  const renderFolders = (folders) => {
    foldersBox.innerHTML = folders.length
      ? folders.map((f) => `
          <div class="sbrow" data-kind="folder" data-value="${esc(f.expression)}"
               data-id="${f.id}" title="${esc(f.expression)}${f.error ? " — " + esc(serverMsg(f.error)) : ""}">
            <span class="sbdot" style="background:#d9a441"></span>
            <span class="sblabel">${esc(f.name)}</span>
            <button type="button" class="sbdel" title="${STRINGS.folderDelete}">✕</button>
            <span class="sbcount">${countText(f.count)}</span>
          </div>`).join("")
      : `<div class="sbempty">${STRINGS.foldersEmpty}</div>`;
    refreshHighlights();   // geladene Suche bleibt markiert (#133)
  };
  async function loadFolders() {
    const seq = ++foldersSeq;
    try {
      const list = await getFolders({ counts: false });
      if (seq !== foldersSeq) return;
      renderFolders(list.folders);
      const d = await getFolders();
      if (seq !== foldersSeq) return;
      renderFolders(d.folders);
    } catch (err) { console.warn(err); }
  }

  // Ranking-Modul (ADR 0045): Gruppe NUR bei aktivem Modul-Schalter —
  // inaktiv stellt die Sidebar keine Ranking-Queries. Der Zähler ist die
  // Live-Population der Arena (Ausdruck kaputt geworden → ⚠ wie bei
  // gespeicherten Suchen); Duelle stehen im Tooltip.
  let rankingsEnabled = false;
  // Audio-Modul (ADR 0083/0084): die Zeile „Audio" der Medienart gibt es nur
  // mit Modul; Popover/Tipphilfe (advanced.js) hören auf 'audio-enabled'.
  let audioEnabled = null;
  const rankingsBox = nav.querySelector("#sbRankings");
  let arenasSeq = 0;
  const renderArenas = (rankings) => {
    rankingsBox.innerHTML = rankings.map((r) => `
        <div class="sbrow" data-kind="arena" data-id="${r.id}"
             data-name="${esc(r.name)}" data-expr="${esc(r.expression)}"
             title="${esc(r.expression || STRINGS.allMedia)} · ${r.duels} ${STRINGS.rankingDuels}${r.error ? " — " + esc(serverMsg(r.error)) : ""}">
          <span class="sbdot" style="background:#e05b8f"></span>
          <span class="sblabel">${esc(r.name)}</span>
          <span class="sbcount">${countText(r.population)}</span>
        </div>`).join("")
      || `<div class="sbempty">${STRINGS.rankingsEmpty}</div>`;
    refreshHighlights();   // geladenes Ranking bleibt markiert (#133)
  };
  async function loadArenas() {
    if (!rankingsEnabled) return;
    const seq = ++arenasSeq;   // Liste vor Zahlen, wie loadFolders (#69)
    try {
      const list = await getRankings({ counts: false });
      if (seq !== arenasSeq) return;
      renderArenas(list.rankings);
      const d = await getRankings();
      if (seq !== arenasSeq) return;
      renderArenas(d.rankings);
    } catch (err) { console.warn(err); }
  }

  function renderRatings(ratings) {
    // Exakte Verteilung (= n Sterne): auch gezielt schlecht Bewertetes
    // filtern können (Feral Strawberry, 2026-07-08), beste zuerst. rating ist ein
    // Vergleich (kein ODER) — Klick ersetzt/entfernt den Wert (search.js).
    ratingsBox.innerHTML = ratings.length === 0
      ? `<div class="sbempty">${STRINGS.sidebarNoRatings}</div>`
      : ratings.map((r) =>
          chipRow(pred("rating", r.rating), "★".repeat(r.rating), "#d9a441", r.count)).join("");
  }

  // Zähler-Refresh, robust (Feral Strawberrys 100-GB-Runde, 2026-07-08 — „Nach Jahr"
  // blieb nach Neustarts leer/alt): (1) Kennzahlen und Zähler unabhängig
  // verarbeiten statt Alles-oder-nichts; (2) veraltete Antworten
  // verwerfen (Sequenznummer — parallele Refreshes konnten sich sonst in
  // falscher Reihenfolge überschreiben); (3) wenn gar nichts ankam (Seite
  // öffnet, bevor der Server fertig gebootet hat — start.bat!), automatisch
  // mit Backoff nachfassen statt auf das nächste Zufalls-Event zu warten.
  // Die Zähler (Modelle, Facetten, Bewertungen) kommen seit #99 aus EINEM
  // Request (/api/sidebar): ein Filterlauf statt drei, und der Server
  // merkt sich das Ergebnis je Suchzustand bis zum nächsten Schreibvorgang.
  let countsSeq = 0;
  let retryTimer = null;
  let retryDelay = 1000;
  // Aktiver Suchzustand (Block S4): geht als ?filter= an den Zähler-Endpunkt.
  let currentFilter = "";
  async function loadCounts() {
    const seq = ++countsSeq;
    clearTimeout(retryTimer);
    const filter = currentFilter || undefined;
    const [stats, side] = await Promise.allSettled([getStats(), getSidebar(filter)]);
    if (seq !== countsSeq) return;   // eine jüngere Anfrage läuft schon
    const models = side.status === "fulfilled" ? { status: "fulfilled", value: side.value.models } : side;
    // „Alle Medien" zählt den Grundbereich der Ansicht (ADR 0085); ohne
    // Grundbereich (kein Audio im Bestand) den ganzen Bestand.
    const viewTotal = side.status === "fulfilled" ? side.value.total ?? null : null;
    const facets = side.status === "fulfilled" ? { status: "fulfilled", value: side.value.facets } : side;
    if (side.status === "fulfilled") renderRatings(side.value.ratings.ratings);
    if (stats.status === "fulfilled") {
      const s = stats.value;
      nav.querySelector("#sbAllCount").textContent =
        (viewTotal ?? s.total_items).toLocaleString(STRINGS.locale);
      nav.querySelector("#sbDupesCount").textContent =
        s.items_multi_location.toLocaleString(STRINGS.locale);
      const size = (b) => b >= 1e9
        ? `${(b / 1e9).toLocaleString(STRINGS.locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} GB`
        : `${Math.round(b / 1e6).toLocaleString(STRINGS.locale)} MB`;
      // Library vs. katalogisiert gesamt getrennt (ADR 0041, I2) — ohne
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
        emit("rankings-enabled", { enabled: rankingsEnabled });   // 🏆 in der Chip-Leiste
        loadArenas();
      }
      if (audioEnabled !== !!s.audio) {
        audioEnabled = !!s.audio;
        emit("audio-enabled", { enabled: audioEnabled });
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
        ? byContext(m.models, (x) => chipRow(
            { kind: "field", negated: false, field: "model", op: "=",
              values: modelChipValues(x) },
            displayModelName(x.model), "#4bbf82", x.count, modelTitle(x)), STRINGS.nounModels) + unknownRow
        : `<div class="sbempty">${STRINGS.sidebarNoModels}</div>`;
    }
    if (facets.status === "fulfilled") {
      const f = facets.value;
      // Dubletten-Zeile ausblendbar (Admin → Konfiguration → Oberfläche).
      nav.querySelector('.sbrow[data-kind="dupes"]').hidden = f.show_dupes === false;
      // Medienart (ADR 0084): nur Arten, die es gibt (Server), Audio nur mit
      // Modul — keine dauerhaft toten Zeilen; Zähler mitfilternd.
      const kinds = (f.media_kinds || []).filter((m) => m.typ !== "audio" || audioEnabled);
      nav.querySelector('.sbgroup[data-group="mediakind"]').hidden = !kinds.length;
      mediaKindsBox.innerHTML = kinds.map((m) =>
        chipRow(pred("typ", m.typ), STRINGS.mediaKindLabels[m.typ] ?? m.typ,
                MEDIA_KIND_DOTS[m.typ] ?? "var(--faint)", m.count, `typ: ${m.typ}`)).join("");
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
        ? byContext(f.loras, (x) => chipRow(
            { kind: "field", negated: false, field: "lora", op: "=",
              values: [{ value: x.lora, exact: true }] },
            x.lora, "#6fbf9a", x.count, x.lora), STRINGS.nounLoras)
        : `<div class="sbempty">${STRINGS.sidebarNoLoras}</div>`;
      // Generator (ADR 0066 + Nachtrag 2026-09-08): Plattform-Zeilen aus dem
      // tool-Feld — ComfyUI, A1111, Midjourney, Google, OpenAI, Adobe, Topaz …
      // Grob vor fein: die Gruppe steht ÜBER „Nach Modell", ein Klick lässt
      // die Modell-Liste im Kontext zählen (Treffer oben). Chip = exakter
      // Rohwert; Anzeigename aus den Strings, unbekannte Werte roh.
      toolsBox.innerHTML = f.tools?.length
        ? byContext(f.tools, (x) => chipRow(
            { kind: "field", negated: false, field: "tool", op: "=",
              values: [{ value: x.tool, exact: true }] },
            (Object.hasOwn(STRINGS.generatorLabels, x.tool) ? STRINGS.generatorLabels[x.tool] : x.tool),
            "#e0915b", x.count,
            `tool: ${x.tool}`), STRINGS.nounGenerators)
        : `<div class="sbempty">${STRINGS.sidebarNoGenerators}</div>`;
      inputImageBox.innerHTML = f.input_image
        ? chipRow(pred("has", "input_image"), STRINGS.inputImageWith,
                  "#c9b45b", f.input_image.mit, "has: input_image")
          + chipRow(pred("has", "input_image", { negated: true }), STRINGS.inputImageWithout,
                    "var(--faint)", f.input_image.ohne, "-has: input_image")
        : "";
      // Songtext (ADR 0084): has: lyrics = Gesang, ohne = instrumental —
      // Bauform wie Eingangsbild, nur in der Audioansicht (data-scope).
      lyricsBox.innerHTML = f.lyrics
        ? chipRow(pred("has", "lyrics"), STRINGS.lyricsWith,
                  "#b06fd6", f.lyrics.mit, "has: lyrics")
          + chipRow(pred("has", "lyrics", { negated: true }), STRINGS.lyricsWithout,
                    "var(--faint)", f.lyrics.ohne, "-has: lyrics")
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
             data-akey="year::${y.year}" title="year: ${y.year} · ${esc(rowHint())}">
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
    const failures = [stats, side].filter((r) => r.status === "rejected");
    if (failures.length) {
      console.warn(...failures.map((r) => r.reason));
      if (failures.length === 2) {
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
  // Geladene Suche/Ranking (#133): ein Ranking leuchtet, solange sein
  // Bearbeiten-Modus läuft (context-changed); eine gespeicherte Suche
  // leuchtet, solange die Chips ihr entsprechen (Vergleich des kanonischen
  // Ausdrucks — saved wird mit dem ersten Zustand nach dem Laden gefüllt,
  // der gespeicherte Text kann aus alten Fassungen stammen). {kind, id,
  // saved?, match} oder null.
  let loaded = null;
  const loadedActive = () =>
    !!loaded && (loaded.kind === "arena" || loaded.match === true);
  // Ersthinweis zur Klick-Regel (Feral Strawberry, 2026-09-08: „Menschen lesen keine
  // Doku, Tooltips sieht man nur durch Zufall"): genau in dem Moment, in dem
  // ein einfacher Klick eine ANDERE aktive Auswahl derselben Gruppe ersetzt,
  // erscheint unter der Gruppe eine Zeile „Auswahl ersetzt · ⌘-Klick fügt
  // hinzu". Sie verschwindet nach ein paar Sekunden und kommt höchstens
  // dreimal je Browser (localStorage) — danach ist die Regel gelernt.
  const OR_HINT_KEY = "feral-or-hint-shown";
  const OR_HINT_MAX = 3;
  // Jeder weitere Facetten-Klick, der NICHT lehrt, räumt einen noch stehenden
  // Hinweis weg — der Nutzer hat weitergemacht.
  function dismissOrHint() { orHint = null; placeOrHint(); }
  function teachOr(row, pred) {
    if (pred.kind === "rating" || pred.kind === "has") return dismissOrHint();   // dort gibt es kein ODER
    if (row.classList.contains("active")) return dismissOrHint();               // Klick auf Aktives = entfernen
    const group = row.closest(".sbgroup");
    if (!group) return dismissOrHint();
    const groupOf = (akey) => akey.split(":").slice(0, 2).join(":");
    const other = [...group.querySelectorAll(".sbrow.active")]
      .some((r) => r !== row && r.dataset.akey && groupOf(r.dataset.akey) === groupOf(row.dataset.akey));
    if (!other) return dismissOrHint();                                          // nichts ersetzt
    let shown = 0;
    try { shown = parseInt(localStorage.getItem(OR_HINT_KEY) || "0", 10) || 0; } catch { /* privat */ }
    if (shown >= OR_HINT_MAX) return dismissOrHint();
    try { localStorage.setItem(OR_HINT_KEY, String(shown + 1)); } catch { /* privat */ }
    // Direkt UNTER der geklickten Zeile (Feral Strawberry, 2026-09-08: am Gruppenende
    // sieht ihn bei 60 Modellen niemand). Die Liste wird nach dem Klick neu
    // gezeichnet — placeOrHint() setzt ihn in refreshHighlights() wieder
    // unter dieselbe Zeile (über ihren Aktiv-Schlüssel), bis die Zeit um ist.
    orHint = { akey: row.dataset.akey, text: STRINGS.sidebarOrHint.replace("{mod}", modKey()),
               until: Date.now() + OR_HINT_MS };
    placeOrHint();
    setTimeout(() => { orHint = null; placeOrHint(); }, OR_HINT_MS);
  }
  const OR_HINT_MS = 6000;
  let orHint = null;
  function placeOrHint() {
    nav.querySelector(".sbhint")?.remove();
    if (!orHint || Date.now() >= orHint.until) return;
    const row = [...nav.querySelectorAll(".sbrow")].find((r) => r.dataset.akey === orHint.akey);
    if (!row) return;
    const hint = document.createElement("div");
    hint.className = "sbhint";
    hint.textContent = orHint.text;
    row.parentNode.insertBefore(hint, row.nextSibling);
  }

  function refreshHighlights() {
    placeOrHint();   // Ersthinweis überlebt die Neuzeichnung der Listen
    refreshActiveMarks();
    for (const row of nav.querySelectorAll(".sbrow")) {
      if (row.dataset.akey !== undefined) {
        row.classList.toggle("active", activeKeys.has(row.dataset.akey));
      } else if (row.dataset.kind === "all") {
        row.classList.toggle("active", stateEmpty && !dupesActive);
      } else if (row.dataset.kind === "dupes") {
        row.classList.toggle("active", dupesActive);
      } else {
        // Gespeicherte Suchen/Rankings: aktiv NUR im Bearbeiten-Modus (#133).
        row.classList.toggle("active",
          loadedActive() && row.dataset.kind === loaded.kind && Number(row.dataset.id) === loaded.id);
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
      // Lightroom-Regel (2026-09-08): Klick ersetzt, Cmd/Strg-Klick fügt hinzu.
      const pred = JSON.parse(row.dataset.chip);
      const additive = !!(e.metaKey || e.ctrlKey);
      if (additive) dismissOrHint(); else teachOr(row, pred);
      emit("chip-toggle", { pred, additive });
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
    activePreds = (d.predicates || []).filter((p) => p.kind !== "sort");
    for (const p of d.predicates || []) {
      if (p.kind === "sort") continue;
      for (const v of p.values || []) {
        activeKeys.add(`${p.negated ? "-" : ""}${p.kind}:${p.field || ""}:${v.value}`);
      }
    }
    stateEmpty = !d.expression;
    dupesActive = false;
    if (loaded?.kind === "folder") {
      if (!d.canonical) loaded = null;
      else {
        if (loaded.saved === null) loaded.saved = d.canonical;
        loaded.match = d.canonical === loaded.saved;
      }
    }
    refreshHighlights();
    if (d.viewChanged) {
      // Neuer Grundbereich: sofort zählen, auch bei gleichem Ausdruck.
      currentFilter = d.expression || "";
      clearTimeout(filterTimer);
      loadCounts();
    } else {
      applyFilter(d.expression || "");
    }
  });
  // Gespeicherte Suche geladen (Sidebar-Klick) bzw. gerade gespeichert
  // (Speicherdialog): ab jetzt ist sie die Quelle der Chips.
  on("state-load", (d) => {
    if (d.folder) { loaded = { kind: "folder", id: d.folder.id, saved: null, match: false }; refreshHighlights(); }
    else if (!d.arena) { loaded = null; refreshHighlights(); }
  });
  on("folder-origin", (d) => { loaded = { kind: "folder", id: d.id, saved: d.expression, match: true }; refreshHighlights(); });
  on("state-clear", () => { loaded = null; refreshHighlights(); });
  on("context-changed", (d) => {
    if (d) loaded = { kind: d.kind, id: d.id };
    else if (loaded?.kind === "arena") loaded = null;
    refreshHighlights();
  });
  on("source-changed", (d) => {
    if (d?.kind !== "dupes") return;
    activeKeys = new Set();
    activePreds = [];
    stateEmpty = true;
    dupesActive = true;
    refreshHighlights();
    applyFilter("");   // Spezialansicht: Zähler wieder global
  });

  // Ansichtswechsel (ADR 0085): andere Gruppen, andere Zähl-Basis — die
  // Chips (und damit currentFilter) bleiben.
  // Die Zähler lädt der Suchzustand nach (viewChanged, s. unten) — search.js
  // verkündet ihn nach dem Ausdünnen der Medienart-Chips neu.
  on("library-view-changed", () => { applyScope(); refreshActiveMarks(); loadFolders(); });

  // Nach abgeschlossenen Engine-Aufgaben (Scan/Wartung) alles auffrischen.
  // Nach einem Rating-Klick NUR Bewertungs-Gruppe + Smart Folders — die
  // vollen Statistiken je Klick waren bei 1,4-GB-DBs der Frost-Auslöser.
  on("engine-idle", () => { loadCounts(); loadFolders(); loadArenas(); });
  // Nach Arena-Änderungen/Duellen (rankings.js) die Gruppe nachziehen.
  on("rankings-changed", loadArenas);
  on("annotation-changed", () => { loadCounts(); loadFolders(); });
  on("model-changed", () => { loadCounts(); loadFolders(); });  // ADR 0022
  on("items-rejected", () => { loadCounts(); loadFolders(); }); // ADR 0041
  on("cover-changed", () => { loadCounts(); loadFolders(); });  // Song kommt/geht (#165)
  on("folders-changed", loadFolders);
  // Sammel-Aktion (ADR 0040): kann Tags/Modelle/Bewertungen in Masse ändern.
  on("bulk-applied", () => { loadCounts(); loadFolders(); });

  // Tab kommt zurück in den Vordergrund (z. B. nach einem Server-Neustart bei
  // offenem Browser): Zähler auffrischen — heilt veraltete Gruppen von selbst.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { loadCounts(); loadFolders(); }
  });

  loadCounts();
  loadFolders();
}
