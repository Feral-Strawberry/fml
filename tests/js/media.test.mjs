// media.test.mjs — gemeinsame Medien-Weiche (#158, ADR 0083):
// EIN Helfer entscheidet <img>/<video>/<audio> bzw. den ehrlichen Hinweis;
// releaseVideos gibt auch <audio> frei; Galerie-Kachel und Detail-Panel
// zeigen Audio als ♪ mit Dauer und fragen kein Vorschaubild an.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, flush, item, serveLibrary } from "./harness.mjs";
import { DomEvent, Element } from "./dom.mjs";
import { mockApi } from "./apimock.mjs";
import { emit, on } from "./bus.mjs";

const api = await import("../../src/feral/web/static/js/api.js");
const { initDetail } = await import("../../src/feral/web/static/js/detail.js");
const { initLoupe } = await import("../../src/feral/web/static/js/loupe.js");

const song = item(7, { container: "flac", media_kind: "audio", width: null, height: null, duration: 187.4 });
const caf = item(8, { container: "caf", media_kind: "audio", width: null, height: null, duration: 5 });

before(() => {
  loadShell();
  serveLibrary([song, caf, item(9)]);
  mockApi.get("/api/tags", () => ({ tags: [] }));
  mockApi.get("/api/models", () => ({ models: [] }));
  initDetail();
  initLoupe();
});

test("fmtDuration: m:ss, h:mm:ss, leer ohne Dauer", () => {
  assert.equal(api.fmtDuration(187.4), "3:07");
  assert.equal(api.fmtDuration(3723), "1:02:03");
  assert.equal(api.fmtDuration(null), "");
});

test("mediaHtml: je Medienart das passende Element", () => {
  const holder = document.createElement("div");
  holder.innerHTML = api.mediaHtml(item(1), { image: 'class="x"' });
  assert.ok(holder.querySelector("img"));
  holder.innerHTML = api.mediaHtml(item(2, { media_kind: "video", container: "isobmff" }), { video: "controls" });
  assert.ok(holder.querySelector("video"));
  holder.innerHTML = api.mediaHtml(song);
  // Audio (A5 #162): der eigene Player auf der ♪-Bühne, ohne eigenes <audio>
  // (player.js spielt alles über EIN Element).
  const w = holder.querySelector(".audiostage .aplayer");
  assert.ok(w, "eigener Player auf der ♪-Bühne");
  assert.equal(holder.querySelector("audio"), null);
  assert.equal(w.dataset.hash, song.file_hash);
  assert.equal(w.dataset.container, "flac");
  assert.equal(holder.querySelector(".ptime").textContent, "0:00 / 3:07");
  assert.equal(api.kindLabel(song), "AUDIO");
  assert.ok(api.isTimed(song) && !api.isTimed(item(1)));
});

test("AIFF/CAF/ALAC spielen über /api/preview (FLAC-Proxy, A4 #161) — auch wenn der Browser das Format nicht kann", () => {
  const orig = Element.prototype.canPlayType;
  Element.prototype.canPlayType = () => "";
  try {
    assert.equal(api.displayUrl(caf), `/api/preview/${caf.file_hash}`);
    // auch Browser-Formate: der Server entscheidet
    assert.equal(api.displayUrl(song), `/api/preview/${song.file_hash}`);
    assert.ok(api.canPlay(caf), "Player bleibt bedienbar — der Proxy spielt");
  } finally {
    Element.prototype.canPlayType = orig;
  }
});

test("?native= nur, wenn der Browser AIFF/ALAC selbst spielt (Safari) — dann keine Kopie", () => {
  const aiff = item(9, { container: "aiff", media_kind: "audio", width: null, height: null });
  const m4a = item(10, { container: "isobmff", media_kind: "audio", width: null, height: null });
  const orig = Element.prototype.canPlayType;
  try {
    Element.prototype.canPlayType = () => "";                       // Chrome/Firefox
    assert.equal(api.displayUrl(aiff), `/api/preview/${aiff.file_hash}`);
    assert.equal(api.displayUrl(m4a), `/api/preview/${m4a.file_hash}`);
    Element.prototype.canPlayType = (t) => (t.includes("aiff") || t.includes("alac") ? "maybe" : "");
    assert.equal(api.displayUrl(aiff), `/api/preview/${aiff.file_hash}?native=aiff`);
    assert.equal(api.displayUrl(m4a), `/api/preview/${m4a.file_hash}?native=alac`);
    assert.equal(api.displayUrl(caf), `/api/preview/${caf.file_hash}`, "CAF fragt nie");
  } finally {
    Element.prototype.canPlayType = orig;
  }
});

