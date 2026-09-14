// picker.test.mjs — Ordner-Picker im Admin-Dokument (admin/dialogs.js):
// öffnen, abbrechen, erneut öffnen, wählen, übernehmen; keine hängenden
// Tastatur-Listener; Ordnerwahl der Rausverschieben-Karte (Issue #22
// Rauchtest 4, Issues #31 und #36; seit ADR 0074 mit eigenem Stapel, seit
// A3 #107 ist Rausverschieben eine Karte — kein Dialog darunter mehr).

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { bootAdmin, keydown, click, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";

const picker = () => document.querySelector(".pickoverlay #pickDirs")?.closest(".pickoverlay") || null;
const dir = (path) => document.querySelector(`.addir[data-path="${path}"]`);
const overlays = () => document.querySelectorAll(".pickoverlay").length;
let baseline;   // Capture-keydown-Listener am Dokument: EINER für alle Dialoge (dialogs.js)
let state;

before(async () => {
  state = await bootAdmin("/admin/sources");
  mockApi.get("/api/browse", ({ params }) => {
    const path = params.get("path");
    if (path === "/home/j/kaputt") return mockApi.status(500, { detail: "Zugriff verweigert" });
    return {
      path, parent: path === "/home/j" ? null : "/home/j", file_count: 3,
      subdirs: path === "/home/j" ? [{ name: "out", path: "/home/j/out" }, { name: "kaputt", path: "/home/j/kaputt" }] : [],
    };
  });
  mockApi.post("/api/admin/moveout", () => ({ queued: 3 }));
  baseline = document.listenerCount("keydown", true);
});

async function gotoMaintenance() {
  click(document.querySelector('#navlist a[data-page="maintenance"]'));
  await flush();
}
async function gotoSources() {
  click(document.querySelector('#navlist a[data-page="sources"]'));
  await flush();
}

test("Import-Pfad: öffnen, abbrechen, erneut öffnen, wählen, übernehmen", async () => {
  const input = document.getElementById("adImpPath");
  click(document.getElementById("adImpPick"));
  await flush();
  assert.ok(picker(), "Picker offen");
  assert.ok(dir("/home/j"), "Wurzeln gelistet");
  assert.equal(document.listenerCount("keydown", true), baseline, "kein Listener je Dialog (Stapel)");

  click(document.getElementById("pickCancel"));
  await flush();
  assert.equal(picker(), null, "abgebrochen: Picker weg");
  assert.equal(input.value, "");
  assert.equal(document.listenerCount("keydown", true), baseline, "kein hängender Listener");

  click(document.getElementById("adImpPick"));
  await flush();
  assert.ok(picker(), "zweites Öffnen funktioniert (#36)");
  click(dir("/home/j"));
  await flush();
  assert.ok(document.getElementById("pickPath").textContent.startsWith("/home/j"));
  click(dir("/home/j/out"));
  await flush();
  click(document.getElementById("pickOk"));
  await flush();
  assert.equal(picker(), null);
  assert.equal(input.value, "/home/j/out", "Auswahl steht im Feld");
  assert.equal(document.listenerCount("keydown", true), baseline);
  assert.equal(overlays(), 0);
});

test("Esc schließt nur den Picker, die Seite bleibt", async () => {
  click(document.getElementById("adImpPick"));
  await flush();
  assert.ok(picker());
  keydown("Escape");
  await flush();
  assert.equal(picker(), null);
  assert.ok(document.getElementById("adImpPath"), "Seite steht noch");
  assert.equal(document.listenerCount("keydown", true), baseline);
});

test("Fehler beim Blättern: Picker bleibt bedienbar", async () => {
  click(document.getElementById("adImpPick"));
  await flush();
  click(dir("/home/j"));
  await flush();
  click(dir("/home/j/kaputt"));
  await flush();
  assert.equal(globalThis.__alerts.length, 1, "Fehler wird gemeldet (heute per alert)");
  assert.ok(picker(), "Picker steht noch");
  click(document.getElementById("pickCancel"));
  await flush();
  assert.equal(picker(), null);
  assert.equal(document.listenerCount("keydown", true), baseline);
});

test("Rausverschieben-Karte: Ordner wählen, übernehmen, Ziel steht im Feld, Seite reagiert", async () => {
  await gotoMaintenance();
  assert.ok(document.getElementById("moTarget"), "Karte steht auf der Seite (kein Dialog)");
  assert.equal(overlays(), 0);
  click(document.getElementById("moPick"));
  await flush();
  assert.ok(picker(), "Picker offen");
  click(dir("/home/j"));
  await flush();
  click(document.getElementById("pickOk"));
  await flush();
  assert.equal(picker(), null);
  const target = document.getElementById("moTarget");
  assert.ok(target && target.isConnected, "Karte steht");
  assert.equal(target.value, "/home/j", "Ziel übernommen");
  assert.equal(document.getElementById("moArm").disabled, false, "mit Ziel + Treffern scharf schaltbar");
  keydown("Escape");
  await flush();
  assert.ok(document.getElementById("moTarget").isConnected, "Esc ohne Dialog ändert an der Seite nichts");
  assert.equal(document.listenerCount("keydown", true), baseline, "keine hängenden Listener");
  assert.equal(overlays(), 0);
});

test("Rausverschieben-Karte: Eingabe bleibt stehen, während der Picker offen ist und nach Abbruch (#31)", async () => {
  const target = document.getElementById("moTarget");
  target.value = "/vorher";
  click(document.getElementById("moPick"));
  await flush();
  assert.ok(picker(), "Picker offen");
  assert.ok(target.isConnected, "Karte liegt weiter unter dem Picker");
  click(document.getElementById("pickCancel"));
  await flush();
  assert.equal(document.getElementById("moTarget"), target, "dasselbe Feld");
  assert.equal(target.value, "/vorher", "Eingabe bleibt erhalten");
  assert.equal(overlays(), 0);
  assert.equal(document.listenerCount("keydown", true), baseline);
});

test("Picker-Abbruch blockiert keine spätere Ordnerwahl an anderer Stelle (Seitenwechsel)", async () => {
  await gotoSources();
  click(document.getElementById("adImpPick"));
  await flush();
  click(document.getElementById("pickCancel"));
  await flush();
  await gotoMaintenance();
  click(document.getElementById("moPick"));
  await flush();
  assert.ok(picker(), "Picker der Rausverschieben-Karte öffnet nach Abbruch anderswo");
  click(dir("/home/j"));
  await flush();
  click(document.getElementById("pickOk"));
  await flush();
  assert.equal(document.getElementById("moTarget").value, "/home/j");
  assert.equal(overlays(), 0);
  assert.equal(document.listenerCount("keydown", true), baseline);
});
