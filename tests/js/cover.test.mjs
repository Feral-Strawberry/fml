// cover.test.mjs — Cover eines Songs (Audio A8, #165, ADR 0090): Galerie-
// Kachel zeigt das Vorschaubild des Coverbilds (kein Thumb-Auftrag für den
// Song), ♪ + Dauer und ▶; Leertaste spielt statt Lupe; das Detailpanel setzt
// und entfernt; der Auswahldialog sucht Bilder mit den Tags des Songs im
// Galerie-Grundbereich und hält Tasten bei sich.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, keydown, click, flush, item, hashOf, serveLibrary, itemDetail } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { emit, record } from "./bus.mjs";
import { DomEvent } from "./dom.mjs";

const { initGallery } = await import("../../src/feral/web/static/js/gallery.js");
const { initLoupe } = await import("../../src/feral/web/static/js/loupe.js");
const { initDetail } = await import("../../src/feral/web/static/js/detail.js");
const { initCoverDialog, startExpression } = await import("../../src/feral/web/static/js/coverdialog.js");

const IMG = hashOf(1), SONG = hashOf(2), TAKE = hashOf(3);
const img = item(1, { name: "regenzeit_cover_00001_.png" });
const song = item(2, { media_kind: "audio", container: "mp3", width: null, height: null,
                       duration: 200, name: "Regenzeit final.mp3", tool: "suno", cover: IMG });
const grid = () => document.getElementById("grid");
const panel = () => document.getElementById("panel");
const dlg = () => document.getElementById("coverdlg");

// Fake-<audio>: der DOM-Stub spielt nichts ab.
const played = [];
const origCreate = document.createElement.bind(document);
document.createElement = (tag) => {
  if (tag !== "audio") return origCreate(tag);
  const el = origCreate("div");
  Object.assign(el, {
    paused: true, currentTime: 0, duration: NaN, src: "",
    play() { this.paused = false; played.push(this.src); this.dispatchEvent(new DomEvent("play")); return Promise.resolve(); },
    pause() { this.paused = true; this.dispatchEvent(new DomEvent("pause")); },
  });
  return el;
};

let manual = { rating: null, tags: ["regenzeit"], notes: "", model: null, cover: IMG };

