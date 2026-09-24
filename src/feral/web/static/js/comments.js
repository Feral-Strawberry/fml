// comments.js — Zeitkommentare im SoundCloud-Stil (Audio A6, #163, ADR 0088).
//
// Kommentare hängen an einer Stelle im Song (Punkt, kein Bereich) und leben
// in der manuellen Schicht. Hier steht alles, was sie im Browser brauchen:
// - **Speicher je Hash** (zeitlich sortiert). Gefüllt aus den Listenzeilen
//   (/api/items liefert `comments` mit), dem Detailpanel und jeder Antwort
//   der Kommentar-API; fehlt ein Song (Arena, Leiste), wird nachgeladen.
// - **Pins** auf allen Wellenformen (player.paintWave ruft paintPins), Hover
//   zeigt den Text, Klick springt (die Wellen-Klickstellen fragen pinTime).
// - **Einblenden beim Abspielen:** Beim geladenen Song steht jeder Kommentar
//   von LEAD s vor bis HOLD s nach seiner Stelle über der Welle; mehrere
//   zugleich stapeln sich nach oben.
// - **Anlegen** an der Abspielstelle: Taste K, 💬 in der Leiste, ＋ im Panel
//   öffnen dieselbe kleine Eingabe (Enter speichert, Esc verwirft).
// - **Abschnitt im Detailpanel:** Liste, Klick springt, Doppelklick ändert,
//   ✕ löscht.

import { STRINGS } from "./strings.js";
import {
  addComment, deleteComment, editComment, fmtDuration, getComments, libraryView,
} from "./api.js";
import { emit, on } from "./main.js";
import { currentHash, positionOf, repaint, seek, snap } from "./player.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** Stelle als „m:ss" (auch 0:00). */
export const fmtAt = (ms) => fmtDuration(ms / 1000) || "0:00";

const store = new Map();     // Hash → [{id, at_ms, text}]
const loading = new Set();

const slim = (list) => (list || []).map(({ id, at_ms, text }) => ({ id, at_ms, text }));

/** Stand vom Server übernehmen (Detail, API-Antwort) — maßgeblich. */
export function setComments(hash, list) {
  store.set(hash, slim(list));
  emit("comments-changed", { hash });
  repaint(hash);
}

/** Stand aus einer Listenzeile: nur, wenn noch keiner da ist — gemerkte
 *  Galerie-Seiten sind älter als eigene Änderungen. */
export function seedComments(hash, list) {
  if (hash && !store.has(hash)) store.set(hash, slim(list));
}

/** Kommentare eines Songs; unbekannt → [] und im Hintergrund nachladen. */
export function commentsOf(hash) {
  if (!hash) return [];
  if (store.has(hash)) return store.get(hash);
  if (!loading.has(hash)) {
    loading.add(hash);
    getComments(hash)
      .then((d) => setComments(hash, d.comments))
      .catch(() => store.set(hash, []))
      .finally(() => loading.delete(hash));
  }
  return [];
}

async function run(hash, promise) {
  try {
    const d = await promise;
    setComments(hash, d.comments);
  } catch (err) {
    console.warn(err);
  }
}

export const createComment = (hash, ms, text) => run(hash, addComment(hash, Math.max(0, Math.round(ms)), text));
export const changeComment = (hash, id, text) => run(hash, editComment(hash, id, { text }));
export const removeComment = (hash, id) => run(hash, deleteComment(hash, id));

// -- Pins ------------------------------------------------------------------------------

export const LEAD = 1;    // Sekunden vor der Stelle: der Kommentar kündigt sich an
export const HOLD = 5;    // Sekunden danach: lang genug zum Lesen beim Hören

/** Welche Kommentare stehen bei `pos` Sekunden? (null = nicht geladen: keiner) */
export function shownAt(list, pos) {
  if (pos == null) return [];
  return list.filter((c) => pos >= c.at_ms / 1000 - LEAD && pos < c.at_ms / 1000 + HOLD);
}

/** Pins eines Songs in eine Wellenfläche (.wv) setzen. `axis` = Sekunden der
 *  vollen Breite (Liste: gemeinsame Zeitachse), `pos` = Abspielstelle, wenn
 *  der Song geladen ist (dann blenden die Beschriftungen ein), sonst null.
 *  Pins und Beschriftungen werden nur bei Änderung neu gebaut; das Ein- und
 *  Ausblenden schaltet nur Klassen (läuft ~10× je Sekunde mit). */
