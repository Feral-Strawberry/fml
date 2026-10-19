// locationrows.test.mjs — Fundort-Zeilen und Ordnergruppen der Audioliste
// (ADR 0108 + Nachtrag, #295): in „Angaben" Standard „Nach Ordnern", Wahl
// über ☰▾ (nur aktiv; nach Ordnern / je Fundort / je Song), ?rows= an den Server,
// Ordnerköpfe als eigene Zeilen (Segment öffnet den Ordner, ⌕ setzt den
// Chip), Auswahl je Song, ↑/↓ überspringen Köpfe, Welle ohne Fundort-Zeilen.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, click, keydown, flush, item, hashOf } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { record } from "./bus.mjs";

localStorage.setItem("feral-view", "audio");
localStorage.setItem("feral-liststyle", "info");

const { initAudioList, folderSegments, groupRowHtml } = await import("../../src/feral/web/static/js/audiolist.js");
const { initLibraryView } = await import("../../src/feral/web/static/js/libview.js");
const { initGallery } = await import("../../src/feral/web/static/js/gallery.js");

const song = (n, extra) => item(n, { media_kind: "audio", container: "mp3", width: null, height: null,
                                     duration: 120, tool: null, ...extra });
const A = song(1, { name: "a.mp3", title: "Alpha" });
const B = song(2, { name: "b.mp3", title: "Beta" });
const loc = (id, path, kind, count = 1, skip = 0) => ({ id, path, kind, count, skip });
const head = (kind, path, count, skip = 0) => ({ group: { kind, path, count, skip } });
const GROUPED = [
  head("watch", "/Volumes/Musik/Kiss", 1, 9),
  { ...A, loc: loc(1, "/Volumes/Musik/Kiss/a.mp3", "watch", 2, 9) },
  head("watch", "/Volumes/Musik/Kiss/Demos", 2, 9),
  { ...A, name: "a (Kopie).mp3", loc: loc(2, "/Volumes/Musik/Kiss/Demos/a (Kopie).mp3", "watch", 2, 9) },
  { ...B, loc: loc(3, "/Volumes/Musik/Kiss/Demos/b.mp3", "watch", 1, 9) },
];

const grid = () => document.getElementById("grid");
const rows = () => grid().querySelectorAll(".arow");
const infoBtn = () => document.querySelector('#density [data-liststyle="info"]');
// ▾ ist immer da (hält den Platz), sichtbar nur in „Angaben".
const caretShown = () => !infoBtn().querySelector(".caret").classList.contains("off");
const menuRow = (key) => document.querySelector(`#rowsmenu .sortrow[data-rows="${key}"]`);
const itemCalls = () => mockApi.callsTo("/api/items").filter((c) => c.path === "/api/items");

before(async () => {
  loadShell();
  mockApi.get("/api/items", ({ params }) => {
    const mode = params.get("rows");
    const list = mode === "ordner" ? GROUPED : mode === "fundorte" ? GROUPED.filter((e) => !e.group) : [A, B];
    return { total: list.length, offset: 0, items: list,
             ...(mode ? { songs: 2, locations: 3 } : {}) };
  });
  mockApi.get("/api/items/position", () => ({ index: null }));
  mockApi.get("/api/stats", () => ({ total_items: 2, audio: true }));
  mockApi.get(/^\/api\/item\/[0-9a-f]+$/, () => ({ ...A, locations: [], raw: [], interpreted: [] }));
  mockApi.post(/^\/api\/item\/[0-9a-f]+\/open$/, () => ({ ok: true }));
  document.rectFor = (el) => (el.classList.contains("tile") ? { height: 35 } : null);
  document.getElementById("gridwrap").clientHeight = 1000;
  // Die Liste hat EINE Spalte (das CSS fehlt der Attrappe): ↑/↓ = eine Zeile.
  const style = globalThis.getComputedStyle;
  globalThis.getComputedStyle = (el) => ({ ...style(el), gridTemplateColumns: "1px" });
  initLibraryView();
  initGallery();
  initAudioList();
  await flush(10);
});

test("Ordner-Segmente: Wurzel weggelassen, Laufwerk mit Trenner, gemeinsamer Anfang abgedunkelt", () => {
  assert.deepEqual(folderSegments("/Volumes/Musik/Kiss", 9).map((s) => [s.text, s.path]),
    [["Musik", "/Volumes/Musik"], ["Kiss", "/Volumes/Musik/Kiss"]]);
  assert.deepEqual(folderSegments("D:\\Suno\\x").map((s) => s.path), ["D:\\", "D:\\Suno", "D:\\Suno\\x"]);
  const html = groupRowHtml(GROUPED[2].group, GROUPED[0].group);
  const box = document.createElement("div");
  box.innerHTML = html;
  assert.deepEqual(box.querySelectorAll("a.seg").map((a) => a.classList.contains("pre")), [true, true, false]);
});

