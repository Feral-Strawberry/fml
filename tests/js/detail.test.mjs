// detail.test.mjs — Detail-Panel: Fundorte in Reveal-Reihenfolge mit
// Herkunfts-Badge, der bevorzugte Fundort (den „Im Dateimanager anzeigen"
// öffnet) ist markiert, fehlende/fremde Dateien werden benannt (Issue #37,
// ADR-0062-Nachtrag). Dazu der Reveal-Knopf aus api.js: ⏳ während der
// Server prüft, 📁-Hinweis bei „nur Ordner", ⚠ bei Fehler.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, flush, item, serveLibrary } from "./harness.mjs";
import { DomEvent, Element } from "./dom.mjs";
import { mockApi } from "./apimock.mjs";
import { emit } from "./bus.mjs";

const { initDetail, breadcrumbHtml } = await import("../../src/feral/web/static/js/detail.js");
const { wireReveal } = await import("../../src/feral/web/static/js/api.js");

const panel = () => document.getElementById("panel");
const it = item(1);
const locations = [
  { path: "D:\\fml\\bestand\\2026\\09\\08\\bild.png", exists: true, usable: true, kind: "library", preferred: true },
  { path: "D:\\comfy\\output\\bild.png", exists: true, usable: true, kind: "watch", preferred: false },
  { path: "E:\\alt\\bild.png", exists: false, usable: false, kind: "extern", preferred: false },
  { path: "E:\\alt2\\bild.png", exists: true, usable: false, kind: "extern", preferred: false },
];

before(() => {
  loadShell();
  serveLibrary([it]);
  mockApi.get(/^\/api\/item\/[0-9a-f]+$/, () => ({
    ...it, locations, raw: [], interpreted: [],
    manual: { rating: null, tags: [], notes: "", model: null },
  }));
  mockApi.get("/api/tags", () => ({ tags: [] }));
  mockApi.get("/api/models", () => ({ models: [] }));
  initDetail();
});

test("Fundorte: Reihenfolge vom Server, Badge je Herkunft, 📂 am bevorzugten", async () => {
  emit("selection-changed", { hash: it.file_hash, index: 0 });
  await flush();
  const rows = panel().querySelectorAll(".locrowv");
  assert.equal(rows.length, 4);
  assert.deepEqual(rows.map((r) => r.classList.contains("preferred")), [true, false, false, false]);
  assert.ok(rows[0].textContent.includes("📂"), "bevorzugter Fundort trägt den Ordner-Marker");
  assert.ok(rows[0].getAttribute("title"), "Marker erklärt sich per Tooltip");
  assert.deepEqual(rows.map((r) => r.querySelector(".lockind").textContent.replace("📂 ", "")),
    ["Library", "Quelle", "extern", "extern"]);
  // Fehlende Datei und fremder Inhalt sind ehrlich benannt und gewarnt.
  assert.ok(rows[2].classList.contains("warn") && rows[2].textContent.includes("(fehlt)"));
  assert.ok(rows[3].classList.contains("warn") && rows[3].textContent.includes("andere Datei"));
  assert.ok(!rows[1].classList.contains("warn"));
  // Anzeigename kommt vom bevorzugten (ersten) Fundort.
  assert.equal(panel().querySelector(".pname").textContent, "bild.png");
  // Pfad bleibt als Text lesbar (Trenner wie gespeichert).
  assert.equal(rows[0].querySelector(".locpath").textContent, "D:\\fml\\bestand\\2026\\09\\08\\bild.png");
});

test("Breadcrumb: Ordner-Segmente öffnen genau diesen Ordner, Dateiname die Datei", () => {
  const html = breadcrumbHtml({ path: "D:\\fml\\out\\a b.png", exists: true, usable: true });
  const el = document.createElement("div"); el.innerHTML = html;
  const segs = el.querySelectorAll("a.seg");
  assert.deepEqual(segs.map((a) => [a.dataset.what, a.dataset.path]), [
    ["folder", "D:\\"],                 // Laufwerkswurzel mit Trenner (sonst „aktuelles Verzeichnis")
    ["folder", "D:\\fml"],
    ["folder", "D:\\fml\\out"],
    ["file", "D:\\fml\\out\\a b.png"],
  ]);
  assert.equal(el.textContent, "D:\\fml\\out\\a b.png");
  // POSIX + UNC: Leerpräfixe bleiben im Pfad, sind aber keine Segmente.
  const posix = document.createElement("div"); posix.innerHTML = breadcrumbHtml({ path: "/m/x/b.png", exists: true, usable: true });
  assert.deepEqual(posix.querySelectorAll("a.seg").map((a) => a.dataset.path), ["/m", "/m/x", "/m/x/b.png"]);
  assert.equal(posix.textContent, "/m/x/b.png");
  const unc = document.createElement("div"); unc.innerHTML = breadcrumbHtml({ path: "\\\\nas\\share\\b.png", exists: true, usable: true });
  assert.deepEqual(unc.querySelectorAll("a.seg").map((a) => a.dataset.path), ["\\\\nas", "\\\\nas\\share", "\\\\nas\\share\\b.png"]);
  assert.equal(unc.textContent, "\\\\nas\\share\\b.png");
  // Fehlende/fremde Datei: Ordner bleiben klickbar, der Dateiname nicht.
  const gone = document.createElement("div"); gone.innerHTML = breadcrumbHtml({ path: "/m/b.png", exists: false, usable: false });
  assert.deepEqual(gone.querySelectorAll("a.seg").map((a) => a.dataset.what), ["folder"]);
  assert.ok(gone.querySelector("span.seg.file"));
});

