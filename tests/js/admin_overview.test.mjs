// admin_overview.test.mjs — Seite „Übersicht" (ADR 0074 + Nachtrag, Mockup
// #104 Runde 5): Kennzahl-Kacheln mit Quoten, Zusammensetzung/Zuwachs/
// Jahrgänge, Aktivität mit Trichter/Neu/Verlauf, System-Kacheln, Hinweis-
// karten mit Links; Kennzahlen laden neu, wenn eine Aufgabe fertig wurde.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { bootAdmin, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";

const { pollOnce } = await import("../../src/feral/web/static/js/status.js");
let state;
const $ = (id) => document.getElementById(id);

before(async () => { state = await bootAdmin("/admin"); });

test("Kennzahl-Kacheln: sechs Kacheln mit Quoten-Balken, Items mit „+heute“", () => {
  const kpis = [...document.querySelectorAll("#kpis .kpi")];
  assert.equal(kpis.length, 6);
  assert.ok(kpis[0].innerHTML.includes(">3<") && kpis[0].textContent.includes("+2 heute"), kpis[0].innerHTML);
  // ohne Media Library: „katalogisiert gesamt" statt Library-Kachel
  assert.ok(kpis[1].textContent.includes("katalogisiert gesamt"));
  // mit Metadaten 2/3 → 67 %, Balken folgt
  assert.ok(kpis[2].textContent.includes("67 %") && kpis[2].innerHTML.includes("width:67%"), kpis[2].innerHTML);
  assert.ok(kpis[3].textContent.includes("33 %"));
  assert.ok(kpis[5].textContent.includes("davon WAL"));
});

test("Zusammensetzung nach Typ als Stapelbalken mit Tabellen-Legende; Zuwachs; Jahrgänge", () => {
  const t = $("pType");
  assert.equal(t.querySelectorAll(".comp > i").length, 2);
  assert.ok(t.querySelector(".lg").textContent.includes("PNG") && t.querySelector(".lg").textContent.includes("67 %"));
  // Beide Typen mit Anteil UND Speicher (Summe = katalogisiert gesamt): 2 GB + 1 GB
  assert.ok(t.textContent.includes("Bilder 67 % · 2 GB"), t.textContent);
  assert.ok(t.textContent.includes("Videos 33 % · 1 GB"), t.textContent);
  assert.equal($("growCols").querySelectorAll("i").length, 30);
  assert.ok($("growCols").lastChild.className.includes("hi"), "heute hervorgehoben");
  assert.ok($("growSum").textContent.includes("2"));
  assert.equal($("yearCols").querySelectorAll("i").length, 2);
  assert.ok($("yearAxis").textContent.includes("2026"));
});

test("Aktivität im Leerlauf: bereit, kein Trichter, leerer Verlauf", () => {
  assert.equal($("aTask").textContent, "bereit.");
  assert.equal($("funnelNone").hidden, false);
  assert.equal($("funnel").hidden, true);
  assert.ok($("gantt").textContent.includes("noch nichts erledigt"));
  assert.ok($("qlist").textContent.includes("nichts wartet"));
});

test("Laufender Scan: Balken, Fortschrittszeile, Trichter mit Abfällen, „Neu in diesem Lauf“", async () => {
  state.status = { ...state.status, running: true, worker_alive: true, elapsed: 98, started_at: "2026-09-12T10:00:00Z",
    label: { key: "taskRescan" }, current_file: { key: "progressFile", params: { index: 60, total: 100 } },
    report: { scanned_files: 60, media_files: 55, new_items: 2, known_items: 50, with_metadata: 40,
              interpreted: 38, pending_extractor: 1, skipped_unknown: 4, ausgefiltert: 1, failed: 3 },
    queue_pending: 1, queue: [{ key: "taskReindex" }] };
  await pollOnce(); await flush();
  assert.equal($("aBar").style.width, "60%");
  assert.equal($("aDot").className, "dot");
  assert.ok($("aLeft").textContent.includes("60") && $("aLeft").textContent.includes("60 %"), $("aLeft").textContent);
  assert.equal($("funnel").hidden, false);
  const labels = [...$("funnel").querySelectorAll(".l")].map((e) => e.textContent);
  assert.deepEqual(labels, ["betrachtet", "Medien", "aufgenommen", "mit Metadaten", "interpretiert"]);
  const drops = [...$("funnel").querySelectorAll(".drop")].map((e) => e.textContent);
  assert.deepEqual(drops, ["−5 ausgefiltert · übersprungen", "−3 fehlgeschlagen", "−12 ohne Metadaten", "−2 Extraktor fehlt · unverstanden"]);
  assert.ok($("funnel").querySelector(".drop.hit"), "Fehlschläge rot");
  assert.equal($("lNew").textContent, "2");
  assert.equal($("qCount").textContent, "1");
  assert.ok($("qlist").textContent.includes("Suchindex aufbauen"));
});

