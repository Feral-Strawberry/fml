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
//
// Zwei Abschnitte (ADR 0103 Punkt 12): „Treffer ändern" mit eigenem
// Anwenden-Knopf und „Export", der hier nichts ändert und darum ohne
// Scharfstellen auskommt: je Funktion EIN Kasten (Kopien, Austausch) mit
// Titel, Erklärung, Optionen und rechts seinem Knopf. „Kopien exportieren …"
// tauscht den Dialog gegen ein kleines Formular (Paketname, Ablage,
// umgerechnete Formate); der Lauf selbst ist eine Aufgabe im Hintergrund.

import { STRINGS } from "./strings.js";
import {
  bulkApply, exportExchange, getExportState, getTags, getModels, libraryView,
  planExport, startExport,
} from "./api.js";
import { serverMsg } from "./servermsg.js";
import { emit, on } from "./main.js";
import { registerDialog } from "./overlays.js";
import { chipText } from "./search.js";
import { selectionHashes } from "./curate.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const fmt = (n) => Number(n || 0).toLocaleString(STRINGS.locale);
const tpl = (text, values) => text.replace(/\{(\w+)\}/g, (_, k) => values[k] ?? "");

function fmtBytes(n) {
  if (n >= 1e9) return (n / 1e9).toFixed(1) + " GB";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + " MB";
  return Math.max(1, Math.round(n / 1024)) + " KB";
}

/** Paketname, wie der Server ihn bereinigt (nur für die Zielanzeige; es
 *  gilt, was der Server daraus macht). */
