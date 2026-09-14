// rankings.test.mjs — Ranking-Arena (ADR 0045), Ausscheiden aus der Arena
// (Issue #87): „Beide raus" (↓) schreibt beide_verloren und verwirft ein
// vorgeholtes Paar, das einen der beiden enthält; erschöpfter Pool zeigt den
// Hinweis mit Zahlen und den Weg zur Bestenliste; die Bestenliste dimmt
// Ausgeschiedene am Ende, „Wieder rein" ruft den Endpunkt und bleibt am Index.

import { test, before } from "node:test";
import assert from "node:assert/strict";
import { loadShell, keydown, click, flush, item, serveLibrary } from "./harness.mjs";
import { emit, record } from "./bus.mjs";
import { mockApi } from "./apimock.mjs";

const { STRINGS } = await import("../../src/feral/web/static/js/strings.js");
const { initRankings } = await import("../../src/feral/web/static/js/rankings.js");

const root = () => document.getElementById("rankings");
const body = () => document.getElementById("rkBody");

const items = [item(1), item(2), item(3), item(4)];
const [h1, h2, h3, h4] = items.map((it) => it.file_hash);
const entry = (it, extra = {}) => ({ file_hash: it.file_hash, media_kind: "image", container: "png",
                                     score: 1000, duels: 0, eliminated: 0, ...extra });

let pairQueue = [];   // Antworten von /pair in Aufrufreihenfolge (letzte bleibt)
let board;            // Antwort von /leaderboard

before(() => {
  loadShell();
  serveLibrary(items);
  mockApi.get("/api/rankings/1/pair", () =>
    pairQueue.length > 1 ? pairQueue.shift() : pairQueue[0]);
  mockApi.post("/api/rankings/1/duel", ({ body: b }) => ({ scores: { [b.winner]: 984, [b.loser]: 984 } }));
  mockApi.post("/api/rankings/1/reinstate", ({ body: b }) => ({ reinstated: b.hash }));
  mockApi.get(/^\/api\/rankings\/1\/leaderboard/, () => board);
  mockApi.post(/^\/api\/item\/[0-9a-f]+\/rating$/, ({ body: b }) =>
    ({ manual: { rating: b.rating || null, tags: [], notes: "", model: null } }));
  initRankings();
});

const duelPosts = () => mockApi.calls.filter((c) => c.method === "POST" && c.path === "/api/rankings/1/duel");

async function openDuel() {
  keydown("Escape");
  await flush();
  mockApi.calls.length = 0;
  emit("arena-open", { id: 1, name: "Test", expression: "" });
  await flush();
  click(document.getElementById("rkSegDuel"));
  await flush();
}

test("↓ = Beide raus: beide_verloren wird gesendet, ein vorgeholtes Paar mit einem der beiden fällt weg", async () => {
  pairQueue = [
    { population: 4, eliminated: 0, pair: [entry(items[0]), entry(items[1])] },   // Start
    { population: 4, eliminated: 0, pair: [entry(items[0]), entry(items[2])] },   // vorgeholt, enthält h1
    { population: 4, eliminated: 2, pair: [entry(items[2]), entry(items[3])] },   // frisch nach dem Urteil
  ];
  await openDuel();
  assert.ok(body().innerHTML.includes(h1) && body().innerHTML.includes(h2));
  assert.equal(document.getElementById("rkBothLost").textContent, STRINGS.rankingBothLost);
  keydown("ArrowDown");
  await flush();
  const posts = duelPosts();
  assert.equal(posts.length, 1);
  assert.equal(posts[0].body.outcome, "beide_verloren");
  assert.deepEqual(new Set([posts[0].body.winner, posts[0].body.loser]), new Set([h1, h2]));
  // Nach dem Feedback kommt NICHT das vorgeholte Paar (h1 ist raus), sondern ein frisches.
  await new Promise((r) => setTimeout(r, 350));
  await flush();
  assert.ok(!body().innerHTML.includes(h1) && !body().innerHTML.includes(h2), body().innerHTML);
  assert.ok(body().innerHTML.includes(h3) && body().innerHTML.includes(h4), body().innerHTML);
  assert.ok(document.getElementById("rkPop").textContent.includes(STRINGS.rankingEliminated));
});

test("Pool erschöpft: Hinweis mit Zahlen statt Fehler, Knopf führt zur Bestenliste", async () => {
  pairQueue = [{ population: 4, eliminated: 3, pair: null }];
  board = { population: 4, total: 4, eliminated: 3, entries: [] };
  await openDuel();
  const text = body().textContent;
  assert.ok(text.includes("3") && text.includes("4"), text);
  assert.ok(text.includes(STRINGS.rankingPoolEmpty.split(":")[0]), text);
  assert.equal(duelPosts().length, 0);
  keydown("ArrowDown");   // kein Paar → kein Urteil
  await flush();
  assert.equal(duelPosts().length, 0);
  click(document.getElementById("rkToBoard"));
  await flush();
  assert.ok(document.getElementById("rkSegBoard").classList.contains("active"));
  assert.ok(mockApi.callsTo("/api/rankings/1/leaderboard").length >= 1);
});

