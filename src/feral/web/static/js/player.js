// player.js — der eigene Audio-Player (A5 #162, ADR 0083 Punkt 7, ADR 0087).
//
// EIN <audio>-Element für die ganze Seite, ohne Frontend-Abhängigkeit:
// - **Eigener Abspielkopf je Song:** ein Wechsel pausiert und merkt die
//   Stelle (Refrain gegen Refrain); es spielt genau einer.
// - **Lautheitsangleich** über Web Audio (GainNode) auf Basis der Analyse
//   (A4, ADR 0086), global schaltbar und gemerkt.
// - **Tempo ohne Tonhöhe** (preservesPitch), **A–B-Loop**, Sprünge.
// - **Alle abspielen:** Warteschlange, beim Start eingefroren.
// - **Abspielleiste** (#pbar) unten; läuft beim Wechsel in die Galerie weiter.
// - **Medientasten** über navigator.mediaSession.
// Darstellungen: Listenzeilen (audiolist.js, per onRepaint), eingebettete
// Player (.aplayer aus api.mediaHtml: Detailpanel außerhalb der
// Audioansicht, Arena) und die Leiste — alle malen denselben Zustand.
// Keine Lupe für Audio (die Liste kann mehr); die Einzelansicht nur für
// Songs mit Cover, aus der Galerie (#165).
//
// Freigabe (#89): Weil es nur dieses eine Element gibt, gibt jeder
// Songwechsel die vorige Range-Verbindung mit dem neuen src frei; „Beenden"
// (✕) gibt sie über api.releaseVideo ganz zurück.

import { STRINGS } from "./strings.js";
import { displayUrl, fmtDuration, getAudioAnalysis, loadThumb, releaseVideo, thumbUrl } from "./api.js";
import { dbToGain, drawWave, fmtDb, matchGainDb } from "./waveform.js";
import { on } from "./main.js";
import { openCommentPrompt, paintPins, pinTime } from "./comments.js";

const MATCH_KEY = "feral-audio-match";
const TEMPI = [1, 1.25, 1.5];   // schneller vorhören; langsamer braucht Musik nicht
const ANALYSIS_CAP = 800;     // gemerkte Analysen (je ~30 KB)
const ANALYSIS_PARALLEL = 4;

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let el = null;                 // das EINE <audio> (lazy — Node-Tests brauchen keins)
let cur = null;                // Schnappschuss des geladenen Songs
let pendingStart = null;       // Startstelle, sobald die Metadaten da sind
const positions = new Map();   // Hash → gemerkte Stelle (Sekunden)
const failed = new Set();      // Hashes, deren Wiedergabe scheiterte
let loop = null;               // {hash, a, b} — b null = A gesetzt, B fehlt
let tempo = 1;
let match = readMatch();
let matchOverride = null;      // Vergleich in der Liste (A7): eigener Stand, nie gemerkt
let queue = null;              // {items, i} — „Alle abspielen", eingefroren
let actx = null;               // AudioContext (erst beim ersten Abspielen)
let gainNode = null;
const repainters = new Set();

function readMatch() {
  try { return localStorage.getItem(MATCH_KEY) !== "0"; } catch { return true; }
}

/** Was der Player von einem Item braucht (Galerie-Item, Detail oder .aplayer). */
export function snap(item) {
  return {
    file_hash: item.file_hash, container: item.container, media_kind: "audio",
    duration: item.duration ?? null, name: item.name || "", tool: item.tool || "",
    model: item.model || "", cover: item.cover || null, artwork: !!item.artwork,
  };
}

/** Anzeigebild eines Songs: das Cover (#165), sonst das eingebettete Bild
 *  normaler Musik (#198, /api/thumb des Songs selbst) — oder null. */
const pictureOf = (s) => s.cover || (s.artwork ? s.file_hash : null);

const isPlaying = () => !!el && !!cur && !el.paused;
export const currentHash = () => cur?.file_hash ?? null;
export const playingHash = () => (isPlaying() ? cur.file_hash : null);
export const isFailed = (hash) => failed.has(hash);
export const matchOn = () => matchOverride ?? match;
export const loopOf = (hash) => (loop && loop.hash === hash ? loop : null);

/** Aktuelle bzw. gemerkte Stelle eines Songs (Sekunden). */
export function positionOf(hash) {
  if (cur && cur.file_hash === hash && el) return el.currentTime || pendingStart || 0;
  return positions.get(hash) || 0;
}

