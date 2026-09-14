// admin_issues.test.mjs — Seite „Probleme" (A3, #107; schließt #66): je Fehlerart
// eine Karte mit ehrlichen Zählern, Alle-Knopf mit Gesamtzahl, Quittieren mit
// Rückmeldung und Neuladen; Sperrliste GETRENNT geladen, seitenweise (100),
// mit Suche über Pfad/Hash/Grund und Zähler vom Server; Entsperren einzeln
// und (bestätigt) alle.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { bootAdmin, click, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";

let state;
const resolved = [];
let blockedTotal = 250;
const blockedRows = (n, offset) => Array.from({ length: n }, (_, i) => ({
  file_hash: (offset + i).toString(16).padStart(64, "0"), reason: { key: "blockedRejected" },
  blocked_at: "2026-09-12T10:00:00", last_paths: [`/Volumes/Archiv/IMG_${offset + i}.jpg`],
}));

before(async () => {
  state = await bootAdmin("/admin/issues");
  mockApi.get("/api/admin/issues", () => ({
    total: resolved.length ? 0 : 3,
    kinds: resolved.length ? [] : [
      { kind: "thumbnail", count: 2, issues: [
        { id: 1, path: "/a.png", message: "kein Bild", last_seen_at: "2026-09-12T10:00:00" }] },
      { kind: "failed", count: 1, issues: [{ id: 2, path: "/b.png", message: "kaputt", last_seen_at: "" }] },
    ],
  }));
  mockApi.get("/api/admin/blocked", ({ params }) => {
    const q = params.get("q") || "", offset = +(params.get("offset") || 0), limit = +(params.get("limit") || 100);
    const total = q ? (q.includes("IMG_12") ? 11 : 0) : blockedTotal;
    const n = Math.max(0, Math.min(limit, total - offset));
    return { blocked: blockedRows(n, offset), total, total_all: blockedTotal, offset, limit };
  });
  mockApi.post("/api/admin/issues/resolve", ({ params }) => { resolved.push(params.get("kind") || params.get("issue_id") || "all"); return { resolved: 2 }; });
  mockApi.post("/api/admin/blocked/remove", ({ params }) => {
    const all = !params.get("file_hash");
    const removed = all ? blockedTotal : 1;
    blockedTotal = all ? 0 : blockedTotal - 1;
    return { removed };
  });
  await state.main.show("issues");
  await flush(10);
});

test("Karten je Fehlerart mit Zählern, Alle-Knopf mit echter Zahl, Sperrliste getrennt mit Server-Zähler", () => {
  const kinds = [...document.querySelectorAll(".issuekind")].map((c) => c.dataset.issuekind);
  assert.deepEqual(kinds, ["thumbnail", "failed"]);
  assert.ok(document.getElementById("adResolveAll").textContent.includes("3"), "Alle-Knopf nennt die echte Zahl");
  assert.ok(document.querySelector('.issuekind[data-issuekind="thumbnail"] .kindfoot').textContent.includes("1 von 2"), "jüngste 1 von 2");
  assert.equal(document.getElementById("navCnt-issues").textContent, "3");
  assert.equal(document.querySelectorAll("#ovBlocked .result").length, 100, "eine Seite = 100");
  assert.ok(document.getElementById("blkCount").textContent.includes("250"), "Zähler vom Server, kein Deckel");
  assert.ok(document.getElementById("blkRange").textContent.includes("1–100"));
  assert.equal(document.getElementById("blkPrev").disabled, true);
  assert.equal(document.getElementById("blkNext").disabled, false);
  assert.equal(mockApi.callsTo("/api/admin/blocked")[0].params.get("limit"), "100");
});

test("Blättern: Weiter lädt die nächste Seite, Zurück die vorige", async () => {
  click(document.getElementById("blkNext"));
  await flush();
  assert.equal(mockApi.callsTo("/api/admin/blocked").at(-1).params.get("offset"), "100");
  assert.ok(document.getElementById("blkRange").textContent.includes("101–200"));
  click(document.getElementById("blkNext"));
  await flush();
  assert.ok(document.getElementById("blkRange").textContent.includes("201–250"));
  assert.equal(document.getElementById("blkNext").disabled, true, "letzte Seite");
  click(document.getElementById("blkPrev"));
  click(document.getElementById("blkPrev"));
  await flush();
  assert.equal(document.getElementById("blkPrev").disabled, true);
});

test("Suche: Treffer mit ehrlichem „n von gesamt“, keine Treffer ehrlich gemeldet", async () => {
  const q = document.getElementById("blkQ");
  q.value = "IMG_12";
  q.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  await flush();
  const last = mockApi.callsTo("/api/admin/blocked").at(-1);
  assert.equal(last.params.get("q"), "IMG_12");
  assert.equal(last.params.get("offset"), null, "Suche beginnt bei Seite 1");
  assert.ok(document.getElementById("blkCount").textContent.includes("11"), document.getElementById("blkCount").textContent);
  assert.ok(document.getElementById("blkCount").textContent.includes("250"));
  assert.equal(document.querySelectorAll("#ovBlocked .result").length, 11);
  q.value = "nix";
  q.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  await flush();
  assert.ok(document.getElementById("ovBlocked").textContent.includes("Keine Treffer"));
  q.value = "";
  q.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  await flush();
});

test("Quittieren einer Art meldet die Zahl und lädt die Karten neu; Navi-Zähler verschwindet", async () => {
  click(document.querySelector('[data-kind="thumbnail"]'));
  await flush();
  assert.deepEqual(resolved, ["thumbnail"]);
  assert.ok(document.getElementById("issMsg").textContent.includes("2"), "Rückmeldung mit Zahl");
  assert.equal(document.querySelectorAll(".issuekind").length, 0);
  assert.ok(document.getElementById("issSummary").textContent.includes("Keine"));
  assert.equal(document.getElementById("navCnt-issues").hidden, true);
  assert.equal(document.getElementById("adResolveAll").hidden, true);
});

test("Entsperren: einzeln lädt die Seite neu; alle nur nach Bestätigung", async () => {
  click(document.querySelector("[data-unblock]"));
  await flush();
  assert.ok(document.getElementById("blkMsg").textContent.includes("1"));
  assert.ok(document.getElementById("blkCount").textContent.includes("249"));
  click(document.getElementById("blkUnblockAll"));
  await flush();
  assert.ok(document.getElementById("dlgOk"), "Bestätigungsdialog");
  click(document.getElementById("dlgCancel"));
  await flush();
  assert.equal(mockApi.callsTo("/api/admin/blocked/remove").length, 1, "Abbrechen entsperrt nichts");
  click(document.getElementById("blkUnblockAll"));
  await flush();
  click(document.getElementById("dlgOk"));
  await flush();
  assert.equal(mockApi.callsTo("/api/admin/blocked/remove").at(-1).params.get("file_hash"), null);
  assert.ok(document.getElementById("ovBlocked").textContent.includes("Keine gesperrten"));
  assert.equal(document.getElementById("blkUnblockAll").hidden, true);
});
