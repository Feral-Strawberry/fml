// admin/pages/overview.js — Seite „Übersicht" (ADR 0074 + Nachtrag,
// Mockup #104 Runde 5): Bestand, laufende Arbeit und Systemzustand.
//
// Vier feste Reihen (keine Verschachtelung, gleiche Kachelhöhen):
//   1. Bestand — Kennzahl-Kacheln mit Quoten-Balken + drei Felder
//      (Zusammensetzung nach Typ, Zuwachs 30 Tage, Jahrgänge)
//   2. Aktivität — laufende Aufgabe mit Balken, Trichter „wo fällt was ab",
//      „Neu in diesem Lauf" + Durchsatz-Sparkline, Warteschlange + Verlauf
//   3. System — sechs Zustandskacheln + Pfadzeile
//   4. Hinweiskarten (verwaiste Fundorte, Probleme, Sperrliste, Quellen)
// Diagramm-Regel: Donut nur bei EINER Prozent-Aussage (Speicherplatz),
// Stapelbalken mit Tabellen-Legende, Säulen für Zeit, Trichter für Flüsse.
// Alles inline SVG/CSS, keine Abhängigkeit.
//
// Daten in zwei Stufen (erster Test 2026-09-12: die Seite blieb Sekunden
// leer): ZUERST /api/stats + /api/admin/overview (beide epochen-gecacht,
// Millisekunden) — Kennzahlen, Diagramme, Instanz stehen sofort; DANACH
// /api/admin/info für Thumbnails, DB, Werkzeuge, Parser, Fundorte,
// Probleme, Sperrliste. Bis dahin zeigen diese Stellen „…". Verwaiste
// Fundorte und Cache-Größe sind seit #118 (ADR 0077) ein GEMERKTER STAND
// mit Zeitstempel („Stand 18:23"), nie ein Platten-Lauf beim Seitenladen:
// „?" heißt noch nie gezählt (Wartung: Fundorte prüfen / Cache zählen);
// läuft nach einer Aufgabe eine Hintergrund-Zählung, steht „wird geprüft …"
// und die Seite fragt nach, bis der Stand da ist. Alles erneut nach jeder
// fertigen Aufgabe; die Aktivität aus jedem Poll. Die Durchsatz-Kurve
// entsteht hier aus den Poll-Deltas (keine Serverzahl).

import { STRINGS } from "../../strings.js";
import { getStats, getAdminInfo, getAdminOverview } from "../../api.js";
import { serverMsg } from "../../servermsg.js";
import { isBusy } from "../../status.js";
import { setNavCount, setNavMeta, progressPercent } from "../nav.js";
import { esc, fmtBytes, fmtElapsed, fmtNum, fmtTime, pct, tpl, timing, standNote, standValue } from "../util.js";

export const id = "overview";
export const icon = '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="8" height="8" rx="1.5"/><rect x="13" y="3" width="8" height="5" rx="1.5"/><rect x="13" y="11" width="8" height="10" rx="1.5"/><rect x="3" y="14" width="8" height="7" rx="1.5"/></svg>';
export const title = () => STRINGS.adminOverview;
export const subtitle = () => STRINGS.subOverview;

let root = null;
let stats = null;       // /api/stats (schnell)
let info = null;        // /api/admin/info (teuer, kommt nach)
let ov = null;          // /api/admin/overview
const PENDING = '<span class="pending">…</span>';
let loadSeq = 0;        // Antworten alter Ladevorgänge verwerfen (Seitenwechsel)
let lastStatus = null;
let recheck = null;     // Nachfrage-Timer, solange eine Hintergrund-Zählung läuft (#118)
const el = (sel) => root.querySelector("#" + sel);

// Durchsatz-Kurve: Messpunkte {t, n} des laufenden Laufs (letzte 3 min).
const SPARK_WINDOW = 180;
let samples = [];
let sampleRun = null;   // started_at des Laufs, zu dem die Punkte gehören

