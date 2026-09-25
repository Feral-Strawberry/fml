// player.test.mjs — eigener Audio-Player (A5 #162, ADR 0087): eigener
// Abspielkopf je Zeile, gemeinsame Zeitachse, Lautheitsangleich, Loop,
// Tempo, „Alle abspielen" mit eingefrorener Reihenfolge, Abspielleiste über
// den Ansichtswechsel, Medientasten, eingebetteter Player im Detailpanel.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, keydown, click, flush, item, hashOf, serveLibrary } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { DomEvent } from "./dom.mjs";

localStorage.setItem("feral-view", "audio");

// Medientasten: Attrappe, die die Handler mitschreibt.
const actions = {};
globalThis.navigator.mediaSession = {
  metadata: null, playbackState: "none",
  setActionHandler(name, fn) { actions[name] = fn; },
  setPositionState() {},
};
globalThis.MediaMetadata = class { constructor(m) { Object.assign(this, m); } };

// Fake-<audio>: der DOM-Stub spielt nichts ab; Zustandswechsel als Ereignis.
let audio = null;
const played = [];
const origCreate = document.createElement.bind(document);
document.createElement = (tag) => {
  if (tag !== "audio") return origCreate(tag);
  const el = origCreate("div");
  Object.assign(el, {
    paused: true, currentTime: 0, duration: NaN, volume: 1, playbackRate: 1,
    play() { this.paused = false; played.push(this.src); this.dispatchEvent(new DomEvent("play")); return Promise.resolve(); },
    pause() { this.paused = true; this.dispatchEvent(new DomEvent("pause")); },
  });
  audio = el;
  return el;
};
const fire = (type) => {
  if (type === "ended") audio.paused = true;                          // wie der Browser
  audio.dispatchEvent(new DomEvent(type));
};

const { matchGainDb, barPeaks, rulerTicks, fmtDb } = await import("../../src/feral/web/static/js/waveform.js");
const player = await import("../../src/feral/web/static/js/player.js");
const { initAudioList } = await import("../../src/feral/web/static/js/audiolist.js");
const { initLibraryView } = await import("../../src/feral/web/static/js/libview.js");
const { initGallery } = await import("../../src/feral/web/static/js/gallery.js");
const { mediaHtml } = await import("../../src/feral/web/static/js/api.js");
const { initSingleView } = await import("../../src/feral/web/static/js/singleview.js");

const song = (n, dur, name) => item(n, { media_kind: "audio", container: "mp3", width: null,
  height: null, duration: dur, name, tool: "suno" });
const songs = [song(1, 200, "Regenzeit A.mp3"), song(2, 100, "Regenzeit B.mp3"), song(3, 150, "Regenzeit C.mp3")];
const grid = () => document.getElementById("grid");
const row = (n) => grid().querySelector(`.arow[data-hash="${hashOf(n)}"]`);
const bar = () => document.getElementById("pbar");

// Analyse (A4): Song 1 laut (-9 LUFS), Song 2 leise mit wenig Luft (-20, TP -3).
const analysis = (integrated, tp) => ({
  version: 1, duration: 10, loudness: { integrated, lra: 4, true_peak: tp },
  waveform: { buckets: 4, seconds_per_bucket: 2.5, bands: ["low", "mid", "high"],
    low: { min: [-100, -200, -300, -400], max: [100, 16384, 300, 400] },
    mid: { min: [0, 0, 0, 0], max: [50, 50, 50, 32767] },
    high: { min: [0, 0, 0, 0], max: [1, 2, 3, 4] } },
});

