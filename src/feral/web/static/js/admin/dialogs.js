// admin/dialogs.js — Dialoge des Admin-Dokuments mit EIGENEM Stapel
// (ADR 0074 Punkt 4), unabhängig von overlays.js der Galerie. Seit A3
// (#107) gibt es im Admin NUR noch diese zwei: Ordnerwahl (pickFolder) und
// Bestätigung (confirmDialog) — alles andere ist Seiteninhalt. Dialoge
// dürfen übereinander liegen (Bestätigung → Ordnerwahl): Esc schließt den
// obersten, Klick auf den Hintergrund auch.
//
// Regeln wie in ADR 0069: Dialoge dürfen übereinander liegen, Schließen
// von außen läuft IMMER über die Schließfunktion des Dialogs (ein
// wartendes Promise löst sich auf, kein hängender Picker, #31/#36).

import { STRINGS } from "../strings.js";
import { getRoots, browse } from "../api.js";
import { esc } from "./util.js";

const stack = [];   // [{ el, close }], oberster Dialog am Ende

export function registerDialog(el, close) {
  const entry = { el, close };
  stack.push(entry);
  return () => {
    const i = stack.indexOf(entry);
    if (i >= 0) stack.splice(i, 1);
  };
}

export function closeTopDialog() {
  const top = stack.pop();
  if (!top) return false;
  top.close();
  return true;
}

export function closeAllDialogs() {
  while (closeTopDialog()) { /* bis der Stapel leer ist */ }
}

export const dialogsOpen = () => stack.length > 0;

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || !stack.length) return;
  e.stopPropagation();
  e.stopImmediatePropagation();
  e.preventDefault();
  closeTopDialog();
}, true);

/** Overlay-Hülle anlegen: .pickoverlay > .pickbox mit `html`; liefert
 *  {overlay, close(value)} — close entfernt das Element und meldet ab. */
function openBox(html, onClose) {
  const overlay = document.createElement("div");
  overlay.className = "pickoverlay";
  overlay.innerHTML = `<div class="pickbox">${html}</div>`;
  document.body.appendChild(overlay);
  let done = false;
  const unregister = registerDialog(overlay, () => close(undefined));
  const close = (value) => {
    if (done) return;
    done = true;
    unregister();
    overlay.remove();
    onClose(value);
  };
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(undefined); });
  return { overlay, close };
}

// -- Ordner-Auswahl (über /api/roots + /api/browse) -----------------------------

export function pickFolder(startPath) {
  return new Promise((resolve) => {
    const { overlay, close } = openBox(`
        <div class="pickhead"><span class="mlabel">${STRINGS.pickTitle}</span>
          <span class="pickpath vmono" id="pickPath"></span></div>
        <div class="addirs" id="pickDirs"></div>
        <div class="adactions">
          <button type="button" class="accentbtn" id="pickOk">${STRINGS.pickChoose}</button>
          <button type="button" id="pickCancel">${STRINGS.pickCancel}</button>
        </div>`, (v) => resolve(v ?? null));
    let current = null;

    async function show(path) {
      try {
        if (!path) {
          const r = await getRoots();
          overlay.querySelector("#pickPath").textContent = "";
          overlay.querySelector("#pickDirs").innerHTML = r.roots.map((d) =>
            `<div class="addir" data-path="${esc(d.path)}">${esc(d.name)}</div>`).join("");
          current = null;
          return;
        }
        const d = await browse(path);
        current = d.path;
        overlay.querySelector("#pickPath").textContent =
          `${d.path} · ${d.file_count} ${STRINGS.scanFilesHere}`;
        overlay.querySelector("#pickDirs").innerHTML =
          (d.parent ? `<div class="addir" data-path="${esc(d.parent)}">↑ ..</div>` : "") +
          d.subdirs.map((sub) =>
            `<div class="addir" data-path="${esc(sub.path)}">${esc(sub.name)}</div>`).join("");
      } catch (err) { alert(err.message); }
    }
    overlay.addEventListener("click", (e) => {
      const dir = e.target.closest(".addir");
      if (dir) return void show(dir.dataset.path);
      if (e.target.closest("#pickOk")) return close(current);
      if (e.target.closest("#pickCancel")) return close(null);
    });
    show(startPath || null);
  });
}

// -- Bestätigung -------------------------------------------------------------------

/** Ja/Nein-Dialog; löst mit true (bestätigt) oder false auf. */
export function confirmDialog(text, { ok = STRINGS.dlgOk, cancel = STRINGS.dlgCancel, danger = false } = {}) {
  return new Promise((resolve) => {
    const { overlay, close } = openBox(`
        <div class="pickhead"><span class="mlabel">${STRINGS.dlgConfirmTitle}</span></div>
        <div class="dlgtext">${esc(text)}</div>
        <div class="adactions" style="margin-bottom:0;">
          <button type="button" class="${danger ? "danger" : "accentbtn"}" id="dlgOk">${esc(ok)}</button>
          <button type="button" id="dlgCancel">${esc(cancel)}</button>
        </div>`, (v) => resolve(v === true));
    overlay.addEventListener("click", (e) => {
      if (e.target.closest("#dlgOk")) return close(true);
      if (e.target.closest("#dlgCancel")) return close(false);
    });
  });
}