export function render(target) {
  root = target;
  root.innerHTML = `
    <div class="row"><div class="card">
      <div class="chead"><span class="mlabel">${STRINGS.ovStock}</span><span class="right">${STRINGS.ovOneSource}</span></div>
      <div class="kpis" id="kpis"></div>
      <div class="panels">
        <div class="panel"><div class="mlabel"><span>${STRINGS.ovByType}</span><span>${STRINGS.statItems}</span></div><div id="pType"></div></div>
        <div class="panel"><div class="mlabel"><span>${STRINGS.ovGrowth}</span><span id="growSum"></span></div><div class="cols" id="growCols"></div><div class="axis"><span>${STRINGS.ovAgo30}</span><span id="growAvg"></span><span>${STRINGS.ovToday}</span></div></div>
        <div class="panel"><div class="mlabel"><span>${STRINGS.ovYears}</span><span>${STRINGS.statItems}</span></div><div class="cols wide" id="yearCols"></div><div class="axis even" id="yearAxis"></div></div>
      </div>
    </div></div>

    <div class="row"><div class="card">
      <div class="chead"><span class="mlabel">${STRINGS.adminActivity}</span><span class="right" id="aWorker"></span></div>
      <div class="acthead"><span class="dot idle" id="aDot"></span><span class="task" id="aTask"></span><span class="mono vdim" id="aElapsed"></span><span class="file" id="aFile"></span></div>
      <div class="bar big"><i id="aBar" style="width:0%"></i></div>
      <div class="progline"><span id="aLeft"></span><span id="aRight"></span></div>
      <div class="panels">
        <div class="panel"><div class="mlabel"><span>${STRINGS.ovResult}</span><span>${STRINGS.ovWhereDrop}</span></div><div class="funnel" id="funnel"></div><div class="vdim" id="funnelNone" hidden>${STRINGS.ovNoReport}</div></div>
        <div class="panel">
          <div class="mlabel"><span>${STRINGS.ovNewInRun}</span><span>${STRINGS.statItems}</span></div>
          <div class="hero2">+<span id="lNew">0</span><small id="lNewSub"></small></div>
          <div class="bar thin" style="margin-top:8px"><i id="sNew" style="width:0%"></i></div>
          <div class="spark" style="margin-top:12px">
            <div class="mlabel" style="display:flex;justify-content:space-between;margin-bottom:6px"><span>${STRINGS.ovThroughput}</span><span><b class="mono" id="spNow" style="color:var(--text)">–</b> ${STRINGS.ovRate}</span></div>
            <svg id="spark" viewBox="0 0 300 64" preserveAspectRatio="none">
              <defs><linearGradient id="spg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--accent)" stop-opacity=".28"/><stop offset="1" stop-color="var(--accent)" stop-opacity="0"/></linearGradient></defs>
              <path id="spArea" fill="url(#spg)" d=""/><path id="spLine" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round" d=""/>
              <circle id="spDot" r="3.5" fill="var(--accent)" stroke="var(--panel2)" stroke-width="2" cx="-10" cy="-10"/>
            </svg>
            <div class="axis"><span>${STRINGS.ovAgo3}</span><span>${STRINGS.ovNow}</span></div>
          </div>
        </div>
        <div class="panel">
          <div class="mlabel"><span>${STRINGS.statusQueueTitle}</span><span id="qCount">0</span></div>
          <ol class="qlist" id="qlist"></ol>
          <div class="mlabel" style="display:flex;justify-content:space-between;margin-bottom:8px"><span>${STRINGS.ovHistory}</span><span>${STRINGS.ovDuration}</span></div>
          <div class="gantt" id="gantt"></div>
        </div>
      </div>
    </div></div>

    <div class="row"><div class="card">
      <div class="chead"><span class="mlabel">${STRINGS.ovSystem}</span><span class="right" id="sysRight"></span></div>
      <div class="tiles" id="tiles"></div>
      <div class="paths" id="paths"></div>
    </div></div>

    <div class="row c4" id="hints"></div>`;
  document.getElementById("pageHead").innerHTML =
    `<span class="mlabel">${tpl(STRINGS.ovStand, { t: '<span id="clock"></span>' })}</span>`;
}

