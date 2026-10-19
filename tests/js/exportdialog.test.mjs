// exportdialog.test.mjs — Kopie-Export in der Sammel-Aktion (ADR 0103):
// ohne brauchbaren Export-Ordner ist der Knopf gesperrt und die Zeile sagt,
// warum; sonst tauscht der Knopf den Dialog gegen das kleine Formular
// (Paketname, Ablage, umgerechnete Formate, Angaben von Hand nach
// ADR 0107), „Exportieren" reiht die
// Aufgabe ein und zeigt den Zielordner.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, click, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit } from "./bus.mjs";

const { initBulkDialog, packageName } = await import("../../src/feral/web/static/js/bulkdialog.js");

const dlg = () => document.getElementById("bulkdlg");
const open = () =>
  emit("bulk-dialog-open", { expression: "tag: x", predicates: [], liveTerms: [], total: 3 });
const starts = () => mockApi.calls.filter((c) => c.method === "POST" && c.path === "/api/export");
let state;
let plan;

before(async () => {
  loadShell();
  mockApi.get("/api/export", () => state);
  mockApi.post("/api/export/plan", () => plan);
  mockApi.post("/api/export", () => ({ queued: true, count: 3, target: "/exp/2026-10-09 Clip A" }));
  initBulkDialog();
  await flush();
});

test("ohne Export-Ordner: Knopf gesperrt, die Zeile nennt den Grund", async () => {
  state = { available: false, root: null, reason: { key: "errExportNoRoot" } };
  open();
  await flush();
  assert.equal(dlg().querySelector(".bulkcopy").disabled, true);
  assert.match(dlg().querySelector(".bulkcopymsg").textContent, /Kein Export-Ordner eingerichtet/);
});

test("Formular: Zahlen, Ziel folgt dem Paketnamen, Exportieren reiht ein", async () => {
  state = { available: true, root: "/exp", reason: null };
  plan = { ...state, count: 3, bytes: 3_000_000, converted: 1, free: 9e9, target: "/exp/2026-10-09" };
  open();
  await flush();
  assert.equal(dlg().querySelector(".bulkcopy").disabled, false);
  click(dlg().querySelector(".bulkcopy"));
  await flush();
  assert.match(dlg().querySelector(".pickpath").textContent, /3 Dateien · 3\.0 MB/);
  assert.match(dlg().querySelector(".exptarget").textContent, /Ziel: \/exp\/2026-10-09 ·/);
  // umgerechnete Formate nur, wenn welche dabei sind
  assert.equal(dlg().querySelectorAll('input[name="expconverted"]').length, 2);

  const name = dlg().querySelector(".expname");
  name.value = 'Clip: "A"';
  name.dispatchEvent(new Event("input", { bubbles: true }));
  assert.match(dlg().querySelector(".exptarget").textContent, /Ziel: \/exp\/2026-10-09 Clip A ·/);

  click(dlg().querySelector(".expgo"));
  await flush();
  assert.deepEqual(starts().at(-1).body, {
    filter: "tag: x", name: 'Clip: "A"', layout: "flat", converted: "png", tags: false,
    view: "galerie",
  });
  assert.equal(dlg().querySelector(".exppath").textContent, "/exp/2026-10-09 Clip A");
  click(dlg().querySelector(".bulkcancel"));
  assert.equal(dlg().hidden, true);
});

test("zu wenig Platz: Exportieren gesperrt, Zurück führt zur Sammel-Aktion", async () => {
  plan = { ...state, count: 3, bytes: 9e9, converted: 0, free: 1e9, target: "/exp/2026-10-09" };
  const before = starts().length;
  open();
  await flush();
  click(dlg().querySelector(".bulkcopy"));
  await flush();
  assert.equal(dlg().querySelector(".expgo").disabled, true);
  assert.equal(dlg().querySelector(".sderr").hidden, false);
  assert.equal(dlg().querySelectorAll('input[name="expconverted"]').length, 0);
  click(dlg().querySelector(".expback"));
  await flush();
  assert.ok(dlg().querySelector(".bulkgo"));
  assert.equal(starts().length, before);
});

test("Songs mit Angaben von Hand: Häkchen an, abwählbar (ADR 0107)", async () => {
  plan = { ...state, count: 3, bytes: 3_000_000, converted: 0, tagged: 2, free: 9e9,
           target: "/exp/2026-10-09" };
  open();
  await flush();
  click(dlg().querySelector(".bulkcopy"));
  await flush();
  const box = dlg().querySelector(".exptags");
  assert.equal(box.checked, true);
  assert.match(dlg().textContent, /2 Songs mit Angaben, Songtext oder Cover von Hand/);
  click(dlg().querySelector(".expgo"));
  await flush();
  assert.equal(starts().at(-1).body.tags, true);

  open();
  await flush();
  click(dlg().querySelector(".bulkcopy"));
  await flush();
  dlg().querySelector(".exptags").checked = false;
  click(dlg().querySelector(".expgo"));
  await flush();
  assert.equal(starts().at(-1).body.tags, false);
});

test("Paketname wird wie auf dem Server bereinigt", () => {
  assert.equal(packageName('  Clip: "Feuer" / Take<2>?  '), "Clip Feuer Take 2");
  assert.equal(packageName("..\\..\\weg"), "weg");
  assert.equal(packageName("Ende. "), "Ende");
});
