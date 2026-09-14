// compare.test.mjs — A/B-Vergleichsansicht (Issue #38): Öffnen über Taste C,
// Knopf und Bus, Tastatur-Guards in beide Richtungen (kein zweites Overlay,
// Galerie/Lupe/Einzelansicht/curate.js bekommen die Tasten NICHT), Wischkante,
// Tausch, Bewerten und Ablehnen der Seite A, Schließpfade über den Bus.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import {
  loadShell, keydown, click, flush, item, hashOf, serveLibrary, visibleOverlays,
} from "./harness.mjs";
import { emit, record } from "./bus.mjs";
import { mockApi } from "./apimock.mjs";

const { initLoupe } = await import("../../src/feral/web/static/js/loupe.js");
const { initSingleView } = await import("../../src/feral/web/static/js/singleview.js");
const { initCurate } = await import("../../src/feral/web/static/js/curate.js");
const { initCompare } = await import("../../src/feral/web/static/js/compare.js");

const compare = () => document.getElementById("compare");
const btn = () => document.getElementById("compareBtn");
const imgA = () => compare().querySelector(".cmpa");
const imgB = () => compare().querySelector(".cmpb");
const sideA = () => compare().querySelector('.cmpside[data-side="a"]');
const divider = () => compare().querySelector(".cmpdivider");

const items = [
  item(1), item(2, { width: 768, height: 768 }), item(3),
  item(4, { media_kind: "video", container: "webm", fps: 24 }),
];
const [h1, h2, h3, h4] = items.map((it) => it.file_hash);

before(() => {
  loadShell();
  serveLibrary(items);
  // Rating-Endpunkt antwortet mit dem frischen Stand (wie der Server).
  mockApi.post(/^\/api\/item\/[0-9a-f]+\/rating$/, ({ body }) =>
    ({ manual: { rating: body.rating || null, tags: [], notes: "", model: null } }));
  mockApi.post("/api/batch/apply", ({ body }) => ({ rejected: body.hashes.length }));
  // Reihenfolge wie in main.js: curate.js hängt seinen Esc-Fänger VOR compare.js ein.
  initLoupe();
  initSingleView();
  initCurate();
  initCompare();
});

const pair = (a = h1, b = h3) => emit("selection-changed", { hash: a, index: 0, hashes: [a, b] });
const ratingCalls = (hash) =>
  mockApi.calls.filter((c) => c.method === "POST" && c.path === `/api/item/${hash}/rating`);

/** Ausgangslage je Test: alles zu, Bild 1 UND 3 markiert. */
async function reset() {
  keydown("Escape"); keydown("Escape");
  await flush();
  mockApi.calls.length = 0;
  pair();
  assert.deepEqual(visibleOverlays(), []);
}

async function openPair() {
  keydown("c");
  await flush();
  assert.deepEqual(visibleOverlays(), ["compare"]);
}

test("Knopf ⇆ erscheint nur bei genau zwei markierten Medien", async () => {
  await reset();
  assert.equal(btn().hidden, false);
  emit("selection-changed", { hash: h1, index: 0 });
  assert.equal(btn().hidden, true);
  emit("selection-changed", { hash: h1, index: 0, hashes: [h1, h2, h3] });
  assert.equal(btn().hidden, true);
  emit("selection-changed", { hash: null, index: null, hashes: [] });
  assert.equal(btn().hidden, true);
});

test("C mit zwei markierten Bildern öffnet den Vergleich, Esc schließt", async () => {
  await reset();
  await openPair();
  assert.ok(imgA().src.includes(h1), "A ist das Primär-Item");
  assert.ok(imgB().src.includes(h3), "B ist das zweite Item");
  assert.equal(sideA().dataset.hash, h1);
  assert.equal(compare().querySelector("#cmpDims").hidden, true, "gleiche Maße: kein Hinweis");
  keydown("Escape");
  assert.deepEqual(visibleOverlays(), []);
  assert.equal(imgA().getAttribute("src"), null, "Bilder beim Schließen entladen");
});

test("Knopf und Bus-Event öffnen ebenfalls; ✕ schließt", async () => {
  await reset();
  click(btn());
  await flush();
  assert.deepEqual(visibleOverlays(), ["compare"]);
  click(compare().querySelector("#cmpClose"));
  assert.deepEqual(visibleOverlays(), []);
  emit("compare-open", { hashes: [h2, h1] });
  await flush();
  assert.deepEqual(visibleOverlays(), ["compare"]);
  assert.equal(sideA().dataset.hash, h2);
  assert.equal(compare().querySelector("#cmpDims").hidden, false, "768 vs 512: Hinweis sichtbar");
});

test("C ohne Zweier-Auswahl öffnet nichts", async () => {
  await reset();
  emit("selection-changed", { hash: h1, index: 0 });
  keydown("c");
  await flush();
  assert.deepEqual(visibleOverlays(), []);
  emit("selection-changed", { hash: h1, index: 0, hashes: [h1, h2, h3] });
  keydown("C");
  await flush();
  assert.deepEqual(visibleOverlays(), []);
});

test("Lupe oder Einzelansicht offen: C öffnet KEINEN Vergleich", async () => {
  await reset();
  keydown(" ");
  await flush();
  assert.deepEqual(visibleOverlays(), ["loupe"]);
  keydown("c");
  await flush();
  assert.deepEqual(visibleOverlays(), ["loupe"]);
  keydown("Escape");
  keydown("Enter");
  await flush();
  assert.deepEqual(visibleOverlays(), ["single"]);
  keydown("c");
  await flush();
  assert.deepEqual(visibleOverlays(), ["single"]);
});

