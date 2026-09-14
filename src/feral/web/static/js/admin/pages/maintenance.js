// admin/pages/maintenance.js — Seite „Wartung" (ADR 0074, A3 #107).
//
// Vier Gruppenkarten in EINER Reihe gleicher Höhe (Rohdateien | Thumbnails |
// Datenbank | Neubewertung): oben eine begründende Kennzahl (Meter/Balken,
// Diagramm-Regel ADR-0074-Nachtrag Punkt 3), darunter je Aktion eine Zeile
// mit Titel, Erklärung, Knopf und Inline-Zustand. Der Zustand kommt aus dem
// Status-Poll (läuft mit Balken / in der Warteschlange · Position / zuletzt
// ✓ Ergebnis · Uhrzeit) — die Zeile ist die Wahrheit über „ihre" Aufgabe.
// Rausverschieben (ADR 0041 I3), Import-Regeln auf den Bestand (ADR 0046)
// und Verwaiste Fundorte aufräumen (ADR 0033) sind EIGENE Karten in eigenen
// Reihen (keine Verschachtelung, Nachtrag Punkt 1) mit derselben Logik in
// drei Schritten: Ziel/Regeln/Bereich → Vorschau → Scharf schalten +
// Ausführen. Kein Overlay mehr (#31 hat damit keinen Boden mehr).
// Ladeprinzip wie die Übersicht: billige Zahlen sofort (/api/stats +
// /api/admin/maintenance), /api/admin/info danach. Verwaiste Fundorte und
// Cache-Größe sind ein GEMERKTER STAND mit Zeitstempel (#118, ADR 0077):
// gezählt wird nur auf Klick („Fundorte prüfen" — im Meter oder überall in
// der Aufräum-Karte —, „Cache zählen") oder nach passenden Aufgaben im
// Hintergrund (dann „wird geprüft …" und Nachfragen bis der Stand da ist);
// die DB-Aufteilung (dbstat) ebenfalls nur auf Knopfdruck.

import { STRINGS } from "../../strings.js";
import {
  getStats, getAdminInfo, getMaintenanceStats, getDbBreakdown,
  getOrphans, pruneOrphans, clearThumbCache, getThumbCache, getImportRulesPreview, applyImportRules,
  getMoveout, startMoveout, startReparse, startRescan, startIntegrityCheck,
  startVacuum, startThumbWarm, startBackfillDates, startReindex,
} from "../../api.js";
import { serverMsg } from "../../servermsg.js";
import { lastKnownStatus } from "../../status.js";
import { pickFolder } from "../dialogs.js";
import { progressPercent } from "../nav.js";
import { esc, fmtBytes, fmtElapsed, fmtNum, fmtTime, pct, tpl, timing, isChecking, standNote } from "../util.js";

export const id = "maintenance";
export const icon = '<svg viewBox="0 0 24 24"><path d="M14.7 6.3a4 4 0 0 0 5 5L13 18a2.1 2.1 0 0 1-3-3l6.7-6.7z"/><path d="M6 21l-3-3 4-4 3 3z"/></svg>';
export const title = () => STRINGS.adminMaintenance;
export const subtitle = () => STRINGS.subMaintenance;

// Eine Aktion: id, Titel, Erklärung, Schlüssel des Aufgaben-Labels im Status
// (null = synchron, Ergebnis kommt direkt zurück), Ausführung, Knopftext.
const A = (aid, t, ex, task, run, btn, accent = true) => ({ id: aid, t, ex, task, run, btn, accent });
const CARDS = () => [
  { key: "raw", title: STRINGS.mtHeaderRaw, actions: [
    A("rescan", STRINGS.maintRescan, STRINGS.maintRescanSub, "taskRescan", startRescan, STRINGS.mtEnqueue),
  ] },
  { key: "thumbs", title: STRINGS.mtHeaderThumbs, actions: [
    A("thumbwarm", STRINGS.maintThumbWarm, STRINGS.maintThumbWarmSub, "taskThumbWarm", startThumbWarm, STRINGS.mtEnqueue),
    A("thumbs", STRINGS.maintThumbs, STRINGS.maintThumbsSub, null, "thumbs", STRINGS.mtClear, false),
  ] },
  { key: "db", title: STRINGS.mtHeaderDb, actions: [
    A("integrity", STRINGS.maintIntegrity, STRINGS.maintIntegritySub, "taskIntegrity", startIntegrityCheck, STRINGS.mtEnqueue),
    A("vacuum", STRINGS.maintVacuum, STRINGS.maintVacuumSub, "taskVacuum", startVacuum, STRINGS.mtEnqueue),
  ] },
  { key: "reeval", title: STRINGS.mtHeaderReeval, actions: [
    A("reparse", STRINGS.maintReparse, STRINGS.maintReparseSub, "taskReparse", startReparse, STRINGS.mtEnqueue),
    A("backfill", STRINGS.maintBackfill, STRINGS.maintBackfillSub, "taskBackfillDates", startBackfillDates, STRINGS.mtEnqueue),
    A("reindex", STRINGS.maintReindex, STRINGS.maintReindexSub, "taskReindex", startReindex, STRINGS.mtEnqueue),
  ] },
];

