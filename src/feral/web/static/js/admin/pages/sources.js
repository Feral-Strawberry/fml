// admin/pages/sources.js — Seite „Quellen & Import" (ADR 0074, A2 #106).
//
// Oben die Karte „Ordner aufnehmen" (EIN Formular: Pfad + Ordnerwahl, Modus,
// einmal/dauerhaft, Leeren-Option; Feral Strawberry, 2026-07-09), darunter
// die Watchordner als Karten in Reihen gleicher Höhe: Name, Pfad, Zustand,
// Zähler wartend/importiert, Modus, Aktionen Beobachten/Stoppen/Entfernen
// (Watch-Quellen-Modell ADR 0030). Live-Zähler kommen mit jedem Status-Poll
// aus `status.watchers` (onStatus), ohne eigene Anfrage; die Liste selbst
// wird nach Aktionen, nach fertigen Aufgaben und alle ~10 s neu geladen.

import { STRINGS } from "../../strings.js";
import {
  startImport, getWatch, startWatchSource, stopWatchSource, saveWatchSources,
} from "../../api.js";
import { pickFolder } from "../dialogs.js";
import { esc, fmtNum } from "../util.js";

export const id = "sources";
export const icon = '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M12 11v6M9.5 14.5 12 17l2.5-2.5"/></svg>';
export const title = () => STRINGS.adminSources;
export const subtitle = () => STRINGS.subSources;

let root = null;
let watchSources = [];   // zuletzt geladene Liste (inkl. quiet/poll — Round-Trip)
let watchTick = 0;
const el = (sel) => root.querySelector("#" + sel);

const MODES = () => [
  ["kopieren", STRINGS.cfgModusKopieren],
  ["verschieben", STRINGS.cfgModusVerschieben],
  ["katalogisieren", STRINGS.cfgModusKatalog],
];

export function render(target) {
  root = target;
  root.innerHTML = `
    <div class="row"><div class="card">
      <div class="chead"><span class="mlabel">${STRINGS.importFormTitle}</span></div>
      <div class="vdim dashhint">${STRINGS.importFormHint}</div>
      <div class="srcform">
        <div class="pathline">
          <input type="text" id="adImpPath" placeholder="${STRINGS.scanPathPlaceholder}">
          <button type="button" id="adImpPick" title="${STRINGS.cfgPick}">📁</button>
        </div>
        <div class="optline">
          <select id="adImpModus" title="${STRINGS.watchModusTitle}">
            ${MODES().map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}
          </select>
          <select id="adImpFreq" title="${STRINGS.freqTitle}">
            <option value="einmal" selected>${STRINGS.freqOnce}</option>
            <option value="watch">${STRINGS.freqWatch}</option>
          </select>
          <label class="wleer" id="adImpLeerWrap" title="${esc(STRINGS.watchLeerTitle)}" hidden>
            <input type="checkbox" id="adImpLeer"> ${STRINGS.watchLeer}</label>
          <button type="button" class="accentbtn" id="adImpGo">${STRINGS.importGo}</button>
        </div>
      </div>
      <div id="adImpMsg" class="admsg"></div>
    </div></div>
    <div class="srchead"><span class="mlabel">${STRINGS.watchSection}</span>
      <span class="vdim" id="adWatchCount"></span></div>
    <div class="vdim dashhint">${STRINGS.watchHint}</div>
    <div id="adWatchWarn"></div>
    <div class="row c3" id="adWatch"></div>`;

  el("adImpPick").addEventListener("click", async () => {
    const input = el("adImpPath");
    const chosen = await pickFolder(input.value.trim() || null);
    if (chosen) input.value = chosen;
  });
  // Leerordner-Schalter (ADR 0033) nur zeigen, wo er wirkt: verschieben.
  el("adImpModus").addEventListener("change", () => {
    el("adImpLeerWrap").hidden = el("adImpModus").value !== "verschieben";
  });
  el("adImpGo").addEventListener("click", submitImport);
  el("adImpPath").addEventListener("keydown", (e) => {
    if (e.key === "Enter") el("adImpGo").click();
  });
  el("adWatch").addEventListener("change", onWatchChange);
  el("adWatch").addEventListener("click", onWatchClick);
}

export async function load() { await loadWatch(); }

/** Jeder Status-Poll (700 ms): Live-Zähler aus `watchers` direkt in die
 *  Karten; die Liste selbst nur alle ~10 s (Zustand/Existenz/Konfig). */