test("Standard in „Angaben“ ist „Nach Ordnern“: rows=ordner, Köpfe als eigene Zeilen", () => {
  assert.equal(caretShown(), true);
  assert.equal(itemCalls().at(-1).params.get("rows"), "ordner");
  const r = rows();
  assert.equal(r.length, 5);
  assert.deepEqual(r.map((el) => el.classList.contains("agroup")), [true, false, true, false, false]);
  assert.equal(r[0].querySelector(".gcount").textContent, "1");
  assert.equal(r[3].querySelector(".rname b").textContent, "Alpha");
  assert.equal(r[3].querySelector(".rlocs").textContent, "⧉2");
  assert.equal(r[4].querySelector(".rlocs"), null);
  // Das Sortiermenü bleibt reine Sortierung.
  click(document.getElementById("sort"));
  assert.equal(document.querySelector("#sortmenu [data-rows]"), null);
  click(document.getElementById("sort"));
});

test("☰▾ öffnet die Zeilen-Arten; „Je Song“ lädt ohne rows, gemerkt; „Nach Ordnern“ zurück", async () => {
  click(infoBtn());
  assert.deepEqual(document.querySelectorAll("#rowsmenu .sortrow").map((b) => b.dataset.rows),
    ["ordner", "fundorte", "songs"]);
  assert.equal(menuRow("ordner").classList.contains("active"), true);
  mockApi.calls.length = 0;
  click(menuRow("songs"));
  await flush(10);
  assert.equal(document.getElementById("rowsmenu").hidden, true);
  assert.equal(itemCalls().at(-1).params.get("rows"), null);
  assert.equal(localStorage.getItem("feral-listrows"), "songs");
  assert.equal(rows().length, 2);
  click(infoBtn());
  click(menuRow("ordner"));
  await flush(10);
  assert.equal(itemCalls().at(-1).params.get("rows"), "ordner");
  assert.equal(rows().length, 5);
});

test("Klick auf eine Zeile wählt den Song: alle seine Zeilen leuchten; Köpfe nie", async () => {
  click(rows()[1].querySelector(".rname"));
  await flush();
  assert.deepEqual(rows().map((el) => el.classList.contains("selected")), [false, true, false, true, false]);
});

test("↑/↓ überspringen Ordnerköpfe", async () => {
  const seen = record("selection-changed");
  keydown("ArrowDown");
  await flush();
  assert.deepEqual(seen.map((d) => d.index), [3]);           // Kopf an Index 2 übersprungen
  keydown("ArrowUp");
  await flush();
  assert.deepEqual(seen.map((d) => d.index), [3, 1]);
  seen.stop();
});

test("Segment im Kopf öffnet den Ordner über einen Song der Gruppe; ⌕ setzt ordner:", async () => {
  mockApi.calls.length = 0;
  click(rows()[2].querySelectorAll("a.seg")[1]);
  await flush();
  const open = mockApi.calls.find((c) => c.path.endsWith("/open"));
  assert.equal(open.path, `/api/item/${hashOf(1)}/open`);
  assert.deepEqual(open.body, { path: "/Volumes/Musik/Kiss", what: "folder" });
  const toggles = record("chip-toggle");
  click(rows()[2].querySelector(".gfilter"));
  assert.equal(toggles.length, 1);
  assert.equal(toggles[0].additive, false);
  assert.deepEqual(toggles[0].pred.values, [{ value: "/Volumes/Musik/Kiss/Demos", exact: true }]);
  assert.equal(toggles[0].pred.kind, "ordner");
  toggles.stop();
});

test("In „Welle“ steht nur ☰: ein Klick schaltet auf „Angaben“ statt das Menü zu öffnen", async () => {
  mockApi.calls.length = 0;
  click(document.querySelector('#density [data-density="m"]'));
  await flush(10);
  assert.equal(itemCalls().at(-1).params.get("rows"), null);
  assert.equal(rows().length, 2);
  assert.equal(caretShown(), false);
  mockApi.calls.length = 0;
  click(infoBtn());
  await flush(10);
  assert.equal(document.getElementById("rowsmenu").hidden, true);
  assert.equal(caretShown(), true);
  assert.equal(itemCalls().at(-1).params.get("rows"), "ordner");
});