export async function load() {
  const seq = ++loadSeq;
  const infoRequest = getAdminInfo();      // parallel starten, später einsammeln
  infoRequest.catch(() => {});             // Fehler kommt unten ans Licht
  try {
    [stats, ov] = await Promise.all([getStats(), getAdminOverview()]);
  } catch (err) {
    el("kpis").innerHTML = `<span class="warn">${esc(err.message)}</span>`;
    return;
  }
  if (seq !== loadSeq || !root.isConnected) return;
  renderStock();
  renderSystem();
  renderHints();
  setNavMeta(ov.port ? `:${ov.port}` : "");
  if (lastStatus) renderActivity(lastStatus);
  try {
    const fresh = await infoRequest;
    if (seq !== loadSeq || !root.isConnected) return;
    info = fresh;
  } catch (err) {
    if (seq !== loadSeq || !root.isConnected) return;
    el("sysRight").innerHTML = `<span class="warn">${esc(err.message)}</span>`;
    return;
  }
  renderStock();
  renderSystem();
  renderHints();
  setNavCount("issues", info.open_issues || null);
  setNavMeta(`${tpl(STRINGS.tileSchema, { v: info.schema_version })}${ov.port ? ` · :${ov.port}` : ""}`);
  if (lastStatus) renderActivity(lastStatus);
  scheduleRecheck();
}

export function onTaskFinished() { if (root && root.isConnected) load(); }

// Läuft eine Hintergrund-Zählung (info.checking), in timing.recheckMs nur
// /api/admin/info nachladen — billig — bis der Stand da ist.
function scheduleRecheck() {
  clearTimeout(recheck);
  if (info && (info.checking || []).length) recheck = setTimeout(reloadInfo, timing.recheckMs);
}

async function reloadInfo() {
  if (!root || !root.isConnected) return;
  const seq = loadSeq;
  let fresh;
  try { fresh = await getAdminInfo(); } catch { return; }
  if (seq !== loadSeq || !root.isConnected) return;
  info = fresh;
  renderStock();
  renderSystem();
  renderHints();
  scheduleRecheck();
}

export function onStatus(s) {
  lastStatus = s;
  if (!root || !root.isConnected) return;
  const clock = document.getElementById("clock");
  if (clock) clock.textContent = fmtTime();
  renderActivity(s);
  renderSourceHint(s);
}

// -- Reihe 1: Bestand ------------------------------------------------------------

function kpi(value, label, sub, bar) {
  return `<div class="kpi"><div class="v">${value}</div><div class="k">${label}</div>
    ${sub ? `<div class="q"><span>${sub[0]}</span><span>${sub[1]}</span></div>` : ""}
    ${bar != null ? `<div class="bar thin"><i style="width:${Math.min(100, bar)}%"></i></div>` : ""}</div>`;
}

function big(bytes) {
  // Wert + Einheit getrennt (Einheit klein), wie im Mockup.
  const [v, unit] = fmtBytes(bytes).split(" ");
  return `${v}<small>${unit}</small>`;
}

