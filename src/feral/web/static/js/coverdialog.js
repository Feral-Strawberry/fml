// coverdialog.js — Cover eines Songs wählen (Audio A8, #165, ADR 0090).
//
// Ein Bild der Bibliothek wird Cover: fml speichert nur den Verweis, die
// Audiodatei bleibt unangetastet. Die Suche startet mit `typ: bild` und den
// Tags des Songs (für ihn erzeugtes Artwork liegt so oben) und lässt sich
// wie die Chip-Leiste verfeinern — Chips ↔ Text NUR über /api/filter/parse|
// build (ADR 0035), ein eigener Zustand nur für diesen Dialog, nicht der
// Suchzustand der Galerie. Öffnen über 'cover-pick' {hash, name, tags,
// cover}; nach dem Setzen 'cover-changed' {hash, manual}.

import { STRINGS } from "./strings.js";
import { buildFilter, getCoverCandidates, loadThumb, parseFilter, setCover } from "./api.js";
import { emit, on } from "./main.js";
import { registerDialog } from "./overlays.js";
import { chipText, inputExpression, liveInput } from "./search.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const PAGE = 120;

/** Startausdruck: nur Bilder, bei getaggten Songs ODER-verknüpft deren Tags. */
export function startExpression(tags) {
  const quoted = (tags || []).map((t) => `"${String(t).replace(/"/g, "")}"`);
  return quoted.length ? `typ: bild tag: ${quoted.join(" | ")}` : "typ: bild";
}

