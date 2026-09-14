// overlays.test.mjs — Lupe und Einzelansicht: Tastatur-Guards in ALLEN
// Richtungen, nie zwei Overlays, Videos werden beim Schließen entfernt
// (Issue #22 Rauchtest 1, Issue #28 behoben); Video-Fallback, Abbruch beim
// Schließen und `view-changed` (ADR 0069, Issue #23/#25).

import { test, before } from "node:test";
import assert from "node:assert/strict";
import {
  loadShell, keydown, click, flush, item, itemDetail, serveLibrary, visibleOverlays,
} from "./harness.mjs";
import { emit, record } from "./bus.mjs";
import { mockApi } from "./apimock.mjs";
import { UIEvent } from "./dom.mjs";

const { initLoupe } = await import("../../src/feral/web/static/js/loupe.js");
const { initSingleView } = await import("../../src/feral/web/static/js/singleview.js");

const loupe = () => document.getElementById("loupe");
const single = () => document.getElementById("single");
const items = [item(1), item(2, { media_kind: "video", container: "webm", fps: 24 }), item(3)];

before(() => {
  loadShell();
  serveLibrary(items);
  initLoupe();
  initSingleView();
});

/** Ausgangslage je Test: alles zu, Bild 1 ausgewählt. */
async function reset() {
  keydown("Escape"); keydown("Escape");
  await flush();
  emit("selection-changed", { hash: items[0].file_hash, index: 0 });
  assert.deepEqual(visibleOverlays(), []);
}

test("Space öffnet die Lupe, Space/Esc schließen sie wieder", async () => {
  await reset();
  keydown(" ");
  await flush();
  assert.deepEqual(visibleOverlays(), ["loupe"]);
  assert.ok(loupe().querySelector("#lpStage img"), "Bild liegt auf der Bühne");
  keydown(" ");
  assert.deepEqual(visibleOverlays(), []);
  keydown(" ");
  await flush();
  assert.deepEqual(visibleOverlays(), ["loupe"]);
  keydown("Escape");
  assert.deepEqual(visibleOverlays(), []);
});

test("Enter öffnet die Einzelansicht, Enter/Esc schließen sie", async () => {
  await reset();
  keydown("Enter");
  await flush();
  assert.deepEqual(visibleOverlays(), ["single"]);
  // Panel wird adoptiert und beim Schließen zurückgegeben.
  assert.equal(document.getElementById("panel").parentElement.id, "svPanel");
  keydown("Enter");
  assert.deepEqual(visibleOverlays(), []);
  assert.equal(document.getElementById("panel").parentElement.id, "body");
  keydown("Enter");
  await flush();
  assert.deepEqual(visibleOverlays(), ["single"]);
  keydown("Escape");
  assert.deepEqual(visibleOverlays(), []);
});

test("Lupe offen: Enter öffnet KEINE Einzelansicht", async () => {
  await reset();
  keydown(" ");
  await flush();
  keydown("Enter");
  await flush();
  assert.deepEqual(visibleOverlays(), ["loupe"]);
});

test("Einzelansicht offen: Space öffnet KEINE Lupe (#28)", async () => {
  await reset();
  keydown("Enter");
  await flush();
  keydown(" ");
  await flush();
  assert.deepEqual(visibleOverlays(), ["single"]);
  assert.equal(document.getElementById("panel").parentElement.id, "svPanel");
});

test("Lupe offen: 'single-open' von außen schließt die Lupe (#28)", async () => {
  await reset();
  keydown(" ");
  await flush();
  // Galerie-Doppelklick/Arena öffnen die Einzelansicht über den Bus, nicht
  // über das Lupen-Segment — die Lupe muss sich trotzdem zurückziehen.
  emit("single-open", { hash: items[0].file_hash, index: 0 });
  await flush();
  assert.deepEqual(visibleOverlays(), ["single"]);
  assert.equal(loupe().querySelectorAll("video, img").length, 0, "Lupe räumt die Bühne");
});

test("Tippen im Suchfeld löst keine Overlays aus", async () => {
  await reset();
  const q = document.getElementById("q");
  keydown(" ", { target: q });
  keydown("Enter", { target: q });
  await flush();
  assert.deepEqual(visibleOverlays(), []);
});

test("Arena offen: Space/Enter gehören dem Duell", async () => {
  await reset();
  document.getElementById("rankings").hidden = false;
  keydown(" "); keydown("Enter");
  await flush();
  assert.deepEqual(visibleOverlays(), ["rankings"]);
  document.getElementById("rankings").hidden = true;
});

