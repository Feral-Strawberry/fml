// musicfields.test.mjs — Musik-Angaben von Hand im Panel (ADR 0101, #256):
// vorbelegt mit dem geltenden Wert, „(verschieden)" bei gemischter Auswahl,
// Eingabe wirkt auf die Auswahl, „✎ von Hand" entfernt die Angabe, große
// Auswahl läuft als Aufgabe.

import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { loadShell, click, keydown, flush, hashOf } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { record } from "./bus.mjs";
import { DomEvent } from "./dom.mjs";

const { MUSIC_FIELDS, mountMusicFields } = await import("../../src/feral/web/static/js/musicfields.js");

const blank = () => Object.fromEntries(MUSIC_FIELDS.map((f) =>
  [f, { value: "", mixed: false, manual: false, source: null }]));
let state;
let box;
const row = (field) => box.querySelector(`.mfrow[data-field="${field}"]`);
const input = (field) => row(field).querySelector("input");
const hand = (field) => row(field).querySelector(".mfhand");
const posts = () => mockApi.calls.filter((c) => c.method === "POST" && c.path === "/api/fields");

async function type(field, value) {
  const el = input(field);
  el.focus();
  el.value = value;
  el.blur();
  el.dispatchEvent(new DomEvent("focusout", { bubbles: true }));
  await flush();
}

beforeEach(async () => {
  loadShell();
  mockApi.reset();
  state = blank();
  state.artist = { value: "Alte Band", mixed: false, manual: false, source: null };
  state.album = { value: "Zweites Album", mixed: false, manual: true, source: "Anna" };
  state.genre = { value: "", mixed: true, manual: false, source: null };
  mockApi.post("/api/fields/state", () => ({ fields: state, count: 2 }));
  mockApi.post("/api/fields", ({ body }) => {
    for (const [f, v] of Object.entries(body.fields)) {
      state = { ...state, [f]: { value: v, mixed: false, manual: !!v, source: null } };
    }
    return { updated: body.hashes.length, fields: state, items: [{ file_hash: body.hashes[0], artist: "Neue Band" }] };
  });
  box = document.createElement("div");
  document.body.appendChild(box);
  await mountMusicFields(box, [hashOf(1), hashOf(2)]);
});

test("acht Felder, vorbelegt; von Hand und verschieden sind markiert", () => {
  assert.equal(box.querySelectorAll(".mfrow").length, 8);
  assert.equal(input("artist").value, "Alte Band");
  assert.equal(hand("artist").hidden, true);
  assert.equal(input("album").value, "Zweites Album");
  assert.equal(hand("album").hidden, false);
  assert.match(hand("album").title, /Anna/);
  assert.equal(input("genre").value, "");
  assert.notEqual(input("genre").placeholder, "");
});

test("Eingabe wirkt auf die Auswahl und meldet fields-changed", async () => {
  const seen = record("fields-changed");
  await type("artist", "  Neue Band ");
  assert.deepEqual(posts().at(-1).body, { hashes: [hashOf(1), hashOf(2)], fields: { artist: "Neue Band" } });
  assert.equal(hand("artist").hidden, false);
  assert.deepEqual(seen.at(-1), { hashes: [hashOf(1), hashOf(2)], fields: ["artist"],
                                  items: [{ file_hash: hashOf(1), artist: "Neue Band" }] });
  seen.stop();
});

test("Enter übernimmt; unveränderte und gemischte Felder bleiben unberührt", async () => {
  input("genre").focus();
  keydown("Enter", { target: input("genre") });
  input("genre").dispatchEvent(new DomEvent("focusout", { bubbles: true }));
  await type("artist", "Alte Band");
  assert.equal(posts().length, 0);
});

test("leer ohne Angabe von Hand: der Wert aus der Datei bleibt stehen", async () => {
  await type("artist", "");
  assert.equal(posts().length, 0);
  assert.equal(input("artist").value, "Alte Band");
});

test("Leeren und der Knopf entfernen die Angabe von Hand", async () => {
  await type("album", "");
  assert.deepEqual(posts().at(-1).body.fields, { album: "" });
  assert.equal(hand("album").hidden, true);
  state = { ...state, track: { value: "", mixed: true, manual: true, source: null } };
  await mountMusicFields(box, [hashOf(1), hashOf(2)]);
  click(hand("track"));
  await flush();
  assert.deepEqual(posts().at(-1).body.fields, { track: "" });
});

test("Fehler und Aufgabe stehen unter den Feldern", async () => {
  mockApi.post("/api/fields", () => mockApi.status(400, { detail: "Jahr vierstellig" }));
  await type("year", "94");
  const note = box.querySelector(".mfnote");
  assert.equal(note.hidden, false);
  assert.match(note.textContent, /vierstellig/);
  mockApi.post("/api/fields", () => ({ queued: true, count: 350 }));
  const seen = record("fields-changed");
  await type("year", "1994");
  assert.match(note.textContent, /350/);
  assert.equal(seen.length, 0);
  seen.stop();
});
