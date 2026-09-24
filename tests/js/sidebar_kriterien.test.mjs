// sidebar_kriterien.test.mjs — Such-Kriterien (ADR 0084, #172): Gruppe
// „Medienart" (vorhandene Arten, Audio nur mit Modul, Klick = typ:-Chip),
// Reihenfolge häufig → selten mit dem Sammelblock „Weitere Kriterien"
// (ab Werk zu, Zustand in localStorage) und der Aktiv-Marker „· N aktiv"
// im Kopf zugeklappter Gruppen.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, click, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit, record } from "./bus.mjs";

const { initSidebar } = await import("../../src/feral/web/static/js/sidebar.js");

const facets = {
  media_kinds: [{ typ: "bild", count: 5 }, { typ: "video", count: 0 }, { typ: "audio", count: 2 }],
  containers: [{ container: "png", count: 5 }], formats: { quadratisch: 5 }, megapixels: {},
  years: [], undated: 0, undated_total: 0, loras: [], tools: [],
  input_image: { mit: 0, ohne: 7 }, fundort: null, tags: [],
};
let audio = false;
const nav = () => document.getElementById("sidebar");
const group = (key) => nav().querySelector(`.sbgroup[data-group="${key}"]`);
const labels = (key) => group(key).querySelectorAll(".sbrow").map((r) => r.querySelector(".sblabel").textContent);
const mark = (key) => group(key).querySelector(".sbactive").textContent;
const head = (key) => [...group(key).children].find((c) => c.classList.contains("mlabel"));

before(async () => {
  localStorage.removeItem("feral-sb-more-open");
  loadShell();
  mockApi.get("/api/stats", () => ({
    total_items: 7, items_multi_location: 0, total_bytes: 1e6,
    library_configured: false, rankings: false, audio,
  }));
  mockApi.get("/api/folders", () => ({ folders: [] }));
  mockApi.get("/api/sidebar", () => ({
    models: { models: [], unknown: 0, unknown_total: 0 }, facets, ratings: { ratings: [] },
  }));
  initSidebar();
  await flush();
});

test("Reihenfolge: Bewertung · Medienart · Generator · Modell · LoRA · Jahr, darunter der Sammelblock", () => {
  const top = nav().querySelector(".sbscroll").children.map((g) => g.dataset.group);
  // Songtext (ADR 0085) steht an der Stelle der Medienart: je Ansicht ist
  // nur eine der beiden sichtbar (Geltungsbereich).
  assert.deepEqual(top, ["library", "folders", "rankings", "rating", "mediakind", "lyrics",
                         "generator", "model", "lora", "year", "more"]);
  const inner = group("more").querySelectorAll(".sbmorebody .sbgroup").map((g) => g.dataset.group);
  assert.deepEqual(inner, ["container", "format", "megapixels", "inputimage", "fundort"]);
  assert.ok(group("more").classList.contains("collapsed"), "ab Werk zugeklappt");
});

test("Medienart: Audio nur mit Modul, 0 gedimmt, Klick = typ:-Chip", async () => {
  assert.deepEqual(labels("mediakind"), ["Bild", "Video"]);
  assert.ok(group("mediakind").querySelectorAll(".sbrow")[1].classList.contains("dim"));
  const enabled = record("audio-enabled");
  audio = true;
  emit("engine-idle", {});
  await flush();
  assert.deepEqual(labels("mediakind"), ["Bild", "Video", "Audio"]);
  assert.deepEqual(enabled.at(-1), { enabled: true });
  enabled.stop();

  const toggles = record("chip-toggle");
  click(group("mediakind").querySelectorAll(".sbrow")[2]);
  assert.deepEqual(toggles[0].pred, {
    kind: "typ", negated: false, field: "", op: "=", values: [{ value: "audio", exact: false }],
  });
  toggles.stop();
});

test("Aktiv-Marker: zugeklappter Block zeigt aktive Werte, aufgeklappt die innere Gruppe", async () => {
  const fmt = { kind: "format", negated: false, field: "", op: "=", values: [{ value: "quadratisch", exact: false }] };
  emit("search-state-changed", { expression: "format: quadratisch", predicates: [fmt] });
  await flush();
  assert.equal(mark("more"), " · 1 aktiv");
  // Block auf: jetzt markiert die Zeile, der Block-Kopf schweigt.
  click(head("more"));
  assert.equal(localStorage.getItem("feral-sb-more-open"), "1");
  assert.equal(mark("more"), "");
  assert.equal(mark("format"), "");
  // Gruppe „Format" zu: ihr Kopf zeigt den aktiven Wert.
  click(head("format"));
  assert.equal(mark("format"), " · 1 aktiv");
  click(head("format"));
  click(head("more"));
  assert.equal(localStorage.getItem("feral-sb-more-open"), "0");
  // Negierter Medienart-Chip ohne eigene Zeile zählt trotzdem.
  const typ = { kind: "typ", negated: true, field: "", op: "=",
                values: [{ value: "audio", exact: false }, { value: "video", exact: false }] };
  emit("search-state-changed", { expression: "-typ: audio | video", predicates: [typ] });
  await flush();
  click(head("mediakind"));
  assert.equal(mark("mediakind"), " · 2 aktiv");
  assert.equal(mark("more"), "");
  click(head("mediakind"));
});
