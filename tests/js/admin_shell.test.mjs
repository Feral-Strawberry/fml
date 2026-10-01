// admin_shell.test.mjs — Admin-Dokument (ADR 0074): Router (Slug → Seite,
// Klick → pushState, popstate, unbekannter Slug → Übersicht), Navigation,
// Aktivitäts-Widget und Rückweg zur Galerie als echter Link.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { bootAdmin, click, flush, popstate } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";

const { pollOnce } = await import("../../src/feral/web/static/js/status.js");

let state;
const slugFromPath = (p) => state.main.slugFromPath(p);
const title = () => document.getElementById("pageTitle").textContent;
const activeNav = () => document.querySelector("#navlist a.on")?.dataset.page;

before(async () => {
  state = await bootAdmin("/admin/unbekannt");
});

test("unbekannter Slug fällt auf die Übersicht zurück (URL wird ersetzt)", () => {
  assert.equal(title(), "Übersicht");
  assert.equal(activeNav(), "overview");
  assert.equal(globalThis.location.pathname, "/admin/overview");
  assert.ok(document.title.startsWith("Übersicht · Admin"));
});

test("Navigation: sieben Seiten in fester Reihenfolge, alle echte Links", () => {
  const links = [...document.querySelectorAll("#navlist a")];
  assert.deepEqual(links.map((a) => a.dataset.page),
    ["overview", "config", "sources", "maintenance", "issues", "arenas", "logs"]);
  assert.deepEqual(links.map((a) => a.getAttribute("href")),
    ["/admin/overview", "/admin/config", "/admin/sources", "/admin/maintenance", "/admin/issues", "/admin/arenas", "/admin/logs"]);
  assert.equal(document.getElementById("adBack").getAttribute("href"), "/");
  assert.equal(document.getElementById("adBackLabel").textContent, "Zurück zur Bibliothek");
});

test("Klick auf einen Navi-Link: pushState + Seite gerendert; Zurück (popstate) rendert die vorige", async () => {
  const ev = click(document.querySelector('#navlist a[data-page="logs"]'));
  await flush();
  assert.ok(ev.defaultPrevented, "Router fängt den Klick ab");
  assert.equal(globalThis.location.pathname, "/admin/logs");
  assert.equal(title(), "Logs");
  assert.equal(activeNav(), "logs");
  assert.ok(document.querySelector(".logcard"), "Logs-Seite gerendert");

  globalThis.location.pathname = "/admin/overview";   // der Browser stellt die URL her …
  popstate();                                          // … und meldet popstate
  await flush();
  assert.equal(title(), "Übersicht");
  assert.equal(activeNav(), "overview");
});

test("Modifier-Klick (neuer Tab) und der Galerie-Link gehen am Router vorbei", async () => {
  const ev = click(document.querySelector('#navlist a[data-page="logs"]'), { ctrlKey: true });
  assert.equal(ev.defaultPrevented, false);
  const back = click(document.getElementById("adBack"));
  assert.equal(back.defaultPrevented, false, "/ ist ein echter Seitenwechsel");
  await flush();
  assert.equal(title(), "Übersicht", "nichts gerendert");
});

test("slugFromPath: Slug lesen, Rest ist Übersicht", () => {
  assert.equal(slugFromPath("/admin"), "overview");
  assert.equal(slugFromPath("/admin/"), "overview");
  assert.equal(slugFromPath("/admin/issues"), "issues");
  assert.equal(slugFromPath("/admin/issues/"), "issues");
  assert.equal(slugFromPath("/admin/nope"), "overview");
  assert.equal(slugFromPath("/api/admin/log"), "overview");
});

