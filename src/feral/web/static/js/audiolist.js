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
import { colorDotsHtml, dotsHtml } from "./curate.js";
import { galleryItemAt, galleryTotal, listComparing } from "./gallery.js";
import { emit, on } from "./main.js";
import {
  analysisOf, btnState, currentHash, currentSong, matchOn, nudge, onRepaint, overrideMatch, paintWave,
  playAll, playingHash, seek, setText, toggle, toggleMatch,
} from "./player.js";
import { rulerTicks } from "./waveform.js";
import { dialogsOpen } from "./overlays.js";
import { commentsOf, seedComments } from "./comments.js";
import { seedSections } from "./lyrics.js";

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

// -- Darstellung: Welle | Angaben (#258) ------------------------------------------------
//
// „Welle" ist die Zeile mit Wellenform (Hören, Vergleichen), „Angaben" die
// flache Zeile mit eigenen Spalten für Titel, Interpret, Album, Nummer, Jahr
// und Genre (Verwalten). gallery.js hält die Wahl und die Zeilenhöhe.

let style = "wave";

export const listStyle = () => style;
export function setListStyle(s) { style = s === "info" ? "info" : "wave"; }
/** Flache Zeilen? Im Vergleich nie: der zeigt immer Wellen. */
export const infoRows = () => style === "info" && !listComparing();

/** Was eine Zeile außer Hash und Bewertung zeigt, für die Zeilen-Signatur. */
export const rowFacts = (item) =>
  [infoRows() ? "i" : "w", listRows(), item.loc?.id, item.loc?.count, item.title, item.artist, item.album, item.track, item.year, item.genre]
    .map((v) => v || "").join("\u0001");

// -- Fundort-Zeilen und Ordnergruppen (ADR 0108) -----------------------------------------
//
// Nur in „Angaben": eine von drei Zeilen-Arten, gewählt über ▾ an ☰
// (Nachtrag ADR 0108). „ordner" = je Fundort eine Zeile, nach Ordnern mit
// Köpfen dazwischen (Standard), „fundorte" = je Fundort eine Zeile in der
// gewählten Sortierung, „songs" = je Song eine Zeile wie zuvor. Gemerkt im
// Browser; kein Suchzustand.

export const ROWS = ["ordner", "fundorte", "songs"];
const ROWS_KEY = "feral-listrows";
let rowsChoice = "ordner";
try {
  const v = localStorage.getItem(ROWS_KEY);
  if (ROWS.includes(v)) rowsChoice = v;
} catch { /* privat */ }

/** Gewählte Zeilen-Art (auch, wenn gerade „Welle" gilt). */
export const rowsKind = () => rowsChoice;
export function setRowsKind(v) {
  rowsChoice = ROWS.includes(v) ? v : "ordner";
  try { localStorage.setItem(ROWS_KEY, rowsChoice); } catch { /* privat */ }
}
/** Gilt gerade eine Fundort-Darstellung? "ordner" | "fundorte" | "" — nur in
 *  „Angaben", nie im Vergleich (der zeigt Wellen und arbeitet mit Songs). */
export const listRows = () => (infoRows() && rowsChoice !== "songs" ? rowsChoice : "");

/** Ordner-Segmente eines Pfads ab `skip`: [{text, path}], `path` = der Ordner
 *  bis einschließlich dieses Segments (Laufwerk „D:" als „D:\"). */
export function folderSegments(path, skip = 0) {
  const out = [];
  let i = skip;
  while (i < path.length) {
    let j = i;
    while (j < path.length && path[j] !== "/" && path[j] !== "\\") j++;
    if (j > i) {
      const upto = path.slice(0, j);
      out.push({ text: path.slice(i, j), path: /^[A-Za-z]:$/.test(upto) ? `${upto}\\` : upto });
    }
    i = j + 1;
  }
  return out;
}

const kindLabels = () => ({ library: STRINGS.locKindLibrary, watch: STRINGS.locKindWatch, extern: STRINGS.locKindExtern });

/** Kopf einer Ordnergruppe: Herkunft, Pfad (Segmente öffnen den Ordner wie im
 *  Panel, #37), Zahl der Zeilen, ⌕ setzt den Chip. Der mit dem vorigen Kopf
 *  gemeinsame Anfang ist abgedunkelt; das letzte Segment nie. */
