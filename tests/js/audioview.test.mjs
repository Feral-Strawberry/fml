// audioview.test.mjs — Audioansicht (ADR 0085, #159): der Umschalter setzt
// den Grundbereich (?view=), die Galerie wird zur Liste mit Zeilen, Leertaste
// spielt statt Lupe, Sterne bewerten in der Zeile, Chips bleiben beim Wechsel;
// Sidebar-Gruppen nach Geltungsbereich; Leer-Hinweis und Navigationszeile der
// Tipphilfe schalten nie selbst um (ADR 0084).

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, keydown, click, flush, item, hashOf, serveLibrary } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit, record } from "./bus.mjs";
import { DomEvent } from "./dom.mjs";

// Gemerkte Ansicht: Audio (gilt ab dem ersten Laden, libview.js).
localStorage.setItem("feral-view", "audio");

const { commonPrefix } = await import("../../src/feral/web/static/js/audiolist.js");
const { initAudioList } = await import("../../src/feral/web/static/js/audiolist.js");
const { initLibraryView } = await import("../../src/feral/web/static/js/libview.js");
const { initGallery, viewHint } = await import("../../src/feral/web/static/js/gallery.js");
const { initSidebar } = await import("../../src/feral/web/static/js/sidebar.js");
const { initLoupe } = await import("../../src/feral/web/static/js/loupe.js");
const { navSuggestion, visibleCats } = await import("../../src/feral/web/static/js/advanced.js");
const { initSearch, pruneForView } = await import("../../src/feral/web/static/js/search.js");

const songs = [
  item(1, { media_kind: "audio", container: "mp3", width: null, height: null, duration: 187,
            name: "Regenzeit v3 refrain lauter.mp3", model: "Suno v4.5", tool: "suno" }),
  item(2, { media_kind: "audio", container: "mp3", width: null, height: null, duration: 190,
            name: "Regenzeit v3 refrain leiser.mp3", tool: "suno", rating: 2 }),
  item(3, { media_kind: "audio", container: "flac", width: null, height: null, duration: 95,
            name: "yue2_00001_.flac", tool: "comfyui" }),
];
const grid = () => document.getElementById("grid");
const rows = () => grid().querySelectorAll(".arow");
const facets = {
  media_kinds: [], containers: [], formats: {}, megapixels: {}, years: [], undated: 0,
  undated_total: 0, loras: [], input_image: { mit: 0, ohne: 3 }, lyrics: { mit: 1, ohne: 2 },
  fundort: null, tags: [], tools: [],
};

// Fake-<audio>: der DOM-Stub spielt nichts ab.
const played = [];
const origCreate = document.createElement.bind(document);
document.createElement = (tag) => {
  if (tag !== "audio") return origCreate(tag);
  const el = origCreate("div");
  Object.assign(el, {
    paused: true, currentTime: 0, duration: NaN, src: "",
    // Wie der Browser: Zustandswechsel melden sich als Ereignis.
    play() { this.paused = false; played.push(this.src); this.dispatchEvent(new DomEvent("play")); return Promise.resolve(); },
    pause() { this.paused = true; this.dispatchEvent(new DomEvent("pause")); },
  });
  return el;
};

before(async () => {
  loadShell();
  serveLibrary(songs);
  mockApi.get("/api/stats", () => ({
    total_items: 10, items_multi_location: 0, total_bytes: 1e6,
    library_configured: false, rankings: false, audio: true,
  }));
  mockApi.get("/api/folders", () => ({ folders: [] }));
  mockApi.get("/api/sidebar", () => ({
    models: { models: [], unknown: 0, unknown_total: 0 }, facets,
    ratings: { ratings: [] }, total: 3,
  }));
  // Grammatik lebt serverseitig (ADR 0035): Attrappe, die Chips 1:1 spiegelt.
  const text = (p) => `${p.negated ? "-" : ""}${p.kind}: ${p.values.map((v) => v.value).join(" | ")}`;
  mockApi.post("/api/filter/build", ({ body }) => ({
    expression: body.predicates.map(text).join(" "), predicates: body.predicates, sort: null }));
  mockApi.post(/^\/api\/item\/[0-9a-f]+\/rating$/, ({ body }) =>
    ({ manual: { rating: body.rating || null, tags: [], notes: "", model: null } }));
  document.rectFor = (el) => (el.classList.contains("tile") ? { height: 65 } : null);
  document.getElementById("gridwrap").clientHeight = 1000;
  initLibraryView();
  initGallery();
  initSidebar();
  initLoupe();
  initSearch();
  initAudioList();
  await flush(10);
});