test("Vergleich offen: Space schaltet Wisch → nur A → nur B → Wisch, Enter schließt — keine Lupe, keine Einzelansicht", async () => {
  await reset();
  await openPair();
  const clip = compare().querySelector(".cmpclip");
  const cls = () => ["nowipe", "onlyb"].filter((c) => compare().classList.contains(c));
  assert.deepEqual(cls(), []);
  keydown(" ");
  await flush();
  assert.deepEqual(visibleOverlays(), ["compare"]);
  assert.deepEqual(cls(), ["nowipe"], "nur A");
  keydown(" ");
  assert.deepEqual(cls(), ["nowipe", "onlyb"], "nur B");
  assert.equal(clip.style.left, "0%", "B über die ganze Breite");
  keydown("ArrowRight");
  assert.equal(clip.style.left, "0%", "Pfeile bewegen ohne Wisch nichts");
  keydown(" ");
  assert.deepEqual(cls(), [], "wieder Wisch");
  assert.equal(clip.style.left, "50%", "Wischkante steht noch, wo sie war");
  click(compare().querySelector("#cmpWipe"));
  assert.deepEqual(cls(), ["nowipe"], "Knopf schaltet genauso weiter");
  keydown("Enter");
  await flush();
  assert.deepEqual(visibleOverlays(), []);
});

test("←/→ bewegen die Wischkante und wandern NICHT in die Galerie", async () => {
  await reset();
  await openPair();
  const seen = record("selection-changed");
  assert.equal(divider().style.left, "50%");
  keydown("ArrowLeft");
  assert.equal(divider().style.left, "48%");
  keydown("ArrowRight", { shiftKey: true });
  assert.equal(divider().style.left, "58%");
  keydown("Home");
  assert.equal(divider().style.left, "0%");
  keydown("ArrowLeft");
  assert.equal(divider().style.left, "0%", "Anschlag links");
  keydown("End");
  assert.equal(divider().style.left, "100%");
  await flush();
  assert.equal(seen.length, 0, "Galerie hat nicht geblättert");
  seen.stop();
  keydown("Escape");
});

test("Tab tauscht A und B", async () => {
  await reset();
  await openPair();
  keydown("Tab");
  assert.equal(sideA().dataset.hash, h3);
  assert.ok(imgA().src.includes(h3));
  assert.ok(imgB().src.includes(h1));
  click(compare().querySelector("#cmpSwap"));
  assert.equal(sideA().dataset.hash, h1);
  keydown("Escape");
});

test("1–5 bewerten NUR Seite A (gleiche Zahl löscht), curate.js bleibt außen vor", async () => {
  await reset();
  await openPair();
  keydown("3");
  await flush();
  assert.equal(ratingCalls(h1).length, 1);
  assert.equal(ratingCalls(h1)[0].body.rating, 3);
  assert.equal(ratingCalls(h3).length, 0, "B unbewertet");
  assert.equal(mockApi.calls.filter((c) => c.path === "/api/batch/annotate").length, 0,
    "keine Sammel-Bewertung der Zweier-Auswahl");
  assert.equal(sideA().querySelectorAll(".rdot.on").length, 3, "Punkte nachgezogen");
  keydown("3");
  await flush();
  assert.equal(ratingCalls(h1)[1].body.rating, 0, "Toggle: gleiche Zahl löscht");
  // Punkte-Klick auf Seite B bewertet B.
  click(compare().querySelector('.cmpside[data-side="b"] .rdot[data-n="5"]'));
  await flush();
  assert.equal(ratingCalls(h3)[0].body.rating, 5);
  keydown("Escape");
});

test("Entf öffnet den Ablehnen-Dialog für A; Ablehnen beendet den Vergleich", async () => {
  await reset();
  await openPair();
  const dlg = document.getElementById("rejectdlg");
  keydown("Delete");
  assert.equal(dlg.hidden, false);
  assert.ok(dlg.querySelector(".pickpath").textContent.startsWith("1 "), "genau ein Medium");
  // Esc schließt NUR den Dialog (curate.js fängt in der Capture-Phase ab).
  keydown("Escape");
  assert.equal(dlg.hidden, true);
  assert.deepEqual(visibleOverlays(), ["compare"]);
  keydown("Delete");
  const rejected = record("items-rejected");
  click(dlg.querySelector(".rejgo"));
  await flush();
  assert.equal(rejected.length, 1);
  assert.deepEqual(rejected[0].hashes, [h1]);
  assert.deepEqual(visibleOverlays(), []);
  rejected.stop();
});

test("items-reloaded und loupe-open schließen den Vergleich", async () => {
  await reset();
  await openPair();
  emit("items-reloaded", { total: 3 });
  assert.deepEqual(visibleOverlays(), []);
  assert.equal(btn().hidden, true, "Auswahl ist weg");
  pair();
  await openPair();
  emit("loupe-open", { hash: h1 });
  await flush();
  assert.deepEqual(visibleOverlays(), ["loupe"]);
  keydown("Escape");
});

test("Video in der Auswahl: Hinweis statt Bilder (erste Version nur Bilder)", async () => {
  await reset();
  pair(h1, h4);
  await openPair();
  const note = compare().querySelector("#cmpStage .nopreview");
  assert.ok(note && note.textContent.length > 0, "Hinweistext liegt auf der Bühne");
  assert.equal(compare().querySelector("#cmpFrame").hidden, true);
  assert.equal(imgA().getAttribute("src"), null);
  keydown("Escape");
  assert.equal(compare().querySelector("#cmpStage .nopreview"), null, "Hinweis beim Schließen entfernt");
});