export function initCoverDialog() {
  const overlay = document.createElement("div");
  overlay.id = "coverdlg";
  overlay.className = "pickoverlay";
  overlay.hidden = true;
  document.body.appendChild(overlay);

  let song = null;       // {hash, name, cover}
  let preds = [];        // Chips des Dialogs (parse-Form)
  let expr = "";         // Ausdruck der Chips (kanonisch)
  let live = "";         // getippte, noch nicht festgemachte Begriffe (wie die Suche)
  let liveTimer = null;
  let pick = null;       // gewählter Bild-Hash
  let loaded = 0;
  let total = 0;
  let seq = 0;
  let unregister = () => {};

  function close() {
    unregister();
    overlay.hidden = true;
    overlay.innerHTML = "";
    song = null;
    seq++;
  }

  function frame() {
    overlay.innerHTML = `
      <div class="pickbox coverbox" role="dialog" tabindex="-1">
        <div class="pickhead"><b>${esc(STRINGS.coverDlgTitle.replace("{name}", song.name))}</b></div>
        <div class="sdhint">${esc(STRINGS.coverDlgHint)}</div>
        <div class="cvsearch"><span class="cvchips"></span>
          <input type="text" class="cvinput" placeholder="${esc(STRINGS.coverDlgRefine)}">
          <span class="sdcount"></span></div>
        <span class="sderr" hidden></span>
        <div class="cvgrid"></div>
        <div class="sdactions">
          <span class="sdhint">${esc(STRINGS.coverDlgFoot)}</span>
          <button type="button" class="cvcancel">${esc(STRINGS.coverDlgCancel)}</button>
          <button type="button" class="accentbtn cvok" disabled>${esc(STRINGS.coverDlgSet)}</button>
        </div>
      </div>`;
  }

  function showError(message) {
    const el = overlay.querySelector(".sderr");
    if (!el) return;
    el.textContent = message ? `⚠ ${message}` : "";
    el.hidden = !message;
  }

  function renderChips() {
    overlay.querySelector(".cvchips").innerHTML = preds.map((p, i) => `
      <span class="chip${p.negated ? " neg" : ""}">
        ${p.negated ? `<span class="chipneg">${STRINGS.chipNegated}</span>` : ""}
        <span class="chiptext">${esc(chipText(p))}</span>
        <button type="button" class="chipx" data-i="${i}" title="${esc(STRINGS.coverDlgChipRemove)}">✕</button>
      </span>`).join("");
  }

  function tileHtml(it) {
    return `<div class="tile cvtile${it.file_hash === pick ? " selected" : ""}" data-hash="${it.file_hash}"
      title="${esc(it.name || "")}"><span class="ph">${it.width ? `${it.width}×${it.height}` : esc(it.container || "")}</span><img alt=""></div>`;
  }

  async function loadMore(reset) {
    const mySeq = reset ? ++seq : seq;
    if (!reset && loaded >= total) return;
    let page;
    const filter = [expr, live].filter(Boolean).join(" ");
    try { page = await getCoverCandidates({ filter, offset: reset ? 0 : loaded, limit: PAGE }); }
    catch (err) { if (mySeq === seq) showError(err.message); return; }
    if (mySeq !== seq || !song) return;
    const grid = overlay.querySelector(".cvgrid");
    if (reset) { grid.innerHTML = ""; grid.scrollTop = 0; loaded = 0; total = page.total; }
    grid.insertAdjacentHTML("beforeend", page.items.map(tileHtml).join(""));
    for (const it of page.items) {
      const img = grid.querySelector(`.cvtile[data-hash="${it.file_hash}"] img`);
      if (img) loadThumb(img, it.file_hash);
    }
    loaded += page.items.length;
    overlay.querySelector(".sdcount").textContent =
      `${total.toLocaleString(STRINGS.locale)} ${STRINGS.coverDlgHits}`;
    if (!total) grid.innerHTML = `<div class="cvempty">${esc(STRINGS.coverDlgEmpty)}</div>`;
  }

  // Ausdruck → Chips (kanonisch) → Treffer; ungültige Eingabe bleibt im Feld.
  async function applyExpression(text) {
    let parsed;
    try { parsed = await parseFilter(text); }
    catch (err) { showError(err.message); return false; }
    showError("");
    preds = parsed.predicates;
    expr = parsed.expression;
    renderChips();
    await loadMore(true);
    return true;
  }

  async function removeChip(i) {
    const rest = preds.filter((_, k) => k !== i);
    let built;
    try { built = await buildFilter(rest); }
    catch (err) { showError(err.message); return; }
    await applyExpression(built.expression);
  }

  function choose(hash) {
    pick = hash;
    overlay.querySelectorAll(".cvtile").forEach((t) =>
      t.classList.toggle("selected", t.dataset.hash === hash));
    overlay.querySelector(".cvok").disabled = !hash;
  }

  async function commit() {
    if (!song || !pick) return;
    const hash = song.hash;
    try {
      const r = await setCover(hash, pick);
      close();
      emit("cover-changed", { hash, manual: r.manual });
    } catch (err) { showError(err.message); }
  }

  overlay.addEventListener("click", (e) => {
    if (e.target === overlay || e.target.closest(".cvcancel")) { close(); return; }
    if (e.target.closest(".cvok")) { commit(); return; }
    const x = e.target.closest(".chipx");
    if (x) { removeChip(parseInt(x.dataset.i, 10)); return; }
    const t = e.target.closest(".cvtile");
    if (t) choose(t.dataset.hash);
  });
  overlay.addEventListener("dblclick", (e) => {
    const t = e.target.closest(".cvtile");
    if (t) { choose(t.dataset.hash); commit(); }
  });
  overlay.addEventListener("keydown", async (e) => {
    // Tasten gehören dem Dialog: Ziffern (Bewertung), Entf (Ablehnen),
    // Leertaste (Wiedergabe) dürfen nicht zur Galerie durchschlagen. Esc
    // schließt über den Dialog-Stapel (overlays.js, Capture davor).
    if (e.key !== "Escape") e.stopPropagation();
    const input = e.target.closest?.(".cvinput");
    if (input && e.key === "Enter" && input.value.trim()) {
      // Wie die Suche: ein Wort ist Text, Grammatik bleibt Grammatik.
      e.preventDefault();
      clearTimeout(liveTimer);
      live = "";
      if (await applyExpression(`${expr} ${inputExpression(input.value.trim())}`)) input.value = "";
    } else if (!input && e.key === "Enter" && pick) {
      e.preventDefault();
      commit();
    }
  });
  // Live filtern beim Tippen (ab 3 Zeichen, Ausdrücke erst mit Enter) —
  // dieselbe Regel wie im Suchfeld der Galerie.
  overlay.addEventListener("input", (e) => {
    const input = e.target.closest?.(".cvinput");
    if (!input) return;
    clearTimeout(liveTimer);
    liveTimer = setTimeout(() => {
      const text = input.value.trim();
      const next = liveInput(text) ? inputExpression(text) : "";
      if (next === live) return;
      live = next;
      showError("");
      loadMore(true);
    }, 350);
  });
  overlay.addEventListener("scroll", (e) => {
    const g = e.target;
    if (g.classList?.contains("cvgrid") && g.scrollTop + g.clientHeight > g.scrollHeight - 300) {
      loadMore(false);
    }
  }, true);

  on("cover-pick", (d) => {
    if (!d?.hash) return;
    song = { hash: d.hash, name: d.name || d.hash.slice(0, 12), cover: d.cover || null };
    live = "";
    pick = song.cover;
    frame();
    overlay.hidden = false;
    unregister = registerDialog(overlay, close);
    choose(pick);
    applyExpression(startExpression(d.tags));
    overlay.querySelector(".cvinput").focus();
  });
}
