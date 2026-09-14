// harness.mjs — gemeinsame Testhelfer für tests/js/*.test.mjs (ADR 0064).
//
// loadShell()  baut die ECHTE index.html (oder admin.html) in den DOM-Stub
//              (gleiche IDs wie im Browser: #loupe, #single, #rankings, #gridwrap …).
// keydown()/click()  schicken Ereignisse mit Capture-/Bubble-Phase.
// flush()      lässt anstehende Promises/Timer (fetch-Attrappe, rAF) laufen.
// xfail()      erwartet-roter Test mit Issue-Nummer: ein bekannter Fehler ist
//              als Test festgehalten, die Fix-Session macht daraus test().
//              Besteht er vorzeitig, wird das GEMELDET (strict wie pytest).

import { readFileSync } from "node:fs";
import { test } from "node:test";
import { mockApi } from "./apimock.mjs";
import { DomEvent } from "./dom.mjs";

const ROOT = new URL("../../", import.meta.url);
export const STATIC = new URL("src/feral/web/static/", ROOT);

/** Shell laden: "index.html" (Galerie, Standard) oder "admin.html" (ADR 0074). */
export function loadShell(name = "index.html") {
  const html = readFileSync(new URL(name, STATIC), "utf8");
  document.loadHtml(html);
  mockApi.reset();
  globalThis.__alerts.length = 0;
}

/** Tastendruck wie im Browser: am Body (bubbelt bis document/window). */
export function keydown(key, init = {}) {
  const target = init.target || document.body;
  const ev = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(ev);
  return ev;
}

