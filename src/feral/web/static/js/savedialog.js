// savedialog.js — Speicherdialog für gespeicherte Suchen (Block S7, ADR 0035;
// Fassung ADR-0081-Revision #133).
//
// Eigener Theme-Dialog statt prompt(): Chip-Vorschau, Trefferzahl, Hinweis
// auf mitgespeicherte Sortierung, Name. Kommt der Zustand aus einer
// gespeicherten Suche (Sidebar-Klick, 'state-load' mit `folder`), sagt der
// Dialog das AUSDRÜCKLICH („Aus der gespeicherten Suche »PNGs«"), belegt
// den Namen vor und bietet zwei klar benannte Wege: „»PNGs« überschreiben"
// (mit geändertem Namen = umbenennen) und „Als neue Suche speichern". Ohne
// Ursprung gibt es nur „Speichern". Der Ursprung ist nie versteckt: er
// steht im Dialog, und die Sidebar markiert die Suche, solange die Chips
// ihr entsprechen (sidebar.js). Gespeichert wird NUR der kanonische
// Ausdruckstext — die Chips sind Ansicht, nicht Speicherformat.
//
// Löschen bleibt am ✕ der Sidebar-Zeile (zweistufig).

import { STRINGS } from "./strings.js";
import { createFolder, updateFolder } from "./api.js";
import { emit, on } from "./main.js";
import { registerDialog } from "./overlays.js";
import { chipText } from "./search.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export function initSaveDialog() {
  // Ursprung: aus WELCHER gespeicherten Suche kam der Zustand? Bleibt beim
  // Chip-Bearbeiten erhalten (genau dafür ist das Laden da) und endet,
  // wenn der Zustand geleert oder verlassen wird.
  let origin = null;    // {id, name} | null
  let current = null;   // Zustand beim Öffnen: {expression, predicates, sort, total}

  const overlay = document.createElement("div");
  overlay.id = "savedlg";
  overlay.className = "pickoverlay";
  overlay.hidden = true;
  document.body.appendChild(overlay);

  let unregister = () => {};   // Dialog-Stapel (ADR 0069)
  function close() {
    unregister();
    overlay.hidden = true;
    current = null;
  }

  function showError(message) {
    const el = overlay.querySelector(".sderr");
    el.textContent = `⚠ ${message}`;
    el.hidden = false;
  }

  function render() {
    const sortKey = current.sort;
    // Richtungs-Suffix -auf/-ab (ADR 0039) als Pfeil, wie im Sortier-Chip.
    const base = (sortKey || "").split("-")[0];
    const richtung = (sortKey || "").split("-")[1];
    const opt = STRINGS.sortOptions.find((o) => o.key === base);
    const sortLabel = opt
      ? `${opt.label} ${(richtung || opt.dir) === "auf" ? "↑" : "↓"}`
      : sortKey;
    const named = (s) => s.replace("{name}", origin?.name ?? "");
    overlay.innerHTML = `
      <div class="pickbox savebox">
        <div class="pickhead"><b>${esc(STRINGS.saveDlgTitle)}</b></div>
        ${origin ? `<div class="sdorigin">☆ ${esc(named(STRINGS.saveDlgOrigin))}</div>` : ""}
        <div class="sdchips">
          ${current.predicates.map((p) => `
            <span class="chip${p.negated ? " neg" : ""}${p.kind === "sort" ? " sort" : ""}">
              ${p.negated ? `<span class="chipneg">${STRINGS.chipNegated}</span>` : ""}
              <span class="chiptext">${esc(chipText(p))}</span>
            </span>`).join("")}
          <span class="sdcount">· ${current.total.toLocaleString(STRINGS.locale)} ${STRINGS.saveDlgHits}</span>
        </div>
        ${sortKey ? `<div class="sdhint">${esc(STRINGS.saveDlgSortHint)} ${esc(sortLabel)}</div>` : ""}
        <input type="text" class="sdname" placeholder="${STRINGS.saveDlgNamePlaceholder}"
               value="${esc(origin ? origin.name : "")}">
        <span class="sderr" hidden></span>
        <div class="sdactions">
          ${origin ? `
            <button type="button" class="sdprimary" data-act="overwrite">${esc(named(STRINGS.saveDlgOverwriteNamed))}</button>
            <button type="button" data-act="createnew">${esc(STRINGS.saveDlgSaveAsNew)}</button>
          ` : `
            <button type="button" class="sdprimary" data-act="create">${esc(STRINGS.saveDlgCreate)}</button>
          `}
          <button type="button" data-act="cancel">${esc(STRINGS.saveDlgCancel)}</button>
        </div>
      </div>`;
    const name = overlay.querySelector(".sdname");
    name.focus();
    name.select();
  }

  async function act(action) {
    const name = overlay.querySelector(".sdname").value.trim();
    if (!name) { showError(STRINGS.saveDlgNoName); return; }
    try {
      if (action === "overwrite") {
        await updateFolder(origin.id, name, current.expression);
        origin = { id: origin.id, name };
      } else {
        const d = await createFolder(name, current.expression);
        origin = { id: d.id, name };   // ab jetzt ist DIESE Suche der Ursprung
      }
      // Sidebar: markiert die Suche, solange die Chips ihr entsprechen.
      emit("folder-origin", { id: origin.id, name, expression: current.expression });
      emit("folders-changed", {});
      close();
    } catch (err) {
      showError(err.message);
    }
  }

  overlay.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-act]");
    if (btn) {
      btn.dataset.act === "cancel" ? close() : act(btn.dataset.act);
      return;
    }
    if (e.target === overlay) close();   // Klick auf den Hintergrund
  });
  overlay.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.matches(".sdname")) {
      act(origin ? "overwrite" : "create");
    }
  });

  // -- Bus ------------------------------------------------------------------

  on("save-dialog-open", (d) => {
    current = d;
    unregister();
    unregister = registerDialog(overlay, close);
    overlay.hidden = false;
    render();
  });

  // Ursprungs-Pflege: Laden setzt ihn, Leeren/Verlassen beendet ihn.
  on("state-load", (d) => { origin = d.folder ? { id: d.folder.id, name: d.folder.name } : null; });
  on("state-clear", () => { origin = null; });
  on("source-changed", (d) => { if (d?.kind === "dupes") origin = null; });
  on("search-state-changed", (d) => { if (!d.expression) origin = null; });
}