function renderStock() {
  const st = stats || {};
  const total = st.total_items || 0;
  const today = ov.growth.length ? ov.growth[ov.growth.length - 1].count : 0;
  el("kpis").innerHTML =
    kpi(fmtNum(total), STRINGS.statItems, [STRINGS.ovAllTypes, tpl(STRINGS.ovNewToday, { n: fmtNum(today) })]) +
    (st.library_configured
      ? kpi(big(st.library_bytes), STRINGS.statLibraryShort, [STRINGS.ovIndexedTotal, fmtBytes(st.total_bytes)],
            pct(st.library_bytes, st.total_bytes))
      : kpi(big(st.total_bytes), STRINGS.ovIndexedTotal, [STRINGS.ovNoLibrary, ""])) +
    kpi(fmtNum(st.items_with_metadata), STRINGS.statWithMeta, [STRINGS.ovQuote, `${pct(st.items_with_metadata, total)} %`], pct(st.items_with_metadata, total)) +
    kpi(fmtNum(st.items_interpreted), STRINGS.statInterpretedItems, [STRINGS.ovQuote, `${pct(st.items_interpreted, total)} %`], pct(st.items_interpreted, total)) +
    (info
      ? kpi(standValue(info, "cache", (c) => fmtNum(c.count)), STRINGS.statThumbs,
            [STRINGS.ovCache, `${info.cache ? `${fmtBytes(info.cache.bytes)} · ` : ""}${standNote(info, "cache", STRINGS.standNotCounted)}`],
            info.cache ? pct(info.cache.count, total) : null)
        + kpi(big(info.db_bytes + info.wal_bytes), STRINGS.statDb, [STRINGS.ovWal, fmtBytes(info.wal_bytes)])
      : kpi(PENDING, STRINGS.statThumbs, [STRINGS.ovCache, "…"]) + kpi(PENDING, STRINGS.statDb, [STRINGS.ovWal, "…"]));

  // Zusammensetzung nach Typ: Stapelbalken + Tabellen-Legende (Top 5 + Rest).
  const byc = st.by_container || [];
  const top = byc.slice(0, 5);
  const rest = byc.slice(5).reduce((a, b) => a + b.count, 0);
  const segs = [...top.map((c, i) => ({ n: c.container.toUpperCase(), v: c.count, cls: i ? `s${i + 1}` : "" })),
                ...(rest ? [{ n: STRINGS.ovOther, v: rest, cls: "rest" }] : [])];
  const kinds = Object.fromEntries(ov.by_kind.map((k) => [k.kind, k]));
  // Beide Typen gleich: Anteil an der Stückzahl · Speicher (Summe = „katalogisiert
  // gesamt" oben). Vorher stand nur bei Videos eine unbeschriftete GB-Zahl.
  const img = kinds.image || { count: 0, bytes: 0 };
  const vid = kinds.video || { count: 0, bytes: 0 };
  el("pType").innerHTML = total ? `
    <div class="comp">${segs.map((s) => `<i class="${s.cls}" style="width:${(s.v / total) * 100}%" title="${esc(s.n)} ${fmtNum(s.v)}"></i>`).join("")}</div>
    <div class="lg">${segs.map((s) => `<i class="${s.cls}"></i><span class="n">${esc(s.n)}</span><span class="v">${fmtNum(s.v)}</span><span class="p">${pct(s.v, total)} %</span>`).join("")}</div>
    <div class="axis" style="margin-top:auto;padding-top:8px"><span>${STRINGS.ovImages} ${pct(img.count, total)} % · ${fmtBytes(img.bytes)}</span><span>${STRINGS.ovVideos} ${pct(vid.count, total)} % · ${fmtBytes(vid.bytes)}</span></div>`
    : `<div class="vdim">${STRINGS.ovEmpty}</div>`;

  // Zuwachs je Tag: 30 Säulen, heute hervorgehoben.
  const g = ov.growth;
  const gmax = Math.max(1, ...g.map((d) => d.count));
  const gsum = g.reduce((a, d) => a + d.count, 0);
  el("growCols").innerHTML = g.map((d, i) =>
    `<i style="height:${(d.count / gmax) * 100}%" title="${d.day}: ${fmtNum(d.count)}"${i === g.length - 1 ? ' class="hi"' : ""}></i>`).join("");
  el("growSum").innerHTML = `<b>${fmtNum(gsum)}</b> ${STRINGS.ovNew}`;
  el("growAvg").textContent = tpl(STRINGS.ovGrowthAvg, { n: fmtNum(Math.round(gsum / Math.max(1, g.length))) });

  // Jahrgänge: Säulen breit, jüngstes Jahr hervorgehoben, „ohne Datum" gedämpft.
  const years = ov.by_year.filter((y) => y.year);
  const none = ov.by_year.find((y) => !y.year);
  const shown = years.slice(-8);
  const ymax = Math.max(1, ...shown.map((y) => y.count), none ? none.count : 0);
  el("yearCols").innerHTML = shown.map((y, i) =>
    `<i style="height:${(y.count / ymax) * 100}%"${i === shown.length - 1 ? ' class="hi"' : ""} title="${y.year}"></i>`).join("")
    + (none ? `<i class="lo" style="height:${(none.count / ymax) * 100}%" title="${STRINGS.ovNoDate}"></i>` : "");
  el("yearAxis").innerHTML = shown.map((y) => `<span>${y.year}<br>${fmtNum(y.count)}</span>`).join("")
    + (none ? `<span>${STRINGS.ovNoDate}<br>${fmtNum(none.count)}</span>` : "");
}

// -- Reihe 2: Aktivität ----------------------------------------------------------

