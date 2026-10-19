// lyricsedit.js — Songtext von Hand (ADR 0106, #285).
//
// Ansicht „Songtext bearbeiten" über allem, was gerade offen ist (wie der
// Ausschnitt, ADR 0105). Einstieg ist die Zeile „Songtext" unter KURATIERT
// im Panel ('lyrics-edit-open' mit dem Item). ✕ oder Esc schließt
// (overlays.js); mit ungespeicherten Änderungen erscheint daneben
// „Ungespeicherte Änderungen" mit Speichern, Verwerfen und Abbrechen. Esc
// heißt dann Abbrechen: verworfen wird nur mit dem Knopf.
//
// Eine Zeilenliste, je Zeile ▶, Zeit und Text, ohne Modi: Was eine Taste
// tut, hängt am Feld, in dem der Cursor steht.
// - Text: Enter teilt die Zeile an der Schreibmarke, Rückschritt am Anfang
//   verbindet mit der Zeile davor, Entf am Ende mit der danach, ↑/↓ wechseln
//   die Zeile. Mehrzeiliger Text aus der Zwischenablage wird zu Zeilen.
//   Eine Zeile in eckigen Klammern ist eine Abschnittsmarke ([Chorus]).
// - Zeit (#286): Eintippen (1:23.4, 83,4, 83), Enter übernimmt und geht
//   zur nächsten Zeile (wie in einer Tabelle); Verlassen übernimmt auch.
//   Strg/⌘+Enter setzt die Zeile an die Abspielstelle und geht weiter, aus
//   dem Zeit- wie aus dem Textfeld (Mitklopfen: Song laufen lassen, bei
//   jeder Zeile Strg/⌘+Enter). ↑/↓ wechseln die Zeile; Entf nimmt die Zeit
//   weg; Leertaste spielt.
// - ▶ vor der Zeile spielt ab 1 s vor ihrem Anfang.
// - Die Abspielzeit steht groß links neben der Liste, fest in der
//   senkrechten Mitte der Ansicht: Sie springt nie, auch nicht beim Anhalten.
// - Hat der Song Zeiten, bekommt jede neue Zeile die Mitte zwischen ihren
//   Nachbarn (geschätzt, kursiv). Beginnt eine Zeile vor der davor, ist
//   ihre Zeit rot und Speichern gesperrt.
// - Speichern schreibt die ganze Fassung; „Stand der Datei wiederherstellen"
//   verwirft sie (zweistufig, kein System-Dialog).
//
// Nach dem Speichern: 'fields-changed' {hashes, fields: ["lyrics"], items}
// — Liste ersetzt die Zeile, Seitenleiste zählt neu, Panel und Songtext-
// Zwischenspeicher (lyrics.js) ziehen nach.
//
// Tasten: solange die Ansicht offen ist, sieht keine Ebene darunter einen
// Tastendruck (Capture-Listener, wie beim Ausschnitt).

import { STRINGS } from "./strings.js";
import { getLyricsState, setLyrics } from "./api.js";
import { emit, on } from "./main.js";
import { registerDialog } from "./overlays.js";
import { isSection } from "./lyrics.js";
import { playingHash, positionOf, seek, toggle } from "./player.js";
import { parseTime } from "./clip.js";

const PREROLL = 1;   // ▶ vor einer Zeile: so viele Sekunden davor anhören

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// -- Zeilen (rein, getestet) -------------------------------------------------------
//
// Eine Zeile im Editor: {s, e, t, est} — Start/Ende in ms (oder null), Text,
// est = Zeit geschätzt (nur Anzeige). Leerzeilen trennen Strophen und
// tragen keine Zeit.

const fold = (t) => String(t ?? "").split(/\s+/).filter(Boolean).join(" ");

export const fromServer = (lines) =>
  (Array.isArray(lines) ? lines : []).map(([s, e, t]) => ({ s: s ?? null, e: e ?? null, t: t ?? "", est: false }));

