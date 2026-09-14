// gallery.test.mjs — Galerie über den Bus: „Alle Medien" nach Filter (Issue
// #33, nur der Sidebar-Klick setzt nach oben; ✕/Esc springen zurück), Rücksprung bei Filterwechsel (ADR 0060), schonender Refresh bei
// engine-idle (ADR 0057, Issue #32). Läuft mit search.js zusammen, damit der
// Weg Sidebar → Suchzustand → Grid so geprüft wird, wie er im Browser liegt.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, keydown, click, flush, item, hashOf, serveLibrary } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit, record } from "./bus.mjs";

const { initGallery } = await import("../../src/feral/web/static/js/gallery.js");
const { initSearch } = await import("../../src/feral/web/static/js/search.js");

const grid = () => document.getElementById("grid");
const wrap = () => document.getElementById("gridwrap");
const tileOf = (hash) => grid().querySelector(`.tile[data-hash="${hash}"]`);
const selectedHashes = () => grid().querySelectorAll(".tile.selected").map((t) => t.dataset.hash);

const items = Array.from({ length: 30 }, (_, i) => item(i + 1));
let lib;

before(async () => {
  loadShell();
  lib = serveLibrary(items);
  // Die Filtergrammatik lebt serverseitig (ADR 0035): hier eine Attrappe,
  // die aus „rating>=1" ein Prädikat macht.
  mockApi.get("/api/filter/parse", ({ params }) => ({
    expression: params.get("expr"),
    predicates: [{ kind: "rating", op: ">=", values: [{ value: "1" }] }],
    sort: null,
  }));
  mockApi.post("/api/filter/build", () => ({ expression: "", predicates: [], sort: null }));
  // Layout-Attrappe: Kacheln 100 px hoch, 4 Spalten (getComputedStyle-Stub),
  // Sichtfenster 1000 px → alle 30 Kacheln liegen im Render-Fenster.
  document.rectFor = (el) => (el.classList.contains("tile") ? { height: 100 } : null);
  wrap().clientHeight = 1000;
  initGallery();
  initSearch();
  await flush();
});

/** Ausgangslage: neutraler Zustand, Bild 5 ausgewählt, nach unten gescrollt. */
async function selectAndScroll() {
  emit("selection-changed", { hash: hashOf(5), index: 4 });
  wrap().scrollTop = 300;
  await flush();
  assert.deepEqual(selectedHashes(), [hashOf(5)]);
  mockApi.calls.length = 0;
}

test("Erstes Laden: alle Kacheln stehen, Trefferzahl gemeldet", () => {
  assert.equal(grid().querySelectorAll(".tile[data-hash]").length, 30);
  assert.equal(grid().children[0].dataset.hash, hashOf(1));
  assert.ok(tileOf(hashOf(7)).querySelector("img"), "Thumb-Element je Kachel");
  assert.ok(document.getElementById("crumb").textContent.includes("30"));
});

test("Filterwechsel: Rücksprung zum ausgewählten Bild (ADR 0060)", async () => {
  await selectAndScroll();
  const sel = record("selection-changed");
  emit("state-load", { expression: "rating>=1" });
  await flush(10);
  assert.equal(mockApi.callsTo("/api/items/position").length, 1, "Position wird nachgeschlagen");
  assert.equal(sel.at(-1)?.hash, hashOf(5), "Auswahl landet wieder auf Bild 5");
  assert.equal(sel.at(-1)?.index, 4);
  sel.stop();
  assert.deepEqual(selectedHashes(), [hashOf(5)]);
});

test("Sidebar ‚Alle Medien‘: oben, keine Auswahl, kein Rücksprung (#33)", async () => {
  emit("state-load", { expression: "rating>=1" });     // erst ein Filter …
  await flush(10);
  await selectAndScroll();                              // … dann Auswahl + Scroll
  const sel = record("selection-changed");
  emit("state-clear", {});
  await flush(10);
  sel.stop();
  assert.equal(wrap().scrollTop, 0, "Galerie steht oben");
  assert.equal(mockApi.callsTo("/api/items/position").length, 0, "kein Rücksprung-Lookup");
  assert.ok(!sel.some((d) => d.hash), "keine Auswahl gesetzt");
  assert.deepEqual(selectedHashes(), [], "kein Ring im Grid");
});