function renderActivity(s) {
  const r = s.report || {};
  const cf = s.current_file && s.current_file.params;
  const dead = s.worker_alive === false;
  const total = stats ? stats.total_items || 0 : 0;

  el("aWorker").textContent = dead ? STRINGS.ovWorkerDead
    : s.worker_alive ? STRINGS.ovWorkerRunning : STRINGS.ovWorkerNever;
  el("aDot").className = s.running ? "dot" : dead ? "dot dead" : s.queue_pending ? "dot warn" : "dot idle";
  if (s.running) {
    el("aTask").textContent = serverMsg(s.label) || STRINGS.activityRunning;
    el("aElapsed").textContent = s.elapsed != null ? fmtElapsed(s.elapsed) : "";
    el("aFile").textContent = s.current_file ? serverMsg(s.current_file) : "";
  } else {
    el("aTask").textContent = dead ? STRINGS.activityWorkerDead
      : s.queue_pending ? `${s.queue_pending} ${STRINGS.statusQueued}`
      : s.last_finished ? `${STRINGS.statusLast} ${serverMsg(s.last_finished)}` : STRINGS.statusReady;
    el("aElapsed").textContent = "";
    el("aFile").textContent = s.last_result ? serverMsg(s.last_result) : "";
  }
  const p = progressPercent(s);
  el("aBar").style.width = `${s.running ? p : 0}%`;
  const rate = updateSamples(s);
  if (s.running && cf && cf.total) {
    el("aLeft").innerHTML = `<b>${fmtNum(cf.index)}</b> / ${fmtNum(cf.total)} ${STRINGS.ovFiles} · <b>${p} %</b>`;
    const rest = rate > 0 ? tpl(STRINGS.ovRest, { t: fmtElapsed((cf.total - cf.index) / rate) }) : "";
    el("aRight").innerHTML = `<b>${rate.toLocaleString(STRINGS.locale, { maximumFractionDigits: 1 })}</b> ${STRINGS.ovRate}${rest ? ` · ${rest}` : ""}`;
  } else if (s.running && r.scanned_files) {
    el("aLeft").innerHTML = `<b>${fmtNum(r.scanned_files)}</b> ${STRINGS.ovFiles}`;
    el("aRight").innerHTML = rate > 0 ? `<b>${rate.toLocaleString(STRINGS.locale, { maximumFractionDigits: 1 })}</b> ${STRINGS.ovRate}` : "";
  } else {
    el("aLeft").innerHTML = "";
    el("aRight").innerHTML = "";
  }

  renderFunnel(r);
  el("lNew").textContent = fmtNum(r.new_items || 0);
  el("lNewSub").textContent = total
    ? `${tpl(STRINGS.ovOfTotal, { n: fmtNum(total) })} · ${((r.new_items || 0) / total * 100).toLocaleString(STRINGS.locale, { maximumFractionDigits: 1 })} %`
    : "";
  el("sNew").style.width = `${total ? Math.max(r.new_items ? 0.4 : 0, (r.new_items || 0) / total * 100) : 0}%`;
  renderSpark(rate);

  const queue = s.queue || [];
  el("qCount").textContent = fmtNum(queue.length);
  el("qlist").innerHTML = queue.length
    ? queue.map((l) => `<li>${esc(serverMsg(l))}</li>`).join("")
    : `<li class="vdim" style="list-style:none;margin-left:-18px">${STRINGS.ovQueueEmpty}</li>`;
  const hist = s.history || [];
  const hmax = Math.max(1, ...hist.map((h) => h.elapsed || 0));
  el("gantt").innerHTML = hist.length ? hist.map((h) => `
    <span class="l" title="${esc(serverMsg(h.result))}">${esc(serverMsg(h.label))}</span>
    <span class="b"><i style="width:${Math.max(3, ((h.elapsed || 0) / hmax) * 100)}%${h.ok ? "" : ";background:var(--bad)"}"></i></span>
    <span class="v${h.ok ? "" : " err"}">${h.elapsed != null ? fmtElapsed(h.elapsed) : "–"}${h.ok ? "" : ` · ${STRINGS.ovFailed}`}</span>`).join("")
    : `<span class="vdim" style="grid-column:1/-1">${STRINGS.ovHistoryEmpty}</span>`;
}

