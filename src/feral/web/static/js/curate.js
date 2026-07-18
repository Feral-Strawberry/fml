// curate.js — Kuratieren (Stufe 3.2 + Multiselect ADR 0022): Rating per
// Tastatur und die eine Schreibstelle für die manuelle Schicht.
//
// Alle Rating-/Tag-/Notiz-/Modell-Änderungen laufen durch dieses Modul.
// Einzel-Auswahl nutzt die Einzel-Endpunkte (mit Toggle-Verhalten), eine
// Multiselect-Auswahl (Shift/Strg im Grid) läuft über /api/batch/annotate —
// EIN Durchlauf durch den einen Writer. Events: 'annotation-changed'
// {hash, manual} für das Panel (Primär-Item) und 'annotations-batch'
// {hashes, rating} für die Grid-Kacheln der ganzen Auswahl.

import { setRating, setNotes, addTag, removeTag, batchAnnotate, rejectItems } from "./api.js";
import { STRINGS } from "./strings.js";
import { emit, on } from "./main.js";

/** 5 Rating-Punkte als HTML (geteilt von Panel und Loupe). */
export const dotsHtml = (rating) =>
  [1, 2, 3, 4, 5].map((n) =>
    `<span class="rdot${rating && n <= rating ? " on" : ""}" data-n="${n}" title="${n}★"></span>`,
  ).join("");

let current = null;       // {hash, index, hashes?} — letzte Auswahl
let currentRating = null; // fürs Toggle-Verhalten (gleiche Zahl löscht)

/** Aktuelle Auswahl als Hash-Liste, Primär-Item (Panel) zuerst. */
export function selectionHashes() {
  if (!current) return [];
  if (!current.hashes || current.hashes.length <= 1) return [current.hash];
  return [current.hash, ...current.hashes.filter((h) => h !== current.hash)];
}

async function apply(promise, hash) {
  try {
    const d = await promise;
    if (current && current.hash === hash) currentRating = d.manual.rating;
    emit("annotation-changed", { hash, manual: d.manual });
    return d.manual;
  } catch (err) {
    console.warn(err);
    return null;
  }
}

async function applyBatch(hashes, fields) {
  try {
    const d = await batchAnnotate(hashes, fields);
    if (current && current.hash === hashes[0]) currentRating = d.manual.rating;
    emit("annotation-changed", { hash: hashes[0], manual: d.manual });
    if ("rating" in fields) {
      emit("annotations-batch", { hashes, rating: fields.rating || null });
    }
    return d.manual;
  } catch (err) {
    console.warn(err);
    return null;
  }
}

/** Rating auf die AUSWAHL anwenden (Einzel: mit Toggle; Multi: setzen). */
export function applyRating(n) {
  const hashes = selectionHashes();
  if (!hashes.length) return null;
  if (hashes.length > 1) return applyBatch(hashes, { rating: n });
  return rate(hashes[0], n !== 0 && n === currentRating ? 0 : n);
}

/** Tag an die AUSWAHL hängen. */
export function applyTag(name) {
  const hashes = selectionHashes();
  if (!hashes.length) return null;
  if (hashes.length > 1) return applyBatch(hashes, { add_tag: name });
  return tagAdd(hashes[0], name);
}

/** Manuelles Modell für die AUSWAHL setzen ("" löscht; ADR 0022). */
export function applyModel(model) {
  const hashes = selectionHashes();
  if (!hashes.length) return null;
  const done = applyBatch(hashes, { model });
  // „Nach Modell"-Zähler ändern sich — Sidebar einmal voll auffrischen
  // (bewusst eigenes Event: Modell-Zuweisung ist selten, Rating-Klicks nicht).
  done?.then(() => emit("model-changed", { hashes }));
  return done;
}

/** Rating schreiben (0/null löscht) — Einzel-Item. */
export const rate = (hash, rating) => apply(setRating(hash, rating), hash);

/** Notizen schreiben (leer löscht). */
export const note = (hash, notes) => apply(setNotes(hash, notes), hash);

/** Tag anhängen — Einzel-Item. */
export const tagAdd = (hash, name) => apply(addTag(hash, name), hash);

/** Tag lösen. */
export const tagRemove = (hash, name) => apply(removeTag(hash, name), hash);