export function onStatus(s) {
  const live = new Map((s.watchers || []).map((w) => [normPath(w.root), w]));
  for (const card of root.querySelectorAll(".srccard[data-path]")) {
    const w = live.get(normPath(card.dataset.path));
    if (!w) continue;
    card.querySelector("[data-pending]").textContent = fmtNum(w.pending);
    card.querySelector("[data-imported]").textContent = fmtNum(w.enqueued_total);
  }
  if (++watchTick % 14 === 0) loadWatch();
}

export function onTaskFinished() { loadWatch(); }

/** Pfadvergleich Konfiguration ↔ Watcher (der Server löst auf): ohne
 *  Schluss-Slash, Windows-Backslashes vereinheitlicht. */
const normPath = (p) => String(p || "").replace(/\\/g, "/").replace(/\/+$/, "");

function renderWatch(d) {
  const box = el("adWatch");
  watchSources = d.sources;
  // Übersichtsmodus (ADR 0041, I4): dateischreibende Modi sind gesperrt —
  // im Import-Formular UND auf den Karten. katalogisieren bleibt frei.
  const locked = d.verwaltung === false;
  const lockOpt = (value) => locked && value !== "katalogisieren"
    ? ` disabled title="${esc(STRINGS.modeLocked)}"` : "";
  for (const opt of el("adImpModus").options) {
    opt.disabled = locked && opt.value !== "katalogisieren";
    opt.title = opt.disabled ? STRINGS.modeLocked : "";
  }
  if (locked && el("adImpModus").value !== "katalogisieren") {
    el("adImpModus").value = "katalogisieren";
  }
  // Ohne Media Library nur warnen, wo sie gebraucht wird (#187): Im
  // Übersichtsmodus mit reinen katalogisieren-Ordnern ist sie überflüssig,
  // die Warnung dort nur falscher Alarm.
  const needsLibrary = !locked || d.sources.some((s) => s.modus !== "katalogisieren");
  el("adWatchWarn").innerHTML = d.has_library || !needsLibrary
    ? "" : `<div class="warn watchwarn">${STRINGS.watchNoLibrary}</div>`;
  el("adWatchCount").textContent = d.sources.length ? `${d.sources.length}` : "";
  if (!d.sources.length) {
    box.className = "row";
    box.innerHTML = `<div class="card srcempty">${STRINGS.watchNone}</div>`;
    return;
  }
  box.className = "row c3";
  box.innerHTML = d.sources.map((s, i) => {
    const srcLocked = locked && s.modus !== "katalogisieren";
    const state = srcLocked
      ? `<span class="wdot"></span><span class="warn">${STRINGS.modeLocked}</span>`
      : s.watching
      ? `<span class="wdot on"></span>${STRINGS.watchOn}`
      : `<span class="wdot"></span>${s.exists ? STRINGS.watchOff : STRINGS.scanMissing}`;
    const btn = s.watching
      ? `<button type="button" class="watchtoggle" data-stop="${esc(s.path)}">${STRINGS.watchStop}</button>`
      : `<button type="button" class="watchtoggle accentbtn" data-start="${esc(s.path)}" ${s.exists && !srcLocked ? "" : "disabled"}${srcLocked ? ` title="${esc(STRINGS.modeLocked)}"` : ""}>${STRINGS.watchStart}</button>`;
    return `<div class="card srccard" data-path="${esc(s.path)}">
      <div class="srcname"><span>${esc(s.name)}</span></div>
      <div class="srcpath" title="${esc(s.path)}">${esc(s.path)}</div>
      <div class="srcstate">${state}</div>
      <div class="srcnums">
        <div class="srcnum"><b data-pending>${fmtNum(s.pending)}</b><small>${STRINGS.watchPendingLabel}</small></div>
        <div class="srcnum"><b data-imported>${fmtNum(s.enqueued_total)}</b><small>${STRINGS.watchImportedLabel}</small></div>
      </div>
      <div class="srcctl">
        <select class="wmodus" data-idx="${i}" title="${STRINGS.watchModusTitle}">
          ${MODES().map(([v, l]) => `<option value="${v}" ${s.modus === v ? "selected" : ""}${lockOpt(v)}>${l}</option>`).join("")}
        </select>
        ${s.modus === "verschieben" ? `<label class="wleer" title="${esc(STRINGS.watchLeerTitle)}">
          <input type="checkbox" class="wleerchk" data-idx="${i}" ${s.leere_ordner_entfernen ? "checked" : ""}>
          ${STRINGS.watchLeer}</label>` : ""}
        ${btn}
        <button type="button" class="wremove" data-idx="${i}" title="${STRINGS.watchRemoveTitle}">✕ ${STRINGS.watchRemove}</button>
      </div>
    </div>`;
  }).join("");
}

