// bulkdialog.js — Sammel-Aktion aufs Suchergebnis (Großbaustelle K, ADR 0040).
//
// Theme-Dialog nach dem Muster des Speicherdialogs (Block S7): Chip-Vorschau
// + Trefferzahl zeigen, WAS getroffen wird; fünf Aktionen (Basisbewertung
// füllt nur Unbewertete, Tag/Notiz hängen an, Modell setzt, Ablehnen läuft
// allein — ADR 0041: Item raus + Sperre, Datei bleibt); Scope-Schalter
// „Auswahl (N) / alle Treffer (M)", wenn eine Multiselect-Auswahl existiert
// (sonst wirkt der Dialog auf alle Treffer). Anwenden ist zweistufig
// („Wirklich anwenden auf …?" statt confirm()) — die Leitplanke gegen den
// versehentlichen 250k-Tag. Nach Erfolg: ehrliche Zusammenfassung aus der
// Server-Antwort + 'bulk-applied' (Grid und Sidebar frischen auf).

import { STRINGS } from "./strings.js";
import { bulkApply, getTags, getModels } from "./api.js";
import { emit, on } from "./main.js";
import { chipText } from "./search.js";
import { selectionHashes } from "./curate.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const fmt = (n) => Number(n || 0).toLocaleString(STRINGS.locale);