test("fmtLoudness: Dezimalzeichen der Sprache, Stille als –", () => {
  assert.equal(api.fmtLoudness({ integrated: -14.23, lra: 5.3, true_peak: null }),
    "-14,2 LUFS · LRA 5,3 LU · True Peak – dBTP");
});

test("releaseVideos gibt auch <audio> frei", () => {
  const holder = document.createElement("div");
  holder.innerHTML = `<audio src="/api/preview/${song.file_hash}"></audio>`;
  const audio = holder.querySelector("audio");
  api.releaseVideos(holder);
  assert.equal(audio.getAttribute("src"), null);
});

test("Detail-Panel: Audio mit Player, AUDIO-Badge und Dauer; Klick auf den Player öffnet keine Lupe", async () => {
  const opened = [];
  on("loupe-open", (d) => opened.push(d));
  emit("selection-changed", { hash: song.file_hash, index: 0 });
  await flush();
  const panel = document.getElementById("panel");
  const player = panel.querySelector(".ppreview .aplayer");
  assert.ok(player);
  assert.equal(panel.querySelector(".ppreview audio"), null, "kein zweites <audio>, nie Autoplay");
  assert.ok(panel.querySelector(".pmeta").textContent.includes("AUDIO"));
  assert.ok(panel.querySelector(".pmeta").textContent.includes("3:07"));
  player.querySelector(".wv").dispatchEvent(new DomEvent("click", { bubbles: true }));
  // Audio hat keine Lupe (#162) — auch nicht per Klick neben den Player.
  panel.querySelector(".ppreview").dispatchEvent(new DomEvent("click", { bubbles: true }));
  assert.equal(opened.length, 0);
  assert.equal(panel.querySelector(".ppreview").hasAttribute("title"), false);
});

test("Lupe: Audio nur als Node-Graph, ohne Medienbühne und Einzelansicht; Bilder unverändert", async () => {
  const loupe = document.getElementById("loupe");
  emit("loupe-open", { hash: song.file_hash });                 // auch ohne mode: Graph
  await flush();
  assert.equal(loupe.hidden, false);
  assert.equal(loupe.querySelector("#lpSegImg").hidden, true);
  assert.equal(loupe.querySelector("#lpSegSingle").hidden, true);
  assert.equal(loupe.querySelector("#lpStage .aplayer"), null);
  assert.ok(loupe.querySelector("#lpWfBox"));
  emit("loupe-open", { hash: item(9).file_hash });              // Bild: alles wie gehabt
  await flush();
  assert.equal(loupe.querySelector("#lpSegImg").hidden, false);
  assert.equal(loupe.querySelector("#lpSegSingle").hidden, false);
  assert.ok(loupe.querySelector("#lpStage img"));
});

test("Detail-Panel: Lautheit kommt nach, auch wenn die Analyse erst entsteht (202)", async () => {
  let calls = 0;
  mockApi.get(`/api/audio/analysis/${song.file_hash}`, () => (++calls === 1
    ? mockApi.status(202)
    : { version: 1, loudness: { integrated: -9.04, lra: 6.1, true_peak: -0.3 } }));
  emit("selection-changed", { hash: caf.file_hash, index: 1 });
  await flush();
  emit("selection-changed", { hash: song.file_hash, index: 0 });
  await flush();
  const loud = () => document.getElementById("panel").querySelector("#pLoud").textContent;
  assert.ok(loud().includes("…"), "erst der Platzhalter");
  await new Promise((r) => setTimeout(r, 600));
  await flush();
  assert.equal(loud(), "-9,0 LUFS · LRA 6,1 LU · True Peak -0,3 dBTP");
  assert.equal(calls, 2);
});