test("Bestenliste: Ausgeschiedene gedimmt am Ende, Wieder-rein ruft den Endpunkt und bleibt am Index", async () => {
  board = {
    population: 4, total: 3, eliminated: 1,
    entries: [
      { rank: 1, ...entry(items[0], { score: 1016, duels: 1 }) },
      { rank: 2, ...entry(items[1], { score: 984, duels: 1 }) },
      { rank: 3, ...entry(items[2], { score: 984, duels: 1, eliminated: 1 }) },
    ],
  };
  keydown("Escape");
  await flush();
  mockApi.calls.length = 0;
  emit("arena-open", { id: 1, name: "Test", expression: "" });
  await flush();
  const rows = [...body().querySelectorAll(".rkbrow")];
  assert.equal(rows.length, 3);
  assert.deepEqual(rows.map((r) => r.classList.contains("rkout")), [false, false, true]);
  assert.equal(rows[2].querySelector(".rkbrank").textContent, STRINGS.rankingOutMarker);
  assert.equal(rows[0].querySelector(".rkbrank").textContent, "1");
  // Platz 1 „von 2": nur Aktive zählen.
  assert.ok(document.getElementById("rkbInfo").textContent.includes(`${STRINGS.rankingBoardOf} 2`));
  assert.equal(document.getElementById("rkbReinstate"), null);
  keydown("End");
  await flush();
  const info = document.getElementById("rkbInfo");
  assert.ok(info.textContent.includes(STRINGS.rankingOutInfo), info.textContent);
  // Nach „Wieder rein" liefert der Server h3 aktiv, dafür ist jetzt h2 ausgeschieden.
  board = {
    population: 4, total: 3, eliminated: 1,
    entries: [
      { rank: 1, ...entry(items[0], { score: 1016, duels: 1 }) },
      { rank: 2, ...entry(items[2], { score: 984, duels: 1 }) },
      { rank: 3, ...entry(items[1], { score: 984, duels: 1, eliminated: 1 }) },
    ],
  };
  click(document.getElementById("rkbReinstate"));
  await flush();
  const posts = mockApi.calls.filter((c) => c.method === "POST" && c.path === "/api/rankings/1/reinstate");
  assert.equal(posts.length, 1);
  assert.equal(posts[0].body.hash, h3);
  // Liste neu geladen, Index 2 bleibt: dort steht jetzt der nächste Ausgeschiedene (h2).
  assert.ok(body().querySelector('.rkbrow[data-index="2"]').classList.contains("active"));
  assert.ok(document.getElementById("rkbInfo").textContent.includes(STRINGS.rankingOutInfo));
  assert.ok(body().querySelector("#rkbStage img").getAttribute("src").includes(h2));
});

test("Videos im Duell: Thumbnail als Poster, vorgeholtes <video> wird wiederverwendet", async () => {
  // Befund: Bilder waren beim Wechsel im Cache, Videos begannen erst beim
  // Anzeigen zu laden — Karte leer, Video blitzte nach dem Urteil auf.
  const vid = { ...items[3], media_kind: "video", container: "webm" };
  pairQueue = [
    { population: 4, eliminated: 0, pair: [entry(items[0]), entry(items[1])] },
    { population: 4, eliminated: 0, pair: [entry(vid, { media_kind: "video", container: "webm" }), entry(items[2])] },
    { population: 4, eliminated: 0, pair: [entry(items[0]), entry(items[2])] },
  ];
  await openDuel();
  assert.equal(body().querySelector("video"), null);
  keydown("ArrowLeft");   // Sieg links → vorgeholtes Paar (mit Video) erscheint
  await new Promise((r) => setTimeout(r, 350));
  await flush();
  const video = body().querySelector(".rkcard video");
  assert.ok(video, body().innerHTML);
  assert.equal(video.getAttribute("poster"), `/api/thumb/${h4}`);
  assert.equal(video.getAttribute("preload"), "auto");
  assert.equal(video.getAttribute("src"), `/api/media/${h4}`);
  assert.equal(video.dataset.prefetched, "1");   // DASSELBE Element wie beim Vorholen
  assert.ok(video.hasAttribute("muted") && video.hasAttribute("autoplay"));
  assert.equal(video.parentNode?.classList.contains("rkmedia"), true);
  // Kopfzeile: primärer Fundort über dem Medium (Muster Vergleichsansicht).
  const heads = [...body().querySelectorAll(".rkcard .rkpath")].map((e) => e.textContent);
  assert.deepEqual(heads, [`/lib/2026/${h4.slice(0, 6)}.png`, `/lib/2026/${h3.slice(0, 6)}.png`]);
});

