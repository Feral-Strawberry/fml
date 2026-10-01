// background.test.mjs — Hintergrund-Knöpfe der Galerie (ADR 0093, #226/#223):
// Leistung (Blitz/Blatt) und Anhalten („Zz") sind zwei unabhängige Knöpfe,
// der Zustand kommt vom Server (/api/status), ein Klick schickt nur den
// Wechsel; angehalten nennt das Aktivitäts-Badge die Wartenden.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";

const { initBackgroundButtons } =
  await import("../../src/feral/web/static/js/background.js");
const { startStatusPolling, initActivityBadge, pollOnce } =
  await import("../../src/feral/web/static/js/status.js");

let status;
const power = () => document.getElementById("bgPower");
const pause = () => document.getElementById("bgPause");

before(async () => {
  loadShell();
  status = { running: false, label: null, queue_pending: 0, queue: [], worker_alive: null,
             watchers: [], finished_seq: 0, history: [], quiet: true, paused: false };
  mockApi.get("/api/status", () => status);
  mockApi.post("/api/background", (body) => body);
  initActivityBadge(document.getElementById("activity"));
  initBackgroundButtons(power(), pause());
  startStatusPolling();
  await flush();
});

async function tick() { await pollOnce(); await flush(); }

test("Leistung zeigt den Serverzustand als Icon (Blatt = Leise)", () => {
  assert.equal(power().dataset.icon, "leaf");
  assert.ok(power().querySelector("svg"));
  assert.equal(power().classList.contains("on"), false, "kein Highlight, wie Hell/Dunkel");
  assert.equal(pause().classList.contains("on"), false);
});

test("Leistungs-Klick schaltet um, ohne die Pause anzufassen", async () => {
  power().click();
  await flush();
  assert.deepEqual(mockApi.callsTo("/api/background").map((c) => c.body), [{ quiet: false }]);
  assert.equal(power().dataset.icon, "bolt");
});

test("Anhalten ist ein eigener Knopf; angehalten zeigt das Badge die Wartenden", async () => {
  pause().click();
  await flush();
  assert.deepEqual(mockApi.callsTo("/api/background").at(-1).body, { paused: true });
  status = { ...status, quiet: false, paused: true, queue_pending: 3, queue: [{ key: "taskAudioWarm" }] };
  await tick();
  assert.ok(pause().classList.contains("on"));
  assert.match(pause().title, /3/);
  const badge = document.getElementById("activity");
  assert.equal(badge.hidden, false);
  assert.match(badge.textContent, /3/);
  assert.ok(badge.querySelector(".actdot.paused"));
  pause().click();                         // nochmal = fortsetzen
  await flush();
  assert.deepEqual(mockApi.callsTo("/api/background").at(-1).body, { paused: false });
});