let root = null;
let actions = new Map();     // id → Aktion
let stats = null;            // /api/stats
let info = null;             // /api/admin/info (teuer, zweite Stufe)
let moveout = null;          // /api/admin/moveout
let rulesPreview = null;     // /api/admin/import-rules
let orphanPreview = null;    // /api/admin/orphans (nur auf Knopfdruck)
let recheck = null;          // Nachfrage-Timer, solange eine Hintergrund-Zählung läuft (#118)
const el = (sel) => root.querySelector("#" + sel);

function actionRow(a) {
  return `
    <div class="action" data-action="${a.id}">
      <div class="ti">${esc(a.t)}</div>
      <button type="button" class="go${a.accent ? " accent" : ""}" data-run="${a.id}">${esc(a.btn)}</button>
      <div class="ex">${esc(a.ex)}</div>
      <div class="st" data-st="${a.id}"></div>
    </div>`;
}

export function render(target) {
  root = target;
  info = null; moveout = null; rulesPreview = null; orphanPreview = null;
  actions = new Map(CARDS().flatMap((c) => c.actions).map((a) => [a.id, a]));
  root.innerHTML = `
    <div class="row c4">${CARDS().map((c) => `
      <div class="card" data-card="${c.key}">
        <div class="chead"><span class="mlabel">${esc(c.title)}</span><span class="right" id="mtHead-${c.key}">…</span></div>
        <div class="meter" id="mtMeter-${c.key}"><span class="vdim">…</span></div>
        <div class="actions">${c.actions.map(actionRow).join("")}</div>
      </div>`).join("")}
    </div>
    <div class="row"><div class="card" id="moCard">
      <div class="chead"><span class="mlabel">${STRINGS.moTitle}</span><span class="right">${STRINGS.moTouchesFiles}</span></div>
      <div class="vdim dashhint">${STRINGS.moHint}</div>
      <div class="steps">
        <div class="step">
          <div class="mlabel">${STRINGS.moStepTarget}</div>
          <div class="pathrow"><input type="text" id="moTarget" placeholder="${STRINGS.scanPathPlaceholder}">
            <button type="button" id="moPick" title="${STRINGS.cfgPick}">📁</button></div>
          <div class="stephint">${STRINGS.moTargetHint}</div>
        </div>
        <div class="step">
          <div class="mlabel">${STRINGS.moStepPreview}</div>
          <div class="prev" id="moInfo"><span class="vdim">${STRINGS.moPreviewLoading}</span></div>
          <div style="margin-top:8px"><button type="button" id="moRefresh">${STRINGS.moRefresh}</button></div>
        </div>
        <div class="step">
          <div class="mlabel">${STRINGS.moStepRun}</div>
          <div class="armrow">
            <label><input type="checkbox" id="moArm" disabled> ${STRINGS.moArm}</label>
            <button type="button" class="danger" id="moGo" disabled>${tpl(STRINGS.moGoN, { n: 0 })}</button>
            <span class="vdim">${STRINGS.moRunHint}</span>
          </div>
          <div class="st" id="moMsg"></div>
        </div>
      </div>
      <div class="runbox" id="moRun" hidden>
        <div class="rh"><span class="dot" id="moDot"></span><span id="moRunTitle"></span><span class="mono" id="moElapsed"></span></div>
        <div class="bar big"><i id="moBar" style="width:0%"></i></div>
        <div class="file" id="moFile"></div>
        <div class="cnts" id="moCnts"></div>
      </div>
    </div></div>
    <div class="row"><div class="card" id="irCard">
      <div class="chead"><span class="mlabel">${STRINGS.maintImportRules}</span><span class="right">${STRINGS.irTwoStep}</span></div>
      <div class="vdim dashhint">${STRINGS.maintImportRulesSub}</div>
      <div class="steps">
        <div class="step">
          <div class="mlabel">${STRINGS.irStepRules}</div>
          <div class="rules" id="irRules"><span class="vdim">…</span></div>
          <div class="stephint">${STRINGS.irChangeIn} <a class="link" href="/admin/config">${STRINGS.irChangeLink}</a>.</div>
        </div>
        <div class="step">
          <div class="mlabel">${STRINGS.irStepPreview}</div>
          <div class="prev" id="irPrev"><span class="vdim">${STRINGS.irNotChecked}</span></div>
          <div style="margin-top:8px"><button type="button" class="accent" id="irCheck">${STRINGS.irCheck}</button></div>
        </div>
        <div class="step">
          <div class="mlabel">${STRINGS.irStepApply}</div>
          <div class="armrow">
            <label><input type="checkbox" id="irArm" disabled> ${STRINGS.irArm}</label>
            <button type="button" class="danger" id="irGo" disabled>${tpl(STRINGS.irGoN, { n: 0 })}</button>
            <span class="vdim">${STRINGS.irApplyHint}</span>
          </div>
          <div class="st" id="irMsg"></div>
        </div>
      </div>
    </div></div>
    <div class="row"><div class="card" id="prCard">
      <div class="chead"><span class="mlabel">${STRINGS.maintPrune}</span><span class="right">${STRINGS.prTouches}</span></div>
      <div class="vdim dashhint">${STRINGS.maintPruneSub}. ${STRINGS.pruneOfflineHint}</div>
      <div class="steps">
        <div class="step">
          <div class="mlabel">${STRINGS.prStepScope}</div>
          <div class="armrow">
            <label><input type="radio" name="prScope" value="all" id="prScopeAll" checked> ${STRINGS.prScopeAll}</label>
            <label><input type="radio" name="prScope" value="under" id="prScopeUnder"> ${STRINGS.prScopeUnder}</label>
          </div>
          <div class="pathrow" style="margin-top:8px"><input type="text" id="prPath" placeholder="${STRINGS.scanPathPlaceholder}" disabled>
            <button type="button" id="prPick" title="${STRINGS.cfgPick}" disabled>📁</button></div>
        </div>
        <div class="step">
          <div class="mlabel">${STRINGS.prStepPreview}</div>
          <div class="prev" id="prPrev"><span class="vdim">${STRINGS.prNotChecked}</span></div>
          <div style="margin-top:8px"><button type="button" class="accent" id="prCheck">${STRINGS.prCheck}</button></div>
        </div>
        <div class="step">
          <div class="mlabel">${STRINGS.prStepRun}</div>
          <div class="armrow">
            <label><input type="checkbox" id="prArm" disabled> ${STRINGS.prArm}</label>
            <button type="button" class="danger" id="prGo" disabled>${tpl(STRINGS.prGoN, { n: 0 })}</button>
            <span class="vdim">${STRINGS.prRunHint}</span>
          </div>
          <div class="st" id="prMsg"></div>
        </div>
      </div>
    </div></div>`;

  root.addEventListener("click", onClick);
  el("moTarget").addEventListener("input", updateMoveoutArm);
  el("moArm").addEventListener("change", updateMoveoutArm);
  el("irArm").addEventListener("change", () => { el("irGo").disabled = !el("irArm").checked; });
  // Aufräum-Karte: jede Änderung am Bereich entwertet die Vorschau (ADR 0033:
  // die Zahl gilt nur für den geprüften Bereich).
  for (const r of root.querySelectorAll('input[name="prScope"]')) r.addEventListener("change", onPruneScope);
  el("prPath").addEventListener("input", resetPrunePreview);
  el("prArm").addEventListener("change", () => { el("prGo").disabled = !el("prArm").checked; });
}

