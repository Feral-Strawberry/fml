// lyricsedit.test.mjs — Songtext von Hand (ADR 0106, #285): Zeilen teilen,
// verbinden und einfügen, Zeiten für neue Zeilen, Einstieg im Panel, Ansicht
// öffnen, tippen, speichern, Schließen mit ungespeicherten Änderungen
// (Speichern, Verwerfen, Abbrechen; Esc = Abbrechen) und
// „Stand der Datei wiederherstellen" in zwei Schritten. Stufe 2 (#286):
// Zeitfeld je Zeile (Strg/⌘+Enter = jetzt und weiter, Enter übernimmt
// Getipptes und geht nach unten, ↑/↓ Zeile, Entf entfernt), AltGr bleibt
// frei, große Uhr, gesperrtes Speichern bei Zeiten außer der Reihe.

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { loadShell, keydown, click, flush, hashOf } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit, record } from "./bus.mjs";
import { DomEvent } from "./dom.mjs";

const S = "../../src/feral/web/static/js/";
const le = await import(`${S}lyricsedit.js`);
const { nudge: playerNudge, positionOf: playerPos } = await import(`${S}player.js`);

const H = hashOf(7);
const song = { file_hash: H, container: "m4a", media_kind: "audio", duration: 60, name: "song.m4a" };
const FILE = [[10000, 12000, "[Verse]"], [10000, 13000, "Erste Zeile"], [20000, 24000, "Zweite Zile"]];
const m = (rows) => rows.map(([s, e, t]) => ({ s, e, t, est: false }));
let view;
let saved = null;
let manual = false;

const root = () => document.getElementById("lyedit");
const rows = () => [...root().querySelectorAll(".lyrow")];
const text = (i) => rows()[i].querySelector(".lytext");
const posts = () => mockApi.calls.filter((c) => c.method === "POST" && c.path === `/api/lyrics/${H}`);

async function open() {
  emit("lyrics-edit-open", { item: song });
  await flush();
}

function type(i, value) {
  const el = text(i);
  el.value = value;
  el.dispatchEvent(new DomEvent("input", { bubbles: true }));
}

before(() => {
  loadShell();
  mockApi.get(`/api/lyrics/${H}`, () => ({
    lines: saved ?? FILE, manual, source: null, duration: 60 }));
  mockApi.post(`/api/lyrics/${H}`, ({ body }) => {
    manual = body.lines.length > 0;
    saved = manual ? body.lines : null;
    return { state: { lines: saved ?? FILE, manual, source: null, duration: 60 },
             items: [{ file_hash: H, sections: [[10000, "Verse"]] }] };
  });
  view = le.initLyricsEdit();
});

after(() => view.close(true));

test("Zeilen: teilen, verbinden, Leerzeile verschwindet, Einfügen wird zu Zeilen", () => {
  const model = m([[1000, 3000, "eins zwei"], [5000, null, "drei"]]);
  assert.deepEqual(le.splitAt(model, 0, 5), { i: 1, caret: 0 });
  assert.deepEqual(model.map((l) => [l.s, l.e, l.t]), [[1000, null, "eins "], [null, 3000, "zwei"], [5000, null, "drei"]]);
  assert.deepEqual(le.joinUp(model, 1), { i: 0, caret: 5 });
  assert.equal(model[0].t, "eins zwei");
  assert.equal(model[0].e, 3000);
  const blank = m([[null, null, ""], [null, null, "a"]]);
  assert.deepEqual(le.joinUp(blank, 1), { i: 0, caret: 0 });
  assert.deepEqual(blank.map((l) => l.t), ["a"]);
  const down = m([[0, null, "ab"], [10, null, "cd"]]);
  assert.deepEqual(le.joinDown(down, 0), { i: 0, caret: 2 });
  assert.equal(down[0].t, "ab cd");
  const paste = m([[0, 900, "AB"]]);
  assert.deepEqual(le.pasteAt(paste, 0, 1, 1, "x\ny\r\nz"), { i: 2, caret: 1 });
  assert.deepEqual(paste.map((l) => [l.e, l.t]), [[null, "Ax"], [null, "y"], [900, "zB"]]);
});

