// listcompare.test.mjs — Vergleichen in der Liste (A7 #164, ADR 0089): C bzw.
// der Knopf engt die Audioliste auf 2 bis 6 markierte Songs ein, vergrößert,
// mit eigenem Lautheitsangleich (Standard an); Bewerten und Ablehnen treffen
// nur die aktuelle Zeile; Esc bringt die volle Liste an derselben Stelle
// zurück, ohne die Filter zurückzusetzen.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, keydown, click, flush, item, hashOf, serveLibrary } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit, record } from "./bus.mjs";

localStorage.setItem("feral-view", "audio");
localStorage.setItem("feral-audio-match", "0");   // gemerkt: original

const { initAudioList } = await import("../../src/feral/web/static/js/audiolist.js");
const { initLibraryView } = await import("../../src/feral/web/static/js/libview.js");
const { initGallery, listComparing } = await import("../../src/feral/web/static/js/gallery.js");
const { initSearch } = await import("../../src/feral/web/static/js/search.js");
const { initCurate } = await import("../../src/feral/web/static/js/curate.js");
const { initCompare } = await import("../../src/feral/web/static/js/compare.js");
const { matchOn } = await import("../../src/feral/web/static/js/player.js");
const { stackLevels } = await import("../../src/feral/web/static/js/comments.js");

const songs = Array.from({ length: 10 }, (_, k) => item(k + 1, {
  media_kind: "audio", container: "mp3", width: null, height: null, duration: 120 + k * 10,
  name: `suno_kandidat_${k + 1}.mp3`, tool: "suno",
}));
const grid = () => document.getElementById("grid");
const rows = () => grid().querySelectorAll(".arow");
const hashesShown = () => rows().map((r) => r.dataset.hash);
const btn = () => document.getElementById("listCmpBtn");
const wrap = () => document.getElementById("gridwrap");
let lib;

before(async () => {
  loadShell();
  lib = serveLibrary(songs);
  mockApi.get("/api/stats", () => ({ total_items: 10, items_multi_location: 0, total_bytes: 1e6,
    library_configured: false, rankings: false, audio: true }));
  mockApi.get("/api/folders", () => ({ folders: [] }));
  mockApi.post("/api/filter/build", ({ body }) => ({ expression: "", predicates: body.predicates, sort: null }));
  mockApi.post(/^\/api\/item\/[0-9a-f]+\/rating$/, ({ body }) =>
    ({ manual: { rating: body.rating || null, tags: [], notes: "", model: null } }));
  mockApi.post("/api/batch/apply", ({ body }) => {
    lib.items = lib.items.filter((it) => !body.hashes.includes(it.file_hash));
    return { matched: body.hashes.length, rejected: body.hashes.length };
  });
  document.rectFor = (el) => (el.classList.contains("tile") ? { height: 65 } : null);
  wrap().clientHeight = 2000;
  initLibraryView();
  initGallery();
  initSearch();
  initCurate();
  initCompare();
  initAudioList();
  await flush(10);
});

const mark = (...ns) => emit("selection-changed",
  { hash: hashOf(ns[0]), index: ns[0] - 1, hashes: ns.map(hashOf) });

test("Knopf erscheint ab 2 markierten Songs, über 6 gesperrt; C tut dann nichts", async () => {
  mark(1);
  assert.equal(btn().hidden, true);
  mark(1, 2, 3, 4, 5, 6, 7);
  assert.equal(btn().hidden, false);
  assert.equal(btn().disabled, true);
  keydown("c");
  await flush();
  assert.equal(listComparing(), 0);
  assert.equal(rows().length, 10);
});