async function loadWatch() {
  if (!root || !root.isConnected) return;
  const box = el("adWatch");
  // Nicht unter den Händen wegrendern: der Poller frischt die Karten auf —
  // aber nicht, während in der Liste gerade ein Select/Feld offen ist.
  const active = document.activeElement;
  if (box.contains(active) && (active.tagName === "SELECT" || active.tagName === "INPUT")) return;
  try {
    renderWatch(await getWatch());
  } catch (err) { box.innerHTML = `<div class="card"><span class="warn">${esc(err.message)}</span></div>`; }
}

async function saveWatch(next) {
  try {
    renderWatch(await saveWatchSources(next.map((s) => ({
      name: s.name, path: s.path, modus: s.modus,
      quiet_seconds: s.quiet_seconds, poll_seconds: s.poll_seconds,
      leere_ordner_entfernen: !!s.leere_ordner_entfernen,
    }))));
    return true;
  } catch (err) { alert(err.message); loadWatch(); return false; }
}

// EIN Import-Formular: Pfad + Modus + Häufigkeit — „einmal jetzt" reiht den
// Einmal-Import ein, „dauerhaft beobachten" legt einen Watchordner an.
// Gleiche Pipeline, eine Entscheidung an einem Ort; verschieben immer mit
// Sicherheitsabfrage.
async function submitImport() {
  const input = el("adImpPath");
  const path = input.value.trim();
  if (!path) { alert(STRINGS.watchAddNoPath); return; }
  const modus = el("adImpModus").value;
  const freq = el("adImpFreq").value;
  const leer = modus === "verschieben" && el("adImpLeer").checked;
  const msg = el("adImpMsg");
  // Nur verschieben ist eingreifend (Quelle wird geleert) → Abfrage.
  // kopieren fasst die Quelle nie an, katalogisieren kopiert nicht mal
  // (ADR 0031) — beides braucht keine Bestätigung.
  if (modus === "verschieben" && !confirm(STRINGS.cfgVerschiebenConfirm)) return;
  try {
    if (freq === "watch") {
      if (watchSources.some((s) => s.path === path)) { alert(STRINGS.watchDupe); return; }
      const name = path.split(/[\\/]/).filter(Boolean).pop() || path;
      if (!(await saveWatch([...watchSources,
        { name, path, modus, leere_ordner_entfernen: leer }]))) return;
      msg.innerHTML = `<span class="adok">${STRINGS.watchCreated}</span>`;
    } else {
      const r = await startImport(path, modus, leer);
      msg.innerHTML = modus === "katalogisieren"
        ? `<span class="adok">${r.queued_files} ${STRINGS.scanQueued}</span>`
        : `<span class="adok">${r.queued_files} ${STRINGS.importQueued} → ${esc(r.target)}</span>`;
    }
    input.value = "";
    el("adImpModus").value = "kopieren";
    el("adImpFreq").value = "einmal";
    el("adImpLeer").checked = false;
    el("adImpLeerWrap").hidden = true;
  } catch (err) { alert(err.message); }
}

function onWatchChange(e) {
  const chk = e.target.closest(".wleerchk");
  if (chk) {
    const src = watchSources[Number(chk.dataset.idx)];
    if (!src) return;
    chk.blur();   // Fokus freigeben, sonst blockiert der Render-Schutz das Update
    saveWatch(watchSources.map((s) =>
      s === src ? { ...s, leere_ordner_entfernen: chk.checked } : s));
    return;
  }
  const sel = e.target.closest(".wmodus");
  if (!sel) return;
  const src = watchSources[Number(sel.dataset.idx)];
  if (!src) return;
  // Verschieben ist eingreifend (Quelle wird geleert) → ausdrückliche Warnung.
  if (sel.value === "verschieben" && !confirm(STRINGS.cfgVerschiebenConfirm)) {
    sel.value = "kopieren";
    return;
  }
  sel.blur();
  saveWatch(watchSources.map((s) => s === src ? { ...s, modus: sel.value } : s));
}

async function onWatchClick(e) {
  const remove = e.target.closest(".wremove");
  if (remove) {
    const src = watchSources[Number(remove.dataset.idx)];
    if (src) saveWatch(watchSources.filter((s) => s !== src));
    return;
  }
  const start = e.target.closest("[data-start]");
  const stop = e.target.closest("[data-stop]");
  if (!start && !stop) return;
  try {
    if (start) await startWatchSource(start.dataset.start);
    else await stopWatchSource(stop.dataset.stop);
    loadWatch();
  } catch (err) { alert(err.message); }
}
