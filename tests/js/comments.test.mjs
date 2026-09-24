// comments.test.mjs — Zeitkommentare (Audio A6, #163, ADR 0088): Zahl und
// Pins in der Listenzeile, Taste K an der Abspielstelle der ausgewählten
// Zeile, Pin-Klick springt genau dorthin, Hover zeigt den Text, Abschnitt im
// Detailpanel (Liste, Löschen), 💬 in der Abspielleiste.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, keydown, click, flush, item, hashOf, serveLibrary } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { DomEvent, MouseEvent } from "./dom.mjs";

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
const { initComments } = await import("../../src/feral/web/static/js/comments.js");
const { initAudioList } = await import("../../src/feral/web/static/js/audiolist.js");
const { initLibraryView } = await import("../../src/feral/web/static/js/libview.js");
const { initGallery } = await import("../../src/feral/web/static/js/gallery.js");
const { initDetail } = await import("../../src/feral/web/static/js/detail.js");
const { emit } = await import("./bus.mjs");

const song = (n, dur, name, comments) => item(n, { media_kind: "audio", container: "mp3", width: null,
  height: null, duration: dur, name, tool: "suno", ...(comments ? { comments } : {}) });
const songs = [
  song(1, 200, "Regenzeit A.mp3", [{ id: 1, at_ms: 10_000, text: "Intro" }, { id: 2, at_ms: 100_000, text: "Chorus" }]),
  song(2, 100, "Regenzeit B.mp3"),
];
const grid = () => document.getElementById("grid");
const row = (n) => grid().querySelector(`.arow[data-hash="${hashOf(n)}"]`);
const posted = [];