export async function load() {
  // Stufe 1: billige Zahlen sofort.
  try {
    const [st, mt] = await Promise.all([getStats(), getMaintenanceStats()]);
    stats = st;
    renderCheap(st, mt);
  } catch (err) {
    el("mtMeter-raw").innerHTML = `<span class="warn">${esc(err.message)}</span>`;
  }
  const s = lastKnownStatus();
  if (s) applyStatus(s);
  // Stufe 2 + Karten-Vorschauen nebeneinander; jede meldet ihren Fehler selbst.
  loadInfo();
  loadMoveout();
  loadRules();
}

export function onStatus(s) { if (root && root.isConnected) applyStatus(s); }
export function onTaskFinished() { loadInfo(); loadMoveout(); }

// -- Stufe 1: Kennzahlen ---------------------------------------------------------

function renderCheap(st, mt) {
  el("mtHead-raw").textContent = tpl(STRINGS.mtLocations, { n: fmtNum(st.total_locations) });
  el("mtMeter-raw").innerHTML = `<div class="mh"><b>…</b><span>${STRINGS.mtChecking}</span></div>`;
  el("mtMeter-thumbs").innerHTML = `<div class="mh"><b>…</b><span>${STRINGS.mtThumbsHave}</span></div>`;
  el("mtMeter-db").innerHTML = `
    <div class="mh"><b id="mtDbSize">…</b><span id="mtDbWal"></span></div>
    <div id="mtDbBreak"></div>
    ${mt.dbstat
      ? `<div style="margin-top:8px"><button type="button" id="mtDbCalc">${STRINGS.mtDbBreakdown}</button></div>
         <div class="stephint">${STRINGS.mtDbBreakdownHint}</div>`
      : `<div class="stephint">${STRINGS.mtDbNA}</div>`}`;
  const max = Math.max(1, ...mt.parsers.map((p) => p.items));
  const uninterpreted = Math.max(0, (st.items_with_metadata || 0) - (st.items_interpreted || 0));
  el("mtHead-reeval").textContent = `${fmtNum(st.items_interpreted)} / ${fmtNum(st.total_items)}`;
  el("mtMeter-reeval").innerHTML = `
    <div class="mh"><span>${STRINGS.mtParsers}</span><span>${STRINGS.mtItems}</span></div>
    <div class="hbars mtparsers">${mt.parsers.map((p) => {
      const z = p.items ? "" : " zero";
      const v = p.version == null ? STRINGS.mtParserGone : tpl(STRINGS.mtParserVersion, { v: p.version });
      return `<span class="l${z}">${esc(p.parser)} <span class="vdim">${esc(v)}</span></span><span class="b${z}"><i style="width:${(p.items / max) * 100}%"></i></span><span class="v${z}">${fmtNum(p.items)}</span>`;
    }).join("")}</div>
    <div class="legend" style="margin-top:8px"><span>${tpl(STRINGS.mtUninterpreted, { n: fmtNum(uninterpreted) })}</span><span>${tpl(STRINGS.mtUndated, { n: fmtNum(mt.undated) })}</span></div>`;
}

