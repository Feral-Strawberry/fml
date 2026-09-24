// admin_maintenance.test.mjs — Seite „Wartung" (A3, #107): vier Gruppenkarten
// mit Aktionszeilen, Zustand je Zeile aus dem Status-Poll (läuft / Warteschlange /
// zuletzt ✓), synchrone Aktionen mit Inline-Ergebnis, Rausverschieben und
// Import-Regeln als eigene Karten mit zweistufigem Schärfen, DB-Aufteilung
// nur auf Knopfdruck. Kein Overlay mehr (#31 hat keinen Boden mehr).

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { bootAdmin, click, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";

let state, status;
const calls = (p) => mockApi.callsTo(p).length;
const posts = (p) => mockApi.calls.filter((c) => c.method === "POST" && c.path.startsWith(p)).length;

before(async () => {
  state = await bootAdmin("/admin/maintenance");
  status = await import("../../src/feral/web/static/js/status.js");
  mockApi.post("/api/admin/rescan", () => ({ queued: true }));
  mockApi.post("/api/admin/thumbcache/clear", () => ({ deleted: 7 }));
  mockApi.post("/api/admin/prune", ({ body }) => ({ pruned: body && body.under ? 1 : 3 }));
  mockApi.get("/api/admin/orphans", ({ params }) => params.get("under")
    ? { total: 1, sample: ["/ext/x.png"], under: params.get("under") }
    : { total: 3, sample: ["/a.png", "/b.png", "/c.png"], under: null });
  mockApi.post("/api/admin/moveout", () => ({ queued: true }));
  mockApi.post("/api/admin/import-rules/apply", () => ({ queued: true, expected: 5 }));
  mockApi.get("/api/admin/import-rules", () => ({
    active: true, rules: { min_kante: 241, formate: ["arw"] }, counts: { min_kante: 4, formate: 1 }, total: 5,
  }));
  await state.main.show("maintenance");
  await flush(10);
});

test("vier Karten in einer Reihe, je Aktion eine Zeile; keine Overlay-Reste", () => {
  const cards = [...document.querySelectorAll(".row.c4 > .card[data-card]")].map((c) => c.dataset.card);
  assert.deepEqual(cards, ["raw", "thumbs", "db", "reeval"]);
  assert.equal(document.querySelectorAll(".action[data-action]").length, 9, "neun Aktionszeilen in den vier Karten");
  // „Audio analysieren" (A4 #161) nur mit Audio-Modul — /api/stats ohne audio.
  assert.equal(document.querySelector('[data-action="audiowarm"]').hidden, true);
  assert.equal(document.querySelector(".maintbtn"), null, "alte Knopfleiste ist weg");
  assert.equal(document.querySelector(".pickoverlay"), null, "kein Overlay offen");
  assert.ok(document.getElementById("moCard"), "Rausverschieben ist eine Karte");
  assert.ok(document.getElementById("irCard"), "Import-Regeln ist eine Karte");
  assert.ok(document.getElementById("prCard"), "Verwaiste Fundorte aufräumen ist eine Karte");
  assert.equal(document.querySelector('[data-run="prune"]'), null, "Aufräumen ist keine Zeile mehr");
  assert.equal(document.querySelector('[data-action="rankscores"]'), null, "Ranking-Scores sind zur Arenen-Seite gezogen");
  // Kennzahlen: Parser-Balken aus /api/admin/maintenance, Fundorte aus /api/stats.
  assert.ok(document.getElementById("mtMeter-reeval").textContent.includes("comfyui"));
  assert.ok(document.getElementById("mtHead-raw").textContent.includes("3"), "Fundorte aus stats");
});

test("Zustand je Zeile: läuft mit Balken → Warteschlange mit Position → zuletzt ✓ Ergebnis", async () => {
  state.status = { ...state.status, running: true, label: { key: "taskRescan" }, elapsed: 98,
    current_file: { params: { index: 61, total: 97, name: "x.png" } },
    queue: [{ key: "taskReparse" }, { key: "taskReindex" }], queue_pending: 2 };
  await status.pollOnce();
  const rescan = document.querySelector('[data-st="rescan"]');
  assert.ok(rescan.classList.contains("running"));
  assert.ok(rescan.textContent.includes("61"), rescan.textContent);
  assert.ok(rescan.querySelector(".bar"), "Balken in der Zeile");
  assert.equal(document.querySelector('[data-run="rescan"]').disabled, true);
  assert.ok(document.querySelector('[data-st="reindex"]').textContent.includes("2"), "Position 2 in der Warteschlange");
  assert.equal(document.querySelector('[data-run="reindex"]').disabled, true);
  state.status = { ...state.status, running: false, label: null, current_file: null, queue: [], queue_pending: 0,
    finished_seq: 1,
    history: [{ label: { key: "taskRescan" }, result: { key: "sumReindex", params: { n: 97 } }, ok: true,
                elapsed: 100, finished_at: "2026-09-13T10:00:00Z" }] };
  await status.pollOnce();
  await flush();
  assert.ok(rescan.classList.contains("done"));
  assert.ok(rescan.textContent.startsWith("✓"), rescan.textContent);
  assert.equal(document.querySelector('[data-run="rescan"]').disabled, false);
  assert.equal(document.querySelector('[data-st="reindex"]').textContent, "", "ohne Verlaufseintrag leer");
});

test("Einreihen und synchrone Aktionen melden inline", async () => {
  click(document.querySelector('[data-run="rescan"]'));
  await flush();
  assert.equal(posts("/api/admin/rescan"), 1);
  assert.ok(document.querySelector('[data-st="rescan"]').classList.contains("queued"));
  click(document.querySelector('[data-run="thumbs"]'));
  await flush();
  assert.ok(document.querySelector('[data-st="thumbs"]').textContent.includes("7"), "Zahl der gelöschten Cache-Dateien");
});

test("Verwaiste Fundorte: Bereich → Vorschau nur auf Knopfdruck → scharf → aufräumen; Bereichswechsel entwertet die Vorschau", async () => {
  assert.equal(calls("/api/admin/orphans"), 0, "kein stat-Lauf beim Seitenladen");
  const arm = document.getElementById("prArm"), go = document.getElementById("prGo");
  assert.equal(arm.disabled, true);
  click(document.getElementById("prCheck"));
  await flush();
  assert.equal(calls("/api/admin/orphans"), 1);
  assert.equal(mockApi.callsTo("/api/admin/orphans").at(-1).params.get("under"), null, "überall");
  assert.ok(document.getElementById("prPrev").textContent.includes("3 verwaiste"));
  assert.ok(document.getElementById("prPrev").textContent.includes("/a.png"), "Beispielpfade");
  assert.equal(arm.disabled, false);
  assert.ok(go.textContent.includes("3"));
  // Bereich wechseln: Vorschau weg, Pfadfeld frei, ohne Pfad ehrliche Meldung.
  const under = document.getElementById("prScopeUnder");
  under.checked = true;
  under.dispatchEvent(new DomEvent("change", { bubbles: true }));
  assert.equal(arm.disabled, true, "Bereichswechsel entwertet die Vorschau");
  assert.equal(document.getElementById("prPath").disabled, false);
  click(document.getElementById("prCheck"));
  await flush();
  assert.equal(calls("/api/admin/orphans"), 1, "ohne Pfad kein Aufruf");
  assert.ok(document.getElementById("prPrev").textContent.includes("Ordner"));
  document.getElementById("prPath").value = "/ext";
  click(document.getElementById("prCheck"));
  await flush();
  assert.equal(mockApi.callsTo("/api/admin/orphans").at(-1).params.get("under"), "/ext");
  assert.ok(document.getElementById("prPrev").textContent.includes("/ext"));
  arm.checked = true;
  arm.dispatchEvent(new DomEvent("change", { bubbles: true }));
  assert.equal(go.disabled, false);
  click(go);
  await flush();
  const prune = mockApi.calls.filter((c) => c.method === "POST" && c.path === "/api/admin/prune");
  assert.equal(prune.length, 1);
  assert.deepEqual(prune[0].body, { under: "/ext" }, "Bereich aus der geprüften Vorschau");
  assert.ok(document.getElementById("prMsg").textContent.includes("1"), "Ergebnis inline");
  assert.equal(arm.disabled, true, "nach dem Lauf entschärft, Vorschau neu nötig");
});

test("Rausverschieben: Vorschau aus dem Server, scharf erst mit Ziel + Häkchen, dann eingereiht", async () => {
  assert.ok(document.getElementById("moInfo").textContent.includes("/lib/a.png"), "Beispielpfad aus der Vorschau");
  const arm = document.getElementById("moArm"), go = document.getElementById("moGo");
  assert.equal(arm.disabled, true, "ohne Ziel nicht scharf schaltbar");
  assert.equal(go.disabled, true);
  const target = document.getElementById("moTarget");
  target.value = "/out";
  target.dispatchEvent(new DomEvent("input", { bubbles: true }));
  assert.equal(arm.disabled, false);
  assert.equal(go.disabled, true, "Häkchen fehlt noch");
  arm.checked = true;
  arm.dispatchEvent(new DomEvent("change", { bubbles: true }));
  assert.equal(go.disabled, false);
  assert.ok(go.textContent.includes("3"), go.textContent);
  click(go);
  await flush();
  assert.equal(posts("/api/admin/moveout"), 1);
  assert.deepEqual(mockApi.calls.filter((c) => c.method === "POST" && c.path === "/api/admin/moveout").at(-1).body, { target: "/out" });
  assert.ok(document.getElementById("moMsg").classList.contains("queued"));
  assert.equal(document.getElementById("moArm").checked, false, "nach dem Einreihen entschärft");
});

test("Import-Regeln: Regeln + Vorschau sichtbar, scharf erst nach „Bestand prüfen“, Ablehnen reiht ein", async () => {
  assert.ok(document.getElementById("irRules").textContent.includes("241"));
  assert.ok(document.getElementById("irPrev").textContent.includes("5"));
  assert.equal(document.getElementById("irArm").disabled, true, "vor dem Prüfen nicht scharf schaltbar");
  click(document.getElementById("irCheck"));
  await flush();
  const arm = document.getElementById("irArm");
  assert.equal(arm.disabled, false);
  arm.checked = true;
  arm.dispatchEvent(new DomEvent("change", { bubbles: true }));
  assert.equal(document.getElementById("irGo").disabled, false);
  click(document.getElementById("irGo"));
  await flush();
  assert.equal(posts("/api/admin/import-rules/apply"), 1);
  assert.ok(document.getElementById("irMsg").classList.contains("queued"));
});

test("DB-Aufteilung nur auf Knopfdruck; Build ohne dbstat bekommt keinen Knopf", async () => {
  assert.equal(calls("/api/admin/dbstat"), 0, "kein dbstat beim Seitenladen");
  click(document.getElementById("mtDbCalc"));
  await flush();
  assert.equal(calls("/api/admin/dbstat"), 1);
  assert.ok(document.getElementById("mtDbBreak").querySelector(".comp"), "Stapelbalken");
  assert.ok(document.getElementById("mtDbBreak").textContent.includes("Roh-Blobs"));
  // Build ohne dbstat: kein Knopf, nur der Hinweis (Befund 2026-09-13, Windows).
  mockApi.get("/api/admin/maintenance", () => ({ parsers: [], undated: 0, open_issues: 0, blocked_count: 0, dbstat: false }));
  await state.main.show("maintenance");
  await flush(10);
  assert.equal(document.getElementById("mtDbCalc"), null, "kein Knopf ohne dbstat");
  assert.ok(document.getElementById("mtMeter-db").textContent.includes("nicht verfügbar"));
  assert.equal(calls("/api/admin/dbstat"), 1, "kein weiterer dbstat-Aufruf");
});

test("Laufkasten Rausverschieben: Endstand aus der Zusammenfassung, nicht vom letzten Zwischenstand", async () => {
  state.status = { ...state.status, running: true, label: { key: "taskMoveout" }, elapsed: 5,
    current_file: { params: { index: 4, total: 78, name: "a.png" } },
    report: { media_files: 3 }, queue: [], queue_pending: 0 };
  await status.pollOnce();
  const box = document.getElementById("moRun");
  assert.equal(box.hidden, false);
  assert.equal(document.getElementById("moCnts").textContent.trim(), "3 / 78");
  state.status = { ...state.status, running: false, label: null, current_file: null, report: { media_files: 77 },
    finished_seq: 9,
    history: [{ label: { key: "taskMoveout" }, ok: true, elapsed: 12, finished_at: "2026-09-13T10:00:00Z",
                result: { key: "sumMoveout", params: { parts: [
                  { key: "sumMoveMoved", params: { n: 78 } }, { key: "sumMoveMissing", params: { n: 1 } }] } } }] };
  await status.pollOnce();
  await flush();
  const cnts = document.getElementById("moCnts").textContent.trim();
  assert.equal(cnts, "78 / 79", "verschoben / Kandidaten (78 + 1 nicht mehr auffindbar), kein Zwischenstand");
  assert.ok(box.classList.contains("done"));
});

test("Gemerkter Stand (#118): Meter zeigen Stand + Zeit; „Fundorte prüfen“/„Cache zählen“ zählen auf Klick und laden den Stand neu; „überall“ in der Aufräum-Karte zieht das Meter nach", async () => {
  const { timing } = await import("../../src/feral/web/static/js/admin/util.js");
  timing.recheckMs = 1;
  const raw = () => document.getElementById("mtMeter-raw");
  const thumbs = () => document.getElementById("mtMeter-thumbs");
  assert.ok(raw().textContent.includes("Stand"), raw().textContent);
  assert.ok(thumbs().textContent.includes("Stand") && document.getElementById("mtHead-thumbs").textContent.includes("MB"));
  const infoBefore = calls("/api/admin/info"), orphBefore = calls("/api/admin/orphans");
  const countBefore = mockApi.calls.filter((c) => c.method === "GET" && c.path === "/api/admin/thumbcache").length;
  assert.equal(countBefore, 0, "kein Verzeichnislauf beim Seitenladen");
  click(document.getElementById("mtCacheCount"));
  await flush();
  assert.equal(mockApi.calls.filter((c) => c.method === "GET" && c.path === "/api/admin/thumbcache").length, 1, "Verzeichnislauf nur auf Klick");
  assert.equal(calls("/api/admin/info"), infoBefore + 1, "danach Stand neu geladen");
  click(document.getElementById("mtOrphCheck"));
  await flush();
  assert.equal(calls("/api/admin/orphans"), orphBefore + 1);
  assert.equal(mockApi.callsTo("/api/admin/orphans").at(-1).params.get("under"), null, "Meter prüft überall");
  assert.equal(calls("/api/admin/info"), infoBefore + 2);
  // Nie gezählt + Hintergrund-Zählung: „?" bzw. „…" mit Hinweis, Knopf gesperrt, Nachfrage bis der Stand da ist.
  let round = 0;
  mockApi.get("/api/admin/info", () => {
    round += 1;
    const base = { stats: {}, parsers: [], db_bytes: 1, wal_bytes: 0, schema_version: 23, open_issues: 0, blocked_count: 0,
                   db_path: "/x", log_dir: null, ffprobe: true, ffmpeg: true };
    return round === 1 ? { ...base, orphans: null, cache: null, checking: ["cache"] }
                       : { ...base, orphans: null, cache: { count: 9, bytes: 1e6, at: "2026-09-13T10:00:00Z" }, checking: [] };
  });
  document.getElementById("prScopeAll").checked = true;
  document.getElementById("prScopeUnder").checked = false;
  click(document.getElementById("prCheck"));
  await flush();
  assert.ok(raw().textContent.includes("noch nicht geprüft") && raw().querySelector(".mh b").textContent === "?");
  assert.equal(document.getElementById("mtOrphCheck").disabled, false);
  await flush(12);
  assert.ok(round >= 2, `Nachfrage während der Hintergrund-Zählung (${round})`);
  assert.ok(thumbs().textContent.includes("9") && thumbs().textContent.includes("Stand"), thumbs().textContent);
  assert.equal(document.getElementById("mtCacheCount").disabled, false);
});