/** Tatsächliche Dauer: vom Element, sobald bekannt, sonst die katalogisierte. */
export function durationOf(hash, fallback) {
  if (cur && cur.file_hash === hash && el && Number.isFinite(el.duration) && el.duration > 0) return el.duration;
  return fallback || 0;
}

// -- Analysen (Wellenform + Lautheit, A4) -------------------------------------------

const analyses = new Map();    // Hash → Analyse | false (fehlgeschlagen)
const pending = new Set();
const waiting = [];
let active = 0;

/** Analyse eines Songs aus dem Speicher; fehlt sie, wird sie geholt (dann
 *  undefined, später ein Neuzeichnen). false = nicht messbar. */
export function analysisOf(hash) {
  if (analyses.has(hash)) return analyses.get(hash);
  if (!pending.has(hash)) {
    pending.add(hash);
    waiting.push(hash);
    pumpAnalyses();
  }
  return undefined;
}

function pumpAnalyses() {
  while (active < ANALYSIS_PARALLEL && waiting.length) {
    const hash = waiting.pop();      // zuletzt angefragt = gerade sichtbar
    active++;
    getAudioAnalysis(hash)
      .then((a) => { if (a) rememberAnalysis(hash, a); })
      .catch(() => rememberAnalysis(hash, false))
      .finally(() => {
        pending.delete(hash);
        active--;
        pumpAnalyses();
      });
  }
}

function rememberAnalysis(hash, a) {
  analyses.set(hash, a);
  while (analyses.size > ANALYSIS_CAP) analyses.delete(analyses.keys().next().value);
  if (cur && cur.file_hash === hash) applyGain();
  repaint(hash);
}

/** Angleich in dB für einen Song (0 bei „original" oder ohne Messung). */
export function gainOf(hash) {
  const a = analyses.get(hash);
  return matchOn() && a ? matchGainDb(a.loudness) : 0;
}

// -- Wiedergabe -----------------------------------------------------------------------

function ensureEl() {
  if (el) return el;
  el = document.createElement("audio");
  el.preload = "auto";
  el.preservesPitch = true;
  for (const ev of ["play", "pause", "loadedmetadata"]) el.addEventListener(ev, () => { syncTicker(); repaint(); });
  el.addEventListener("loadedmetadata", () => {
    if (pendingStart !== null) { el.currentTime = pendingStart; pendingStart = null; }
  });
  el.addEventListener("timeupdate", () => { checkLoop(); sessionPosition(); });
  el.addEventListener("ended", onEnded);
  el.addEventListener("error", () => {
    if (!cur || !el.getAttribute("src")) return;
    failed.add(cur.file_hash);
    repaint(cur.file_hash);
  });
  return el;
}

/** Web Audio einklinken (einmal, im Klick — Browser erlauben den Ton-
 *  Kontext nur nach einer Geste). Ohne Web Audio: Angleich nur absenkend
 *  über die Lautstärke des Elements. */
function route() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!actx && AC) {
    try {
      actx = new AC();
      gainNode = actx.createGain();
      actx.createMediaElementSource(el).connect(gainNode).connect(actx.destination);
    } catch { actx = null; gainNode = null; }
  }
  if (actx?.state === "suspended") actx.resume().catch(() => {});
}

function applyGain() {
  if (!el || !cur) return;
  const g = dbToGain(gainOf(cur.file_hash));
  if (gainNode) gainNode.gain.value = g;
  else el.volume = Math.min(1, g);
}

/** Alle anderen Medien MIT TON anhalten (Lupe, Einzelansicht …); stumme
 *  Vorschauen im Panel und in der Arena laufen weiter (#198). */
function pauseOthers() {
  for (const m of document.querySelectorAll("audio, video")) {
    if (m !== el && !m.muted && !m.paused) m.pause();
  }
}

/** Song abspielen; `at` (Sekunden) springt vorher dorthin. Ein anderer Song
 *  übernimmt: der bisherige merkt seine Stelle. */