// -- Ablehnen-Dialog (ADR 0041) --------------------------------------------------
//
// Theme-Dialog statt System-confirm() (Feral Strawberry, 2026-07-11 — seit Entf ablehnt
// statt löscht, darf die Bestätigung auch zum Design gehören): Anzahl im
// Kopf, ehrliche Erklärung, Ablehnen/Abbrechen; Fehler erscheinen im Dialog
// statt als alert(). Muster: Speicher-/Sammel-Dialog (pickoverlay/pickbox).

const rejectOverlay = document.createElement("div");
rejectOverlay.id = "rejectdlg";
rejectOverlay.className = "pickoverlay";
rejectOverlay.hidden = true;
let rejectHashes = [];

function openRejectDialog(hashes) {
  rejectHashes = hashes;
  rejectOverlay.innerHTML = `
    <div class="pickbox savebox">
      <div class="pickhead"><b>${STRINGS.rejectDlgTitle}</b>
        <span class="pickpath">${hashes.length.toLocaleString(STRINGS.locale)} ${hashes.length === 1 ? STRINGS.rejectDlgCountOne : STRINGS.rejectDlgCount}</span></div>
      <div class="bulkline">${STRINGS.rejectConfirm}</div>
      <span class="sderr" hidden></span>
      <div class="sdactions">
        <button type="button" class="sdprimary rejgo">${STRINGS.rejectDlgGo}</button>
        <button type="button" class="rejcancel">${STRINGS.saveDlgCancel}</button>
      </div>
    </div>`;
  rejectOverlay.hidden = false;
  rejectOverlay.querySelector(".rejgo").focus();
}

function closeRejectDialog() {
  rejectOverlay.hidden = true;
  rejectHashes = [];
}

function initRejectDialog() {
  document.body.appendChild(rejectOverlay);
  rejectOverlay.addEventListener("click", async (e) => {
    if (e.target.closest(".rejgo")) {
      const go = rejectOverlay.querySelector(".rejgo");
      go.disabled = true;
      try {
        const d = await rejectItems(rejectHashes);
        emit("items-rejected", { hashes: rejectHashes, rejected: d.rejected });
        closeRejectDialog();
      } catch (err) {
        go.disabled = false;
        const el = rejectOverlay.querySelector(".sderr");
        el.textContent = `⚠ ${err.message}`;
        el.hidden = false;
      }
      return;
    }
    if (e.target.closest(".rejcancel") || e.target === rejectOverlay) closeRejectDialog();
  });
  // CAPTURE + stopPropagation: Esc soll NUR den Dialog schließen — nicht
  // zusätzlich die Lupe/Einzelbildansicht darunter (Entf geht auch dort).
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !rejectOverlay.hidden) {
      e.stopPropagation();
      closeRejectDialog();
    }
  }, true);
}

export function initCurate() {
  initRejectDialog();
  // Leere Auswahl (hash null) zählt wie „nichts ausgewählt" — sonst würden
  // Entf/Rating-Tasten auf einem Phantom-Item arbeiten.
  on("selection-changed", (d) => { current = d.hash ? d : null; currentRating = null; });
  on("items-reloaded", () => { current = null; currentRating = null; });
  // Panel/Loupe melden den geladenen Stand, damit das Toggle stimmt.
  on("annotation-loaded", (d) => {
    if (current && current.hash === d.hash) currentRating = d.rating;
  });

  document.addEventListener("keydown", async (e) => {
    const typing = e.target instanceof Element && e.target.matches("input, textarea, select");
    if (typing || !current) return;
    if (!document.getElementById("admin").hidden) return;
    // Arena offen (Ranking-Modul): 1–5/Entf würden sonst unsichtbar auf
    // der Grid-Auswahl unter der Vollbild-Ebene arbeiten.
    if (!document.getElementById("rankings").hidden) return;
    // Entf = Ablehnen der Auswahl (ADR 0041): Item raus + Sperre — die
    // Datei bleibt unangetastet, egal ob Library oder nur indiziert.
    if (e.key === "Delete") {
      const hashes = selectionHashes();
      if (!hashes.length) return;
      e.preventDefault();
      if (rejectOverlay.hidden) openRejectDialog(hashes);
      return;
    }
    if (e.key < "0" || e.key > "5" || e.altKey || e.ctrlKey || e.metaKey) return;
    e.preventDefault();
    applyRating(parseInt(e.key, 10));
  });
}
