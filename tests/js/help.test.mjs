// help.test.mjs — Hilfe-Knopf „?“ (ADR 0091): unsichtbar ohne Hilfe-Ordner,
// öffnet /hilfe/ in einem Dialog über der Bibliothek; Esc und ✕ schließen
// über den Dialogstapel (ADR 0069), nichts darunter sieht das Esc.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, click, keydown } from "./harness.mjs";

const { initHelp, setHelpAvailable } = await import("../../src/feral/web/static/js/help.js");
const { dialogsOpen } = await import("../../src/feral/web/static/js/overlays.js");

const btn = () => document.getElementById("helpBtn");
const overlay = () => document.querySelector(".helpoverlay");

before(() => {
  loadShell();
  initHelp(btn());
});

test("ohne Hilfe-Ordner bleibt der Knopf verborgen", () => {
  assert.equal(btn().hidden, true);
  setHelpAvailable(btn(), false);
  assert.equal(btn().hidden, true);
});

test("mit Hilfe-Ordner: Klick öffnet /hilfe/ im Dialog", () => {
  setHelpAvailable(btn(), true);
  assert.equal(btn().hidden, false);
  click(btn());
  assert.equal(overlay().hidden, false);
  assert.equal(overlay().querySelector(".helpframe").getAttribute("src"), "/hilfe/");
  assert.ok(dialogsOpen(), "im Dialogstapel angemeldet");
});

test("Esc schließt den Dialog und meldet ihn ab", () => {
  let below = 0;
  const spy = () => { below += 1; };
  document.addEventListener("keydown", spy);
  keydown("Escape");
  document.removeEventListener("keydown", spy);
  assert.equal(overlay().hidden, true);
  assert.equal(dialogsOpen(), false);
  assert.equal(below, 0, "das Esc erreicht die Bibliothek darunter nicht");
});

test("✕ schließt; erneutes Öffnen lädt nicht neu", () => {
  click(btn());
  const frame = overlay().querySelector(".helpframe");
  frame.setAttribute("src", "/hilfe/#kapitel-4");   // Leser war weiter unten
  click(overlay().querySelector(".helpclose"));
  assert.equal(overlay().hidden, true);
  click(btn());
  assert.equal(frame.getAttribute("src"), "/hilfe/#kapitel-4");
  click(overlay());                                   // Klick daneben
  assert.equal(overlay().hidden, true);
});