/** Trichter: wo fallen Dateien ab? Stufen aus dem Report, Abfälle dazwischen. */
function renderFunnel(r) {
  const scanned = r.scanned_files || 0;
  el("funnelNone").hidden = scanned > 0;
  el("funnel").hidden = scanned === 0;
  if (!scanned) { el("funnel").innerHTML = ""; return; }
  const taken = (r.new_items || 0) + (r.known_items || 0);
  const steps = [
    [STRINGS.fnScanned, scanned], [STRINGS.fnMedia, r.media_files || 0], [STRINGS.fnTaken, taken],
    [STRINGS.fnWithMeta, r.with_metadata || 0], [STRINGS.fnInterpreted, r.interpreted || 0],
  ];
  const drops = {
    1: [STRINGS.fnDropFiltered, (r.ausgefiltert || 0) + (r.skipped_unknown || 0), false],
    2: [STRINGS.fnDropFailed, r.failed || 0, true],
    3: [STRINGS.fnDropNoMeta, Math.max(0, taken - (r.with_metadata || 0)), false],
    4: [STRINGS.fnDropPending, Math.max(0, (r.with_metadata || 0) - (r.interpreted || 0)), false],
  };
  const max = scanned;
  let html = "";
  steps.forEach(([l, v], i) => {
    if (i && drops[i]) {
      const [dl, dv, bad] = drops[i];
      html += `<span class="drop${bad && dv ? " hit" : ""}">−${fmtNum(dv)} ${dl}</span>`;
    }
    const split = i === 2
      ? `<i class="s2" style="width:${((r.known_items || 0) / max) * 100}%" title="${STRINGS.fnKnown}"></i><i style="width:${((r.new_items || 0) / max) * 100}%" title="${STRINGS.fnNew}"></i>`
      : `<i style="width:${(v / max) * 100}%"></i>`;
    html += `<span class="l">${l}</span><span class="b${i === 2 ? " split" : ""}">${split}</span><span class="v">${fmtNum(v)}</span>`;
  });
  el("funnel").innerHTML = html;
}

/** Messpunkt des laufenden Laufs merken; liefert die aktuelle Rate (Dateien/s). */
function updateSamples(s) {
  if (!s.running) { sampleRun = null; return 0; }
  if (s.started_at !== sampleRun) { samples = []; sampleRun = s.started_at; }
  const cf = s.current_file && s.current_file.params;
  const n = cf && cf.total != null ? cf.index : (s.report || {}).scanned_files;
  if (n == null) return 0;
  const t = Date.now() / 1000;
  samples.push({ t, n });
  samples = samples.filter((p) => t - p.t <= SPARK_WINDOW);
  // Rate über die letzten ~5 Sekunden (glättet Poll-Zittern).
  const ref = samples.find((p) => t - p.t <= 5) || samples[0];
  const dt = t - ref.t;
  return dt > 0 ? Math.max(0, (n - ref.n) / dt) : 0;
}

function renderSpark(rate) {
  const now = el("spNow");
  if (samples.length < 2) {
    now.textContent = "–";
    el("spLine").setAttribute("d", ""); el("spArea").setAttribute("d", "");
    el("spDot").setAttribute("cx", -10);
    return;
  }
  // Raten je Messpunkt (Delta zum Vorgänger), Zeitachse = letzte 3 Minuten.
  const t1 = samples[samples.length - 1].t, t0 = t1 - SPARK_WINDOW;
  const rates = samples.slice(1).map((p, i) => {
    const q = samples[i];
    return { t: p.t, r: p.t > q.t ? Math.max(0, (p.n - q.n) / (p.t - q.t)) : 0 };
  });
  const max = Math.max(...rates.map((p) => p.r), rate, 0.1) * 1.15;
  const pts = rates.map((p) => [((p.t - t0) / SPARK_WINDOW) * 300, 62 - (p.r / max) * 58]);
  const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  el("spLine").setAttribute("d", line);
  el("spArea").setAttribute("d", `${line} L${pts[pts.length - 1][0].toFixed(1)} 64 L${pts[0][0].toFixed(1)} 64 Z`);
  const last = pts[pts.length - 1];
  el("spDot").setAttribute("cx", last[0].toFixed(1)); el("spDot").setAttribute("cy", last[1].toFixed(1));
  now.textContent = rate.toLocaleString(STRINGS.locale, { maximumFractionDigits: 1 });
}

// -- Reihe 3: System -------------------------------------------------------------

function tile(state, head, value, sub, extra, foot) {
  return `<div class="tile">
    <div class="th"><span class="dot ${state}"></span>${head}</div>
    <div class="tv">${value}</div>
    ${sub ? `<div class="ts">${sub}</div>` : ""}${extra || ""}
    ${foot ? `<div class="q"><span>${foot[0]}</span><span>${foot[1]}</span></div>` : ""}</div>`;
}

