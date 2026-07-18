// quickmenu.js — Schnellzugriff-Overlay am Admin-Knopf (Vorschlag, 2026-07-07).
//
// Idee aus dem Design-Prototyp (Settings-Popover): Die Admin-Konsole behält
// ihre Untersektionen, aber die wichtigsten Handgriffe sind ohne Seitenwechsel
// erreichbar — Wartungs-Schnellaktionen, Absprung in die Konsole, Theme.
// Klick auf den Topbar-Knopf öffnet das Popover; Esc/Klick daneben schließt.

import { STRINGS } from "./strings.js";
import { getIssues, startRescan, startReparse, clearThumbCache } from "./api.js";
import { emit } from "./main.js";

const THEME_KEY = "feral-theme";

export function initQuickmenu() {
  const btn = document.getElementById("adminBtn");
  const menu = document.createElement("div");
  menu.id = "qmenu";
  menu.hidden = true;
  menu.innerHTML = `
    <div class="qmadmin" data-admin="status">
      <img class="mascot" src="/static/img/feral-strawberry.png" alt="">
      <div class="qmadmintext">
        <div>${STRINGS.qmAdminTitle}</div>
        <div class="qmsub">${STRINGS.qmAdminSub}</div>
      </div>
      <span class="qmarrow">→</span>
    </div>
    <div id="qmIssues" class="qmissues" data-admin="issues" hidden></div>
    <div class="mlabel qmhead">${STRINGS.qmActions}</div>
    <button type="button" data-action="rescan">${STRINGS.maintRescan}</button>
    <button type="button" data-action="reparse">${STRINGS.maintReparse}</button>
    <button type="button" data-action="thumbs">${STRINGS.maintThumbs}</button>
    <div class="mlabel qmhead">${STRINGS.qmAppearance}</div>
    <div class="qmseg">
      <button type="button" data-theme="dark">${STRINGS.qmDark}</button>
      <button type="button" data-theme="light">${STRINGS.qmLight}</button>
    </div>
    <div id="qmMsg" class="qmmsg"></div>
    <div class="qmfoot">Feral Media Library · ${STRINGS.qmFooter}</div>`;
  document.body.appendChild(menu);
  const msg = menu.querySelector("#qmMsg");

  function syncTheme() {
    const light = document.documentElement.dataset.theme === "light";
    for (const b of menu.querySelectorAll("[data-theme]")) {
      b.classList.toggle("active", (b.dataset.theme === "light") === light);
    }
  }

  // Unbearbeitete Probleme direkt im Popover zeigen (Feral Strawberry, 2026-07-09) —
  // Klick springt zur Probleme-Kachel. Billige Abfrage (nur scan_issues),
  // läuft bei jedem Öffnen frisch.
  async function loadIssueHint() {
    const box = menu.querySelector("#qmIssues");
    try {
      const d = await getIssues();
      box.hidden = !d.issues.length;
      box.innerHTML = d.issues.length
        ? `<span class="warn">⚠ ${d.issues.length} ${STRINGS.issuesOpenCount}</span> <span class="qmarrow">→</span>`
        : "";
    } catch { box.hidden = true; }
  }

  function toggle(show) {
    menu.hidden = show === undefined ? !menu.hidden : !show;
    if (!menu.hidden) { msg.textContent = ""; syncTheme(); loadIssueHint(); }
  }

  btn.addEventListener("click", (e) => { e.stopPropagation(); toggle(); });
  document.addEventListener("click", (e) => {
    if (!menu.hidden && !menu.contains(e.target)) toggle(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !menu.hidden) toggle(false);
  });

  menu.addEventListener("click", async (e) => {
    const admin = e.target.closest("[data-admin]");
    if (admin) {
      toggle(false);
      emit("admin-open", { section: admin.dataset.admin });
      return;
    }
    const theme = e.target.closest("[data-theme]");
    if (theme) {
      if (theme.dataset.theme === "light") {
        document.documentElement.dataset.theme = "light";
      } else {
        delete document.documentElement.dataset.theme;
      }
      localStorage.setItem(THEME_KEY, theme.dataset.theme);
      syncTheme();
      return;
    }
    const action = e.target.closest("[data-action]");
    if (!action) return;
    try {
      if (action.dataset.action === "rescan") { await startRescan(); msg.textContent = STRINGS.maintQueued; }
      else if (action.dataset.action === "reparse") { await startReparse(); msg.textContent = STRINGS.maintQueued; }
      else if (action.dataset.action === "thumbs") {
        const r = await clearThumbCache();
        msg.textContent = `${r.deleted} ${STRINGS.maintThumbsCleared}`;
      }
    } catch (err) { msg.textContent = err.message; }
  });
}
