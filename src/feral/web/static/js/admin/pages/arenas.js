// admin/pages/arenas.js — Seite „Ranking-Arenen" (ADR 0074 Punkt 7, A3 #107).
//
// Tabelle: Name, Ausdruck, Population (Items, die der Ausdruck trifft),
// Duelle, Items mit Score, angelegt am, Löschen mit Bestätigungsdialog
// (Löschen lebt HIER, ADR 0045: das ✕ in der Arena wurde als „Overlay
// schließen" gelesen). Darunter „Ranking-Scores neu berechnen" (Elo-Replay,
// Rescan-Prinzip) mit Inline-Ergebnis. Anlegen läuft NUR in der Galerie
// (🏆 in der Chip-Leiste, ADR 0081) — hier gibt es keinen Anlege-Knopf
// (#133: er warf nackt auf „Alle Medien"). „Bearbeiten" je Zeile springt
// in den Bearbeiten-Modus dieses Rankings in der Galerie (?ranking=ID,
// rankings.js), derselbe Weg wie ✎ in der Ranking-Ansicht.

import { STRINGS } from "../../strings.js";
import { getRankings, deleteRanking, recomputeRankings } from "../../api.js";
import { confirmDialog } from "../dialogs.js";
import { setNavCount } from "../nav.js";
import { esc, fmtNum, fmtTime, tpl } from "../util.js";

export const id = "arenas";
export const icon = '<svg viewBox="0 0 24 24"><path d="M8 4h8v5a4 4 0 0 1-8 0z"/><path d="M8 6H5a3 3 0 0 0 3 5M16 6h3a3 3 0 0 1-3 5"/><path d="M12 13v4M9 21h6M10 17h4"/></svg>';
export const title = () => STRINGS.adminArenas;
export const subtitle = () => STRINGS.subArenas;

let root = null;
const el = (sel) => root.querySelector("#" + sel);

export function render(target) {
  root = target;
  root.innerHTML = `
    <div class="row"><div class="card">
      <div class="chead"><span class="mlabel">${STRINGS.adminArenas}</span><span class="right" id="arCount"></span></div>
      <div class="vdim dashhint">${STRINGS.adminArenasHint}</div>
      <div class="vdim" id="arMsg"></div>
      <div id="adArenas" style="overflow-x:auto"></div>
    </div></div>
    <div class="row"><div class="card">
      <div class="actions">
        <div class="action" data-action="rankscores">
          <div class="ti">${STRINGS.maintRankScores}</div>
          <button type="button" class="go accent" id="arRecompute">${STRINGS.mtRun}</button>
          <div class="ex">${STRINGS.maintRankScoresSub}</div>
          <div class="st" id="arRecomputeSt"></div>
        </div>
      </div>
    </div></div>`;
  root.addEventListener("click", onClick);
}

export async function load() {
  const box = el("adArenas");
  try {
    const d = await getRankings();
    if (!root.isConnected) return;
    setNavCount("arenas", d.rankings.length || null);
    el("arCount").textContent = tpl(STRINGS.arenaCount, { n: fmtNum(d.rankings.length) });
    box.innerHTML = d.rankings.length ? `
      <table class="atable">
        <thead><tr>
          <th>${STRINGS.arenaColName}</th><th>${STRINGS.arenaColExpr}</th>
          <th class="num">${STRINGS.arenaColPopulation}</th><th class="num">${STRINGS.arenaColDuels}</th>
          <th class="num">${STRINGS.arenaColRated}</th><th>${STRINGS.arenaColCreated}</th><th></th>
        </tr></thead>
        <tbody>${d.rankings.map((r) => `
          <tr data-arena="${r.id}">
            <td><b>${esc(r.name)}</b></td>
            <td class="expr" title="${esc(r.expression || "")}">${esc(r.expression || STRINGS.allMedia)}</td>
            <td class="num">${r.population == null ? "…" : fmtNum(r.population)}</td>
            <td class="num">${fmtNum(r.duels)}</td>
            <td class="num">${fmtNum(r.rated)}</td>
            <td class="vmono">${esc((r.created_at || "").slice(0, 10))}</td>
            <td class="arenaacts"><a class="arenaedit" href="/?ranking=${r.id}" title="${esc(STRINGS.arenaEditTitle)}">✎ ${esc(STRINGS.arenaEditBtn)}</a>
              <button type="button" class="arenadel" data-id="${r.id}" data-name="${esc(r.name)}" data-duels="${r.duels}">${STRINGS.arenaDeleteBtn}</button></td>
          </tr>`).join("")}</tbody>
      </table>`
      : `<div class="vdim">${STRINGS.adminArenasEmpty}</div>`;
  } catch (err) { box.innerHTML = `<div class="warn">${esc(err.message)}</div>`; }
}

async function onClick(e) {
  const del = e.target.closest(".arenadel");
  if (del) {
    const ok = await confirmDialog(
      tpl(STRINGS.arenaDeleteConfirm, { name: del.dataset.name, duels: fmtNum(del.dataset.duels) }),
      { ok: STRINGS.arenaDeleteBtn, danger: true });
    if (!ok) return;
    try {
      await deleteRanking(del.dataset.id);
      el("arMsg").textContent = tpl(STRINGS.arenaDeleted, { name: del.dataset.name });
    } catch (err) { el("arMsg").innerHTML = `<span class="warn">${esc(err.message)}</span>`; }
    return void load();
  }
  if (e.target.closest("#arRecompute")) {
    const btn = el("arRecompute"), st = el("arRecomputeSt");
    btn.disabled = true;
    st.className = "st running"; st.textContent = STRINGS.mtStRunning;
    try {
      const r = await recomputeRankings();
      st.className = "st done";
      st.textContent = `✓ ${tpl(STRINGS.rankScoresDone, { n: fmtNum(r.replayed) })} · ${fmtTime(new Date(), false)}`;
    } catch (err) { st.className = "st failed"; st.textContent = err.message; }
    btn.disabled = false;
  }
}
