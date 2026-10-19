// selectioncontract.test.mjs — Auswahl-Vertrag (#305): Bei Mehrfachauswahl
// wirkt JEDE Aktion im Detailpanel auf die ganze Auswahl. Anlass: #281
// stellte nur das Cover um, #303 fand danach das Tag-✕, das nur das
// angezeigte Medium traf.
//
// Neue Aktion im Panel: hier eine Zeile in ACTIONS. Wirkt sie bewusst nur
// auf ein Medium, gehört sie in SINGLE_ON_PURPOSE, mit Begründung.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { loadShell, click, keydown, flush, item, hashOf, serveLibrary, itemDetail } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit, record } from "./bus.mjs";
import { DomEvent } from "./dom.mjs";

const { initDetail } = await import("../../src/feral/web/static/js/detail.js");
const { initCurate } = await import("../../src/feral/web/static/js/curate.js");
const { MUSIC_FIELDS } = await import("../../src/feral/web/static/js/musicfields.js");

// Bewusst je Medium: Notizen (ein Text pro Medium, Sammel-Aktion hängt an),
// Zeitkommentare (Stellen in genau einem Song), Songtext (nur bei
// Einzelauswahl sichtbar), Ausschnitt (genau eine Datei).
const SINGLE_ON_PURPOSE = new Set(["note", "setNotes", "addComment", "deleteComment", "setLyrics"]);
// Schreibwege für genau ein Medium (api.js/curate.js).
const SINGLE_WRITERS = ["rate", "tagAdd", "tagRemove", "note",
                        "setRating", "setNotes", "addTag", "removeTag", "setLyrics"];

const A = hashOf(1), B = hashOf(2), C = hashOf(3);
const ALL = [A, B, C];
const song = (n) => item(n, { media_kind: "audio", container: "mp3", width: null, height: null,
                              duration: 180, name: `Song ${n}.mp3` });
const items = [song(1), song(2), song(3)];
const panel = () => document.getElementById("panel");
const manual = () => ({ rating: null, tags: ["album"], notes: "", model: null, media_date: null, cover: null });

const writes = () => mockApi.calls.filter((c) => c.method === "POST");
const lastWrite = (path) => writes().filter((c) => c.path === path).at(-1);
const sameSet = (got, msg) => assert.deepEqual([...new Set(got)].sort(), [...ALL].sort(), msg);

async function typeInto(el, value) {
  el.focus();
  el.value = value;
  el.blur();
  el.dispatchEvent(new DomEvent("blur"));
  el.dispatchEvent(new DomEvent("focusout", { bubbles: true }));
  await flush();
}

before(() => {
  loadShell();
  serveLibrary(items);
  mockApi.get(/^\/api\/item\/[0-9a-f]+$/, ({ path }) => {
    const it = items.find((x) => x.file_hash === path.split("/").pop());
    return { ...itemDetail(it), manual: manual() };
  });
  mockApi.get(/^\/api\/item\/[0-9a-f]+\/comments$/, () => ({ comments: [] }));
  mockApi.get(/^\/api\/audio\/analysis\//, () => mockApi.status(404, {}));
  mockApi.get("/api/tags", () => ({ tags: [] }));
  mockApi.get("/api/models", () => ({ models: [] }));
  mockApi.post("/api/batch/tags", () => ({ tags: [{ name: "album", count: 3, color: null, finder: false }], count: 3 }));
  mockApi.post("/api/batch/annotate", ({ body }) => ({ updated: body.hashes.length, manual: manual(), tags: [] }));
  const fields = () => Object.fromEntries(MUSIC_FIELDS.map((f) =>
    [f, { value: "", mixed: false, manual: false, source: null }]));
  mockApi.post("/api/fields/state", () => ({ fields: fields(), count: 3 }));
  mockApi.post("/api/fields", ({ body }) => ({ updated: body.hashes.length, fields: fields() }));
  mockApi.post("/api/batch/cover/remove", ({ body }) => ({ songs: body.hashes, manual: manual() }));
  initCurate();
  initDetail();
});

const ACTIONS = [
  ["Bewertung", async () => {
    click(panel().querySelector('#pRate .rdot[data-n="4"]'));
    await flush();
    return lastWrite("/api/batch/annotate").body;
  }],
  ["Tag anhängen", async () => {
    const input = panel().querySelector("#pTagInput");
    input.value = "neu";
    keydown("Enter", { target: input });
    await flush();
    return lastWrite("/api/batch/annotate").body;
  }],
  ["Tag entfernen", async () => {
    click(panel().querySelector("#pTags .tagdel"));
    await flush();
    return lastWrite("/api/batch/annotate").body;
  }],
  ["Modell", async () => {
    await typeInto(panel().querySelector("#pModel"), "Flux");
    return lastWrite("/api/batch/annotate").body;
  }],
  ["Datum von Hand", async () => {
    await typeInto(panel().querySelector("#pDate"), "1997");
    return lastWrite("/api/batch/annotate").body;
  }],
  ["Musik-Angaben", async () => {
    await typeInto(panel().querySelector('#pFields .mfrow[data-field="album"] input'), "Regenzeit");
    return lastWrite("/api/fields").body;
  }],
  ["Cover wählen", async () => {
    const picks = record("cover-pick");
    click(panel().querySelector('#pCover [data-cover="pick"]'));
    await flush();
    picks.stop();
    return picks[0];
  }],
  ["Cover entfernen", async () => {
    click(panel().querySelector('#pCover [data-cover="remove"]'));
    await flush();
    return lastWrite("/api/batch/cover/remove").body;
  }],
];

for (const [name, act] of ACTIONS) {
  test(`Mehrfachauswahl: „${name}“ wirkt auf alle drei Songs`, async () => {
    emit("selection-changed", { hash: A, index: 0, hashes: ALL });
    await flush();
    const before = writes().length;
    const sent = await act();
    assert.ok(sent, `${name}: keine Anfrage`);
    sameSet(sent.hashes, `${name}: nicht die ganze Auswahl`);
    const single = writes().slice(before).filter((c) => /^\/api\/item\/[0-9a-f]+\//.test(c.path));
    assert.deepEqual(single.map((c) => c.path), [], `${name}: Schreibweg für ein einzelnes Medium`);
  });
}

test("Statisch: das Panel importiert keine Einzel-Schreibwege außer den bewusst einzelnen", () => {
  const src = readFileSync(new URL("../../src/feral/web/static/js/detail.js", import.meta.url), "utf8");
  const imported = [...src.matchAll(/import\s*\{([^}]*)\}\s*from\s*"[^"]+"/g)]
    .flatMap((m) => m[1].split(",").map((s) => s.trim().split(/\s+as\s+/)[0]).filter(Boolean));
  const offenders = imported.filter((n) => SINGLE_WRITERS.includes(n) && !SINGLE_ON_PURPOSE.has(n));
  assert.deepEqual(offenders, [], "Einzel-Schreibweg im Panel: über curate.js apply… auf die Auswahl führen "
    + "oder mit Begründung in SINGLE_ON_PURPOSE aufnehmen");
});
