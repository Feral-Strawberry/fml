// admin_dialogs.test.mjs — Dialog-Stapel des Admin-Dokuments (ADR 0074
// Punkt 4, eigener Stapel unabhängig von overlays.js): seit A3 (#107) nur
// noch Ordner-Auswahl und Bestätigung. Dialoge dürfen übereinander liegen,
// Esc schließt von oben nach unten, Schließen von außen läuft über die
// Schließfunktion (kein hängendes Promise, #31/#36); die Ordnerwahl der
// Rausverschieben-Karte übernimmt den Pfad ins Feld.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { bootAdmin, click, flush, keydown } from "./harness.mjs";

let state, dialogs;
const visible = () => [...document.querySelectorAll(".pickoverlay")].filter((o) => !o.hidden).length;
const picker = () => document.querySelector(".pickoverlay #pickDirs")?.closest(".pickoverlay") || null;

before(async () => {
  state = await bootAdmin("/admin/maintenance");
  dialogs = await import("../../src/feral/web/static/js/admin/dialogs.js");
  await flush(6);
});

test("Stapel: Picker über der Bestätigung, Esc schließt von oben nach unten", async () => {
  const confirmed = dialogs.confirmDialog("Wirklich?");
  const picked = dialogs.pickFolder(null);
  await flush();
  assert.equal(visible(), 2, "beide Dialoge liegen im DOM");
  assert.ok(dialogs.dialogsOpen());
  keydown("Escape");
  await flush();
  assert.equal(picker(), null, "Esc schließt nur den Picker");
  assert.equal(await picked, null);
  assert.ok(document.getElementById("dlgOk"), "Dialog darunter steht noch");
  keydown("Escape");
  await flush();
  assert.equal(visible(), 0);
  assert.equal(await confirmed, false);
  assert.equal(dialogs.dialogsOpen(), false);
});

test("Ordnerwahl der Rausverschieben-Karte: Abbruch lässt das Feld stehen, Wahl übernimmt den Pfad (#31)", async () => {
  const target = document.getElementById("moTarget");
  target.value = "/alt";
  click(document.getElementById("moPick"));
  await flush();
  assert.ok(picker(), "Picker liegt über der Seite");
  click(document.getElementById("pickCancel"));
  await flush();
  assert.equal(picker(), null);
  assert.equal(target.value, "/alt", "Abbruch verwirft nichts");
  target.value = "";   // leeres Feld: der Picker startet bei den Wurzeln
  click(document.getElementById("moPick"));
  await flush();
  click(document.querySelector('.addir[data-path="/home/j"]'));
  await flush();
  click(document.getElementById("pickOk"));
  await flush();
  assert.equal(target.value, "/home/j", "Wahl steht im Feld");
  assert.equal(visible(), 0);
  click(document.getElementById("moPick"));
  await flush();
  assert.ok(picker(), "Picker öffnet ein zweites Mal (kein hängendes Promise)");
  dialogs.closeAllDialogs();
  assert.equal(visible(), 0);
});

test("closeAllDialogs schließt über die Schließfunktion — das Picker-Promise löst sich", async () => {
  const p = dialogs.pickFolder(null);
  await flush();
  assert.equal(visible(), 1);
  dialogs.closeAllDialogs();
  assert.equal(await p, null);
  assert.equal(visible(), 0);
});

test("Bestätigungsdialog: Ja → true, Abbrechen → false, Esc → false", async () => {
  let p = dialogs.confirmDialog("Wirklich?");
  await flush();
  assert.ok(document.getElementById("dlgOk"));
  click(document.getElementById("dlgOk"));
  assert.equal(await p, true);
  p = dialogs.confirmDialog("Wirklich?");
  await flush();
  click(document.getElementById("dlgCancel"));
  assert.equal(await p, false);
  p = dialogs.confirmDialog("Wirklich?");
  await flush();
  keydown("Escape");
  assert.equal(await p, false);
  assert.equal(visible(), 0);
});