/** Fürs Speichern wie der Server (manual_lyrics.check_lines): Leerraum
 *  gefaltet, Leerzeilen am Rand weg, mehrere hintereinander werden eine. */
export function toServer(model) {
  const out = [];
  for (const line of model) {
    const t = fold(line.t);
    if (!t) {
      if (out.length && out[out.length - 1][2]) out.push([null, null, ""]);
      continue;
    }
    out.push([line.s, line.s === null ? null : line.e, t]);
  }
  while (out.length && !out[out.length - 1][2]) out.pop();
  return out;
}

/** Zeiten für NEUE Zeilen (`fresh`: eben eingefügt, geteilt oder eine
 *  Leerzeile, die Text bekam): Hat der Song Zeiten, bekommt jede neue
 *  Textzeile ohne Zeit eine gleichmäßige Stelle zwischen der Zeile mit Zeit
 *  davor (sonst 0) und der danach (sonst das Songende). Zeilen, die schon
 *  vorher keine Zeit hatten (halb geklopft), bleiben ohne. */
export function fillTimes(model, durMs) {
  const text = (l) => fold(l.t) !== "";
  const wanted = (l) => text(l) && l.s === null && l.fresh;
  if (!model.some((l) => text(l) && l.s !== null)) return model;
  let i = 0;
  while (i < model.length) {
    if (!wanted(model[i])) { i++; continue; }
    const run = [];
    let j = i;
    for (; j < model.length; j++) {
      if (!text(model[j])) continue;
      if (!wanted(model[j])) break;
      run.push(j);
    }
    let lo = 0;
    for (let k = i - 1; k >= 0; k--) if (model[k].s !== null) { lo = model[k].s; break; }
    let hi = null;
    for (let k = j; k < model.length; k++) if (model[k].s !== null) { hi = model[k].s; break; }
    if (hi === null) hi = Math.max(lo, durMs || lo);
    run.forEach((k, n) => {
      model[k].s = Math.round(lo + ((hi - lo) * (n + 1)) / (run.length + 1));
      model[k].e = null;
      model[k].est = true;
      model[k].fresh = false;
    });
    i = j;
  }
  return model;
}

/** Nächste Zeile mit Text ab `i` in Richtung `dir` (-1 / +1); -1 = keine.
 *  Leerzeilen trennen nur Strophen und tragen keine Zeit. */
export function textLine(model, i, dir) {
  for (let j = i; j >= 0 && j < model.length; j += dir) if (fold(model[j].t)) return j;
  return -1;
}

/** Zeile `i` beginnt bei `ms` (Mitklopfen, Eintippen). Ein Ende, das
 *  davor läge, fällt weg (Singdauer-Regel); eine Schätzung ist damit
 *  ersetzt. */
export function tapAt(model, i, ms) {
  const line = model[i];
  line.s = Math.max(0, Math.round(ms));
  line.est = false;
  line.fresh = false;
  if (line.e !== null && line.e <= line.s) line.e = null;
}

/** Zeilen, die vor der Zeile mit Zeit davor beginnen: Beim Neu-Klopfen eines
 *  getimten Songs entsteht das kurz, bis die folgenden Zeilen auch geklopft
 *  sind. Angezeigt, Speichern ist solange gesperrt. */
export function orderErrors(model) {
  const bad = new Set();
  let last = -1;
  model.forEach((l, i) => {
    if (!fold(l.t) || l.s === null) return;
    if (l.s < last) bad.add(i); else last = l.s;
  });
  return bad;
}

/** Leerzeilen zählen nicht; Zeilen ohne Zeit in einem Song mit Zeiten. */
export const missingTimes = (model) => model.filter((l) => fold(l.t) && l.s === null).length;
export const hasTimes = (model) => model.some((l) => fold(l.t) && l.s !== null);

/** Enter: Zeile `i` an der Schreibmarke teilen. Die neue Zeile bekommt den
 *  Rest und das Ende der alten; die alte endet offen (Singdauer-Regel). */