function renderSystem() {
  const s = lastStatus || {};
  const dead = s.worker_alive === false;
  const right = el("sysRight");
  if (!info) {
    right.className = "right pending";
    right.textContent = STRINGS.ovPending;
  } else {
    const issues = [];
    if (dead) issues.push(STRINGS.ovWorkerDead);
    if (!info.ffprobe || !info.ffmpeg) issues.push(STRINGS.toolsMissingHint);
    right.className = "right";
    right.textContent = issues.length ? tpl(STRINGS.ovIssuesFound, { n: issues.length })
      : `${STRINGS.ovAllGreen} · ${tpl(STRINGS.ovChecked, { t: fmtTime(new Date(), false) })}`;
  }

  const disk = ov.disks[0];
  const diskPct = disk ? pct(disk.used, disk.total) : 0;
  const tools = info ? [["ffprobe", info.ffprobe], ["ffmpeg", info.ffmpeg]] : [];
  const nTools = tools.filter(([, ok]) => ok).length;
  const inst = (ov.versions || {});
  // Laufzeit-Pakete (#42): installierte Version; weicht sie vom Pin in
  // requirements.txt ab (git pull ohne pip install -r) oder fehlt das
  // Paket, wird der Chip gelb und die Kachel bekommt den Warn-Punkt.
  const pkgs = ov.packages || [];
  const pkgChip = (p) => {
    if (p.installed === null || p.installed === undefined) {
      return `<span class="warn" title="${esc(STRINGS.tilePkgMissing)}"><b>${esc(p.name)}</b> ${STRINGS.tileMissing}</span>`;
    }
    if (!p.ok) {
      return `<span class="warn" title="${esc(tpl(STRINGS.tilePkgPinned, { v: p.pinned }))}"><b>${esc(p.name)}</b> ${esc(p.installed)} ≠ ${esc(p.pinned)}</span>`;
    }
    return `<span><b>${esc(p.name)}</b> ${esc(p.installed)}</span>`;
  };
  const pkgDrift = pkgs.some((p) => !p.ok);
  el("tiles").innerHTML =
    tile(dead ? "dead" : "idle", STRINGS.tileWorker,
         dead ? STRINGS.tileWorkerDead : s.worker_alive ? STRINGS.tileWorkerRunning : STRINGS.tileWorkerNever,
         `${fmtNum(ov.pool_workers)} ${STRINGS.tilePool}`, "",
         [STRINGS.statusQueueTitle, fmtNum((s.queue || []).length)]) +
    (info
      ? tile(nTools === 2 ? "idle" : "warn", STRINGS.tileTools, `${nTools}<small>/ 2</small>`, "",
             `<div class="chips">${tools.map(([n, ok]) => `<span><b>${n}</b> ${ok ? "✓" : STRINGS.tileMissing}</span>`).join("")}</div>`,
             [STRINGS.tileVideoPipeline, nTools === 2 ? STRINGS.tileReady : STRINGS.toolsMissingHint])
      : tile("idle", STRINGS.tileTools, PENDING, "", "", null)) +
    (info
      ? tile("idle", STRINGS.tileDb, big(info.db_bytes + info.wal_bytes),
             tpl(STRINGS.tileSchema, { v: info.schema_version }), "",
             [STRINGS.tileWal, fmtBytes(info.wal_bytes)])
      : tile("idle", STRINGS.tileDb, PENDING, "", "", null)) +
    (disk ? `<div class="tile"><div class="th"><span class="dot ${diskPct > 90 ? "warn" : "idle"}"></span>${STRINGS.tileDisk}</div>
      <div class="donut" style="margin-top:8px">
        <div class="ring"><svg viewBox="0 0 36 36"><circle class="track" cx="18" cy="18" r="15.9"/><circle class="seg ${diskPct > 90 ? "badc" : "okc"}" cx="18" cy="18" r="15.9" stroke-dasharray="${diskPct} 100"/></svg><div class="hero">${diskPct} %<small>${STRINGS.tileUsed}</small></div></div>
        <div class="lg"><i class="${diskPct > 90 ? "badc" : "okc"}"></i><span class="n">${STRINGS.tileUsed}</span><span class="v">${fmtBytes(disk.used)}</span><span class="p"></span><i class="gray"></i><span class="n">${STRINGS.tileFree}</span><span class="v">${fmtBytes(disk.free)}</span><span class="p"></span></div>
      </div>
      <div class="q"><span>${STRINGS.tileDrive} · ${fmtBytes(disk.total)}</span><span>${ov.disks.length > 1 ? `${STRINGS.pathLibrary}: ${fmtBytes(ov.disks[1].free)} ${STRINGS.tileFree}` : ""}</span></div></div>`
      : tile("warn", STRINGS.tileDisk, "–", "", "", null)) +
    (info
      ? tile("idle", STRINGS.tileParsers, `${info.parsers.length}<small>${STRINGS.tileActive}</small>`, "",
             `<div class="chips">${info.parsers.map((p) => `<span><b>${esc(p.name)}</b> v${esc(p.version)}</span>`).join("")}</div>`, null)
      : tile("idle", STRINGS.tileParsers, PENDING, "", "", null)) +
    tile(pkgDrift ? "warn" : "idle", STRINGS.tileInstance, esc(document.getElementById("navInstance").textContent || "fml"),
         `${ov.port ? tpl(STRINGS.tilePort, { p: ov.port }) + " · " : ""}${ov.verwaltung ? STRINGS.tileVerwaltungOn : STRINGS.tileVerwaltungOff}`,
         `<div class="chips"><span><b>fml</b> ${esc(inst.fml)}</span><span><b>Python</b> ${esc(inst.python)}</span><span><b>SQLite</b> ${esc(inst.sqlite)}</span>${pkgs.map(pkgChip).join("")}</div>`
         + (pkgDrift ? `<div class="ts warn">${STRINGS.tilePkgDriftHint}</div>` : ""),
         [STRINGS.tileUptime, fmtElapsed(ov.uptime)]);

  el("paths").innerHTML = `
    <span class="k">${STRINGS.pathDb}</span><span class="p" title="${esc(info ? info.db_path : "")}">${info ? esc(info.db_path) : "…"}</span>
    <span class="k">${STRINGS.pathLogs}</span><span class="p" title="${esc(info?.log_dir || "")}">${info ? esc(info.log_dir || "–") : "…"}</span>
    <span class="k">${STRINGS.pathLibrary}</span><span class="p" title="${esc(ov.library_root || "")}">${ov.library_root ? esc(ov.library_root) : STRINGS.pathLibraryNone}</span>`;
}

