// overlays.js — Dialog-Stapel (ADR 0069, Issue #23).
//
// Jeder Dialog (die `.pickoverlay`-Boxen: Ordner-Picker, Rausverschieben,
// Probleme, Arena, Speichern, Sammel-Aktion, Ablehnen) meldet sich beim
// Öffnen mit seiner Schließfunktion an und beim Schließen wieder ab.
// EIN zentraler Escape-Listener (Capture) schließt den obersten Dialog und
// stoppt das Ereignis, damit Esc nicht zusätzlich die Ebene darunter trifft
// (Lupe, Einzelbild, Filter-Reset in search.js).
//
// Vorher entfernte jeder Öffner fremde Dialoge per `.remove()` aus dem DOM:
// deren Promise löste sich nie auf (Rausverschieben wartete auf den Picker),
// deren Esc-Listener blieben hängen (#31, #36). Jetzt gilt: Dialoge dürfen
// übereinander liegen, und Schließen von außen läuft IMMER über die
// Schließfunktion des Dialogs.

import { on } from "./main.js";

const stack = [];   // [{ el, close }], oberster Dialog am Ende

/** Dialog anmelden. Gibt die Abmeldefunktion zurück (mehrfach rufbar) —
 *  die Schließfunktion des Dialogs ruft sie, bevor sie das Element entfernt
 *  oder versteckt. `close` selbst muss mehrfach aufrufbar sein. */
export function registerDialog(el, close) {
  const entry = { el, close };
  stack.push(entry);
  return () => {
    const i = stack.indexOf(entry);
    if (i >= 0) stack.splice(i, 1);
  };
}

/** Obersten Dialog schließen. true, wenn einer offen war. */
export function closeTopDialog() {
  const top = stack.pop();
  if (!top) return false;
  top.close();
  return true;
}

/** Alle Dialoge schließen (Ansichtswechsel, ADR 0069 Punkt 3). */
export function closeAllDialogs() {
  while (closeTopDialog()) { /* bis der Stapel leer ist */ }
}

export const dialogsOpen = () => stack.length > 0;

// Ein Listener für alle Dialoge, installiert beim Laden des Moduls: er muss
// existieren, sobald der erste Dialog existiert, und darf nie doppelt sein.
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || !stack.length) return;
  e.stopPropagation();            // nichts darunter (Lupe, Filter-Reset) sieht das Esc
  e.stopImmediatePropagation();   // auch keine Geschwister-Listener am Dokument
  e.preventDefault();
  closeTopDialog();
}, true);

/** Bus-Anmeldung — aus main.js aufrufen (nicht beim Laden: overlays.js wird
 *  über die Dialog-Module importiert, BEVOR main.js seinen Bus gebaut hat). */
export function initOverlays() {
  on("view-changed", closeAllDialogs);
}
