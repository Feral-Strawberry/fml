// dialogs.test.mjs — Dialog-Stapel der Galerie (ADR 0069, Issue #23):
// Dialoge dürfen übereinander liegen, Esc schließt nur den obersten,
// Schließen von außen (Ansichtswechsel) läuft über die Schließfunktion;
// versteckte Dialoge hängen am selben Stapel. Dazu die Zeitlimits lesender
// Anfragen (#27). Der Admin hat seit ADR 0074 einen eigenen Stapel:
// admin_dialogs.test.mjs / picker.test.mjs.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, keydown, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit } from "./bus.mjs";

const { initSaveDialog } = await import("../../src/feral/web/static/js/savedialog.js");
const { dialogsOpen, closeAllDialogs, initOverlays } = await import("../../src/feral/web/static/js/overlays.js");
const { getItem } = await import("../../src/feral/web/static/js/api.js");
const { STRINGS } = await import("../../src/feral/web/static/js/strings.js");

before(async () => {
  loadShell();
  initOverlays();
  initSaveDialog();
  await flush();
});

test("Versteckte Dialoge (Speichern) hängen am Stapel: Esc schließt, kein eigener Listener", async () => {
  const before = document.listenerCount("keydown", true);
  emit("save-dialog-open", { expression: "tag: x", predicates: [], sort: "added-ab", total: 1 });
  await flush();
  assert.equal(document.getElementById("savedlg").hidden, false);
  assert.ok(dialogsOpen());
  assert.equal(document.listenerCount("keydown", true), before);
  keydown("Escape");
  await flush();
  assert.equal(document.getElementById("savedlg").hidden, true);
  assert.equal(dialogsOpen(), false);
});

test("Ansichtswechsel schließt alle Dialoge über ihre Schließfunktion", async () => {
  emit("save-dialog-open", { expression: "tag: x", predicates: [], sort: "added-ab", total: 1 });
  await flush();
  assert.ok(dialogsOpen());
  emit("view-changed", { view: "loupe", open: true });
  await flush();
  assert.equal(document.getElementById("savedlg").hidden, true, "view-changed räumt den Stapel");
  assert.equal(dialogsOpen(), false);
  closeAllDialogs();   // leer: kein Fehler
});

test("Lesende Anfrage bricht nach dem Zeitlimit mit übersetzter Meldung ab (#27)", async () => {
  mockApi.get(/^\/api\/item\//, () => new Promise(() => {}));   // antwortet nie
  await assert.rejects(getItem("ab".repeat(32), { timeout: 20 }), (err) => {
    assert.equal(err.message, STRINGS.requestTimeout);
    return true;
  });
});
