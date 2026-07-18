// main.js — Einstiegspunkt der neuen Shell (Block 3.0).
//
// Hier leben nur: der Mini-Event-Bus (Module reden über Events, nicht
// direkt miteinander — Begründung: ADR 0015) und der Boot-Ablauf
// (Theme, Kopfzeile, Einhängen der Funktionsmodule).

import { STRINGS, LANG, LANGUAGES, setLang } from "./strings.js";
import { getStats } from "./api.js";
import { initGallery } from "./gallery.js";
import { initSidebar } from "./sidebar.js";
import { initSearch } from "./search.js";
import { initAdvanced } from "./advanced.js";
import { initSaveDialog } from "./savedialog.js";
import { initBulkDialog } from "./bulkdialog.js";
import { initDetail } from "./detail.js";
import { initLoupe } from "./loupe.js";
import { initSingleView } from "./singleview.js";
import { initAdmin } from "./admin.js";
import { initCurate } from "./curate.js";
import { initQuickmenu } from "./quickmenu.js";
import { initRankings } from "./rankings.js";

// -- Event-Bus -----------------------------------------------------------------
//
// Vereinbarte Events (Payload = event.detail):
//   'search-state-changed' {expression, predicates, sort}
//                       — der EINE Suchzustand (Chips, ADR 0035) hat sich
//                         geändert: Grid filtert, Sidebar markiert
//   'chip-toggle'       {pred}   — Facetten-Wert togglen (Sidebar → search.js)
//   'sort-changed'      {sort}   — Galerie-Dropdown setzt die Sortierung
//                         (search.js ersetzt den sort:-Chip; Block S6)
//   'state-load'        {expression, label, folder?} — gespeicherte Suche als
//                         Chips laden (folder {id, name} merkt sich der
//                         Speicherdialog zum Überschreiben, Block S7)
//   'save-dialog-open'  {expression, predicates, sort, total}
//                       — ☆ speichern: Speicherdialog öffnen (Block S7)
//   'state-clear'       {}       — Zustand leeren („Alle Medien")
//   'source-changed'    {kind: 'dupes'} — Spezialansicht Dubletten
//   'selection-changed' {hash, index}
//                       — anderes Item ausgewählt (Grid → Panel/Loupe)
//   'loupe-open'        {hash, mode}
//                       — Loupe öffnen (mode: 'media'|'workflow';
//                         mode optional, Standard 'media')
//   'items-reloaded'    {total}
//                       — Grid hat neue Daten geladen (z. B. für Zähler);
//                         Konsumenten setzen ihren Zustand zurück
//   'items-refreshed'   {total}
//                       — schonender Refresh (ADR 0057): nur Daten frisch,
//                         Scroll/Auswahl blieben — KEINE Zustands-Resets
//   'arena-open'        {id, name, expression}
//                       — Arena öffnen (Sidebar → rankings.js, ADR 0045)
//   'arena-create'      {}       — Arena-Dialog „Neue Arena" öffnen
//   'rankings-changed'  {}       — Arenen-Bestand/Duelle geändert
//                         (rankings.js → Sidebar lädt die Gruppe neu)

export const bus = new EventTarget();
export const emit = (type, detail) => bus.dispatchEvent(new CustomEvent(type, { detail }));
// Gibt den Wrapper-Handler zurück — damit ist bus.removeEventListener(type, h)
// möglich (Loupe/Admin können temporäre Listener wieder abhängen).
export const on = (type, fn) => {
  const h = (e) => fn(e.detail);
  bus.addEventListener(type, h);
  return h;
};

// -- Theme -----------------------------------------------------------------------
//
// Dark ist Standard (kein data-theme-Attribut); nur 'light' wird explizit
// gesetzt. Wahl überlebt in localStorage('feral-theme'). Umschalten passiert
// NUR im Admin-Schnellmenü (quickmenu.js) — das separate Header-Icon flog
// raus (Feral Strawberry, 2026-07-16: doppelt verwaltbar, so oft braucht man das nicht).

const THEME_KEY = "feral-theme";

function initTheme() {
  if (localStorage.getItem(THEME_KEY) === "light") {
    document.documentElement.dataset.theme = "light";
  }
}

// -- Topbar ------------------------------------------------------------------------

/** Bytes → lesbare Größe: ab 1 GB in GB (eine Nachkommastelle), darunter MB. */
function fmtSize(n) {
  if (n >= 1e9) {
    return (n / 1e9).toLocaleString(STRINGS.locale, {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    }) + " GB";
  }
  return Math.round(n / 1e6).toLocaleString(STRINGS.locale) + " MB";
}