export function splitAt(model, i, from, to = from) {
  const line = model[i];
  const rest = { s: null, e: line.e, t: line.t.slice(to), est: false, fresh: true };
  line.t = line.t.slice(0, from);
  line.e = null;
  model.splice(i + 1, 0, rest);
  return { i: i + 1, caret: 0 };
}

const glue = (a, b) => (a && b && !/\s$/.test(a) && !/^\s/.test(b) ? `${a} ${b}` : a + b);

/** Rückschritt am Zeilenanfang: mit der Zeile davor verbinden (eine leere
 *  Zeile davor verschwindet einfach). */
export function joinUp(model, i) {
  if (i <= 0) return null;
  const prev = model[i - 1];
  const cur = model[i];
  if (!fold(prev.t)) {
    model.splice(i - 1, 1);
    return { i: i - 1, caret: 0 };
  }
  const caret = glue(prev.t, cur.t).length - cur.t.length;
  prev.t = glue(prev.t, cur.t);
  if (cur.e !== null) prev.e = cur.e;
  model.splice(i, 1);
  return { i: i - 1, caret };
}

/** Entf am Zeilenende: die Zeile danach anhängen. */
export function joinDown(model, i) {
  if (i >= model.length - 1) return null;
  const caret = model[i].t.length;
  const at = joinUp(model, i + 1);
  return at && fold(model[at.i].t) ? { i, caret } : at;
}

/** Text einfügen: mehrere Zeilen werden zu Zeilen, die erste an der
 *  Schreibmarke, die letzte vor dem Rest der Zeile. */
export function pasteAt(model, i, from, to, text) {
  const parts = String(text).replace(/\r\n?/g, "\n").split("\n");
  const line = model[i];
  const tail = line.t.slice(to);
  if (parts.length === 1) {
    line.t = line.t.slice(0, from) + parts[0] + tail;
    return { i, caret: from + parts[0].length };
  }
  line.t = line.t.slice(0, from) + parts[0];
  const last = parts.length - 1;
  const added = parts.slice(1).map((t, n) => ({
    s: null, e: n === last - 1 ? line.e : null, t: n === last - 1 ? t + tail : t, est: false,
    fresh: true }));
  line.e = null;
  model.splice(i + 1, 0, ...added);
  return { i: i + last, caret: parts[last].length };
}

/** Zeit für die Anzeige: m:ss.t, ohne Zeit ein Strich. */
export function fmtMs(ms) {
  if (ms === null || ms === undefined) return "–";
  const tenth = Math.round(ms / 100);
  const m = Math.floor(tenth / 600);
  const s = (tenth % 600) / 10;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}

// -- Einstieg im Panel ----------------------------------------------------------------

/** Zeile „Songtext" unter KURATIERT (nur Songs, nur ein Song ausgewählt). */
export function lyricsRowHtml(d) {
  const rows = (d.interpreted || []).filter((f) => f.field === "lyrics" && f.value);
  const manual = rows.some((f) => f.parser === "manual");
  const state = manual ? STRINGS.lyricsStateManual
    : rows.length ? STRINGS.lyricsStateFile : STRINGS.lyricsStateNone;
  return `<div class="lyedrow">
    <span class="mflabel">${esc(STRINGS.lyricsEditTitle)}</span>
    <span class="lyedstate${manual ? " manual" : ""}"${manual ? ` title="${esc(STRINGS.lyricsManualTitle)}"` : ""}>${esc(state)}</span>
    <button type="button" id="pLyEdit" title="${esc(STRINGS.lyricsEditOpenTitle)}">${esc(rows.length ? STRINGS.lyricsEditButton : STRINGS.lyricsEnterButton)}</button>
  </div>`;
}

// -- Ansicht ----------------------------------------------------------------------

