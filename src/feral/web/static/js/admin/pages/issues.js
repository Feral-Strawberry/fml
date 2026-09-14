// admin/pages/issues.js — Seite „Probleme" (ADR 0074, A3 #107; schließt #66).
//
// Oben die Zusammenfassung mit dem Alle-Knopf (echte Gesamtzahl, ADR 0034),
// darunter je Fehlerart eine Karte: Zähler, die jüngsten Einträge, „alle N
// dieser Art quittieren"; Quittieren meldet die Zahl und lädt die Karten neu.
// Die Sperrliste ist eine eigene Karte und wird GETRENNT geladen: seitenweise
// (100 je Seite), mit Suche über Pfad/Hash/Grund und Zähler vom Server —
// bei rein indexierten Laufwerken sind es tausende Einträge, ein 500er-
// Deckel verschwieg den Rest. Entsperren einzeln oder (bestätigt) alle.

import { STRINGS } from "../../strings.js";
import { getIssues, resolveIssues, getBlocked, unblockHash } from "../../api.js";
import { serverMsg } from "../../servermsg.js";
import { confirmDialog } from "../dialogs.js";
import { setNavCount } from "../nav.js";
import { esc, fmtNum, tpl } from "../util.js";

export const id = "issues";
export const icon = '<svg viewBox="0 0 24 24"><path d="M12 3 2.5 19.5h19z"/><path d="M12 10v4M12 17h.01"/></svg>';
export const title = () => STRINGS.adminIssues;
export const subtitle = () => STRINGS.subIssues;

export const PAGE_SIZE = 100;
let root = null;
let blk = { q: "", offset: 0, total: 0, total_all: 0 };
let searchTimer = 0;
const el = (sel) => root.querySelector("#" + sel);

const KIND_LABELS = () => ({
  failed: STRINGS.issuesKindFailed, warning: STRINGS.issuesKindWarning,
  thumbnail: STRINGS.issuesKindThumbnail, playback: STRINGS.issuesKindPlayback,
});

export function render(target) {
  root = target;
  blk = { q: "", offset: 0, total: 0, total_all: 0 };
  root.innerHTML = `
    <div class="isshead"><span id="issSummary">…</span><span class="vdim" id="issMsg"></span>
      <button type="button" id="adResolveAll" hidden></button></div>
    <div class="row c2" id="issKinds"></div>
    <div class="row"><div class="card" id="blkCard">
      <div class="chead"><span class="mlabel">${STRINGS.blockedTitle}</span><span class="right" id="blkCount"></span></div>
      <div class="vdim dashhint">${STRINGS.blockedHint}</div>
      <div class="blktools">
        <input type="text" id="blkQ" placeholder="${esc(STRINGS.blockedSearch)}">
        <span class="blkmeta" id="blkRange"></span>
        <button type="button" id="blkPrev" disabled>${STRINGS.blockedPrev}</button>
        <button type="button" id="blkNext" disabled>${STRINGS.blockedNext}</button>
        <button type="button" class="danger" id="blkUnblockAll" hidden></button>
      </div>
      <div class="vdim" id="blkMsg"></div>
      <div id="ovBlocked" class="isslist"><span class="vdim">${STRINGS.blockedLoading}</span></div>
    </div></div>`;
  root.addEventListener("click", onClick);
  el("blkQ").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { blk.q = el("blkQ").value.trim(); blk.offset = 0; loadBlocked(); }, 250);
  });
  el("blkQ").addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    clearTimeout(searchTimer);
    blk.q = el("blkQ").value.trim(); blk.offset = 0; loadBlocked();
  });
}

export async function load() {
  // Bewusst NICHT Promise.all: die Problemkarten sollen nicht auf die
  // Sperrliste warten und umgekehrt (#66).
  loadIssues();
  loadBlocked();
}

export function onTaskFinished() { loadIssues(); }
export function unmount() { clearTimeout(searchTimer); }

// -- Probleme je Fehlerart -----------------------------------------------------------

async function loadIssues() {
  if (!root || !root.isConnected) return;
  try {
    const d = await getIssues();
    if (!root.isConnected) return;
    setNavCount("issues", d.total || null);
    renderIssues(d);
  } catch (err) {
    el("issKinds").innerHTML = `<div class="card"><span class="warn">${esc(err.message)}</span></div>`;
  }
}

function renderIssues(ov) {
  const all = el("adResolveAll");
  if (!ov.total) {
    el("issSummary").innerHTML = `<span class="adok">${STRINGS.issuesNone}</span>`;
    all.hidden = true;
    el("issKinds").innerHTML = "";
    return;
  }
  el("issSummary").textContent = tpl(STRINGS.issuesSummary, { n: fmtNum(ov.total), k: ov.kinds.length });
  all.hidden = false;
  all.textContent = tpl(STRINGS.issuesResolveAll, { n: fmtNum(ov.total) });
  const labels = KIND_LABELS();
  el("issKinds").innerHTML = ov.kinds.map((k) => `
    <div class="card issuekind" data-issuekind="${esc(k.kind)}">
      <div class="chead"><span class="mlabel">${esc(labels[k.kind] || k.kind)}</span>
        <span class="badgechip">${esc(k.kind)}</span><span class="right"><b>${fmtNum(k.count)}</b></span></div>
      <div class="isslist">${k.issues.map((i) => `
        <div class="result">
          <div class="rpath">${esc(i.path)}</div>
          <div class="rbadges"><a class="issueresolve" data-issue="${i.id}">${STRINGS.issuesResolveOne}</a></div>
          <div class="rsnippet">${esc(serverMsg(i.message))} · ${esc((i.last_seen_at || "").slice(0, 19))}</div>
        </div>`).join("")}</div>
      <div class="kindfoot">
        <span>${k.count > k.issues.length ? tpl(STRINGS.issuesLatest, { n: fmtNum(k.issues.length), total: fmtNum(k.count) }) : ""}</span>
        <button type="button" data-kind="${esc(k.kind)}">${tpl(STRINGS.issuesResolveKind, { n: fmtNum(k.count) })}</button>
      </div>
    </div>`).join("");
}

