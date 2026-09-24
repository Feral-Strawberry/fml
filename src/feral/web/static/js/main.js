// main.js — Einstiegspunkt der neuen Shell (Block 3.0).
//
// Hier leben nur: der Mini-Event-Bus (Module reden über Events, nicht
// direkt miteinander — Begründung: ADR 0015) und der Boot-Ablauf
// (Theme, Kopfzeile, Einhängen der Funktionsmodule).

import { STRINGS, LANG, LANGUAGES, setLang } from "./strings.js";
import { getStats } from "./api.js";
import { initGallery } from "./gallery.js";
import { initLibraryView } from "./libview.js";
import { initAudioList } from "./audiolist.js";
import { initPlayer } from "./player.js";
import { initComments } from "./comments.js";
import { initSidebar } from "./sidebar.js";
import { initSearch } from "./search.js";
import { initAdvanced } from "./advanced.js";
import { initSaveDialog } from "./savedialog.js";
import { initCoverDialog } from "./coverdialog.js";
import { initContext } from "./context.js";
import { initBulkDialog } from "./bulkdialog.js";
import { initDetail } from "./detail.js";
import { initLoupe } from "./loupe.js";
import { initSingleView } from "./singleview.js";
import { initCompare } from "./compare.js";
import { initCurate } from "./curate.js";
import { initRankings } from "./rankings.js";
import { initOverlays } from "./overlays.js";
import { initTheme, initThemeToggle, applyInstance } from "./appearance.js";
import { startStatusPolling, initActivityBadge } from "./status.js";

// -- Event-Bus -----------------------------------------------------------------
//
// Vereinbarte Events (Payload = event.detail):
//   'search-state-changed' {expression, predicates, sort, reset, viewChanged}
//                       — der EINE Suchzustand (Chips, ADR 0035) hat sich
//                         geändert: Grid filtert, Sidebar markiert;
//                         reset: true = „Alle Medien" (Sidebar) — Grid
//                         oben, kein Rücksprung (Issue #33)
//   'chip-toggle'       {pred}   — Facetten-Wert togglen (Sidebar → search.js)
//   'sort-changed'      {sort}   — Galerie-Dropdown setzt die Sortierung
//                         (search.js ersetzt den sort:-Chip; Block S6)
//   'state-load'        {expression, label, folder?, arena?} — gespeicherte Suche/Arena als
//                         Chips laden (folder = Ursprung für ☆-Dialog und
//                         Sidebar-Markierung; arena = Bearbeiten-Modus im
//                         Breadcrumb, ADR 0081/#133)
//   'save-dialog-open'  {expression, predicates, sort, total}
//                       — ☆ speichern: Speicherdialog öffnen (Block S7)
//   'state-clear'       {}       — Zustand leeren („Alle Medien")
//   'source-changed'    {kind: 'dupes'} — Spezialansicht Dubletten
//   'selection-changed' {hash, index}
//                       — anderes Item ausgewählt (Grid → Panel/Loupe)
//   'loupe-open'        {hash, mode}
//                       — Loupe öffnen (mode: 'media'|'workflow';
//                         mode optional, Standard 'media')
//   'single-open'       {hash, index?}
//                       — Einzelbildansicht öffnen (Grid-Doppelklick, Lupe)
//   'compare-open'      {hashes: [a, b]}
//                       — A/B-Vergleichsansicht für genau zwei Medien
//                         (Galerie-Knopf ⇆ / Taste C → compare.js, Issue #38)
//   'items-reloaded'    {total, reset}
//                       — Grid hat neue Daten geladen (z. B. für Zähler);
//                         Konsumenten setzen ihren Zustand zurück;
//                         reset: true nach „Alle Medien" (Issue #33)
//   'items-refreshed'   {total}
//                       — schonender Refresh (ADR 0057): nur Daten frisch,
//                         Scroll/Auswahl blieben — KEINE Zustands-Resets
//   'arena-open'        {id, name, expression}
//                       — Arena öffnen (Sidebar → rankings.js, ADR 0045)
//   'arena-dialog-open' {expression, predicates, total}
//                       — 🏆 in der Chip-Leiste: NEUE Arena aus den Chips
//                         (search.js → rankings.js, ADR 0081)
//   'rankings-enabled'  {enabled} — Modul-Schalter (Sidebar → search.js)
//   'audio-enabled'     {enabled} — Modul-Schalter Audio (Sidebar →
//                         advanced.js: Medienart „Audio" nur mit Modul, ADR 0084)
//   'chips-rendered'    {}       — Chip-Leiste neu gezeichnet (search.js →
//                         context.js hängt das Kontext-Segment ein)
//   'folder-origin'     {id, name, expression}
//                       — gespeicherte Suche gerade gespeichert/überschrieben
//                         (savedialog.js → Sidebar markiert sie)
//   'context-changed'   {kind, id, name} | null — Bearbeiten-Modus für
//                         Rankings (context.js → Sidebar)
//   'rankings-changed'  {}       — Arenen-Bestand/Duelle geändert
//                         (rankings.js → Sidebar lädt die Gruppe neu)
//   'library-view-changed' {view} — Ansicht „galerie"|„audio" gewechselt
//                         (libview.js, ADR 0085): Grundbereich, NICHT
//                         Suchzustand — Galerie/Sidebar stellen die
//                         Darstellung um; search.js dünnt die Medienart-
//                         Chips aus und verkündet 'search-state-changed'
//                         mit viewChanged: true, darauf wird geladen
//   'library-view-set'  {view}   — Wunsch nach Ansichtswechsel (Leer-
//                         Hinweis, Tipphilfe → libview.js)
//   'cover-pick'        {hash, name, tags, cover} — Cover-Dialog für einen
//                         Song öffnen (Detailpanel → coverdialog.js, #165)
//   'cover-changed'     {hash, manual} — Cover gesetzt/entfernt: Galerie
//                         frischt auf (Song kommt/geht), Panel zeichnet neu
//   'view-changed'      {view, open}
//                       — eine Ansicht (loupe|single|compare|rankings)
//                         wurde geöffnet/geschlossen (ADR 0069): Haken für
//                         Aufräumer — Dialog-Stapel leert sich (overlays.js),
//                         Sperren fallen zurück. Nur Ressourcen, nie Daten.

