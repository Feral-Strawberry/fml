// admin_overview_pending.test.mjs — Übersicht in zwei Stufen (erster Test
// 2026-09-12: Seite blieb Sekunden leer): schnelle Zahlen (/api/stats,
// /api/admin/overview) stehen sofort, /api/admin/info (Werkzeuge, DB,
// Parser, Fundorte, Cache) kommt nach — bis dahin „…". Eigener Prozess,
// weil die Seite geladene Zahlen über Seitenwechsel behält.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, mockAdminApi, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";

const $ = (id) => document.getElementById(id);
let release;

before(async () => {
  loadShell("admin.html");
  mockAdminApi();
  mockApi.get("/api/admin/info", () => new Promise((r) => { release = r; }));
  globalThis.location.pathname = "/admin";
  await import("../../src/feral/web/static/js/admin/main.js");
  await flush(8);
});

test("vor /api/admin/info: Kennzahlen aus /api/stats stehen, teure Stellen zeigen „…“ + Hinweis", () => {
  assert.equal($("sysRight").textContent, "lädt Systemzustand …");
  assert.ok($("kpis").textContent.includes("Items") && $("kpis").innerHTML.includes(">3<"), "schnelle Kennzahlen da");
  assert.ok($("kpis").querySelectorAll(".pending").length >= 2, "Thumbnails/DB warten");
  assert.ok($("hints").querySelectorAll(".pending").length >= 3, "Hinweiskarten warten");
  assert.ok($("tiles").innerHTML.includes("pending"), "Werkzeuge/DB/Parser-Kacheln warten");
  assert.ok($("pType").textContent.includes("PNG"), "Diagramme aus /api/admin/overview stehen");
  assert.ok(!$("pageBody").innerHTML.includes("animation"), "keine Einblend-Animation");
});

test("nach /api/admin/info: alles gefüllt, kein „…“ mehr", async () => {
  release({ stats: {}, parsers: [{ name: "comfyui", version: 11 }],
            cache: { count: 4, bytes: 1e6, at: "2026-09-13T10:00:00Z" },
            orphans: { count: 1, at: "2026-09-13T10:00:00Z" }, checking: [],
            db_bytes: 1e9, wal_bytes: 0, schema_version: 23, open_issues: 0,
            blocked_count: 0, db_path: "/x", log_dir: "/x/logs", ffprobe: true, ffmpeg: true });
  await flush();
  assert.equal($("pageBody").querySelectorAll(".pending").length, 0);
  assert.ok($("kpis").textContent.includes("Stand"), "Cache-Kennzahl trägt den Zeitstempel des Standes (#118)");
  assert.ok($("sysRight").textContent.includes("alles grün"));
  assert.ok($("tiles").textContent.includes("comfyui"));
  assert.equal($("hints").querySelector(".hint .n").textContent, "1");
  assert.equal($("navMeta").textContent, "Schema v23 · :8766");
});