test("gemeinsamer Anfang: ab 8 Zeichen, an der Wortgrenze, nie der ganze Name", () => {
  assert.equal(commonPrefix("Regenzeit v3 refrain leiser", "Regenzeit v3 refrain lauter"), 21);
  assert.equal(commonPrefix("yue2_00002_", "yue2_00001_"), 5);
  assert.equal(commonPrefix("song a", "song b"), 0);                // unter 8 Zeichen
  assert.equal(commonPrefix("Regenzeit v3", "Regenzeit v3"), 10);   // Rest bleibt stehen
});

test("gemerkte Audioansicht lädt sofort mit ?view=audio und zeigt Zeilen statt Kacheln", () => {
  const calls = mockApi.callsTo("/api/items");
  assert.ok(calls.length && calls.every((c) => c.params.get("view") === "audio"));
  assert.equal(rows().length, 3);
  assert.ok(document.body.classList.contains("view-audio"));
  assert.equal(document.getElementById("listhead").hidden, false);
  assert.equal(document.getElementById("viewseg").hidden, false);   // Modul an
  // Dateiname als Hauptzeile, der mit der Vorzeile gemeinsame Anfang abgedunkelt.
  const second = rows()[1];
  assert.equal(second.querySelector(".pre").textContent, "Regenzeit v3 refrain ");
  assert.equal(second.querySelector("b").textContent, "leiser");
  assert.equal(rows()[0].querySelector(".rtool").textContent, "Suno v4.5");
});

test("Leertaste spielt die ausgewählte Zeile (keine Lupe), zweimal pausiert", async () => {
  emit("selection-changed", { hash: hashOf(2), index: 1 });
  keydown(" ");
  await flush();
  assert.equal(document.getElementById("loupe").hidden, true);
  assert.equal(played.at(-1), `/api/preview/${hashOf(2)}`);   // Original oder FLAC-Proxy (A4 #161)
  assert.ok(rows()[1].classList.contains("playing"));
  keydown(" ");
  await flush();
  assert.ok(!rows()[1].classList.contains("playing"));
});

test("Stern in der Zeile bewertet ohne Auswahlwechsel; derselbe Stern nimmt weg", async () => {
  const sel = record("selection-changed");
  click(rows()[0].querySelector('.rdot[data-n="4"]'));
  await flush();
  const post = mockApi.calls.filter((c) => c.method === "POST").at(-1);
  assert.equal(post.path, `/api/item/${hashOf(1)}/rating`);
  assert.equal(post.body.rating, 4);
  click(rows()[1].querySelector('.rdot[data-n="2"]'));    // Item 2 hat schon 2
  await flush();
  assert.equal(mockApi.calls.filter((c) => c.method === "POST").at(-1).body.rating, 0);
  assert.equal(sel.length, 0);
  sel.stop();
});

test("Sidebar in der Audioansicht: Songtext statt LoRA/Format/Medienart, Alle = Grundbereich", () => {
  const group = (g) => document.querySelector(`.sbgroup[data-group="${g}"]`);
  for (const g of ["lora", "format", "megapixels", "inputimage", "mediakind", "rankings"]) {
    assert.ok(group(g).classList.contains("offview"), g);
  }
  assert.ok(!group("lyrics").classList.contains("offview"));
  const labels = group("lyrics").querySelectorAll(".sblabel").map((l) => l.textContent);
  assert.deepEqual(labels, ["mit Gesang", "instrumental"]);
  assert.equal(document.getElementById("sbAllCount").textContent, "3");
  assert.ok(mockApi.callsTo("/api/sidebar").every((c) => c.params.get("view") === "audio"));
});

