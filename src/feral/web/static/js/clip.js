// clip.js — Ausschnitt-Ansicht (Modul „Ausschnitt", ADR 0105, #271).
//
// Einen Abschnitt aus einem Song oder Video markieren und als Datei in den
// Export-Ordner schreiben lassen. Einstieg ist der Knopf ✂ im Detail-Panel
// ('clip-open' mit dem Item); die Ansicht liegt als Dialog über allem, was
// gerade offen ist (Galerie, Audioansicht, Einzelansicht) — Esc führt
// dorthin zurück (overlays.js).
//
// Bedienung:
// - Zeitleiste über die ganze Länge (Songs: die dreibandige Wellenform).
//   Griff ziehen = Anfang/Ende, in der Mitte ziehen = Bereich verschieben
//   (die Länge bleibt), Klick daneben = nur die Abspielstelle.
// - Felder Anfang/Ende/Länge in Zehntelsekunden; „hier" bzw. I und O setzen
//   Anfang und Ende an die Abspielstelle.
// - Leertaste spielt; läuft die Abspielstelle über das Ende des Bereichs,
//   springt sie an den Anfang (Schleife). Außerhalb des Bereichs läuft es
//   frei weiter: so sucht man eine Stelle.
// - ←/→ schieben den zuletzt angefassten Griff um 0,1 s, mit Shift um 1 s.
//
// Die Ansicht hat ihr EIGENES Medien-Element. Alle anderen geben solange
// ihre Verbindung ab (#89: dieselbe große Datei nie zweimal streamen) und
// bekommen sie beim Schließen zurück; der Audio-Player pausiert.
//
// Tasten: solange die Ansicht offen ist, sieht keine Ebene darunter einen
// Tastendruck (Capture-Listener, der alles anhält).

import { STRINGS } from "./strings.js";
import { displayUrl, getAudioAnalysis, getClipState, mediaUrl, releaseVideo, revealExportPath, startClip } from "./api.js";
import { drawWave } from "./waveform.js";
import { on } from "./main.js";
import { registerDialog } from "./overlays.js";
import { onStatus, onTaskFinished } from "./status.js";
import { serverMsg } from "./servermsg.js";
import { loopOf, pause as pausePlayer, positionOf } from "./player.js";

export const MIN_LENGTH = 0.1;
const DEFAULT_LENGTH = 10;
const PREROLL = 2;                       // nach „Ende setzen": so viel davor anhören
const OUTPUT_KEY = "feral-clip-outputs";
const VIDEO_OUTPUTS = ["av", "video", "audio"];

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// -- Zeiten und Bereich (rein, ohne DOM) ------------------------------------------

const tenth = (t) => Math.round(t * 10) / 10;
const clamp = (t, lo, hi) => Math.min(Math.max(t, lo), hi);

/** „1:12.5", „72,5", „1:02:03" → Sekunden; null, wenn es keine Zeit ist. */
export function parseTime(text) {
  const parts = String(text ?? "").trim().replace(",", ".").split(":");
  if (parts.length > 3 || parts.some((p) => !/^\d+(\.\d*)?$/.test(p))) return null;
  return parts.reduce((sum, p) => sum * 60 + parseFloat(p), 0);
}

/** Sekunden → „0:12.0" bzw. „1:02:03.5", immer mit Zehntel. */
export function fmtTime(sec) {
  const tenths = Math.round(Math.max(0, sec || 0) * 10);
  const whole = Math.floor(tenths / 10);
  const h = Math.floor(whole / 3600), m = Math.floor((whole % 3600) / 60), s = whole % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return `${h ? `${h}:${pad(m)}` : m}:${pad(s)}.${tenths % 10}`;
}

/** Bereich als Fenster verschieben: die Länge bleibt, die Datei begrenzt. */
export function moveRange(range, a, dur) {
  const len = Math.min(range.b - range.a, dur);
  const start = clamp(tenth(a), 0, Math.max(0, dur - len));
  return { a: start, b: Math.min(dur, start + len) };
}

/** Griff ziehen: Anfang bzw. Ende, der andere Rand bleibt stehen. */
export const dragStart = (range, t) =>
  ({ a: clamp(tenth(t), 0, range.b - MIN_LENGTH), b: range.b });