export function initLyricsEdit() {
  const root = document.getElementById("lyedit");
  let st = null;
  const $ = (sel) => root.querySelector(sel);

  function skeleton(name) {
    root.innerHTML = `
      <div class="lphead">
        <span class="cltitle">✎ ${esc(STRINGS.lyricsViewTitle)}</span>
        <span class="vmono">${esc(name)}</span>
        <span class="lyedstate" id="lyState"></span>
        <div class="lpspacer"></div>
        <button type="button" class="pbtn" id="lyPlay" title="${esc(STRINGS.lyricsPlayTitle)}">▶</button>
        <span class="lyleave" id="lyLeave" hidden>
          <span>${esc(STRINGS.lyricsUnsaved)}</span>
          <button type="button" class="primary" id="lyLeaveSave">${esc(STRINGS.lyricsSave)}</button>
          <button type="button" id="lyLeaveDrop">${esc(STRINGS.lyricsDiscard)}</button>
          <button type="button" id="lyLeaveCancel" title="${esc(STRINGS.lyricsCancelTitle)}">${esc(STRINGS.lyricsCancel)}</button>
        </span>
        <button type="button" id="lyClose" title="${esc(STRINGS.lyricsClose)}">✕</button>
      </div>
      <div class="lystage">
        <button type="button" class="lyclock" id="lyClock" title="${esc(STRINGS.lyricsPlayTitle)}"><i>▶</i><span>0:00.0</span></button>
        <div class="lybody"><div class="lywrap"><div class="lylist" id="lyList"></div></div></div>
      </div>
      <div class="lybar">
        <span class="lynote" id="lyNote"></span>
        <div class="lpspacer"></div>
        <button type="button" id="lyRestore" hidden>${esc(STRINGS.lyricsRestore)}</button>
        <button type="button" class="primary" id="lySave" disabled>${esc(STRINGS.lyricsSave)}</button>
      </div>
      <div class="lpfoot"><div>${esc(STRINGS.lyricsHint)}</div></div>`;
  }

  const durMs = () => (st.duration > 0 ? Math.round(st.duration * 1000) : 0);
  const payload = () => JSON.stringify(toServer(st.model));
  const dirty = () => payload() !== st.saved;

  function rowHtml(line, i) {
    const text = fold(line.t) !== "";
    const cls = `lyrow${isSection(fold(line.t)) ? " sec" : ""}`;
    return `<div class="${cls}" data-i="${i}">
      <button type="button" class="lyplay" tabindex="-1" title="${esc(STRINGS.lyricsPlayLine)}"${line.s === null ? " disabled" : ""}>▶</button>
      <input class="lytime${line.est ? " est" : ""}" value="${line.s === null ? "" : fmtMs(line.s)}" placeholder="–"
        inputmode="decimal" spellcheck="false" autocomplete="off"
        title="${esc(line.est ? STRINGS.lyricsEstimated : STRINGS.lyricsTimeTitle)}"${text ? "" : " disabled"}>
      <input class="lytext" value="${esc(line.t)}" spellcheck="false" autocomplete="off"${i === 0 ? ` placeholder="${esc(STRINGS.lyricsPlaceholder)}"` : ""}>
      <button type="button" class="lydel" tabindex="-1" title="${esc(STRINGS.lyricsDelete)}">✕</button>
    </div>`;
  }

  function render(focus = null) {
    if (!st.model.length) st.model.push({ s: null, e: null, t: "", est: false });
    $("#lyList").innerHTML = st.model.map(rowHtml).join("");
    st.at = -1;
    paintTimes();
    paintState();
    if (focus) focusRow(focus.i, focus.caret);
  }

  function focusRow(i, caret) {
    const input = $(`#lyList .lyrow[data-i="${Math.max(0, Math.min(i, st.model.length - 1))}"] .lytext`);
    if (!input) return;
    input.focus();
    const at = Math.min(caret ?? input.value.length, input.value.length);
    input.setSelectionRange?.(at, at);
  }

  /** Ins Zeitfeld einer Zeile, Inhalt markiert: Tippen ersetzt ihn. */
  function focusTime(i) {
    const input = $(`#lyList .lyrow[data-i="${i}"] .lytime`);
    if (!input) return;
    input.focus();
    input.select?.();
  }

  const timeInput = (i) => $(`#lyList .lyrow[data-i="${i}"] .lytime`);

  /** Zeiten, Schätzungen, Reihenfolge und Abschnitte an Ort und Stelle. Ein
   *  Zeitfeld, in dem gerade getippt wird, behält seinen Text. */
  function paintTimes() {
    const bad = orderErrors(st.model);
    for (const row of root.querySelectorAll(".lyrow")) {
      const i = Number(row.dataset.i);
      const line = st.model[i];
      if (!line) continue;
      const input = row.querySelector(".lytime");
      const text = fold(line.t) !== "";
      if (!input.dataset.typed) input.value = line.s === null ? "" : fmtMs(line.s);
      input.disabled = !text;
      input.classList.toggle("est", line.est);
      input.classList.toggle("bad", bad.has(i));
      input.title = bad.has(i) ? STRINGS.lyricsOrderTitle
        : line.est ? STRINGS.lyricsEstimated : STRINGS.lyricsTimeTitle;
      row.querySelector(".lyplay").disabled = line.s === null;
      row.classList.toggle("sec", isSection(fold(line.t)));
    }
  }

  function paintState() {
    const state = $("#lyState");
    state.textContent = st.manual ? STRINGS.lyricsStateManual : STRINGS.lyricsStateFile;
    state.hidden = !st.manual && !st.fromFile;
    state.classList.toggle("manual", st.manual);
    state.title = st.manual && st.source ? STRINGS.lyricsFrom.replace("{source}", st.source) : "";
    $("#lyRestore").hidden = !st.manual;
    $("#lyLeave").hidden = !st.armedClose;
    const bad = orderErrors(st.model);
    $("#lySave").disabled = st.busy || !dirty() || bad.size > 0;
    if (st.message) { $("#lyNote").textContent = st.message; return; }
    if (bad.size) {
      $("#lyNote").textContent = STRINGS.lyricsOrderNote.replace("{n}", Math.min(...bad) + 1);
      return;
    }
    const missing = missingTimes(st.model);
    const any = toServer(st.model).some((l) => l[2]);
    $("#lyNote").textContent = !any ? ""
      : !hasTimes(st.model) ? STRINGS.lyricsNoTimes
        : missing ? STRINGS.lyricsMissing.replace("{n}", missing) : "";
  }

  function edited() {
    st.message = "";
    st.armedClose = false;
    st.armedRestore = false;
    $("#lyRestore").textContent = STRINGS.lyricsRestore;
    fillTimes(st.model, durMs());
    paintTimes();
    paintState();
  }

  function apply(state, message) {
    st.model = fromServer(state.lines);
    st.saved = payload();
    st.manual = !!state.manual;
    st.source = state.source || null;
    st.fromFile = !state.manual && st.model.length > 0;
    st.message = message || "";
    render();
  }

  async function save(lines, message) {
    if (st.busy) return;
    st.busy = true;
    paintState();
    const mine = st;
    try {
      const d = await setLyrics(st.item.file_hash, lines);
      if (st !== mine) return;
      st.busy = false;
      const leave = st.armedClose;   // „Speichern" in der Nachfrage: danach schließen
      st.armedClose = false;
      apply(d.state, message);
      emit("fields-changed", { hashes: [st.item.file_hash], fields: ["lyrics"], items: d.items || [] });
      if (leave) close(true);
    } catch (err) {
      if (st !== mine) return;
      st.busy = false;
      st.message = err.message;
      paintState();
    }
  }

  // -- Zeiten ---------------------------------------------------------------------

  /** Getipptes übernehmen (Enter oder Verlassen): leer = keine Zeit.
   *  Ungültiges: mit `keep` (Enter) bleibt es zum Korrigieren stehen, sonst
   *  (Verlassen) wird es verworfen und die alte Zeit bleibt; beides mit
   *  Hinweis. false = ungültig. */
  function commitTyped(i, keep = false) {
    const input = timeInput(i);
    const line = st.model[i];
    if (!input || !line || !input.dataset.typed) return true;
    const raw = input.value.trim();
    const sec = raw ? parseTime(raw) : null;
    if (raw && sec === null) {
      st.message = STRINGS.lyricsTimeInvalid;
      if (keep) { paintState(); return false; }
      delete input.dataset.typed;
    } else {
      delete input.dataset.typed;
      setTime(i, raw ? Math.round(sec * 1000) : null);
      st.message = "";
    }
    st.armedClose = false;
    paintTimes();
    paintState();
    return true;
  }

  /** Strg/⌘+Enter: Zeile `i` beginnt an der Abspielstelle, weiter zur
   *  nächsten Zeile mit Text, im selben Feld (Zeit oder Text). */
  function setNow(i, field) {
    const input = timeInput(i);
    if (input) delete input.dataset.typed;
    setTime(i, positionOf(st.item.file_hash) * 1000);
    st.message = "";
    st.armedClose = false;
    paintTimes();
    paintState();
    const next = textLine(st.model, i + 1, 1);
    if (next < 0) return;
    if (field === "time") focusTime(next);
    else focusRow(next, null);
  }

  /** Zeit einer Zeile setzen (null = keine), begrenzt auf den Song. */
  function setTime(i, ms) {
    const line = st.model[i];
    if (ms === null) Object.assign(line, { s: null, e: null, est: false, fresh: false });
    else tapAt(st.model, i, Math.min(ms, durMs() || Infinity));
  }

  // -- Abspielen --------------------------------------------------------------

  function tick() {
    if (!st) return;
    const hash = st.item.file_hash;
    const pos = positionOf(hash);
    const playing = playingHash() === hash;
    $("#lyPlay").textContent = playing ? "❚❚" : "▶";
    const clock = $("#lyClock");
    clock.querySelector("span").textContent = fmtMs(pos * 1000);
    clock.querySelector("i").textContent = playing ? "❚❚" : "▶";
    clock.classList.toggle("playing", playing);
    let at = -1;
    if (playing) st.model.forEach((l, i) => { if (l.s !== null && l.s <= pos * 1000) at = i; });
    if (at !== st.at) {
      root.querySelector(".lyrow.on")?.classList.remove("on");
      if (at >= 0) root.querySelector(`.lyrow[data-i="${at}"]`)?.classList.add("on");
      st.at = at;
    }
    st.raf = requestAnimationFrame(tick);
  }

  // -- Öffnen / Schließen -----------------------------------------------------------

  async function open(item) {
    if (st) close(true);
    if (!root || !item) return;
    skeleton(item.name || item.file_hash.slice(0, 16));
    st = { item, duration: item.duration || 0, model: [], saved: "[]", manual: false,
           source: null, fromFile: false, message: "", busy: true, at: -1, raf: null,
           armedClose: false, armedRestore: false, unregister: null };
    const mine = st;
    root.hidden = false;
    st.unregister = registerDialog(root, close);
    wire();
    st.raf = requestAnimationFrame(tick);
    try {
      const state = await getLyricsState(item.file_hash);
      if (st !== mine) return;
      st.busy = false;
      if (state.duration > 0) st.duration = state.duration;
      apply(state);
      focusRow(0, 0);
    } catch (err) {
      if (st !== mine) return;
      st.message = err.message;
      $("#lyNote").textContent = err.message;
    }
  }

  /** Schließen. Mit ungespeicherten Änderungen kommt erst die Nachfrage
   *  neben ✕; ist sie schon offen, heißt Esc Abbrechen und ✕ ändert
   *  nichts. `true` schließt immer (Verwerfen, Speichern). overlays.js hat
   *  den Dialog beim Esc schon abgemeldet; bleibt er offen, meldet er sich
   *  neu an. */
  function close(how = "esc") {
    if (!st) return;
    if (how !== true && dirty()) {
      if (how === "esc") {
        // Esc kommt über overlays.js, das den Dialog schon abgemeldet hat.
        // Erst im nächsten Mikrotask neu anmelden: closeAllDialogs (Ansichts-
        // wechsel) ruft in einer Schleife, bis der Stapel leer ist; die
        // Ansicht bleibt dann mit der Nachfrage offen, statt zu verwerfen.
        const mine = st;
        queueMicrotask(() => { if (st === mine) st.unregister = registerDialog(root, close); });
      }
      if (!st.armedClose) {
        st.armedClose = true;
        st.leaveFocus = document.activeElement;   // nach Abbrechen dorthin zurück
        paintState();
      } else if (how === "esc") {
        cancelLeave();
      }
      return;
    }
    const old = st;
    st = null;
    old.unregister?.();
    if (old.raf) cancelAnimationFrame(old.raf);
    root.hidden = true;
    root.innerHTML = "";
  }

  /** Nachfrage zurücknehmen: weiterarbeiten, Cursor wieder wie vorher. */
  function cancelLeave() {
    st.armedClose = false;
    paintState();
    const back = st.leaveFocus;
    st.leaveFocus = null;
    if (back instanceof Element && root.contains(back)) back.focus();
  }

  // -- Verdrahtung ----------------------------------------------------------------

  const rowOf = (el) => {
    const row = el instanceof Element ? el.closest(".lyrow") : null;
    return row ? Number(row.dataset.i) : -1;
  };

  function wire() {
    $("#lyClose").addEventListener("click", () => close("button"));
    $("#lyLeaveDrop").addEventListener("click", () => close(true));
    $("#lyLeaveCancel").addEventListener("click", cancelLeave);
    $("#lyLeaveSave").addEventListener("click", () => {
      const active = document.activeElement;
      if (active?.matches?.(".lytime")) commitTyped(rowOf(active));
      if (orderErrors(st.model).size) { st.armedClose = false; paintState(); return; }
      st.armedClose = true;
      save(toServer(st.model), STRINGS.lyricsSaved);
    });
    $("#lyPlay").addEventListener("click", () => toggle(st.item));
    $("#lyClock").addEventListener("click", () => toggle(st.item));
    $("#lySave").addEventListener("click", () => { if (dirty()) save(toServer(st.model), STRINGS.lyricsSaved); });
    $("#lyRestore").addEventListener("click", () => {
      if (!st.armedRestore) {
        st.armedRestore = true;
        $("#lyRestore").textContent = STRINGS.lyricsRestoreConfirm;
        return;
      }
      save([], STRINGS.lyricsRestored);
    });
    const list = $("#lyList");
    list.addEventListener("input", (e) => {
      const i = rowOf(e.target);
      if (i < 0) return;
      if (e.target.matches(".lytime")) {   // erst Enter oder Verlassen übernimmt
        e.target.dataset.typed = "1";
        return;
      }
      if (!e.target.matches(".lytext")) return;
      const line = st.model[i];
      // Eine Leerzeile, die Text bekommt, ist eine neue Zeile (Zeit schätzen).
      if (!fold(line.t) && line.s === null) line.fresh = true;
      line.t = e.target.value;
      edited();
    });
    // Zeitfeld verlassen (↑/↓, Tab, Klick): Getipptes übernehmen.
    list.addEventListener("focusout", (e) => {
      if (st && e.target.matches?.(".lytime")) commitTyped(rowOf(e.target));
    });
    list.addEventListener("click", (e) => {
      const i = rowOf(e.target);
      if (i < 0) return;
      if (e.target.closest(".lydel")) {
        st.model.splice(i, 1);
        render({ i, caret: 0 });
        edited();
      } else if (e.target.closest(".lyplay") && st.model[i].s !== null) {
        // 1 s davor: so hört man, ob der Einsatz stimmt.
        seek(st.item, Math.max(0, st.model[i].s / 1000 - PREROLL));
      }
    });
    list.addEventListener("paste", (e) => {
      if (!e.target.matches?.(".lytext")) return;
      const text = e.clipboardData?.getData("text/plain") ?? "";
      const i = rowOf(e.target);
      if (i < 0 || !/[\r\n]/.test(text)) return;   // eine Zeile: der Browser fügt ein
      e.preventDefault();
      const input = e.target;
      const from = input.selectionStart ?? input.value.length;
      const to = input.selectionEnd ?? from;
      const at = pasteAt(st.model, i, from, to, text);
      fillTimes(st.model, durMs());
      render(at);
      edited();
    });
  }

  /** Tasten in einer Zeile: teilen, verbinden, Zeile wechseln. */
  function rowKey(e) {
    const input = e.target;
    const i = rowOf(input);
    const from = input.selectionStart ?? input.value.length;
    const to = input.selectionEnd ?? from;
    let at = null;
    if (e.key === "Enter") {
      at = splitAt(st.model, i, from, to);
    } else if (e.key === "Backspace" && from === 0 && to === 0) {
      at = joinUp(st.model, i);
    } else if (e.key === "Delete" && from === input.value.length && to === from) {
      at = joinDown(st.model, i);
    } else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      e.preventDefault();
      focusRow(i + (e.key === "ArrowUp" ? -1 : 1), from);
      return;
    } else {
      return;
    }
    e.preventDefault();
    if (!at) return;
    fillTimes(st.model, durMs());
    render(at);
    edited();
  }

  /** Tasten im Zeitfeld: Enter übernimmt Getipptes und geht zur nächsten
   *  Zeile (wie in einer Tabelle), ↑/↓ wechseln die Zeile, Entf nimmt die
   *  Zeit weg, Leertaste spielt. Alles andere ist Tippen. Strg/⌘+Enter
   *  (jetzt) kommt vorher im Capture-Listener. */
  function timeKey(e) {
    const i = rowOf(e.target);
    if (e.key === " ") {
      e.preventDefault();
      toggle(st.item);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (!commitTyped(i, true)) return;
      const next = textLine(st.model, i + 1, 1);
      if (next >= 0) focusTime(next); else e.target.select?.();
    } else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      e.preventDefault();
      const up = e.key === "ArrowUp";
      const j = textLine(st.model, i + (up ? -1 : 1), up ? -1 : 1);
      if (j >= 0) focusTime(j);
    } else if (e.key === "Delete") {
      e.preventDefault();
      delete e.target.dataset.typed;
      setTime(i, null);
      st.message = "";
      paintTimes();
      paintState();
    }
  }

  on("lyrics-edit-open", (d) => open(d?.item));

  // Solange die Ansicht offen ist, gehören ihr ALLE Tasten: nichts darunter
  // (Player, Galerie, Bewerten) sieht sie. Esc nimmt overlays.js vorher.
  document.addEventListener("keydown", (e) => {
    if (!st || e.key === "Escape") return;
    e.stopPropagation();
    if ((e.metaKey || e.ctrlKey) && (e.key === "s" || e.key === "S")) {
      e.preventDefault();
      const active = document.activeElement;
      if (active?.matches?.(".lytime")) commitTyped(rowOf(active));
      if (dirty() && !orderErrors(st.model).size) save(toServer(st.model), STRINGS.lyricsSaved);
      return;
    }
    const target = e.target instanceof Element ? e.target : null;
    // Strg/⌘+Enter = jetzt (nicht mit Alt: Strg+Alt ist unter Windows AltGr).
    if ((e.metaKey || e.ctrlKey) && !e.altKey && e.key === "Enter" && target?.matches(".lytime, .lytext")) {
      e.preventDefault();
      const i = rowOf(target);
      if (i >= 0 && fold(st.model[i].t)) setNow(i, target.matches(".lytime") ? "time" : "text");
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (target?.matches(".lytime")) { timeKey(e); return; }
    if (target?.matches(".lytext")) { rowKey(e); return; }
    if (target?.matches("input, textarea, select")) return;
    if (e.key === " ") { e.preventDefault(); toggle(st.item); }
  }, true);

  return { isOpen: () => !!st, close };
}