test("Verlauf zeigt die letzten Aufgaben mit Dauer; Fehlschlag rot", async () => {
  state.status = { ...state.status, running: false, label: null, current_file: null, elapsed: null,
    queue_pending: 0, queue: [], finished_seq: 1, last_finished: { key: "taskRescan" },
    history: [
      { label: { key: "taskRescan" }, result: { key: "sumTest", params: { n: 1 } }, ok: true, elapsed: 120, finished_at: "x" },
      { label: { key: "taskReparse" }, result: { key: "sumFailed", params: { error: "kaputt" } }, ok: false, elapsed: 3, finished_at: "x" },
    ] };
  await pollOnce(); await flush();
  const rows = [...$("gantt").querySelectorAll(".l")].map((e) => e.textContent);
  assert.deepEqual(rows, ["Re-Scan: alle bekannten Fundorte", "Neu interpretieren (Schicht 2)"]);
  const vals = [...$("gantt").querySelectorAll(".v")].map((e) => e.textContent);
  assert.deepEqual(vals, ["2:00", "0:03 · Fehler"]);
  assert.ok($("gantt").querySelector(".v.err"));
});

test("Fertige Aufgabe (finished_seq) lädt Kennzahlen und Übersichts-Zahlen neu", async () => {
  const before = mockApi.callsTo("/api/admin/info").length;
  const beforeOv = mockApi.callsTo("/api/admin/overview").length;
  state.status = { ...state.status, finished_seq: 2 };
  await pollOnce(); await flush();
  assert.equal(mockApi.callsTo("/api/admin/info").length, before + 1);
  assert.equal(mockApi.callsTo("/api/admin/overview").length, beforeOv + 1);
  await pollOnce(); await flush();
  assert.equal(mockApi.callsTo("/api/admin/info").length, before + 1, "kein Dauerfeuer");
});

test("System-Kacheln: Werkzeuge, Datenbank, Speicherplatz-Donut, Parser, Instanz; Pfadzeile", () => {
  const tiles = [...document.querySelectorAll("#tiles .tile")];
  assert.equal(tiles.length, 6);
  assert.ok(tiles[1].textContent.includes("ffprobe") && tiles[1].innerHTML.includes("2<small>/ 2"));
  assert.ok(tiles[2].textContent.includes("Schema v23"));
  assert.ok(tiles[3].innerHTML.includes('stroke-dasharray="56 100"') && tiles[3].textContent.includes("56 %"), tiles[3].innerHTML);
  assert.ok(tiles[4].textContent.includes("comfyui") && tiles[4].textContent.includes("v11"));
  assert.ok(tiles[5].textContent.includes("Port 8766") && tiles[5].textContent.includes("Übersichtsmodus"));
  assert.ok(tiles[5].textContent.includes("1:01:40"), "Laufzeit");
  // Laufzeit-Pakete (#42): Pillow passt, fastapi weicht vom Pin ab, uvicorn fehlt
  assert.ok(tiles[5].textContent.includes("Pillow 12.3.0"), tiles[5].textContent);
  assert.ok(tiles[5].innerHTML.includes('class="warn"') && tiles[5].textContent.includes("0.136.3 ≠ 0.141.1"));
  assert.ok(tiles[5].textContent.includes("uvicorn") && tiles[5].textContent.includes("fehlt"));
  assert.ok(tiles[5].querySelector(".dot.warn"), "Warn-Punkt bei Drift");
  assert.ok(tiles[5].textContent.includes("pip install -r requirements.txt"));
  assert.ok($("paths").textContent.includes("/x/feral.sqlite") && $("paths").textContent.includes("keine konfiguriert"));
});

