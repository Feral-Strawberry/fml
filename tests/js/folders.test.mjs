// folders.test.mjs — Smart Folders in der Sidebar: „Liste vor Zahlen" (Issue
// #69, ADR 0071). Die Liste erscheint sofort aus dem ersten Aufruf
// (?counts=0, Zähler „…"), die Zähler kommen mit dem zweiten Aufruf nach;
// ein älterer, überholter Ladevorgang darf fertige Zahlen nicht mehr
// überschreiben.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit } from "./bus.mjs";

const { initSidebar } = await import("../../src/feral/web/static/js/sidebar.js");

const FOLDERS = [
  { id: 1, name: "PNGs", expression: "container: png" },
  { id: 2, name: "Kaputt", expression: "unbekannt:: (" },
];
const counted = () => ({ folders: [
  { ...FOLDERS[0], count: 1234, error: null },
  { ...FOLDERS[1], count: null, error: { key: "errFilterSyntax" } },
] });

const rows = () => [...document.getElementById("sbFolders").querySelectorAll(".sbrow")];
const counts = () => rows().map((r) => r.querySelector(".sbcount").textContent);

let countsGate;
before(async () => {
  loadShell();
  mockApi.get("/api/stats", () => ({
    total_items: 3, items_multi_location: 0, total_bytes: 1e6,
    library_configured: false, rankings: false,
  }));
  mockApi.get("/api/sidebar", () => ({      // alle Zähler aus einem Request (#99)
    models: { models: [], unknown: 0, unknown_total: 0 },
    ratings: { ratings: [] },
    facets: {
      containers: [], formats: {}, megapixels: {}, years: [], undated: 0, undated_total: 0,
      loras: [], input_image: { mit: 0, ohne: 3 }, fundort: null, tags: [], tools: [],
    },
  }));
  // counts=0 antwortet sofort mit der nackten Liste; der Zähler-Aufruf
  // wartet am Tor, bis der Test ihn öffnet.
  mockApi.get("/api/folders", async ({ params }) => {
    if (params.get("counts") === "0") return { folders: FOLDERS };
    await countsGate.promise;
    return counted();
  });
  countsGate = mockApi.gate();
  initSidebar();
  await flush();
});

test('Liste steht mit „…" bevor die Zähler da sind; danach Zahl bzw. ⚠', async () => {
  assert.deepEqual(rows().map((r) => r.querySelector(".sblabel").textContent), ["PNGs", "Kaputt"]);
  assert.deepEqual(counts(), ["…", "…"]);
  const calls = mockApi.callsTo("/api/folders");
  assert.deepEqual(calls.map((c) => c.params.get("counts")), ["0", null]);
  countsGate.open();
  await flush();
  assert.deepEqual(counts(), ["1.234", "⚠"]);
  assert.match(rows()[1].getAttribute("title"), /unbekannt:: \(/);
});

test("überholter Ladevorgang überschreibt fertige Zahlen nicht", async () => {
  // Zwei Auslöser kurz nacheinander (engine-idle + folders-changed): nur der
  // jüngste zeichnet; die Liste des älteren („…") darf die Zahlen des
  // jüngeren nicht mehr zurücksetzen.
  const slowGate = mockApi.gate();
  mockApi.get("/api/folders", async ({ params }) => {
    if (params.get("counts") === "0") { await slowGate.promise; return { folders: FOLDERS }; }
    return counted();
  });
  emit("engine-idle", {});            // Aufruf 1: Liste hängt am Tor
  await flush();
  mockApi.get("/api/folders", async ({ params }) =>
    params.get("counts") === "0" ? { folders: FOLDERS } : counted());
  emit("folders-changed", {});        // Aufruf 2: läuft sofort durch
  await flush();
  assert.deepEqual(counts(), ["1.234", "⚠"]);
  slowGate.open();                    // Aufruf 1 kommt verspätet zurück
  await flush();
  assert.deepEqual(counts(), ["1.234", "⚠"]);
});

test("geladene Suche leuchtet, solange die Chips ihr entsprechen (#133)", async () => {
  const active = () => rows().map((r) => r.classList.contains("active"));
  emit("state-load", { expression: "container: png", label: "PNGs", folder: { id: 1, name: "PNGs" } });
  emit("search-state-changed", { expression: "container: png", canonical: "container: png", predicates: [], sort: null });
  assert.deepEqual(active(), [true, false]);
  emit("folders-changed", {});          // Neuzeichnen der Liste behält die Markierung
  await flush();
  assert.deepEqual(active(), [true, false]);
  emit("search-state-changed", { expression: "container: png year: 2026", canonical: "container: png year: 2026", predicates: [], sort: null });
  assert.deepEqual(active(), [false, false], "geänderte Chips = freie Suche");
  emit("search-state-changed", { expression: "container: png", canonical: "container: png", predicates: [], sort: null });
  assert.deepEqual(active(), [true, false], "zurück auf den gespeicherten Stand");
  emit("folder-origin", { id: 2, name: "Kaputt", expression: "container: png" });
  assert.deepEqual(active(), [false, true], "gerade gespeichert/überschrieben = Ursprung");
  emit("state-clear", {});
  assert.deepEqual(active(), [false, false]);
});
