// status.js — geteilter Poller für /api/status (ADR 0074, Punkt 3).
//
// Galerie UND Admin sind eigene Dokumente; beide brauchen denselben Blick
// auf die Engine: Was läuft, was wartet, lebt der Worker? Dieses Modul
// pollt EINMAL je Dokument (700 ms — der Endpunkt ist billig, Zustand im
// Speicher) und verteilt das Ergebnis:
//
//   onStatus(fn)        — jeder Poll (Widget, Seiten, Topbar-Badge)
//   onTaskFinished(fn)  — eine Aufgabe ist fertig geworden: Flanke
//                         laufend→leer ODER finished_seq hat sich geändert
//                         (auch wenn die Flanke zwischen zwei Polls lag,
//                         schneller Ein-Datei-Import). Vergleich über die
//                         laufende Nummer, NICHT über das Label-Objekt —
//                         Meldungs-Dicts sind bei jedem Poll neue Objekte.
//   startStatusPolling({ onIdle })
//                       — onIdle feuert, wenn die Engine LEER ist und seit
//                         dem letzten Poll etwas fertig wurde: Flanke
//                         laufend→leer ODER finished_seq geändert (#32: ein
//                         Ein-Datei-Scan aus dem Watchordner liegt komplett
//                         zwischen zwei Polls — ohne die Nummer sah die
//                         Galerie nie eine Flanke und frischte nie auf).
//                         Nicht mitten in einer Warteschlange: dort bleibt
//                         es bei EINEM Refresh am Ende. Die Galerie macht
//                         daraus den Bus-Event 'engine-idle' (Grid/Sidebar/
//                         Zähler laden neu).
//
// Kein Import von main.js: das Modul muss in beiden Dokumenten laufen.

import { getStatus } from "./api.js";
import { STRINGS } from "./strings.js";
import { serverMsg } from "./servermsg.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const statusListeners = new Set();
const finishedListeners = new Set();
const idleListeners = new Set();
let timer = null;
let lastBusy = false;
let lastSeq = null;       // null = noch kein Poll (erster Poll ist keine Flanke)
let lastStatus = null;

/** Läuft etwas oder wartet etwas? */
export const isBusy = (s) => !!(s && (s.running || s.queue_pending > 0));

/** Zuletzt gesehener Status (null vor dem ersten Poll). */
export const lastKnownStatus = () => lastStatus;

export function onStatus(fn) {
  statusListeners.add(fn);
  if (lastStatus) fn(lastStatus);
  return () => statusListeners.delete(fn);
}

export function onTaskFinished(fn) {
  finishedListeners.add(fn);
  return () => finishedListeners.delete(fn);
}

/** Ein Poll; bei Netzfehler null (nichts wird ausgelöst). */
export async function pollOnce() {
  let s;
  try { s = await getStatus(); } catch { return null; }
  const busy = isBusy(s);
  const idleEdge = lastBusy && !busy;
  const seq = s.finished_seq || 0;
  const finished = idleEdge || (lastSeq !== null && seq !== lastSeq);
  const idleNow = finished && !busy;   // leer UND etwas ist fertig geworden
  lastBusy = busy;
  lastSeq = seq;
  lastStatus = s;
  for (const fn of statusListeners) fn(s);
  if (idleNow) for (const fn of idleListeners) fn(s);
  if (finished) for (const fn of finishedListeners) fn(s);
  return s;
}

export function startStatusPolling({ interval = 700, onIdle = null } = {}) {
  if (onIdle) idleListeners.add(onIdle);
  if (timer) return;
  timer = setInterval(pollOnce, interval);
  pollOnce();
}

// -- Topbar-Badge der Galerie -------------------------------------------------
//
// Zeigt in Kurzform, was das Admin-Widget ausführlich zeigt: laufende bzw.
// erste wartende Aufgabe (+N wartend), toter Worker rot, sonst „beobachtet"
// wenn Watchordner aktiv sind. Das Element ist ein Link nach /admin.

export function badgeHtml(s) {
  const watchingAny = (s.watchers || []).length > 0;
  const busy = isBusy(s);
  const dead = s.worker_alive === false;
  // Label ist seit Block M.2 ein Meldungs-Dict {key, params} → serverMsg()
  // (#63: vorher stand hier „[object Object]").
  const label = s.running ? serverMsg(s.label) : serverMsg((s.queue || [])[0]);
  if (busy) {
    return `<span class="actdot${dead ? " dead" : ""}"></span>${esc(label || STRINGS.activityRunning)}`
      + (s.queue_pending ? ` <span class="actqueue">+${s.queue_pending}</span>` : "");
  }
  if (dead) return `<span class="actdot dead"></span>${STRINGS.activityWorkerDead}`;
  if (watchingAny) return `<span class="actdot idle"></span>${STRINGS.activityWatching}`;
  return "";
}

export function initActivityBadge(el) {
  el.title = STRINGS.tooltipActivity;
  onStatus((s) => {
    const html = badgeHtml(s);
    el.hidden = !html;
    el.innerHTML = html;
    el.classList.toggle("dead", s.worker_alive === false);
  });
}