test("Hinweiskarten verlinken auf Wartung/Probleme/Quellen; Quellen-Karte folgt dem Status", async () => {
  const hints = [...document.querySelectorAll("#hints .hint")];
  assert.equal(hints.length, 4);
  assert.deepEqual(hints.map((h) => h.querySelector("a.link").getAttribute("href")),
    ["/admin/maintenance", "/admin/issues", "/admin/issues", "/admin/sources"]);
  assert.ok(hints[1].className.includes("good"));
  state.status = { ...state.status, watchers: [{ name: "out", path: "/o", pending: 3 }] };
  await pollOnce(); await flush();
  const src = $("hintSources");
  assert.equal(src.querySelector(".n").textContent, "1");
  assert.ok(src.textContent.includes("out · 3 wartend"), src.textContent);
});

test("Fehlende Werkzeuge: Hinweis im System-Kopf statt „alles grün“", async () => {
  mockApi.get("/api/stats", () => ({ total_items: 0, total_bytes: 0, by_container: [], total_locations: 0, instanz: {} }));
  mockApi.get("/api/admin/info", () => ({
    stats: {}, parsers: [], cache: { count: 0, bytes: 0, at: "2026-09-13T10:00:00Z" },
    orphans: { count: 2, at: "2026-09-13T10:00:00Z" }, checking: [],
    db_bytes: 0, wal_bytes: 0, schema_version: 23, open_issues: 1, blocked_count: 0,
    db_path: "/x", log_dir: null, ffprobe: false, ffmpeg: false,
  }));
  state.status = { ...state.status, finished_seq: 3 };
  await pollOnce(); await flush();
  assert.ok($("sysRight").textContent.includes("1 Hinweis"), $("sysRight").textContent);
  assert.ok($("pType").textContent.includes("noch keine Items"));
  const hints = [...document.querySelectorAll("#hints .hint")];
  assert.ok(hints[0].className.includes("warn") && hints[0].querySelector(".n").textContent === "2");
  assert.equal($("navCnt-issues").textContent, "1");
});

test("Gemerkter Stand (#118): nie gezählt → „?“ + Hinweis; Hintergrund-Zählung → „wird geprüft …“ und Nachfrage, bis der Stand da ist", async () => {
  const { timing } = await import("../../src/feral/web/static/js/admin/util.js");
  timing.recheckMs = 1;
  let round = 0;
  const done = { count: 0, at: "2026-09-13T10:10:00Z" }, cache = { count: 5, bytes: 1e6, at: "2026-09-13T10:00:00Z" };
  const gate = mockApi.gate();   // Runde 3 wartet: der Zwischenzustand „wird geprüft" bleibt prüfbar
  mockApi.get("/api/admin/info", async () => {
    round += 1;
    const base = { stats: {}, parsers: [], db_bytes: 0, wal_bytes: 0, schema_version: 23, open_issues: 0,
                   blocked_count: 0, db_path: "/x", log_dir: null, ffprobe: true, ffmpeg: true };
    if (round === 1) return { ...base, orphans: null, cache: null, checking: [] };
    if (round === 2) return { ...base, orphans: null, cache, checking: ["orphans"] };
    await gate.promise;
    return { ...base, orphans: done, cache, checking: [] };
  });
  state.status = { ...state.status, finished_seq: 4 };
  await pollOnce(); await flush();
  const hint = () => document.querySelector("#hints .hint");
  assert.equal(hint().querySelector(".n").textContent, "?", "nie geprüft");
  assert.ok(hint().textContent.includes("noch nicht geprüft"), hint().textContent);
  assert.ok($("kpis").textContent.includes("noch nicht gezählt"), "Cache nie gezählt");
  assert.equal(round, 1, "keine Nachfrage ohne laufende Zählung");
  state.status = { ...state.status, finished_seq: 5 };
  await pollOnce(); await flush(12);
  assert.equal(hint().querySelector(".n").textContent, "…");
  assert.ok(hint().textContent.includes("wird geprüft"), hint().textContent);
  assert.ok($("kpis").textContent.includes("Stand"), "Cache-Stand mit Zeitstempel");
  assert.equal(round, 3, "genau EINE Nachfrage läuft, solange die Antwort aussteht");
  gate.open();
  await flush(12);
  assert.equal(hint().querySelector(".n").textContent, "0");
  assert.ok(hint().className.includes("good"));
  assert.ok(hint().textContent.includes("Stand"), hint().textContent);
  const rounds = round;
  await flush(12);
  assert.equal(round, rounds, "keine weitere Nachfrage, sobald nichts mehr läuft");
});