export function play(item, at = null) {
  if (!item) return;
  const p = ensureEl();
  const hash = item.file_hash;
  if (queue && queue.items[queue.i]?.file_hash !== hash) {
    // Ein Song außerhalb der Reihenfolge beendet „Alle abspielen";
    // einer aus ihr setzt sie dort fort.
    const i = queue.items.findIndex((q) => q.file_hash === hash);
    if (i < 0) queue = null; else queue.i = i;
  }
  if (!cur || cur.file_hash !== hash) {
    if (cur) { positions.set(cur.file_hash, p.currentTime || pendingStart || 0); p.pause(); }
    const prev = cur?.file_hash;
    cur = snap(item);
    failed.delete(hash);
    if (loop && loop.hash !== hash) loop = null;
    let start = at ?? positions.get(hash) ?? 0;
    if (cur.duration && start >= cur.duration - 0.5) start = 0;   // am Ende → von vorn
    pendingStart = start > 0 ? start : null;
    p.defaultPlaybackRate = tempo;
    p.playbackRate = tempo;
    p.src = displayUrl(cur);   // Original oder FLAC-Proxy (A4 #161)
    setSession();
    if (prev) repaint(prev);
  } else if (at !== null) {
    if (pendingStart !== null) pendingStart = at; else p.currentTime = at;
  }
  route();
  applyGain();
  pauseOthers();
  p.play().catch(() => {});
  repaint(hash);
}

/** Abspielen bzw. anhalten (▶/❚❚, Leertaste). */
export function toggle(item) {
  if (!item) return;
  if (cur && cur.file_hash === item.file_hash && isPlaying()) el.pause();
  else play(item);
}

export function pause() { if (isPlaying()) el.pause(); }

/** Springen: der geladene Song sofort, jeder andere startet an der Stelle. */
export function seek(item, sec) {
  if (!item) return;
  const dur = durationOf(item.file_hash, item.duration);
  play(item, Math.max(0, dur ? Math.min(sec, dur - 0.25) : sec));
}

/** ±Sekunden (Pfeiltasten): der geladene Song springt, jeder andere
 *  verschiebt nur seinen gemerkten Abspielkopf. */
export function nudge(item, delta) {
  if (!item) return;
  const hash = item.file_hash;
  const dur = durationOf(hash, item.duration);
  const to = Math.max(0, Math.min(dur ? dur - 0.25 : Infinity, positionOf(hash) + delta));
  if (cur && cur.file_hash === hash && el) {
    if (pendingStart !== null) pendingStart = to; else el.currentTime = to;
  } else positions.set(hash, to);
  repaint(hash);
}

/** Wiedergabe beenden (✕ in der Leiste, Modul aus): Stelle merken,
 *  Verbindung freigeben (#89), Leiste weg. */
export function stop() {
  if (!cur) return;
  const hash = cur.file_hash;
  if (el) { positions.set(hash, el.currentTime || 0); releaseVideo(el); }
  cur = null; queue = null; loop = null; pendingStart = null;
  if (navigator.mediaSession) {
    try { navigator.mediaSession.metadata = null; navigator.mediaSession.playbackState = "none"; } catch { /* egal */ }
  }
  syncTicker();
  repaint(hash);
}

/** Alle abspielen: Reihenfolge wie übergeben, eingefroren; jeder Song von vorn. */
export function playAll(items) {
  if (!items?.length) return;
  queue = { items: items.map(snap), i: 0 };
  positions.delete(queue.items[0].file_hash);
  play(queue.items[0], 0);
}

function step(delta) {
  if (!queue) return false;
  const i = queue.i + delta;
  if (i < 0 || i >= queue.items.length) return false;
  queue.i = i;
  play(queue.items[i], 0);
  return true;
}

/** ⏭: nächster Song der Reihenfolge. */
export function next() { step(1); }

/** ⏮: nach den ersten Sekunden an den Anfang, sonst der vorige Song. */
export function prev() {
  if (!cur || !el) return;
  if (el.currentTime > 3 || !step(-1)) play(cur, 0);
}

function onEnded() {
  if (!cur) return;
  positions.delete(cur.file_hash);
  if (!step(1)) { queue = null; repaint(); }
}

/** Lautheitsangleich an/aus (global, gemerkt). Während eines Vergleichs
 *  schaltet er nur dessen eigenen Stand um. */
export function toggleMatch() {
  if (matchOverride !== null) matchOverride = !matchOverride;
  else {
    match = !match;
    try { localStorage.setItem(MATCH_KEY, match ? "1" : "0"); } catch { /* privat */ }
  }
  applyGain();
  repaint();
}