test("Verworfene Videos geben ihre Verbindung frei (src weg + load), im Duell und in der Bestenliste", async () => {
  // Log-Befund: 206-Antworten mit 600 s Laufzeit — verwaiste <video> hielten
  // Range-Verbindungen offen, neue Medien warteten (leere Flächen).
  const vid = { ...items[3], media_kind: "video", container: "webm" };
  pairQueue = [
    { population: 4, eliminated: 0, pair: [entry(vid, { media_kind: "video", container: "webm" }), entry(items[0])] },
    { population: 4, eliminated: 0, pair: [entry(items[1]), entry(items[2])] },
  ];
  await openDuel();
  const video = body().querySelector(".rkcard video");
  assert.ok(video && video.getAttribute("src"));
  keydown(" ");   // Überspringen → Karten werden ersetzt
  await flush();
  assert.equal(video.getAttribute("src"), null);
  assert.equal(video.getAttribute("poster"), null);
  assert.equal(body().querySelector(".rkcard video"), null);
  // Bestenliste: Rangwechsel gibt das Video des vorigen Rangs frei.
  board = {
    population: 4, total: 2, eliminated: 0,
    entries: [
      { rank: 1, ...entry(vid, { media_kind: "video", container: "webm", score: 1016, duels: 1 }) },
      { rank: 2, ...entry(items[0], { score: 984, duels: 1 }) },
    ],
  };
  keydown("Escape");
  await flush();
  emit("arena-open", { id: 1, name: "Test", expression: "" });
  await flush();
  const boardVideo = body().querySelector("#rkbStage video");
  assert.ok(boardVideo && boardVideo.getAttribute("src"));
  keydown("ArrowRight");
  await flush();
  assert.equal(boardVideo.getAttribute("src"), null);
  assert.ok(body().querySelector("#rkbStage img"));
});

test("Klick auf die Kopfzeile (Pfad) wertet NICHT, Klick aufs Medium schon", async () => {
  pairQueue = [{ population: 4, eliminated: 0, pair: [entry(items[0]), entry(items[1])] }];
  await openDuel();
  click(body().querySelector('.rkcard[data-side="0"] .rkpath'));
  click(body().querySelector('.rkcard[data-side="0"] .rkmeta'));
  await flush();
  assert.equal(duelPosts().length, 0);
  click(body().querySelector('.rkcard[data-side="0"] .rkmedia img'));
  await flush();
  assert.equal(duelPosts().length, 1);
  assert.equal(duelPosts()[0].body.winner, h1);
});

test("Kopfzeile: Bewertungspunkte setzen ein Rating, „raus“ nimmt nur dieses Bild und lädt das nächste Paar", async () => {
  pairQueue = [
    { population: 4, eliminated: 0, pair: [entry(items[0]), entry(items[1])] },
    { population: 4, eliminated: 0, pair: [entry(items[0]), entry(items[2])] },   // vorgeholt, enthält h1
    { population: 4, eliminated: 1, pair: [entry(items[2]), entry(items[3])] },
  ];
  await openDuel();
  // Bewertung: Klick auf den dritten Punkt der linken Karte → POST rating 3, Punkte nachgezogen.
  click(body().querySelector('.rkcard[data-side="0"] .rkrate .rdot[data-n="3"]'));
  await flush();
  const ratings = mockApi.calls.filter((c) => c.method === "POST" && c.path === `/api/item/${h1}/rating`);
  assert.equal(ratings.length, 1);
  assert.equal(ratings[0].body.rating, 3);
  assert.equal(body().querySelectorAll('.rkcard[data-side="0"] .rdot.on').length, 3);
  assert.equal(duelPosts().length, 0);   // keine Wertung durch den Klick
  // „raus" links (Variante 2): Duell mit Ausgang raus, Partner h2 gewinnt,
  // h1 verliert und ist raus; vorgeholtes Paar mit h1 verworfen.
  click(body().querySelector('.rkcard[data-side="0"] .rkout'));
  await flush();
  assert.equal(duelPosts().length, 1);
  assert.deepEqual(duelPosts()[0].body, { winner: h2, loser: h1, outcome: "raus" });
  assert.ok(body().querySelector('.rkcard[data-side="1"]').classList.contains("rkwin"));
  assert.ok(body().querySelector('.rkcard[data-side="0"] .rkscore').textContent.includes(STRINGS.rankingOutMarker));
  await new Promise((r) => setTimeout(r, 350));
  await flush();
  assert.ok(!body().innerHTML.includes(h1), body().innerHTML);
  assert.ok(body().innerHTML.includes(h3) && body().innerHTML.includes(h4));
});