export const bus = new EventTarget();
export const emit = (type, detail) => bus.dispatchEvent(new CustomEvent(type, { detail }));
// Gibt den Wrapper-Handler zurück — damit ist bus.removeEventListener(type, h)
// möglich (Loupe/Admin können temporäre Listener wieder abhängen).
export const on = (type, fn) => {
  const h = (e) => fn(e.detail);
  bus.addEventListener(type, h);
  return h;
};

// -- Topbar ------------------------------------------------------------------------

// -- Instanz (ADR 0041, I5) -- Name/Farbe: appearance.js (geteilt mit dem Admin).

/** Übersichtsmodus- und Instanz-Badge aus den Kennzahlen setzen. Der
 *  Bestandszähler (Items · Größe) steht seit #121 NUR im Sidebar-Fuß —
 *  die Topbar-Kopie war ärmer (ohne Library/gesamt) und hing an weniger
 *  Ereignissen. Bei Serverfehler bleibt die Oberfläche sanft. */
async function initCounts() {
  const badge = document.getElementById("modeBadge");
  try {
    const s = await getStats();
    // Badge NUR im Übersichtsmodus (ADR 0041, I4) — der eingeschaltete
    // Zustand braucht keinen eigenen Modusnamen.
    badge.hidden = s.verwaltung !== false;
    badge.textContent = STRINGS.modeBadge;
    badge.title = STRINGS.modeBadgeTitle;
    // I5: Name/Farbe wirken sofort (auch nach Config-Speichern im Admin-Tab)
    applyInstance(s.instanz, { badge: document.getElementById("instanceBadge"),
                               badgeTitle: STRINGS.instanceBadgeTitle });
  } catch (err) {
    console.warn(err); // Debugbarkeit — die Oberfläche bleibt trotzdem sanft.
  }
}

