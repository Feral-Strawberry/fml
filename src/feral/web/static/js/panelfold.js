// panelfold.js — rechtes Detail-Panel wegklappen (#219).
//
// Kleine Monitore: beim Markieren (Ablehnen, Sammel-Aktionen) ist jede
// Galerie-Spalte Gold wert. Muster Lightroom (Wunsch beim Test): ein
// schmaler Streifen FEST am rechten Fensterrand (#panelFold, rechts neben
// dem Panel) ist ein reiner Umschalter — Klick irgendwo darauf klappt
// weg bzw. holt zurück, der Pfeil auf halber Höhe zeigt die Richtung.
// Der Trenner links vom Panel bleibt der Griff für die Breite. Taste P
// schaltet ebenfalls um. Zustand in localStorage, gilt über Neustarts.
//
// Nur die Galerie-Spalte ist betroffen: Lupe und Einzelansicht zeigen ihr
// Panel wie immer (die Einzelansicht leiht sich #panel aus, das CSS blendet
// nur „#body > #panel" aus). Die Galerie rechnet ihre Spalten über das
// resize-Ereignis neu, die Auswahl bleibt unberührt.

import { STRINGS } from "./strings.js";
import { emit } from "./main.js";

const FOLD_KEY = "feral-panel-folded";
const chevron = (d) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
const ICON_FOLD = chevron("M9 5l7 7-7 7");     // › Panel nach rechts weg
const ICON_UNFOLD = chevron("M15 5l-7 7 7 7"); // ‹ Panel zurückholen

export function initPanelFold() {
  const tab = document.getElementById("panelFold");
  if (!tab) return;

  let stored = false;
  try { stored = localStorage.getItem(FOLD_KEY) === "1"; } catch { /* privat */ }

  function apply(folded, announce) {
    document.body.classList.toggle("panel-folded", folded);
    tab.innerHTML = `<span class="grip">${folded ? ICON_UNFOLD : ICON_FOLD}</span>`;
    tab.dataset.icon = folded ? "unfold" : "fold";
    tab.title = folded ? STRINGS.panelUnfoldTitle : STRINGS.panelFoldTitle;
    if (!announce) return;
    try { localStorage.setItem(FOLD_KEY, folded ? "1" : "0"); } catch { /* privat */ }
    window.dispatchEvent(new Event("resize"));   // Galerie: mehr/weniger Spalten
    emit("panel-folded", { folded });
  }
  const isFolded = () => document.body.classList.contains("panel-folded");
  const toggle = () => apply(!isFolded(), true);

  apply(stored, false);
  tab.addEventListener("click", toggle);

  document.addEventListener("keydown", (e) => {
    if (e.key !== "p" && e.key !== "P") return;
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.target instanceof Element && e.target.matches("input, textarea, select, [contenteditable]")) return;
    for (const id of ["loupe", "single", "rankings", "compare"]) {
      if (!document.getElementById(id)?.hidden) return;
    }
    e.preventDefault();
    toggle();
  });
}