before(async () => {
  loadShell();
  serveLibrary([img, song]);
  const detail = (it) => ({
    ...itemDetail(it),
    manual: it.file_hash === SONG ? manual : itemDetail(it).manual,
    embedded_picture: it.file_hash === SONG,
    cover_item: it.file_hash === SONG && manual.cover
      ? { file_hash: IMG, container: "png", media_kind: "image" } : null,
  });
  mockApi.get(/^\/api\/item\/[0-9a-f]+$/, ({ path }) =>
    detail([img, song, { ...song, file_hash: TAKE }].find((x) => x.file_hash === path.split("/").pop())));
  mockApi.get("/api/tags", () => ({ tags: [] }));
  mockApi.get("/api/models", () => ({ models: [] }));
  mockApi.get(/^\/api\/audio\/analysis\//, () => mockApi.status(404, {}));
  mockApi.get(/^\/api\/item\/[0-9a-f]+\/comments$/, () => ({ comments: [] }));
  const text = (p) => `${p.kind}: ${p.values.map((v) => v.value).join(" | ")}`;
  mockApi.get("/api/filter/parse", ({ params }) => {
    const expr = params.get("expr");
    const preds = [...expr.matchAll(/(\w+): ([^:]+?)(?= \w+:|$)/g)].map((m) => ({
      kind: m[1], negated: false, values: m[2].split(" | ").map((v) => ({ value: v.replace(/"/g, "") })) }));
    return { expression: expr, predicates: preds, sort: null };
  });
  mockApi.post("/api/filter/build", ({ body }) => ({
    expression: body.predicates.map(text).join(" "), predicates: body.predicates, sort: null }));
  document.rectFor = (el) => (el.classList.contains("tile") ? { height: 200 } : null);
  document.getElementById("gridwrap").clientHeight = 1000;
  initGallery();
  initLoupe();
  initDetail();
  initCoverDialog();
  emit("search-state-changed", { predicates: [], expression: "" });
  await flush();
});

test("Kachel des finalisierten Songs: Coverbild, ♪ + Dauer, ▶ — kein Thumb-Auftrag für den Song", async () => {
  const tile = grid().querySelector(`.tile[data-hash="${SONG}"]`);
  assert.ok(tile, "Song steht in der Galerie");
  assert.ok(tile.querySelector("img"), "Vorschaubild statt ♪-Platzhalter allein");
  assert.equal(tile.querySelector(".badge").textContent, "♪ 3:20");
  assert.ok(tile.querySelector(".tplay"));
  await flush();
  assert.equal(mockApi.callsTo(`/api/thumb/${SONG}`).length, 0);
  assert.ok(mockApi.callsTo(`/api/thumb/${IMG}`).length >= 1);
});

test("▶ auf der Kachel und Leertaste spielen den Song, die Lupe bleibt zu", async () => {
  click(grid().querySelector(`.tile[data-hash="${SONG}"] .tplay`));
  await flush();
  assert.equal(played.length, 1);
  assert.ok(played[0].endsWith(`/api/preview/${SONG}`));
  emit("selection-changed", { hash: SONG, index: 1 });
  keydown(" ");
  await flush();
  assert.equal(document.getElementById("loupe").hidden, true);
});

test("Panel: Cover oben, Zeile Finalisiert direkt darunter, eingebettetes Bild unter Datei, Entfernen", async () => {
  emit("selection-changed", { hash: SONG, index: 1 });
  await flush();
  const sec = panel().querySelector("#pCover");
  assert.ok(sec.textContent.includes("Finalisiert"));
  const kids = [...panel().children];
  assert.ok(kids.indexOf(sec) === kids.indexOf(panel().querySelector(".ppreview")) + 1,
    "Cover-Zeile folgt direkt auf die Vorschau");
  assert.ok(panel().querySelector(".filerows .cvemb"), "eingebettetes Suno-Bild klein unter Datei");
  assert.ok(panel().querySelector(".ppreview .audiocover"), "Cover über dem Player");
  const changed = record("cover-changed");
  mockApi.on("DELETE", `/api/item/${SONG}/cover`, () => {
    manual = { ...manual, cover: null };
    return { manual };
  });
  click(sec.querySelector('[data-cover="remove"]'));
  await flush();
  assert.equal(changed.length, 1);
  assert.equal(changed[0].manual.cover, null);
  changed.stop();
  // Neu geladen: jetzt „Cover wählen …“.
  const again = panel().querySelector("#pCover");
  assert.ok(again.querySelector('.accentbtn[data-cover="pick"]'));
  assert.equal(panel().querySelector(".audiocover"), null);
});

test("Startausdruck: nur Bilder, Tags des Songs ODER-verknüpft", () => {
  assert.equal(startExpression([]), "typ: bild");
  assert.equal(startExpression(["regenzeit", 'a"b']), 'typ: bild tag: "regenzeit" | "ab"');
});

test("Dialog: sucht im Galerie-Grundbereich, setzt das gewählte Bild, Tasten bleiben drin", async () => {
  const picks = record("cover-pick");
  click(panel().querySelector('#pCover [data-cover="pick"]'));
  await flush();
  assert.deepEqual(picks[0].tags, ["regenzeit"]);
  picks.stop();
  assert.equal(dlg().hidden, false);
  const q = mockApi.callsTo("/api/items").at(-1).params;
  assert.equal(q.get("view"), "galerie");
  assert.equal(q.get("filter"), 'typ: bild tag: "regenzeit"');
  assert.equal(dlg().querySelectorAll(".cvchips .chip").length, 2);
  // Ziffern/Entf dürfen nicht zur Galerie durchschlagen (Bewerten/Ablehnen).
  const seen = [];
  const spy = (e) => seen.push(e.key);
  document.addEventListener("keydown", spy);
  keydown("Delete", { target: dlg().querySelector(".coverbox") });
  document.removeEventListener("keydown", spy);
  assert.deepEqual(seen, []);
  // Wählen + setzen.
  let posted = null;
  mockApi.post(`/api/item/${SONG}/cover`, ({ body }) => {
    posted = body;
    manual = { ...manual, cover: body.cover };
    return { manual };
  });
  const changed = record("cover-changed");
  assert.equal(dlg().querySelector(".cvok").disabled, true);
  click(dlg().querySelector(`.cvtile[data-hash="${IMG}"]`));
  assert.equal(dlg().querySelector(".cvok").disabled, false);
  click(dlg().querySelector(".cvok"));
  await flush();
  assert.deepEqual(posted, { cover: IMG });
  assert.equal(changed.length, 1);
  assert.equal(dlg().hidden, true);
  changed.stop();
});

test("Chip ✕ im Dialog baut den Ausdruck über /api/filter/build neu", async () => {
  emit("cover-pick", { hash: SONG, name: "Regenzeit final", tags: ["regenzeit"], cover: IMG });
  await flush();
  click(dlg().querySelectorAll(".cvchips .chipx")[1]);   // tag-Chip weg
  await flush();
  assert.equal(mockApi.callsTo("/api/items").at(-1).params.get("filter"), "typ: bild");
  keydown("Escape");
  assert.equal(dlg().hidden, true);
});

test("Dialog: ein nacktes Wort ist Text — live beim Tippen und als Chip mit Enter", async () => {
  emit("cover-pick", { hash: SONG, name: "Regenzeit final", tags: [], cover: null });
  await flush();
  const input = dlg().querySelector(".cvinput");
  input.value = "pyromania";
  input.dispatchEvent(new DomEvent("input", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 400));
  await flush();
  assert.equal(mockApi.callsTo("/api/items").at(-1).params.get("filter"), "typ: bild text: pyromania");
  keydown("Enter", { target: input });
  await flush();
  assert.equal(dlg().querySelector(".sderr").hidden, true, "kein Grammatikfehler");
  assert.equal(dlg().querySelectorAll(".cvchips .chip").length, 2);
  assert.equal(input.value, "");
  keydown("Escape");
});

test("Abspielleiste zeigt das Cover des laufenden Songs", async () => {
  const bar = document.getElementById("pbar");
  const img = bar.querySelector(".pcov img");
  assert.ok(img, "Miniatur links vom Titel");
  assert.equal(bar.querySelector(".pcov").dataset.cover, IMG);
});
