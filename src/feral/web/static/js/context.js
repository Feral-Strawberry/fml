// context.js — Bearbeiten-Modus für Rankings im Breadcrumb (ADR 0081,
// Issue #91; seit der Revision #133 NUR noch für Rankings — gespeicherte
// Suchen pflegt wieder der ☆-Dialog mit ausgesprochenem Ursprung,
// savedialog.js).
//
// Regel 1 von ADR 0081: „Die Leiste bearbeitet das Geladene." Ist ein
// Ranking per ✎ aus der Ranking-Ansicht geladen, steht vorn im Breadcrumb
// ein Segment `Bearbeiten: 🏆 Name` mit Stift
// (Umbenennen inline), „Suche/Ranking speichern" (nur aktiv, wenn die Chips
// vom Gespeicherten abweichen — dann steht ein Punkt am Namen) und
// „✕ Beenden". Die Kopfzeile trägt dabei die Klasse `editing` (#133:
// akzentfarbene Zeile, die Icons ☆/🏆 rechts zeigen nur noch ihr Symbol —
// Feral Strawberry klickte sonst aufs ☆ „speichern", um ein Ranking zu sichern). Die
// Icons ☆/🏆 in #midtools legen NUR Neues an (Regel 2, search.js).
//
// Kein zweiter Suchzustand: das Segment merkt sich nur, WELCHES Objekt
// geladen ist, und vergleicht kanonische Ausdrücke aus /api/filter/build
// (EIN Serialisierer, ADR 0035). Bei Arenen zählt ein sort:-Chip nicht —
// die Arena hat ihre eigene Ordnung; das Ein-Token-Prädikat wird vor
// Vergleich und Speichern aus dem kanonischen Text gestrichen.
//
// Lebensdauer: 'state-load' mit `arena` (✎ in der Ranking-Ansicht) setzt
// den Kontext; ✕, 'state-clear' („Alle Medien"/Esc), die Dubletten-Ansicht
// und das Laden einer gespeicherten Suche beenden ihn. Ein leerer Ausdruck
// beendet ihn NICHT: „ganze Bibliothek" ist eine gültige Population.
//
// Das Segment ist ein persistentes Element (ein offenes Umbenennen darf
// die Neuzeichnung der Chips überleben) und hängt sich nach jedem
// 'chips-rendered' in den Slot, den search.js hinter „Bibliothek /" lässt.

import { STRINGS } from "./strings.js";
import { updateRanking } from "./api.js";
import { emit, on } from "./main.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** sort:-Direktive aus einem kanonischen Ausdruck streichen (Arenen). */
export const withoutSort = (expression) =>
  String(expression || "").replace(/(^|\s)-?sort:\s*\S+/g, " ").replace(/\s+/g, " ").trim();