test("Zeiten: neue Zeilen gleichmäßig zwischen den Nachbarn, ohne Zeiten bleibt alles leer", () => {
  const fresh = (rows) => m(rows).map((l) => ({ ...l, fresh: l.s === null && l.t !== "" }));
  const timed = le.fillTimes(fresh([[1000, null, "a"], [null, null, "b"], [null, null, ""], [null, null, "c"],
                                    [4000, null, "d"], [null, null, "e"]]), 10000);
  assert.deepEqual(timed.map((l) => l.s), [1000, 2000, null, 3000, 4000, 7000]);
  assert.deepEqual(timed.map((l) => l.est), [false, true, false, true, false, true]);
  // Halb geklopft: Zeilen, die schon vorher keine Zeit hatten, bleiben ohne.
  const half = le.fillTimes(m([[1000, null, "a"], [null, null, "b"]]), 10000);
  assert.deepEqual(half.map((l) => l.s), [1000, null]);
  const plain = le.fillTimes(m([[null, null, "a"], [null, null, "b"]]), 10000);
  assert.deepEqual(plain.map((l) => l.s), [null, null]);
  assert.equal(le.missingTimes(m([[0, null, "a"], [null, null, "b"], [null, null, ""]])), 1);
});

test("Klopfen und Reihenfolge: Zeit setzen, Ende fällt weg, Leerzeilen überspringen", () => {
  const model = m([[null, null, "a"], [null, null, ""], [9000, 9500, "b"], [null, null, "c"]]);
  le.tapAt(model, 0, 1234.4);
  assert.equal(model[0].s, 1234);
  le.tapAt(model, 2, 9600);                               // Ende 9500 läge davor: weg
  assert.deepEqual([model[2].s, model[2].e], [9600, null]);
  le.tapAt(model, 2, 9200);                               // Ende danach bliebe, aber es ist schon weg
  assert.equal(model[2].s, 9200);
  assert.equal(le.textLine(model, 1, 1), 2);              // überspringt die Leerzeile
  assert.equal(le.textLine(model, 4, 1), -1);
  assert.deepEqual([...le.orderErrors(m([[5, null, "a"], [3, null, "b"], [null, null, "c"], [6, null, "d"]]))], [1]);
  assert.equal(le.textLine(model, 1, -1), 0);
});

test("Speicherform wie der Server: Leerraum gefaltet, Leerzeilen am Rand weg", () => {
  assert.deepEqual(le.toServer(m([[null, null, " "], [5, 9, "  a  b "], [null, null, ""], [null, null, ""],
                                  [null, 4, "c"], [null, null, ""]])),
                   [[5, 9, "a b"], [null, null, ""], [null, null, "c"]]);
  assert.equal(le.fmtMs(83450), "1:23.5");
  assert.equal(le.fmtMs(null), "–");
});

test("Panel: Zeile „Songtext“ nennt die Herkunft und öffnet die Ansicht", () => {
  const html = (interpreted) => le.lyricsRowHtml({ interpreted });
  assert.match(html([]), /eintragen/);
  assert.match(html([{ parser: "audio", field: "lyrics", value: "x" }]), /aus der Datei[\s\S]*bearbeiten/);
  assert.match(html([{ parser: "manual", field: "lyrics", value: "x" }]), /von Hand/);
});