/** Eigener Angleich-Stand für die Dauer eines Vergleichs (A7, ADR 0089):
 *  true/false setzt ihn, null gibt die gemerkte Einstellung zurück. */
export function overrideMatch(v) {
  matchOverride = v === null ? null : !!v;
  applyGain();
  repaint();
}

/** Tempo reihum 1 → 1,25 → 1,5; die Tonhöhe bleibt (preservesPitch). */
export function cycleTempo() {
  tempo = TEMPI[(TEMPI.indexOf(tempo) + 1) % TEMPI.length];
  if (el) { el.defaultPlaybackRate = tempo; el.playbackRate = tempo; el.preservesPitch = true; }
  sessionPosition();
  repaint();
}

/** Loop reihum: A an der Abspielstelle → B an der Abspielstelle (der
 *  Bereich läuft) → aus. B vor A tauscht die Enden. */
export function cycleLoop() {
  if (!cur || !el) return;
  const t = el.currentTime || 0;
  if (!loop || loop.hash !== cur.file_hash) loop = { hash: cur.file_hash, a: t, b: null };
  else if (loop.b === null) {
    if (Math.abs(t - loop.a) < 0.5) return;
    loop = t > loop.a ? { ...loop, b: t } : { ...loop, a: t, b: loop.a };
    if (el.currentTime >= loop.b || el.currentTime < loop.a) el.currentTime = loop.a;
  } else loop = null;
  repaint(cur.file_hash);
}

function checkLoop() {
  if (loop && loop.b !== null && cur && loop.hash === cur.file_hash && el.currentTime >= loop.b) {
    el.currentTime = loop.a;
  }
}

// -- Medientasten (navigator.mediaSession) -------------------------------------------

function setSession() {
  const ms = navigator.mediaSession;
  if (!ms || !cur) return;
  try {
    const dot = cur.name.lastIndexOf(".");
    ms.metadata = new MediaMetadata({
      title: dot > 0 ? cur.name.slice(0, dot) : cur.name || cur.file_hash.slice(0, 12),
      artist: cur.model || cur.tool || "", album: "Feral Media Library",
      // Cover (#165) bzw. eingebettetes Bild (#198) für Sperrbildschirm und
      // Medientasten des Systems.
      ...(pictureOf(cur) ? { artwork: [{ src: thumbUrl(pictureOf(cur)), type: "image/jpeg" }] } : {}),
    });
  } catch { /* MediaMetadata fehlt */ }
}

function sessionPosition() {
  const ms = navigator.mediaSession;
  if (!ms || !cur || !el) return;
  try {
    ms.playbackState = el.paused ? "paused" : "playing";
    if (Number.isFinite(el.duration) && el.duration > 0) {
      ms.setPositionState?.({ duration: el.duration, playbackRate: tempo,
                              position: Math.min(el.currentTime, el.duration) });
    }
  } catch { /* ältere Browser */ }
}

function wireSession() {
  const ms = navigator.mediaSession;
  if (!ms?.setActionHandler) return;
  const handlers = {
    play: () => cur && play(cur),
    pause: () => pause(),
    stop: () => stop(),
    previoustrack: () => prev(),
    nexttrack: () => next(),
    seekbackward: (d) => cur && nudge(cur, -(d?.seekOffset || 5)),
    seekforward: (d) => cur && nudge(cur, d?.seekOffset || 5),
    seekto: (d) => cur && d?.seekTime != null && seek(cur, d.seekTime),
  };
  for (const [action, fn] of Object.entries(handlers)) {
    try { ms.setActionHandler(action, fn); } catch { /* nicht unterstützt */ }
  }
}

// -- Malen ------------------------------------------------------------------------------

/** Neuzeichnen anmelden (audiolist.js: Zeilen); fn(hash|null). */
export function onRepaint(fn) { repainters.add(fn); }

let frame = 0;
let dirtyAll = false;
const dirty = new Set();

/** Darstellungen eines Songs (oder aller: ohne Hash) neu malen — gebündelt
 *  auf den nächsten Frame. */
export function repaint(hash = null) {
  if (hash === null) dirtyAll = true; else dirty.add(hash);
  if (frame) return;
  frame = requestAnimationFrame(flushPaint);
}