before(async () => {
  loadShell();
  const lib = serveLibrary(songs);
  mockApi.get("/api/items", ({ params }) => ({
    total: params.get("total") === "1" ? lib.items.length : -1, offset: 0, items: lib.items,
    ...(params.get("total") === "1" ? { max_duration: 200 } : {}),
  }));
  mockApi.get(/^\/api\/audio\/analysis\//, () => mockApi.status(404, { detail: "nicht messbar" }));
  mockApi.get("/api/stats", () => ({ total_items: 2, items_multi_location: 0, total_bytes: 1,
    library_configured: false, rankings: false, audio: true }));
  mockApi.get("/api/folders", () => ({ folders: [] }));
  mockApi.get("/api/tags", () => ({ tags: [] }));
  // Kommentar-API: eine Liste je Song, jede Antwort liefert sie ganz.
  const db = new Map(songs.map((s) => [s.file_hash, [...(s.comments || [])]]));
  let next = 10;
  const sorted = (h) => ({ comments: db.get(h).sort((a, b) => a.at_ms - b.at_ms) });
  mockApi.on("POST", /^\/api\/item\/[0-9a-f]+\/comments$/, ({ path, body }) => {
    const h = path.split("/")[3];
    posted.push({ h, ...body });
    db.get(h).push({ id: next++, at_ms: body.at_ms, text: body.text });
    return sorted(h);
  });
  mockApi.on("DELETE", /^\/api\/item\/[0-9a-f]+\/comments\/\d+$/, ({ path }) => {
    const [, , , h, , id] = path.split("/");
    db.set(h, db.get(h).filter((c) => String(c.id) !== id));
    return sorted(h);
  });
  mockApi.get(/^\/api\/item\/[0-9a-f]+\/comments$/, ({ path }) => sorted(path.split("/")[3]));
  document.rectFor = (el) => (el.classList.contains("tile") ? { height: 65 }
    : el.classList.contains("wv") ? { left: 0, width: 400, top: 200, bottom: 218 } : null);
  document.getElementById("gridwrap").clientHeight = 1000;
  initLibraryView();
  initGallery();
  player.initPlayer();
  initAudioList();
  initComments();
  initDetail();
  emit("audio-enabled", { enabled: true });
  await flush(10);
});

const pins = (n) => row(n).querySelectorAll(".wv .pin");

test("Listenzeile: Zahl der Kommentare und Pins auf der gemeinsamen Zeitachse", async () => {
  player.repaint();
  await flush();
  assert.equal(row(1).querySelector(".rcom").textContent, "2");
  assert.ok(row(1).querySelector(".rcom").classList.contains("has"));
  assert.equal(row(2).querySelector(".rcom").textContent, "–");
  assert.deepEqual(pins(1).map((p) => p.getAttribute("style")), ["left:5%", "left:50%"]);   // 10 s / 100 s auf 200 s
  assert.equal(pins(2).length, 0);
  assert.equal(document.querySelector("#listhead").textContent.includes("💬"), true);
});

test("Hover über einem Pin zeigt Stelle und Text", () => {
  pins(1)[1].dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
  const tip = document.getElementById("pintip");
  assert.equal(tip.hidden, false);
  assert.equal(tip.textContent, "1:40Chorus");
  row(1).querySelector(".rname").dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
  assert.equal(tip.hidden, true);
});

test("Klick auf einen Pin spielt genau ab der Kommentarstelle", async () => {
  click(pins(1)[1], { clientX: 3 });          // Mausposition egal: der Pin zählt
  await flush();
  audio.dispatchEvent(new DomEvent("loadedmetadata"));
  assert.equal(player.currentHash(), hashOf(1));
  assert.equal(player.positionOf(hashOf(1)), 100);
  // Beim geladenen Song blendet der Kommentar ein: 1 s vorher bis 5 s danach.
  const shown = () => row(1).querySelectorAll(".wv .plabel.on").map((l) => l.textContent);
  player.repaint();
  await flush();
  assert.deepEqual(shown(), ["1:40Chorus"]);
  for (const [t, want] of [[98.9, []], [99, ["1:40Chorus"]], [104.9, ["1:40Chorus"]], [105, []], [9.5, ["0:10Intro"]]]) {
    audio.currentTime = t;
    player.repaint();
    await flush();
    assert.deepEqual(shown(), want, `bei ${t} s`);
  }
  assert.equal(row(2).querySelectorAll(".wv .plabel.on").length, 0);   // nicht geladen: nichts
  player.pause();
});

test("Mehrere Kommentare zugleich stapeln sich nach oben", async () => {
  const { shownAt } = await import("../../src/feral/web/static/js/comments.js");
  const list = [{ id: 1, at_ms: 10_000 }, { id: 2, at_ms: 12_000 }, { id: 3, at_ms: 30_000 }];
  assert.deepEqual(shownAt(list, 11).map((c) => c.id), [1, 2]);
  assert.deepEqual(shownAt(list, null), []);
});

test("K: Kommentar an der Abspielstelle der ausgewählten Zeile, Enter speichert", async () => {
  emit("selection-changed", { hash: hashOf(2), index: 1 });
  keydown("ArrowRight");                        // Song 2: eigener Abspielkopf auf 0:05
  await flush();
  keydown("k");
  const box = document.getElementById("comprompt");
  assert.ok(box, "Eingabe offen");
  assert.equal(box.querySelector(".t").textContent, "0:05");
  const input = box.querySelector("input");
  input.value = "Strophe 2";
  keydown("Enter", { target: input });
  await flush();
  assert.equal(document.getElementById("comprompt"), null);
  assert.deepEqual(posted.at(-1), { h: hashOf(2), at_ms: 5000, text: "Strophe 2" });
  player.repaint();
  await flush();
  assert.equal(row(2).querySelector(".rcom").textContent, "1");
  assert.equal(pins(2).length, 1);
  // Esc verwirft, leerer Text speichert nichts.
  keydown("K");
  const esc = document.getElementById("comprompt").querySelector("input");
  esc.value = "weg";
  keydown("Escape", { target: esc });
  await flush();
  assert.equal(document.getElementById("comprompt"), null);
  assert.equal(posted.length, 1);
});

test("Detailpanel: Abschnitt listet, Klick springt, ✕ löscht", async () => {
  click(row(1));
  await flush(5);
  const sec = document.getElementById("pComs");
  assert.ok(sec, "Abschnitt Zeitkommentare");
  const rows = sec.querySelectorAll(".com");
  assert.deepEqual(rows.map((r) => r.querySelector(".t").textContent), ["0:10", "1:40"]);
  click(rows[0].querySelector(".ctext"));
  await flush();
  assert.equal(player.positionOf(hashOf(1)), 10);
  player.pause();
  click(rows[1].querySelector(".x"));
  await flush();
  assert.deepEqual(document.getElementById("pComs").querySelectorAll(".com .ctext").map((c) => c.textContent), ["Intro"]);
  player.repaint();
  await flush();
  assert.equal(row(1).querySelector(".rcom").textContent, "1");
  assert.equal(pins(1).length, 1);
});

test("💬 in der Abspielleiste: Kommentar für den geladenen Song", async () => {
  const bar = document.getElementById("pbar");
  click(bar.querySelector('[data-act="comment"]'));
  const input = document.getElementById("comprompt").querySelector("input");
  input.value = "Bridge";
  keydown("Enter", { target: input });
  await flush();
  assert.equal(posted.at(-1).h, hashOf(1));
  assert.equal(posted.at(-1).text, "Bridge");
});
