// admin.js — Ein-Seiten-Admin-Dashboard (ADR 0029, Feinschliff ADR 0034).
//
// Fünf Regionen auf EINER scrollbaren Seite: Überblick (Bestand-Kennzahlen +
// Aktivität in EINEM Kasten) · Quellen & Import · Wartung · Probleme (nur
// Zusammenfassung; das Aufräumen läuft im Overlay) · Konfiguration. Kein
// Sektions-Umschalter mehr — die Kopf-Navigation springt nur zu Ankern. Ein
// Poller (/api/status) speist den Topbar-Indikator und die Aktivitäts-Leiste
// im Überblick und meldet den Übergang laufend→fertig als 'engine-idle'
// (Galerie/Zähler/Sidebar laden neu).
//
// Quellen: Watch-Quellen-Modell (ADR 0030) — mehrere überwachte Ordner, je Modus
// kopieren/verschieben, alle über dieselbe Import-Pipeline. Statt einem Hotfolder.

import { STRINGS, LANG, LANGUAGES, setLang } from "./strings.js";
import {
  getStatus, browse, startImport,
  getWatch, startWatchSource, stopWatchSource, saveWatchSources,
  getAdminInfo, getIssues, resolveIssues, getBlocked, unblockHash, pruneOrphans, clearThumbCache,
  getImportRulesPreview, applyImportRules,
  getMoveout, startMoveout,
  startReparse, startRescan, startIntegrityCheck, startVacuum, startThumbWarm,
  startBackfillDates, startReindex, recomputeRankings, getRankings, deleteRanking,
  getConfig, saveConfig, getRoots,
} from "./api.js";
import { emit, on } from "./main.js";
import { serverMsg } from "./servermsg.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function fmtBytes(n) {
  if (n >= 1e9) return (n / 1e9).toFixed(2) + " GB";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + " MB";
  return Math.round(n / 1024) + " KB";
}

// Kopf-Navigation: Anker-Sprünge (keine getrennten Views mehr). Aktivität
// lebt seit ADR 0034 IM Überblick (eine Live-Zahlen-Leiste, ein Poller-Ziel).
const NAV = [
  ["dashOverview", () => STRINGS.adminOverview],
  ["dashSources", () => STRINGS.adminSources],
  ["dashMaint", () => STRINGS.adminMaintenance],
  ["dashIssues", () => STRINGS.adminIssues],
  ["dashConfig", () => STRINGS.adminConfig],
];

// Alt-Sektions-IDs (Quickmenu/Aktivität) → neue Anker.
const SECTION_ALIAS = {
  status: "dashOverview", maint: "dashMaint", scan: "dashSources",
  issues: "dashIssues", config: "dashConfig",
  activity: "dashOverview", dashActivity: "dashOverview",
};

// Wartung — nach Funktionsbereich gruppiert (Feral Strawberry, ADR 0029). Ein Eintrag:
// [id, Titel, Untertext, Aktion]. Aktion "prune"/"thumbs" laufen synchron und
// melden eine Zahl; alle anderen reihen eine Engine-Aufgabe ein.
const MAINT_GROUPS = [
  [() => STRINGS.maintGroupRaw, [
    ["rescan", () => STRINGS.maintRescan, () => STRINGS.maintRescanSub, startRescan],
    ["prune", () => STRINGS.maintPrune, () => STRINGS.maintPruneSub, "prune"],
    ["moveout", () => STRINGS.maintMoveout, () => STRINGS.maintMoveoutSub, "moveout"],
    // Import-Regeln rückwirkend (ADR 0046): Vorschau + zweistufiges Ablehnen.
    ["importrules", () => STRINGS.maintImportRules, () => STRINGS.maintImportRulesSub, "importrules"],
  ]],
  [() => STRINGS.maintGroupThumbs, [
    ["thumbwarm", () => STRINGS.maintThumbWarm, () => STRINGS.maintThumbWarmSub, startThumbWarm],
    ["thumbs", () => STRINGS.maintThumbs, () => STRINGS.maintThumbsSub, "thumbs"],
  ]],
  [() => STRINGS.maintGroupDb, [
    ["integrity", () => STRINGS.maintIntegrity, () => STRINGS.maintIntegritySub, startIntegrityCheck],
    ["vacuum", () => STRINGS.maintVacuum, () => STRINGS.maintVacuumSub, startVacuum],
  ]],
  [() => STRINGS.maintGroupReeval, [
    ["reparse", () => STRINGS.maintReparse, () => STRINGS.maintReparseSub, startReparse],
    ["backfill", () => STRINGS.maintBackfill, () => STRINGS.maintBackfillSub, startBackfillDates],
    ["reindex", () => STRINGS.maintReindex, () => STRINGS.maintReindexSub, startReindex],
    // Rescan-Prinzip fürs Ranking-Modul (ADR 0045): Elo-Replay übers
    // Duell-Log — deterministisch, jederzeit, auch bei inaktivem Schalter.
    ["rankscores", () => STRINGS.maintRankScores, () => STRINGS.maintRankScoresSub, recomputeRankings],
  ]],
];