function flushPaint() {
  frame = 0;
  const all = dirtyAll;
  const hashes = [...dirty];
  dirtyAll = false;
  dirty.clear();
  for (const fn of repainters) {
    if (all) fn(null); else hashes.forEach((h) => fn(h));
  }
  for (const w of document.querySelectorAll(".aplayer[data-hash]")) {
    if (all || hashes.includes(w.dataset.hash)) paintWidget(w);
  }
  paintBar();
}

/** Wellenfläche (.wv mit canvas/.ph/.loopr) eines Songs malen. `axis` =
 *  Sekunden der vollen Breite (Liste: gemeinsame Zeitachse). */
export function paintWave(wv, hash, { axis, duration }) {
  if (!wv) return;
  const dur = durationOf(hash, duration);
  const ax = axis > 0 ? Math.max(axis, dur) : dur;
  const pos = positionOf(hash);
  const known = cur?.file_hash === hash || positions.has(hash);
  const a = analysisOf(hash);
  const cv = wv.querySelector("canvas");
  if (cv) drawWave(cv, a || null, { axis: ax, duration: dur, played: known && dur ? pos / dur : 0, gainDb: gainOf(hash) });
  paintPins(wv, hash, ax, cur?.file_hash === hash ? pos : null);   // Zeitkommentare (#163)
  const ph = wv.querySelector(".ph");
  if (ph) {
    ph.hidden = !known || !ax;
    if (ax) ph.style.left = `${Math.min(100, (pos / ax) * 100)}%`;
  }
  const lr = wv.querySelector(".loopr");
  const lp = loopOf(hash);
  if (lr) {
    lr.hidden = !lp || !ax;
    if (lp && ax) {
      const b = lp.b ?? lp.a;
      lr.style.left = `${(lp.a / ax) * 100}%`;
      lr.style.width = `${((b - lp.a) / ax) * 100}%`;
      lr.classList.toggle("open", lp.b === null);
    }
  }
}

// Neumalen läuft während der Wiedergabe ~10× je Sekunde: nur schreiben, was
// sich ändert. Ein neu gesetzter Text ersetzt den Textknoten unter dem
// Mauszeiger, fällt das zwischen mousedown und mouseup, verwirft der
// Browser den Klick — ❚❚ ließ sich kaum drücken (#211).
export function setText(node, text) {
  if (node && node.textContent !== text) node.textContent = text;
}
const setTitle = (node, title) => { if (node && node.title !== title) node.title = title; };
const setHtml = (node, html) => { if (node._html !== html) { node._html = html; node.innerHTML = html; } };

/** ▶/❚❚-Knopf eines Songs (Listenzeile, eingebetteter Player, Leiste). */
export function btnState(btn, hash) {
  if (!btn) return;
  const bad = failed.has(hash);
  const on = playingHash() === hash;
  if (btn.disabled !== bad) btn.disabled = bad;
  setText(btn, on ? "❚❚" : "▶");
  setTitle(btn, bad ? STRINGS.audioPlayFailed : on ? STRINGS.audioPause : STRINGS.audioPlay);
}

const gainText = (hash) => {
  if (!matchOn()) return STRINGS.audioGainOff;
  const a = analyses.get(hash);
  return a ? STRINGS.audioGainOn.replace("{db}", fmtDb(matchGainDb(a.loudness), STRINGS.locale)) : "";
};

/** Eingebetteter Player (.aplayer aus api.mediaHtml). */
function itemOfWidget(w) {
  const d = w.dataset;
  return { file_hash: d.hash, container: d.container, duration: parseFloat(d.dur) || null,
           name: d.name || "", tool: d.tool || "", model: "", cover: d.cover || null };
}

function paintWidget(w) {
  const hash = w.dataset.hash;
  const dur = durationOf(hash, parseFloat(w.dataset.dur) || 0);
  paintWave(w.querySelector(".wv"), hash, { axis: dur, duration: dur });
  btnState(w.querySelector(".pbtn"), hash);
  setText(w.querySelector(".ptime"), `${fmtDuration(positionOf(hash)) || "0:00"} / ${fmtDuration(dur)}`);
  setText(w.querySelector(".pgain"), gainText(hash));
  const note = w.querySelector(".pnote");
  if (note) note.hidden = !failed.has(hash);
}

// -- Abspielleiste -------------------------------------------------------------------------

