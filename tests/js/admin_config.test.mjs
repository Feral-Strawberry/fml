// admin_config.test.mjs — Seite „Konfiguration" (ADR 0074, A2 #106): fünf
// Karten in Reihen, je Einstellung Label/Eingabe/Erklärung/Badge; die
// Speicherleiste erscheint nur bei ungespeicherten Änderungen (Dirty-
// Erkennung über den Schnappschuss), Speichern schickt alle Felder, Verwerfen
// stellt den gespeicherten Stand her. Sprache/Darstellung sind Browser-Sache
// und machen NICHT dirty. Langsam-Schwelle (#110): Profile ↔ Zahlenfeld.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { bootAdmin, click, flush } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";

let state;
let posted = [];
const CONFIG = {
  editable: true, path: "/x/config.toml", exists: true,
  thumbnail_size: 320, library_root: "/lib", verwaltung: true, import_min_date: "2015-01-01",
  import_rules: { min_kante: 240, max_kante: 0, formate: ["psd"] },
  thumbnail_low_priority: true, thumbnail_workers: 0, show_dupes: true, model_sort: "zuletzt",
  web_port: 8765, instanz_name: "", akzentfarbe: "", rankings_enabled: false, slow_request_ms: 250,
};

before(async () => {
  state = await bootAdmin("/admin/config");
  mockApi.get("/api/admin/config", () => CONFIG);
  mockApi.post("/api/admin/config", ({ body }) => { posted.push(body); return { saved: true, hint: { key: "cfgSavedHint" } }; });
  await state.main.show("config");
  await flush();
});

const field = (key) => document.querySelector(`[data-key="${key}"]`);
const bar = () => document.getElementById("cfgBar");
function edit(el, value) {
  if (el.type === "checkbox") el.checked = value; else el.value = value;
  el.dispatchEvent(new Event(el.localName === "select" ? "change" : "input", { bubbles: true }));
}

test("fünf Karten in Reihen; je Zeile Label + Badge + Erklärung darunter; Leiste zunächst versteckt", () => {
  const rows = document.querySelectorAll("#cfgBody .row");
  assert.equal(rows.length, 3);
  assert.equal(document.querySelectorAll("#cfgBody .card").length, 5);
  assert.ok(rows[0].className.includes("c2") && rows[1].className.includes("c2"));
  const line = field("thumbnail_size").closest(".cfgline");
  assert.ok(line.querySelector(".lab .badge").textContent.length > 0, "Badge Neustart");
  assert.ok(!line.querySelector(".lab .badge").className.includes("now"));
  assert.ok(line.querySelector(".hint2").textContent.length > 0, "Erklärung darunter");
  assert.ok(field("library_root").closest(".cfgline").querySelector(".badge.now"));
  assert.equal(bar().hidden, true);
  assert.ok(document.getElementById("cfgFile").textContent.includes("/x/config.toml"));
});

test("Dirty-Erkennung: Änderung zeigt die Leiste mit Zähler, Rücknahme versteckt sie wieder", () => {
  edit(field("thumbnail_size"), "512");
  assert.equal(bar().hidden, false);
  assert.equal(document.getElementById("cfgCount").textContent, "1 Änderung");
  edit(field("verwaltung"), false);
  assert.equal(document.getElementById("cfgCount").textContent, "2 Änderungen");
  edit(field("thumbnail_size"), "320");
  edit(field("verwaltung"), true);
  assert.equal(bar().hidden, true);
});

test("Sprache und Darstellung machen nicht dirty (Browser-Sache, ADR 0054)", () => {
  const theme = document.getElementById("cfgTheme");
  theme.value = "light";
  theme.dispatchEvent(new Event("change", { bubbles: true }));
  assert.equal(bar().hidden, true);
  assert.equal(localStorage.getItem("feral-theme"), "light");
  theme.value = "dark";
  theme.dispatchEvent(new Event("change", { bubbles: true }));
});

test("Verwerfen stellt den gespeicherten Stand her", () => {
  edit(field("instanz_name"), "Archiv");
  edit(field("rankings_enabled"), true);
  assert.equal(bar().hidden, false);
  click(document.getElementById("cfgDiscard"));
  assert.equal(field("instanz_name").value, "");
  assert.equal(field("rankings_enabled").checked, false);
  assert.equal(bar().hidden, true);
});

test("Langsam-Schwelle: Profil setzt das Zahlenfeld, „Eigener Wert“ zeigt es", () => {
  const sel = document.getElementById("cfgSlowProfile");
  const num = field("slow_request_ms");
  assert.equal(sel.value, "250");
  assert.equal(num.hidden, true);
  edit(sel, "1500");
  assert.equal(num.value, "1500");
  assert.equal(num.hidden, true);
  assert.equal(document.getElementById("cfgCount").textContent, "1 Änderung");
  edit(sel, "x");
  assert.equal(num.hidden, false);
  edit(num, "900");
  assert.equal(document.getElementById("cfgCount").textContent, "1 Änderung");
});

test("Speichern schickt alle Felder (auch slow_request_ms), Leiste verschwindet, Rückmeldung inline", async () => {
  posted = [];
  edit(field("import_formate"), "psd, ARW");
  click(document.getElementById("cfgSave"));
  await flush();
  assert.equal(posted.length, 1);
  const b = posted[0];
  assert.equal(b.slow_request_ms, 900);
  assert.deepEqual(b.import_formate_ausschliessen, ["psd", "arw"]);
  assert.equal(b.thumbnail_size, 320);
  assert.equal(b.thumbnail_low_priority, true);
  assert.equal(b.akzentfarbe, "");
  assert.equal(b.web_port, 8765);
  assert.equal(bar().hidden, true, "nach dem Speichern ist nichts mehr dirty");
  assert.ok(document.getElementById("cfgStatus").textContent.includes("Gespeichert"));
  // Der neue Stand ist jetzt der Schnappschuss: Zurückstellen macht wieder dirty.
  edit(field("import_formate"), "psd");
  assert.equal(bar().hidden, false);
  click(document.getElementById("cfgDiscard"));
  assert.equal(field("import_formate").value, "psd, ARW");
});

test("Farbwahl schaltet die eigene Akzentfarbe mit ein; Serverfehler bleibt in der Leiste", async () => {
  edit(field("akzentfarbe"), "#3b82f6");
  assert.equal(field("akzent_on").checked, true);
  mockApi.post("/api/admin/config", () => mockApi.status(400, { detail: { key: "errAccent" } }));
  click(document.getElementById("cfgSave"));
  await flush();
  assert.equal(bar().hidden, false);
  assert.ok(document.getElementById("cfgBarMsg").textContent.length > 0);
});

test("Ohne --config: ehrlicher Hinweis statt Formular", async () => {
  mockApi.get("/api/admin/config", () => ({ editable: false }));
  await state.main.show("config");
  await flush();
  assert.equal(document.getElementById("cfgBar"), null);
  assert.ok(document.getElementById("cfgBody").textContent.includes("--config"));
});
