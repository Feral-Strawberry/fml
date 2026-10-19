// clip.test.mjs — Ausschnitt-Ansicht (Modul, ADR 0105, #271): Bereich
// rechnen (Zehntel, Fenster verschieben, „hier"), Öffnen aus dem Panel,
// Sperre mit Grund, Tasten gehören der Ansicht, Ziehen in der Zeitleiste,
// Exportieren mit Kennung und Ergebniszeile mit „📂 zeigen".

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, keydown, click, flush, item, hashOf, idleStatus } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit } from "./bus.mjs";
import { DomEvent } from "./dom.mjs";

// Fake-Medien: der DOM-Stub spielt nichts ab; Zustandswechsel als Ereignis.
const origCreate = document.createElement.bind(document);
let media = null;
document.createElement = (tag) => {
  const el = origCreate(tag);
  if (tag !== "audio" && tag !== "video") return el;
  Object.assign(el, {
    paused: true, currentTime: 0, duration: NaN,
    play() { this.paused = false; this.dispatchEvent(new DomEvent("play")); return Promise.resolve(); },
    pause() { this.paused = true; this.dispatchEvent(new DomEvent("pause")); },
    load() {},
  });
  media = el;
  return el;
};

const S = "../../src/feral/web/static/js/";
const { initClip, parseTime, fmtTime, moveRange, dragStart, dragEnd, markStart, markEnd,
        setLength, initialRange } = await import(`${S}clip.js`);
const { clipButtonHtml } = await import(`${S}detail.js`);
const { pollOnce } = await import(`${S}status.js`);

const song = { ...item(1, { container: "flac", media_kind: "audio", duration: 60 }), name: "song.flac" };
const video = { ...item(2, { container: "isobmff", media_kind: "video", duration: 8 }), name: "take.mp4" };
const root = () => document.getElementById("clip");
const q = (sel) => root().querySelector(sel);
const val = (sel) => q(sel).value;
const starts = () => mockApi.calls.filter((c) => c.method === "POST" && c.path.startsWith("/api/clip/"));
let state;
let status;
let view;

const okState = (extra = {}) => ({
  available: true, reason: null, root: "/exp", target: "/exp/2026-10-11", encoder: "ok",
  outputs: ["audio"], kind: "audio", duration: 60, name: "song.flac", ...extra });

async function open(it) {
  emit("clip-open", { item: it });
  await flush();
}

