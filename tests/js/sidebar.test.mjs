// sidebar.test.mjs — Facette „Generator" (Issue #43, ADR 0066): die Gruppe
// rendert alle tool-Werte aus /api/sidebar (facets) mit Anzeigename und Zähler,
// 0-Einträge gedimmt statt versteckt (Block S4), und ein Klick erzeugt
// AUSSCHLIESSLICH ein 'chip-toggle' mit exaktem tool:-Prädikat (ADR 0035 —
// keine zweite Zustandslogik in der Sidebar).

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, click, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit, record } from "./bus.mjs";

const { initSidebar } = await import("../../src/feral/web/static/js/sidebar.js");

const facets = {
  containers: [], formats: {}, megapixels: {}, years: [], undated: 0, undated_total: 0,
  loras: [], input_image: { mit: 0, ohne: 3 }, fundort: null, tags: [],
  tools: [
    { tool: "comfyui", count: 2 },
    { tool: "google", count: 1 },
    { tool: "c2pa", count: 0 },
    { tool: "fancy-engine", count: 1 },     // unbekannter Wert → roh anzeigen
  ],
};

// /api/sidebar (#99): {models, facets, ratings} aus einem Request — die
// Tests tauschen je Fall nur den betroffenen Teil.
const side = { models: { models: [], unknown: 0, unknown_total: 0 }, facets, ratings: { ratings: [] } };
const mockSidebar = (over = {}) => mockApi.get("/api/sidebar", () => ({ ...side, ...over }));

const toolsBox = () => document.getElementById("sbTools");
const rows = () => toolsBox().querySelectorAll(".sbrow");

before(async () => {
  loadShell();
  mockApi.get("/api/stats", () => ({
    total_items: 3, items_multi_location: 0, total_bytes: 1e6,
    library_configured: false, rankings: false,
  }));
  mockApi.get("/api/folders", () => ({ folders: [] }));
  mockSidebar();
  initSidebar();
  await flush();
});

test("Gruppe „Generator' listet alle tool-Werte mit Anzeigename, Zähler und Rohwert im Tooltip", () => {
  const labels = rows().map((r) => r.querySelector(".sblabel").textContent);
  // Kontext-Sortierung (Konzeptrunde 2026-09-08): Treffer zuerst, die im
  // Kontext leere Zeile rutscht unter die Trennzeile „keine Treffer mit diesem Filter".
  assert.deepEqual(labels, ["ComfyUI", "Google", "fancy-engine", "(C2PA, nicht zugeordnet)"]);
  assert.deepEqual(rows().map((r) => r.querySelector(".sbcount").textContent), ["2", "1", "1", "0"]);
  // Tooltip: Grammatik + Tastenhinweis fürs ODER. Node kennt navigator.platform
  // des Rechners (Mac hier, Windows bei Feral Strawberry) — deshalb beide Tasten erlaubt;
  // die Zuordnung Plattform → Taste prüft der eigene Test unten.
  assert.deepEqual(rows().map((r) => r.getAttribute("title").split(" · ")[0]),
    ["tool: comfyui", "tool: google", "tool: fancy-engine", "tool: c2pa"]);
  assert.ok(rows().every((r) => /(⌘|Strg)-Klick: hinzufügen \(ODER\)$/.test(r.getAttribute("title"))));
  assert.match(toolsBox().querySelector(".sbctx").textContent, /keine Treffer mit diesem Filter · 1 Generatoren/);
});

test("0 im Kontext = gedimmt, aber klickbar (nicht versteckt)", () => {
  const dimmed = rows().filter((r) => r.classList.contains("dim"));
  assert.equal(dimmed.length, 1);
  assert.equal(dimmed[0].getAttribute("title").split(" · ")[0], "tool: c2pa");
});

test("Klick auf einen Generator erzeugt genau ein chip-toggle mit exaktem tool:-Prädikat", async () => {
  const toggles = record("chip-toggle");
  const loads = record("state-load");
  click(rows()[1].querySelector(".sblabel"));
  await flush();
  assert.equal(toggles.length, 1);
  assert.deepEqual(toggles[0].pred, {
    kind: "field", negated: false, field: "tool", op: "=",
    values: [{ value: "google", exact: true }],
  });
  assert.equal(loads.length, 0);
  toggles.stop(); loads.stop();
});

test("Suchzustand geht als ?filter= an /api/sidebar — EIN Request für alle Zähler (ADR 0037, #99)", async () => {
  mockApi.calls.length = 0;
  emit("search-state-changed", { expression: 'tool: "gemini"', predicates: [], sort: null });
  await new Promise((r) => setTimeout(r, 300));   // Entprellung (250 ms) abwarten
  await flush();
  const call = mockApi.callsTo("/api/sidebar").at(-1);
  assert.ok(call, "kein Zähler-Refresh nach search-state-changed");
  assert.equal(call.params.get("filter"), 'tool: "gemini"');
  for (const old of ["/api/models", "/api/facets", "/api/ratings"]) {
    assert.equal(mockApi.callsTo(old).length, 0, `${old} wird von der Sidebar nicht mehr geholt`);
  }
});