before(async () => {
  loadShell();
  const lib = serveLibrary(songs);
  mockApi.get("/api/items", ({ params }) => {
    const offset = parseInt(params.get("offset") || "0", 10);
    return { total: params.get("total") === "1" ? lib.items.length : -1, offset,
             items: lib.items.slice(offset, offset + 200),
             ...(params.get("total") === "1" ? { max_duration: 200 } : {}) };
  });
  mockApi.get(/^\/api\/audio\/analysis\//, ({ path }) => {
    const h = path.split("/").pop();
    return h === hashOf(1) ? analysis(-9, -0.5) : h === hashOf(2) ? analysis(-20, -3)
      : mockApi.status(404, { detail: "nicht messbar" });
  });
  mockApi.get("/api/stats", () => ({ total_items: 3, items_multi_location: 0, total_bytes: 1,
    library_configured: false, rankings: false, audio: true }));
  mockApi.get("/api/folders", () => ({ folders: [] }));
  document.rectFor = (el) => (el.classList.contains("tile") ? { height: 65 }
    : el.classList.contains("wv") ? { left: 0, width: 400 } : null);
  document.getElementById("gridwrap").clientHeight = 1000;
  initLibraryView();
  initGallery();
  player.initPlayer();
  initAudioList();
  initSingleView();
  (await import("./bus.mjs")).emit("audio-enabled", { enabled: true });   // sonst: Sidebar
  await flush(10);
});

test("Angleich: Lautes wird abgesenkt, Leises nur bis True Peak −1 dBTP angehoben", () => {
  assert.equal(matchGainDb({ integrated: -9, true_peak: -0.5 }), -5);
  assert.equal(matchGainDb({ integrated: -20, true_peak: -3 }), 2);      // statt +6
  assert.equal(matchGainDb({ integrated: -20, true_peak: -12 }), 6);
  assert.equal(matchGainDb({ integrated: null, true_peak: null }), 0);   // Stille
  assert.equal(matchGainDb(undefined), 0);
  assert.equal(fmtDb(-5, "de"), "−5,0");
  assert.equal(fmtDb(2, "en"), "+2.0");
});

test("Wellenform: je Balken das Maximum seiner Buckets, Anteil an Vollaussteuerung", () => {
  const peaks = barPeaks(analysis(-9, -1), 2);
  assert.equal(peaks.length, 2);
  assert.equal(peaks[0][0], 16384 / 32768);        // Bass: Spitze im 2. Bucket
  assert.equal(peaks[1][1], 32767 / 32768);        // Mitten
  assert.deepEqual(barPeaks(null, 10), []);
  assert.deepEqual(rulerTicks(200), [0, 30, 60, 90, 120, 150, 180]);
  assert.deepEqual(rulerTicks(0), []);
});

test("Liste: Lineal der gemeinsamen Zeitachse und Lautheit je Zeile", async () => {
  const ticks = document.querySelectorAll("#listhead .ruler span").map((s) => s.textContent);
  assert.deepEqual(ticks, ["0:00", "0:30", "1:00", "1:30", "2:00", "2:30", "3:00"]);
  // Legende: was die Farben bedeuten, nicht nur welche (Tooltip erklärt mehr).
  const legend = document.querySelector("#listhead .wlegend");
  assert.match(legend.textContent, /Bass Kick, Bassline/);
  assert.match(legend.getAttribute("title"), /dominiert/);
  await flush();
  assert.equal(row(1).querySelector(".rlufs").textContent, "-9,0");
  assert.equal(row(3).querySelector(".rlufs").textContent, "–");      // nicht messbar
});

test("Klick auf die Welle: Stelle auf der gemeinsamen Achse, hinter dem Songende nichts", async () => {
  // Song 2 (100 s) auf der 200-s-Achse: 25 % der Breite = 50 s.
  click(row(2).querySelector(".wv"), { clientX: 100 });
  await flush();
  assert.equal(player.currentHash(), hashOf(2));
  fire("loadedmetadata");
  assert.equal(audio.currentTime, 50);
  const n = played.length;
  click(row(2).querySelector(".wv"), { clientX: 300 });               // 150 s > 100 s
  await flush();
  assert.equal(played.length, n);
});