// -- Stufe 2: /api/admin/info mit dem gemerkten Stand der teuren Zähler (#118) --------

async function loadInfo() {
  try { info = await getAdminInfo(); } catch (err) {
    el("mtMeter-raw").innerHTML = `<span class="warn">${esc(err.message)}</span>`;
    return;
  }
  if (!root.isConnected) return;
  const total = stats ? stats.total_locations : 0;
  const o = info.orphans, checkingO = isChecking(info, "orphans");
  const orphans = o ? o.count : 0;
  el("mtMeter-raw").innerHTML = (o ? `
    <div class="mh"><b>${fmtNum(orphans)}</b><span>${orphans ? `${STRINGS.mtOrphans} · ${pct(orphans, total)} %` : STRINGS.mtOrphansNone}</span></div>
    <div class="bar"><i class="${orphans ? "warnc" : "okc"}" style="width:${orphans ? Math.max(1, pct(orphans, total)) : 100}%"></i></div>
    <div class="legend"><span><i class="gray"></i>${STRINGS.mtAtPlace} <b>${fmtNum(Math.max(0, total - orphans))}</b></span><span><i style="background:var(--warnc)"></i>${STRINGS.mtOrphaned} <b>${fmtNum(orphans)}</b></span></div>`
    : `<div class="mh"><b class="pending">${checkingO ? "…" : "?"}</b><span>${checkingO ? STRINGS.standChecking : STRINGS.standNotChecked}</span></div>`) + `
    <div class="stephint">${o ? `${standNote(info, "orphans", "")} · ` : ""}${STRINGS.mtCheckOrphansHint}</div>
    <div style="margin-top:8px"><button type="button" id="mtOrphCheck"${checkingO ? " disabled" : ""}>${STRINGS.prCheck}</button></div>`;
  const items = stats ? stats.total_items : 0;
  const c = info.cache, checkingC = isChecking(info, "cache");
  el("mtHead-thumbs").textContent = tpl(STRINGS.mtCache, { size: c ? fmtBytes(c.bytes) : "?" });
  el("mtMeter-thumbs").innerHTML = (c ? `
    <div class="mh"><b>${fmtNum(c.count)}</b><span>${STRINGS.mtThumbsHave} · ${tpl(STRINGS.mtThumbsOf, { n: fmtNum(items) })}</span></div>
    <div class="bar"><i class="okc" style="width:${Math.min(100, pct(c.count, items))}%"></i></div>`
    : `<div class="mh"><b class="pending">${checkingC ? "…" : "?"}</b><span>${checkingC ? STRINGS.standChecking : STRINGS.standNotCounted}</span></div>`) + `
    <div class="stephint">${c ? `${standNote(info, "cache", "")} · ` : ""}${STRINGS.mtThumbsHint} ${STRINGS.mtCountCacheHint}</div>
    <div style="margin-top:8px"><button type="button" id="mtCacheCount"${checkingC ? " disabled" : ""}>${STRINGS.mtCountCache}</button></div>`;
  el("mtHead-db").textContent = tpl(STRINGS.mtSchema, { n: info.schema_version });
  el("mtDbSize").textContent = fmtBytes(info.db_bytes);
  el("mtDbWal").textContent = tpl(STRINGS.mtDbWal, { size: fmtBytes(info.wal_bytes) });
  // Hintergrund-Zählung nach einer Aufgabe: nachfragen, bis der Stand da ist.
  clearTimeout(recheck);
  if ((info.checking || []).length) recheck = setTimeout(() => { if (root && root.isConnected) loadInfo(); }, timing.recheckMs);
}

