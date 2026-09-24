// advanced.test.mjs — Popover „+ Kriterium" und Tipphilfe (ADR 0038) mit
// den Such-Kriterien aus ADR 0084 (#172): Kategorien in Sidebar-Reihenfolge,
// neu Medienart/Generator/Dauer; ein Wort, das eine Medienart GENAU trifft
// (Name, Wert, Alias), ist vorausgewählt (Enter = typ:), darunter die Zeile
// „Volltext" — Enter darauf bleibt die Textsuche.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, click, keydown, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit, record } from "./bus.mjs";

const { initAdvanced } = await import("../../src/feral/web/static/js/advanced.js");

const side = {
  models: { models: [{ model: "audiomix_v2", count: 3 }], unknown: 0, unknown_total: 0 },
  facets: {
    media_kinds: [{ typ: "bild", count: 5 }, { typ: "video", count: 1 }, { typ: "audio", count: 2 }],
    containers: [], formats: {}, megapixels: {}, years: [], undated: 0, undated_total: 0,
    loras: [], tools: [{ tool: "comfyui", count: 4 }], input_image: { mit: 0, ohne: 8 },
    fundort: null, tags: [],
  },
  ratings: { ratings: [] },
};
const q = () => document.getElementById("q");
const taRows = () => document.getElementById("typeahead").querySelectorAll(".tarow");
const rowText = (r) => `${r.querySelector(".tacat").textContent} ${r.querySelector(".talabel").textContent}`;

async function type(text) {
  q().value = text;
  q().dispatchEvent(new Event("input", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 300));   // Tipphilfe entprellt 250 ms
  await flush();
}

before(async () => {
  loadShell();
  mockApi.get("/api/sidebar", () => side);
  initAdvanced();
  emit("audio-enabled", { enabled: true });
  await flush();
});

test("Genauer Medienart-Treffer ist vorausgewählt, Enter ergibt typ:", async () => {
  await type("audio");
  const rows = taRows();
  assert.equal(rowText(rows[0]), "Medienart: Audio");
  assert.ok(rows[0].classList.contains("active"));
  assert.equal(rowText(rows[1]), "Modell: audiomix_v2");
  assert.equal(rowText(rows.at(-1)), "Volltext: audio");
  const toggles = record("chip-toggle");
  const ev = keydown("Enter", { target: q() });
  assert.ok(ev.defaultPrevented);
  assert.deepEqual(toggles[0].pred.values, [{ value: "audio", exact: false }]);
  assert.equal(toggles[0].pred.kind, "typ");
  toggles.stop();
});

test("Alias „image“ trifft Bild; „Volltext“ gewählt lässt Enter zur Textsuche durch", async () => {
  await type("image");
  assert.equal(rowText(taRows()[0]), "Medienart: Bild");
  keydown("ArrowUp", { target: q() });            // von der Vorauswahl auf „Volltext"
  assert.ok(taRows().at(-1).classList.contains("active"));
  const toggles = record("chip-toggle");
  const ev = keydown("Enter", { target: q() });
  assert.equal(ev.defaultPrevented, false);       // search.js macht den text:-Chip
  assert.equal(toggles.length, 0);
  assert.ok(document.getElementById("typeahead").hidden);
  toggles.stop();
});

test("Teilwort: keine Vorauswahl, keine Volltext-Zeile", async () => {
  await type("aud");
  const rows = taRows();
  assert.ok(rows.every((r) => !r.classList.contains("active")));
  assert.ok(rows.every((r) => !r.classList.contains("tafull")));
  assert.ok(rows.some((r) => rowText(r) === "Medienart: Audio"));
});

test("Popover: Sidebar-Reihenfolge mit Medienart, Generator und Dauer", async () => {
  const btn = document.createElement("button");
  btn.className = "crumbadd";
  document.body.appendChild(btn);
  click(btn);
  await flush();
  const pop = document.getElementById("addcrit");
  const cats = pop.querySelectorAll(".accat").map((b) => b.dataset.cat);
  assert.deepEqual(cats.slice(0, 11), ["rating", "typ", "tool", "model", "lora", "year",
                                       "container", "format", "mp", "inputimage", "fundort"]);
  assert.ok(cats.includes("dauer"));
  click(pop.querySelector('.accat[data-cat="typ"]'));
  await flush();
  assert.deepEqual(pop.querySelectorAll(".aclabel").map((l) => l.textContent), ["Bild", "Video", "Audio"]);

  click(pop.querySelector('.accat[data-cat="dauer"]'));
  await flush();
  const toggles = record("chip-toggle");
  const input = pop.querySelector(".acinput");
  input.value = ">120";
  keydown("Enter", { target: input });
  assert.deepEqual(toggles[0].pred, {
    kind: "dauer", negated: false, field: "", op: "=", values: [{ value: ">120", exact: false }],
  });
  toggles.stop();
});
