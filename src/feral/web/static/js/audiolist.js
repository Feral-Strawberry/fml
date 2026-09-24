// audiolist.js — Zeilen der Audioansicht (A2 #159, Player A5 #162).
//
// Die Audioansicht ist dieselbe virtualisierte Galerie (gallery.js) mit
// einer Spalte: gallery.js fragt hier nur nach dem Zeilen-HTML (rowHtml)
// und lässt den Wiedergabe-Zustand malen (paintRow). Auswahl, Nachladen,
// Rücksprung, Ablehnen und Bewerten laufen über die bewährten Wege der
// Galerie — keine zweite Listenlogik.
//
// Wiedergabe: player.js (ein <audio>, eigener Abspielkopf je Zeile,
// Lautheitsangleich, Abspielleiste). Hier: die Wellenform jeder Zeile auf
// der GEMEINSAMEN Zeitachse (längste Dauer der Treffermenge, ADR 0087),
// Lineal im Listenkopf, Tasten der Liste und „Alle abspielen".

import { STRINGS } from "./strings.js";
import { canPlay, fmtDuration, libraryView } from "./api.js";
import { dotsHtml } from "./curate.js";
import { galleryItemAt, galleryTotal, listComparing } from "./gallery.js";
import { emit, on } from "./main.js";
import {
  analysisOf, currentHash, isFailed, matchOn, nudge, onRepaint, overrideMatch, paintWave, playAll,
  playingHash, seek, toggle, toggleMatch,
} from "./player.js";
import { rulerTicks } from "./waveform.js";
import { commentsOf, seedComments } from "./comments.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Höchstzahl für „Alle abspielen" (≈ zwei Wochen Musik am Stück).
const PLAY_ALL_CAP = 5000;
// Vergleich in der Liste (A7): so viele markierte Songs.
export const CMP_MIN = 2;
export const CMP_MAX = 6;

/** Dateiname → {stem, ext}; ext ohne Punkt, leer ohne Endung. */
export function splitName(name) {
  const n = String(name || "");
  const dot = n.lastIndexOf(".");
  return dot > 0 ? { stem: n.slice(0, dot), ext: n.slice(dot + 1) } : { stem: n, ext: "" };
}

/** Länge des mit der Vorzeile gemeinsamen Anfangs, der abgedunkelt wird
 *  (Optik-Referenz A0): erst ab 8 gleichen Zeichen (Groß/klein egal), auf
 *  die letzte Wortgrenze (Leerzeichen, -, _) davor gekürzt, damit nie ein
 *  Wort zerschnitten wird; der Rest bleibt nie leer. 0 = nichts abdunkeln. */
export function commonPrefix(a, b) {
  if (!a || !b) return 0;
  let k = 0;
  while (k < a.length && k < b.length && a[k].toLowerCase() === b[k].toLowerCase()) k++;
  k = Math.min(k, a.length - 1);
  if (k < 8) return 0;
  const cut = Math.max(a.lastIndexOf(" ", k), a.lastIndexOf("-", k), a.lastIndexOf("_", k));
  return cut > 0 ? cut + 1 : 0;
}

/** Innenleben einer Listenzeile (Kachel mit Klasse .arow). `prev` = Item der
 *  Vorzeile (gemeinsamer Anfang), undefined am Anfang oder beim Nachladen. */
export function rowHtml(item, prev) {
  const { stem, ext } = splitName(item.name || item.file_hash.slice(0, 12));
  const p = commonPrefix(stem, prev ? splitName(prev.name).stem : "");
  const who = item.model || item.tool || "";
  const whoTitle = [item.tool, item.model].filter(Boolean).join(" · ");
  const playable = canPlay(item);
  seedComments(item.file_hash, item.comments);   // Zeitkommentare kommen mit der Zeile (#163)
  return `
    <div class="rtop">
      <button type="button" class="pbtn"${playable ? "" : " disabled"}
              title="${esc(playable ? STRINGS.audioPlay : STRINGS.audioUnplayable)}">▶</button>
      <div class="rname" title="${esc(item.name || "")}">${item.cover || item.artwork ? `<img class="rcov" alt="" title="${esc(item.cover ? STRINGS.coverFinalTitle : STRINGS.artworkTitle)}">` : ""}<span class="pre">${esc(stem.slice(0, p))}</span><b>${esc(stem.slice(p))}</b>${ext ? `<span class="ext">.${esc(ext)}</span>` : ""}</div>
      <span class="rtool" title="${esc(whoTitle)}">${esc(who)}</span>
      <span class="rdur">${fmtDuration(item.duration)}</span>
      <span class="rlufs" title="${esc(STRINGS.listColLoudnessTitle)}"></span>
      <span class="rdots">${dotsHtml(item.rating)}</span>
      <span class="rcom" title="${esc(STRINGS.listColCommentsTitle)}"></span>
    </div>
    <div class="wv" title="${esc(STRINGS.audioSeek)}"><canvas></canvas><span class="loopr" hidden></span><span class="ph" hidden></span></div>`;
}