export function groupRowHtml(group, prev) {
  const library = group.kind === "library";
  const segs = library ? [] : folderSegments(group.path, group.skip);
  let same = 0;
  if (prev && prev.kind === group.kind && !library) {
    const ps = folderSegments(prev.path, prev.skip);
    while (same < segs.length - 1 && same < ps.length
           && ps[same].path.toLowerCase() === segs[same].path.toLowerCase()) same++;
  }
  // Library (ADR 0108 Punkt 3): ein Ordner, ihr Pfad nur als Hinweis (die
  // Datumsordner gehören fml); das Badge sagt schon „Library".
  const path = library ? `<span class="glib">${esc(group.path)}</span>`
    : segs.map((sg, k) => `<a href="#" class="seg${k < same ? " pre" : ""}" data-path="${esc(sg.path)}"
        title="${esc(STRINGS.locOpenFolderTitle)}">${esc(sg.text)}</a>`).join(`<span class="gsep">›</span>`);
  return `
    <div class="rtop gtop">
      <span class="lockind">${esc(kindLabels()[group.kind] || "")}</span>
      <span class="gpath" title="${esc(group.path)}">${path}</span>
      <span class="gerr"></span>
      <span class="gcount">${group.count.toLocaleString(STRINGS.locale)}</span>
      <button type="button" class="gfilter"
              title="${esc(library ? STRINGS.groupFilterLibraryTitle : STRINGS.groupFilterTitle)}">⌕</button>
    </div>`;
}

/** Ordner eines Fundorts für die Spalte „Ordner" (ohne Gruppierung). */
function locFolder(loc) {
  if (loc.kind === "library") return STRINGS.locKindLibrary;
  const cut = Math.max(loc.path.lastIndexOf("/"), loc.path.lastIndexOf("\\"));
  return folderSegments(loc.path.slice(0, Math.max(cut, 0)), loc.skip).map((sg) => sg.text).join(" › ");
}

/** Zeile der Darstellung „Angaben": Titel aus der Datei, sonst der Dateiname;
 *  ohne Interpret stehen Modell oder Tool in der Spalte. */
function infoRowHtml(item) {
  const name = item.name || item.file_hash.slice(0, 12);
  const who = item.artist || item.model || item.tool || "";
  const playable = canPlay(item);
  const cell = (cls, text) => `<span class="${cls}" title="${esc(text || "")}">${esc(text || "")}</span>`;
  return `
    <div class="rtop">
      <button type="button" class="pbtn"${playable ? "" : " disabled"}
              title="${esc(playable ? STRINGS.audioPlay : STRINGS.audioUnplayable)}">▶</button>
      <div class="rname" title="${esc(name)}">${colorDotsHtml(item.colors)}${item.cover || item.artwork ? `<img class="rcov" alt="" title="${esc(item.cover ? STRINGS.coverFinalTitle : STRINGS.artworkTitle)}">` : ""}<b>${esc(item.title || splitName(name).stem)}</b>${item.loc?.count > 1 ? `<span class="rlocs" title="${esc(STRINGS.rowLocsTitle.replace("{n}", item.loc.count))}">⧉${item.loc.count}</span>` : ""}</div>
      ${listRows() === "fundorte" && item.loc ? `<span class="rcell c-folder" title="${esc(item.loc.path)}">${esc(locFolder(item.loc))}</span>` : ""}
      ${cell(item.artist ? "rcell" : "rcell rgen", who)}
      ${cell("rcell c-album", item.album)}
      <span class="rnum c-track">${esc(item.track || "")}</span>
      <span class="rnum c-year">${esc(item.year || "")}</span>
      ${cell("rcell c-genre", item.genre)}
      <span class="rdur">${fmtDuration(item.duration)}</span>
      <span class="rdots">${dotsHtml(item.rating)}</span>
      <span class="rcom" title="${esc(STRINGS.listColCommentsTitle)}"></span>
    </div>`;
}

/** Innenleben einer Listenzeile (Kachel mit Klasse .arow). `prev` = Item der
 *  Vorzeile (gemeinsamer Anfang), undefined am Anfang oder beim Nachladen. */
