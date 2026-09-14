// theme.test.mjs — Dark/Light-Knopf in der Topbar (#123, ersetzt das
// Schnellmenü): Icon zeigt den aktiven Modus, Klick wechselt und merkt die
// Wahl in localStorage (geteilt mit dem Admin, appearance.js).

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, click } from "./harness.mjs";

const { initTheme, initThemeToggle, currentTheme, THEME_KEY } =
  await import("../../src/feral/web/static/js/appearance.js");

const btn = () => document.getElementById("themeBtn");

before(() => {
  loadShell();
  localStorage.removeItem(THEME_KEY);
  initTheme();
  initThemeToggle(btn(), { toDark: "zu dark", toLight: "zu light" });
});

test("Start dunkel: Mond-Icon, Titel nennt den Wechsel nach Light", () => {
  assert.equal(currentTheme(), "dark");
  assert.equal(btn().dataset.theme, "dark");
  assert.equal(btn().title, "zu light");
  assert.ok(btn().querySelector("svg"), "Icon gerendert");
});

test("Klick wechselt nach Light, merkt die Wahl, Icon und Titel folgen", () => {
  click(btn());
  assert.equal(currentTheme(), "light");
  assert.equal(document.documentElement.dataset.theme, "light");
  assert.equal(localStorage.getItem(THEME_KEY), "light");
  assert.equal(btn().dataset.theme, "light");
  assert.equal(btn().title, "zu dark");
});

test("zweiter Klick zurück nach Dark (Attribut weg, localStorage dark)", () => {
  click(btn());
  assert.equal(currentTheme(), "dark");
  assert.equal(document.documentElement.dataset.theme, undefined);
  assert.equal(localStorage.getItem(THEME_KEY), "dark");
});
