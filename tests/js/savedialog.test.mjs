// savedialog.test.mjs — Speicherdialog (Block S7, Revision #133): ohne
// Ursprung nur „Speichern" (POST); aus einer geladenen Suche sagt der
// Dialog den Ursprung, belegt den Namen vor und bietet „»Name«
// überschreiben" (PUT, geänderter Name = umbenennen) und „Als neue Suche
// speichern" (POST); danach ist das Gespeicherte der Ursprung
// ('folder-origin'). Leeren beendet den Ursprung.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, click, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit, record } from "./bus.mjs";

const { initSaveDialog } = await import("../../src/feral/web/static/js/savedialog.js");

const dlg = () => document.getElementById("savedlg");
const open = (expression = "tag: x") =>
  emit("save-dialog-open", { expression, predicates: [], sort: null, total: 3 });
const posts = () => mockApi.calls.filter((c) => c.method === "POST" && c.path === "/api/folders");
const puts = () => mockApi.calls.filter((c) => c.method === "PUT" && c.path.startsWith("/api/folders/"));
let origins;

before(async () => {
  loadShell();
  mockApi.post("/api/folders", ({ body }) => ({ id: 9, ...body }));
  mockApi.on("PUT", /^\/api\/folders\/\d+$/, ({ body }) => ({ id: 1, ...body }));
  initSaveDialog();
  origins = record("folder-origin");
  await flush();
});

test("ohne Ursprung: nur Speichern, leerer Name wird abgewiesen", async () => {
  open();
  await flush();
  assert.equal(dlg().querySelector(".sdorigin"), null);
  assert.deepEqual([...dlg().querySelectorAll("[data-act]")].map((b) => b.dataset.act), ["create", "cancel"]);
  click(dlg().querySelector('[data-act="create"]'));
  await flush();
  assert.equal(dlg().querySelector(".sderr").hidden, false);
  dlg().querySelector(".sdname").value = "Neu";
  click(dlg().querySelector('[data-act="create"]'));
  await flush();
  assert.deepEqual(posts().at(-1).body, { name: "Neu", expression: "tag: x" });
  assert.deepEqual(origins.at(-1), { id: 9, name: "Neu", expression: "tag: x" });
  assert.equal(dlg().hidden, true);
});

test("aus geladener Suche: Ursprung steht im Dialog, Name vorbelegt, Überschreiben = PUT", async () => {
  emit("state-load", { expression: "container: png", label: "PNGs", folder: { id: 1, name: "PNGs" } });
  open("container: png year: 2026");
  await flush();
  assert.match(dlg().querySelector(".sdorigin").textContent, /»PNGs«/);
  assert.equal(dlg().querySelector(".sdname").value, "PNGs");
  const acts = [...dlg().querySelectorAll("[data-act]")].map((b) => b.dataset.act);
  assert.deepEqual(acts, ["overwrite", "createnew", "cancel"]);
  assert.match(dlg().querySelector('[data-act="overwrite"]').textContent, /»PNGs« überschreiben/);
  dlg().querySelector(".sdname").value = "PNG neu";   // geänderter Name = umbenennen
  click(dlg().querySelector('[data-act="overwrite"]'));
  await flush();
  assert.deepEqual(puts().at(-1).body, { name: "PNG neu", expression: "container: png year: 2026" });
  assert.deepEqual(origins.at(-1), { id: 1, name: "PNG neu", expression: "container: png year: 2026" });
});

test("Als neue Suche speichern legt an und macht die neue zum Ursprung; Leeren beendet ihn", async () => {
  open("container: png year: 2026");
  await flush();
  assert.equal(dlg().querySelector(".sdname").value, "PNG neu", "Ursprung ist jetzt die überschriebene Suche");
  dlg().querySelector(".sdname").value = "Kopie";
  click(dlg().querySelector('[data-act="createnew"]'));
  await flush();
  assert.deepEqual(posts().at(-1).body, { name: "Kopie", expression: "container: png year: 2026" });
  assert.equal(origins.at(-1).id, 9);
  emit("search-state-changed", { expression: "", canonical: "", predicates: [], sort: null });
  open();
  await flush();
  assert.equal(dlg().querySelector(".sdorigin"), null, "ohne Ausdruck kein Ursprung mehr");
  click(dlg().querySelector('[data-act="cancel"]'));
});