// Zählen auf Klick (#118): der Server merkt sich das Ergebnis, danach den
// Stand neu laden — beide Meter und die Übersicht zeigen dieselbe Zahl.
async function countNow(btn, meter, fetcher) {
  btn.disabled = true;
  const note = el(meter).querySelector(".mh span");
  if (note) note.textContent = STRINGS.standChecking;
  try { await fetcher(); } catch (err) {
    el(meter).innerHTML = `<span class="warn">${esc(err.message)}</span>`;
    return;
  }
  if (root.isConnected) loadInfo();
}

async function loadDbBreakdown(btn) {
  btn.disabled = true;
  try {
    const d = await getDbBreakdown();
    if (!root.isConnected) return;
    const box = el("mtDbBreak");
    if (!d.available) { box.innerHTML = `<div class="stephint">${STRINGS.mtDbNA}</div>`; return; }
    const names = { raw: STRINGS.mtDbRaw, items: STRINGS.mtDbItems, interpreted: STRINGS.mtDbInterp,
                    search: STRINGS.mtDbSearch, other: STRINGS.mtDbOther };
    const cls = { raw: "", items: "s2", interpreted: "s3", search: "s4", other: "s5" };
    const total = Math.max(1, d.groups.reduce((a, g) => a + g.bytes, 0) + d.free_bytes);
    const parts = [...d.groups.map((g) => ({ key: g.key, bytes: g.bytes })), { key: "free", bytes: d.free_bytes }];
    box.innerHTML = `
      <div class="comp" style="margin:8px 0 0;height:10px">${parts.map((g) =>
        `<i class="${g.key === "free" ? "rest" : cls[g.key]}" style="width:${(g.bytes / total) * 100}%" title="${esc(names[g.key] || STRINGS.mtDbFree)}"></i>`).join("")}</div>
      <div class="lg" style="margin-top:7px">${parts.map((g) =>
        `<i class="${g.key === "free" ? "rest" : cls[g.key]}"></i><span class="n">${esc(names[g.key] || STRINGS.mtDbFree)}</span><span class="v">${fmtBytes(g.bytes)}</span><span class="p">${pct(g.bytes, total)} %</span>`).join("")}</div>
      <div class="stephint">${tpl(STRINGS.mtDbIndexes, { size: fmtBytes(d.index_bytes) })}</div>`;
  } catch (err) {
    el("mtDbBreak").innerHTML = `<span class="warn">${esc(err.message)}</span>`;
  } finally { btn.disabled = false; }
}

// -- Zustand der Aktionszeilen aus dem Status-Poll ----------------------------------

const labelKey = (l) => (l && typeof l === "object" ? l.key : null);

function applyStatus(s) {
  const running = s.running ? labelKey(s.label) : null;
  const queue = (s.queue || []).map(labelKey);
  const hist = s.history || [];
  for (const a of actions.values()) {
    if (!a.task) continue;
    const st = root.querySelector(`[data-st="${a.id}"]`);
    const btn = root.querySelector(`[data-run="${a.id}"]`);
    if (!st || !btn) continue;
    const qpos = queue.indexOf(a.task);
    if (running === a.task) {
      const cf = s.current_file && s.current_file.params;
      const counter = cf && cf.total ? ` · ${fmtNum(cf.index)} / ${fmtNum(cf.total)}` : "";
      st.className = "st running";
      st.innerHTML = `${STRINGS.mtStRunning}${counter} · ${fmtElapsed(s.elapsed)}<div class="bar"><i style="width:${progressPercent(s)}%"></i></div>`;
      btn.disabled = true; btn.textContent = STRINGS.mtRunning;
    } else if (qpos >= 0) {
      st.className = "st queued";
      st.textContent = tpl(STRINGS.mtStQueued, { n: qpos + 1 });
      btn.disabled = true; btn.textContent = STRINGS.mtWaiting;
    } else {
      btn.disabled = false; btn.textContent = a.btn;
      const last = hist.find((h) => labelKey(h.label) === a.task);
      if (last) {
        const when = last.finished_at ? fmtTime(new Date(last.finished_at), false) : "";
        st.className = `st ${last.ok ? "done" : "failed"}`;
        st.textContent = `${last.ok ? "✓" : "✗"} ${serverMsg(last.result) || (last.ok ? "" : STRINGS.mtStFailed)}${when ? ` · ${when}` : ""}`;
      } else if (st.dataset.keep !== "1") {
        st.className = "st"; st.textContent = "";
      }
    }
  }
  renderMoveoutRun(s, running, hist);
}