export function initBulkDialog() {
  let current = null;   // {expression, predicates, liveTerms, total}
  let rating = 0;       // 0 = keine Bewertungs-Aktion

  const overlay = document.createElement("div");
  overlay.id = "bulkdlg";
  overlay.className = "pickoverlay";
  overlay.hidden = true;
  document.body.appendChild(overlay);

  function close() {
    overlay.hidden = true;
    current = null;
  }

  function showError(message) {
    const el = overlay.querySelector(".sderr");
    el.textContent = `⚠ ${message}`;
    el.hidden = false;
  }

  // Scope der Aktion: Multiselect-Auswahl oder alle Treffer des Zustands.
  const useSelection = () =>
    overlay.querySelector('input[name="bulkscope"][value="sel"]')?.checked;
  const scopeCount = (selCount) =>
    useSelection() ? selCount : current.total;

  function render() {
    const sel = selectionHashes();
    const filtered = current.predicates.length || current.liveTerms.length;
    const matchesLabel = filtered
      ? `${STRINGS.bulkScopeMatches} (${fmt(current.total)})`
      : `${STRINGS.bulkScopeAll} (${fmt(current.total)})`;
    overlay.innerHTML = `
      <div class="pickbox savebox bulkbox">
        <div class="pickhead"><b>${esc(STRINGS.bulkDlgTitle)}</b></div>
        <div class="sdchips">
          ${current.predicates.map((p) => `
            <span class="chip${p.negated ? " neg" : ""}${p.kind === "sort" ? " sort" : ""}">
              ${p.negated ? `<span class="chipneg">${STRINGS.chipNegated}</span>` : ""}
              <span class="chiptext">${esc(chipText(p))}</span>
            </span>`).join("")}
          ${current.liveTerms.map((t) => `
            <span class="chip"><span class="chiptext">${esc(STRINGS.chipKindLabels.text)}: ${esc(t)}</span></span>`).join("")}
          <span class="sdcount">· ${fmt(current.total)} ${STRINGS.saveDlgHits}</span>
        </div>
        ${sel.length ? `
          <div class="bulkscope">
            <label><input type="radio" name="bulkscope" value="sel" checked>
              ${STRINGS.bulkScopeSelection} (${fmt(sel.length)})</label>
            <label><input type="radio" name="bulkscope" value="all">
              ${esc(matchesLabel)}</label>
          </div>` : ""}
        <div class="bulkrow">
          <label>${STRINGS.bulkRating}</label>
          <span class="bulkstars">
            ${[1, 2, 3, 4, 5].map((n) => `
              <button type="button" class="bstar${rating >= n ? " on" : ""}" data-n="${n}">★</button>`).join("")}
          </span>
          <span class="sdhint">${STRINGS.bulkRatingHint}</span>
        </div>
        <div class="bulkrow">
          <label>${STRINGS.bulkTag}</label>
          <input type="text" class="sdname bulktag" list="bulktaglist">
          <datalist id="bulktaglist"></datalist>
        </div>
        <div class="bulkrow">
          <label>${STRINGS.bulkModel}</label>
          <input type="text" class="sdname bulkmodel" list="bulkmodellist"
                 placeholder="${STRINGS.bulkModelHint}">
          <datalist id="bulkmodellist"></datalist>
        </div>
        <div class="bulkrow">
          <label>${STRINGS.bulkNote}</label>
          <textarea class="sdname bulknote" rows="2"
                    placeholder="${STRINGS.bulkNoteHint}"></textarea>
        </div>
        <div class="bulkrow">
          <label>${STRINGS.bulkReject}</label>
          <label class="bulkrejectlbl"><input type="checkbox" class="bulkreject">
            ${STRINGS.bulkRejectLabel}</label>
          <span class="sdhint">${STRINGS.bulkRejectHint}</span>
        </div>
        <span class="sderr" hidden></span>
        <div class="sdactions">
          <button type="button" class="sdprimary bulkgo">${STRINGS.bulkApply}</button>
          <button type="button" class="bulkcancel">${STRINGS.saveDlgCancel}</button>
        </div>
      </div>`;
    fillSuggestions();
  }

  // Vokabular-Vorschläge (Tags/Modelle) — lazy, Fehler sind egal.
  async function fillSuggestions() {
    try {
      const [t, m] = await Promise.all([getTags(), getModels()]);
      const tl = overlay.querySelector("#bulktaglist");
      if (tl) tl.innerHTML = (t.tags || [])
        .map((x) => `<option value="${esc(x.name)}">`).join("");
      const ml = overlay.querySelector("#bulkmodellist");
      if (ml) ml.innerHTML = (m.models || [])
        .map((x) => `<option value="${esc(x.model)}">`).join("");
    } catch { /* Vorschläge sind Komfort, kein Muss */ }
  }

  function renderResult(d) {
    const lines = [];
    if ("rejected" in d) lines.push(`${STRINGS.bulkResultRejected}: ${fmt(d.rejected)}`);
    if ("rating_set" in d) lines.push(`${STRINGS.bulkResultRating}: ${fmt(d.rating_set)}`);
    if ("tagged" in d) lines.push(`${STRINGS.bulkResultTagged}: ${fmt(d.tagged)}`
      + (d.matched > d.tagged ? ` (${fmt(d.matched - d.tagged)} ${STRINGS.bulkResultSkipped})` : ""));
    if ("model_set" in d) lines.push(`${STRINGS.bulkResultModel}: ${fmt(d.model_set)}`);
    if ("noted" in d) lines.push(`${STRINGS.bulkResultNoted}: ${fmt(d.noted)}`);
    overlay.innerHTML = `
      <div class="pickbox savebox bulkbox">
        <div class="pickhead"><b>${esc(STRINGS.bulkDone)}</b>
          <span class="pickpath">${fmt(d.matched)} ${STRINGS.saveDlgHits}</span></div>
        ${lines.map((l) => `<div class="bulkline">${esc(l)}</div>`).join("")}
        <div class="sdactions">
          <button type="button" class="sdprimary bulkcancel">${STRINGS.bulkClose}</button>
        </div>
      </div>`;
  }

  async function apply() {
    const fields = {};
    if (rating) fields.rating = rating;
    const tag = overlay.querySelector(".bulktag").value.trim();
    if (tag) fields.add_tag = tag;
    const model = overlay.querySelector(".bulkmodel").value.trim();
    if (model) fields.model = model;
    const note = overlay.querySelector(".bulknote").value.trim();
    if (note) fields.note = note;
    // Ablehnen (ADR 0041) läuft allein — die Kombination wäre nie gewollt.
    if (overlay.querySelector(".bulkreject").checked) {
      if (Object.keys(fields).length) {
        showError(STRINGS.bulkRejectExclusive);
        return;
      }
      fields.reject = true;
    }
    if (!Object.keys(fields).length) {
      showError(STRINGS.bulkNoAction);
      return;
    }
    const sel = selectionHashes();
    // Zweistufig: erster Klick fragt mit der ehrlichen Zahl, zweiter wendet an.
    const go = overlay.querySelector(".bulkgo");
    if (!go.dataset.armed) {
      go.dataset.armed = "1";
      go.textContent = `${STRINGS.bulkApplyArm} ${fmt(scopeCount(sel.length))}?`;
      return;
    }
    go.disabled = true;
    try {
      const scope = useSelection()
        ? { hashes: sel }
        : { filter: current.expression };
      const d = await bulkApply(scope, fields);
      emit("bulk-applied", d);
      renderResult(d);
    } catch (err) {
      go.disabled = false;
      delete go.dataset.armed;
      go.textContent = STRINGS.bulkApply;
      showError(err.message);
    }
  }

  overlay.addEventListener("click", (e) => {
    const star = e.target.closest(".bstar");
    if (star) {
      const n = parseInt(star.dataset.n, 10);
      rating = rating === n ? 0 : n;   // erneuter Klick nimmt die Aktion raus
      overlay.querySelectorAll(".bstar").forEach((b) =>
        b.classList.toggle("on", parseInt(b.dataset.n, 10) <= rating));
      disarm();
      return;
    }
    if (e.target.closest(".bulkgo")) { apply(); return; }
    if (e.target.closest(".bulkcancel")) { close(); return; }
    if (e.target === overlay) close();
  });
  // Jede Eingabe-Änderung entschärft den scharf gestellten Anwenden-Knopf —
  // die Bestätigungszahl soll nie zu einer ANDEREN Aktion/Menge gehören.
  function disarm() {
    const go = overlay.querySelector(".bulkgo");
    if (go && go.dataset.armed) {
      delete go.dataset.armed;
      go.textContent = STRINGS.bulkApply;
    }
  }
  overlay.addEventListener("input", disarm);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !overlay.hidden) close();
  });

  on("bulk-dialog-open", (d) => {
    current = d;
    rating = 0;
    overlay.hidden = false;
    render();
  });
}