test("Widget: Leerlauf → laufende Aufgabe mit Balken → wartend → toter Worker", async () => {
  assert.equal(document.getElementById("wTask").textContent, "Leerlauf");
  state.status = { ...state.status, running: true, label: { key: "taskReparse" }, elapsed: 98,
    current_file: { key: "progressReparse", params: { index: 6127, total: 9700 } },
    queue_pending: 2, queue: [{ key: "taskReindex" }, { key: "taskVacuum" }], worker_alive: true };
  await pollOnce(); await flush();
  assert.equal(document.getElementById("wTask").textContent, "Neu interpretieren (Schicht 2)");
  assert.equal(document.getElementById("wCount").textContent, "6.127 / 9.700");
  assert.equal(document.getElementById("wRight").textContent, "1:38 · +2 wartend");
  assert.equal(document.getElementById("wBar").style.width, "63%");
  assert.equal(document.getElementById("wDot").className, "dot");

  state.status = { ...state.status, running: false, label: null, current_file: null, elapsed: null,
    queue_pending: 1, queue: [{ key: "taskVacuum" }] };
  await pollOnce(); await flush();
  assert.equal(document.getElementById("wTask").textContent, "VACUUM");
  assert.equal(document.getElementById("wDot").className, "dot warn");

  state.status = { ...state.status, queue_pending: 0, queue: [], worker_alive: false };
  await pollOnce(); await flush();
  assert.equal(document.getElementById("wDot").className, "dot dead");
  assert.equal(document.getElementById("wTask").textContent, "Arbeitsprozess abgestürzt");
});

test("Widget zählt beobachtete Ordner und setzt den Navi-Zähler der Quellen", async () => {
  state.status = { ...state.status, worker_alive: true, watchers: [{ name: "out", path: "/o", pending: 0 }, { name: "dl", path: "/d", pending: 3 }] };
  await pollOnce(); await flush();
  assert.equal(document.getElementById("wTask").textContent, "beobachtet 2 Ordner");
  assert.equal(document.getElementById("wDot").className, "dot idle");
  const cnt = document.getElementById("navCnt-sources");
  assert.equal(cnt.hidden, false);
  assert.equal(cnt.textContent, "2");
  assert.equal(document.getElementById("actlink").getAttribute("href"), "/admin/overview");
});

test("Widget (#236): Leistung + Anhalten neben dem Link, gleicher Serverzustand; angehalten sagt das Widget warum", async () => {
  const power = document.getElementById("wPower"), pause = document.getElementById("wPause");
  assert.equal(power.closest("a"), null, "Knöpfe nicht im Link (gültiges HTML)");
  assert.equal(pause.closest("a"), null);
  state.status = { ...state.status, watchers: [], quiet: false, paused: false, queue_pending: 0 };
  await pollOnce(); await flush();
  assert.equal(power.dataset.icon, "bolt");
  assert.ok(!pause.classList.contains("on"));
  mockApi.post("/api/background", () => ({ ok: true }));
  click(pause);
  await flush();
  const sent = mockApi.calls.filter((c) => c.method === "POST" && c.path === "/api/background").at(-1);
  assert.deepEqual(sent.body, { paused: true });
  assert.ok(pause.classList.contains("on"), "Zz sofort in Akzentfarbe");

  // Server meldet angehalten mit zwei wartenden, eine Aufgabe beendet noch ihre Datei.
  state.status = { ...state.status, quiet: true, paused: true, queue_pending: 2,
    running: true, label: { key: "taskThumbWarm" }, current_file: { key: "x", params: { index: 5, total: 10 } } };
  await pollOnce(); await flush();
  assert.equal(power.dataset.icon, "leaf", "Leise aus dem Serverzustand");
  assert.equal(document.getElementById("wTask").textContent, "angehalten · 2 wartend");
  assert.match(document.getElementById("wCount").textContent, /endet noch mit ihrer Datei/);
  assert.equal(document.getElementById("wDot").className, "dot warn");
  state.status = { ...state.status, running: false, label: null, current_file: null };
  await pollOnce(); await flush();
  assert.equal(document.getElementById("wCount").textContent, "");
  assert.equal(document.getElementById("wBar").style.width, "0%");
  state.status = { ...state.status, paused: false, quiet: false, queue_pending: 0 };
  await pollOnce(); await flush();
});

test("Instanzname erscheint als Pille; Schema + Port unten in der Navi", async () => {
  mockApi.get("/api/stats", () => ({ total_items: 3, total_bytes: 300, instanz: { name: "DEV Mode", farbe: "#ff7a1a" } }));
  document.dispatchEvent(new CustomEvent("fml:config-saved"));
  await flush();
  const pill = document.getElementById("navInstance");
  assert.equal(pill.hidden, false);
  assert.equal(pill.textContent, "DEV Mode");
  assert.ok(document.title.startsWith("DEV Mode — "), document.title);
  assert.equal(document.getElementById("navMeta").textContent, "Schema v23 · :8766");
});
