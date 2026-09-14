// search.test.mjs — Klick-Regel der Sidebar im Suchzustand (ADR 0035 +
// Nachtrag 2026-09-08, „wie in Lightroom"): ein einfacher Klick ERSETZT die
// Auswahl der Gruppe, Cmd/Strg-Klick (additive) erweitert zum ODER, Klick auf
// den aktiven Wert nimmt ihn heraus. Popover/Tipphilfe schicken kein
// additive-Feld und bleiben additiv.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit, record } from "./bus.mjs";

const { initSearch } = await import("../../src/feral/web/static/js/search.js");

const tool = (...values) => ({
  kind: "field", negated: false, field: "tool", op: "=",
  values: values.map((v) => ({ value: v, exact: true })),
});
const valuesOf = (state) => state.predicates.map((p) => `${p.field}:${p.values.map((v) => v.value).join("|")}`);
let states;

before(async () => {
  loadShell();
  // Die Grammatik lebt serverseitig (ADR 0035): die Attrappe reicht die
  // Prädikate unverändert zurück, der Ausdruck ist hier egal.
  mockApi.post("/api/filter/build", ({ body }) => ({
    expression: "x", predicates: body.predicates, sort: null,
  }));
  initSearch();
  states = record("search-state-changed");
  await flush();
});

async function toggle(pred, opts = {}) {
  emit("chip-toggle", { pred, ...opts });
  await flush();
  return states.at(-1);
}

test("einfacher Klick auf einen anderen Wert derselben Gruppe ERSETZT (kein ODER)", async () => {
  assert.deepEqual(valuesOf(await toggle(tool("google"), { additive: false })), ["tool:google"]);
  assert.deepEqual(valuesOf(await toggle(tool("openai"), { additive: false })), ["tool:openai"]);
});

test("Cmd/Strg-Klick fügt hinzu → ODER; einfacher Klick auf einen Teil der Auswahl reduziert darauf", async () => {
  assert.deepEqual(valuesOf(await toggle(tool("google"), { additive: true })), ["tool:openai|google"]);
  assert.deepEqual(valuesOf(await toggle(tool("google"), { additive: false })), ["tool:google"]);
});

test("Klick auf den aktiven Wert (ganze Auswahl) nimmt ihn heraus", async () => {
  const s = await toggle(tool("google"), { additive: false });
  assert.deepEqual(s.predicates, []);
});

test("ohne additive-Feld (Popover, Tipphilfe) bleibt es beim alten ODER-Verhalten", async () => {
  await toggle(tool("google"));
  assert.deepEqual(valuesOf(await toggle(tool("openai"))), ["tool:google|openai"]);
  assert.deepEqual(valuesOf(await toggle(tool("openai"))), ["tool:google"]);
  await toggle(tool("google"));
});

test("andere Gruppen bleiben unberührt: Generator wechseln lässt den Modell-Chip stehen", async () => {
  const model = { kind: "field", negated: false, field: "model", op: "=", values: [{ value: "flux1-dev", exact: true }] };
  await toggle(model, { additive: false });
  await toggle(tool("google"), { additive: false });
  const s = await toggle(tool("openai"), { additive: false });
  assert.deepEqual(valuesOf(s), ["model:flux1-dev", "tool:openai"]);
});

// -- #132 (ADR-0035-Nachtrag): getippte Werte im Chip-Editor / in der Tipphilfe --

test("parseTypedValue: \"…\" = exakt, '…' = enthält, verdoppelte Anführungszeichen, nackt = Teilstring", async () => {
  const { parseTypedValue, displayValue } = await import("../../src/feral/web/static/js/search.js");
  assert.deepEqual(parseTypedValue('"new york"'), { value: "new york", exact: true });
  assert.deepEqual(parseTypedValue("'new york'"), { value: "new york", exact: false });
  assert.deepEqual(parseTypedValue("'don''t stop'"), { value: "don't stop", exact: false });
  assert.deepEqual(parseTypedValue('"sag ""hi"""'), { value: 'sag "hi"', exact: true });
  assert.deepEqual(parseTypedValue("york"), { value: "york", exact: false });
  // Apostrophe im oder am Ende eines nackten Werts öffnen nichts.
  assert.deepEqual(parseTypedValue("don't"), { value: "don't", exact: false });
  assert.deepEqual(parseTypedValue("cats'"), { value: "cats'", exact: false });
  // Offene oder leere Phrase: der Server meldet den Fehler, hier nur roh durchreichen bzw. leer.
  assert.deepEqual(parseTypedValue("'tis"), { value: "'tis", exact: false });
  assert.deepEqual(parseTypedValue("''"), { value: "", exact: false });
  // Anzeige spiegelt die Grammatik-Schreibweise.
  assert.equal(displayValue({ value: "new york", exact: true }), '"new york"');
  assert.equal(displayValue({ value: "new york", exact: false }), "'new york'");
  assert.equal(displayValue({ value: "york", exact: false }), "york");
  assert.equal(displayValue({ value: '"zitat', exact: false }), "'\"zitat'");
});