// -- Gemeinsame Zeitachse + Listenkopf ------------------------------------------------

let axis = 0;   // Sekunden der vollen Wellenbreite (0 = unbekannt: je Zeile die eigene Dauer)

/** Spaltenköpfe der Liste mit Lineal der gemeinsamen Zeitachse. */
export function listHeadHtml() {
  return `<div class="cmpnote" hidden></div><span></span><span class="mlabel">${STRINGS.listColName}</span>
    <span class="mlabel h-tool">${STRINGS.listColTool}</span>
    <span class="mlabel num">${STRINGS.listColDuration}</span>
    <span class="mlabel num h-lufs">${STRINGS.listColLoudness}</span>
    <span class="mlabel num">${STRINGS.listColRating}</span>
    <span class="mlabel num" title="${esc(STRINGS.listColCommentsTitle)}">💬</span>
    <div class="wlegend" title="${esc(STRINGS.waveLegendTitle)}">
      <span><i class="lo"></i><b>${STRINGS.waveLow}</b> ${STRINGS.waveLowHint}</span>
      <span><i class="mid"></i><b>${STRINGS.waveMid}</b> ${STRINGS.waveMidHint}</span>
      <span><i class="hi"></i><b>${STRINGS.waveHigh}</b> ${STRINGS.waveHighHint}</span></div>
    <div class="ruler">${rulerHtml()}</div>`;
}

function rulerHtml() {
  return axis > 0
    ? rulerTicks(axis).map((t) => `<span style="left:${(t / axis) * 100}%">${fmtDuration(t)}</span>`).join("")
    : "";
}

/** Sekunden der gemeinsamen Zeitachse (0 = unbekannt). */
export const timeAxis = () => axis;

/** Gemeinsame Zeitachse setzen (gallery.js mit der ersten Seite:
 *  max_duration der Treffermenge) — Lineal und alle Wellen folgen. */
export function setTimeAxis(sec) {
  const next = sec > 0 ? sec : 0;
  if (next === axis) return;
  axis = next;
  const r = document.querySelector("#listhead .ruler");
  if (r) r.innerHTML = rulerHtml();
  document.querySelectorAll("#grid .arow[data-hash]").forEach(paintRow);
}

// -- Wiedergabe-Zustand malen ------------------------------------------------------------