function renderMoveoutRun(s, running, hist) {
  const box = el("moRun");
  if (!box) return;
  if (running === "taskMoveout") {
    const cf = s.current_file && s.current_file.params;
    const r = s.report || {};
    box.hidden = false; box.classList.remove("done");
    el("moDot").className = "dot";
    el("moRunTitle").textContent = serverMsg(s.label);
    el("moElapsed").textContent = fmtElapsed(s.elapsed);
    el("moBar").style.width = `${progressPercent(s)}%`;
    el("moFile").textContent = cf && cf.name ? cf.name : "";
    // Nur der Zähler „n / gesamt" — was passiert, sagt die Überschrift.
    el("moCnts").innerHTML = `<span><b>${fmtNum(r.media_files || 0)}</b>${cf && cf.total ? ` / ${fmtNum(cf.total)}` : ""}</span>`;
    el("moGo").disabled = true;
    return;
  }
  const last = hist.find((h) => labelKey(h.label) === "taskMoveout");
  if (last && !box.hidden) {
    box.classList.toggle("done", !!last.ok);
    el("moDot").className = `dot ${last.ok ? "idle" : "dead"}`;
    el("moRunTitle").textContent = serverMsg(last.result);
    el("moElapsed").textContent = last.elapsed != null ? fmtElapsed(last.elapsed) : "";
    el("moBar").style.width = "100%";
    el("moFile").textContent = "";
    // Endstand „verschoben / Kandidaten" aus der Zusammenfassung, nicht aus
    // dem letzten Zwischenstand: der Fortschritt wird VOR jeder Datei
    // gemeldet, und der letzte Poll kann Dateien zurückliegen (Befund
    // 2026-09-13: „3 / 78" unter „78 rausverschoben"). Die Teile
    // (verschoben, fehlt, verändert, Fehler) stehen als Meldungs-Dicts im
    // Ergebnis; ihre Summe ist die Zahl der Kandidaten.
    const parts = last.result && last.result.params && Array.isArray(last.result.params.parts)
      ? last.result.params.parts : [];
    const n = (m) => Number((m.params || {}).n || 0);
    const moved = parts.filter((m) => m.key === "sumMoveMoved").reduce((a, m) => a + n(m), 0);
    const total = parts.reduce((a, m) => a + n(m), 0);
    el("moCnts").innerHTML = parts.length ? `<span><b>${fmtNum(moved)}</b> / ${fmtNum(total)}</span>` : "";
  }
}

// -- Klicks -------------------------------------------------------------------------

async function onClick(e) {
  const run = e.target.closest("[data-run]");
  if (run) return void runAction(run.dataset.run, run);
  if (e.target.closest("#mtDbCalc")) return void loadDbBreakdown(e.target.closest("#mtDbCalc"));
  if (e.target.closest("#mtOrphCheck")) return void countNow(e.target.closest("#mtOrphCheck"), "mtMeter-raw", () => getOrphans(null));
  if (e.target.closest("#mtCacheCount")) return void countNow(e.target.closest("#mtCacheCount"), "mtMeter-thumbs", getThumbCache);
  if (e.target.closest("#moPick")) {
    const chosen = await pickFolder(el("moTarget").value.trim() || null);
    if (chosen) { el("moTarget").value = chosen; updateMoveoutArm(); }
    return;
  }
  if (e.target.closest("#moRefresh")) return void loadMoveout();
  if (e.target.closest("#moGo")) return void runMoveout();
  if (e.target.closest("#irCheck")) return void loadRules(true);
  if (e.target.closest("#irGo")) return void runImportRules();
  if (e.target.closest("#prPick")) {
    const chosen = await pickFolder(el("prPath").value.trim() || null);
    if (chosen) { el("prPath").value = chosen; resetPrunePreview(); }
    return;
  }
  if (e.target.closest("#prCheck")) return void checkOrphans();
  if (e.target.closest("#prGo")) return void runPrune();
}

