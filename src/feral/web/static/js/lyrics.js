// Songtext mit Zeiten (#234): Suno V6 schreibt den Songtext Zeile für Zeile
// mit Zeiten in eine Untertitel-Spur (Schicht 2: lyrics_synced / song_sections).
//
// - **Abschnitte** ([Chorus], [Verse] …) kommen mit der Listenzeile und
//   stehen als schmale Marke oben auf der Welle (paintSections).
// - **Die aktuelle Zeile** steht klein mittig unter der Welle der
//   Abspielleiste (lineAt), mit dem Abschnitt davor.
// - **Im Panel** läuft der Songtext mit, wenn der Abschnitt GENERATION offen
//   ist; ein Klick auf eine Zeile springt dorthin (followPanel).
//
// Die Zeilen holt /api/audio/lyrics/<hash> einmal je Song, erst wenn er
// gespielt oder im Panel gezeigt wird.

import { playAt, repaint } from "./player.js";

const lines = new Map();      // Hash → [[start_ms, end_ms|null, "Zeile"], …] ([] = keine)
const sections = new Map();   // Hash → [[start_ms, "Chorus"], …]
const pending = new Set();
const CACHE_CAP = 200;
const GAP_MS = 1500;          // so lange bleibt eine Zeile nach ihrem Ende stehen
// Höchstens so lange, wie man eine Zeile ungefähr singt: Suno setzt das
// Ende der letzten Zeile eines Abschnitts auf die nächste gesungene Zeile,
// über Solo und Bridge hinweg (Befund bei einem schnellen Song: ~9 s zu lang).
const SHOW_BASE_MS = 2500;
const SHOW_PER_WORD_MS = 700;
const maxShowMs = (text) => SHOW_BASE_MS + SHOW_PER_WORD_MS * text.split(/\s+/).filter(Boolean).length;

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const SECTION = /^\[([^[\]]{1,40})\]$/;
export const isSection = (text) => SECTION.test(text);

/** Abschnitte aus der Listenzeile übernehmen (nur wo es welche gibt). */
export function seedSections(hash, secs) {
  if (Array.isArray(secs) && secs.length) sections.set(hash, secs);
}

export const sectionsOf = (hash) => sections.get(hash) || [];

/** Zeilen eines Songs (lädt beim ersten Aufruf nach; bis dahin null). */
export function linesOf(hash) {
  if (lines.has(hash)) return lines.get(hash);
  if (!pending.has(hash)) {
    pending.add(hash);
    fetch(`/api/audio/lyrics/${hash}`)
      .then((r) => (r.ok ? r.json() : { lines: [] }))
      .catch(() => ({ lines: [] }))
      .then((d) => {
        pending.delete(hash);
        if (lines.size >= CACHE_CAP) lines.delete(lines.keys().next().value);
        lines.set(hash, Array.isArray(d?.lines) ? d.lines : []);
        // Abschnitte vom Server: Solo-Marken stehen dort schon an ihrer
        // geschätzten Stelle (Suno setzt sie ans Ende des Solos).
        seedSections(hash, d?.sections);
        repaint(hash);
      });
  }
  return null;
}

/** Index der Zeile, die bei `sec` gerade läuft (-1: keine). Abschnittszeilen
 *  zählen mit (das Panel zeigt sie als Überschrift). */
export function indexAt(list, sec) {
  const ms = sec * 1000;
  let at = -1;
  for (let i = 0; i < list.length && list[i][0] <= ms; i++) at = i;
  return at;
}

/** Index der Textzeile, die bei `sec` gerade gesungen wird (-1: Pause).
 *  Eine Zeile endet mit ihrem Ende (plus Nachlauf), spätestens nach ihrer
 *  ungefähren Singdauer, und sofort, wenn danach ein neuer Abschnitt
 *  begonnen hat. */
export function activeIndex(list, sec) {
  const i = indexAt(list, sec);
  if (i < 0) return -1;
  const [start, end, t] = list[i];
  if (isSection(t)) return -1;
  const until = Math.min(end == null ? Infinity : end + GAP_MS, start + maxShowMs(t));
  return sec * 1000 <= until ? i : -1;
}

/** Panel: die gesungene Zeile; ist keine aktiv (Solo, Pause), die
 *  Überschrift des laufenden Abschnitts. Die Abschnitte (geschätzte Starts)
 *  stehen in derselben Reihenfolge wie die Klammerzeilen der Liste. */