export function paintPins(wv, hash, axis, pos = null) {
  if (!wv) return;
  const list = commentsOf(hash);
  let box = wv.querySelector(".pins");
  if (!box) {
    if (!list.length) return;
    box = document.createElement("span");
    box.className = "pins";
    wv.appendChild(box);
  }
  const key = `${hash}|${axis}|${list.map((c) => `${c.id}@${c.at_ms}:${c.text}`).join(",")}`;
  if (box._key !== key) {
    box._key = key;
    box.dataset.hash = hash;
    box.innerHTML = axis > 0
      ? list.map((c) => {
        const x = Math.min(100, (c.at_ms / 1000 / axis) * 100);
        return `<span class="pin" data-cid="${c.id}" data-t="${c.at_ms / 1000}" style="left:${x}%"></span>`
          + `<span class="plabel${x > 70 ? " r" : ""}" data-cid="${c.id}" style="left:${x}%"><span class="t">${fmtAt(c.at_ms)}</span>${esc(c.text)}</span>`;
      }).join("")
      : "";
  }
  const on = new Set(shownAt(list, pos).map((c) => String(c.id)));
  const labs = [...box.querySelectorAll(".plabel")];
  // Vergleich in der Liste (A7): alle Beschriftungen stehen, gestapelt nur,
  // wo sie sich überdecken; gemessen nur bei geänderten Kommentaren/Breite.
  const all = !!wv.closest(".pinlabels");
  box.classList.toggle("all", all);
  if (all) {
    const w = box.clientWidth;
    if (w && box._lkey !== `${key}|${w}`) {
      box._lkey = `${key}|${w}`;
      const lv = stackLevels(labs.map((l) => { const r = l.getBoundingClientRect(); return [r.left, r.right]; }));
      labs.forEach((l, k) => { l.dataset.lvl = String(lv[k]); });
    }
  } else box._lkey = null;
  let level = 0;
  for (const lab of labs) {
    const vis = on.has(lab.dataset.cid);
    lab.classList.toggle("on", vis);
    if (vis && !all) lab.dataset.lvl = String(Math.min(level++, 3));   // gleichzeitig: nach oben stapeln
  }
}

/** Stapel-Ebenen für Beschriftungen, die alle zugleich stehen: `spans` =
 *  [links, rechts] in px, in Zeitreihenfolge. Jede nimmt die unterste Ebene,
 *  auf der sie keine frühere überdeckt (4 px Luft); höchstens `max`. */
export function stackLevels(spans, max = 3) {
  const ends = [];   // rechtes Ende der letzten Beschriftung je Ebene
  const order = spans.map((s, i) => i).sort((a, b) => spans[a][0] - spans[b][0]);
  const out = new Array(spans.length).fill(0);
  for (const i of order) {
    const [l, r] = spans[i];
    let lvl = ends.findIndex((e) => e + 4 <= l);
    if (lvl < 0) lvl = Math.min(ends.length, max);
    ends[lvl] = Math.max(ends[lvl] ?? -Infinity, r);
    out[i] = lvl;
  }
  return out;
}

/** Sekunden des angeklickten Pins, sonst null — die Wellen-Klickstellen
 *  springen dann genau dorthin statt an die Mausposition. */
export function pinTime(e) {
  const pin = e.target instanceof Element ? e.target.closest(".pin") : null;
  return pin ? parseFloat(pin.dataset.t) : null;
}

function commentOfPin(pin) {
  const hash = pin.parentElement?.dataset.hash;
  return (store.get(hash) || []).find((c) => String(c.id) === pin.dataset.cid) || null;
}

function tipEl() {
  let tip = document.getElementById("pintip");
  if (!tip) {
    tip = document.createElement("div");
    tip.id = "pintip";
    tip.hidden = true;
    document.body.appendChild(tip);
  }
  return tip;
}

// -- Anlegen: kleine Eingabe an der Abspielstelle ------------------------------------

function closePrompt() {
  document.getElementById("comprompt")?.remove();
}

/** Eingabe für einen neuen Kommentar an `sec` öffnen, neben `anchor`.
 *  Enter oder Verlassen mit Text speichert (wie die Notizen), Esc verwirft. */