test("Eigener Abspielkopf je Zeile: Wechsel pausiert und merkt die Stelle", async () => {
  audio.currentTime = 42;
  click(row(1).querySelector(".pbtn"));
  await flush();
  assert.equal(player.currentHash(), hashOf(1));
  assert.equal(player.positionOf(hashOf(2)), 42);
  assert.ok(row(1).classList.contains("playing") && !row(2).classList.contains("playing"));
  assert.equal(row(2).querySelector(".ph").hidden, false);           // Kopf bleibt sichtbar stehen
  audio.currentTime = 70;
  click(row(2).querySelector(".pbtn"));                              // zurück: Refrain gegen Refrain
  await flush();
  fire("loadedmetadata");
  assert.equal(audio.currentTime, 42);
  assert.equal(player.positionOf(hashOf(1)), 70);
});

test("Pfeiltasten: ausgewählte Zeile ±5 s, Shift ±1 s — auch ohne dass sie spielt", async () => {
  const { emit } = await import("./bus.mjs");
  emit("selection-changed", { hash: hashOf(1), index: 0 });          // Song 1 ist nicht geladen
  keydown("ArrowRight");
  await flush();
  assert.equal(player.positionOf(hashOf(1)), 75);
  keydown("ArrowLeft", { shiftKey: true });
  await flush();
  assert.equal(player.positionOf(hashOf(1)), 74);
  assert.equal(player.currentHash(), hashOf(2));                     // nichts umgeschaltet
  // Leertaste nach einem MAUS-Klick auf einen Knopf (⏮, ≈ Lautheit …):
  // Play/Pause der Zeile, nicht noch einmal der Knopf (#162).
  const btn = bar().querySelector('[data-act="match"]');
  btn.focus();
  const before = player.matchOn();
  keydown(" ", { target: btn });
  await flush();
  assert.equal(player.matchOn(), before);                            // Knopf nicht erneut
  assert.notEqual(document.activeElement, btn);                      // Fokus weg
  assert.equal(player.playingHash(), hashOf(1));                     // ausgewählte Zeile spielt
  keydown(" ");
  await flush();
  assert.equal(player.playingHash(), null);
  // Enter öffnet für Songs keine Einzelansicht (#162).
  keydown("Enter");
  await flush();
  assert.equal(document.getElementById("single").hidden, true);
});

test("Neumalen während der Wiedergabe lässt ❚❚ und die Leiste unangetastet (#211)", async () => {
  click(row(1).querySelector(".pbtn"));
  await flush();
  assert.equal(player.playingHash(), hashOf(1));
  const btn = row(1).querySelector(".pbtn");
  const barBtn = bar().querySelector('[data-act="play"]');
  const tempo = bar().querySelector('[data-act="tempo"]');
  // Der Textknoten unter dem Mauszeiger darf nicht ersetzt werden: sonst
  // verwirft der Browser einen Klick, dessen mousedown davor lag.
  const before = [btn.childNodes[0], barBtn.childNodes[0], tempo.childNodes[0]];
  assert.equal(btn.textContent, "❚❚");
  player.repaint();
  player.repaint(hashOf(1));
  await flush();
  assert.deepEqual([btn.childNodes[0], barBtn.childNodes[0], tempo.childNodes[0]], before);
  click(btn);                                                        // anhalten klappt
  await flush();
  assert.equal(player.playingHash(), null);
  assert.equal(btn.textContent, "▶");
});

test("Lautheitsangleich: Faktor aus der Analyse, global abschaltbar und gemerkt", async () => {
  click(row(1).querySelector(".pbtn"));
  await flush();
  assert.ok(Math.abs(audio.volume - 10 ** (-5 / 20)) < 1e-9);         // ohne Web Audio: nur absenken
  assert.equal(bar().querySelector('[data-act="match"] .gain').textContent, "−5,0 dB");
  click(bar().querySelector('[data-act="match"]'));
  await flush();
  assert.equal(audio.volume, 1);
  assert.equal(localStorage.getItem("feral-audio-match"), "0");
  click(bar().querySelector('[data-act="match"]'));
  await flush();
});