// -- Instanz (ADR 0041, I5) ---------------------------------------------------
//
// Name + Akzentfarbe aus [web] in der Config unterscheiden parallel laufende
// Instanzen: Topbar-Badge, Tab-Titel und ein Farbpunkt im Favicon. Ohne
// Config-Einträge bleibt alles beim Standard-Erscheinungsbild.

const DEFAULT_TITLE = "Feral Media Library";
let faviconBase = null; // Original-Href merken, um zum Standard zurückzukönnen

function tintFavicon(farbe) {
  const link = document.querySelector('link[rel="icon"]');
  if (!link) return;
  if (faviconBase === null) faviconBase = link.href;
  if (!farbe) { link.href = faviconBase; return; }
  const img = new Image();
  img.onload = () => {
    const c = document.createElement("canvas");
    c.width = c.height = 64;
    const ctx = c.getContext("2d");
    ctx.drawImage(img, 0, 0, 64, 64);
    // Farbpunkt unten rechts statt Um-Einfärben: die Erdbeere bleibt
    // erkennbar, der Punkt unterscheidet die Tabs.
    ctx.beginPath();
    ctx.arc(46, 46, 16, 0, Math.PI * 2);
    ctx.fillStyle = farbe;
    ctx.fill();
    ctx.lineWidth = 3;
    ctx.strokeStyle = "rgba(0, 0, 0, .35)";
    ctx.stroke();
    link.href = c.toDataURL("image/png");
  };
  img.src = faviconBase;
}

function applyInstance(inst) {
  const root = document.documentElement;
  const badge = document.getElementById("instanceBadge");
  const name = (inst && inst.name) || "";
  const farbe = (inst && inst.farbe) || "";
  document.title = name ? `${name} — ${DEFAULT_TITLE}` : DEFAULT_TITLE;
  badge.hidden = !name;
  badge.textContent = name;
  badge.title = STRINGS.instanceBadgeTitle;
  if (/^#[0-9a-f]{6}$/i.test(farbe)) {
    // Die abgeleiteten Varianten (-dim/-line) sind in theme.css feste
    // rgba-Werte — hier aus dem Hex neu gerechnet, gleiche Alphas.
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(farbe.slice(i, i + 2), 16));
    root.style.setProperty("--accent", farbe);
    root.style.setProperty("--accent-dim", `rgba(${r}, ${g}, ${b}, .14)`);
    root.style.setProperty("--accent-line", `rgba(${r}, ${g}, ${b}, .5)`);
    tintFavicon(farbe);
  } else {
    root.style.removeProperty("--accent");
    root.style.removeProperty("--accent-dim");
    root.style.removeProperty("--accent-line");
    tintFavicon(null);
  }
}

/** Bestandszähler laden; bei Serverfehler dezente Meldung statt Crash. */
async function initCounts() {
  const counts = document.getElementById("counts");
  const badge = document.getElementById("modeBadge");
  try {
    const s = await getStats();
    counts.textContent = STRINGS.totalsPlain
      .replace("{items}", s.total_items.toLocaleString(STRINGS.locale))
      .replace("{size}", fmtSize(s.total_bytes));
    // Badge NUR im Übersichtsmodus (ADR 0041, I4) — der eingeschaltete
    // Zustand braucht keinen eigenen Modusnamen.
    badge.hidden = s.verwaltung !== false;
    badge.textContent = STRINGS.modeBadge;
    badge.title = STRINGS.modeBadgeTitle;
    applyInstance(s.instanz); // I5: Name/Farbe wirken sofort (auch nach Config-Speichern)
  } catch (err) {
    console.warn(err); // Debugbarkeit — die Oberfläche bleibt trotzdem sanft.
    counts.textContent = STRINGS.serverUnreachable;
  }
}

function initTopbar() {
  document.getElementById("q").placeholder = STRINGS.searchPlaceholder;
  const adminBtn = document.getElementById("adminBtn");
  adminBtn.title = STRINGS.tooltipAdmin;
  // Slider-Icon aus dem Design (drei Regler-Balken mit Knopf).
  adminBtn.innerHTML = '<span class="sliders"><i></i><i></i><i></i></span>';
  document.getElementById("activity").title = STRINGS.tooltipActivity;
  // Der Sortier-Knopf samt Popover gehört der Galerie (gallery.js, ADR 0039).

  // Harter Sprachumschalter (ADR 0054): zeigt die aktive Sprache, Klick
  // rotiert durch LANGUAGES — setLang merkt sich die Wahl und lädt neu.
  const langBtn = document.getElementById("langBtn");
  langBtn.textContent = LANG.toUpperCase();
  langBtn.title = STRINGS.langSwitchTitle;
  langBtn.addEventListener("click", () => {
    const i = LANGUAGES.findIndex((l) => l.code === LANG);
    setLang(LANGUAGES[(i + 1) % LANGUAGES.length].code);
  });
}