before(async () => {
  loadShell();
  status = idleStatus();
  mockApi.get("/api/status", () => status);
  mockApi.get(/^\/api\/clip\/[0-9a-f]+$/, () => state);
  mockApi.post(/^\/api\/clip\/[0-9a-f]+$/, ({ body }) => ({
    queued: true, target: "/exp/2026-10-11",
    files: body.outputs.map((o) => `song ${o}.wav`) }));
  mockApi.post("/api/export/reveal", () => ({ revealed: "x", selected: true }));
  mockApi.get(/^\/api\/audio\/analysis\//, () => mockApi.status(404, { detail: "keine" }));
  view = initClip();
  await pollOnce();               // erster Poll: Ausgangsstand, keine Flanke
});

test("Zeiten: lesen in jeder Schreibweise, zeigen immer mit Zehntel", () => {
  assert.equal(parseTime("1:12.5"), 72.5);
  assert.equal(parseTime("72,5"), 72.5);
  assert.equal(parseTime("1:02:03"), 3723);
  assert.equal(parseTime("abc"), null);
  assert.equal(parseTime(""), null);
  assert.equal(fmtTime(12), "0:12.0");
  assert.equal(fmtTime(72.54), "1:12.5");
  assert.equal(fmtTime(3723.5), "1:02:03.5");
});

test("Bereich: Fenster verschieben hält die Länge, die Datei begrenzt", () => {
  const r = { a: 10, b: 20 };
  assert.deepEqual(moveRange(r, 26.04, 60), { a: 26, b: 36 });
  assert.deepEqual(moveRange(r, 55, 60), { a: 50, b: 60 });       // am Ende angestoßen
  assert.deepEqual(moveRange(r, -3, 60), { a: 0, b: 10 });
  assert.deepEqual(dragStart(r, 25), { a: 19.9, b: 20 });         // Griff schiebt den anderen nicht
  assert.deepEqual(dragEnd(r, 99, 60), { a: 10, b: 60 });
});

test("„hier“ hinter dem Ende bzw. vor dem Anfang nimmt das Fenster mit", () => {
  const r = { a: 10, b: 20 };
  assert.deepEqual(markStart(r, 12.5, 60), { a: 12.5, b: 20 });
  assert.deepEqual(markStart(r, 30, 60), { a: 30, b: 40 });
  assert.deepEqual(markEnd(r, 15, 60), { a: 10, b: 15 });
  assert.deepEqual(markEnd(r, 8, 60), { a: 0, b: 10 });           // Ende bei 8 ginge vor die Datei
  assert.deepEqual(markEnd({ a: 20, b: 25 }, 12, 60), { a: 7, b: 12 });
});

test("Länge eintippen: das Ende rückt nach, am Dateiende der Anfang", () => {
  assert.deepEqual(setLength({ a: 10, b: 20 }, 5, 60), { a: 10, b: 15 });
  assert.deepEqual(setLength({ a: 55, b: 58 }, 10, 60), { a: 50, b: 60 });
  assert.deepEqual(setLength({ a: 0, b: 5 }, 0, 60), { a: 0, b: 0.1 });
});

test("Startbereich: A–B-Schleife des Players, sonst 10 s ab der Abspielstelle", () => {
  assert.deepEqual(initialRange({ duration: 60, position: 0 }), { a: 0, b: 10 });
  assert.deepEqual(initialRange({ duration: 60, position: 33.33 }), { a: 33.3, b: 43.3 });
  assert.deepEqual(initialRange({ duration: 60, position: 58 }), { a: 50, b: 60 });
  assert.deepEqual(initialRange({ duration: 4, position: 0 }), { a: 0, b: 4 });
  assert.deepEqual(initialRange({ duration: 60, loop: { a: 12, b: 22 } }), { a: 12, b: 22 });
  assert.deepEqual(initialRange({ duration: 60, position: 5, loop: { a: 12, b: null } }), { a: 5, b: 15 });
});

test("Knopf im Panel: nur mit Modul, nur Video und Song, gesperrt ohne Wiedergabe", () => {
  assert.equal(clipButtonHtml(song, false), "");
  assert.equal(clipButtonHtml(item(3), true), "");
  assert.match(clipButtonHtml(song, true), /id="pClip"\s+title=/);
  assert.match(clipButtonHtml({ ...song, duration: null }, true), /id="pClip" disabled/);
});

test("Ohne Export-Ordner: Ansicht offen, Exportieren gesperrt, der Grund steht da", async () => {
  state = okState({ available: false, target: null, reason: { key: "errExportNoRoot" } });
  await open(song);
  assert.equal(root().hidden, false);
  assert.equal(q("#clGo").disabled, true);
  assert.match(q("#clMsg").textContent, /Kein Export-Ordner eingerichtet/);
  keydown("Escape");
  assert.equal(root().hidden, true);
  assert.equal(view.isOpen(), false);
});

test("Song: Felder zeigen den Startbereich, Länge eintippen verschiebt das Ende", async () => {
  state = okState();
  await open(song);
  assert.deepEqual([val("#clA"), val("#clB"), val("#clLen")], ["0:00.0", "0:10.0", "10.0"]);
  assert.equal(q("#clGo").disabled, false);
  assert.equal(q("#clOut").textContent, "Ton (WAV)");
  assert.equal(q("#clTarget").textContent, "/exp/2026-10-11");

  q("#clLen").value = "4,5";
  q("#clLen").dispatchEvent(new DomEvent("change", { bubbles: true }));
  assert.deepEqual([val("#clA"), val("#clB"), val("#clLen")], ["0:00.0", "0:04.5", "4.5"]);
  q("#clA").value = "0:20";
  q("#clA").dispatchEvent(new DomEvent("change", { bubbles: true }));
  assert.deepEqual([val("#clA"), val("#clB")], ["0:20.0", "0:24.5"]);   // hinter dem Ende: Fenster wandert
  assert.equal(media.currentTime, 20);                                  // Anhören am neuen Anfang
  view.close();
});

test("Tasten gehören der Ansicht: I/O, Pfeile, Leertaste, nichts sickert durch", async () => {
  state = okState();
  await open(song);
  const leaked = [];
  const spy = (e) => leaked.push(e.key);
  document.addEventListener("keydown", spy);

  media.currentTime = 30;
  keydown("i");
  assert.deepEqual([val("#clA"), val("#clB")], ["0:30.0", "0:40.0"]);
  media.currentTime = 36;
  keydown("o");
  assert.deepEqual([val("#clA"), val("#clB")], ["0:30.0", "0:36.0"]);
  assert.equal(media.currentTime, 34);                 // zwei Sekunden vor dem neuen Ende
  keydown("ArrowRight");                               // der zuletzt angefasste Griff: das Ende
  assert.equal(val("#clB"), "0:36.1");
  keydown("ArrowLeft", { shiftKey: true });
  assert.equal(val("#clB"), "0:35.1");
  keydown(" ");
  assert.equal(media.paused, false);
  keydown(" ");
  assert.equal(media.paused, true);
  keydown("p");                                        // Panel wegklappen der Galerie: nicht hier
  assert.deepEqual(leaked, []);

  document.removeEventListener("keydown", spy);
  view.close();
});

test("Zeitleiste: in der Mitte ziehen verschiebt, Griff ändert, Klick daneben springt nur", async () => {
  state = okState();
  await open(song);
  const track = q("#clTrack");
  track._rect = { left: 0, width: 600 };               // 10 px = 1 s
  const pointer = (type, target, x) =>
    target.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, clientX: x, pointerId: 1 }));

  pointer("pointerdown", q("#clRange"), 60);           // bei 6 s im Bereich 0–10 gegriffen
  pointer("pointermove", track, 260);
  pointer("pointerup", track, 260);
  assert.deepEqual([val("#clA"), val("#clB")], ["0:20.0", "0:30.0"]);

  pointer("pointerdown", q(".clh.b"), 300);
  pointer("pointermove", track, 345);
  pointer("pointerup", track, 345);
  assert.deepEqual([val("#clA"), val("#clB"), val("#clLen")], ["0:20.0", "0:34.5", "14.5"]);

  pointer("pointerdown", track, 500);                  // daneben: nur die Abspielstelle
  pointer("pointerup", track, 500);
  assert.equal(media.currentTime, 50);
  assert.deepEqual([val("#clA"), val("#clB")], ["0:20.0", "0:34.5"]);
  view.close();
});