function initTopbar() {
  document.getElementById("q").placeholder = STRINGS.searchPlaceholder;
  const adminBtn = document.getElementById("adminBtn");
  adminBtn.title = STRINGS.tooltipAdmin;
  // Slider-Icon aus dem Design (drei Regler-Balken mit Knopf).
  adminBtn.innerHTML = '<span class="sliders"><i></i><i></i><i></i></span>';
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
  // Dark/Light neben der Sprache (#123) — das Schnellmenü ist Geschichte,
  // der Admin-Knopf daneben ist ein reiner Link.
  initThemeToggle(document.getElementById("themeBtn"),
                  { toDark: STRINGS.themeToDark, toLight: STRINGS.themeToLight });
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

initOverlays(); // Dialog-Stapel: Ansichtswechsel schließt alle Dialoge (ADR 0069)
initLibraryView(); // Galerie | Audio (ADR 0085) — VOR der Galerie: gemerkte Ansicht gilt ab dem ersten Laden
initGallery(); // Galerie: virtualisiertes Grid + Sortierung + Dichte
initSidebar(); // Sidebar: Bibliothek + Nach Modell (Task 7)
initSearch();  // Suche: Topbar-Feld + Ergebnisliste + Breadcrumb (Task 7)
initAdvanced(); // Advanced Mode: „+ Kriterium"-Popover + Tipphilfe (Block S5)
initSaveDialog(); // Speicherdialog: neue Suche oder »Name« überschreiben (Block S7, #133)
initCoverDialog(); // Cover eines Songs aus der Bibliothek wählen (Audio A8, #165)
initContext();    // Bearbeiten-Modus für Rankings im Breadcrumb (ADR 0081/#133)
initBulkDialog(); // Sammel-Aktion aufs Suchergebnis (Großbaustelle K, ADR 0040)
initDetail();  // Detail-Panel rechts: alle Schichten sichtbar (Task 9)
initLoupe();   // Vollbild-Lupe: Blättern mit Vorladen + Workflow-Modus (Task 10)
initSingleView();  // Einzelbildansicht: Zoom + breites Panel (Feral Strawberry, 2026-07-08)
initCompare();     // A/B-Vergleich zweier markierter Bilder mit Wischkante (Issue #38)
initCurate();  // Kuratieren: Rating-Tastatur + Schreibstelle manuelle Schicht (3.2)
initRankings(); // Ranking-Modul: Arenen mit Duell + Bestenliste (ADR 0045)
initPlayer();    // eigener Audio-Player + Abspielleiste (A5 #162, ADR 0087)
initAudioList(); // Audioansicht: Zeilen, Zeitachse, Tasten, Alle abspielen (ADR 0085/0087)
initComments();  // Zeitkommentare: Pins, Taste K, Panel-Abschnitt (A6 #163, ADR 0088)

// Status-Poller (status.js, geteilt mit dem Admin-Dokument): Topbar-Badge,
// und an der Flanke laufend→leer der Bus-Event 'engine-idle' (Grid, Sidebar,
// Zähler laden neu). Der Admin selbst ist seit ADR 0074 ein eigenes Dokument
// unter /admin — kein initAdmin() mehr in dieser Shell.
initActivityBadge(document.getElementById("activity"));
startStatusPolling({ onIdle: () => emit("engine-idle", {}) });

// Nach abgeschlossenen Engine-Aufgaben (Scan/Wartung) Zähler auffrischen.
on("engine-idle", initCounts);
// Config-Speichern passiert im Admin-Tab: Wird dieser Tab wieder sichtbar,
// Kennzahlen + Übersichtsmodus-Badge + Instanzname frisch holen (I4/I5;
// /api/stats ist epochen-gecacht, das kostet nichts).
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") initCounts();
});
