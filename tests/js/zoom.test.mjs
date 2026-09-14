// zoom.test.mjs — Zoomstufe „max. 100 %" (Issue #30, ADR-0059-Nachtrag 2):
// echte Pixel, aber höchstens bildschirmfüllend. Passt das Bild bei 100 % in
// die Bühne, steht es in 100 %; sonst verhält es sich wie „Anpassen". Die Wahl
// wird wie die anderen Stufen gemerkt; Gesten starten aus der effektiven Skala.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, keydown, click, flush, item, serveLibrary } from "./harness.mjs";
import { emit } from "./bus.mjs";
import { UIEvent } from "./dom.mjs";

const { initSingleView } = await import("../../src/feral/web/static/js/singleview.js");

const items = [item(1, { width: 800, height: 600 }), item(2, { width: 4000, height: 3000 })];
const single = () => document.getElementById("single");
const stage = () => document.getElementById("svStage");
const img = () => stage().querySelector("img");
const btn = (z) => single().querySelector(`#svZoom button[data-zoom="${z}"]`);
const pct = () => single().querySelector("#svPct").textContent;

/** Bild „laden": natürliche Maße setzen und load feuern — die Bühne misst 1000×800 CSS-px. */
async function loaded(w, h) {
  stage().clientWidth = 1000; stage().clientHeight = 800;
  const el = img();
  el.naturalWidth = w; el.naturalHeight = h;
  // Gemessene Breite: Inline-Breite, sonst die CSS-„Anpassen"-Größe.
  document.rectFor = (e) => e === el
    ? { width: parseFloat(e.style.width) || Math.min(1000, 800 * (w / h)) } : null;
  el.dispatchEvent(new UIEvent("load"));
  await flush();
}

before(async () => {
  loadShell();
  serveLibrary(items);
  initSingleView();
  window.devicePixelRatio = 1;
});

async function open(i, { keep = false } = {}) {
  keydown("Escape"); await flush();
  if (!keep) localStorage.removeItem("feral-zoom");
  emit("selection-changed", { hash: items[i].file_hash, index: i });
  keydown("Enter");
  await flush();
  assert.ok(img(), "kein Bild auf der Bühne");
}

test("max. 100 %: kleines Bild steht in echten Pixeln, zentriert wie Anpassen", async () => {
  await open(0);
  click(btn("fit1"));
  await loaded(800, 600);
  assert.equal(img().style.width, "800px");
  assert.ok(stage().classList.contains("fit"), "zentriert/ohne Scrollbalken");
  assert.equal(pct(), "100 %");
  assert.ok(btn("fit1").classList.contains("active"));
  assert.equal(localStorage.getItem("feral-zoom"), "fit1");
});

test("max. 100 %: großes Bild wird wie Anpassen verkleinert", async () => {
  await open(1);
  click(btn("fit1"));
  await loaded(4000, 3000);
  assert.equal(img().style.width, "");                 // CSS-Anpassen, kein 4000px
  assert.ok(stage().classList.contains("fit"));
  assert.equal(pct(), "25 %");                         // 1000/4000 bei dpr 1
});

test("max. 100 % rechnet in Gerätepixeln: bei dpr 2 ist 100 % halb so viele CSS-Pixel", async () => {
  window.devicePixelRatio = 2;
  try {
    await open(0);
    click(btn("fit1"));
    await loaded(800, 600);
    assert.equal(img().style.width, "400px");
    assert.equal(pct(), "100 %");
  } finally { window.devicePixelRatio = 1; }
});

test("Gedächtnis: gespeichertes fit1 gilt beim nächsten Bild; Gesten starten aus der effektiven Skala", async () => {
  await open(0);
  click(btn("fit1"));
  await loaded(800, 600);
  // nächstes Bild (neu geöffnet, Gedächtnis bleibt): fit1 gilt weiter
  await open(1, { keep: true });
  await loaded(4000, 3000);
  assert.ok(btn("fit1").classList.contains("active"), "fit1 nicht gemerkt");
  assert.equal(pct(), "25 %");
  // „+" startet aus 25 % → 31 %, kein Sprung auf 125 %
  keydown("+");
  await flush();
  assert.equal(pct(), "31 %");
  assert.equal(localStorage.getItem("feral-zoom"), "fit1", "Gesten stempeln nicht");
  // Doppelklick aus fit1 heraus → 100 %
  click(btn("fit1"));
  img().dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
  await flush();
  assert.equal(img().style.width, "4000px");
});