async function resolve({ issueId = null, kind = null } = {}) {
  const msg = el("issMsg");
  try {
    const r = await resolveIssues(issueId, kind);
    msg.textContent = tpl(STRINGS.issuesResolved, { n: fmtNum(r.resolved) });
  } catch (err) { msg.innerHTML = `<span class="warn">${esc(err.message)}</span>`; }
  loadIssues();
}

// -- Sperrliste: getrennt, seitenweise, mit Suche ---------------------------------

async function loadBlocked() {
  if (!root || !root.isConnected) return;
  const box = el("ovBlocked");
  try {
    const d = await getBlocked({ q: blk.q, offset: blk.offset, limit: PAGE_SIZE });
    if (!root.isConnected) return;
    blk.total = d.total; blk.total_all = d.total_all ?? d.total;
    // Seite hinter dem Ende (nach Entsperren): eine zurück.
    if (blk.offset >= d.total && blk.offset > 0) {
      blk.offset = Math.max(0, Math.floor((d.total - 1) / PAGE_SIZE) * PAGE_SIZE);
      return loadBlocked();
    }
    renderBlocked(d);
  } catch (err) {
    box.innerHTML = `<span class="warn">${esc(err.message)}</span>`;
  }
}

function renderBlocked(d) {
  const from = d.total ? blk.offset + 1 : 0;
  const to = Math.min(d.total, blk.offset + d.blocked.length);
  el("blkCount").textContent = blk.q
    ? tpl(STRINGS.blockedMatches, { n: fmtNum(d.total), total: fmtNum(blk.total_all) })
    : tpl(STRINGS.blockedTotal, { n: fmtNum(d.total) });
  el("blkRange").textContent = d.total > PAGE_SIZE || blk.offset
    ? tpl(STRINGS.blockedRange, { from: fmtNum(from), to: fmtNum(to) }) : "";
  el("blkPrev").disabled = blk.offset <= 0;
  el("blkNext").disabled = blk.offset + PAGE_SIZE >= d.total;
  const all = el("blkUnblockAll");
  all.hidden = !blk.total_all;
  all.textContent = tpl(STRINGS.blockedUnblockAll, { n: fmtNum(blk.total_all) });
  el("ovBlocked").innerHTML = d.blocked.length
    ? d.blocked.map((b) => `
        <div class="result">
          <div class="rpath vmono" title="${esc(b.file_hash)}">${esc(b.file_hash.slice(0, 20))}…</div>
          <div class="rbadges">
            <a class="issueresolve" data-unblock="${esc(b.file_hash)}">${STRINGS.blockedRemove}</a></div>
          <div class="rsnippet">${esc(serverMsg(b.reason))} · ${esc((b.blocked_at || "").slice(0, 19))}${
            b.last_paths?.length ? `<br>${esc(b.last_paths[0])}${
              b.last_paths.length > 1 ? ` (+${b.last_paths.length - 1})` : ""}` : ""}</div>
        </div>`).join("")
    : `<span class="adok">${blk.q ? STRINGS.blockedNoMatch : STRINGS.blockedNone}</span>`;
}

async function unblock(hash) {
  const msg = el("blkMsg");
  try {
    const r = await unblockHash(hash);
    msg.textContent = tpl(STRINGS.blockedUnblocked, { n: fmtNum(r.removed) });
  } catch (err) { msg.innerHTML = `<span class="warn">${esc(err.message)}</span>`; }
  loadBlocked();
}

// -- Klicks -------------------------------------------------------------------------

async function onClick(e) {
  const one = e.target.closest("[data-issue]");
  if (one) return void resolve({ issueId: one.dataset.issue });
  const kind = e.target.closest("[data-kind]");
  if (kind) return void resolve({ kind: kind.dataset.kind });
  if (e.target.closest("#adResolveAll")) return void resolve();
  const un = e.target.closest("[data-unblock]");
  if (un) return void unblock(un.dataset.unblock);
  if (e.target.closest("#blkPrev")) { blk.offset = Math.max(0, blk.offset - PAGE_SIZE); return void loadBlocked(); }
  if (e.target.closest("#blkNext")) { blk.offset += PAGE_SIZE; return void loadBlocked(); }
  if (e.target.closest("#blkUnblockAll")) {
    const ok = await confirmDialog(tpl(STRINGS.blockedUnblockAllConfirm, { n: fmtNum(blk.total_all) }),
                                   { ok: STRINGS.blockedRemove, danger: true });
    if (ok) unblock(null);
  }
}
