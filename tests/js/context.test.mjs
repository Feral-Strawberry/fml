// context.test.mjs — Bearbeiten-Modus für Rankings im Breadcrumb (ADR 0081,
// Issue #91, Revision #133): ein per ✎ geladenes Ranking steht als
// „Bearbeiten: 🏆 Name" vorn, die Kopfzeile trägt `editing`; Speichern nur
// bei Abweichung (Punkt am Namen), Umbenennen sichert NUR den Namen, ✕ führt
// zurück ins Ranking, sort: zählt nicht. Eine gespeicherte Suche ist KEIN
// Bearbeiten-Modus. Die Icons ☆/🏆 in #midtools legen nur Neues an.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, click, keydown, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit, record } from "./bus.mjs";

const { initSearch } = await import("../../src/feral/web/static/js/search.js");
const { initContext, withoutSort } = await import("../../src/feral/web/static/js/context.js");

// Mini-Grammatik der Attrappe: „kind: wert kind: wert" ↔ Prädikate (die
// echte lebt serverseitig, ADR 0035 — hier zählt nur der Rundweg).
const parse = (expr) => String(expr).trim().split(/\s+(?=\w+:)/).filter(Boolean).map((tok) => {
  const [kind, value] = tok.split(/:\s*/);
  return { kind, negated: false, field: "", op: "=", values: [{ value, exact: false }] };
});
const serialize = (preds) => preds.map((p) => `${p.kind}: ${p.values.map((v) => v.value).join(" | ")}`).join(" ");
const pred = (kind, value) => ({ kind, negated: false, field: "", op: "=", values: [{ value, exact: false }] });

const seg = () => document.getElementById("ctxseg");
const inCrumb = () => !!document.querySelector("#crumb .ctxslot #ctxseg");
const saveBtn = () => seg().querySelector(".ctxsave");
const dirty = () => !seg().querySelector(".ctxdirty").hidden;
const puts = (prefix) => mockApi.calls.filter((c) => c.method === "PUT" && c.path.startsWith(prefix));

let arenaOpens;
before(async () => {
  loadShell();
  mockApi.get("/api/filter/parse", ({ params }) => {
    const preds = parse(params.get("expr"));
    return { expression: serialize(preds), predicates: preds, sort: null };
  });
  mockApi.post("/api/filter/build", ({ body }) =>
    ({ expression: serialize(body.predicates), predicates: body.predicates, sort: null }));
  mockApi.on("PUT", /^\/api\/folders\/\d+$/, ({ body }) => ({ id: 1, ...body }));
  mockApi.on("PUT", /^\/api\/rankings\/\d+$/, ({ body }) => ({ id: 7, ...body }));
  initSearch();
  initContext();
  arenaOpens = record("arena-open");
  await flush();
});

test("withoutSort streicht nur die sort:-Direktive", () => {
  assert.equal(withoutSort("tag: x sort: created year: 2026"), "tag: x year: 2026");
  assert.equal(withoutSort("sort: name-auf"), "");
  assert.equal(withoutSort(""), "");
});

test("gespeicherte Suche laden ist KEIN Bearbeiten-Modus (#133)", async () => {
  emit("state-load", { expression: "container: png", label: "PNGs", folder: { id: 1, name: "PNGs" } });
  await flush();
  assert.equal(inCrumb(), false);
  assert.equal(document.getElementById("midhead").classList.contains("editing"), false);
  emit("chip-toggle", { pred: pred("year", "2026") });
  await flush();
  assert.equal(inCrumb(), false, "auch geänderte Chips öffnen keinen Modus");
  assert.equal(puts("/api/folders/1").length, 0);
});

