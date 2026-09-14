// status.test.mjs — geteilter Status-Poller (status.js, ADR 0074) und das
// Topbar-Badge der Galerie (ADR 0067, Issues #62/#63): das Label ist ein
// Meldungs-Dict {key, params} und wird über serverMsg() übersetzt (#63:
// vorher „[object Object]"); die Warteschlange wird gezählt, ein toter
// Worker ist rot markiert; onTaskFinished feuert nur bei echter Flanke oder
// geänderter finished_seq (kein Dauerfeuer auf /api/admin/info).

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";

const { startStatusPolling, initActivityBadge, onStatus, onTaskFinished, pollOnce, isBusy } =
  await import("../../src/feral/web/static/js/status.js");

let status;   // was /api/status gerade antwortet
const activity = () => document.getElementById("activity");
const idle = { running: false, label: null, current_file: null, report: {}, last_finished: null,
               last_result: null, queue_pending: 0, queue: [], worker_alive: null, watchers: [],
               finished_seq: 0, history: [] };
let idleEvents = 0, finishedEvents = 0, statusEvents = 0;

before(async () => {
  loadShell();
  status = { ...idle };
  mockApi.get("/api/status", () => status);
  initActivityBadge(activity());
  onStatus(() => statusEvents++);
  onTaskFinished(() => finishedEvents++);
  startStatusPolling({ onIdle: () => idleEvents++ });
  await flush();
});

async function tick() { await pollOnce(); await flush(); }

test("Badge ist ein Link nach /admin und im Leerlauf ohne Watcher versteckt", async () => {
  assert.equal(activity().tagName, "A");
  assert.equal(activity().getAttribute("href"), "/admin");
  assert.equal(activity().hidden, true);
  assert.ok(statusEvents >= 1, "onStatus hat den ersten Poll gesehen");
  assert.equal(idleEvents, 0);
  assert.equal(finishedEvents, 0, "der erste Poll ist keine Flanke");
});

test("Topbar-Badge zeigt den übersetzten Aufgabennamen (#63), nicht [object Object]", async () => {
  status = { ...idle, running: true, label: { key: "taskReparse" },
             current_file: { key: "progressReparse", params: { index: 35000, total: 70000 } },
             elapsed: 65, worker_alive: true };
  await tick();
  const text = activity().textContent;
  assert.ok(!text.includes("[object Object]"), text);
  assert.ok(text.includes("Neu interpretieren"), text);
  assert.equal(activity().hidden, false);
  assert.ok(isBusy(status));
});

test("Warteschlange wird im Badge gezählt; erste wartende Aufgabe ohne laufende", async () => {
  status = { ...status, queue_pending: 2, queue: [{ key: "taskReindex" }, { key: "taskVacuum" }] };
  await tick();
  assert.ok(activity().textContent.includes("+2"), activity().textContent);
  status = { ...idle, queue_pending: 1, queue: [{ key: "taskReindex" }], worker_alive: true };
  await tick();
  assert.ok(activity().textContent.includes("Suchindex aufbauen"), activity().textContent);
});

test("Flanke laufend→leer: engine-idle einmal, onTaskFinished einmal", async () => {
  const idleBefore = idleEvents, finBefore = finishedEvents;
  status = { ...idle, last_finished: { key: "taskReindex" }, finished_seq: 7, worker_alive: true };
  await tick();
  assert.equal(idleEvents, idleBefore + 1);
  assert.equal(finishedEvents, finBefore + 1);
  await tick(); await tick();
  assert.equal(idleEvents, idleBefore + 1, "kein Dauerfeuer im Leerlauf");
  assert.equal(finishedEvents, finBefore + 1);
});

test("onTaskFinished feuert bei geänderter finished_seq, nicht bei neuem Label-Objekt", async () => {
  // Vorher: Objektvergleich der Label-Dicts → bei JEDEM Poll loadInfo()
  // (/api/admin/info scannt den ganzen Bestand) — Feral Strawberrys „träge", 2026-09-07.
  const before = finishedEvents;
  status = { ...status, last_finished: { key: "taskReindex" }, finished_seq: 7 };   // neues Objekt, gleiche Nummer
  await tick(); await tick();
  assert.equal(finishedEvents, before);
  status = { ...status, finished_seq: 8 };
  await tick();
  assert.equal(finishedEvents, before + 1);
});

test("Aufgabe zwischen zwei Polls fertig: engine-idle trotzdem (#32), nicht mitten in der Warteschlange", async () => {
  // Ein-Datei-Scan aus dem Watchordner: der Poller sieht nie „laufend",
  // nur die gestiegene finished_seq — im Leerlauf muss das reichen.
  const idleBefore = idleEvents;
  status = { ...idle, finished_seq: 20, worker_alive: true };
  await tick();
  assert.equal(idleEvents, idleBefore + 1, "fertig + leer → engine-idle");
  await tick();
  assert.equal(idleEvents, idleBefore + 1, "kein Dauerfeuer");
  // Fertig, aber die nächste Aufgabe läuft schon: kein engine-idle (erst am Ende).
  status = { ...idle, running: true, label: { key: "taskReparse" }, finished_seq: 21, worker_alive: true };
  await tick();
  assert.equal(idleEvents, idleBefore + 1, "mitten in der Warteschlange kein Refresh");
  status = { ...idle, finished_seq: 22, worker_alive: true };
  await tick();
  assert.equal(idleEvents, idleBefore + 2, "Flanke am Ende: einmal");
});

test("Toter Worker ist im Badge markiert und bleibt auch im Leerlauf sichtbar", async () => {
  status = { ...idle, queue_pending: 1, queue: [{ key: "taskReindex" }], worker_alive: false,
             last_result: { key: "sumWorkerDied", params: { code: 3 } } };
  await tick();
  assert.ok(activity().classList.contains("dead"));
  assert.ok(activity().textContent.includes("Suchindex aufbauen"));   // erste wartende
  // Leerlauf + toter Worker: Badge bleibt sichtbar (sonst sieht man es erst im Admin).
  status = { ...status, queue_pending: 0, queue: [], worker_alive: false };
  await tick();
  assert.equal(activity().hidden, false);
  assert.ok(activity().textContent.includes("abgestürzt"), activity().textContent);
});

test("Watcher aktiv: Badge „beobachtet“ mit grünem Punkt", async () => {
  status = { ...idle, worker_alive: true, watchers: [{ path: "/x" }] };
  await tick();
  assert.equal(activity().hidden, false);
  assert.ok(activity().innerHTML.includes("actdot idle"), activity().innerHTML);
  assert.ok(activity().textContent.includes("beobachtet"), activity().textContent);
});