test("Video: Schließen der Lupe/Einzelansicht entfernt das <video>", async () => {
  await reset();
  emit("selection-changed", { hash: items[1].file_hash, index: 1 });
  keydown(" ");
  await flush();
  const lpVideo = loupe().querySelector("#lpStage video");
  assert.ok(lpVideo, "Video spielt in der Lupe");
  keydown("Escape");
  assert.equal(loupe().querySelectorAll("video").length, 0, "Lupe räumt das Video weg");
  assert.equal(lpVideo.getAttribute("src"), null, "Lupe gibt die Verbindung frei (#89)");

  keydown("Enter");
  await flush();
  const svVideo = single().querySelector("#svStage video");
  assert.ok(svVideo, "Video spielt in der Einzelansicht");
  keydown("Escape");
  assert.equal(single().querySelectorAll("video").length, 0, "Einzelansicht räumt das Video weg");
  assert.equal(svVideo.getAttribute("src"), null, "Einzelansicht gibt die Verbindung frei (#89)");
});

test("Blättern in Lupe/Einzelansicht gibt das vorige Video frei (#89: zweites 4-GB-Video in Firefox)", async () => {
  await reset();
  emit("selection-changed", { hash: items[1].file_hash, index: 1 });
  keydown("Enter");
  await flush();
  const first = single().querySelector("#svStage video");
  assert.ok(first && first.getAttribute("src"));
  // Ohne Galerie-Modul kein Seiten-Cache (Pfeiltasten wirkungslos, s. u.):
  // der Wechsel läuft über den Bus, derselbe show()-Pfad wie beim Blättern.
  emit("single-open", { hash: items[2].file_hash, index: 2 });   // weiter zu Bild 3
  await flush();
  assert.equal(first.getAttribute("src"), null, "voriges Video ohne src");
  assert.ok(single().querySelector("#svStage img"), "Bild 3 steht auf der Bühne");
  emit("single-open", { hash: items[1].file_hash, index: 1 });   // zurück zum Video
  await flush();
  const again = single().querySelector("#svStage video");
  assert.ok(again && again !== first && again.getAttribute("src"));
  keydown("Escape");
  await flush();

  keydown(" ");            // dasselbe in der Lupe
  await flush();
  const lp = loupe().querySelector("#lpStage video");
  assert.ok(lp && lp.getAttribute("src"));
  emit("loupe-open", { hash: items[2].file_hash, index: 2 });
  await flush();
  assert.equal(lp.getAttribute("src"), null, "Lupe: voriges Video ohne src");
  keydown("Escape");
});

test("Einzelbild-Segment der Lupe wechselt sauber in die Einzelansicht", async () => {
  await reset();
  keydown(" ");
  await flush();
  const opened = record("single-open");
  click(loupe().querySelector("#lpSegSingle"));
  await flush();
  assert.deepEqual(visibleOverlays(), ["single"]);
  assert.equal(opened.length, 1);
  opened.stop();
  // Umgekehrt: 'loupe-open' bei offener Einzelansicht schließt diese.
  emit("loupe-open", { hash: items[0].file_hash, index: 0 });
  await flush();
  assert.deepEqual(visibleOverlays(), ["loupe"]);
});

test("Blättern in der Lupe zieht die Auswahl mit", async () => {
  await reset();
  // Ohne Galerie-Modul gibt es keinen Seiten-Cache: galleryItemAt → null,
  // Blättern bleibt wirkungslos, darf aber nicht werfen.
  keydown(" ");
  await flush();
  const sel = record("selection-changed");
  keydown("ArrowRight");
  await flush();
  assert.equal(sel.length, 0);
  sel.stop();
  keydown("Escape");
});

test("Einzelansicht: Video-Fehler zeigt den Hinweis statt schwarzer Bühne (#25)", async () => {
  await reset();
  emit("single-open", { hash: items[1].file_hash, index: 1 });
  await flush();
  const video = single().querySelector("#svStage video");
  assert.ok(video, "Video liegt auf der Bühne");
  video.dispatchEvent(new UIEvent("error"));
  await flush();
  assert.equal(single().querySelector("#svStage video"), null, "Video weg");
  assert.ok(single().querySelector("#svStage .nopreview"), "Hinweis steht");
  keydown("Escape");
  await flush();
});

test("Schließen bricht die laufende Detail-Anfrage ab; verspätete Antwort baut nichts mehr", async () => {
  await reset();
  const gate = mockApi.gate();
  mockApi.get(/^\/api\/item\/[0-9a-f]+$/, async ({ path }) => {
    await gate.promise;
    return itemDetail(items.find((x) => x.file_hash === path.split("/").pop()));
  });
  const seen = record("view-changed");
  emit("single-open", { hash: items[0].file_hash, index: 0 });
  await flush();
  assert.equal(single().querySelector("#svStage img"), null, "noch nichts geladen");
  keydown("Escape");
  await flush();
  gate.open();
  await flush();
  assert.equal(single().querySelector("#svStage img"), null, "abgebrochen: Bühne bleibt leer");
  assert.deepEqual(seen.map((d) => [d.view, d.open]), [["single", true], ["single", false]]);
  seen.stop();
  serveLibrary(items);   // Standard-Routen zurück
});
