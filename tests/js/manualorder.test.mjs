// manualorder.test.mjs — Sortierung der Audioliste: „Manuell" (#218, ADR 0095)
// nur mit offener gespeicherter Suche, deren Chips unverändert stehen (eine
// andere Suche schließt sie und räumt den manual-Chip; Alt+↓ schickt den
// Nachbarn an den Server, der Listenkopf erklärt die Bedienung) — und der
// Album-Standard bei Album-Chip (#224), den eine ausdrückliche Wahl schlägt.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, keydown, flush, item, serveLibrary } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit, record } from "./bus.mjs";

localStorage.setItem("feral-view", "audio");

const { initAudioList } = await import("../../src/feral/web/static/js/audiolist.js");
const { initLibraryView } = await import("../../src/feral/web/static/js/libview.js");
const { initGallery } = await import("../../src/feral/web/static/js/gallery.js");
const { initSearch } = await import("../../src/feral/web/static/js/search.js");
const { initCurate } = await import("../../src/feral/web/static/js/curate.js");

const songs = Array.from({ length: 4 }, (_, k) => item(k + 1, {
  media_kind: "audio", container: "mp3", width: null, height: null, duration: 100,
  name: `song_${k + 1}.mp3`,
}));
const wrap = () => document.getElementById("gridwrap");
const note = () => document.querySelector("#listhead .manualnote");
const sortKeys = () => {
  document.getElementById("sort").dispatchEvent(new MouseEvent("click", { bubbles: true }));
  const keys = document.querySelectorAll("#sortmenu .sortrow").map((b) => b.dataset.key);
  document.getElementById("sort").dispatchEvent(new MouseEvent("click", { bubbles: true }));
  return keys;
};

// Grammatik-Attrappe: „tag: X" und optional „sort: manual".
const tagPred = (v) => ({ kind: "tag", negated: false, field: "", op: "=", values: [{ value: v, exact: false }] });
const sortPred = (v) => ({ kind: "sort", negated: false, field: "", op: "=", values: [{ value: v, exact: false }] });
function state(preds) {
  const sort = preds.find((p) => p.kind === "sort")?.values[0].value ?? null;
  const expression = preds.map((p) => `${p.field || p.kind}: ${p.values[0].value}`).join(" ");
  return { expression, predicates: preds, sort };
}

before(async () => {
  loadShell();
  serveLibrary(songs);
  mockApi.get("/api/filter/parse", ({ params }) => {
    const expr = params.get("expr");
    const album = expr.match(/album: (\w+)/);
    const preds = album
      ? [{ kind: "field", negated: false, field: "album", op: "=", values: [{ value: album[1], exact: true }] }]
      : [tagPred(expr.match(/tag: (\w+)/)[1])];
    if (expr.includes("sort: manual")) preds.push(sortPred("manual"));
    return state(preds);
  });
  mockApi.post("/api/filter/build", ({ body }) => state(body.predicates));
  mockApi.post("/api/folders/3/order", () => ({ index: 1 }));
  document.rectFor = (el) => (el.classList.contains("tile") ? { height: 65 } : null);
  wrap().clientHeight = 2000;
  initLibraryView();
  initGallery();
  initSearch();
  initCurate();
  initAudioList();
  await flush(10);
});

test("ohne gespeicherte Suche kein ‚Manuell‘, Album gibt es in der Audioansicht", () => {
  const keys = sortKeys();
  assert.ok(keys.includes("album"));
  assert.ok(!keys.includes("manual"));
});

test("offene Suche: Manuell wählbar, Hinweis sichtbar, Alt+↓ schickt den Nachbarn", async () => {
  emit("state-load", { expression: "tag: rc", folder: { id: 3, name: "Playlist" } });
  await flush(10);
  assert.ok(sortKeys().includes("manual"));
  emit("sort-changed", { sort: "manual" });
  await flush(10);
  assert.equal(note().hidden, false, "Bedienhinweis im Listenkopf");
  const last = mockApi.callsTo("/api/items").at(-1);
  assert.equal(last.params.get("folder"), "3");
  emit("selection-changed", { hash: songs[0].file_hash, index: 0 });
  await flush();
  mockApi.calls.length = 0;
  keydown("ArrowDown", { altKey: true });
  await flush(10);
  const move = mockApi.callsTo("/api/folders/3/order");
  assert.equal(move.length, 1);
  assert.deepEqual(move[0].body, { hash: songs[0].file_hash, after: songs[1].file_hash, view: "audio" });
});

test("andere Suche schließt die gespeicherte: kein Manuell mehr, Chip wird geräumt", async () => {
  const sorts = record("sort-changed");
  emit("state-load", { expression: "tag: anders sort: manual" });
  await flush(10);
  sorts.stop();
  assert.ok(sorts.some((d) => d.sort === "added"), "manual-Chip ohne Suche geräumt");
  assert.ok(!sortKeys().includes("manual"));
  assert.equal(note().hidden, true);
});

test("Album-Chip: Standard ist die Album-Reihenfolge, ausdrücklich ‚Hinzugefügt‘ gewinnt", async () => {
  emit("state-load", { expression: "album: Debil" });
  await flush(10);
  assert.equal(mockApi.callsTo("/api/items").at(-1).params.get("sort"), "album");
  const sorts = record("sort-changed");
  document.getElementById("sort").dispatchEvent(new MouseEvent("click", { bubbles: true }));
  document.querySelector('#sortmenu .sortrow[data-key="added"]').dispatchEvent(
    new MouseEvent("click", { bubbles: true }));
  await flush(10);
  sorts.stop();
  assert.deepEqual(sorts.at(-1), { sort: "added", explicit: true });
  assert.equal(mockApi.callsTo("/api/items").at(-1).params.get("sort"), "added");
});
