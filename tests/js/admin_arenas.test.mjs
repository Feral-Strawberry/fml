// admin_arenas.test.mjs — Seite „Ranking-Arenen" (A3, #107): Tabelle mit Name,
// Ausdruck, Population, Duellen, Items mit Score, angelegt am; Löschen nur
// nach Bestätigungsdialog (ADR 0045: Löschen lebt hier); „Ranking-Scores neu
// berechnen" mit Inline-Ergebnis.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { bootAdmin, click, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";

let state;
let arenas = [
  { id: 1, name: "Porträts", expression: "tool:comfyui", population: 1234, duels: 56, rated: 40, created_at: "2026-09-01T10:00:00" },
  { id: 2, name: "Alles", expression: "", population: null, duels: 0, rated: 0, created_at: "2026-09-02T10:00:00" },
];

before(async () => {
  state = await bootAdmin("/admin/arenas");
  mockApi.get("/api/rankings", () => ({ rankings: arenas }));
  mockApi.on("DELETE", /^\/api\/rankings\/\d+$/, ({ path }) => { arenas = arenas.filter((a) => String(a.id) !== path.split("/").pop()); return {}; });
  mockApi.post("/api/admin/rankings/recompute", () => ({ replayed: 56 }));
  await state.main.show("arenas");
  await flush();
});

test("Tabelle mit allen Spalten; leerer Ausdruck heißt „Alle Medien“, Population ohne Zahl ist „…“", () => {
  const rows = [...document.querySelectorAll(".atable tbody tr")];
  assert.equal(rows.length, 2);
  const cells = (r) => [...r.querySelectorAll("td")].map((c) => c.textContent.trim());
  assert.deepEqual(cells(rows[0]).slice(0, 6), ["Porträts", "tool:comfyui", "1.234", "56", "40", "2026-09-01"]);
  assert.equal(cells(rows[1])[1], "Alle Medien");
  assert.equal(cells(rows[1])[2], "…");
  assert.equal(document.getElementById("navCnt-arenas").textContent, "2");
  assert.equal(document.querySelector('[data-action="rankscores"] .ti').textContent, "Ranking-Scores neu berechnen");
});

test("Löschen: Abbrechen löscht nichts, Bestätigen löscht und lädt neu", async () => {
  assert.equal(document.querySelector('tr[data-arena="1"] .arenaedit').getAttribute("href"), "/?ranking=1",
    "Bearbeiten je Zeile springt in den Bearbeiten-Modus der Galerie (#133)");
  assert.equal(document.querySelector(".arenanew"), null, "kein Anlege-Knopf im Admin (#133)");
  click(document.querySelector('.arenadel[data-id="1"]'));
  await flush();
  assert.ok(document.getElementById("dlgOk"), "Bestätigungsdialog");
  assert.ok(document.querySelector(".dlgtext").textContent.includes("Porträts"));
  click(document.getElementById("dlgCancel"));
  await flush();
  assert.equal(document.querySelectorAll(".atable tbody tr").length, 2);
  click(document.querySelector('.arenadel[data-id="1"]'));
  await flush();
  click(document.getElementById("dlgOk"));
  await flush();
  assert.equal(document.querySelectorAll(".atable tbody tr").length, 1);
  assert.ok(document.getElementById("arMsg").textContent.includes("Porträts"));
  assert.equal(document.getElementById("navCnt-arenas").textContent, "1");
});

test("Scores neu berechnen meldet die nachgespielten Duelle inline", async () => {
  click(document.getElementById("arRecompute"));
  await flush();
  const st = document.getElementById("arRecomputeSt");
  assert.ok(st.classList.contains("done"));
  assert.ok(st.textContent.includes("56"), st.textContent);
});