// -- Reihe 4: Hinweiskarten ----------------------------------------------------------

function hint(cls, value, text, sub, href, link) {
  const num = value == null ? PENDING : value;   // fertiges HTML: Zahl, „?" oder „…"
  return `<div class="card hint ${cls}"><div class="n">${num}</div><div class="t">${text}<small>${sub}</small></div><a class="link" href="${href}">${link}</a></div>`;
}

function renderHints() {
  const st = stats || {};
  const i = info;   // null = noch nicht geladen → „…"
  const o = i ? i.orphans : null;   // gemerkter Stand (#118): null = noch nie geprüft → „?"
  el("hints").innerHTML =
    hint(!o ? "" : o.count ? "warn" : "good", i ? standValue(i, "orphans", (s) => fmtNum(s.count)) : null, STRINGS.hintOrphans,
         !i ? "…" : o ? tpl(STRINGS.hintOrphansSub, { p: pct(o.count, st.total_locations), stand: standNote(i, "orphans", "") })
                      : standNote(i, "orphans", STRINGS.hintOrphansNever),
         "/admin/maintenance", STRINGS.linkMaintenance) +
    hint(!i ? "" : i.open_issues ? "warn" : "good", i ? fmtNum(i.open_issues) : null, STRINGS.hintIssues,
         !i ? "…" : i.open_issues ? STRINGS.hintIssuesSub : STRINGS.hintIssuesNone, "/admin/issues", STRINGS.linkIssues) +
    hint("", i ? fmtNum(i.blocked_count) : null, STRINGS.hintBlocked, STRINGS.hintBlockedSub, "/admin/issues", STRINGS.linkIssues) +
    `<div class="card hint good" id="hintSources"></div>`;
  if (lastStatus) renderSourceHint(lastStatus);
}

function renderSourceHint(s) {
  const box = el("hintSources");
  if (!box) return;
  const w = s.watchers || [];
  const pending = w.reduce((a, x) => a + (x.pending || 0), 0);
  box.className = `card hint${w.length ? " good" : ""}`;
  box.innerHTML = `<div class="n">${fmtNum(w.length)}</div><div class="t">${STRINGS.hintSources}<small>${
    w.length ? tpl(STRINGS.hintSourcesSub, { names: esc(w.map((x) => x.name || x.path).join(" · ")), n: fmtNum(pending) }) : STRINGS.hintSourcesNone
  }</small></div><a class="link" href="/admin/sources">${STRINGS.linkSources}</a>`;
}

export { isBusy };
