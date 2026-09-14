// admin_logs.test.mjs — Seite „Logs" (ADR 0074): beide Dateien sofort, je
// Datei Zeilenzahl/Filter/Auffrischen; „nur WARNING und höher" geht als
// ?level=warning an den Server; WARNING/ERROR-Zeilen sind eingefärbt; nach
// einer fertigen Aufgabe frischen beide Fenster auf.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { bootAdmin, click, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";

const { pollOnce } = await import("../../src/feral/web/static/js/status.js");
let state;
const LINES = {
  web: ["2026-09-12 10:00:00,001 INFO    feral.web: Start", "2026-09-12 10:00:01,001 WARNING feral.web: slow: /api/items"],
  worker: ["2026-09-12 10:00:02,001 ERROR   feral.web.worker: kaputt", "Traceback (most recent call last):"],
};
let calls = [];

before(async () => {
  state = await bootAdmin("/admin/logs");
  loadMock();                    // eigene Log-Attrappe, dann Seite frisch rendern
  await state.main.show("logs");
  await flush();
});

function loadMock() {
  calls = [];
  mockApi.get("/api/admin/log", ({ params }) => {
    const file = params.get("file");
    calls.push({ file, lines: params.get("lines"), level: params.get("level") });
    let lines = LINES[file];
    if (params.get("level") === "warning") lines = lines.filter((l) => /WARNING|ERROR|Traceback/.test(l));
    return { log_dir: "/x/logs", files: [{ name: `fml-${file}.log`, bytes: 1234, lines }] };
  });
}

const card = (f) => document.querySelector(`.logcard[data-file="${f}"]`);

test("beide Dateien sofort geladen (je ein Aufruf mit ?file=), neueste Zeile unten", () => {
  assert.deepEqual(calls.map((c) => c.file).sort(), ["web", "worker"]);
  assert.ok(calls.every((c) => c.lines === "100" && c.level === null));
  const web = card("web").querySelector("[data-pre]");
  assert.ok(web.innerHTML.includes('logline warn">') && web.innerHTML.includes("slow"), web.innerHTML);
  assert.ok(card("worker").querySelector("[data-pre]").innerHTML.includes('logline err">'));
  assert.equal(card("web").querySelector("[data-size]").textContent, "1 KB");
});

test("Schalter „nur WARNING und höher“ lädt mit level=warning, nur diese Datei", async () => {
  calls = [];
  const chk = card("web").querySelector("[data-warn]");
  chk.checked = true;
  chk.dispatchEvent(new Event("change", { bubbles: true }));
  await flush();
  assert.deepEqual(calls, [{ file: "web", lines: "100", level: "warning" }]);
  assert.ok(!card("web").querySelector("[data-pre]").textContent.includes("Start"));
});

test("Zeilenzahl 500/2000 und Auffrischen", async () => {
  calls = [];
  const sel = card("worker").querySelector("[data-lines]");
  assert.deepEqual([...sel.options].map((o) => o.value), ["100", "500", "2000"]);
  sel.value = "2000";
  sel.dispatchEvent(new Event("change", { bubbles: true }));
  await flush();
  assert.deepEqual(calls, [{ file: "worker", lines: "2000", level: null }]);
  calls = [];
  click(card("worker").querySelector("[data-refresh]"));
  await flush();
  assert.equal(calls.length, 1);
});

test("Leere Datei / kein Treffer wird ehrlich gesagt", async () => {
  mockApi.get("/api/admin/log", ({ params }) => ({ files: [{ name: "x", bytes: 0, lines: [] }] }));
  click(card("web").querySelector("[data-refresh]"));
  await flush();
  const pre = card("web").querySelector("[data-pre]");
  assert.ok(pre.className.includes("empty"));
  assert.ok(pre.textContent.includes("WARNING"), "Filter ist an → „keine Einträge ab WARNING“");
});

test("Seitenoptionen: Zeilenumbruch (Standard an) und untereinander, im Browser gemerkt", async () => {
  const wrap = document.getElementById("logWrap");
  const stack = document.getElementById("logStack");
  assert.equal(wrap.checked, true);
  assert.ok(card("web").querySelector("[data-pre]").className.includes("wrap"));
  assert.ok(document.querySelector("#pageBody .row").className.includes("c2"), "nebeneinander");
  wrap.checked = false; wrap.dispatchEvent(new Event("change", { bubbles: true }));
  stack.checked = true; stack.dispatchEvent(new Event("change", { bubbles: true }));
  await flush();
  assert.ok(!card("web").querySelector("[data-pre]").className.includes("wrap"));
  assert.equal(document.querySelector("#pageBody .row").className, "row");
  assert.equal(localStorage.getItem("feral-admin-logwrap"), "0");
  assert.equal(localStorage.getItem("feral-admin-logstack"), "1");
});

test("Fertige Aufgabe frischt beide Fenster auf", async () => {
  loadMock();
  state.status = { ...state.status, finished_seq: 5 };
  await pollOnce(); await flush();
  assert.deepEqual(calls.map((c) => c.file).sort(), ["web", "worker"]);
});