export function rowHtml(item, prev) {
  seedComments(item.file_hash, item.comments);   // Zeitkommentare kommen mit der Zeile (#163)
  seedSections(item.file_hash, item.sections);   // Songabschnitte ebenso (#234)
  if (infoRows()) return infoRowHtml(item);
  const { stem, ext } = splitName(item.name || item.file_hash.slice(0, 12));
  const p = commonPrefix(stem, prev ? splitName(prev.name).stem : "");
  // Musiksammlung (#224): Interpret · Album aus den Tags, sonst wie bisher
  // der KI-Erzeuger (Modell/Tool).
  const music = [item.artist, item.album].filter(Boolean).join(" · ");
  const who = music || item.model || item.tool || "";
  const whoTitle = music || [item.tool, item.model].filter(Boolean).join(" · ");
  const playable = canPlay(item);
  return `
    <div class="rtop">
      <button type="button" class="pbtn"${playable ? "" : " disabled"}
              title="${esc(playable ? STRINGS.audioPlay : STRINGS.audioUnplayable)}">▶</button>
      <div class="rname" title="${esc(item.name || "")}">${colorDotsHtml(item.colors)}${item.cover || item.artwork ? `<img class="rcov" alt="" title="${esc(item.cover ? STRINGS.coverFinalTitle : STRINGS.artworkTitle)}">` : ""}<span class="pre">${esc(stem.slice(0, p))}</span><b>${esc(stem.slice(p))}</b>${ext ? `<span class="ext">.${esc(ext)}</span>` : ""}</div>
      <span class="rtool" title="${esc(whoTitle)}">${esc(who)}</span>
      <span class="rdur">${fmtDuration(item.duration)}</span>
      <span class="rlufs" title="${esc(STRINGS.listColLoudnessTitle)}"></span>
      <span class="rdots">${dotsHtml(item.rating)}</span>
      <span class="rcom" title="${esc(STRINGS.listColCommentsTitle)}"></span>
    </div>
    <div class="wv" title="${esc(STRINGS.audioSeek)}"><canvas></canvas><span class="loopr" hidden></span><span class="ph" hidden></span><span class="sqz" hidden>»</span></div>`;
}

// -- Gemeinsame Zeitachse + Listenkopf ------------------------------------------------

let axis = 0;   // Sekunden der vollen Wellenbreite (0 = unbekannt: je Zeile die eigene Dauer)

/** Höchstens so weit reicht die gemeinsame Zeitachse (ADR 0109, #265): ein
 *  Konzert-Mitschnitt macht die übrigen Wellen nicht mehr winzig. Längere
 *  Songs füllen ihre Zeile gestaucht (paintWave: eigene Dauer als Breite)
 *  und tragen ». Gilt auch im Vergleich, der setTimeAxis mit dem längsten
 *  Verglichenen aufruft. */
export const AXIS_CAP = 7 * 60;