export const packageName = (text) =>
  text.replace(/[<>:"/\\|?*\u0000-\u001f]/g, " ").split(/\s+/).filter(Boolean).join(" ")
    .replace(/^[ .]+|[ .]+$/g, "").slice(0, 80).replace(/[ .]+$/, "");

export function initBulkDialog() {
  let current = null;   // {expression, predicates, liveTerms, total}
  let rating = 0;       // 0 = keine Bewertungs-Aktion
  let exporting = null; // Kopie-Export-Formular: {scope, plan}

  const overlay = document.createElement("div");
  overlay.id = "bulkdlg";
  overlay.className = "pickoverlay";
  overlay.hidden = true;
  document.body.appendChild(overlay);

  let unregister = () => {};   // Dialog-Stapel (ADR 0069)
  function close() {
    unregister();
    overlay.hidden = true;
    current = null;
    exporting = null;
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
        <div class="bulksec">
        <div class="bulksechead">${STRINGS.bulkSecChange}</div>
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
          <label>${STRINGS.bulkDate}</label>
          <input type="text" class="sdname bulkdate" autocomplete="off" placeholder="${STRINGS.bulkDateHint}">
        </div>
        <div class="bulkrow">
          <label>${STRINGS.bulkNote}</label>
          <textarea class="sdname bulknote" rows="2"
                    placeholder="${STRINGS.bulkNoteHint}"></textarea>
        </div>
        <div class="bulkrow bulkblock">
          <label>${STRINGS.bulkReject}</label>
          <span class="bulkctl">
            <label><input type="checkbox" class="bulkreject"> ${STRINGS.bulkRejectLabel}</label>
          </span>
          <span class="sdhint">${STRINGS.bulkRejectHint}</span>
        </div>
        <div class="sdactions">
          <button type="button" class="sdprimary bulkgo">${STRINGS.bulkApply}</button>
        </div>
        </div>
        <div class="bulksec">
        <div class="bulksechead">${STRINGS.bulkSecExport}<span>${STRINGS.bulkSecExportHint}</span></div>
        <div class="bulkcard">
          <div class="bulkcardtext">
            <b>${STRINGS.bulkCopy}</b>
            <span class="sdhint bulkcopymsg">${STRINGS.bulkCopyHint}</span>
          </div>
          <button type="button" class="bulkcopy">${STRINGS.bulkCopyOpen}</button>
        </div>
        ${libraryView() === "audio" ? `
          <div class="bulkcard">
            <div class="bulkcardtext">
              <b>${STRINGS.bulkComments}</b>
              <span class="sdhint bulkexportmsg">${STRINGS.bulkExportHint}</span>
              <span class="bulkctl">
                <label><input type="checkbox" class="bulkexcomments" checked> ${STRINGS.bulkExportComments}</label>
                <label title="${STRINGS.bulkExportFieldsTitle}"><input type="checkbox" class="bulkexfields" checked> ${STRINGS.bulkExportFields}</label>
                <label title="${STRINGS.bulkExportLyricsTitle}"><input type="checkbox" class="bulkexlyrics" checked> ${STRINGS.bulkExportLyrics}</label>
              </span>
            </div>
            <button type="button" class="bulkexport">${STRINGS.bulkExport}</button>
          </div>` : ""}
        </div>
        <div class="bulksec bulkfoot">
          <span class="sderr" hidden></span>
          <div class="sdactions">
            <button type="button" class="bulkcancel">${STRINGS.bulkClose}</button>
          </div>
        </div>
      </div>`;
    fillSuggestions();
    lockExport();
  }

  // Ohne brauchbaren Export-Ordner ist der Knopf gesperrt und die Zeile
  // sagt, warum (ADR 0103 Punkt 3).
  async function lockExport() {
    try {
      const state = await getExportState();
      const btn = overlay.querySelector(".bulkcopy");
      if (!btn || state.available) return;
      btn.disabled = true;
      overlay.querySelector(".bulkcopymsg").textContent = serverMsg(state.reason);
    } catch { /* dann meldet der Klick den Fehler */ }
  }

  // -- Kopie-Export (ADR 0103) ---------------------------------------------------

  async function openExport() {
    const sel = selectionHashes();
    const scope = useSelection() ? { hashes: sel } : { filter: current.expression };
    try {
      const plan = await planExport(scope);
      if (!plan.available) { showError(serverMsg(plan.reason)); return; }
      exporting = { scope, plan };
      renderExport();
    } catch (err) {
      showError(err.message);
    }
  }

  const picked = (group) =>
    [...overlay.querySelectorAll(`input[name="${group}"]`)].find((i) => i.checked)?.value;

  function exportTarget() {
    const name = packageName(overlay.querySelector(".expname").value);
    return exporting.plan.target + (name ? ` ${name}` : "");
  }

  function renderExport() {
    const p = exporting.plan;
    const tight = p.bytes > p.free;
    const radio = (group, value, label, on) =>
      `<label><input type="radio" name="${group}" value="${value}" ${on ? "checked" : ""}> ${label}</label>`;
    overlay.innerHTML = `
      <div class="pickbox savebox bulkbox">
        <div class="pickhead"><b>${esc(STRINGS.exportDlgTitle)}</b>
          <span class="pickpath">${esc(tpl(STRINGS.exportSummary, { n: fmt(p.count), size: fmtBytes(p.bytes) }))}</span></div>
        <div class="bulkrow">
          <label>${STRINGS.exportName}</label>
          <input type="text" class="sdname expname" maxlength="80" autocomplete="off"
                 placeholder="${STRINGS.exportNameHint}">
        </div>
        <div class="bulkrow">
          <label>${STRINGS.exportLayout}</label>
          <span class="bulkscope">
            ${radio("explayout", "flat", STRINGS.exportLayoutFlat, true)}
            ${radio("explayout", "date", STRINGS.exportLayoutDate, false)}
          </span>
        </div>
        ${p.converted ? `
          <div class="bulkrow bulkblock">
            <label>${STRINGS.exportConverted}</label>
            <span class="bulkctl">
              ${radio("expconverted", "png", STRINGS.exportConvertedPng, true)}
              ${radio("expconverted", "original", STRINGS.exportConvertedOriginal, false)}
            </span>
            <span class="sdhint">${esc(tpl(STRINGS.exportConvertedHint, { n: fmt(p.converted) }))}</span>
          </div>` : ""}
        ${p.tagged ? `
          <div class="bulkrow bulkblock">
            <label>${STRINGS.exportTags}</label>
            <span class="bulkctl">
              <label><input type="checkbox" class="exptags" checked> ${STRINGS.exportTagsWrite}</label>
            </span>
            <span class="sdhint">${esc(tpl(STRINGS.exportTagsHint, { n: fmt(p.tagged) }))}</span>
          </div>` : ""}
        <div class="sdhint exptarget"></div>
        <span class="sderr" ${tight ? "" : "hidden"}>${tight
          ? `⚠ ${esc(tpl(STRINGS.exportNoSpace, { size: fmtBytes(p.bytes), free: fmtBytes(p.free) }))}` : ""}</span>
        <div class="sdactions">
          <button type="button" class="sdprimary expgo" ${tight || !p.count ? "disabled" : ""}>${STRINGS.exportGo}</button>
          <button type="button" class="expback">${STRINGS.exportBack}</button>
        </div>
      </div>`;
    paintTarget();
    overlay.querySelector(".expname").focus();
  }

  function paintTarget() {
    overlay.querySelector(".exptarget").textContent =
      `${tpl(STRINGS.exportTarget, { target: exportTarget() })} · ${tpl(STRINGS.exportFree, { free: fmtBytes(exporting.plan.free) })}`;
  }

  async function runExport(btn) {
    btn.disabled = true;
    try {
      const d = await startExport(exporting.scope, {
        name: overlay.querySelector(".expname").value,
        layout: picked("explayout") || "flat",
        converted: picked("expconverted") || "png",
        tags: !!overlay.querySelector(".exptags")?.checked,
      });
      exporting = null;
      overlay.innerHTML = `
        <div class="pickbox savebox bulkbox">
          <div class="pickhead"><b>${esc(STRINGS.exportQueued)}</b></div>
          <div class="bulkline">${esc(tpl(STRINGS.exportQueuedLine, { n: fmt(d.count) }))}</div>
          <div class="bulkline vmono exppath">${esc(d.target)}</div>
          <span class="sdhint">${esc(STRINGS.exportQueuedHint)}</span>
          <div class="sdactions">
            <button type="button" class="sdprimary bulkcancel">${STRINGS.bulkClose}</button>
          </div>
        </div>`;
    } catch (err) {
      btn.disabled = false;
      showError(err.message);
    }
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
    if ("date_set" in d) lines.push(`${STRINGS.bulkResultDate}: ${fmt(d.date_set)}`);
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
    const date = overlay.querySelector(".bulkdate").value.trim();
    if (date) fields.media_date = date;   // ADR 0096
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

  // Austausch exportieren (#228, ADR 0101, ADR 0106): Zeitkommentare,
  // Musik-Angaben und Songtext von Hand. Nur lesend, darum ohne
  // Scharfstellen; die Antwort wird im Browser zur Datei.
  async function exportNow(btn) {
    const sel = selectionHashes();
    const parts = { comments: overlay.querySelector(".bulkexcomments").checked,
                    fields: overlay.querySelector(".bulkexfields").checked,
                    lyrics: overlay.querySelector(".bulkexlyrics").checked };
    if (!parts.comments && !parts.fields && !parts.lyrics) { showError(STRINGS.bulkExportPick); return; }
    btn.disabled = true;
    try {
      const data = await exportExchange(useSelection() ? { hashes: sel } : { filter: current.expression }, parts);
      const count = data.items.reduce((n, it) => n + (it.comments?.length || 0), 0);
      const fields = data.items.reduce((n, it) => n + Object.keys(it.fields || {}).length, 0);
      const lyrics = data.items.filter((it) => it.lyrics).length;
      if (!data.items.length) { showError(STRINGS.bulkExportNone); return; }
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 1)], { type: "application/json" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `${STRINGS.bulkExportFile}-${data.exported_at.slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
      overlay.querySelector(".bulkexportmsg").textContent =
        STRINGS.bulkExportDone.replace("{items}", fmt(data.items.length))
          .replace("{comments}", fmt(count)).replace("{fields}", fmt(fields))
          .replace("{lyrics}", fmt(lyrics));
    } catch (err) {
      showError(err.message);
    } finally {
      btn.disabled = false;
    }
  }

  overlay.addEventListener("click", (e) => {
    const exp = e.target.closest(".bulkexport");
    if (exp) { exportNow(exp); return; }
    if (e.target.closest(".bulkcopy")) { openExport(); return; }
    const go = e.target.closest(".expgo");
    if (go) { runExport(go); return; }
    if (e.target.closest(".expback")) { exporting = null; rating = 0; render(); return; }
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
  overlay.addEventListener("input", () => {
    if (exporting) { if (overlay.querySelector(".exptarget")) paintTarget(); return; }
    disarm();
  });

  on("bulk-dialog-open", (d) => {
    current = d;
    rating = 0;
    exporting = null;
    unregister();
    unregister = registerDialog(overlay, close);
    overlay.hidden = false;
    render();
  });
}
