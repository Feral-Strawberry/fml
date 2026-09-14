// rankings_deeplink.test.mjs — Sprung aus dem Admin (Rankings → „Bearbeiten"
// je Zeile, #133): /?ranking=ID lädt das Ranking beim Start wie per ✎ in den
// Bearbeiten-Modus der Galerie ('state-load' mit arena) und räumt den
// Parameter aus der Adresszeile.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { record } from "./bus.mjs";

let loads;
before(async () => {
  loadShell();
  mockApi.get("/api/rankings", () => ({ rankings: [{ id: 7, name: "Arena A", expression: "tag: x", duels: 0 }] }));
  globalThis.location.search = "?ranking=7";
  globalThis.location.pathname = "/";
  loads = record("state-load");
  const { initRankings } = await import("../../src/feral/web/static/js/rankings.js");
  initRankings();
  await flush();
});

test("?ranking=ID lädt das Ranking in den Bearbeiten-Modus und räumt die Adresszeile", () => {
  assert.deepEqual(loads.at(-1), { expression: "tag: x", label: "Arena A", arena: { id: 7, name: "Arena A" } });
  assert.equal(globalThis.location.pathname, "/");
  assert.equal(mockApi.callsTo("/api/rankings").length, 1);
});