export function initAdmin() {
  const root = document.getElementById("admin");
  const activity = document.getElementById("activity");
  root.innerHTML = `
    <div class="adhead">
      <button type="button" id="adBack">← ${STRINGS.adminBack}</button>
      <img class="mascot" src="/static/img/feral-strawberry.png" alt="">
      <div class="adtitle">
        <div>Feral Media Library</div>
        <div class="mlabel adaccent">${STRINGS.adminConsole}</div>
      </div>
      <nav class="adjump">${STRINGS.adminManage}:
        ${NAV.map(([id, n]) => `<a data-jump="${id}">${n()}</a>`).join('<span class="adjumpsep">·</span>')}
      </nav>
    </div>
    <div class="addash">
      <section id="dashOverview" class="dashsec dashstrip">
        <div class="stripgrid">
          <div class="stripcol">
            <div class="mlabel">${STRINGS.overviewLibrary}</div>
            <div id="adInfo" class="statstrip"></div>
            <div id="adInfoMore" class="stripinfo"></div>
          </div>
          <div class="stripcol stripact">
            <div class="mlabel">${STRINGS.adminActivity}</div>
            <div id="adStatus" class="adstatus"></div>
          </div>
        </div>
      </section>

      <section id="dashSources" class="dashsec">
        <div class="dashtitle">${STRINGS.adminSources}</div>
        <div class="mlabel">${STRINGS.watchTitle}</div>
        <div class="vdim dashhint">${STRINGS.watchHint}</div>
        <div id="adWatch" class="watchlist"></div>
        <div class="mlabel" style="margin-top:12px;">${STRINGS.importFormTitle}</div>
        <div class="vdim dashhint">${STRINGS.importFormHint}</div>
        <div class="srcform">
          <input type="text" id="adImpPath" placeholder="${STRINGS.scanPathPlaceholder}">
          <button type="button" id="adImpPick" title="${STRINGS.cfgPick}">📁</button>
          <select id="adImpModus" title="${STRINGS.watchModusTitle}">
            <option value="kopieren" selected>${STRINGS.cfgModusKopieren}</option>
            <option value="verschieben">${STRINGS.cfgModusVerschieben}</option>
            <option value="katalogisieren">${STRINGS.cfgModusKatalog}</option>
          </select>
          <select id="adImpFreq" title="${STRINGS.freqTitle}">
            <option value="einmal" selected>${STRINGS.freqOnce}</option>
            <option value="watch">${STRINGS.freqWatch}</option>
          </select>
          <label class="wleer" id="adImpLeerWrap" title="${esc(STRINGS.watchLeerTitle)}" hidden>
            <input type="checkbox" id="adImpLeer"> ${STRINGS.watchLeer}</label>
          <button type="button" class="accentbtn" id="adImpGo">${STRINGS.importGo}</button>
        </div>
        <div id="adImpMsg" class="admsg"></div>
      </section>

      <div class="dashcol" id="dashOps">
        <section id="dashMaint" class="dashsec">
          <div class="dashtitle">${STRINGS.adminMaintenance}</div>
          <div id="adMaint" class="maintgroups"></div>
          <div id="adMaintMsg" class="admsg"></div>
          <div class="mlabel" style="margin-top:14px;">${STRINGS.adminArenas}</div>
          <div class="vdim dashhint">${STRINGS.adminArenasHint}</div>
          <div id="adArenas" class="watchlist"></div>
        </section>

        <section id="dashIssues" class="dashsec">
          <div class="dashtitle">${STRINGS.adminIssues}</div>
          <div id="adIssueSummary" class="issueline"></div>
        </section>
      </div>

      <section id="dashConfig" class="dashsec">
        <div class="dashtitle">${STRINGS.adminConfig}</div>
        <div id="adConfig"></div>
      </section>
    </div>`;

  const el = (id) => root.querySelector("#" + id);
  const dash = root.querySelector(".addash");
  let lastRunning = false;
  let lastFinished = null;
  let watchTick = 0;

  // -- Öffnen / Schließen / Springen --------------------------------------------

  function jumpTo(id) {
    const target = SECTION_ALIAS[id] || id;
    root.querySelector("#" + target)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  root.querySelector(".adjump").addEventListener("click", (e) => {
    const a = e.target.closest("[data-jump]");
    if (a) jumpTo(a.dataset.jump);
  });

  function openAdmin(section) {
    root.hidden = false;
    loadInfo(); loadWatch(); loadIssues(); loadConfig(); loadArenas();
    if (section) requestAnimationFrame(() => jumpTo(section));
    else dash.scrollTop = 0;
  }
  function closeAdmin() { root.hidden = true; }
  el("adBack").addEventListener("click", closeAdmin);
  on("admin-open", (d) => openAdmin(d && d.section));
  activity.addEventListener("click", () => openAdmin("dashActivity"));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !root.hidden && document.getElementById("loupe").hidden) closeAdmin();
  });

  // -- Überblick ----------------------------------------------------------------

  async function loadInfo() {
    try {
      const a = await getAdminInfo();
      const st = a.stats || {};
      const tools = `ffprobe ${a.ffprobe ? "✅" : "❌"} · ffmpeg ${a.ffmpeg ? "✅" : "❌"}`
        + (!a.ffprobe || !a.ffmpeg ? ` — ${STRINGS.toolsMissingHint}` : "");
      const parsers = a.parsers.map((p) => `${p.name} v${p.version}`).join(", ");
      const pct = st.total_items ? Math.round((st.items_interpreted / st.total_items) * 100) : 0;
      // Schmale Kennzahlen-Leiste (bescheiden — Stats sind Orientierung,
      // nicht der Star des Dashboards; Feral Strawberry, 2026-07-09).
      const stat = (n, l, warn) => `<span class="stat${warn ? " statwarn" : ""}">
        <b class="statv">${n}</b><span class="statk">${l}</span></span>`;
      el("adInfo").innerHTML =
        stat(st.total_items ?? "—", STRINGS.statItems) +
        // Library-GB vs. indiziert gesamt (ADR 0041, I2) — nur mit
        // konfigurierter Media Library sinnvoll.
        (st.library_configured
          ? stat(`${fmtBytes(st.library_bytes)} / ${fmtBytes(st.total_bytes)}`,
                 STRINGS.statLibrary)
          : "") +
        stat(st.items_with_metadata ?? "—", STRINGS.statWithMeta) +
        stat(`${st.items_interpreted ?? 0} (${pct}%)`, STRINGS.statInterpretedItems) +
        stat(a.thumb_count, `${STRINGS.statThumbs} · ${fmtBytes(a.thumb_bytes)}`) +
        stat(fmtBytes(a.db_bytes + a.wal_bytes), `${STRINGS.statDb} v${a.schema_version}`) +
        stat(a.orphan_locations, STRINGS.statOrphans, a.orphan_locations > 0) +
        stat(a.open_issues, STRINGS.statIssues, a.open_issues > 0);
      el("adInfoMore").innerHTML = `
        <span>${tools}</span>
        <span class="vdim">· ${STRINGS.statParsers}: ${esc(parsers)}</span>
        <span class="vdim stripdb" title="${esc(a.db_path)}">· DB: ${esc(a.db_path)}</span>`;
    } catch (err) {
      el("adInfo").innerHTML = `<span class="warn">${esc(err.message)}</span>`;
    }
  }

  // -- Überwachte Ordner (ADR 0030; Inline-Verwaltung nach Feral Strawberrys Feedback
  //    2026-07-09: EIN Konzept, direkt hier pflegen — kein Umweg über die
  //    Konfiguration, keine konkurrierende „Feste Scan-Orte"-Liste daneben) --

  let watchSources = [];   // zuletzt geladene Liste (inkl. quiet/poll — Round-Trip)

  function renderWatch(d) {
    const box = el("adWatch");
    watchSources = d.sources;
    // Übersichtsmodus (ADR 0041, I4): dateischreibende Modi sind gesperrt —
    // im Import-Formular UND auf den Watch-Karten. katalogisieren bleibt frei.
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
    if (!d.sources.length) {
      box.innerHTML = `<div class="vdim">${STRINGS.watchNone}</div>`;
    } else {
      box.innerHTML = d.sources.map((s, i) => {
        const srcLocked = locked && s.modus !== "katalogisieren";
        const state = srcLocked
          ? `<span class="wdot"></span><span class="warn">${STRINGS.modeLocked}</span>`
          : s.watching
          ? `<span class="wdot on"></span>${STRINGS.watchOn} · ${s.pending} ${STRINGS.watchPending} · ${s.enqueued_total} ${STRINGS.watchImported}`
          : `<span class="wdot"></span>${s.exists ? STRINGS.watchOff : STRINGS.scanMissing}`;
        const btn = s.watching
          ? `<button type="button" class="watchtoggle" data-stop="${esc(s.path)}">${STRINGS.watchStop}</button>`
          : `<button type="button" class="watchtoggle accentbtn" data-start="${esc(s.path)}" ${s.exists && !srcLocked ? "" : "disabled"}${srcLocked ? ` title="${esc(STRINGS.modeLocked)}"` : ""}>${STRINGS.watchStart}</button>`;
        return `<div class="watchcard">
          <div class="watchmain">
            <div class="watchname">${esc(s.name)}</div>
            <div class="watchpath vmono" title="${esc(s.path)}">${esc(s.path)}</div>
            <div class="watchstate">${state}</div>
          </div>
          <div class="watchctl">
            <select class="wmodus" data-idx="${i}" title="${STRINGS.watchModusTitle}">
              <option value="kopieren" ${s.modus === "kopieren" ? "selected" : ""}${lockOpt("kopieren")}>${STRINGS.cfgModusKopieren}</option>
              <option value="verschieben" ${s.modus === "verschieben" ? "selected" : ""}${lockOpt("verschieben")}>${STRINGS.cfgModusVerschieben}</option>
              <option value="katalogisieren" ${s.modus === "katalogisieren" ? "selected" : ""}>${STRINGS.cfgModusKatalog}</option>
            </select>
            ${s.modus === "verschieben" ? `<label class="wleer" title="${esc(STRINGS.watchLeerTitle)}">
              <input type="checkbox" class="wleerchk" data-idx="${i}" ${s.leere_ordner_entfernen ? "checked" : ""}>
              ${STRINGS.watchLeer}</label>` : ""}
            ${btn}
            <button type="button" class="wremove" data-idx="${i}" title="${STRINGS.watchRemoveTitle}">✕</button>
          </div>
        </div>`;
      }).join("");
    }
    if (!d.has_library) {
      box.insertAdjacentHTML("afterbegin", `<div class="warn watchwarn">${STRINGS.watchNoLibrary}</div>`);
    }
  }

  async function loadWatch() {
    const box = el("adWatch");
    // Nicht unter den Händen wegrendern: der Poller frischt die Live-Zähler
    // auf — aber nicht, während in der Liste gerade ein Select/Feld offen ist
    // (Buttons sind egal, die tragen keinen halbfertigen Zustand).
    const active = document.activeElement;
    if (box.contains(active) && (active.tagName === "SELECT" || active.tagName === "INPUT")) return;
    try {
      renderWatch(await getWatch());
    } catch (err) { box.innerHTML = `<span class="warn">${esc(err.message)}</span>`; }
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

  // EIN Import-Formular (Feral Strawberry, 2026-07-09): Pfad + Modus + Häufigkeit —
  // „einmal jetzt" reiht den Einmal-Import ein, „dauerhaft beobachten" legt
  // einen Watchordner an. Gleiche Pipeline, eine Entscheidung an einem Ort;
  // verschieben immer mit Sicherheitsabfrage.
  const wirePick = (btnId, inputId) =>
    el(btnId).addEventListener("click", async () => {
      const input = el(inputId);
      const chosen = await pickFolder(input.value.trim() || null);
      if (chosen) input.value = chosen;
    });
  wirePick("adImpPick", "adImpPath");

  // Leerordner-Schalter (ADR 0033) nur zeigen, wo er wirkt: verschieben.
  el("adImpModus").addEventListener("change", () => {
    el("adImpLeerWrap").hidden = el("adImpModus").value !== "verschieben";
  });

  el("adImpGo").addEventListener("click", async () => {
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
  });
  el("adImpPath").addEventListener("keydown", (e) => {
    if (e.key === "Enter") el("adImpGo").click();
  });
  el("adWatch").addEventListener("change", (e) => {
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
    sel.blur();   // Fokus freigeben, sonst blockiert der Render-Schutz das Update
    saveWatch(watchSources.map((s) => s === src ? { ...s, modus: sel.value } : s));
  });
  el("adWatch").addEventListener("click", async (e) => {
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
  });

  // -- Wartung (kleine Buttons, nach Funktionsbereich) --------------------------

  const MAINT_FN = {};
  el("adMaint").innerHTML = MAINT_GROUPS.map(([group, items]) => `
    <div class="maintgroup">
      <div class="mlabel">${group()}</div>
      <div class="maintbtns">
        ${items.map(([id, t, s, fn]) => {
          MAINT_FN[id] = fn;
          return `<button type="button" class="maintbtn" data-maint="${id}" title="${esc(s())}">${t()}</button>`;
        }).join("")}
      </div>
    </div>`).join("");
  el("adMaint").addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-maint]");
    if (!btn) return;
    const msg = el("adMaintMsg");
    const action = MAINT_FN[btn.dataset.maint];
    try {
      if (action === "prune") {
        // ADR 0033: erst fragen WO — ein globaler Lauf räumt auch Fundorte
        // auf gerade ausgehängten Platten/NAS weg („weg“ und „offline“ sehen
        // für den Dateisystem-Check gleich aus).
        msg.innerHTML = `${STRINGS.pruneWhere}
          <button type="button" id="pruneAll">${STRINGS.pruneEverywhere}</button>
          <button type="button" id="pruneUnder">${STRINGS.pruneUnder}</button>
          <div class="vdim">${STRINGS.pruneOfflineHint}</div>`;
        const doPrune = async (under) => {
          try {
            const r = await pruneOrphans(under);
            msg.textContent = `${r.pruned} ${STRINGS.maintPruned}`;
            loadInfo();
          } catch (err) { msg.textContent = err.message; }
        };
        msg.querySelector("#pruneAll").addEventListener("click", () => doPrune(null));
        msg.querySelector("#pruneUnder").addEventListener("click", async () => {
          const chosen = await pickFolder(null);
          if (chosen) doPrune(chosen);
        });
      } else if (action === "moveout") {
        openMoveoutDialog();
      } else if (action === "importrules") {
        // ADR 0046: erst die ehrliche Vorschau (Zahlen je Grund), dann
        // bestätigen — Ablehnen ist umkehrbar (Sperrliste), Dateien bleiben.
        const p = await getImportRulesPreview();
        if (!p.active) { msg.textContent = STRINGS.importRulesNone; return; }
        if (!p.total) { msg.textContent = STRINGS.importRulesNoHits; return; }
        const parts = [];
        if (p.counts.min_kante) parts.push(`${p.counts.min_kante} ${STRINGS.importRulesTooSmall}`);
        if (p.counts.max_kante) parts.push(`${p.counts.max_kante} ${STRINGS.importRulesTooBig}`);
        if (p.counts.formate) parts.push(`${p.counts.formate} ${STRINGS.importRulesFormat}`);
        msg.innerHTML = `<b>${p.total.toLocaleString(STRINGS.locale)}</b> ${STRINGS.importRulesHits}
          (${parts.join(" · ")})
          <button type="button" id="irApply">${STRINGS.importRulesApply}</button>
          <div class="vdim">${STRINGS.importRulesHint}</div>`;
        msg.querySelector("#irApply").addEventListener("click", async () => {
          try {
            await applyImportRules();
            msg.textContent = STRINGS.maintQueued;
          } catch (err) { msg.textContent = err.message; }
        });
      } else if (action === "thumbs") {
        const r = await clearThumbCache();
        msg.textContent = `${r.deleted} ${STRINGS.maintThumbsCleared}`;
        loadInfo();
      } else {
        await action();
        msg.textContent = STRINGS.maintQueued;
      }
    } catch (err) { msg.textContent = err.message; }
  });

  // -- Ranking-Arenen (R3, ADR 0045): Löschen lebt HIER, nicht in der Arena —
  // das ✕ dort wurde als „Overlay schließen" gelesen und war zu gefährlich.
  // Löschen bleibt zweistufig und entfernt die Arena MIT Duellen und Scores.
  // Anlegen/Umbenennen bleibt in der Sidebar/Arena (dort ist es Alltag).

  async function loadArenas() {
    const box = el("adArenas");
    try {
      const d = await getRankings();
      box.innerHTML = d.rankings.length ? d.rankings.map((r) => `
        <div class="watchcard">
          <div class="watchmain">
            <div class="watchname">${esc(r.name)}</div>
            <div class="watchpath">${esc(r.expression || STRINGS.allMedia)} ·
              ${r.duels} ${STRINGS.rankingDuels}${r.population !== null
                ? ` · ${r.population.toLocaleString(STRINGS.locale)} ${STRINGS.rankingPopulation}` : ""}</div>
          </div>
          <div class="watchctl">
            <button type="button" class="wremove arenadel" data-id="${r.id}">${STRINGS.adminArenaDelete}</button>
          </div>
        </div>`).join("")
        : `<div class="vdim">${STRINGS.adminArenasEmpty}</div>`;
    } catch (err) { box.innerHTML = `<div class="vdim">${esc(err.message)}</div>`; }
  }

  el("adArenas").addEventListener("click", async (e) => {
    const btn = e.target.closest(".arenadel");
    if (!btn) return;
    if (!btn.dataset.armed) {
      btn.dataset.armed = "1";
      btn.textContent = STRINGS.adminArenaDeleteArm;
      setTimeout(() => {
        if (btn.isConnected) { delete btn.dataset.armed; btn.textContent = STRINGS.adminArenaDelete; }
      }, 2500);
      return;
    }
    try { await deleteRanking(btn.dataset.id); } catch (err) { alert(err.message); }
    loadArenas();
    emit("rankings-changed", {});   // Sidebar-Gruppe nachziehen
  });

  // (Der frühere fest eingebaute Ordner-Browser ist raus: er duplizierte die
  // Navigation des 📁-Pickers. Durchklicken läuft überall über pickFolder —
  // inkl. Dateizahl je Ordner, die vorher nur der Browser zeigte.)

  // -- Aktivität (permanent sichtbare Fortschrittsanzeige) ----------------------

  function renderStatus(s) {
    const r = s.report;
    const total = r.scanned_files || 0;
    const pct = total ? Math.min(100, Math.round((r.media_files + r.skipped_unknown) / total * 100)) : 0;
    let head;
    if (s.running) head = `<span class="adok">▶ ${esc(serverMsg(s.label) || STRINGS.activityRunning)}</span> ${s.current_file ? "· " + esc(serverMsg(s.current_file)) : ""}`;
    else if (s.queue_pending) head = `<span class="warn">⏳ ${s.queue_pending} ${STRINGS.statusQueued}</span>`;
    else if (s.last_finished) head = `<span class="vdim">${STRINGS.statusLast} ${esc(serverMsg(s.last_finished))}</span>`;
    else head = `<span class="vdim">${STRINGS.statusReady}</span>`;
    if (s.last_result) head += ` <span class="adok">· ${esc(serverMsg(s.last_result))}</span>`;
    // Zähler in derselben Wert/Label-Optik wie die Bestand-Kennzahlen links
    // (ADR 0034: Stats + Aktivität sind EINE Live-Zahlen-Leiste).
    const cell = (n, l) => `<span class="stat"><b class="statv">${n || 0}</b><span class="statk">${l}</span></span>`;
    el("adStatus").innerHTML = `
      <div>${head}</div>
      <div class="adbar"><div style="width:${s.running ? pct : 0}%"></div></div>
      <div class="statstrip">
        ${cell(r.scanned_files, STRINGS.statScanned)}${cell(r.media_files, STRINGS.statMedia)}
        ${cell(r.new_items, STRINGS.statNew)}${cell(r.known_items, STRINGS.statKnown)}
        ${cell(r.with_metadata, STRINGS.statWithMeta)}${cell(r.interpreted, STRINGS.statInterpretedItems)}
        ${cell(r.pending_extractor, STRINGS.statPendingExtractor)}${cell(r.skipped_unknown, STRINGS.statSkipped)}
        ${cell(r.ausgefiltert, STRINGS.statFiltered)}${cell(r.failed, STRINGS.statFailed)}
      </div>`;
  }

  // -- Probleme (ADR 0034: einzeilige Zusammenfassung im Dashboard, das
  //    Aufräumen läuft in einem Overlay — dutzende Einträge blähen die
  //    Dashboard-Spalte nicht mehr auf) -----------------------------------------

  async function loadIssues() {
    const box = el("adIssueSummary");
    try {
      const [d, b] = await Promise.all([getIssues(), getBlocked()]);
      const parts = [
        d.total
          ? `<span class="warn">⚠ ${d.total} ${STRINGS.issuesOpenCount}</span>`
          : `<span class="adok">${STRINGS.issuesNone}</span>`,
      ];
      if (b.blocked.length) {
        parts.push(`<span class="vdim">${b.blocked.length} ${STRINGS.blockedCount}</span>`);
      }
      const btn = (d.total || b.blocked.length)
        ? `<button type="button" id="adIssuesShow">${STRINGS.issuesShow}</button>` : "";
      box.innerHTML = `${parts.join('<span class="adjumpsep">·</span>')}${btn}`;
      box.querySelector("#adIssuesShow")?.addEventListener("click", openIssuesOverlay);
    } catch (err) { box.innerHTML = `<span class="warn">${esc(err.message)}</span>`; }
  }

  // Block N: gruppiert nach Fehlerart mit ehrlichen Zahlen — die flache
  // Liste zeigte bei >2000 Fehlern still nur 200, „Alle quittieren" traf
  // aber wirklich alle. Je Art: Zähler + Sammel-Quittieren + die jüngsten
  // Einträge; der Alle-Knopf nennt die echte Gesamtzahl.
  function renderIssueList(box, ov) {
    if (!ov.total) { box.innerHTML = `<span class="adok">${STRINGS.issuesNone}</span>`; return; }
    box.innerHTML = ov.kinds.map((k) => `
      <div class="issuekind">
        <div class="rbadges" style="margin-bottom:4px;">
          <span class="badgechip">${esc(k.kind)}</span> <b>${k.count}</b>
          <a class="issueresolve" data-kind="${esc(k.kind)}">${STRINGS.issuesResolveKind.replace("{n}", k.count)}</a>
        </div>
        ${k.issues.map((i) => `
          <div class="result">
            <div class="rpath">${esc(i.path)}</div>
            <div class="rbadges"><a class="issueresolve" data-issue="${i.id}">${STRINGS.issuesResolve}</a></div>
            <div class="rsnippet">${esc(serverMsg(i.message))} · ${esc((i.last_seen_at || "").slice(0, 19))}</div>
          </div>`).join("")}
        ${k.count > k.issues.length
          ? `<div class="rsnippet vdim">${STRINGS.issuesMoreOfKind.replace("{n}", k.count - k.issues.length)}</div>`
          : ""}
      </div>`).join("") +
      `<button type="button" id="adResolveAll" style="margin-top:8px;">${STRINGS.issuesResolveAll.replace("{n}", ov.total)}</button>`;
  }

  function renderBlockedList(box, blocked) {
    box.innerHTML = blocked.length
      ? blocked.map((b) => `
          <div class="result">
            <div class="rpath vmono" title="${esc(b.file_hash)}">${esc(b.file_hash.slice(0, 20))}…</div>
            <div class="rbadges">
              <a class="issueresolve" data-unblock="${esc(b.file_hash)}">${STRINGS.blockedRemove}</a></div>
            <div class="rsnippet">${esc(serverMsg(b.reason))} · ${esc((b.blocked_at || "").slice(0, 19))}${
              b.last_paths?.length ? `<br>${esc(b.last_paths[0])}${
                b.last_paths.length > 1 ? ` (+${b.last_paths.length - 1})` : ""}` : ""}</div>
          </div>`).join("")
      : `<span class="adok">${STRINGS.blockedNone}</span>`;
  }

  function openIssuesOverlay() {
    document.querySelector(".pickoverlay")?.remove();   // nie zwei übereinander
    const overlay = document.createElement("div");
    overlay.className = "pickoverlay";
    overlay.innerHTML = `
      <div class="pickbox issuebox">
        <div class="pickhead"><span class="mlabel">${STRINGS.issuesOverlayTitle}</span></div>
        <div class="isslist">
          <div class="mlabel">${STRINGS.adminIssues}</div>
          <div id="ovIssues"></div>
          <div class="mlabel" style="margin-top:16px;">${STRINGS.blockedTitle}</div>
          <div class="vdim dashhint">${STRINGS.blockedHint}</div>
          <div id="ovBlocked"></div>
        </div>
        <div class="adactions" style="margin-bottom:0;">
          <button type="button" id="ovClose">${STRINGS.issuesClose}</button></div>
      </div>`;
    document.body.appendChild(overlay);
    const close = () => {
      document.removeEventListener("keydown", onKey, true);
      overlay.remove();
      loadIssues(); loadInfo();   // Zusammenfassung + Kennzahlen nachziehen
    };
    const onKey = (e) => {
      if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); close(); }
    };
    document.addEventListener("keydown", onKey, true);

    async function refresh() {
      try {
        const [d, b] = await Promise.all([getIssues(), getBlocked()]);
        renderIssueList(overlay.querySelector("#ovIssues"), d);
        renderBlockedList(overlay.querySelector("#ovBlocked"), b.blocked);
      } catch (err) {
        overlay.querySelector("#ovIssues").innerHTML =
          `<span class="warn">${esc(err.message)}</span>`;
      }
    }
    overlay.addEventListener("click", async (e) => {
      if (e.target === overlay || e.target.closest("#ovClose")) return close();
      const one = e.target.closest("[data-issue]");
      const kind = e.target.closest("[data-kind]");
      const all = e.target.closest("#adResolveAll");
      const unblock = e.target.closest("[data-unblock]");
      if (!one && !kind && !all && !unblock) return;
      try {
        if (unblock) await unblockHash(unblock.dataset.unblock);
        else if (kind) await resolveIssues(null, kind.dataset.kind);
        else await resolveIssues(one ? one.dataset.issue : null);
        refresh();
      } catch (err) { alert(err.message); }
    });
    refresh();
  }

  // -- Rausverschiebe-Dialog (I3, ADR 0041) --------------------------------------
  // Pauschalweg: alle abgelehnten Dateien unter library.root in einen
  // Zielordner bewegen — der einzige Datei-Bewegungsweg neben dem Import.
  // Vorschau mit ehrlichen Zahlen (gedeckelte Beispiel-Liste, Lehre aus dem
  // Probleme-Overlay); Anwenden zweistufig wie im Sammel-Dialog.

  function openMoveoutDialog() {
    document.querySelector(".pickoverlay")?.remove();   // nie zwei übereinander
    const overlay = document.createElement("div");
    overlay.className = "pickoverlay";
    overlay.innerHTML = `
      <div class="pickbox issuebox">
        <div class="pickhead"><span class="mlabel">${STRINGS.moTitle}</span></div>
        <div class="isslist">
          <div class="vdim dashhint">${STRINGS.moHint}</div>
          <div id="moInfo"></div>
          <div class="mlabel" style="margin-top:12px;">${STRINGS.moTarget}</div>
          <div class="srcform">
            <input type="text" id="moTarget" placeholder="${STRINGS.scanPathPlaceholder}">
            <button type="button" id="moPick" title="${STRINGS.cfgPick}">📁</button>
          </div>
          <div id="moMsg" class="vdim" style="margin-top:8px;"></div>
        </div>
        <div class="adactions" style="margin-bottom:0;">
          <button type="button" class="accentbtn" id="moGo" disabled>${STRINGS.moGo}</button>
          <button type="button" id="moClose">${STRINGS.issuesClose}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    const goBtn = overlay.querySelector("#moGo");
    const msg = overlay.querySelector("#moMsg");
    let movable = 0;
    let armed = false;   // zweistufig: erster Klick fragt, zweiter reiht ein
    const close = () => {
      document.removeEventListener("keydown", onKey, true);
      overlay.remove();
    };
    const onKey = (e) => {
      // Esc schließt NUR den Dialog (Capture, wie der Ablehnen-Dialog).
      if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); close(); }
    };
    document.addEventListener("keydown", onKey, true);
    const disarm = () => { armed = false; goBtn.textContent = STRINGS.moGo; };

    (async () => {
      const box = overlay.querySelector("#moInfo");
      try {
        const d = await getMoveout();
        if (d.locked) {
          // Übersichtsmodus (I4): Rausverschieben ist dateischreibend.
          box.innerHTML = `<span class="warn">${STRINGS.modeLocked}</span>`;
          return;
        }
        if (!d.available) {
          box.innerHTML = `<span class="warn">${STRINGS.moNoLibrary}</span>`;
          return;
        }
        if (!d.movable) {
          box.innerHTML = `<span class="adok">${STRINGS.moNone}</span>`;
          if (d.missing) box.innerHTML +=
            `<div class="vdim">${STRINGS.moMissing.replace("{n}", d.missing)}</div>`;
          return;
        }
        movable = d.movable;
        const lines = [
          `<b>${STRINGS.moCount.replace("{n}", d.movable).replace("{gb}", fmtBytes(d.bytes))}</b>`,
          d.missing ? `<span class="vdim">${STRINGS.moMissing.replace("{n}", d.missing)}</span>` : "",
          `<div class="stripinfo" style="margin-top:6px;">${
            d.sample.map((p) => `<div class="rpath vmono">${esc(p)}</div>`).join("")}${
            d.movable > d.sample.length
              ? `<div class="vdim">${STRINGS.moMore.replace("{n}", d.movable - d.sample.length)}</div>` : ""}</div>`,
        ];
        box.innerHTML = lines.filter(Boolean).join("");
        goBtn.disabled = false;
      } catch (err) { box.innerHTML = `<span class="warn">${esc(err.message)}</span>`; }
    })();

    overlay.querySelector("#moTarget").addEventListener("input", disarm);
    overlay.addEventListener("click", async (e) => {
      if (e.target === overlay || e.target.closest("#moClose")) return close();
      if (e.target.closest("#moPick")) {
        const chosen = await pickFolder(null);   // schließt dieses Overlay!
        openMoveoutDialogWithTarget(chosen);
        return;
      }
      if (!e.target.closest("#moGo")) return;
      const target = overlay.querySelector("#moTarget").value.trim();
      if (!target) { msg.textContent = STRINGS.moNoTarget; return; }
      if (!armed) {
        armed = true;
        goBtn.textContent = STRINGS.moConfirm.replace("{n}", movable);
        return;
      }
      try {
        await startMoveout(target);
        el("adMaintMsg").textContent = STRINGS.moQueued;
        close();
      } catch (err) { disarm(); msg.innerHTML = `<span class="warn">${esc(err.message)}</span>`; }
    });

    // pickFolder räumt fremde .pickoverlay ab — nach der Ordnerwahl den
    // Dialog mit vorbelegtem Ziel neu öffnen, statt Zustand zu verrenken.
    function openMoveoutDialogWithTarget(chosen) {
      const previous = overlay.querySelector("#moTarget").value;
      document.removeEventListener("keydown", onKey, true);
      openMoveoutDialog();
      const input = document.querySelector("#moTarget");
      if (input) input.value = chosen || previous;
    }
  }

  // -- Ordner-Auswahl (Overlay über /api/roots + /api/browse) -------------------

  function pickFolder(startPath) {
    document.querySelector(".pickoverlay")?.remove();   // nie zwei übereinander
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.className = "pickoverlay";
      overlay.innerHTML = `
        <div class="pickbox">
          <div class="pickhead"><span class="mlabel">${STRINGS.pickTitle}</span>
            <span class="pickpath vmono" id="pickPath"></span></div>
          <div class="addirs" id="pickDirs"></div>
          <div class="adactions">
            <button type="button" class="accentbtn" id="pickOk">${STRINGS.pickChoose}</button>
            <button type="button" id="pickCancel">${STRINGS.pickCancel}</button>
          </div>
        </div>`;
      document.body.appendChild(overlay);
      let current = null;
      const close = (value) => {
        document.removeEventListener("keydown", onKey, true);
        overlay.remove();
        resolve(value);
      };
      const onKey = (e) => {
        if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); close(null); }
      };
      document.addEventListener("keydown", onKey, true);

      async function show(path) {
        try {
          if (!path) {
            const r = await getRoots();
            overlay.querySelector("#pickPath").textContent = "";
            // roots sind {name, path}-Objekte — vorher wurde das Objekt selbst
            // gerendert („[object Object]", der Picker wirkte kaputt).
            overlay.querySelector("#pickDirs").innerHTML = r.roots.map((d) =>
              `<div class="addir" data-path="${esc(d.path)}">${esc(d.name)}</div>`).join("");
            current = null;
            return;
          }
          const d = await browse(path);
          current = d.path;
          // Pfad + Dateizahl (kam früher nur im eingebauten Browser vor).
          overlay.querySelector("#pickPath").textContent =
            `${d.path} · ${d.file_count} ${STRINGS.scanFilesHere}`;
          overlay.querySelector("#pickDirs").innerHTML =
            (d.parent ? `<div class="addir" data-path="${esc(d.parent)}">↑ ..</div>` : "") +
            d.subdirs.map((sub) =>
              `<div class="addir" data-path="${esc(sub.path)}">${esc(sub.name)}</div>`).join("");
        } catch (err) { alert(err.message); }
      }
      overlay.addEventListener("click", (e) => {
        if (e.target === overlay) return close(null);
        const dir = e.target.closest(".addir");
        if (dir) return void show(dir.dataset.path);
        if (e.target.closest("#pickOk")) return close(current);
        if (e.target.closest("#pickCancel")) return close(null);
      });
      show(startPath || null);
    });
  }

  // -- Konfiguration ------------------------------------------------------------
  // (Ohne Ordner-Listen: Watchordner leben in „Quellen & Import"; die früheren
  // Browser-Lesezeichen sind ersatzlos gestrichen — Feral Strawberry, 2026-07-09.)

  async function loadConfig() {
    const box = el("adConfig");
    try {
      const c = await getConfig();
      if (!c.editable) { box.innerHTML = `<span class="vdim">${STRINGS.cfgNotEditable}</span>`; return; }
      box.innerHTML = `
        <div class="adinfoline vdim">${STRINGS.cfgFile} <code>${esc(c.path)}</code>${c.exists ? "" : ` <span class="warn">${STRINGS.cfgNew}</span>`}</div>

        <div class="cfgcard">
          <div class="mlabel">${STRINGS.cfgLibrary}</div>
          <div class="cfgpathline">
            <input type="text" id="cfgLibRoot" value="${esc(c.library_root || "")}" placeholder="${STRINGS.cfgLibraryPlaceholder}">
            <button type="button" id="cfgLibPick" title="${STRINGS.cfgPick}">📁</button>
          </div>
          <div class="cfghint">${STRINGS.cfgLibraryHint}</div>
          <label class="cfgline cfgcheck">
            <input type="checkbox" id="cfgVerwaltung" ${c.verwaltung ? "checked" : ""}>
            <span>${STRINGS.cfgVerwaltung} <span class="cfghint">${STRINGS.cfgVerwaltungHint}</span></span></label>
          <label class="cfgline">${STRINGS.cfgMinDate}
            <input type="text" id="cfgMinDate" value="${esc(c.import_min_date || "2015-01-01")}" style="width:110px;">
            <span class="cfghint">${STRINGS.cfgMinDateHint}</span></label>
          <label class="cfgline">${STRINGS.cfgMinKante}
            <input type="number" id="cfgMinKante" value="${c.import_rules?.min_kante || 0}" min="0" style="width:90px;"> px
            <span class="cfghint">${STRINGS.cfgMinKanteHint}</span></label>
          <label class="cfgline">${STRINGS.cfgMaxKante}
            <input type="number" id="cfgMaxKante" value="${c.import_rules?.max_kante || 0}" min="0" style="width:90px;"> px
            <span class="cfghint">${STRINGS.cfgMaxKanteHint}</span></label>
          <label class="cfgline">${STRINGS.cfgFormate}
            <input type="text" id="cfgFormate" value="${esc((c.import_rules?.formate || []).join(", "))}" placeholder="psd, arw" style="width:170px;">
            <span class="cfghint">${STRINGS.cfgFormateHint}</span></label>
        </div>

        <div class="cfgcard">
          <div class="mlabel">${STRINGS.cfgPerf}</div>
          <label class="cfgline">${STRINGS.cfgThumbSize}
            <input type="number" id="cfgThumb" value="${c.thumbnail_size}" min="16" max="2048" style="width:90px;"> px
            <span class="cfghint">${STRINGS.cfgThumbHint}</span></label>
          <label class="cfgline">${STRINGS.cfgWorkers}
            <input type="number" id="cfgWorkers" value="${c.thumbnail_workers ?? 0}" min="0" max="128" style="width:80px;">
            <span class="cfghint">${STRINGS.cfgWorkersHint}</span></label>
          <label class="cfgline cfgcheck">
            <input type="checkbox" id="cfgVollgas" ${c.thumbnail_low_priority === false ? "checked" : ""}>
            <span>${STRINGS.cfgVollgas}</span></label>
        </div>

        <div class="cfgcard">
          <div class="mlabel">${STRINGS.cfgUi}</div>
          <label class="cfgline">${STRINGS.cfgLang}
            <select id="cfgLang">
              ${LANGUAGES.map((l) => `<option value="${l.code}" ${l.code === LANG ? "selected" : ""}>${l.label}</option>`).join("")}
            </select>
            <span class="cfghint">${STRINGS.cfgLangHint}</span></label>
          <label class="cfgline cfgcheck">
            <input type="checkbox" id="cfgShowDupes" ${c.show_dupes === false ? "" : "checked"}>
            <span>${STRINGS.cfgShowDupes} <span class="cfghint">${STRINGS.cfgShowDupesHint}</span></span></label>
          <label class="cfgline">${STRINGS.cfgModelSort}
            <select id="cfgModelSort">
              <option value="zuletzt" ${c.model_sort === "zuletzt" ? "selected" : ""}>${STRINGS.cfgModelSortLast}</option>
              <option value="alphabet" ${c.model_sort === "alphabet" ? "selected" : ""}>${STRINGS.cfgModelSortAlpha}</option>
              <option value="anzahl" ${c.model_sort === "anzahl" ? "selected" : ""}>${STRINGS.cfgModelSortCount}</option>
            </select></label>
        </div>

        <div class="cfgcard">
          <div class="mlabel">${STRINGS.cfgModule}</div>
          <label class="cfgline cfgcheck">
            <input type="checkbox" id="cfgRankings" ${c.rankings_enabled ? "checked" : ""}>
            <span>${STRINGS.cfgRankings} <span class="cfghint">${STRINGS.cfgRankingsHint}</span></span></label>
        </div>

        <div class="cfgcard">
          <div class="mlabel">${STRINGS.cfgInstanz}</div>
          <label class="cfgline">${STRINGS.cfgInstName}
            <input type="text" id="cfgInstName" value="${esc(c.instanz_name || "")}" placeholder="${STRINGS.cfgInstNamePlaceholder}" style="width:200px;">
            <span class="cfghint">${STRINGS.cfgInstNameHint}</span></label>
          <label class="cfgline cfgcheck">
            <input type="checkbox" id="cfgAccentOn" ${c.akzentfarbe ? "checked" : ""}>
            <span>${STRINGS.cfgAccent}</span>
            <input type="color" id="cfgAccent" value="${esc(c.akzentfarbe || "#ff3b48")}"></label>
          <label class="cfgline">${STRINGS.cfgPort}
            <input type="number" id="cfgPort" value="${c.web_port ?? ""}" min="1" max="65535" placeholder="8765" style="width:90px;">
            <span class="cfghint">${STRINGS.cfgPortHint}</span></label>
        </div>

        <div class="adactions">
          <button type="button" class="accentbtn" id="cfgSave">${STRINGS.cfgSave}</button>
          <span class="vdim">${STRINGS.cfgBakHint}</span></div>
        <div id="cfgMsg" class="admsg"></div>`;

      // Farbwahl aktiviert die eigene Akzentfarbe gleich mit (ein Klick weniger).
      box.querySelector("#cfgAccent").addEventListener("input", () => {
        box.querySelector("#cfgAccentOn").checked = true;
      });

      // Sprache ist Browser-Sache (localStorage, ADR 0054) — NICHT Teil von
      // saveConfig: wirkt sofort, der Wechsel lädt die Seite neu.
      box.querySelector("#cfgLang").addEventListener("change", (e) => {
        setLang(e.target.value);
      });

      box.querySelector("#cfgLibPick").addEventListener("click", async () => {
        const input = box.querySelector("#cfgLibRoot");
        const chosen = await pickFolder(input.value.trim() || null);
        if (chosen) input.value = chosen;
      });

      box.querySelector("#cfgSave").addEventListener("click", async () => {
        try {
          // Watch-Liste NICHT mitschicken: die lebt in „Quellen & Import"
          // (Inline-Verwaltung, /api/watch/save) — hier bleibt sie unberührt.
          const r = await saveConfig({
            thumbnail_size: parseInt(box.querySelector("#cfgThumb").value, 10) || 320,
            library_root: box.querySelector("#cfgLibRoot").value,
            verwaltung: box.querySelector("#cfgVerwaltung").checked,
            import_min_date: box.querySelector("#cfgMinDate").value,
            // Import-Regeln (ADR 0046): 0/leer = Regel aus.
            import_min_kante: parseInt(box.querySelector("#cfgMinKante").value, 10) || 0,
            import_max_kante: parseInt(box.querySelector("#cfgMaxKante").value, 10) || 0,
            import_formate_ausschliessen: box.querySelector("#cfgFormate").value
              .split(",").map((s) => s.trim().toLowerCase()).filter(Boolean),
            thumbnail_workers: parseInt(box.querySelector("#cfgWorkers").value, 10) || 0,
            thumbnail_low_priority: !box.querySelector("#cfgVollgas").checked,
            show_dupes: box.querySelector("#cfgShowDupes").checked,
            model_sort_order: box.querySelector("#cfgModelSort").value,
            // Instanz (I5): 0/leer = Eintrag raus, zurück zum Standard.
            web_port: parseInt(box.querySelector("#cfgPort").value, 10) || 0,
            instanz_name: box.querySelector("#cfgInstName").value,
            akzentfarbe: box.querySelector("#cfgAccentOn").checked
              ? box.querySelector("#cfgAccent").value : "",
            // Modul-Schalter Rankings (ADR 0045) — wirkt sofort: die
            // Sidebar zieht die Gruppe über 'model-changed' → loadCounts nach.
            rankings_enabled: box.querySelector("#cfgRankings").checked,
          });
          box.querySelector("#cfgMsg").innerHTML = `<span class="adok">${STRINGS.cfgSaved}</span> <span class="vdim">${esc(serverMsg(r.hint))}</span>`;
          loadWatch();
          emit("model-changed", {});   // Sidebar (Modell-Sortierung/Dubletten) auffrischen
          emit("config-saved", {});    // Topbar-Badge Übersichtsmodus nachziehen (I4)
        } catch (err) {
          box.querySelector("#cfgMsg").innerHTML = `<span class="warn">${esc(err.message)}</span>`;
        }
      });
    } catch (err) { box.innerHTML = `<span class="warn">${esc(err.message)}</span>`; }
  }

  // -- Poller: Topbar-Indikator + Live-Aktivität + engine-idle ------------------

  async function poll() {
    let s;
    try { s = await getStatus(); } catch { return; }
    const watchingAny = (s.watchers || []).length > 0;
    const busy = s.running || s.queue_pending > 0;
    activity.hidden = !busy && !watchingAny;
    activity.innerHTML = busy
      ? `<span class="actdot"></span>${esc(s.label || STRINGS.activityRunning)}`
      : (watchingAny ? `<span class="actdot idle"></span>${STRINGS.activityWatching}` : "");
    if (!root.hidden) {
      renderStatus(s);
      if (++watchTick % 4 === 0) loadWatch();   // Live-Zähler der Quellen nachziehen
    }
    // Galerie/Sidebar nur bei echter Flanke laufend→idle neu laden.
    const idleEdge = lastRunning && !busy;
    if (idleEdge) emit("engine-idle", {});
    // Dashboard-Panels zusätzlich immer, wenn eine Aufgabe fertig geworden
    // ist — auch wenn ihre Flanke zwischen zwei Polls verschwand (schneller
    // Ein-Datei-Import). Nur bei SICHTBAREM Dashboard: /api/admin/info macht
    // Orphan-/Cache-Scans, das soll im Hintergrund nicht mitlaufen (250k!);
    // openAdmin() lädt beim Öffnen ohnehin alles frisch.
    if (!root.hidden && (idleEdge || s.last_finished !== lastFinished)) {
      loadInfo(); loadWatch(); loadIssues();
    }
    lastRunning = busy;
    lastFinished = s.last_finished;
  }
  setInterval(poll, 700);
  poll();
}
