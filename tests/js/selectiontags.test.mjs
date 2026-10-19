// selectiontags.test.mjs — Tags bei Mehrfachauswahl (#303): Das Panel zeigt
// alle Tags der Auswahl, die nicht alle tragen mit Zahl („2/3"), und ✕ löst
// einen Tag bei ALLEN ausgewählten, auch wenn das Panel-Item ihn nicht hat.
// Bei Einzelauswahl bleibt es beim Einzel-Endpunkt.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, flush, item, hashOf, serveLibrary, itemDetail } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit } from "./bus.mjs";
import { DomEvent } from "./dom.mjs";

const { initDetail } = await import("../../src/feral/web/static/js/detail.js");
const { initCurate } = await import("../../src/feral/web/static/js/curate.js");

const A = hashOf(1), B = hashOf(2), C = hashOf(3);
const items = [item(1), item(2), item(3)];
const panel = () => document.getElementById("panel");
const tagsOf = { [A]: ["album"], [B]: ["album", "regenzeit"], [C]: ["album", "regenzeit"] };

function union(hashes) {
  const n = new Map();
  for (const h of new Set(hashes)) for (const t of tagsOf[h]) n.set(t, (n.get(t) || 0) + 1);
  return [...n].sort().map(([name, count]) => ({ name, count, color: null, finder: false }));
}
const chips = () => panel().querySelectorAll(".tagchip").map((c) => [
  c.textContent.replace("✕", ""), c.classList.contains("partial")]);

before(() => {
  loadShell();
  serveLibrary(items);
  mockApi.get(/^\/api\/item\/[0-9a-f]+$/, ({ path }) => {
    const h = path.split("/").pop();
    const it = items.find((x) => x.file_hash === h);
    return { ...itemDetail(it), manual: { ...itemDetail(it).manual, tags: [...tagsOf[h]] } };
  });
  mockApi.get("/api/tags", () => ({ tags: [] }));
  mockApi.get("/api/models", () => ({ models: [] }));
  mockApi.post("/api/batch/tags", ({ body }) => ({ tags: union(body.hashes), count: new Set(body.hashes).size }));
  mockApi.post("/api/batch/annotate", ({ body }) => {
    for (const h of body.hashes) tagsOf[h] = tagsOf[h].filter((t) => t !== body.remove_tag);
    return { updated: body.hashes.length,
             manual: { rating: null, tags: [...tagsOf[body.hashes[0]]], notes: "", model: null },
             tags: union(body.hashes) };
  });
  mockApi.post(/^\/api\/item\/[0-9a-f]+\/tags\/remove$/, ({ path, body }) => {
    const h = path.split("/")[3];
    tagsOf[h] = tagsOf[h].filter((t) => t !== body.name);
    return { removed: true, manual: { rating: null, tags: [...tagsOf[h]], notes: "", model: null } };
  });
  initCurate();
  initDetail();
});

test("Mehrfachauswahl: alle Tags der Auswahl, „regenzeit“ mit 2/3", async () => {
  emit("selection-changed", { hash: A, index: 0, hashes: [A, B, C] });
  await flush();
  assert.deepEqual(chips(), [["album", false], ["regenzeit2/3", true]]);
  const partial = panel().querySelectorAll(".tagchip")[1];
  assert.equal(partial.getAttribute("title"), "bei 2 von 3 ausgewählten");
  assert.equal(partial.querySelector(".tagdel").getAttribute("title"), "Tag bei allen ausgewählten entfernen");
});

test("✕ löst den Tag bei allen ausgewählten, auch ohne ihn am Panel-Item", async () => {
  const del = panel().querySelectorAll(".tagdel")[1];
  del.dispatchEvent(new DomEvent("click", { bubbles: true }));
  await flush();
  const call = mockApi.callsTo("/api/batch/annotate").at(-1);
  assert.deepEqual(call.body, { hashes: [A, B, C], remove_tag: "regenzeit" });
  assert.deepEqual(chips(), [["album", false]]);
  assert.equal(mockApi.callsTo(`/api/item/${A}/tags/remove`).length, 0);
});

test("Einzelauswahl: nur die Tags des Items, ✕ über den Einzel-Endpunkt", async () => {
  tagsOf[B] = ["album", "solo"];
  emit("selection-changed", { hash: B, index: 1, hashes: [B] });
  await flush();
  assert.deepEqual(chips(), [["album", false], ["solo", false]]);
  const before = mockApi.callsTo("/api/batch/tags").length;
  panel().querySelectorAll(".tagdel")[1].dispatchEvent(new DomEvent("click", { bubbles: true }));
  await flush();
  assert.equal(mockApi.callsTo(`/api/item/${B}/tags/remove`).length, 1);
  assert.equal(mockApi.callsTo("/api/batch/tags").length, before, "keine Auswahl-Abfrage bei einem Item");
  assert.deepEqual(chips(), [["album", false]]);
});