/** Wiedergabe-Zustand einer Zeile malen (Knopf, Hervorhebung, Welle, Lautheit). */
export function paintRow(el) {
  const hash = el.dataset.hash;
  if (!hash) return;
  const on = playingHash() === hash;
  el.classList.toggle("playing", on);
  el.classList.toggle("current", currentHash() === hash);
  const btn = el.querySelector(".pbtn");
  if (btn) {
    const bad = isFailed(hash);
    btn.disabled = bad;
    btn.textContent = on ? "❚❚" : "▶";
    btn.title = bad ? STRINGS.audioPlayFailed : on ? STRINGS.audioPause : STRINGS.audioPlay;
  }
  const dur = parseFloat(el.dataset.dur) || 0;
  paintWave(el.querySelector(".wv"), hash, { axis, duration: dur });
  const rc = el.querySelector(".rcom");
  if (rc) {
    const n = commentsOf(hash).length;
    rc.textContent = n ? String(n) : "–";
    rc.classList.toggle("has", n > 0);
  }
  const a = analysisOf(hash);
  const l = el.querySelector(".rlufs");
  if (l) {
    const v = a?.loudness?.integrated;
    l.textContent = v == null ? (a === false ? "–" : "") : v.toLocaleString(STRINGS.locale,
      { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  }
}

/** Zeile(n) eines Songs bzw. alle sichtbaren neu malen (player.onRepaint). */
function repaintRows(hash) {
  const sel = hash ? `#grid .arow[data-hash="${hash}"]` : "#grid .arow[data-hash]";
  document.querySelectorAll(sel).forEach(paintRow);
}

// -- Bedienung aus gallery.js ----------------------------------------------------------------

/** ▶/❚❚ einer Zeile. */
export function togglePlay(item) {
  if (item && canPlay(item)) toggle(item);
}

/** Klick auf die Wellenfläche: `fraction` der vollen Breite = Stelle auf der
 *  gemeinsamen Zeitachse; hinter dem Songende passiert nichts. */
export function seekTo(item, fraction) {
  if (!item || !canPlay(item)) return;
  const dur = item.duration || 0;
  const span = axis > 0 ? Math.max(axis, dur) : dur;
  if (!span) return togglePlay(item);
  const sec = Math.max(0, Math.min(1, fraction)) * span;
  if (dur && sec > dur) return;
  seek(item, sec);
}

/** Klick auf einen Kommentar-Pin: genau an seine Stelle (#163). */
export function seekAt(item, sec) {
  if (item && canPlay(item)) seek(item, sec);
}

/** Alle abspielen: Reihenfolge der Liste JETZT (eingefroren), bis PLAY_ALL_CAP. */
async function startPlayAll(btn) {
  const n = Math.min(galleryTotal(), PLAY_ALL_CAP);
  if (!n) return;
  btn.disabled = true;
  const items = [];
  try {
    for (let i = 0; i < n; i++) {
      const it = await galleryItemAt(i);
      if (it && canPlay(it)) items.push(it);
    }
  } finally { btn.disabled = false; }
  playAll(items);
}

export function initAudioList() {
  onRepaint(repaintRows);

  // „Alle abspielen" in der Kopfzeile der Mitte, nur in der Audioansicht.
  const allBtn = document.getElementById("playAllBtn");
  if (allBtn) {
    allBtn.textContent = `▶ ${STRINGS.audioPlayAll}`;
    allBtn.title = STRINGS.audioPlayAllTitle;
    allBtn.hidden = libraryView() !== "audio";
    allBtn.addEventListener("click", () => startPlayAll(allBtn));
    on("library-view-changed", (d) => { allBtn.hidden = d.view !== "audio"; });
  }
  // Neue Ansicht: die Zeitachse kommt mit der ersten Seite neu.
  on("library-view-changed", () => { axis = 0; });

  initListCompare(allBtn);

  // Tasten der Liste: Leertaste = Play/Pause der ausgewählten Zeile (statt
  // Lupe, loupe.js), ←/→ = ±5 s ihres Abspielkopfs (Shift ±1 s).
  let sel = null;
  on("selection-changed", (d) => { sel = d.index ?? null; });
  on("items-reloaded", () => { sel = null; });
  document.addEventListener("keydown", async (e) => {
    const key = e.key;
    if ((key !== " " && key !== "ArrowLeft" && key !== "ArrowRight") || libraryView() !== "audio") return;
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.target instanceof Element && e.target.matches("input, textarea, select")) return;
    // Ein geklickter Knopf behält den Fokus — die Leertaste löste ihn sonst
    // erneut aus (⏮, ≈ Lautheit, Sortierung …) statt Play/Pause. Sie gehört
    // hier immer der Wiedergabe; Knöpfe per Tastatur löst Enter aus.
    if (e.target instanceof Element && e.target.localName === "button") e.target.blur();
    for (const id of ["loupe", "single", "rankings", "compare"]) {
      if (!document.getElementById(id)?.hidden) return;
    }
    e.preventDefault();
    if (sel === null) return;
    const item = await galleryItemAt(sel);
    if (!item || !canPlay(item)) return;
    if (key === " ") togglePlay(item);
    else nudge(item, (e.shiftKey ? 1 : 5) * (key === "ArrowRight" ? 1 : -1));
  });
}

// -- Vergleich in der Liste (A7 #164, ADR 0089) ---------------------------------------
//
// Die Liste selbst engt sich ein (gallery.js); hier sitzen Knopf, Tasten,
// Hinweiszeile und der eigene Lautheitsangleich des Vergleichs (Standard an,
// die gemerkte Einstellung kehrt mit Esc zurück). Bewerten, Ablehnen, K,
// Leertaste und ←/→ laufen über die Wege der Liste.

const OVERLAYS = ["loupe", "single", "rankings", "compare"];
const overlayOpen = () => OVERLAYS.some((id) => document.getElementById(id)?.hidden === false);
const typing = (e) => e.target instanceof Element && e.target.matches("input, textarea, select, [contenteditable]");
// Popover mit eigenem Esc (Sortierung, + Kriterium, Tipphilfe) schließen zuerst.
const popoverOpen = () => ["sortmenu", "addcrit", "typeahead"]
  .some((id) => document.getElementById(id)?.hidden === false);

function initListCompare(allBtn) {
  const btn = document.getElementById("listCmpBtn");
  const end = document.getElementById("listCmpEnd");
  const match = document.getElementById("listCmpMatch");
  if (!btn || !end || !match) return;
  const box = match.querySelector("input");
  match.querySelector("span").textContent = STRINGS.listCmpMatch;
  match.title = STRINGS.audioMatchTitle;
  end.textContent = `✕ ${STRINGS.listCmpEnd}`;
  end.title = STRINGS.listCmpEndTitle;
  let marked = 0;

  const note = () => document.querySelector("#listhead .cmpnote");
  function paint() {
    const n = listComparing();
    const audio = libraryView() === "audio";
    btn.hidden = !audio || !!n || marked < CMP_MIN;
    btn.disabled = marked > CMP_MAX;
    btn.textContent = marked > CMP_MAX ? `⇆ ${STRINGS.listCmpMax}` : `⇆ ${STRINGS.listCmp} (${marked})`;
    btn.title = marked > CMP_MAX ? STRINGS.listCmpMaxTitle : STRINGS.listCmpTitle;
    end.hidden = match.hidden = !n;
    if (allBtn) allBtn.hidden = !audio || !!n;
    box.checked = matchOn();
    match.classList.toggle("on", box.checked);
    const el = note();
    if (el) {
      el.hidden = !n;
      const html = n ? `<span>${STRINGS.listCmpNote.replace("{n}", n)}</span>`
        + `<span class="cmpgain">${matchOn() ? STRINGS.listCmpGainOn : STRINGS.listCmpGainOff}</span>` : "";
      if (el._html !== html) { el._html = html; el.innerHTML = html; }   // läuft mit jedem Neuzeichnen
    }
  }

  const start = () => emit("list-compare-set", { on: true });
  btn.addEventListener("click", start);
  end.addEventListener("click", () => emit("list-compare-set", { on: false }));
  box.addEventListener("change", () => { if (box.checked !== matchOn()) toggleMatch(); });
  // Der Angleich kann auch in der Abspielleiste umschalten: Zustand nachziehen.
  onRepaint(() => { if (listComparing()) paint(); });

  on("selection-changed", (d) => {
    if (!listComparing()) marked = (d.hashes ?? (d.hash ? [d.hash] : [])).length;
    paint();
  });
  on("items-reloaded", () => { marked = 0; paint(); });
  on("library-view-changed", () => { marked = 0; overrideMatch(null); paint(); });
  on("list-compare-changed", (d) => {
    overrideMatch(d.on ? true : null);   // im Vergleich standardmäßig angeglichen
    paint();
  });

  // C = vergleichen (2 bis 6 markierte Songs); der Bildvergleich (compare.js)
  // steigt in der Audioansicht aus.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "c" && e.key !== "C") return;
    if (e.altKey || e.ctrlKey || e.metaKey || typing(e) || overlayOpen()) return;
    if (libraryView() !== "audio" || listComparing()) return;
    if (marked < CMP_MIN || marked > CMP_MAX) return;
    e.preventDefault();
    start();
  });
  // Esc beendet den Vergleich — in der Capture-Phase, damit es nicht zugleich
  // die Filter zurücksetzt (search.js). Offene Dialoge fängt der Dialog-Stapel
  // davor ab (overlays.js), Popover und Eingaben behalten ihr Esc.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !listComparing()) return;
    if (typing(e) || overlayOpen() || popoverOpen() || document.getElementById("comprompt")) return;
    e.stopPropagation();
    e.preventDefault();
    emit("list-compare-set", { on: false });
  }, true);
}