test("Gruppe „Generator' steht ÜBER „Nach Modell' (grob vor fein), Modell-Liste sortiert im Kontext", async () => {
  const groups = [...document.querySelectorAll("#sidebar .sbgroup[data-group]")].map((g) => g.dataset.group);
  assert.ok(groups.indexOf("generator") < groups.indexOf("model"), `Reihenfolge: ${groups.join(",")}`);
  assert.ok(groups.indexOf("rating") < groups.indexOf("generator"));
  mockSidebar({ models: {
    models: [{ model: "flux1-dev", count: 0 }, { model: "sdxl", count: 3 }, { model: "wan2.2", count: 0 }],
    unknown: 0, unknown_total: 0,
  } });
  emit("engine-idle");
  await flush();
  const box = document.getElementById("sbModels");
  assert.deepEqual([...box.querySelectorAll(".sbrow")].map((r) => r.querySelector(".sblabel").textContent),
    ["sdxl", "flux1-dev", "wan2.2"]);
  assert.equal(box.querySelectorAll(".sbctx").length, 1);
  mockSidebar();
});

test("ohne tool-Werte steht der Leerhinweis in der Gruppe", async () => {
  mockSidebar({ facets: { ...facets, tools: [] } });
  emit("engine-idle");
  await flush();
  assert.equal(rows().length, 0);
  assert.match(toolsBox().textContent, /Kein Generator erkannt/);
});

test("Tastenhinweis nennt die Taste der Plattform: ⌘ auf dem Mac, sonst Strg", async () => {
  const { modKey } = await import("../../src/feral/web/static/js/sidebar.js");
  assert.equal(modKey("MacIntel"), "⌘");
  assert.equal(modKey("macOS"), "⌘");        // userAgentData.platform
  assert.equal(modKey("iPad"), "⌘");
  assert.equal(modKey("Win32"), "Strg");
  assert.equal(modKey("Windows"), "Strg");
  assert.equal(modKey("Linux x86_64"), "Strg");
  assert.equal(modKey(""), "Strg");          // unbekannt → die häufigere Taste
  const heading = document.querySelector('#sidebar .sbgroup[data-group="generator"] > .mlabel');
  assert.match(heading.getAttribute("title"), /(⌘|Strg)-Klick fügt hinzu \(ODER\)/);
});

test("Ersthinweis: Klick, der eine andere Auswahl der Gruppe ersetzt, zeigt „Auswahl ersetzt · …-Klick fügt hinzu' (max. dreimal)", async () => {
  localStorage.removeItem("feral-or-hint-shown");
  mockSidebar();     // der Leerhinweis-Test davor hat die Gruppe geleert
  emit("engine-idle");
  await flush();
  const group = document.querySelector('#sidebar .sbgroup[data-group="generator"]');
  const rowOf = (tool) => group.querySelector(`.sbrow[data-akey="field:tool:${tool}"]`);
  const hasHint = () => !!group.querySelector(".sbhint");   // boolesch: assert soll nie DOM-Knoten ausgeben
  const state = (tool) => emit("search-state-changed", {
    expression: `tool: ${tool}`, sort: null,
    predicates: [{ kind: "field", negated: false, field: "tool", op: "=", values: [{ value: tool, exact: true }] }],
  });
  // Nichts aktiv → Klick ersetzt nichts → kein Hinweis.
  emit("search-state-changed", { expression: "", predicates: [], sort: null });
  click(rowOf("google"));
  assert.equal(hasHint(), false);
  // google aktiv, Klick auf comfyui ersetzt → Hinweis mit der Zusatztaste …
  state("google");
  click(rowOf("comfyui"));
  assert.equal(hasHint(), true, "Hinweis fehlt");
  assert.match(group.querySelector(".sbhint").textContent, /^Auswahl ersetzt · (⌘|Strg)-Klick fügt hinzu \(ODER\)$/);
  assert.equal(localStorage.getItem("feral-or-hint-shown"), "1");
  // … DIREKT unter der geklickten Zeile, nicht am Gruppenende.
  assert.equal(rowOf("comfyui").nextSibling === group.querySelector(".sbhint"), true);
  // Die Liste wird nach dem Klick neu gezeichnet: der Hinweis wandert mit.
  emit("engine-idle");
  await flush();
  assert.equal(hasHint(), true, "Hinweis hat die Neuzeichnung nicht überlebt");
  assert.equal(rowOf("comfyui").nextSibling === group.querySelector(".sbhint"), true);
  // Klick auf den aktiven Wert (= entfernen) lehrt nichts und räumt den Hinweis weg.
  click(rowOf("google"));
  assert.equal(hasHint(), false);
  // Cmd/Strg-Klick lehrt nichts.
  click(rowOf("comfyui"), { ctrlKey: true });
  assert.equal(hasHint(), false);
  // Nach drei Malen ist Schluss.
  localStorage.setItem("feral-or-hint-shown", "3");
  click(rowOf("comfyui"));
  assert.equal(hasHint(), false);
  localStorage.removeItem("feral-or-hint-shown");
});