test("Ranking per ✎ geladen: Bearbeiten: 🏆 Name, Kopfzeile editing; sort: zählt nicht, Speichern schreibt ohne sort: und öffnet das Ranking", async () => {
  emit("state-load", { expression: "tag: x sort: created", label: "Arena A", arena: { id: 7, name: "Arena A" } });
  await flush();
  assert.ok(inCrumb(), "Segment hängt im Slot vorn");
  assert.equal(seg().querySelector(".ctxlabel").textContent, "Bearbeiten:");
  assert.ok(document.getElementById("midhead").classList.contains("editing"));
  assert.equal(seg().querySelector(".ctxicon").textContent, "🏆");
  assert.equal(seg().querySelector(".ctxname").textContent, "Arena A");
  assert.equal(saveBtn().textContent, "Ranking speichern");
  assert.match(seg().querySelector(".ctxclose").textContent, /Beenden/);
  assert.equal(dirty(), false);
  assert.equal(saveBtn().disabled, true);
  emit("sort-changed", { sort: "name" });
  await flush();
  assert.equal(dirty(), false, "Sortierung ist keine Abweichung der Population");
  emit("chip-toggle", { pred: pred("year", "2026") });
  await flush();
  assert.equal(dirty(), true);
  click(saveBtn());
  await flush();
  const p = puts("/api/rankings/7");
  assert.equal(p.length, 1);
  assert.deepEqual(p[0].body, { name: "Arena A", expression: "tag: x year: 2026" });
  assert.equal(inCrumb(), false, "zurück ins Ranking — Kontext endet");
  assert.equal(document.getElementById("midhead").classList.contains("editing"), false);
  assert.deepEqual(arenaOpens.at(-1), { id: 7, name: "Arena A", expression: "tag: x year: 2026" });
});

test("Umbenennen sichert NUR den Namen — ungesicherte Chips bleiben ungesichert", async () => {
  emit("state-load", { expression: "tag: x", label: "Arena A", arena: { id: 7, name: "Arena A" } });
  await flush();
  emit("chip-toggle", { pred: pred("tag", "elfe") });
  await flush();
  assert.equal(dirty(), true);
  click(seg().querySelector(".ctxrename"));
  const input = seg().querySelector(".ctxinput");
  assert.ok(input, "Eingabefeld inline im Segment");
  assert.equal(input.value, "Arena A");
  input.value = "Arena B";
  keydown("Enter", { target: input });
  await flush();
  const p = puts("/api/rankings/7");
  assert.deepEqual(p.at(-1).body, { name: "Arena B", expression: "tag: x" });
  assert.equal(seg().querySelector(".ctxname").textContent, "Arena B");
  assert.equal(dirty(), true, "die zusätzlichen Chips sind weiter ungesichert");
  emit("state-clear", {});
  await flush();
  assert.equal(inCrumb(), false, "Alle Medien beendet den Modus");
});

test("Arena: ✕ führt ohne Speichern zurück in die Arena; leerer Ausdruck beendet nicht", async () => {
  emit("state-load", { expression: "", label: "Alles", arena: { id: 8, name: "Alles" } });
  await flush();
  assert.ok(inCrumb(), "ganze Bibliothek ist eine gültige Population");
  emit("chip-toggle", { pred: pred("year", "2026") });
  await flush();
  assert.equal(dirty(), true);
  const before = puts("/api/rankings/8").length;
  click(seg().querySelector(".ctxclose"));
  await flush();
  assert.equal(puts("/api/rankings/8").length, before, "nichts geschrieben");
  assert.equal(inCrumb(), false);
  assert.deepEqual(arenaOpens.at(-1), { id: 8, name: "Alles", expression: "" });
});

test("🏆 in der Chip-Leiste: nur bei aktivem Modul, auch ohne Chips; ☆ nur mit Chips", async () => {
  emit("state-clear", {});
  await flush();
  const arenaBtn = document.getElementById("arenaBtn");
  assert.equal(arenaBtn.hidden, true);
  emit("rankings-enabled", { enabled: true });
  await flush();
  assert.equal(arenaBtn.hidden, false);
  assert.equal(document.getElementById("saveBtn").hidden, true);
  const opens = record("arena-dialog-open");
  click(arenaBtn);
  assert.deepEqual(opens[0], { expression: "", predicates: [], total: 0 });
  emit("rankings-enabled", { enabled: false });
  await flush();
  assert.equal(arenaBtn.hidden, true);
});