test("Breadcrumb-Klick ruft /open mit Pfad + Art; Fehler erscheint an der Zeile", async () => {
  emit("selection-changed", { hash: it.file_hash, index: 0 });
  await flush();
  const calls = [];
  mockApi.post(/^\/api\/item\/[0-9a-f]+\/open$/, ({ body }) => {
    calls.push(body);
    return body.what === "file" ? mockApi.status(404, { detail: { key: "errNoLocation" } }) : { opened: body.path, what: body.what };
  });
  const rows = panel().querySelectorAll(".locrowv");
  const folderSeg = rows[1].querySelectorAll("a.seg")[1];
  folderSeg.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  await flush();
  assert.deepEqual(calls, [{ path: "D:\\comfy", what: "folder" }]);
  assert.equal(mockApi.callsTo("/api/item")[mockApi.callsTo("/api/item").length - 1].path.endsWith("/open"), true);
  rows[1].querySelector("a.seg.file").dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  await flush();
  assert.equal(calls[1].what, "file");
  assert.ok(rows[1].querySelector(".locstate").textContent.includes("Kein Fundort mehr vorhanden."));
});

async function revealButton(handler) {
  const btn = document.createElement("button");
  btn.textContent = "📂"; btn.title = "idle";
  document.body.appendChild(btn);
  wireReveal(btn, () => it.file_hash);
  mockApi.post(/^\/api\/item\/[0-9a-f]+\/reveal$/, handler);
  return btn;
}

test("Reveal-Knopf: ⏳ solange der Server prüft, danach wieder 📂", async () => {
  const gate = mockApi.gate();
  const btn = await revealButton(async () => { await gate.promise; return { revealed: "x", verified: true, selected: true }; });
  btn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  await flush(1);
  assert.equal(btn.textContent, "⏳");
  gate.open();
  await flush();
  assert.equal(btn.textContent, "📂");
  assert.equal(btn.title, "idle");
});

test("Reveal-Knopf: nur Ordner geöffnet (Langpfad) ⇒ 📁 + Hinweis; Fehler ⇒ ⚠ + Meldung", async () => {
  const btn = await revealButton(() => ({ revealed: "x", verified: false, selected: false }));
  btn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  await flush();
  assert.equal(btn.textContent, "📁");
  assert.ok(btn.title.includes("Ordner"));

  const btn2 = await revealButton(() => mockApi.status(404, { detail: { key: "errNoLocation" } }));
  btn2.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  await flush();
  assert.equal(btn2.textContent, "⚠");
  assert.equal(btn2.title, "Kein Fundort mehr vorhanden.");
});

test("Video-Vorschau: in der Galerie ein <video>, bei offener Einzelansicht nur das Poster (#89)", async () => {
  const vid = item(2, { media_kind: "video", container: "webm" });
  mockApi.get(/^\/api\/item\/[0-9a-f]+$/, () => ({
    ...vid, locations: [locations[0]], raw: [], interpreted: [],
    manual: { rating: null, tags: [], notes: "", model: null },
  }));
  const single = document.getElementById("single");
  single.hidden = true;
  emit("selection-changed", { hash: vid.file_hash, index: 0 });
  await flush();
  assert.ok(panel().querySelector(".ppreview video"), "Galerie: Vorschau-Video");
  single.hidden = false;
  emit("selection-changed", { hash: vid.file_hash, index: 0 });
  await flush();
  assert.equal(panel().querySelector(".ppreview video"), null, "Einzelansicht: kein zweiter Stream");
  const poster = panel().querySelector(".ppreview img.pposter");
  assert.ok(poster, "Poster statt Video");
  assert.equal(poster.dataset.video, `/api/media/${vid.file_hash}`);
  single.hidden = true;
});