test("Ansicht: Vorlage aus der Datei, tippen, teilen, speichern", async () => {
  const changed = record("fields-changed");
  await open();
  assert.equal(root().hidden, false);
  assert.equal(rows().length, 3);
  assert.ok(rows()[0].classList.contains("sec"));
  assert.equal(root().querySelector("#lySave").disabled, true);
  type(2, "Zweite Zeile");
  assert.equal(root().querySelector("#lySave").disabled, false);
  // Enter am Ende von Zeile 1 legt eine neue, geschätzte Zeile an.
  keydown("Enter", { target: text(1) });
  assert.equal(rows().length, 4);
  type(2, "Neue Zeile");
  assert.ok(rows()[2].querySelector(".lytime").classList.contains("est"));
  assert.equal(rows()[2].querySelector(".lytime").value, "0:15.0");
  // Tasten gehören der Ansicht: nichts darunter sieht sie.
  const below = [];
  const spy = (e) => below.push(e.key);
  document.body.addEventListener("keydown", spy);
  keydown("x", { target: text(0) });
  document.body.removeEventListener("keydown", spy);
  assert.deepEqual(below, []);
  click(root().querySelector("#lySave"));
  await flush();
  assert.deepEqual(posts().at(-1).body.lines, [
    [10000, 12000, "[Verse]"], [10000, null, "Erste Zeile"], [15000, null, "Neue Zeile"],
    [20000, 24000, "Zweite Zeile"]]);
  assert.equal(root().querySelector("#lyState").textContent, "✎ von Hand");
  assert.equal(root().querySelector("#lyRestore").hidden, false);
  assert.deepEqual(changed.at(-1).fields, ["lyrics"]);
  assert.deepEqual(changed.at(-1).hashes, [H]);
  changed.stop();
});

test("Schließen mit ungespeicherten Änderungen: Nachfrage neben ✕, Esc und Abbrechen machen weiter", async () => {
  await open();
  type(0, "[Intro]");
  const leave = () => root().querySelector("#lyLeave");
  assert.equal(leave().hidden, true);
  text(1).focus();
  keydown("Escape");
  assert.equal(root().hidden, false);
  assert.equal(leave().hidden, false);
  await flush();
  keydown("Escape");                                     // zweites Esc = Abbrechen, nicht verwerfen
  assert.equal(root().hidden, false);
  assert.equal(leave().hidden, true);
  assert.equal(document.activeElement, text(1));         // Cursor wieder wie vorher
  click(root().querySelector("#lyClose"));
  click(root().querySelector("#lyClose"));               // ✕ nochmal: Nachfrage bleibt
  assert.equal(leave().hidden, false);
  click(root().querySelector("#lyLeaveCancel"));
  assert.equal(leave().hidden, true);
  assert.equal(root().hidden, false);
  type(0, "[Intro2]");
  click(root().querySelector("#lyClose"));
  type(0, "[Intro3]");                                   // weiter bearbeiten: Nachfrage weg
  assert.equal(leave().hidden, true);
  view.close(true);
});

test("Nachfrage: Speichern speichert und schließt, Verwerfen schließt ohne", async () => {
  await open();
  type(0, "[Intro]");
  click(root().querySelector("#lyClose"));
  const before = posts().length;
  click(root().querySelector("#lyLeaveDrop"));
  assert.equal(root().hidden, true);
  assert.equal(posts().length, before);
  await open();
  type(0, "[Outro]");
  click(root().querySelector("#lyClose"));
  click(root().querySelector("#lyLeaveSave"));
  await flush();
  assert.equal(posts().at(-1).body.lines[0][2], "[Outro]");
  assert.equal(root().hidden, true);
});