async function runAction(aid, btn) {
  const a = actions.get(aid);
  const st = root.querySelector(`[data-st="${aid}"]`);
  try {
    if (a.run === "thumbs") {
      btn.disabled = true;
      const r = await clearThumbCache();
      st.dataset.keep = "1";
      st.className = "st done";
      st.textContent = `✓ ${fmtNum(r.deleted)} ${STRINGS.maintThumbsCleared} · ${fmtTime(new Date(), false)}`;
      btn.disabled = false;
      loadInfo();
    } else {
      btn.disabled = true;
      await a.run();
      st.className = "st queued";
      st.textContent = STRINGS.mtStQueuedNow;
    }
  } catch (err) {
    btn.disabled = false;
    st.className = "st failed";
    st.textContent = err.message;
  }
}

// -- Karte: Abgelehnte rausverschieben (I3, ADR 0041) -----------------------------------

async function loadMoveout() {
  const box = el("moInfo");
  if (!box) return;
  try {
    moveout = await getMoveout();
  } catch (err) { box.innerHTML = `<span class="warn">${esc(err.message)}</span>`; return; }
  if (!root.isConnected) return;
  const d = moveout;
  if (d.locked) box.innerHTML = `<span class="warn">${STRINGS.modeLocked}</span>`;
  else if (!d.available) box.innerHTML = `<span class="warn">${STRINGS.moNoLibrary}</span>`;
  else if (!d.movable) {
    box.innerHTML = `<span class="adok">${STRINGS.moNone}</span>` +
      (d.missing ? `<div class="vdim">${tpl(STRINGS.moMissing, { n: fmtNum(d.missing) })}</div>` : "");
  } else {
    box.innerHTML = [
      `<b>${tpl(STRINGS.moCount, { n: fmtNum(d.movable), gb: fmtBytes(d.bytes) })}</b>`,
      d.missing ? `<div class="vdim">${tpl(STRINGS.moMissing, { n: fmtNum(d.missing) })}</div>` : "",
      `<div class="paths-sample">${d.sample.map((p) => `<div class="rpath vmono">${esc(p)}</div>`).join("")}${
        d.movable > d.sample.length ? `<div class="vdim">${tpl(STRINGS.moMore, { n: fmtNum(d.movable - d.sample.length) })}</div>` : ""}</div>`,
    ].join("");
  }
  el("moGo").textContent = tpl(STRINGS.moGoN, { n: fmtNum(d.movable || 0) });
  updateMoveoutArm();
}

function updateMoveoutArm() {
  const ready = !!(moveout && moveout.available && !moveout.locked && moveout.movable && el("moTarget").value.trim());
  const arm = el("moArm");
  arm.disabled = !ready;
  if (!ready) arm.checked = false;
  el("moGo").disabled = !(ready && arm.checked);
}

async function runMoveout() {
  const msg = el("moMsg");
  const target = el("moTarget").value.trim();
  if (!target) { msg.className = "st failed"; msg.textContent = STRINGS.moNoTarget; return; }
  try {
    el("moGo").disabled = true;
    await startMoveout(target);
    el("moArm").checked = false;
    msg.className = "st queued";
    msg.textContent = STRINGS.mtStQueuedNow;
    el("moRun").hidden = false;
  } catch (err) {
    msg.className = "st failed";
    msg.textContent = err.message;
    updateMoveoutArm();
  }
}

// -- Karte: Import-Regeln auf den Bestand (ADR 0046) ----------------------------------