test("Vorholen markiert die Paarung mit ?prefetch=1, das sichtbare Laden nicht (ADR-0072-Nachtrag)", async () => {
  pairQueue = [
    { population: 4, eliminated: 0, pair: [entry(items[0]), entry(items[1])] },   // sichtbar (loadPair)
    { population: 4, eliminated: 0, pair: [entry(items[2]), entry(items[3])] },   // vorgeholt
  ];
  await openDuel();
  const pairs = mockApi.calls.filter((c) => c.path === "/api/rankings/1/pair");
  assert.equal(pairs.length, 2);
  assert.equal(pairs[0].params.get("prefetch"), null);
  assert.equal(pairs[1].params.get("prefetch"), "1");
});

// -- ADR 0081 (#91): ✎ lädt die Population in die Galerie, 🏆-Dialog legt Neues an --

test("✎ schließt die Arena und lädt Name + Population als Kontext in die Suche", async () => {
  emit("arena-open", { id: 1, name: "Test", expression: "tag: x" });
  await flush();
  const loads = record("state-load");
  click(document.getElementById("rkEdit"));
  await flush();
  assert.equal(root().hidden, true);
  assert.deepEqual(loads.at(-1), { expression: "tag: x", label: "Test", arena: { id: 1, name: "Test" } });
  loads.stop();
});

test("Dialog Neue Arena: Chip-Vorschau ohne sort:, Trefferzahl, Anlegen öffnet die Arena", async () => {
  mockApi.post("/api/rankings", ({ body: b }) => ({ id: 9, ...b }));
  emit("arena-dialog-open", {
    expression: "tag: x sort: created",
    predicates: [
      { kind: "tag", negated: false, field: "", op: "=", values: [{ value: "x", exact: false }] },
      { kind: "sort", negated: false, field: "", op: "=", values: [{ value: "created", exact: false }] },
    ],
    total: 42,
  });
  await flush();
  const dlg = document.querySelector(".pickoverlay .rkdlg");
  assert.ok(dlg, "Dialog steht");
  assert.equal(dlg.querySelectorAll("#rkDlgChips .chip").length, 1, "sort: nicht in der Vorschau");
  assert.match(dlg.querySelector(".sdcount").textContent, /42/);
  assert.equal(dlg.querySelector("#rkDlgExpr").value, "tag: x");
  click(dlg.querySelector("#rkDlgGo"));
  await flush();
  assert.match(dlg.querySelector("#rkDlgMsg").textContent, /Name/, "ohne Namen kein Anlegen");
  dlg.querySelector("#rkDlgName").value = "Neu";
  click(dlg.querySelector("#rkDlgGo"));
  await flush();
  const posts = mockApi.calls.filter((c) => c.method === "POST" && c.path === "/api/rankings");
  assert.equal(posts.length, 1);
  assert.deepEqual(posts[0].body, { name: "Neu", expression: "tag: x" });
  assert.equal(document.querySelector(".pickoverlay .rkdlg"), null, "Dialog zu");
  assert.equal(root().hidden, false, "Arena offen");
  assert.equal(document.getElementById("rkTitle").textContent, "Neu");
  keydown("Escape");
  await flush();
});

test("Expertenfeld: Enter prüft über /api/filter/parse, Vorschau folgt, Trefferzahl entfällt", async () => {
  mockApi.get("/api/filter/parse", ({ params }) => params.get("expr") === "kaputt"
    ? mockApi.status(400, { detail: "unbekanntes Feld" })
    : ({ expression: "year: 2026", predicates: [
        { kind: "year", negated: false, field: "", op: "=", values: [{ value: "2026", exact: false }] }], sort: null }));
  emit("arena-dialog-open", { expression: "", predicates: [], total: 3 });
  await flush();
  const dlg = document.querySelector(".pickoverlay .rkdlg");
  assert.ok(dlg.querySelector("#rkDlgChips b"), "ohne Chips: ganze Bibliothek");
  const expr = dlg.querySelector("#rkDlgExpr");
  expr.value = "kaputt";
  keydown("Enter", { target: expr });
  await flush();
  assert.equal(dlg.querySelector("#rkDlgMsg").hidden, false, "Parserfehler sichtbar");
  expr.value = "year:2026";
  keydown("Enter", { target: expr });
  await flush();
  assert.equal(dlg.querySelector("#rkDlgMsg").hidden, true);
  assert.equal(dlg.querySelectorAll("#rkDlgChips .chip").length, 1);
  assert.equal(dlg.querySelector(".sdcount"), null, "Trefferzahl galt für den Galerie-Stand");
  assert.equal(expr.value, "year: 2026", "kanonisch zurückgeschrieben");
  click(dlg.querySelector("#rkDlgCancel"));
  await flush();
  assert.equal(document.querySelector(".pickoverlay .rkdlg"), null);
});