export const dragEnd = (range, t, dur) =>
  ({ a: range.a, b: clamp(tenth(t), range.a + MIN_LENGTH, dur) });

/** „Anfang hier" / „Ende hier": liegt die Stelle hinter dem Ende bzw. vor
 *  dem Anfang, wandert das Fenster mit (der Anfang steht danach wirklich
 *  dort), statt am anderen Rand hängen zu bleiben. */
export const markStart = (range, t, dur) =>
  (t < range.b - MIN_LENGTH ? dragStart(range, t) : moveRange(range, t, dur));
export const markEnd = (range, t, dur) =>
  (t > range.a + MIN_LENGTH ? dragEnd(range, t, dur)
    : moveRange(range, t - (range.b - range.a), dur));

/** Länge eintippen: das Ende rückt nach; reicht die Datei nicht, der Anfang. */
export function setLength(range, len, dur) {
  const want = clamp(tenth(len), MIN_LENGTH, dur);
  const b = Math.min(dur, range.a + want);
  return { a: Math.max(0, tenth(b - want)), b };
}

/** Startbereich: eine fertige A–B-Schleife des Players, sonst 10 s ab der
 *  Abspielstelle (höchstens die ganze Datei). */
export function initialRange({ duration, position = 0, loop = null }) {
  if (loop && loop.b != null && loop.b - loop.a >= MIN_LENGTH) {
    return { a: clamp(tenth(loop.a), 0, duration), b: clamp(tenth(loop.b), 0, duration) };
  }
  const len = Math.min(DEFAULT_LENGTH, duration);
  return moveRange({ a: 0, b: len }, position < duration - MIN_LENGTH ? position : 0, duration);
}

// -- Gemerkte Ausgabe-Wahl (nur Videos haben eine) -----------------------------------

function readOutputs() {
  try {
    const saved = JSON.parse(localStorage.getItem(OUTPUT_KEY) || "null");
    if (Array.isArray(saved)) return saved.filter((o) => VIDEO_OUTPUTS.includes(o));
  } catch { /* Vorgabe */ }
  return ["av"];
}

function saveOutputs(outputs) {
  try { localStorage.setItem(OUTPUT_KEY, JSON.stringify(outputs)); } catch { /* egal */ }
}

const newToken = () =>
  globalThis.crypto?.randomUUID?.() || `c${Date.now()}-${Math.floor(Math.random() * 1e9)}`;

const baseName = (path) => String(path).split("/").pop().split("\\").pop();

// -- Ansicht ---------------------------------------------------------------------