export function click(target, init = {}) {
  if (!target) throw new Error("click(): Ziel fehlt (Selektor traf nichts?)");
  const ev = new MouseEvent("click", { bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(ev);
  return ev;
}

/** Mehrere Makrotask-Runden abwarten — fetch-Attrappe + verkettete awaits + rAF. */
export async function flush(rounds = 6) {
  for (let i = 0; i < rounds; i++) await new Promise((r) => setTimeout(r, 0));
}

// -- Synthetische Items --------------------------------------------------------------

export const hashOf = (n) => (n.toString(16).padStart(2, "0")).repeat(32);

export function item(n, extra = {}) {
  return {
    file_hash: hashOf(n), container: "png", media_kind: "image",
    width: 512, height: 512, fps: null, rating: 0, tool: "comfyui", ...extra,
  };
}

/** Detailantwort von /api/item/<hash> — minimal, aber vollständig genug für
 *  Lupe/Einzelansicht (locations, raw, interpreted, manual). */
export function itemDetail(it) {
  return {
    ...it,
    locations: [{ path: `/lib/2026/${it.file_hash.slice(0, 6)}.${it.container}` }],
    raw: [], interpreted: [],
    manual: { rating: it.rating || null, tags: [], notes: "", model: null },
  };
}

/** Standard-Routen für eine Galerie mit `items`: Seiten, Position, Detail, Thumb. */
export function serveLibrary(items) {
  const state = { items, gate: null };   // gate: Seitenantwort anhalten (Zwischenzustand)
  mockApi.get("/api/items", async ({ params }) => {
    if (state.gate) await state.gate.promise;
    const offset = parseInt(params.get("offset") || "0", 10);
    const limit = parseInt(params.get("limit") || "200", 10);
    return {
      total: params.get("total") === "1" ? state.items.length : -1,
      offset,
      items: state.items.slice(offset, offset + limit),
    };
  });
  mockApi.get("/api/items/position", ({ params }) => {
    const i = state.items.findIndex((it) => it.file_hash === params.get("hash"));
    return { index: i < 0 ? null : i };
  });
  mockApi.get(/^\/api\/item\/[0-9a-f]+$/, ({ path }) => {
    const hash = path.split("/").pop();
    const it = state.items.find((x) => x.file_hash === hash);
    return it ? itemDetail(it) : mockApi.status(404, { detail: "unbekannt" });
  });
  mockApi.get(/^\/api\/thumb\//, () => ({}));           // 200 → Blob → img.src gesetzt
  return state;
}

// -- Admin-Dokument (ADR 0074) --------------------------------------------------------

/** Leerlauf-Status von /api/status, wie ihn der Poller sieht. */
export const idleStatus = () => ({
  running: false, label: null, current_file: null, report: {}, last_finished: null,
  last_result: null, queue_pending: 0, queue: [], worker_alive: null, watchers: [],
  finished_seq: 0, history: [], elapsed: null, started_at: null,
});

/** Grundausstattung der Admin-Endpunkte mit harmlosen Antworten; einzelne
 *  Routen überschreibt ein Test danach per mockApi.get(). Liefert das
 *  veränderliche Status-Objekt (Tests setzen Felder und stoßen pollOnce an). */
export function mockAdminApi() {
  const state = { status: idleStatus() };
  mockApi.get("/api/status", () => state.status);
  mockApi.get("/api/stats", () => ({
    total_items: 3, total_bytes: 3e9, items_with_metadata: 2, items_interpreted: 1,
    library_configured: false, library_bytes: 0, total_locations: 3,
    by_container: [{ container: "png", count: 2 }, { container: "mp4", count: 1 }],
    instanz: { name: "", farbe: "" },
  }));
  mockApi.get("/api/admin/info", () => ({
    stats: { total_items: 3, total_bytes: 3e9, items_with_metadata: 2, items_interpreted: 1,
             library_configured: false, library_bytes: 0, total_locations: 3,
             by_container: [{ container: "png", count: 2 }, { container: "mp4", count: 1 }] },
    parsers: [{ name: "comfyui", version: 11 }, { name: "a1111", version: 3 }],
    db_bytes: 2e9, wal_bytes: 1e8, schema_version: 23,
    // Gemerkter Stand der teuren Zähler (#118): {…, at} oder null = nie gezählt.
    orphans: { count: 0, at: "2026-09-13T10:00:00Z" },
    cache: { count: 1, bytes: 5e6, at: "2026-09-13T10:00:00Z" }, checking: [],
    open_issues: 0, blocked_count: 0,
    db_path: "/x/feral.sqlite", log_dir: "/x/logs", ffprobe: true, ffmpeg: true,
  }));
  mockApi.get("/api/admin/thumbcache", () => ({ count: 2, bytes: 3e6, at: "2026-09-13T10:05:00Z" }));
  mockApi.get("/api/admin/overview", () => ({
    by_kind: [{ kind: "image", count: 2, bytes: 2e9 }, { kind: "video", count: 1, bytes: 1e9 }],
    by_year: [{ year: "2025", count: 1 }, { year: "2026", count: 2 }],
    growth: Array.from({ length: 30 }, (_, i) => ({ day: `2026-09-${String(i + 1).padStart(2, "0")}`, count: i === 29 ? 2 : 0 })),
    disks: [{ for: "db", path: "/x", total: 1000, used: 560, free: 440 }],
    uptime: 3700, versions: { fml: "2026.07.3+dev", python: "3.13.5", sqlite: "3.50.0" },
    packages: [{ name: "Pillow", installed: "12.3.0", pinned: "12.3.0", ok: true },
               { name: "fastapi", installed: "0.136.3", pinned: "0.141.1", ok: false },
               { name: "uvicorn", installed: null, pinned: "0.52.4", ok: false }],
    pool_workers: 6, port: 8766, library_root: null, verwaltung: false,
  }));
  mockApi.get("/api/admin/log", ({ params }) => ({
    log_dir: "/x/logs",
    files: [{ name: params.get("file") === "worker" ? "fml-worker.log" : "fml-web.log", bytes: 0, lines: [] }],
  }));
  mockApi.get("/api/watch", () => ({ sources: [], has_library: true, verwaltung: true }));
  mockApi.get("/api/admin/issues", () => ({ total: 0, kinds: [] }));
  mockApi.get("/api/admin/blocked", () => ({ blocked: [], total: 0, total_all: 0, offset: 0, limit: 100 }));
  mockApi.get("/api/admin/maintenance", () => ({
    parsers: [{ parser: "comfyui", version: 11, items: 2 }, { parser: "a1111", version: 3, items: 0 }],
    undated: 1, open_issues: 0, blocked_count: 0, dbstat: true,
  }));
  mockApi.get("/api/admin/dbstat", () => ({
    available: true, free_bytes: 1e8, index_bytes: 3e8,
    groups: [{ key: "raw", bytes: 1e9 }, { key: "items", bytes: 4e8 }, { key: "interpreted", bytes: 3e8 },
             { key: "search", bytes: 1e8 }, { key: "other", bytes: 1e8 }],
  }));
  mockApi.get("/api/admin/import-rules", () => ({ active: false, rules: {}, counts: {}, total: 0 }));
  mockApi.get("/api/admin/config", () => ({ editable: false }));
  mockApi.get("/api/rankings", () => ({ rankings: [] }));
  mockApi.get("/api/roots", () => ({ roots: [{ name: "Home", path: "/home/j" }] }));
  mockApi.get("/api/browse", ({ params }) => ({
    path: params.get("path"), parent: null, file_count: 0, subdirs: [],
  }));
  mockApi.get("/api/admin/moveout", () => ({
    available: true, locked: false, movable: 3, bytes: 1e6, sample: ["/lib/a.png"], missing: 0,
  }));
  return state;
}

/** Admin-Dokument unter `path` booten (Shell + Attrappen + main.js). */
export async function bootAdmin(path = "/admin") {
  loadShell("admin.html");
  const state = mockAdminApi();
  globalThis.location.pathname = path;
  // Erst NACH loadShell importieren: main.js bootet beim Laden (Navi, Router).
  state.main = await import("../../src/feral/web/static/js/admin/main.js");
  await flush(8);
  return state;
}

export function popstate() {
  globalThis.dispatchEvent(new DomEvent("popstate"));
}

// -- Erwartet-rot -------------------------------------------------------------------

export function xfail(name, issue, fn) {
  return test(`${name} [erwartet rot bis #${issue}]`, async (t) => {
    try {
      await fn(t);
    } catch (err) {
      t.diagnostic(`erwartet rot (#${issue}): ${String(err.message).replace(/\s+/g, " ").slice(0, 160)}`);
      return;
    }
    throw new Error(
      `Test besteht bereits — Issue #${issue} scheint behoben: xfail() durch test() ersetzen.`);
  });
}

/** Invariante der Overlays: nie zwei Vollbild-Ebenen gleichzeitig sichtbar. */
export function visibleOverlays() {
  return ["loupe", "single", "compare", "rankings"]
    .filter((id) => !document.getElementById(id).hidden);
}