test("C engt die Liste auf die markierten Songs ein, vergrößert, angeglichen, EINE Auswahl", async () => {
  mark(2, 4, 5, 7, 8, 9);
  wrap().scrollTop = 130;   // nach dem Markieren (das scrollt die Auswahl ins Bild)
  assert.match(btn().textContent, /\(6\)/);
  const sel = record("selection-changed");
  keydown("C");
  await flush();
  assert.equal(listComparing(), 6);
  assert.deepEqual(hashesShown(), [2, 4, 5, 7, 8, 9].map(hashOf));   // Reihenfolge der Liste
  assert.ok(grid().classList.contains("compare"));
  assert.ok(grid().classList.contains("pinlabels"));
  assert.ok(document.body.classList.contains("list-compare"), "Abspielleiste ausgeblendet");
  assert.equal(document.querySelector("#listhead .cmpnote").hidden, false);
  assert.equal(document.getElementById("playAllBtn").hidden, true);
  assert.equal(document.getElementById("listCmpEnd").hidden, false);
  assert.equal(btn().hidden, true);
  assert.equal(matchOn(), true, "im Vergleich standardmäßig angeglichen");
  assert.equal(localStorage.getItem("feral-audio-match"), "0", "gemerkte Einstellung bleibt");
  assert.deepEqual(sel.at(-1), { hash: hashOf(2), index: 0 });
  sel.stop();
});

test("1–5 bewertet nur die aktuelle Zeile, nicht alle Verglichenen", async () => {
  emit("selection-changed", { hash: hashOf(5), index: 2 });
  mockApi.calls.length = 0;
  keydown("4");
  await flush();
  const posts = mockApi.calls.filter((c) => c.method === "POST");
  assert.equal(posts.length, 1);
  assert.equal(posts[0].path, `/api/item/${hashOf(5)}/rating`);
});

test("Ablehnen nimmt den Song aus dem Vergleich, die nächste Zeile rückt nach", async () => {
  keydown("Delete");
  click(document.querySelector("#rejectdlg .rejgo"));
  await flush();
  assert.deepEqual(hashesShown(), [2, 4, 7, 8, 9].map(hashOf));
  assert.equal(listComparing(), 5);
  emit("selection-changed", { hash: hashOf(9), index: 4 });
  keydown("Delete");
  click(document.querySelector("#rejectdlg .rejgo"));
  await flush();
  assert.deepEqual(hashesShown(), [2, 4, 7, 8].map(hashOf));
  assert.equal(document.getElementById("listhead").querySelector(".cmpnote b").textContent.includes("4"), true);
});

test("Esc: volle Liste an derselben Stelle, Filter bleiben, der Rest bleibt markiert", async () => {
  const search = record("search-state-changed");
  const sel = record("selection-changed");
  emit("selection-changed", { hash: hashOf(7), index: 2 });
  keydown("Escape");
  await flush(10);
  assert.equal(listComparing(), 0);
  assert.equal(search.length, 0, "Esc setzt im Vergleich keine Filter zurück");
  assert.ok(!grid().classList.contains("compare"));
  assert.ok(!document.body.classList.contains("list-compare"), "Abspielleiste wieder da");
  assert.equal(wrap().scrollTop, 130);
  assert.equal(matchOn(), false, "gemerkte Einstellung kehrt zurück");
  assert.equal(rows().length, 8, "Abgelehntes ist nach dem Nachladen weg");
  const last = sel.at(-1);
  assert.equal(last.hash, hashOf(7));
  assert.deepEqual([...last.hashes].sort(), [2, 4, 7, 8].map(hashOf).sort());
  assert.equal(btn().hidden, false, "C vergleicht die übrigen erneut");
  search.stop();
  sel.stop();
});

test("neue Suche beendet den Vergleich ohne Rückweg", async () => {
  mark(1, 2);
  click(btn());
  await flush();
  assert.equal(listComparing(), 2);
  emit("search-state-changed", { predicates: [], expression: "", sort: null });
  await flush(10);
  assert.equal(listComparing(), 0);
  assert.equal(rows().length, 8);
});

test("Beschriftungen, die sich überdecken, stapeln sich; freie bleiben unten", () => {
  assert.deepEqual(stackLevels([[0, 80], [40, 120], [200, 260], [90, 150]]), [0, 1, 0, 0]);
  assert.deepEqual(stackLevels([[0, 50], [10, 60], [20, 70], [30, 80], [40, 90]]), [0, 1, 2, 3, 3]);
  assert.deepEqual(stackLevels([]), []);
});
