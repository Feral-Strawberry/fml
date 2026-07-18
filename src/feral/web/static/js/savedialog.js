// savedialog.js — Speicherdialog für gespeicherte Suchen (Block S7, ADR 0035).
//
// Eigener Theme-Dialog statt prompt(): Chip-Vorschau, Trefferzahl, Hinweis
// auf mitgespeicherte Sortierung, Name. Kommt der Suchzustand aus einer
// gespeicherten Suche ('state-load' mit `folder`), wird der Dialog zur
// Pflege: Überschreiben, Als neue Suche speichern, Umbenennen (Name ändern +
// Überschreiben), Löschen. Gespeichert wird weiter NUR der kanonische
// Ausdruckstext — die Chips sind Ansicht, nicht Speicherformat.

import { STRINGS } from "./strings.js";
import { createFolder, updateFolder, deleteFolder } from "./api.js";
import { emit, on } from "./main.js";
import { chipText } from "./search.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export function initSaveDialog() {
  // Kontext: aus WELCHER gespeicherten Suche kam der aktuelle Zustand?
  // Bleibt beim Chip-Bearbeiten erhalten (genau dafür ist das Laden da) und
  // endet, wenn der Zustand geleert oder verlassen wird.
  let folder = null;
  let current = null;   // Zustand beim Öffnen: {expression, predicates, sort, total}

  const overlay = document.createElement("div");
  overlay.id = "savedlg";
  overlay.className = "pickoverlay";
  overlay.hidden = true;
  document.body.appendChild(overlay);

  function close() {
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
    overlay.innerHTML = `
      <div class="pickbox savebox">
        <div class="pickhead">
          <b>${esc(folder ? STRINGS.saveDlgEditTitle : STRINGS.saveDlgTitle)}</b>
          ${folder ? `<span class="pickpath">»${esc(folder.name)}«</span>` : ""}
        </div>
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
               value="${esc(folder ? folder.name : "")}">
        <span class="sderr" hidden></span>
        <div class="sdactions">
          ${folder ? `
            <button type="button" class="sdprimary" data-act="overwrite">${STRINGS.saveDlgOverwrite}</button>
            <button type="button" data-act="createnew">${STRINGS.saveDlgSaveAsNew}</button>
            <button type="button" class="sddelete" data-act="delete">${STRINGS.saveDlgDelete}</button>
          ` : `
            <button type="button" class="sdprimary" data-act="create">${STRINGS.saveDlgCreate}</button>
          `}
          <button type="button" data-act="cancel">${STRINGS.saveDlgCancel}</button>
        </div>
      </div>`;
    const name = overlay.querySelector(".sdname");
    name.focus();
    name.select();
  }

  async function act(action) {
    const name = overlay.querySelector(".sdname").value.trim();
    if (action !== "delete" && !name) {
      showError(STRINGS.saveDlgNoName);
      return;
    }
    try {
      if (action === "create" || action === "createnew") {
        const d = await createFolder(name, current.expression);
        folder = { id: d.id, name };   // ab jetzt wird DIESE Suche bearbeitet
      } else if (action === "overwrite") {
        await updateFolder(folder.id, name, current.expression);
        folder = { ...folder, name };
      } else if (action === "delete") {
        // Zweistufig statt confirm(): erster Klick fragt, zweiter löscht.
        const btn = overlay.querySelector(".sddelete");
        if (!btn.dataset.armed) {
          btn.dataset.armed = "1";
          btn.textContent = STRINGS.saveDlgDeleteConfirm;
          return;
        }
        await deleteFolder(folder.id);
        folder = null;
      }
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
      act(folder ? "overwrite" : "create");
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !overlay.hidden) close();
  });

  // -- Bus ------------------------------------------------------------------

  on("save-dialog-open", (d) => {
    current = d;
    overlay.hidden = false;
    render();
  });

  // Kontext-Pflege: Laden setzt ihn, Leeren/Verlassen beendet ihn.
  on("state-load", (d) => { folder = d.folder || null; });
  on("state-clear", () => { folder = null; });
  on("source-changed", (d) => { if (d?.kind === "dupes") folder = null; });
  on("search-state-changed", (d) => { if (!d.expression) folder = null; });
}
