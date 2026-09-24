// artwork.test.mjs — Anzeigebild normaler Musik (#198): ein Song ohne Cover
// und ohne KI-Erzeuger zeigt sein eingebettetes Bild als Miniatur in der
// Zeile und in der Abspielleiste (Vorschaubild des Songs selbst); ein Suno-
// Song ohne Cover zeigt keins. Ein Anzeigebild ist kein Cover. Dazu Musik
// neben der Bildarbeit: stumme Vorschau-Videos (Panel, Arena) halten den Song
// nicht an und werden von ihm nicht angehalten; ein Video mit Ton schon.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, click, flush, item, hashOf, serveLibrary } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { DomEvent } from "./dom.mjs";

localStorage.setItem("feral-view", "audio");

const { initAudioList } = await import("../../src/feral/web/static/js/audiolist.js");
const { initLibraryView } = await import("../../src/feral/web/static/js/libview.js");
const { initGallery } = await import("../../src/feral/web/static/js/gallery.js");
const { STRINGS } = await import("../../src/feral/web/static/js/strings.js");
const { initPlayer } = await import("../../src/feral/web/static/js/player.js");

const MUSIC = hashOf(1), SUNO = hashOf(2);
const songs = [
  item(1, { media_kind: "audio", container: "mp3", width: null, height: null, duration: 210,
            name: "01 Album Track.mp3", artwork: true }),
  item(2, { media_kind: "audio", container: "mp3", width: null, height: null, duration: 180,
            name: "Regenzeit.mp3", tool: "suno" }),
];
const rowOf = (h) => document.querySelector(`#grid .arow[data-hash="${h}"]`);

const origCreate = document.createElement.bind(document);
document.createElement = (tag) => {
  if (tag !== "audio") return origCreate(tag);
  const el = origCreate("div");
  Object.assign(el, {
    paused: true, currentTime: 0, duration: NaN, src: "",
    play() { this.paused = false; this.dispatchEvent(new DomEvent("play")); return Promise.resolve(); },
    pause() { this.paused = true; this.dispatchEvent(new DomEvent("pause")); },
  });
  return el;
};

before(async () => {
  loadShell();
  serveLibrary(songs);
  mockApi.get("/api/stats", () => ({ total_items: 2, items_multi_location: 0, total_bytes: 1,
                                     library_configured: false, rankings: false, audio: true }));
  mockApi.get(/^\/api\/audio\/analysis\//, () => mockApi.status(404, {}));
  document.rectFor = (el) => (el.classList.contains("tile") ? { height: 65 } : null);
  document.getElementById("gridwrap").clientHeight = 1000;
  initLibraryView();
  initGallery();
  initAudioList();
  initPlayer();
  await flush(10);
});

test("Zeile: eingebettetes Bild nur bei normaler Musik, mit eigenem Tooltip", () => {
  const cov = rowOf(MUSIC).querySelector(".rcov");
  assert.ok(cov, "Miniatur vor dem Namen");
  assert.equal(cov.title, STRINGS.artworkTitle);
  assert.equal(rowOf(SUNO).querySelector(".rcov"), null, "Suno-Standardbild bleibt draußen");
});

test("Abspielleiste zeigt das eingebettete Bild des laufenden Songs", async () => {
  click(rowOf(MUSIC).querySelector(".pbtn"));
  await flush(5);
  const slot = document.getElementById("pbar").querySelector(".pcov");
  assert.equal(slot.hidden, false);
  assert.equal(slot.dataset.cover, MUSIC, "Vorschaubild des Songs selbst");
  click(rowOf(SUNO).querySelector(".pbtn"));
  await flush(5);
  assert.equal(slot.hidden, true, "Suno-Song ohne Cover: keine Miniatur");
  click(rowOf(SUNO).querySelector(".pbtn"));   // pausieren: sonst hält der Fortschritts-Takt Node offen
  await flush(5);
});

function fakeVideo(muted) {
  const v = document.createElement("video");
  Object.assign(v, { muted, paused: false, pause() { this.paused = true; } });
  document.body.appendChild(v);
  return v;
}
const barBtn = () => document.getElementById("pbar").querySelector('[data-act="play"]');

test("Stumme Vorschau-Videos lassen die Musik laufen, ein Video mit Ton pausiert sie", async () => {
  const quiet = fakeVideo(true);
  quiet.paused = true;
  click(rowOf(MUSIC).querySelector(".pbtn"));             // Song startet …
  await flush(5);
  assert.equal(quiet.paused, true, "(lief nicht)");
  quiet.paused = false;                                    // … Vorschau startet stumm
  quiet.dispatchEvent(new DomEvent("play"));
  await flush(5);
  assert.equal(barBtn().textContent, "❚❚", "Song läuft weiter, Knopf zeigt Pause");
  click(rowOf(MUSIC).querySelector(".pbtn"));             // anhalten …
  await flush(5);
  click(rowOf(MUSIC).querySelector(".pbtn"));             // … und wieder starten:
  await flush(5);
  assert.equal(quiet.paused, false, "stumme Vorschau läuft weiter");
  const loud = fakeVideo(false);
  loud.dispatchEvent(new DomEvent("play"));                // Video mit Ton (Lupe)
  await flush(5);
  assert.equal(barBtn().textContent, "▶", "Song pausiert, Knopf zeigt Play");
  quiet.remove(); loud.remove();   // der Song ist pausiert: Node endet sauber
});
