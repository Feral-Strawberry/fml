// libview.js — Umschalter „Galerie | Audio" in der Kopfzeile (ADR 0083/0084/0085).
//
// Zwei Ansichten, EIN Suchzustand: die Chips bleiben beim Wechsel stehen,
// nur der Grundbereich wechselt (Galerie = alles außer Audio, Audio = nur
// Audio). Der Grundbereich ist KEIN Suchzustand — er reist als ?view= mit
// den Anfragen (api.js) und ein Chip schaltet die Ansicht nie um (ADR 0084
// Punkt 2). Den Wechsel gibt es nur mit Audio-Modul; die Wahl überlebt in
// localStorage.
//
// Events: 'library-view-changed' {view} (Galerie, Sidebar, Popover laden
// neu), 'library-view-set' {view} = Wunsch von außen (Leer-Hinweis der
// Galerie, Navigationszeile der Tipphilfe).

import { STRINGS } from "./strings.js";
import { libraryView, setLibraryView } from "./api.js";
import { emit, on } from "./main.js";

const VIEW_KEY = "feral-view";

function stored() {
  try { return localStorage.getItem(VIEW_KEY) === "audio" ? "audio" : "galerie"; } catch { return "galerie"; }
}

/** Medienarten des Grundbereichs einer Ansicht (Geltungsbereich, ADR 0084
 *  Punkt 5) — typ:-Werte. Die Galerie zeigt ab A8 auch finalisierte Songs;
 *  das kommt dann aus den Daten, nicht von hier. */
export const viewKinds = (view = libraryView()) =>
  view === "audio" ? ["audio"] : ["bild", "video"];

export function initLibraryView() {
  const seg = document.getElementById("viewseg");
  seg.title = STRINGS.viewSwitchTitle;
  seg.innerHTML = `
    <button type="button" data-view="galerie">▦ ${STRINGS.viewGallery}</button>
    <button type="button" data-view="audio">♪ ${STRINGS.viewAudio}</button>`;
  let enabled = false;
  let wanted = stored();

  const render = () => {
    for (const b of seg.querySelectorAll("button[data-view]")) {
      b.classList.toggle("on", b.dataset.view === libraryView());
    }
  };
  const apply = (view) => {
    document.body.classList.toggle("view-audio", view === "audio");
    if (view === libraryView()) { render(); return; }
    setLibraryView(view);
    render();
    emit("library-view-changed", { view });
  };
  const choose = (view) => {
    if (view === "audio" && !enabled) return;
    wanted = view;
    try { localStorage.setItem(VIEW_KEY, view); } catch { /* privat */ }
    apply(view);
  };

  // Boot: die gemerkte Ansicht gilt sofort (VOR dem ersten Laden der
  // Galerie — main.js ruft dieses Modul zuerst), damit nichts doppelt lädt.
  // Stellt sich heraus, dass das Modul aus ist, fällt sie auf die Galerie.
  seg.hidden = true;
  setLibraryView(wanted);
  document.body.classList.toggle("view-audio", wanted === "audio");
  render();

  seg.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-view]");
    if (b) choose(b.dataset.view);
  });
  on("library-view-set", (d) => choose(d.view));
  on("audio-enabled", (d) => {
    enabled = !!d?.enabled;
    seg.hidden = !enabled;
    apply(enabled ? wanted : "galerie");
  });
}