test("✕ Filter zurücksetzen / Esc: Rücksprung zum Bild bleibt (ADR 0060, #33)", async () => {
  const triggers = [
    ["Knopf ‚Filter zurücksetzen‘", () => click(document.getElementById("filterReset"))],
    ["Esc in der Galerie", () => keydown("Escape")],
  ];
  for (const [name, fire] of triggers) {
    emit("state-load", { expression: "rating>=1" });
    await flush(10);
    await selectAndScroll();
    const sel = record("selection-changed");
    fire();
    await flush(10);
    sel.stop();
    assert.equal(mockApi.callsTo("/api/items/position").length, 1, `${name}: Position nachgeschlagen`);
    assert.equal(sel.at(-1)?.hash, hashOf(5), `${name}: Auswahl wieder auf Bild 5`);
    assert.deepEqual(selectedHashes(), [hashOf(5)], `${name}: Ring am Bild`);
  }
});

test("engine-idle: schonender Refresh meldet items-refreshed, Auswahl bleibt am Bild", async () => {
  emit("state-clear", {});
  await flush(10);
  emit("selection-changed", { hash: hashOf(1), index: 0 });
  wrap().scrollTop = 40;
  await flush();
  lib.items = [item(99), ...items];                     // Watchordner: neues Bild oben
  const reloaded = record("items-reloaded");
  const refreshed = record("items-refreshed");
  emit("engine-idle", {});
  await flush(10);
  reloaded.stop(); refreshed.stop();
  assert.equal(reloaded.length, 0, "kein harter Reload");
  assert.equal(refreshed.length, 1);
  assert.equal(refreshed[0].total, 31);
  assert.equal(wrap().scrollTop, 40, "Scrollposition bleibt");
  assert.equal(grid().children[0].dataset.hash, hashOf(99), "neues Item steht oben");
  assert.deepEqual(selectedHashes(), [hashOf(1)], "Auswahl hängt am Bild, nicht am Index");
});

test("engine-idle: Kacheln bleiben stehen, nur Geändertes wird ausgetauscht (#32)", async () => {
  emit("selection-changed", { hash: hashOf(1), index: 1 });
  await flush();
  const imgBefore = tileOf(hashOf(1)).querySelector("img");
  const srcBefore = imgBefore.src;
  assert.ok(srcBefore, "Thumb war geladen");
  lib.items = [item(98), ...lib.items];
  lib.gate = mockApi.gate();                            // Seitenantwort anhalten
  emit("engine-idle", {});
  await flush(2);
  // Während die Seite unterwegs ist, rendert ein Scroll das Grid neu — die
  // alten Kacheln müssen dabei stehen bleiben (kein Leer-Zwischenzustand).
  wrap().dispatchEvent(new UIEvent("scroll"));
  await flush(2);
  assert.equal(grid().querySelectorAll(".tile[data-hash]").length, 31,
    "Kacheln bleiben gefüllt, solange die neue Seite fehlt");
  lib.gate.open(); lib.gate = null;
  await flush(10);
  assert.equal(grid().children[0].dataset.hash, hashOf(98));
  const imgAfter = tileOf(hashOf(1)).querySelector("img");
  assert.equal(imgAfter, imgBefore, "Kachel-Element von Bild 1 wird wiederverwendet");
  assert.equal(imgAfter.src, srcBefore, "Thumb wird nicht neu gesetzt");
});

test("items-rejected: Nachfolger rückt an die Grid-Position, übrige Kacheln wandern mit (#32)", async () => {
  emit("selection-changed", { hash: hashOf(3), index: 4 });   // Bild 3 steht an Position 4
  await flush();
  const imgOf7 = tileOf(hashOf(7)).querySelector("img");
  lib.items = lib.items.filter((it) => it.file_hash !== hashOf(3));
  const sel = record("selection-changed");
  emit("items-rejected", {});
  await flush(10);
  sel.stop();
  assert.equal(sel.at(-1)?.hash, hashOf(4), "Nachfolger an derselben Position");
  assert.equal(sel.at(-1)?.index, 4);
  assert.equal(tileOf(hashOf(3)), null, "abgelehnte Kachel ist weg");
  assert.equal(tileOf(hashOf(7)).querySelector("img"), imgOf7, "Kachel von Bild 7 wandert mit");
  assert.equal(tileOf(hashOf(7)).dataset.index, "7", "Position wurde nachgezogen");
  assert.equal(grid().querySelectorAll(".tile[data-hash]").length, 31);
});
