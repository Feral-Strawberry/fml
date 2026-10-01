// liststyle.test.mjs — Darstellung der Audioliste (#258): EIN Regler
// „☰ S M L" (☰ = Angaben, S/M/L = Welle in dieser Höhe, genau ein Knopf
// leuchtet). „Angaben" zeigt flache Zeilen ohne Welle
// mit Titel (aus der Datei, sonst Dateiname), Interpret, Album, Nr., Jahr,
// Genre; fragt keine Analyse an; die Wahl wird gemerkt; der Vergleich zeigt
// immer Wellen; geänderte Musik-Angaben ziehen die Zeilen nach.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, click, flush, item, hashOf, serveLibrary } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit } from "./bus.mjs";

localStorage.setItem("feral-view", "audio");

const { initAudioList, infoRows, listStyle } = await import("../../src/feral/web/static/js/audiolist.js");
const { initLibraryView } = await import("../../src/feral/web/static/js/libview.js");
const { initGallery } = await import("../../src/feral/web/static/js/gallery.js");

const song = (n, extra) => item(n, { media_kind: "audio", container: "mp3", width: null, height: null,
                                     duration: 180, ...extra });
const songs = [
  song(1, { name: "01 Regenzeit.mp3", title: "Regenzeit", artist: "Die Band", album: "Erstes Album",
            track: "3", year: "1994", genre: "Rock; Pop", tool: null }),
  song(2, { name: "song_v3_final.mp3", model: "Suno v4.5", tool: "suno" }),
];
const grid = () => document.getElementById("grid");
const rows = () => grid().querySelectorAll(".arow");
const head = () => document.getElementById("listhead");
const box = () => document.getElementById("density");
const infoBtn = () => box().querySelector('[data-liststyle="info"]');
const sizeBtn = (d) => box().querySelector(`[data-density="${d}"]`);
const lit = () => box().querySelectorAll("button.active").map((b) => b.textContent);
const text = (row, sel) => row.querySelector(sel)?.textContent ?? null;

before(async () => {
  loadShell();
  serveLibrary(songs);
  mockApi.get("/api/stats", () => ({ total_items: 2, audio: true }));
  mockApi.get(/^\/api\/audio\/analysis\//, () => mockApi.status(202, {}));
  document.rectFor = (el) => (el.classList.contains("tile") ? { height: 65 } : null);
  document.getElementById("gridwrap").clientHeight = 1000;
  initLibraryView();
  initGallery();
  initAudioList();
  await flush(10);
});

test("Standard ist Welle: ☰ sichtbar, M leuchtet, Zeilen mit Wellenfläche", () => {
  assert.equal(infoBtn().hidden, false);
  assert.equal(listStyle(), "wave");
  assert.deepEqual(lit(), ["M"]);
  assert.equal(rows().length, 2);
  assert.ok(rows()[0].querySelector(".wv"));
  assert.ok(head().querySelector(".ruler"));
  assert.equal(grid().classList.contains("info"), false);
});

test("☰ Angaben: flache Zeilen mit Spalten, kein Lineal, nur ☰ leuchtet, gemerkt", async () => {
  mockApi.calls.length = 0;
  click(infoBtn());
  await flush();
  assert.equal(infoRows(), true);
  assert.ok(grid().classList.contains("info") && head().classList.contains("info"));
  assert.deepEqual(lit(), ["☰"]);
  assert.equal(localStorage.getItem("feral-liststyle"), "info");
  assert.equal(localStorage.getItem("feral-density"), "m");   // die Galerie behält ihr S/M/L
  assert.equal(head().querySelector(".ruler"), null);
  assert.equal(head().querySelector(".wlegend"), null);
  const [tagged, bare] = rows();
  assert.equal(tagged.querySelector(".wv"), null);
  assert.equal(tagged.querySelector(".rlufs"), null);
  // Titel aus der Datei, der Dateiname steht im Tooltip.
  assert.equal(text(tagged, ".rname b"), "Regenzeit");
  assert.equal(tagged.querySelector(".rname").title, "01 Regenzeit.mp3");
  assert.equal(text(tagged, ".rcell"), "Die Band");
  assert.equal(text(tagged, ".c-album"), "Erstes Album");
  assert.equal(text(tagged, ".c-track"), "3");
  assert.equal(text(tagged, ".c-year"), "1994");
  assert.equal(text(tagged, ".c-genre"), "Rock; Pop");
  // Ohne Titel der Dateiname, ohne Interpret das Modell (abgesetzt).
  assert.equal(text(bare, ".rname b"), "song_v3_final");
  assert.equal(text(bare, ".rcell"), "Suno v4.5");
  assert.ok(bare.querySelector(".rcell").classList.contains("rgen"));
  // Keine Welle, keine Lautheit: die Analyse wird nicht angefragt.
  assert.equal(mockApi.callsTo("/api/audio/analysis").length, 0);
});

test("geänderte Musik-Angaben ersetzen die Zeile an Ort und Stelle, ohne neu zu laden", async () => {
  emit("selection-changed", { hash: hashOf(2), index: 1, hashes: [hashOf(1), hashOf(2)] });
  mockApi.calls.length = 0;
  emit("fields-changed", { hashes: [hashOf(2)], fields: ["title", "artist"],
                           items: [{ ...songs[1], title: "Neuer Titel", artist: "Wir" }] });
  await flush(10);
  assert.equal(mockApi.callsTo("/api/items").length, 0, "kein Neuladen: Sortierung und Filter ziehen nichts unter der Auswahl weg");
  assert.equal(grid().querySelectorAll(".arow.selected").length, 2, "die Mehrfachauswahl bleibt stehen");
  const bare = rows()[1];
  assert.equal(text(bare, ".rname b"), "Neuer Titel");
  assert.equal(text(bare, ".rcell"), "Wir");
  assert.equal(bare.querySelector(".rcell").classList.contains("rgen"), false);
});

test("der Vergleich zeigt immer Wellen, danach wieder Angaben", async () => {
  emit("selection-changed", { hash: hashOf(1), index: 0, hashes: [hashOf(1), hashOf(2)] });
  emit("list-compare-set", { on: true });
  await flush();
  assert.ok(grid().classList.contains("compare"));
  assert.equal(grid().classList.contains("info"), false);
  assert.equal(infoBtn().hidden, true);
  assert.deepEqual(lit(), ["M"]);
  assert.ok(rows()[0].querySelector(".wv"));
  assert.ok(head().querySelector(".ruler"));
  emit("list-compare-set", { on: false });
  await flush();
  assert.ok(grid().classList.contains("info"));
  assert.equal(infoBtn().hidden, false);
  assert.deepEqual(lit(), ["☰"]);
  assert.equal(rows()[0].querySelector(".wv"), null);
});

test("S holt die Welle in dieser Höhe zurück: Wellenfläche und Lineal sind wieder da", async () => {
  click(sizeBtn("s"));
  await flush();
  assert.equal(listStyle(), "wave");
  assert.equal(localStorage.getItem("feral-liststyle"), "wave");
  assert.equal(localStorage.getItem("feral-density"), "s");
  assert.ok(grid().classList.contains("density-s"));
  assert.deepEqual(lit(), ["S"]);
  assert.ok(rows()[0].querySelector(".wv"));
  assert.ok(head().querySelector(".ruler"));
});
