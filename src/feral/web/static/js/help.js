// help.js — Hilfe-Knopf „?“ in der Kopfzeile (ADR 0091).
//
// Nur sichtbar, wenn der Server einen Hilfe-Ordner ausliefert (--help-dir;
// /api/stats meldet `hilfe`). Ein Klick öffnet dessen index.html in einem
// Dialog ÜBER der Bibliothek (Dialogstapel, ADR 0069: Esc und Klick
// daneben schließen) — bewusst kein neues Fenster: im Edge-App-Fenster
// öffnete target=_blank ein normales Browserfenster mit Adresszeile.

import { STRINGS } from "./strings.js";
import { registerDialog } from "./overlays.js";

const HELP_URL = "/hilfe/";

let overlay = null;
let unregister = () => {};

function close() {
  unregister();
  if (overlay) overlay.hidden = true;
}

function build() {
  overlay = document.createElement("div");
  overlay.className = "pickoverlay helpoverlay";
  overlay.hidden = true;
  overlay.innerHTML = `<div class="helpbox">
    <div class="helphead"><b class="helptitle"></b><button type="button" class="helpclose">✕</button></div>
    <iframe class="helpframe"></iframe></div>`;
  overlay.querySelector(".helptitle").textContent = STRINGS.helpTitle;
  overlay.querySelector(".helpclose").title = STRINGS.helpClose;
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay || e.target.closest(".helpclose")) close();
  });
  const frame = overlay.querySelector(".helpframe");
  frame.title = STRINGS.helpTitle;
  // Der Hilfetext hat beim Lesen den Fokus; Esc darin schließt ebenfalls
  // (gleicher Ursprung, die Tasten erreichen die Bibliothek darunter nicht).
  frame.addEventListener("load", () => {
    try {
      frame.contentWindow.document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") close();
      });
      frame.contentWindow.focus();
    } catch { /* fremder Inhalt: dann eben nur ✕ und Klick daneben */ }
  });
  document.body.appendChild(overlay);
}

export function openHelp() {
  if (!overlay) build();
  const frame = overlay.querySelector(".helpframe");
  if (!frame.getAttribute("src")) frame.setAttribute("src", HELP_URL);
  unregister();
  unregister = registerDialog(overlay, close);
  overlay.hidden = false;
  try { frame.contentWindow?.focus(); } catch { /* s. o. */ }
}

/** Knopf verdrahten; sichtbar erst, wenn setHelpAvailable(true) kommt. */
export function initHelp(button) {
  button.textContent = "?";
  button.title = STRINGS.helpButton;
  button.addEventListener("click", openHelp);
}

export function setHelpAvailable(button, available) {
  button.hidden = !available;
}