// -- Verstellbare Panelbreiten (Sidebar links, Detail-Panel rechts) -----------------
//
// Ziehen am Trenner setzt eine CSS-Variable (--sbw/--pw), die Wahl überlebt in
// localStorage; Doppelklick stellt den Design-Standard wieder her. Nach jeder
// Änderung feuert 'resize', damit das virtualisierte Grid neu misst.

const PANEL_KEY = "feral-panels";
const PANEL_DEFAULTS = { sbw: 248, pw: 344 };

function initPanelResize() {
  const root = document.documentElement;
  const saved = { ...JSON.parse(localStorage.getItem(PANEL_KEY) || "{}") };
  const apply = () => {
    root.style.setProperty("--sbw", (saved.sbw || PANEL_DEFAULTS.sbw) + "px");
    root.style.setProperty("--pw", (saved.pw || PANEL_DEFAULTS.pw) + "px");
    window.dispatchEvent(new Event("resize"));
  };
  apply();

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, Math.round(v)));
  const attach = (id, key, fromX) => {
    const el = document.getElementById(id);
    el.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      try { el.setPointerCapture(e.pointerId); } catch { /* synthetische Pointer */ }
      const move = (ev) => { saved[key] = fromX(ev.clientX); apply(); };
      const up = () => {
        el.removeEventListener("pointermove", move);
        el.removeEventListener("pointerup", up);
        localStorage.setItem(PANEL_KEY, JSON.stringify(saved));
      };
      el.addEventListener("pointermove", move);
      el.addEventListener("pointerup", up);
    });
    el.addEventListener("dblclick", () => {
      delete saved[key];
      localStorage.setItem(PANEL_KEY, JSON.stringify(saved));
      apply();
    });
  };
  attach("splitL", "sbw", (x) => clamp(x, 170, 480));
  attach("splitR", "pw", (x) => clamp(window.innerWidth - x, 260, 720));
}

// -- Boot ---------------------------------------------------------------------------

initTheme();
initTopbar();
initCounts();
initPanelResize();

// -- Erweiterungspunkte (Tasks 6–11) ---------------------------------------------
//
// Jeder Funktionsbereich ist ein eigenes Modul mit einer init…()-Funktion,
// die hier importiert und aufgerufen wird (Rezept analog Extraktor/Parser).
// Noch nicht existierende Module NICHT importieren — der Import würde die
// ganze Shell brechen. Reihenfolge unkritisch, Kommunikation läuft über den Bus.
//

initGallery(); // Galerie: virtualisiertes Grid + Sortierung + Dichte
initSidebar(); // Sidebar: Bibliothek + Nach Modell (Task 7)
initSearch();  // Suche: Topbar-Feld + Ergebnisliste + Breadcrumb (Task 7)
initAdvanced(); // Advanced Mode: „+ Kriterium"-Popover + Tipphilfe (Block S5)
initSaveDialog(); // Speicherdialog: speichern/überschreiben/umbenennen/löschen (Block S7)
initBulkDialog(); // Sammel-Aktion aufs Suchergebnis (Großbaustelle K, ADR 0040)
initDetail();  // Detail-Panel rechts: alle Schichten sichtbar (Task 9)
initLoupe();   // Vollbild-Lupe: Blättern mit Vorladen + Workflow-Modus (Task 10)
initSingleView();  // Einzelbildansicht: Zoom + breites Panel (Feral Strawberry, 2026-07-08)
initAdmin();   // Admin-Konsole + Aktivitäts-Indikator (Task 11)
initCurate();  // Kuratieren: Rating-Tastatur + Schreibstelle manuelle Schicht (3.2)
initQuickmenu(); // Schnellzugriff-Overlay am Admin-Knopf (Vorschlag)
initRankings(); // Ranking-Modul: Arenen mit Duell + Bestenliste (ADR 0045)

// Nach abgeschlossenen Engine-Aufgaben (Scan/Wartung) Zähler auffrischen.
on("engine-idle", initCounts);
// Nach Config-Speichern (Admin) das Übersichtsmodus-Badge nachziehen (I4).
on("config-saved", initCounts);