function barSkeleton(bar) {
  bar.innerHTML = `
    <div class="tr">
      <button type="button" data-act="prev" title="${esc(STRINGS.audioPrev)}">⏮</button>
      <button type="button" data-act="play" class="main">▶</button>
      <button type="button" data-act="next" title="${esc(STRINGS.audioNext)}">⏭</button>
    </div>
    <div class="now"><span class="pcov" hidden></span><div class="nt"><div class="n"></div><div class="q"></div></div></div>
    <div class="mid"><span class="tm tpos"></span>
      <div class="wv" title="${esc(STRINGS.audioSeek)}"><canvas></canvas><span class="loopr" hidden></span><span class="ph" hidden></span></div>
      <span class="tm tdur"></span></div>
    <div class="opts">
      <button type="button" data-act="match" title="${esc(STRINGS.audioMatchTitle)}">≈ ${esc(STRINGS.audioMatch)}<span class="gain"></span></button>
      <button type="button" data-act="tempo" title="${esc(STRINGS.audioTempoTitle)}"></button>
      <button type="button" data-act="loop" title="${esc(STRINGS.audioLoopTitle)}"></button>
      <button type="button" data-act="comment" title="${esc(STRINGS.commentAddTitle)}">💬</button>
      <button type="button" data-act="close" title="${esc(STRINGS.audioClose)}">✕</button>
    </div>`;
  bar.dataset.built = "1";
}

function paintBar() {
  const bar = document.getElementById("pbar");
  if (!bar) return;
  bar.hidden = !cur;
  document.body.classList.toggle("has-pbar", !!cur);
  if (!cur) return;
  if (!bar.dataset.built) barSkeleton(bar);
  const hash = cur.file_hash;
  const dur = durationOf(hash, cur.duration);
  btnState(bar.querySelector('[data-act="play"]'), hash);
  const nx = bar.querySelector('[data-act="next"]');
  const last = !queue || queue.i >= queue.items.length - 1;
  if (nx.disabled !== last) nx.disabled = last;
  paintBarCover(bar.querySelector(".pcov"), pictureOf(cur));
  const n = bar.querySelector(".n");
  setText(n, cur.name || hash.slice(0, 12));
  setTitle(n, cur.name);
  const who = cur.model || cur.tool;
  setHtml(bar.querySelector(".q"), (queue
    ? `<b>${esc(STRINGS.audioPlayAll)}</b> · ${esc(STRINGS.audioQueueInfo.replace("{i}", queue.i + 1).replace("{n}", queue.items.length))}`
    : esc(STRINGS.audioSingle)) + (who ? ` · ${esc(who)}` : "")
    + (failed.has(hash) ? ` · <span class="bad">${esc(STRINGS.audioPlayFailed)}</span>` : ""));
  setText(bar.querySelector(".tpos"), fmtDuration(positionOf(hash)) || "0:00");
  setText(bar.querySelector(".tdur"), fmtDuration(dur));
  paintWave(bar.querySelector(".wv"), hash, { axis: dur, duration: dur });
  const m = bar.querySelector('[data-act="match"]');
  m.classList.toggle("on", matchOn());
  setText(m.querySelector(".gain"), matchOn() && analyses.get(hash)
    ? fmtDb(matchGainDb(analyses.get(hash).loudness), STRINGS.locale) + " dB" : "");
  const tb = bar.querySelector('[data-act="tempo"]');
  setText(tb, `${tempo.toLocaleString(STRINGS.locale, { minimumFractionDigits: 2 })}×`);
  tb.classList.toggle("on", tempo !== 1);
  const lb = bar.querySelector('[data-act="loop"]');
  const lp = loopOf(hash);
  setText(lb, !lp ? `⟲ ${STRINGS.audioLoop}` : lp.b === null ? `⟲ ${STRINGS.audioLoopA}` : `⟲ ${STRINGS.audioLoopOn}`);
  lb.classList.toggle("on", !!lp);
}

// Cover-Miniatur der Leiste (#165): nur bei Wechsel neu laden (paintBar läuft
// während der Wiedergabe ~10× je Sekunde).
function paintBarCover(slot, cover) {
  if ((slot.dataset.cover || "") === (cover || "")) return;
  slot.dataset.cover = cover || "";
  slot.innerHTML = cover ? `<img alt="">` : "";
  slot.hidden = !cover;
  if (cover) loadThumb(slot.querySelector("img"), cover);
}

