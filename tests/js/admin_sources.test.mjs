// admin_sources.test.mjs — Seite „Quellen & Import" (ADR 0074, A2 #106):
// Karte „Ordner aufnehmen" oben, Watchordner als Karten mit Zustand,
// Zählern und Aktionen; Live-Zähler kommen aus dem Status-Poll ohne eigene
// Anfrage; Aktionen (Stoppen/Entfernen/Aufnehmen) treffen die richtigen
// Endpunkte; Übersichtsmodus sperrt die dateischreibenden Modi.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { bootAdmin, click, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";

const { pollOnce } = await import("../../src/feral/web/static/js/status.js");
const { STRINGS: STRINGS_DE } = await import("../../src/feral/web/static/js/strings.de.js");
let state;
let watch;
const posts = (p) => mockApi.calls.filter((c) => c.method === "POST" && c.path === p);

function sources() {
  return [
    { name: "output", path: "/a/output", modus: "kopieren", quiet_seconds: 5, poll_seconds: 1,
      leere_ordner_entfernen: false, exists: true, watching: true, pending: 2, enqueued_total: 10 },
    { name: "cleanup", path: "/b/cleanup", modus: "verschieben", quiet_seconds: 5, poll_seconds: 1,
      leere_ordner_entfernen: true, exists: true, watching: false, pending: 0, enqueued_total: 0 },
  ];
}

before(async () => {
  state = await bootAdmin("/admin/sources");
  watch = { sources: sources(), has_library: true, verwaltung: true };
  mockApi.get("/api/watch", () => watch);
  mockApi.post("/api/watch/stop", () => ({ ok: true }));
  mockApi.post("/api/watch/start", () => ({ ok: true }));
  mockApi.post("/api/watch/save", ({ body }) => {
    watch = { ...watch, sources: body.sources.map((s) => ({ ...s, exists: true, watching: true, pending: 0, enqueued_total: 0 })) };
    return watch;
  });
  mockApi.post("/api/import", () => ({ queued_files: 7, target: "/lib" }));
  await state.main.show("sources");
  await flush();
});

const cards = () => [...document.querySelectorAll(".srccard")];
const card = (path) => document.querySelector(`.srccard[data-path="${path}"]`);

test("Formular-Karte oben, Watchordner als Karten mit Zustand, Zählern und Aktionen", () => {
  const rows = document.querySelectorAll("#pageBody .row");
  assert.ok(rows[0].querySelector("#adImpPath"), "Ordner aufnehmen steht oben");
  assert.equal(document.getElementById("adImpLeerWrap").hidden, true);
  assert.equal(cards().length, 2);
  const a = card("/a/output");
  assert.ok(a.querySelector(".wdot").className.includes("on"));
  assert.equal(a.querySelector("[data-pending]").textContent, "2");
  assert.equal(a.querySelector("[data-imported]").textContent, "10");
  assert.ok(a.querySelector("[data-stop]"), "beobachtet → Stoppen");
  const b = card("/b/cleanup");
  assert.ok(!b.querySelector(".wdot").className.includes("on"));
  assert.ok(b.querySelector("[data-start]"), "aus → Beobachten");
  assert.ok(b.querySelector(".wleerchk").checked, "Leeren-Option nur bei verschieben");
  assert.equal(a.querySelector(".wleerchk"), null);
  assert.equal(document.getElementById("adWatchCount").textContent, "2");
});

test("Live-Zähler aus dem Status-Poll, ohne eigene Anfrage an /api/watch", async () => {
  const before = mockApi.callsTo("/api/watch").length;
  state.status = { ...state.status, watchers: [{ root: "/a/output/", pending: 5, enqueued_total: 1234 }] };
  await pollOnce(); await flush();
  assert.equal(card("/a/output").querySelector("[data-pending]").textContent, "5");
  assert.equal(card("/a/output").querySelector("[data-imported]").textContent, "1.234");
  assert.equal(mockApi.callsTo("/api/watch").length, before);
});

test("Stoppen trifft /api/watch/stop mit dem Pfad und lädt die Liste neu", async () => {
  watch.sources[0].watching = false;
  click(card("/a/output").querySelector("[data-stop]"));
  await flush();
  assert.deepEqual(posts("/api/watch/stop").at(-1).body, { path: "/a/output" });
  assert.ok(card("/a/output").querySelector("[data-start]"));
});

test("Entfernen speichert die Liste ohne diese Quelle (löscht keine Dateien)", async () => {
  click(card("/b/cleanup").querySelector(".wremove"));
  await flush();
  const body = posts("/api/watch/save").at(-1).body;
  assert.deepEqual(body.sources.map((s) => s.path), ["/a/output"]);
  assert.equal(cards().length, 1);
});

test("Aufnehmen: einmal jetzt → /api/import; dauerhaft → neuer Watchordner über /api/watch/save", async () => {
  const path = document.getElementById("adImpPath");
  path.value = "/c/neu";
  click(document.getElementById("adImpGo"));
  await flush();
  assert.deepEqual(posts("/api/import").at(-1).body, { path: "/c/neu", modus: "kopieren", leere_ordner_entfernen: false });
  assert.ok(document.getElementById("adImpMsg").textContent.includes("7"));
  assert.equal(path.value, "");

  path.value = "/d/watch";
  document.getElementById("adImpFreq").value = "watch";
  click(document.getElementById("adImpGo"));
  await flush();
  const body = posts("/api/watch/save").at(-1).body;
  assert.deepEqual(body.sources.map((s) => s.path), ["/a/output", "/d/watch"]);
  assert.equal(body.sources[1].name, "watch");
  assert.equal(cards().length, 2);
  assert.ok(document.getElementById("adImpMsg").textContent.includes(STRINGS_DE.watchCreated));
});

test("Übersichtsmodus sperrt kopieren/verschieben im Formular und auf den Karten", async () => {
  watch = { ...watch, verwaltung: false, sources: watch.sources.map((s) => ({ ...s, watching: false })) };
  state.status = { ...state.status, finished_seq: 9 };
  await pollOnce(); await flush();
  const opts = [...document.getElementById("adImpModus").options];
  assert.deepEqual(opts.map((o) => o.disabled), [true, true, false]);
  assert.equal(document.getElementById("adImpModus").value, "katalogisieren");
  assert.ok(card("/a/output").querySelector(".srcstate .warn"), "Karte zeigt die Sperre");
  assert.ok(card("/a/output").querySelector("[data-start]").disabled);
});

test("Leere Liste ehrlich gesagt", async () => {
  watch = { sources: [], has_library: false, verwaltung: true };
  state.status = { ...state.status, finished_seq: 10 };
  await pollOnce(); await flush();
  assert.equal(cards().length, 0);
  assert.ok(document.getElementById("adWatch").textContent.length > 0);
  assert.ok(document.getElementById("adWatchWarn").querySelector(".warn"), "kein Import-Ziel");
});

