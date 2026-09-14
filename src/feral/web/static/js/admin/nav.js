// admin/nav.js — Seitennavigation, Navi-Zähler, Aktivitäts-Widget und
// Dokumenttitel des Admin-Dokuments (ADR 0074). Eigenes Modul (nicht in
// main.js), damit Seiten es importieren können, ohne den Einstieg zu
// importieren.

import { STRINGS } from "../strings.js";
import { serverMsg } from "../servermsg.js";
import { applyInstance } from "../appearance.js";
import { esc, fmtElapsed, fmtNum, tpl } from "./util.js";

export const TITLE = `${STRINGS.adminBrand} — Feral Media Library`;
let instance = null;   // {name, farbe} aus /api/stats

export function initNav(pages) {
  document.getElementById("adBackLabel").textContent = STRINGS.adminBack;
  document.getElementById("brandSub").textContent = STRINGS.adminBrand;
  document.getElementById("navlist").innerHTML = pages.map((p) => `
    <a href="/admin/${p.id}" data-page="${p.id}">${p.icon}<span>${esc(p.title())}</span>
      <span class="cnt mute" id="navCnt-${p.id}" hidden></span></a>`).join("");
  document.getElementById("actw").title = STRINGS.widgetTitle;
}

export function markActive(pageId) {
  for (const a of document.querySelectorAll("#navlist a")) {
    a.classList.toggle("on", a.dataset.page === pageId);
  }
}

/** Navi-Zähler einer Seite setzen (null/undefined = verstecken). */
export function setNavCount(pageId, n) {
  const el = document.getElementById(`navCnt-${pageId}`);
  if (!el) return;
  el.hidden = n == null;
  el.textContent = n == null ? "" : fmtNum(n);
}

/** Schema-Version + Port unten in der Navi. */
export function setNavMeta(text) {
  document.getElementById("navMeta").textContent = text;
}

/** Instanz (Name/Akzent/Favicon) anwenden und Titel setzen. */
export function setInstance(inst, pageTitle) {
  instance = inst || null;
  setDocumentTitle(pageTitle);
}

export function setDocumentTitle(pageTitle) {
  applyInstance(instance, {
    badge: document.getElementById("navInstance"),
    title: pageTitle ? `${pageTitle} · ${TITLE}` : TITLE,
    badgeTitle: STRINGS.instanceBadgeTitle,
  });
}

// -- Aktivitäts-Widget (unten in der Navi) --------------------------------------

export function progressPercent(s) {
  const cf = s.current_file && s.current_file.params;
  const r = s.report || {};
  const total = r.scanned_files || 0;
  if (cf && cf.total) return Math.min(100, Math.round((cf.index / cf.total) * 100));
  if (total) return Math.min(100, Math.round((((r.media_files || 0) + (r.skipped_unknown || 0)) / total) * 100));
  return 0;
}

export function renderWidget(s) {
  const dot = document.getElementById("wDot");
  const task = document.getElementById("wTask");
  const count = document.getElementById("wCount");
  const right = document.getElementById("wRight");
  const bar = document.getElementById("wBar");
  const dead = s.worker_alive === false;
  const cf = s.current_file && s.current_file.params;
  const total = (s.report || {}).scanned_files || 0;
  const queued = s.queue_pending ? tpl(STRINGS.widgetQueued, { n: s.queue_pending }) : "";
  if (s.running) {
    dot.className = "dot";
    task.textContent = serverMsg(s.label) || STRINGS.activityRunning;
    count.textContent = cf && cf.total ? `${fmtNum(cf.index)} / ${fmtNum(cf.total)}`
      : total ? fmtNum(total) : "";
    right.textContent = [s.elapsed != null ? fmtElapsed(s.elapsed) : "", queued].filter(Boolean).join(" · ");
    bar.style.width = `${progressPercent(s)}%`;
  } else if (dead) {
    dot.className = "dot dead";
    task.textContent = STRINGS.activityWorkerDead;
    count.textContent = "";
    right.textContent = queued;
    bar.style.width = "0%";
  } else if (s.queue_pending) {
    dot.className = "dot warn";
    task.textContent = serverMsg((s.queue || [])[0]) || STRINGS.statusQueued;
    count.textContent = "";
    right.textContent = queued;
    bar.style.width = "0%";
  } else {
    dot.className = "dot idle";
    const n = (s.watchers || []).length;
    task.textContent = n ? tpl(STRINGS.widgetWatching, { n }) : STRINGS.widgetIdle;
    count.textContent = s.last_finished ? `${STRINGS.statusLast} ${serverMsg(s.last_finished)}` : "";
    right.textContent = "";
    bar.style.width = "0%";
  }
  setNavCount("sources", (s.watchers || []).length || null);
}
