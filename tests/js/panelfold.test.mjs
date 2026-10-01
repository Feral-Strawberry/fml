// panelfold.test.mjs — rechtes Panel wegklappen (#219): ein fester Streifen
// am rechten Fensterrand (Muster Lightroom) und Taste P schalten um, der
// Zustand steht in localStorage und gilt beim nächsten Start. Tippen in
// Feldern und offene Vollbild-Ebenen lassen P in Ruhe. Das Detail-Panel
// rendert weggeklappt Videos nur als Poster (kein versteckter Stream).

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, keydown, click, flush, item } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit, record } from "./bus.mjs";

const { initPanelFold } = await import("../../src/feral/web/static/js/panelfold.js");
const { initDetail } = await import("../../src/feral/web/static/js/detail.js");

const folded = () => document.body.classList.contains("panel-folded");
const tab = () => document.getElementById("panelFold");
const vid = item(7, { container: "mp4", media_kind: "video" });

before(() => {
  localStorage.setItem("feral-panel-folded", "1");   // gemerkt vom letzten Start
  loadShell();
  mockApi.get(/^\/api\/item\/[0-9a-f]+$/, () => ({
    ...vid, locations: [], raw: [], interpreted: [],
    manual: { rating: null, tags: [], notes: "", model: null },
  }));
  mockApi.get("/api/tags", () => ({ tags: [] }));
  mockApi.get("/api/models", () => ({ models: [] }));
  initPanelFold();
  initDetail();
});

test("Start: gemerkter Zustand gilt; der Umschalter sitzt fest am rechten Rand", () => {
  assert.ok(folded());
  const body = document.getElementById("body");
  assert.equal(body.children.at(-1), tab(), "letztes Element der Spalten = rechter Fensterrand");
  assert.equal(tab().dataset.icon, "unfold", "Pfeil zeigt: zurückholen");
  assert.equal(tab().title, "Panel zurückholen (P)");
});

test("weggeklappt: Video im Panel nur als Poster, Aufklappen baut es wieder", async () => {
  emit("selection-changed", { hash: vid.file_hash, index: 0 });
  await flush();
  const panel = document.getElementById("panel");
  assert.equal(panel.querySelector(".ppreview video"), null, "kein Stream hinter dem Anfasser");
  assert.ok(panel.querySelector(".ppreview img.pposter"));
  const ev = record("panel-folded");
  click(tab());
  await flush();
  assert.ok(!folded());
  assert.deepEqual(ev.at(-1), { folded: false });
  assert.equal(localStorage.getItem("feral-panel-folded"), "0");
  assert.ok(panel.querySelector(".ppreview video"), "aufgeklappt wieder mit Video");
});

test("derselbe Streifen klappt wieder weg; der Trenner links vom Panel ist nur Griff", () => {
  click(document.getElementById("splitR"));
  assert.ok(!folded(), "Klick auf den Breiten-Griff schaltet nicht");
  assert.equal(tab().dataset.icon, "fold", "aufgeklappt: Pfeil zum Wegklappen");
  click(tab());
  assert.ok(folded());
  assert.equal(tab().dataset.icon, "unfold");
  assert.equal(localStorage.getItem("feral-panel-folded"), "1");
});

test("Taste P schaltet um — nicht beim Tippen, nicht über Lupe/Einzelansicht", () => {
  keydown("p");
  assert.ok(!folded());
  keydown("P");
  assert.ok(folded());
  const input = document.createElement("input");
  document.body.appendChild(input);
  keydown("p", { target: input });
  assert.ok(folded(), "im Eingabefeld ist P ein Buchstabe");
  document.getElementById("loupe").hidden = false;
  keydown("p");
  assert.ok(folded(), "über der Lupe wirkt P nicht");
  document.getElementById("loupe").hidden = true;
  keydown("p", { metaKey: true });
  assert.ok(folded(), "mit Modifier nicht");
});