test("Zeitfeld: Strg/⌘+Enter = jetzt, Enter übernimmt und geht runter, ↑/↓, Entf, AltGr frei, Uhr", async () => {
  const H2 = hashOf(8);
  const own = { ...song, file_hash: H2, name: "eigen.mp3" };
  mockApi.get(`/api/lyrics/${H2}`, () => ({
    lines: [[null, null, "Eins"], [null, null, ""], [null, null, "Zwei"], [null, null, "Drei"]],
    manual: true, source: null, duration: 60 }));
  mockApi.post(`/api/lyrics/${H2}`, ({ body }) => ({
    state: { lines: body.lines, manual: true, source: null, duration: 60 }, items: [] }));
  emit("lyrics-edit-open", { item: own });
  await flush();
  const time = (i) => rows()[i].querySelector(".lytime");
  const leave = (i) => time(i).dispatchEvent(new DomEvent("focusout", { bubbles: true }));
  const typeTime = (i, value) => {
    time(i).value = value;
    time(i).dispatchEvent(new DomEvent("input", { bubbles: true }));
  };
  const at = (sec) => { playerNudge(own, sec - playerPos(H2)); };
  assert.equal(time(1).disabled, true);                   // Leerzeile: keine Zeit
  // AltGr (unter Windows Strg+Alt) bleibt dem Tippen: „[" für [Chorus].
  const altgr = keydown("[", { target: text(0), ctrlKey: true, altKey: true });
  assert.equal(altgr.defaultPrevented, false);
  // Mitklopfen: Strg/⌘+Enter nimmt die Abspielstelle und geht weiter.
  time(0).focus();
  at(2);
  keydown("Enter", { target: time(0), ctrlKey: true });
  assert.equal(time(0).value, "0:02.0");
  assert.equal(document.activeElement, time(2));          // Leerzeile übersprungen
  await flush();
  assert.equal(root().querySelector("#lyClock span").textContent, "0:02.0");
  // Aus dem Textfeld geht es genauso, der Cursor bleibt im Text.
  at(3);
  keydown("Enter", { target: text(2), metaKey: true });
  assert.equal(time(2).value, "0:03.0");
  assert.equal(document.activeElement, text(3));
  // Enter übernimmt Getipptes und geht nach unten (wie in einer Tabelle).
  typeTime(2, "3,5");
  keydown("Enter", { target: time(2) });
  assert.equal(time(2).value, "0:03.5");
  assert.equal(document.activeElement, time(3));
  // Enter ohne Getipptes geht nur weiter und ändert nichts.
  keydown("ArrowUp", { target: time(3) });
  keydown("Enter", { target: time(2) });
  assert.equal(time(2).value, "0:03.5");
  // Ungültig + Enter: bleibt zum Korrigieren stehen; Verlassen verwirft.
  typeTime(3, "abc");
  keydown("Enter", { target: time(3) });
  assert.equal(time(3).value, "abc");
  assert.match(root().querySelector("#lyNote").textContent, /gültige Zeit/);
  leave(3);
  assert.equal(time(3).value, "");
  typeTime(3, "4,5");
  leave(3);
  assert.equal(time(3).value, "0:04.5");
  // Zu spät getippt: Zeile 3 steht vor Zeile 1 → rot, Speichern gesperrt.
  typeTime(0, "5");
  leave(0);
  assert.ok(time(2).classList.contains("bad"));
  assert.equal(root().querySelector("#lySave").disabled, true);
  assert.match(root().querySelector("#lyNote").textContent, /Zeile 3/);
  // Entf nimmt die Zeit direkt weg.
  keydown("Delete", { target: time(2) });
  assert.equal(time(2).value, "");
  typeTime(3, "6");
  leave(3);
  assert.equal(root().querySelector("#lySave").disabled, false);
  keydown("s", { target: time(2), metaKey: true });
  await flush();
  assert.deepEqual(mockApi.calls.filter((c) => c.method === "POST" && c.path === `/api/lyrics/${H2}`).at(-1).body.lines,
                   [[5000, null, "Eins"], [null, null, ""], [null, null, "Zwei"], [6000, null, "Drei"]]);
  view.close(true);
});

test("Stand der Datei wiederherstellen: erst nachfragen, dann verwerfen", async () => {
  await open();
  const btn = root().querySelector("#lyRestore");
  assert.equal(btn.hidden, false);
  const before = posts().length;
  click(btn);
  assert.equal(posts().length, before);
  assert.match(btn.textContent, /Wirklich/);
  click(btn);
  await flush();
  assert.deepEqual(posts().at(-1).body.lines, []);
  assert.equal(root().querySelector("#lyRestore").hidden, true);
  assert.equal(root().querySelector("#lyState").textContent, "aus der Datei");
  view.close(true);
});

test("Ansichtswechsel mit ungespeicherten Änderungen: kein Endlos-Schließen, Nachfrage bleibt offen", async () => {
  const { closeAllDialogs } = await import(`${S}overlays.js`);
  await open();
  type(0, "[Bridge]");
  closeAllDialogs();                                     // endet (sonst hinge der Test)
  assert.equal(root().hidden, false);
  assert.equal(root().querySelector("#lyLeave").hidden, false);
  await flush();
  keydown("Escape");                                     // wieder angemeldet: Esc bricht ab
  assert.equal(root().querySelector("#lyLeave").hidden, true);
  view.close(true);
});
