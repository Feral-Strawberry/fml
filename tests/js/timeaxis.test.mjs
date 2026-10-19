// timeaxis.test.mjs — gedeckelte gemeinsame Zeitachse der Audioliste
// (ADR 0109, #265): ein Konzert-Mitschnitt macht die übrigen Wellen nicht
// winzig; er füllt seine Zeile gestaucht, trägt » und springt richtig.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, click, flush, item, hashOf, serveLibrary } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { DomEvent } from "./dom.mjs";

localStorage.setItem("feral-view", "audio");

// Fake-<audio> wie in player.test.mjs: der DOM-Stub spielt nichts ab.
let audio = null;
const origCreate = document.createElement.bind(document);
document.createElement = (tag) => {
  if (tag !== "audio") return origCreate(tag);
  const el = origCreate("div");
  Object.assign(el, {
    paused: true, currentTime: 0, duration: NaN, volume: 1, playbackRate: 1,
    play() { this.paused = false; this.dispatchEvent(new DomEvent("play")); return Promise.resolve(); },
    pause() { this.paused = true; this.dispatchEvent(new DomEvent("pause")); },
  });
  audio = el;
  return el;
};

const player = await import("../../src/feral/web/static/js/player.js");
const { initAudioList, setTimeAxis, timeAxis, AXIS_CAP } = await import("../../src/feral/web/static/js/audiolist.js");
const { initLibraryView } = await import("../../src/feral/web/static/js/libview.js");
const { initGallery } = await import("../../src/feral/web/static/js/gallery.js");

const song = (n, dur, name) => item(n, { media_kind: "audio", container: "mp3", width: null,
  height: null, duration: dur, name, tool: "suno" });
// Ein normaler Song und ein zweistündiger Konzert-Mitschnitt.
const songs = [song(1, 210, "Regenzeit.mp3"), song(2, 7200, "Konzert Juni.mp3")];
const grid = () => document.getElementById("grid");
const row = (n) => grid().querySelector(`.arow[data-hash="${hashOf(n)}"]`);

before(async () => {
  loadShell();
  const lib = serveLibrary(songs);
  mockApi.get("/api/items", ({ params }) => {
    const offset = parseInt(params.get("offset") || "0", 10);
    return { total: params.get("total") === "1" ? lib.items.length : -1, offset,
             items: lib.items.slice(offset, offset + 200),
             ...(params.get("total") === "1" ? { max_duration: 7200 } : {}) };
  });
  mockApi.get(/^\/api\/audio\/analysis\//, () => mockApi.status(404, { detail: "nicht messbar" }));
  mockApi.get("/api/stats", () => ({ total_items: 2, items_multi_location: 0, total_bytes: 1,
    library_configured: false, rankings: false, audio: true }));
  mockApi.get("/api/folders", () => ({ folders: [] }));
  document.rectFor = (el) => (el.classList.contains("tile") ? { height: 65 }
    : el.classList.contains("wv") ? { left: 0, width: 400 } : null);
  document.getElementById("gridwrap").clientHeight = 1000;
  initLibraryView();
  initGallery();
  player.initPlayer();
  initAudioList();
  (await import("./bus.mjs")).emit("audio-enabled", { enabled: true });
  await flush(10);
});

test("Achse höchstens 7 Minuten, das Lineal endet dort", () => {
  assert.equal(AXIS_CAP, 420);
  assert.equal(timeAxis(), 420);                     // statt 7200 vom Server
  const ticks = document.querySelectorAll("#listhead .ruler span").map((s) => s.textContent);
  assert.equal(ticks.at(-1), "7:00");
});

test("Überlanger Song trägt » und die wahre Länge im Tooltip, der normale nicht", () => {
  assert.equal(row(1).querySelector(".sqz").hidden, true);
  assert.equal(row(2).querySelector(".sqz").hidden, false);
  assert.match(row(2).querySelector(".wv").getAttribute("title"), /^Gestaucht: 2:00:00 auf die Breite von 7:00\n/);
  assert.doesNotMatch(row(1).querySelector(".wv").getAttribute("title"), /Gestaucht/);
});

test("Klick in die gestauchte Welle springt in deren eigenem Maßstab", async () => {
  // 25 % der Breite = 1800 s des Mitschnitts, nicht 25 % der 7-Minuten-Achse.
  click(row(2).querySelector(".wv"), { clientX: 100 });
  await flush();
  assert.equal(player.currentHash(), hashOf(2));
  audio.dispatchEvent(new DomEvent("loadedmetadata"));
  assert.equal(audio.currentTime, 1800);
});

test("Unter dem Deckel bleibt die Achse der längste Song", () => {
  setTimeAxis(300);                                  // Liste ohne Überlange
  assert.equal(timeAxis(), 300);
  assert.equal(row(1).querySelector(".sqz").hidden, true);
  setTimeAxis(7200);                                 // Mitschnitt im Vergleich: gedeckelt
  assert.equal(timeAxis(), 420);
  click(document.getElementById("pbar").querySelector('[data-act="close"]'));   // Player-Takt aus
});