test("Umschalter: Galerie lädt EINMAL mit ?view=galerie; typ: audio und tag: bleiben (fertige Songs)", async () => {
  const tag = { kind: "tag", negated: false, field: "", op: "=", values: [{ value: "regenzeit", exact: true }] };
  const typ = { kind: "typ", negated: false, field: "", op: "=", values: [{ value: "audio", exact: false }] };
  emit("chip-toggle", { pred: tag });
  await flush();
  emit("chip-toggle", { pred: typ });
  await flush();
  const changed = record("search-state-changed");
  mockApi.calls.length = 0;
  click(document.querySelector('#viewseg button[data-view="galerie"]'));
  await flush(10);
  assert.ok(!document.body.classList.contains("view-audio"));
  assert.equal(document.getElementById("listhead").hidden, true);
  const pages = mockApi.callsTo("/api/items").filter((c) => c.params.get("offset") === "0");
  assert.equal(pages.length, 1, "ein Ladevorgang, kein Aufblitzen");
  assert.equal(pages[0].params.get("view"), "galerie");
  assert.equal(pages[0].params.get("filter"), "tag: regenzeit typ: audio");
  assert.ok(mockApi.callsTo("/api/sidebar").length, "Sidebar zählt neu");
  assert.equal(rows().length, 0);
  assert.equal(changed.length, 1);
  assert.equal(changed[0].viewChanged, true);
  assert.deepEqual(changed[0].predicates.map((p) => p.kind), ["tag", "typ"]);
  assert.equal(localStorage.getItem("feral-view"), "galerie");
  assert.ok(!document.querySelector('.sbgroup[data-group="lora"]').classList.contains("offview"));
  changed.stop();
});

test("Leer-Hinweis: typ: audio in der Galerie zeigt den Weg, schaltet aber nicht selbst", () => {
  const typ = (...v) => [{ kind: "typ", negated: false, values: v.map((value) => ({ value })) }];
  assert.equal(viewHint(typ("audio"), "galerie", true).goto, "audio");
  assert.equal(viewHint(typ("bild"), "audio", true).goto, "galerie");
  assert.equal(viewHint(typ("bild", "audio"), "galerie", true), null);   // teils drin
  assert.equal(viewHint(typ("audio"), "galerie", false), null);          // Modul aus
  assert.equal(viewHint([{ ...typ("audio")[0], negated: true }], "galerie", true), null);
});

test("Tipphilfe: Wort außerhalb des Grundbereichs bietet die Ansicht an, keinen Chip", () => {
  assert.equal(navSuggestion("audio", "galerie", true).nav, "audio");
  assert.equal(navSuggestion("image", "audio", true).nav, "galerie");
  assert.equal(navSuggestion("audio", "audio", true), null);
  assert.equal(navSuggestion("audio", "galerie", false), null);
  const keys = (v) => visibleCats(v).map((c) => c.key);
  assert.ok(keys("audio").includes("lyrics") && !keys("audio").includes("lora"));
  assert.ok(!keys("galerie").includes("lyrics") && keys("galerie").includes("typ"));
});


test("Medienart gilt innerhalb der Ansicht: nur unmögliche typ:-Werte fallen weg", () => {
  const typ = (neg, ...v) => ({ kind: "typ", negated: neg, values: v.map((value) => ({ value })) });
  const vals = (preds) => preds.map((p) => `${p.negated ? "-" : ""}${p.kind}:${(p.values || []).map((v) => v.value).join("|")}`);
  assert.deepEqual(vals(pruneForView([typ(false, "bild")], "audio")), []);
  // audio bleibt in der Galerie: dort stehen die fertigen Songs mit Cover.
  assert.equal(pruneForView([typ(false, "video", "audio")], "galerie"), null);
  assert.equal(pruneForView([typ(false, "audio")], "galerie"), null);
  assert.equal(pruneForView([typ(true, "audio")], "galerie"), null);
  assert.deepEqual(vals(pruneForView([typ(true, "audio")], "audio")), []);        // schlösse alles aus
  assert.equal(pruneForView([typ(true, "video")], "galerie"), null);               // sinnvoll: bleibt
  assert.equal(pruneForView([typ(false, "bild")], "galerie"), null);               // nichts zu tun
  assert.equal(pruneForView([{ kind: "tag", values: [{ value: "x" }] }], "audio"), null);
});
