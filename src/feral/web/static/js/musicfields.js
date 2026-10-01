// musicfields.js — Musik-Angaben von Hand im Detailpanel (ADR 0101, #256).
//
// Acht Felder unter KURATIERT, vorbelegt mit dem geltenden Wert (Angabe von
// Hand, sonst der Wert aus der Datei). Eine Eingabe wirkt auf die AUSWAHL;
// Felder mit unterschiedlichen Werten zeigen „(verschieden)" und bleiben
// unberührt, solange nichts getippt wird. Leeren bzw. ein Klick auf
// „✎ von Hand" entfernt die Angabe, dann gilt wieder der Wert aus der Datei.
// Tab springt von Feld zu Feld (der Knopf liegt außerhalb der Tab-Reihenfolge).
//
// Event: 'fields-changed' {hashes, fields, items} — Liste (ersetzt die
// Zeilen aus `items`), Seitenleiste und „Erstellt" im Panel ziehen nach.

import { getMusicFields, setMusicFields } from "./api.js";
import { STRINGS } from "./strings.js";
import { emit } from "./main.js";

export const MUSIC_FIELDS = ["title", "artist", "album_artist", "album", "track", "disc", "year", "genre"];
const MULTI = new Set(["artist", "genre"]);

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** Die Felder in `box` aufbauen und mit dem Stand der Auswahl füllen. */
export async function mountMusicFields(box, hashes) {
  box.innerHTML = `
    <div class="mfhead" title="${esc(STRINGS.musicFieldsHint)}">${STRINGS.musicFieldsTitle}</div>
    ${MUSIC_FIELDS.map((f) => `
      <div class="mfrow" data-field="${f}">
        <span class="mflabel">${esc(STRINGS.musicFieldLabels[f])}</span>
        <input autocomplete="off"${MULTI.has(f) ? ` title="${esc(STRINGS.musicFieldsMulti)}"` : ""}>
        <button type="button" class="mfhand" tabindex="-1" hidden>${STRINGS.musicFieldsManual}</button>
      </div>`).join("")}
    <div class="vdim mfnote" hidden></div>`;
  const note = box.querySelector(".mfnote");
  let state = null;

  function paint() {
    for (const row of box.querySelectorAll(".mfrow")) {
      const st = state[row.dataset.field];
      const input = row.querySelector("input");
      if (document.activeElement !== input) input.value = st.value;
      input.placeholder = st.mixed ? STRINGS.musicFieldsMixed : "";
      const hand = row.querySelector(".mfhand");
      hand.hidden = !st.manual;
      hand.title = STRINGS.musicFieldsManualTitle
        + (st.source ? ` ${STRINGS.musicFieldsFrom.replace("{source}", st.source)}` : "");
    }
  }

  async function apply(changes) {
    try {
      const d = await setMusicFields(hashes, changes);
      if (d.queued) {
        note.textContent = STRINGS.musicFieldsQueued.replace("{n}", d.count);
        note.hidden = false;
        return;
      }
      note.hidden = true;
      state = d.fields;
      paint();
      // `items` = frische Listenzeilen der geänderten Songs: die Liste
      // ersetzt sie an Ort und Stelle (kein Neuladen, die Auswahl bleibt).
      emit("fields-changed", { hashes, fields: Object.keys(changes), items: d.items || [] });
    } catch (err) {
      note.textContent = err.message;
      note.hidden = false;
    }
  }

  function take(input) {
    const field = input.closest(".mfrow").dataset.field;
    const st = state?.[field];
    const value = input.value.trim();
    if (!st || value === st.value) return;
    // Leer ohne Angabe von Hand: nichts zu entfernen, der Dateiwert bleibt stehen.
    if (!value && !st.manual) { input.value = st.value; return; }
    apply({ [field]: value });
  }

  box.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.matches("input")) { e.preventDefault(); e.target.blur(); }
  });
  box.addEventListener("focusout", (e) => { if (e.target.matches("input")) take(e.target); });
  box.addEventListener("click", (e) => {
    const hand = e.target.closest(".mfhand");
    if (hand && state) apply({ [hand.closest(".mfrow").dataset.field]: "" });
  });

  try {
    state = (await getMusicFields(hashes)).fields;
  } catch (err) {
    console.warn(err);
    return;
  }
  if (box.isConnected !== false) paint();
}