test("Tempo ohne Tonhöhe und A–B-Loop", async () => {
  click(bar().querySelector('[data-act="tempo"]'));
  await flush();
  assert.equal(audio.playbackRate, 1.25);
  assert.equal(audio.preservesPitch, true);
  click(bar().querySelector('[data-act="tempo"]'));
  assert.equal(audio.playbackRate, 1.5);                             // schneller, nie langsamer
  click(bar().querySelector('[data-act="tempo"]'));
  assert.equal(audio.playbackRate, 1);
  audio.currentTime = 10;
  click(bar().querySelector('[data-act="loop"]'));                   // A
  audio.currentTime = 20;
  click(bar().querySelector('[data-act="loop"]'));                   // B
  audio.currentTime = 20.3;
  fire("timeupdate");
  assert.equal(audio.currentTime, 10);
  click(bar().querySelector('[data-act="loop"]'));                   // aus
  audio.currentTime = 25;
  fire("timeupdate");
  assert.equal(audio.currentTime, 25);
});

test("Scheitert die Wiedergabe (auch der Proxy), sagen es Zeile, Player und Leiste ehrlich", async () => {
  click(row(3).querySelector(".pbtn"));
  await flush();
  fire("error");
  await flush();
  assert.equal(row(3).querySelector(".pbtn").disabled, true);
  assert.match(bar().querySelector(".q").textContent, /nicht möglich/);
  const box = document.getElementById("panel");
  box.innerHTML = mediaHtml({ ...songs.find((s) => s.file_hash === hashOf(3)), locations: [] });
  player.repaint();
  await flush();
  assert.equal(box.querySelector(".pnote").hidden, false);
  click(bar().querySelector('[data-act="close"]'));
  await flush();
});

test("Alle abspielen: Reihenfolge eingefroren, läuft durch, Leiste über den Ansichtswechsel", async () => {
  click(document.getElementById("playAllBtn"));
  await flush(10);
  assert.equal(player.currentHash(), hashOf(1));
  assert.match(bar().querySelector(".q").textContent, /1\/3/);
  songs.reverse();                                                   // Liste ändert sich danach …
  fire("ended");
  await flush();
  assert.equal(player.currentHash(), hashOf(2));                     // … die Reihenfolge nicht
  // Wechsel in die Galerie: die Wiedergabe läuft, die Leiste bleibt.
  click(document.querySelector('#viewseg button[data-view="galerie"]'));
  await flush(10);
  assert.equal(player.playingHash(), hashOf(2));
  assert.equal(bar().hidden, false);
  assert.equal(document.getElementById("playAllBtn").hidden, true);
  // Medientasten: nächster Titel.
  actions.nexttrack();
  await flush();
  assert.equal(player.currentHash(), hashOf(3));
  assert.equal(navigator.mediaSession.metadata.title, "Regenzeit C");
  fire("ended");                                                     // Ende der Reihe
  await flush();
  assert.equal(player.playingHash(), null);
  assert.match(bar().querySelector(".q").textContent, /Einzeln/);
});

test("Eingebetteter Player (Detailpanel): eigener Kopf, kein <audio>, ✕ beendet alles", async () => {
  const d = { file_hash: hashOf(1), container: "mp3", media_kind: "audio", duration: 200,
              locations: [{ path: "/lib/Regenzeit A.mp3" }], interpreted: [] };
  const box = document.getElementById("panel");
  box.innerHTML = mediaHtml(d);
  assert.equal(box.querySelectorAll("audio").length, 0);
  click(box.querySelector(".aplayer .pbtn"));
  await flush();
  assert.equal(player.playingHash(), hashOf(1));
  assert.equal(box.querySelector(".aplayer .pbtn").textContent, "❚❚");
  assert.equal(box.querySelector(".pgain").textContent, "angeglichen −5,0 dB");
  click(bar().querySelector('[data-act="close"]'));
  await flush();
  assert.equal(bar().hidden, true);
  assert.equal(player.currentHash(), null);
  assert.equal(audio.getAttribute("src"), null);                     // Verbindung frei (#89)
});