// Während der Wiedergabe: Abspielkopf ~10× je Sekunde nachführen (rAF,
// gedrosselt); pausiert ruht die Schleife.
let ticker = 0;
let lastTick = 0;
function syncTicker() {
  if (isPlaying() && !ticker) ticker = requestAnimationFrame(tick);
}
function tick(now) {
  ticker = 0;
  if (!isPlaying()) return;
  if (now - lastTick > 100) {
    lastTick = now;
    checkLoop();
    repaint(cur.file_hash);
  }
  ticker = requestAnimationFrame(tick);
}

/** Bruchteil 0…1 einer Klickstelle in einem Element. */
function fractionAt(elm, e) {
  const r = elm.getBoundingClientRect();
  return r.width ? Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) : null;
}

export function initPlayer() {
  // Es spielt immer genau eines: startet ein anderes Medien-Element MIT TON,
  // hält dieses hier an („play" blubbert nicht — darum Capture am Dokument).
  // Stumme Vorschauen (Detailpanel, Arena) lassen die Musik laufen (#198):
  // sonst stoppte jedes Video-Duell den Song, und Firefox setzte ihn danach
  // an diesem Player vorbei fort — der Knopf zeigte ▶ bei laufender Musik.
  document.addEventListener("play", (e) => {
    if (el && e.target !== el && !e.target.muted && !el.paused) el.pause();
  }, true);

  // Eingebettete Player und Leiste: Klick-Delegation am Dokument — die
  // .aplayer entstehen per innerHTML an vielen Stellen (api.mediaHtml).
  document.addEventListener("click", (e) => {
    const t = e.target;
    if (!(t instanceof Element)) return;
    const w = t.closest(".aplayer[data-hash]");
    if (w) {
      const item = itemOfWidget(w);
      if (t.closest(".pbtn")) toggle(item);
      else if (t.closest(".wv")) {
        const f = fractionAt(w.querySelector(".wv"), e);
        const dur = durationOf(item.file_hash, item.duration);
        const at = pinTime(e);   // Pin: genau an den Kommentar
        if (at !== null) seek(item, at);
        else if (f !== null && dur) seek(item, f * dur);
      }
      return;
    }
    const bar = t.closest("#pbar");
    if (!bar || !cur) return;
    const act = t.closest("[data-act]")?.dataset.act;
    if (act === "play") toggle(cur);
    else if (act === "prev") prev();
    else if (act === "next") next();
    else if (act === "match") toggleMatch();
    else if (act === "tempo") cycleTempo();
    else if (act === "loop") cycleLoop();
    else if (act === "close") stop();
    else if (act === "comment") openCommentPrompt(cur.file_hash, positionOf(cur.file_hash), t.closest("[data-act]"));
    else if (t.closest(".wv")) {
      const f = fractionAt(bar.querySelector(".wv"), e);
      const dur = durationOf(cur.file_hash, cur.duration);
      const at = pinTime(e);
      if (at !== null) seek(cur, at);
      else if (f !== null && dur) seek(cur, f * dur);
    }
  });

  // Modul aus: Wiedergabe beenden (die Audio-Items sind ausgeblendet).
  on("audio-enabled", (d) => { if (!d?.enabled) stop(); });
  // Cover geändert (#165): der laufende Song zeigt es sofort in der Leiste.
  on("cover-changed", (d) => {
    if (!cur || cur.file_hash !== d.hash) return;
    cur.cover = d.manual?.cover || null;
    setSession();
    repaint(cur.file_hash);
  });

  // Neue eingebettete Player (Panel, Lupe …) und Größenwechsel: neu malen.
  new MutationObserver(() => {
    if (document.querySelector(".aplayer[data-hash]:not([data-painted])")) {
      document.querySelectorAll(".aplayer[data-hash]:not([data-painted])")
        .forEach((w) => { w.dataset.painted = "1"; paintWidget(w); });
    }
  }).observe(document.body, { childList: true, subtree: true });
  let resizeTimer = 0;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => repaint(), 80);
  });
  const ro = new ResizeObserver(() => repaint());
  for (const id of ["mid", "panel", "pbar"]) {
    const n = document.getElementById(id);
    if (n) ro.observe(n);
  }
  // Themenwechsel (Wellenfarben aus theme.css): neu zeichnen.
  new MutationObserver(() => repaint())
    .observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  wireSession();
}