export function initClip() {
  const root = document.getElementById("clip");
  let st = null;                 // Zustand der offenen Ansicht, sonst null
  const pending = new Map();     // token → Ergebniszeile, bis die Aufgabe fertig ist

  const $ = (sel) => root.querySelector(sel);

  /** Andere <video> geben ihre Verbindung ab, solange hier geschnitten wird. */
  function parkVideos() {
    const parked = [];
    for (const v of document.querySelectorAll("video")) {
      const src = v.getAttribute("src");
      if (!src) continue;
      parked.push({ v, src, at: v.currentTime || 0 });
      releaseVideo(v);
    }
    return parked;
  }

  function unparkVideos(parked) {
    for (const { v, src, at } of parked) {
      if (!v.isConnected) continue;
      v.setAttribute("src", src);          // autoplay-Elemente laufen von selbst wieder an
      if (at > 0) v.addEventListener("loadedmetadata", () => { v.currentTime = at; }, { once: true });
    }
  }

  /** Abspielstelle dieses Items, bevor die anderen Elemente parken: beim
   *  Song die des Players, beim Video die der Einzelansicht. Die stumme
   *  Vorschau im Panel zählt nicht, ihre Stelle ist Zufall. */
  function positionBefore(item) {
    if (item.media_kind === "audio") return positionOf(item.file_hash);
    const v = document.querySelector("#svStage video");
    return v && (v.getAttribute("src") || "").includes(item.file_hash) ? v.currentTime || 0 : 0;
  }

  function skeleton(item, name) {
    const audio = item.media_kind === "audio";
    const cover = audio && item.cover_item
      ? `<div class="audiocover" style="background-image:url('${displayUrl(item.cover_item)}')"></div>`
      : audio ? `<span class="audioglyph" aria-hidden="true">♪</span>` : "";
    root.innerHTML = `
      <div class="lphead">
        <span class="cltitle">✂ ${esc(STRINGS.clipTitle)}</span>
        <span class="vmono">${esc(name)}</span>
        <span class="lpmeta" id="clDur"></span>
        <div class="lpspacer"></div>
        <button type="button" id="clClose" title="${esc(STRINGS.clipClose)}">✕</button>
      </div>
      <div class="clbody">
        <div class="clstage${audio ? " audio" : ""}" id="clStage">${cover}</div>
        <div class="cltl">
          <span class="tm">${fmtTime(0)}</span>
          <div class="cltrack${audio ? " wave" : ""}" id="clTrack" title="${esc(STRINGS.clipTrackTitle)}">
            <canvas></canvas>
            <div class="clrange" id="clRange"><span class="clh a"></span><span class="clh b"></span></div>
            <span class="clph" id="clPh"></span>
          </div>
          <span class="tm" id="clTotal"></span>
        </div>
        <div class="clrow">
          <button type="button" class="pbtn" id="clPlay" title="${esc(STRINGS.clipPlayTitle)}">▶</button>
          <span class="vmono clpos" id="clPos"></span>
          <label>${esc(STRINGS.clipStart)} <input id="clA" inputmode="decimal" autocomplete="off"></label>
          <button type="button" id="clAHere" title="${esc(STRINGS.clipStartHereTitle)}">${esc(STRINGS.clipHere)}</button>
          <label>${esc(STRINGS.clipEnd)} <input id="clB" inputmode="decimal" autocomplete="off"></label>
          <button type="button" id="clBHere" title="${esc(STRINGS.clipEndHereTitle)}">${esc(STRINGS.clipHere)}</button>
          <label>${esc(STRINGS.clipLength)} <input id="clLen" inputmode="decimal" autocomplete="off"> s</label>
        </div>
        <div class="clrow"><span class="lab">${esc(STRINGS.clipOutput)}</span><span id="clOut" class="clout"></span></div>
        <div class="clrow"><span class="lab">${esc(STRINGS.clipTarget)}</span><span class="vmono" id="clTarget"></span></div>
        <div class="clrow">
          <span class="clmsg" id="clMsg"></span>
          <div class="lpspacer"></div>
          <button type="button" class="primary" id="clGo" disabled>${esc(STRINGS.exportGo)}</button>
        </div>
        <div class="clresults" id="clResults"></div>
      </div>
      <div class="lpfoot"><div>${esc(STRINGS.clipHint)}</div></div>`;
  }

  // -- Zeichnen ------------------------------------------------------------------

  const pct = (t) => `${st.dur > 0 ? clamp(t / st.dur, 0, 1) * 100 : 0}%`;

  function paintRange() {
    const { a, b } = st.range;
    const box = $("#clRange");
    box.style.left = pct(a);
    box.style.width = `${st.dur > 0 ? ((b - a) / st.dur) * 100 : 0}%`;
    box.dataset.active = st.active;
    const set = (id, text) => { const f = $(id); if (document.activeElement !== f) f.value = text; };
    set("#clA", fmtTime(a));
    set("#clB", fmtTime(b));
    set("#clLen", (b - a).toFixed(1));
  }

  function paintPlayhead() {
    if (!st) return;
    const t = st.media.currentTime || 0;
    $("#clPh").style.left = pct(t);
    $("#clPos").textContent = fmtTime(t);
    $("#clPlay").textContent = st.media.paused ? "▶" : "❚❚";
  }

  function paintWave() {
    if (st?.analysis) {
      drawWave($("#clTrack canvas"), st.analysis, { axis: st.dur, duration: st.dur });
    }
  }

  function paintTotal() {
    $("#clTotal").textContent = fmtTime(st.dur);
    $("#clDur").textContent = fmtTime(st.dur);
  }

  // -- Abspielen -----------------------------------------------------------------

  function seek(t) {
    st.media.currentTime = clamp(t, 0, st.dur);
    st.last = st.media.currentTime;
    paintPlayhead();
  }

  /** Über das Ende des Bereichs gelaufen (von innen) → zurück an den Anfang. */
  function tick() {
    if (!st) return;
    const t = st.media.currentTime || 0;
    if (!st.media.paused && st.last < st.range.b && t >= st.range.b) {
      st.media.currentTime = st.range.a;
      st.last = st.range.a;
    } else {
      st.last = t;
    }
    paintPlayhead();
    st.raf = st.media.paused ? null : requestAnimationFrame(tick);
  }

  function togglePlay() {
    const m = st.media;
    if (!m.paused) { m.pause(); return; }
    if ((m.currentTime || 0) >= st.dur - 0.05) seek(st.range.a);   // am Dateiende: von vorn
    m.play()?.catch?.(() => {});
  }

  /** Nach einer Änderung dort anhören, wo sie wirkt: am neuen Anfang bzw.
   *  kurz vor dem neuen Ende. */
  function edited(which) {
    st.active = which === "b" ? "b" : "a";
    seek(which === "b" ? Math.max(st.range.a, st.range.b - PREROLL) : st.range.a);
    paintRange();
  }

  function setRange(range, which) {
    st.range = range;
    edited(which);
  }

  // -- Ausgabe, Ziel, Sperren -----------------------------------------------------

  function chosenOutputs() {
    const allowed = st.state?.outputs || [];
    if (allowed.length <= 1) return [...allowed];
    return [...root.querySelectorAll("#clOut input")].filter((c) => c.checked && !c.disabled)
      .map((c) => c.value);
  }

  function paintState() {
    const s = st.state;
    const out = $("#clOut");
    const videoOk = s.encoder === "ok";
    const labels = { av: STRINGS.clipOutAv, video: STRINGS.clipOutVideo, audio: STRINGS.clipOutAudio };
    if (s.outputs.length > 1) {
      const saved = readOutputs();
      out.innerHTML = s.outputs.map((o) => {
        const off = o !== "audio" && !videoOk;
        return `<label><input type="checkbox" value="${o}"${saved.includes(o) && !off ? " checked" : ""}${off ? " disabled" : ""}> ${esc(labels[o])}</label>`;
      }).join("");
    } else {
      out.textContent = s.outputs[0] === "video" ? STRINGS.clipOutVideoSilent : STRINGS.clipOutAudio;
    }
    $("#clTarget").textContent = s.target || "";
    let reason = s.reason ? serverMsg(s.reason) : "";
    if (!reason && s.encoder === "no-ffmpeg") reason = STRINGS.clipNoFfmpeg;
    else if (!reason && !videoOk && s.outputs.some((o) => o !== "audio")) reason = STRINGS.clipNoH264;
    $("#clMsg").textContent = reason;
    paintGo();
  }

  function paintGo() {
    const s = st.state;
    const blocked = !s || !s.available || s.encoder === "no-ffmpeg";
    $("#clGo").disabled = blocked || chosenOutputs().length === 0;
  }

  // -- Exportieren ----------------------------------------------------------------

  function resultRow(text) {
    const row = document.createElement("div");
    row.className = "clres";
    row.textContent = text;
    const box = $("#clResults");
    box.insertBefore(row, box.firstChild);      // jüngstes Ergebnis oben
    return row;
  }

  async function go() {
    const outputs = chosenOutputs();
    if (!outputs.length) return;
    const token = newToken();
    const { a, b } = st.range;
    const row = resultRow(STRINGS.clipWriting);
    $("#clGo").disabled = true;
    pending.set(token, row);              // vor der Anfrage: die Aufgabe kann schneller sein
    try {
      const res = await startClip(st.item.file_hash, { start: a, end: b, outputs, token });
      row.dataset.files = res.files.join(" · ");
      if (pending.has(token)) row.textContent = `${STRINGS.clipWriting} ${row.dataset.files}`;
    } catch (err) {
      pending.delete(token);
      row.classList.add("warn");
      row.textContent = `⚠ ${err.message}`;
    }
    if (st) paintGo();
  }

  /** Fertige Aufgabe: ihre Zeile zeigt das Ergebnis und je Datei „📂 zeigen". */
  function finished(status) {
    for (const entry of status.history || []) {
      const params = entry.result?.params;
      const row = params?.token && pending.get(params.token);
      if (!row) continue;
      pending.delete(params.token);
      const files = params.files || [];
      row.classList.toggle("warn", !files.length || entry.result.key !== "sumClip");
      row.textContent = files.length ? "" : serverMsg(entry.result);
      for (const path of files) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "clfile";
        b.title = STRINGS.revealTitle;
        b.textContent = `📂 ${baseName(path)}`;
        b.addEventListener("click", () => revealExportPath(path).catch((err) => {
          b.textContent = `⚠ ${err.message}`;
        }));
        row.appendChild(b);
      }
      const errors = (params.parts || []).filter((p) => p.key === "sumExportErrors");
      if (errors.length) {
        const note = document.createElement("span");
        note.className = "clnote";
        note.textContent = ` ⚠ ${serverMsg(errors)}`;
        row.appendChild(note);
      }
    }
  }

  onTaskFinished(finished);
  onStatus((s) => {
    // Angehaltene Hintergrundarbeit: sagen, warum nichts fertig wird.
    for (const row of pending.values()) {
      row.textContent = `${s.paused ? STRINGS.clipWaitingPaused : STRINGS.clipWriting} ${row.dataset.files || ""}`;
    }
  });

  // -- Öffnen / Schließen ---------------------------------------------------------

  async function open(item) {
    if (st) close();
    if (!root || !item || !(item.duration > 0)) return;
    const hash = item.file_hash;
    const name = item.name || baseName(item.locations?.[0]?.path || hash.slice(0, 16));
    const position = positionBefore(item);
    const loop = item.media_kind === "audio" ? loopOf(hash) : null;
    pausePlayer();
    const parked = parkVideos();

    skeleton(item, name);
    const media = document.createElement(item.media_kind === "audio" ? "audio" : "video");
    media.preload = "auto";
    if (item.media_kind === "video") {
      media.playsInline = true;
      $("#clStage").appendChild(media);
    }
    const dur = item.duration;
    st = { item, media, dur, parked, range: initialRange({ duration: dur, position, loop }),
           active: "a", last: 0, raf: null, state: null, analysis: null, drag: null,
           unregister: null };
    const mine = st;
    root.hidden = false;
    st.unregister = registerDialog(root, close);

    media.addEventListener("loadedmetadata", () => {
      if (st !== mine) return;
      if (Number.isFinite(media.duration) && media.duration > 0) {
        st.dur = media.duration;
        st.range = moveRange(st.range, st.range.a, st.dur);
        paintTotal();
        paintWave();
      }
      seek(st.range.a);
      paintRange();
    });
    for (const ev of ["play", "pause", "seeked"]) {
      media.addEventListener(ev, () => {
        if (st !== mine) return;
        paintPlayhead();
        if (ev === "play" && !st.raf) st.raf = requestAnimationFrame(tick);
      });
    }
    media.addEventListener("ended", () => {
      if (st !== mine) return;
      // Reicht der Bereich bis ans Dateiende, ist das Ende der Datei sein
      // Ende: weiter in Schleife. Sonst bleibt es am Anfang stehen.
      const loops = st.last >= st.range.a && st.range.b >= st.dur - 0.25;
      seek(st.range.a);
      if (loops) media.play()?.catch?.(() => {});
    });
    media.src = item.media_kind === "audio" ? displayUrl(item) : mediaUrl(hash);

    wire();
    paintTotal();
    paintRange();
    paintPlayhead();

    try {
      const state = await getClipState(hash);
      if (st !== mine) return;
      st.state = state;
      paintState();
    } catch (err) {
      if (st !== mine) return;
      $("#clMsg").textContent = err.message;
    }
    if (item.media_kind === "audio") {
      try {
        const analysis = await getAudioAnalysis(hash, { isStale: () => st !== mine });
        if (st !== mine || !analysis) return;
        st.analysis = analysis;
        paintWave();
      } catch { /* ohne Wellenform bleibt der schlichte Balken */ }
    }
  }

  function close() {
    if (!st) return;
    const old = st;
    st = null;
    old.unregister?.();
    if (old.raf) cancelAnimationFrame(old.raf);
    releaseVideo(old.media);
    pending.clear();
    root.hidden = true;
    root.innerHTML = "";
    unparkVideos(old.parked);
  }

  // -- Verdrahtung ----------------------------------------------------------------

  function wire() {
    const track = $("#clTrack");
    const timeAt = (e) => {
      const r = track.getBoundingClientRect();
      return r.width > 0 ? clamp((e.clientX - r.left) / r.width, 0, 1) * st.dur : 0;
    };
    track.addEventListener("pointerdown", (e) => {
      if (!st) return;
      const handle = e.target.closest?.(".clh");
      const which = handle ? (handle.classList.contains("b") ? "b" : "a")
        : e.target.closest?.(".clrange") ? "move" : "seek";
      const t = timeAt(e);
      st.drag = { which, grab: t - st.range.a, moved: false };
      track.setPointerCapture?.(e.pointerId);
      e.preventDefault();
      if (which === "seek") seek(t);
    });
    track.addEventListener("pointermove", (e) => {
      const d = st?.drag;
      if (!d) return;
      const t = timeAt(e);
      d.moved = true;
      if (d.which === "seek") { seek(t); return; }
      if (d.which === "a") st.range = dragStart(st.range, t);
      else if (d.which === "b") st.range = dragEnd(st.range, t, st.dur);
      else st.range = moveRange(st.range, t - d.grab, st.dur);
      st.active = d.which === "b" ? "b" : "a";
      paintRange();
    });
    const drop = (e) => {
      const d = st?.drag;
      if (!d) return;
      st.drag = null;
      if (d.which === "seek") return;
      if (d.moved) edited(d.which);
      else seek(timeAt(e));               // Klick in den Bereich ohne Ziehen: nur hinspringen
    };
    track.addEventListener("pointerup", drop);
    track.addEventListener("pointercancel", () => { if (st) st.drag = null; });

    $("#clClose").addEventListener("click", close);
    $("#clPlay").addEventListener("click", togglePlay);
    $("#clStage").addEventListener("click", togglePlay);
    $("#clAHere").addEventListener("click", () =>
      setRange(markStart(st.range, st.media.currentTime || 0, st.dur), "a"));
    $("#clBHere").addEventListener("click", () =>
      setRange(markEnd(st.range, st.media.currentTime || 0, st.dur), "b"));
    const field = (id, apply, which) => $(id).addEventListener("change", (e) => {
      const t = parseTime(e.target.value);
      e.target.blur();                    // erst loslassen: paintRange füllt das Feld neu
      if (t !== null) setRange(apply(t), which);
      else paintRange();
    });
    field("#clA", (t) => markStart(st.range, t, st.dur), "a");
    field("#clB", (t) => markEnd(st.range, t, st.dur), "b");
    field("#clLen", (t) => setLength(st.range, t, st.dur), "b");
    $("#clOut").addEventListener("change", () => {
      if (st.state?.outputs.length > 1) saveOutputs(chosenOutputs());
      paintGo();
    });
    $("#clGo").addEventListener("click", go);
  }

  on("clip-open", (d) => open(d?.item));

  // Solange die Ansicht offen ist, gehören ihr ALLE Tasten: nichts darunter
  // (Einzelansicht, Player, Galerie) sieht sie. Esc nimmt overlays.js vorher.
  document.addEventListener("keydown", (e) => {
    if (!st || e.key === "Escape") return;
    e.stopPropagation();
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const typing = e.target instanceof Element && e.target.matches("input, textarea, select");
    if (typing) {
      if (e.key === "Enter") e.target.blur();   // 'change' übernimmt den Wert
      return;
    }
    const step = e.shiftKey ? 1 : 0.1;
    const nudge = (delta) => {
      const r = st.range;
      setRange(st.active === "b" ? dragEnd(r, r.b + delta, st.dur) : dragStart(r, r.a + delta),
               st.active);
    };
    if (e.key === " ") { e.preventDefault(); togglePlay(); }
    else if (e.key === "i" || e.key === "I") setRange(markStart(st.range, st.media.currentTime || 0, st.dur), "a");
    else if (e.key === "o" || e.key === "O") setRange(markEnd(st.range, st.media.currentTime || 0, st.dur), "b");
    else if (e.key === "ArrowLeft") { e.preventDefault(); nudge(-step); }
    else if (e.key === "ArrowRight") { e.preventDefault(); nudge(step); }
  }, true);

  window.addEventListener("resize", () => { if (st) { paintWave(); paintPlayhead(); } });

  return { isOpen: () => !!st, close };
}