export function initContext() {
  // ctx: null | {kind: "arena", id, name, saved} — saved = kanonischer
  // Ausdruck des Gespeicherten; null = wird mit dem nächsten Zustand
  // übernommen (der gespeicherte Text kann aus alten Fassungen stammen und
  // muss erst durch den Parser, bevor er vergleichbar ist).
  let ctx = null;
  let current = "";      // kanonischer Ausdruck des Suchzustands (ohne Live-Begriffe)
  let renaming = false;

  const seg = document.createElement("span");
  seg.id = "ctxseg";
  seg.className = "ctxseg";

  const relevant = (expr) => (ctx?.kind === "arena" ? withoutSort(expr) : expr);
  const dirty = () => !!ctx && ctx.saved !== null && relevant(current) !== relevant(ctx.saved);

  function attach() {
    const slot = document.querySelector("#crumb .ctxslot");
    if (!ctx || !slot) { seg.remove(); return; }
    if (seg.parentNode !== slot) slot.appendChild(seg);
  }

  function render() {
    if (!ctx) { seg.remove(); return; }
    const icon = ctx.kind === "arena" ? "🏆" : "☆";
    const kindLabel = STRINGS.ctxArena;
    if (!renaming) {
      const saveLabel = STRINGS.ctxSaveArena;
      seg.innerHTML = `
        <span class="ctxlabel">${esc(STRINGS.ctxEditing)}</span>
        <span class="ctxicon" title="${esc(kindLabel)}">${icon}</span>
        <span class="ctxname" title="${esc(kindLabel)}: ${esc(ctx.name)}">${esc(ctx.name)}</span>
        <span class="ctxdirty" title="${esc(STRINGS.ctxDirtyTitle)}"${dirty() ? "" : " hidden"}>•</span>
        <button type="button" class="ctxrename" title="${esc(STRINGS.ctxRenameTitle)}">✎</button>
        <button type="button" class="ctxsave"${dirty() ? "" : " disabled"} title="${esc(STRINGS.ctxSaveTitle)}">${esc(saveLabel)}</button>
        <button type="button" class="ctxclose" title="${esc(STRINGS.ctxCloseArenaTitle)}">✕ ${esc(STRINGS.ctxClose)}</button>
        <span class="ctxerr" hidden></span>
        <span class="ctxsep">/</span>`;
    } else {
      // Umbenennen läuft: nur den Speichern-Zustand nachziehen, das
      // Eingabefeld bleibt unangetastet.
      const save = seg.querySelector(".ctxsave");
      if (save) save.disabled = !dirty();
      const dot = seg.querySelector(".ctxdirty");
      if (dot) dot.hidden = !dirty();
    }
    attach();
  }

  function showError(message) {
    const el = seg.querySelector(".ctxerr");
    if (!el) return;
    el.textContent = `⚠ ${message}`;
    el.hidden = false;
  }

  function set(next) {
    ctx = next;
    renaming = false;
    // Bearbeiten-Modus sichtbar (#133): Kopfzeile akzentfarben, Icons rechts ohne Text (app.css).
    document.getElementById("midhead")?.classList.toggle("editing", !!ctx);
    render();
    emit("context-changed", ctx ? { kind: ctx.kind, id: ctx.id, name: ctx.name } : null);
  }

  // -- Aktionen ---------------------------------------------------------------

  async function persist(name, expression) {
    await updateRanking(ctx.id, name, withoutSort(expression));
    emit("rankings-changed", {});
  }

  async function save() {
    if (!dirty()) return;
    const { id, name } = ctx;
    try {
      await persist(name, current);
      ctx.saved = current;
      // Zurück ins Ranking — die Population gilt ab jetzt dort.
      set(null);
      emit("arena-open", { id, name, expression: withoutSort(current) });
    } catch (err) { showError(err.message); }
  }

  function startRename() {
    renaming = true;
    const nameEl = seg.querySelector(".ctxname");
    nameEl.innerHTML = `<input type="text" class="ctxinput" value="${esc(ctx.name)}">`;
    const input = nameEl.querySelector("input");
    input.focus();
    input.select();
  }

  async function finishRename(commit) {
    const input = seg.querySelector(".ctxinput");
    const name = input ? input.value.trim() : "";
    if (!commit || !name || name === ctx.name) { renaming = false; render(); return; }
    try {
      // NUR der Name: die Population bleibt, wie sie gespeichert ist —
      // ungesicherte Chip-Änderungen sichert erst „Speichern".
      await persist(name, ctx.saved ?? current);
      ctx.name = name;
      renaming = false;
      render();
      emit("context-changed", { kind: ctx.kind, id: ctx.id, name });
    } catch (err) { renaming = false; render(); showError(err.message); }
  }

  function close() {
    const was = ctx;
    set(null);
    if (was?.kind === "arena") {
      emit("arena-open", { id: was.id, name: was.name, expression: withoutSort(was.saved ?? "") });
    }
  }

  seg.addEventListener("click", (e) => {
    if (e.target.closest(".ctxrename")) return void startRename();
    if (e.target.closest(".ctxsave")) return void save();
    if (e.target.closest(".ctxclose")) return void close();
  });
  seg.addEventListener("keydown", (e) => {
    if (!e.target.matches(".ctxinput")) return;
    if (e.key === "Enter") { e.preventDefault(); finishRename(true); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); finishRename(false); }
  });
  seg.addEventListener("focusout", (e) => {
    if (e.target.matches?.(".ctxinput") && renaming) finishRename(true);
  });

  // -- Bus ------------------------------------------------------------------

  on("state-load", (d) => {
    // Leerer Ausdruck („ganze Bibliothek"): search.js setzt ihn synchron, der
    // Zustandswechsel ist dann schon durch — Vergleichsbasis direkt "".
    // Sonst kommt die kanonische Fassung mit dem nächsten Zustandswechsel.
    // Eine gespeicherte Suche (d.folder) ist KEIN Bearbeiten-Modus (#133):
    // sie beendet höchstens einen laufenden.
    const saved = String(d.expression || "").trim() ? null : "";
    if (d.arena) set({ kind: "arena", id: d.arena.id, name: d.arena.name, saved });
    else set(null);
  });
  on("state-clear", () => set(null));
  on("source-changed", (d) => { if (d?.kind === "dupes") set(null); });
  on("search-state-changed", (d) => {
    current = d.canonical ?? "";
    if (!ctx) return;
    if (ctx.saved === null) ctx.saved = current;          // geladener Stand, kanonisch
    render();
  });
  on("chips-rendered", attach);
}