test("Video: Häkchen je Ausgabe, die Wahl bleibt gemerkt; ohne H.264 nur Ton", async () => {
  state = okState({ outputs: ["av", "video", "audio"], kind: "video", duration: 8, name: "take.mp4" });
  await open(video);
  const boxes = () => [...root().querySelectorAll("#clOut input")];
  assert.deepEqual(boxes().map((b) => [b.value, b.checked]), [["av", true], ["video", false], ["audio", false]]);
  assert.deepEqual([val("#clA"), val("#clB")], ["0:00.0", "0:08.0"]);    // kürzer als 10 s: ganz
  boxes()[0].checked = false;
  boxes()[2].checked = true;
  q("#clOut").dispatchEvent(new DomEvent("change", { bubbles: true }));
  view.close();

  state = okState({ outputs: ["av", "video", "audio"], kind: "video", duration: 8, encoder: "no-h264" });
  await open(video);
  assert.deepEqual(boxes().map((b) => [b.value, b.checked, b.disabled]),
    [["av", false, true], ["video", false, true], ["audio", true, false]]);
  assert.match(q("#clMsg").textContent, /kein H\.264/);
  assert.equal(q("#clGo").disabled, false);            // Ton geht
  view.close();
  localStorage.removeItem("feral-clip-outputs");
});

test("Andere Videos geben ihre Verbindung ab und bekommen sie beim Schließen zurück (#89)", async () => {
  const other = origCreate("video");
  other.setAttribute("src", `/api/media/${hashOf(2)}`);
  other.load = () => {};
  document.getElementById("panel").appendChild(other);
  state = okState({ outputs: ["video"], kind: "video", duration: 8 });
  await open(video);
  assert.equal(other.getAttribute("src"), null);
  assert.equal(q("#clOut").textContent, "Video (MP4), die Datei hat keine Tonspur");
  keydown("Escape");
  assert.equal(other.getAttribute("src"), `/api/media/${hashOf(2)}`);
  other.remove();
});

test("Exportieren: Bereich + Kennung gehen raus, die Zeile zeigt danach „📂 Datei“", async () => {
  state = okState();
  await open(song);
  click(q("#clGo"));
  await flush();
  const sent = starts().at(-1);
  assert.equal(sent.path, `/api/clip/${hashOf(1)}`);
  assert.deepEqual({ ...sent.body, token: "" }, { start: 0, end: 10, outputs: ["audio"], token: "" });
  assert.match(sent.body.token, /^[A-Za-z0-9_-]{1,64}$/);
  const row = () => q("#clResults .clres");
  assert.match(row().textContent, /wird geschrieben … song audio\.wav/);
  assert.equal(view.isOpen(), true);                   // bleibt offen für das nächste Stück

  status = { ...idleStatus(), paused: true };
  await pollOnce();
  assert.match(row().textContent, /wartet, die Hintergrundarbeit ist angehalten/);

  const written = "/exp/2026-10-11/song 0m00s-0m10s.wav";
  status = { ...idleStatus(), finished_seq: 1, history: [{
    label: { key: "taskClip", params: { name: "song.flac" } }, ok: true,
    result: { key: "sumClip", params: {
      parts: [{ key: "sumClipWritten", params: { n: 1 } }], target: "/exp/2026-10-11",
      token: sent.body.token, files: [written] } } }] };
  await pollOnce();
  const file = row().querySelector(".clfile");
  assert.equal(file.textContent, "📂 song 0m00s-0m10s.wav");
  click(file);
  await flush();
  const shown = mockApi.calls.filter((c) => c.path === "/api/export/reveal").at(-1);
  assert.deepEqual(shown.body, { path: written });
  view.close();
});

test("Fehlgeschlagener Lauf: die Zeile nennt den Grund statt einer Datei", async () => {
  state = okState();
  await open(song);
  click(q("#clGo"));
  await flush();
  const token = starts().at(-1).body.token;
  status = { ...idleStatus(), finished_seq: 2, history: [{
    label: { key: "taskClip", params: { name: "song.flac" } }, ok: true,
    result: { key: "sumClipOffline", params: { name: "song.flac", token } } }] };
  await pollOnce();
  const row = q("#clResults .clres");
  assert.match(row.textContent, /Quelle ist nicht erreichbar \(song\.flac\)/);
  assert.ok(row.classList.contains("warn"));
  view.close();
});
