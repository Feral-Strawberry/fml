// lyrics.test.mjs — Songtext mit Zeiten (#234): aktuelle Zeile mit Abschnitt
// für die Abspielleiste (leer in Pausen nach dem Zeilenende), Abschnitts-
// marken auf der Welle aus der Listenzeile, mitlaufende Zeilen im Panel.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, flush, hashOf } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";

const ly = await import("../../src/feral/web/static/js/lyrics.js");

const H = hashOf(9);
const LINES = [[500, 1400, "[Verse]"], [1500, 2200, "Grey skies above"],
  [2400, null, "[Chorus]"], [2500, 3500, "Sing it loud"]];

before(() => {
  loadShell();
  mockApi.get(/^\/api\/audio\/lyrics\//, () => ({ lines: [] }));
  mockApi.get(`/api/audio/lyrics/${H}`, () => ({ lines: LINES, sections: [[500, "Verse"], [2400, "Chorus"]] }));   // neueste Route gewinnt
});

test("aktuelle Zeile: erst nachladen, dann Zeile + Abschnitt, Pause nach dem Ende leer", async () => {
  assert.equal(ly.lineAt(H, 1.6), null);          // lädt nach
  await flush();
  assert.deepEqual(ly.lineAt(H, 1.6), { text: "Grey skies above", section: "Verse" });
  assert.deepEqual(ly.lineAt(H, 3.0), { text: "Sing it loud", section: "Chorus" });
  assert.deepEqual(ly.lineAt(H, 9.0), { text: "", section: "Chorus" });   // 1,5 s nach dem Ende: leer
  assert.deepEqual(ly.lineAt(H, 0.1), { text: "", section: "" });
});

test("Pausen: Singdauer begrenzt die Zeile, ein neuer Abschnitt beendet sie (Befund: Zeile über Solo und Bridge)", () => {
  // Suno: die letzte Zeile vor dem Solo „dauert“ bis zur nächsten gesungenen Zeile.
  const list = [[0, 30000, "Sing it loud"], [31000, null, "[Solo]"], [40000, 42000, "Back again"]];
  assert.equal(ly.activeIndex(list, 2), 0);
  assert.equal(ly.activeIndex(list, 5), -1);        // 2,5 s + 3 × 0,7 s vorbei
  assert.equal(ly.activeIndex(list, 31.5), -1);     // Solo hat begonnen
  assert.equal(ly.activeIndex(list, 41), 2);
  const short = [[0, 1000, "Hi"], [1200, 1300, "there"]];
  assert.equal(ly.activeIndex(short, 2.5), 1);      // Nachlauf 1,5 s nach dem Ende
  assert.equal(ly.activeIndex(short, 3.0), -1);
});

test("Song ohne getimten Text: keine Zeile", async () => {
  const other = hashOf(10);
  ly.lineAt(other, 1);
  await flush();
  assert.equal(ly.lineAt(other, 1), null);
});

test("Abschnittsmarken aus der Listenzeile, Position auf der Zeitachse", () => {
  const h = hashOf(11);
  ly.seedSections(h, [[0, "Intro"], [30000, "Chorus"]]);
  const wv = document.createElement("div");
  ly.paintSections(wv, h, 60);
  const marks = [...wv.querySelectorAll(".sec")];
  assert.deepEqual(marks.map((m) => m.textContent), ["Intro", "Chorus"]);
  assert.match(wv.querySelector(".secs").innerHTML, /left:50%[^>]*><i>Chorus</);
  // Intro reicht nur bis zur nächsten Marke (sonst schreiben sie sich übereinander).
  assert.match(wv.querySelector(".secs").innerHTML, /left:0%;max-width:min\(90px, 50\.00%\)[^>]*><i>Intro</);
});

test("Abschnitt am Abspielkopf kommt ganz nach vorn, die anderen bleiben gekürzt", () => {
  const h = hashOf(12);
  ly.seedSections(h, [[0, "Chorus"], [700, "Melodic Lead guitar"], [30000, "Verse 2"]]);
  const wv = document.createElement("div");
  const on = () => [...wv.querySelectorAll(".sec")].map((m) => m.classList.contains("on"));
  ly.paintSections(wv, h, 60, 0.3);
  assert.deepEqual(on(), [true, false, false]);
  ly.paintSections(wv, h, 60, 12);
  assert.deepEqual(on(), [false, true, false]);
  ly.paintSections(wv, h, 60);                     // nicht geladen: keiner vorn
  assert.deepEqual(on(), [false, false, false]);
});

test("Panel: im Solo ist die Abschnitts-Überschrift hervorgehoben, sonst die Zeile", () => {
  const h = hashOf(13);
  const list = [[0, 2000, "[Verse 1]"], [500, 3000, "Line one"], [9000, 9000, "[Guitar Solo]"],
    [9000, 9000, "[Verse 2]"], [9000, 11000, "Back again"]];
  // Server-Abschnitte mit geschätztem Solo-Anfang (Ende der Zeile davor).
  ly.seedSections(h, [[0, "Verse 1"], [3000, "Guitar Solo"], [9000, "Verse 2"]]);
  assert.equal(ly.panelIndex(h, list, 1), 1);      // gesungene Zeile
  assert.equal(ly.panelIndex(h, list, 6), 2);      // Solo: Überschrift [Guitar Solo]
  assert.equal(ly.panelIndex(h, list, 9.5), 4);    // wieder gesungen
});

test("Panel: Abschnitte als Überschrift, Zeilen mit Startzeit zum Anklicken", () => {
  const html = ly.panelLinesHtml(H, LINES);
  const box = document.createElement("div");
  box.innerHTML = html;
  const rows = [...box.querySelectorAll(".lyl")];
  assert.equal(rows.length, 4);
  assert.ok(rows[0].classList.contains("lysec"));
  assert.equal(rows[3].dataset.t, "2.5");
  assert.equal(ly.indexAt(LINES, 2.45), 2);
});