async function loadRules(checked = false) {
  const rules = el("irRules"), prev = el("irPrev");
  if (!rules) return;
  try {
    rulesPreview = await getImportRulesPreview();
  } catch (err) { prev.innerHTML = `<span class="warn">${esc(err.message)}</span>`; return; }
  if (!root.isConnected) return;
  const p = rulesPreview;
  const r = p.rules || {};
  const parts = [];
  if (r.min_kante) parts.push(`${STRINGS.irRuleMin} <code>${fmtNum(r.min_kante)} px</code>`);
  if (r.max_kante) parts.push(`${STRINGS.irRuleMax} <code>${fmtNum(r.max_kante)} px</code>`);
  if (r.formate && r.formate.length) parts.push(`${STRINGS.irRuleFormats} <code>${esc(r.formate.join(", "))}</code>`);
  if (r.min_date) parts.push(`${STRINGS.irRuleDate} <code>${esc(String(r.min_date).slice(0, 10))}</code>`);
  rules.innerHTML = parts.length ? parts.join(" · ") : `<span class="vdim">${STRINGS.irNoRules}</span>`;
  // ADR 0046: erst die ehrliche Vorschau (Zahlen je Grund), dann scharf
  // schalten — Ablehnen ist umkehrbar (Sperrliste), Dateien bleiben.
  if (!p.active) prev.innerHTML = `<span class="vdim">${STRINGS.importRulesNone}</span>`;
  else if (!p.total) prev.innerHTML = `<span class="adok">${STRINGS.importRulesNoHits}</span>`;
  else {
    const c = p.counts || {};
    const why = [];
    if (c.min_kante) why.push(`${fmtNum(c.min_kante)} ${STRINGS.importRulesTooSmall}`);
    if (c.max_kante) why.push(`${fmtNum(c.max_kante)} ${STRINGS.importRulesTooBig}`);
    if (c.formate) why.push(`${fmtNum(c.formate)} ${STRINGS.importRulesFormat}`);
    if (c.datum) why.push(`${fmtNum(c.datum)} ${STRINGS.importRulesNoDate}`);
    prev.innerHTML = `<b>${fmtNum(p.total)}</b> ${STRINGS.importRulesHits}<div class="vdim">${why.join(" · ")}</div>`;
  }
  const armable = !!(p.active && p.total && checked);
  el("irArm").disabled = !armable;
  if (!armable) el("irArm").checked = false;
  el("irGo").disabled = true;
  el("irGo").textContent = tpl(STRINGS.irGoN, { n: fmtNum(p.total || 0) });
}

async function runImportRules() {
  const msg = el("irMsg");
  try {
    el("irGo").disabled = true;
    await applyImportRules();
    el("irArm").checked = false; el("irArm").disabled = true;
    msg.className = "st queued";
    msg.textContent = STRINGS.mtStQueuedNow;
  } catch (err) { msg.className = "st failed"; msg.textContent = err.message; }
}

// -- Karte: Verwaiste Fundorte aufräumen (ADR 0033) ---------------------------------

const pruneScope = () => (el("prScopeUnder").checked ? el("prPath").value.trim() : null);

function onPruneScope() {
  const under = el("prScopeUnder").checked;
  el("prPath").disabled = !under;
  el("prPick").disabled = !under;
  resetPrunePreview();
}

function resetPrunePreview() {
  orphanPreview = null;
  el("prPrev").innerHTML = `<span class="vdim">${STRINGS.prNotChecked}</span>`;
  el("prArm").checked = false; el("prArm").disabled = true;
  el("prGo").disabled = true;
  el("prGo").textContent = tpl(STRINGS.prGoN, { n: 0 });
}

async function checkOrphans() {
  const prev = el("prPrev"), btn = el("prCheck");
  if (el("prScopeUnder").checked && !pruneScope()) {
    prev.innerHTML = `<span class="warn">${STRINGS.prNoFolder}</span>`; return;
  }
  const under = pruneScope();
  btn.disabled = true;
  prev.innerHTML = `<span class="vdim">${STRINGS.prChecking}</span>`;
  try {
    orphanPreview = await getOrphans(under);
  } catch (err) { prev.innerHTML = `<span class="warn">${esc(err.message)}</span>`; btn.disabled = false; return; }
  finally { btn.disabled = false; }
  if (!root.isConnected) return;
  const d = orphanPreview;
  d.under = under;
  if (!d.total) prev.innerHTML = `<span class="adok">${STRINGS.prNone}</span>`;
  else {
    prev.innerHTML = `<b>${under
      ? tpl(STRINGS.prCountUnder, { n: fmtNum(d.total), path: esc(under) })
      : tpl(STRINGS.prCount, { n: fmtNum(d.total) })}</b>
      <div class="paths-sample">${d.sample.map((p) => `<div class="rpath vmono">${esc(p)}</div>`).join("")}${
        d.total > d.sample.length ? `<div class="vdim">${tpl(STRINGS.prMore, { n: fmtNum(d.total - d.sample.length) })}</div>` : ""}</div>`;
  }
  el("prArm").disabled = !d.total;
  el("prArm").checked = false;
  el("prGo").disabled = true;
  el("prGo").textContent = tpl(STRINGS.prGoN, { n: fmtNum(d.total) });
  if (!under) loadInfo();   // „überall" ist der volle Stand — der Server hat ihn gemerkt (#118)
}

async function runPrune() {
  const msg = el("prMsg");
  if (!orphanPreview) return;
  try {
    el("prGo").disabled = true;
    const r = await pruneOrphans(orphanPreview.under);
    msg.className = "st done";
    msg.textContent = `✓ ${fmtNum(r.pruned)} ${STRINGS.maintPruned} · ${fmtTime(new Date(), false)}`;
    resetPrunePreview();
    loadInfo();
  } catch (err) { msg.className = "st failed"; msg.textContent = err.message; }
}