export function openCommentPrompt(hash, sec, anchor) {
  if (!hash) return;
  closePrompt();
  const ms = Math.max(0, Math.round((sec || 0) * 1000));
  const box = document.createElement("div");
  box.id = "comprompt";
  box.innerHTML = `<span class="t">${fmtAt(ms)}</span><input type="text" placeholder="${esc(STRINGS.commentPlaceholder)}">`;
  document.body.appendChild(box);
  const r = anchor?.getBoundingClientRect?.() || { left: 16, top: 80, bottom: 80 };
  box.style.left = `${Math.max(8, Math.min(window.innerWidth - 330, r.left))}px`;
  box.style.top = `${r.top > 70 ? r.top - 44 : r.bottom + 6}px`;
  const input = box.querySelector("input");
  let done = false;
  const finish = (save) => {
    if (done) return;
    done = true;
    const v = input.value.trim();
    closePrompt();
    if (save && v) createComment(hash, ms, v);
  };
  input.addEventListener("keydown", (e) => {
    e.stopPropagation();   // Leertaste, Pfeile, Ziffern gehören hier dem Text
    if (e.key === "Enter") finish(true);
    else if (e.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
  input.focus();
}

// -- Abschnitt im Detailpanel ------------------------------------------------------------

/** Abschnitt „Zeitkommentare" (#pComs) für einen Song füllen; `head` baut
 *  die Kopfzeile (detail.sechead). Der Stand im Detail ist maßgeblich. */
export function mountCommentSection(el, item, head) {
  if (!el) return;
  el._item = item;
  el._head = head;
  if (item.comments) {
    store.set(item.file_hash, slim(item.comments));
    repaint(item.file_hash);
  }
  renderSection(el);
}

function renderSection(el) {
  const item = el._item;
  const list = commentsOf(item.file_hash);
  el.innerHTML = `${el._head(STRINGS.sectionComments, `<span class="vmono vdim">${list.length}</span>`)}
    <div class="coms">${list.map((c) => `
      <div class="com" data-cid="${c.id}" title="${esc(STRINGS.commentJump)}">
        <span class="t">${fmtAt(c.at_ms)}</span><span class="ctext" title="${esc(STRINGS.commentEditTitle)}">${esc(c.text)}</span>
        <button type="button" class="x" title="${esc(STRINGS.commentDelete)}">✕</button></div>`).join("")
      || `<div class="vdim">${STRINGS.commentsNone}</div>`}</div>
    <button type="button" class="comadd">${STRINGS.commentAddHere}</button>`;
}

function editInline(el, row) {
  const item = el._item;
  const c = (store.get(item.file_hash) || []).find((x) => String(x.id) === row.dataset.cid);
  const span = row.querySelector(".ctext");
  if (!c || !span) return;
  span.innerHTML = `<input type="text" value="${esc(c.text)}">`;
  const input = span.querySelector("input");
  let done = false;
  const finish = (save) => {
    if (done) return;
    done = true;
    const v = input.value.trim();
    if (save && v && v !== c.text) changeComment(item.file_hash, c.id, v);
    else renderSection(el);
  };
  input.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") finish(true);
    else if (e.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
  input.focus();
}

// -- Wen meint K? -------------------------------------------------------------------------

let selHash = null;

/** Ziel der Taste K: in der Audioansicht die ausgewählte Zeile (ihr eigener
 *  Abspielkopf), sonst der geladene Song der Leiste. */
function keyTarget() {
  if (libraryView() === "audio" && selHash) {
    const row = document.querySelector(`#grid .arow[data-hash="${selHash}"]`);
    return { hash: selHash, anchor: row?.querySelector(".wv") || document.getElementById("pComs") };
  }
  const hash = currentHash();
  return hash ? { hash, anchor: document.querySelector("#pbar .wv") } : null;
}

export function initComments() {
  on("selection-changed", (d) => { selHash = d?.hash ?? null; });
  on("comments-changed", ({ hash }) => {
    const el = document.getElementById("pComs");
    if (el?._item?.file_hash === hash) renderSection(el);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "k" && e.key !== "K") return;
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.target instanceof Element && e.target.matches("input, textarea, select, [contenteditable]")) return;
    for (const id of ["loupe", "single", "rankings", "compare"]) {
      if (!document.getElementById(id)?.hidden) return;
    }
    const t = keyTarget();
    if (!t) return;
    e.preventDefault();
    openCommentPrompt(t.hash, positionOf(t.hash), t.anchor);
  });

  // Panel-Abschnitt: Klick springt, ✕ löscht, Doppelklick ändert, ＋ legt an.
  document.addEventListener("click", (e) => {
    const t = e.target;
    if (!(t instanceof Element)) return;
    const el = t.closest("#pComs");
    if (!el?._item) return;
    const item = el._item;
    if (t.closest(".comadd")) {
      openCommentPrompt(item.file_hash, positionOf(item.file_hash), t.closest(".comadd"));
      return;
    }
    const row = t.closest(".com");
    if (!row || t.closest("input")) return;
    const c = (store.get(item.file_hash) || []).find((x) => String(x.id) === row.dataset.cid);
    if (!c) return;
    if (t.closest(".x")) removeComment(item.file_hash, c.id);
    else seek(snap({ ...item, media_kind: "audio" }), c.at_ms / 1000);
  });
  document.addEventListener("dblclick", (e) => {
    const t = e.target;
    if (!(t instanceof Element) || !t.closest("#pComs .ctext")) return;
    const el = t.closest("#pComs");
    if (el?._item) editInline(el, t.closest(".com"));
  });

  // Hover über einem Pin: Stelle und Text.
  document.addEventListener("mouseover", (e) => {
    const pin = e.target instanceof Element ? e.target.closest(".pin") : null;
    const tip = tipEl();
    const c = pin ? commentOfPin(pin) : null;
    if (!c) { tip.hidden = true; return; }
    tip.innerHTML = `<span class="t">${fmtAt(c.at_ms)}</span>${esc(c.text)}`;
    tip.hidden = false;
    const r = pin.getBoundingClientRect();
    tip.style.left = `${Math.max(4, Math.min(window.innerWidth - 270, r.left - 6))}px`;
    tip.style.top = `${r.top - 30}px`;
  });
}