/** Spaltenköpfe der Liste mit Lineal der gemeinsamen Zeitachse. */
export function listHeadHtml() {
  // „Angaben" (#258): Spaltenköpfe ohne Legende und Lineal.
  if (infoRows()) {
    return `<div class="cmpnote" hidden></div><div class="manualnote" hidden></div><span></span>
    <span class="mlabel" title="${esc(STRINGS.listColTitleTitle)}">${STRINGS.listColTitle}</span>
    ${listRows() === "fundorte" ? `<span class="mlabel c-folder">${STRINGS.listColFolder}</span>` : ""}
    <span class="mlabel">${STRINGS.listColArtist}</span>
    <span class="mlabel c-album">${STRINGS.listColAlbum}</span>
    <span class="mlabel num c-track">${STRINGS.listColTrack}</span>
    <span class="mlabel num c-year">${STRINGS.listColYear}</span>
    <span class="mlabel c-genre">${STRINGS.listColGenre}</span>
    <span class="mlabel num">${STRINGS.listColDuration}</span>
    <span class="mlabel num">${STRINGS.listColRating}</span>
    <span class="mlabel num" title="${esc(STRINGS.listColCommentsTitle)}">💬</span>`;
  }
  return `<div class="cmpnote" hidden></div><div class="manualnote" hidden></div><span></span><span class="mlabel">${STRINGS.listColName}</span>
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
 *  max_duration der Treffermenge, gedeckelt auf AXIS_CAP) — Lineal und alle
 *  Wellen folgen. */
export function setTimeAxis(sec) {
  const next = sec > 0 ? Math.min(sec, AXIS_CAP) : 0;
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
  btnState(el.querySelector(".pbtn"), hash);   // nur bei Änderung (#211)
  const dur = parseFloat(el.dataset.dur) || 0;
  const wv = el.querySelector(".wv");
  paintWave(wv, hash, { axis, duration: dur });
  paintSqueeze(wv, dur);
  const rc = el.querySelector(".rcom");
  if (rc) {
    const n = commentsOf(hash).length;
    setText(rc, n ? String(n) : "–");
    rc.classList.toggle("has", n > 0);
  }
  // Lautheit nur, wo die Zeile sie zeigt: „Angaben" (#258) fragt die
  // Analyse gar nicht erst an.
  const l = el.querySelector(".rlufs");
  if (l) {
    const a = analysisOf(hash);
    const v = a?.loudness?.integrated;
    setText(l, v == null ? (a === false ? "–" : "") : v.toLocaleString(STRINGS.locale,
      { minimumFractionDigits: 1, maximumFractionDigits: 1 }));
  }
}

/** Gestauchte Zeile (ADR 0109): länger als die Achse → » am rechten Rand und
 *  wahre Länge im Tooltip. Schreibt nur bei Änderung (Neumalen ~10×/s). */
function paintSqueeze(wv, dur) {
  const mark = wv?.querySelector(".sqz");
  if (!mark) return;
  const on = axis > 0 && dur > axis;
  mark.hidden = !on;
  const title = on
    ? `${STRINGS.waveSqueezed.replace("{dur}", fmtDuration(dur)).replace("{axis}", fmtDuration(axis))}\n${STRINGS.audioSeek}`
    : STRINGS.audioSeek;
  if (wv.getAttribute("title") !== title) wv.setAttribute("title", title);
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

/** Alle abspielen: Reihenfolge der Liste JETZT (eingefroren), bis PLAY_ALL_CAP.
 *  In den Fundort-Darstellungen jeder Song einmal, an seiner ersten Zeile. */
async function startPlayAll(btn) {
  const n = Math.min(galleryTotal(), PLAY_ALL_CAP);
  if (!n) return;
  btn.disabled = true;
  const items = [];
  const seen = new Set();
  try {
    for (let i = 0; i < n; i++) {
      const it = await galleryItemAt(i);
      if (!it?.file_hash || seen.has(it.file_hash)) continue;   // Ordnerkopf, zweiter Fundort
      seen.add(it.file_hash);
      if (canPlay(it)) items.push(it);
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

  // Tasten der Liste (#260, Nachtrag ADR 0087): Leertaste = Play/Pause,
  // ←/→ = ±5 s (Shift ±1 s) für den Song der Abspielleiste, egal welche Zeile
  // ausgewählt ist. Ist die Leiste leer, oder aus (Vergleich: die Zeilen sind
  // der Player), gelten sie der ausgewählten Zeile. Enter startet die
  // ausgewählte Zeile. Statt Lupe (loupe.js); in Eingabefeldern ist die
  // Leertaste ein Leerzeichen.
  let sel = null;   // {hash, index} — der Index allein zeigt nach Umsortieren woandershin
  on("selection-changed", (d) => {
    sel = d.hash && d.index != null ? { hash: d.hash, index: d.index } : null;
  });
  on("items-reloaded", () => { sel = null; });
  async function selected() {
    if (!sel) return null;
    const item = await galleryItemAt(sel.index);
    return item?.file_hash === sel.hash && canPlay(item) ? item : null;
  }
  document.addEventListener("keydown", async (e) => {
    const key = e.key;
    if (key !== " " && key !== "Enter" && key !== "ArrowLeft" && key !== "ArrowRight") return;
    if (libraryView() !== "audio" || e.altKey || e.ctrlKey || e.metaKey) return;
    if (overlayOpen() || dialogsOpen()) return;   // Lupe, Einzelansicht, Dialoge: deren Tasten
    const t = e.target instanceof Element ? e.target : null;
    // Ein geklickter Knopf (⏮, ≈ Lautheit, Sortierung …) oder ein geklicktes
    // Häkchen behält den Fokus; Leertaste und Enter lösten ihn sonst erneut
    // aus. Nur wer per Tab auf einen Knopf geht, löst ihn mit Enter aus.
    if (t?.matches('button, input[type="checkbox"], input[type="radio"]')) {
      if (key === "Enter" && t.matches(":focus-visible")) return;
      t.blur();
    } else if (typing(e)) return;
    e.preventDefault();
    const bar = listComparing() ? null : currentSong();
    const item = key === "Enter" || !bar ? await selected() : bar;
    if (!item) return;
    if (key === " " || key === "Enter") togglePlay(item);
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
const popoverOpen = () => ["sortmenu", "rowsmenu", "addcrit", "typeahead"]
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