test("Panel-Wechsel gibt das Vorschau-Video frei — kein Zombie-Stream (#23, #89-Lehre)", async () => {
  const vid = item(3, { media_kind: "video", container: "webm" });
  const img = item(4);
  mockApi.get(/^\/api\/item\/[0-9a-f]+$/, ({ path }) => {
    const base = path.endsWith(vid.file_hash) ? vid : img;
    return { ...base, locations: [locations[0]], raw: [], interpreted: [],
             manual: { rating: null, tags: [], notes: "", model: null } };
  });
  document.getElementById("single").hidden = true;
  emit("selection-changed", { hash: vid.file_hash, index: 0 });
  await flush();
  const video = panel().querySelector(".ppreview video");
  assert.ok(video && video.getAttribute("src"), "Video mit Quelle im Panel");

  emit("selection-changed", { hash: img.file_hash, index: 1 });   // anderes Item: Panel wird neu gezeichnet
  await flush();
  assert.ok(panel().querySelector(".ppreview img"), "Bild im Panel");
  assert.equal(video.isConnected, false, "altes Video ist aus dem DOM");
  assert.equal(video.getAttribute("src"), null, "…und hat seine Quelle abgegeben (Verbindung frei)");

  emit("selection-changed", { hash: vid.file_hash, index: 0 });
  await flush();
  const again = panel().querySelector(".ppreview video");
  emit("selection-changed", { hash: null, index: null, hashes: [] });   // leere Auswahl
  await flush();
  assert.ok(panel().querySelector(".panelempty"));
  assert.equal(again.getAttribute("src"), null, "auch die leere Auswahl gibt frei");
});

test("Nicht dekodierbarer Codec (#71): Poster + Hinweis statt Player, Codec in der Kopfzeile", async () => {
  const vid = item(5, { media_kind: "video", container: "isobmff" });
  const interpreted = [
    { parser: "video", field: "video_codec", value: "prores" },
    { parser: "video", field: "video_profile", value: "HQ" },
    { parser: "video", field: "pixel_format", value: "yuv422p10le" },
  ];
  mockApi.get(/^\/api\/item\/[0-9a-f]+$/, () => ({
    ...vid, locations: [locations[0]], raw: [], interpreted,
    manual: { rating: null, tags: [], notes: "", model: null },
  }));
  document.getElementById("single").hidden = true;
  const asked = [];
  const original = Element.prototype.canPlayType;
  Element.prototype.canPlayType = function (type) { asked.push(type); return ""; };   // Chrome/Firefox: kein ProRes
  try {
    emit("selection-changed", { hash: vid.file_hash, index: 0 });
    await flush();
    assert.equal(panel().querySelector(".ppreview video"), null, "kein Player, kein Stream");
    const note = panel().querySelector(".ppreview .nopreview.codecnote");
    assert.ok(note, "Poster + Hinweis");
    assert.equal(note.querySelector("img").getAttribute("src"), `/api/thumb/${vid.file_hash}`);
    assert.match(note.textContent, /ProRes \(HQ, 10-bit\)/);
    const reveal = note.querySelector("button.codecreveal");
    assert.ok(reveal && reveal.dataset.wired === "1", "📂 im Hinweis ist ein echter, verdrahteter Reveal-Knopf");
    assert.match(reveal.textContent, /^📂 /);
    assert.ok(asked.some((t) => t.startsWith("video/quicktime")), "Browser wurde gefragt");
    assert.ok(asked.every((t) => t.includes("codecs=")), "nie ohne Codec-Angabe fragen (Firefox sagt zu nacktem video/quicktime »maybe«)");
    assert.match(panel().querySelector(".pmeta .vmono").textContent, /ProRes \(HQ, 10-bit\)/);
  } finally {
    Element.prototype.canPlayType = original;
  }

  // Safari (spielt ProRes): der Player wird gebaut.
  Element.prototype.canPlayType = () => "maybe";
  try {
    emit("selection-changed", { hash: vid.file_hash, index: 0 });
    await flush();
    assert.ok(panel().querySelector(".ppreview video"), "canPlayType »maybe« → Player");
  } finally {
    Element.prototype.canPlayType = original;
  }
});

test("Firefox-Pfad (#71): canPlayType »maybe«, aber Video ohne Bildspur → Poster + Hinweis statt Ton-Player", async () => {
  const vid = item(6, { media_kind: "video", container: "isobmff" });
  mockApi.get(/^\/api\/item\/[0-9a-f]+$/, () => ({
    ...vid, locations: [locations[0]], raw: [],
    interpreted: [{ parser: "video", field: "video_codec", value: "prores" }],
    manual: { rating: null, tags: [], notes: "", model: null },
  }));
  document.getElementById("single").hidden = true;
  emit("selection-changed", { hash: vid.file_hash, index: 0 });
  await flush();
  const video = panel().querySelector(".ppreview video");
  assert.ok(video, "Stub-Browser verspricht »maybe« → Player wird gebaut");
  video.videoWidth = 0;                                   // Metadaten da, aber keine Bildmaße
  video.dispatchEvent(new DomEvent("loadedmetadata"));
  await flush();
  assert.equal(panel().querySelector(".ppreview video"), null, "Ton-Player weg");
  assert.equal(video.getAttribute("src"), null, "…und Verbindung freigegeben");
  assert.match(panel().querySelector(".ppreview .nopreview").textContent, /kann ProRes nicht abspielen/);
  assert.ok(panel().querySelector(".ppreview .codecreveal[data-wired]"), "auch im Laufzeit-Netz mit 📂-Knopf");
});