export function panelIndex(hash, list, sec) {
  const i = activeIndex(list, sec);
  if (i >= 0) return i;
  let k = -1;
  sectionsOf(hash).forEach(([ms], n) => { if (ms <= sec * 1000) k = n; });
  if (k < 0) return -1;
  for (let j = 0, n = -1; j < list.length; j++) {
    if (isSection(list[j][2]) && ++n === k) return j;
  }
  return -1;
}

/** Aktuelle Textzeile + Abschnitt bei `sec` — für die Abspielleiste.
 *  In Pausen (Solo, Bridge ohne Text) bleibt die Zeile leer. */
export function lineAt(hash, sec) {
  const list = linesOf(hash);
  if (!list || !list.length) return null;
  const ms = sec * 1000;
  const i = activeIndex(list, sec);
  const text = i >= 0 ? list[i][2] : "";
  let section = "";
  for (const [start, name] of sectionsOf(hash)) {
    if (start <= ms) section = name; else break;
  }
  return { text, section };
}

/** Abschnittsmarken (oben auf der Welle) malen; `axis` = Sekunden der Breite.
 *  `pos` (Sekunden, nur beim geladenen Song): der Abschnitt, in dem der
 *  Abspielkopf steht, kommt ganz und vorn (wie die Kommentare an ihrer
 *  Stelle) — auch wenn er sonst gekürzt ist. */
export function paintSections(wv, hash, axis, pos = null) {
  if (!wv) return;
  const secs = sectionsOf(hash);
  let box = wv.querySelector(".secs");
  if (!box) {
    if (!secs.length) return;
    box = document.createElement("span");
    box.className = "secs";
    wv.appendChild(box);
  }
  const key = `${hash}|${axis}|${secs.map((s) => s.join(":")).join(",")}`;
  if (box._key !== key) {
    box._key = key;
    box._on = null;
    renderSections(box, secs, axis);
  }
  let on = -1;
  if (pos !== null) secs.forEach(([ms], i) => { if (ms <= pos * 1000) on = i; });
  if (box._on === on) return;
  box._on = on;
  box.querySelectorAll(".sec").forEach((el, i) => el.classList.toggle("on", i === on));
}

function renderSections(box, secs, axis) {
  // Jede Beschriftung höchstens bis zur nächsten Marke (sonst schrieben sich
  // dicht liegende Abschnitte übereinander: „ChorChorus“); der volle Name
  // steht im Tooltip.
  const pct = (ms) => Math.min(100, (ms / 1000 / axis) * 100);
  box.innerHTML = axis > 0
    ? secs.map(([ms, name], i) => {
      const x = pct(ms);
      const room = (i + 1 < secs.length ? pct(secs[i + 1][0]) : 100) - x;
      return `<span class="sec" style="left:${x}%;max-width:min(90px, ${room.toFixed(2)}%)" title="${esc(name)}"><i>${esc(name)}</i></span>`;
    }).join("")
    : "";
}

/** Songtext-Zeilen fürs Panel (GENERATION): Abschnitte als Überschrift. */
export function panelLinesHtml(hash, list) {
  return `<div class="vblock lysync" data-hash="${esc(hash)}">${list.map(([ms, , t]) =>
    `<div class="lyl${isSection(t) ? " lysec" : ""}" data-t="${ms / 1000}">${esc(t)}</div>`).join("")}</div>`;
}

/** Panel mitlaufen lassen: aktuelle Zeile hervorheben und im Kasten sichtbar
 *  halten. Eingeklappt (#219) ist der Kasten unsichtbar — dann nichts tun. */
export function followPanel(hash, sec) {
  const box = document.querySelector(`#panel .lysync[data-hash="${hash}"]`);
  if (!box || !box.offsetParent) return;
  const list = linesOf(hash);
  if (!list) return;
  const rows = box.querySelectorAll(".lyl");
  const at = rows.length === list.length ? panelIndex(hash, list, sec) : -1;   // Zeilen = Liste
  if (box._at === at) return;
  box._at = at;
  rows.forEach((r, i) => r.classList.toggle("on", i === at));
  if (at >= 0) box.scrollTop = Math.max(0, rows[at].offsetTop - box.clientHeight / 3);
}

/** Klick auf eine Panel-Zeile: dorthin springen (spielt den Song ab dort). */
export function initLyrics() {
  document.addEventListener("click", (e) => {
    const row = e.target instanceof Element ? e.target.closest(".lysync .lyl") : null;
    if (row) playAt(row.closest(".lysync").dataset.hash, parseFloat(row.dataset.t) || 0);
  });
}
