// rankings.js — Ranking-Modul (Großbaustelle R, ADR 0045; UI-Nachbesserung
// R3/R3.2, 2026-07-16): Vollbild-Ansicht je Arena mit der Bestenliste als
// Standard — EINE große Ansicht (Medium links, mitscrollende Rangliste
// rechts, ←/→/↑/↓ blättern nach Rang) — und Duell-Modus (zwei Medien,
// Klick/Tastatur wertet, Überspringen); dazu der Dialog „Neue Arena" aus
// den Chips (ADR 0081: 🏆 in der Chip-Leiste legt NUR Neues an; Umbenennen
// und Population pflegt das Kontext-Segment im Breadcrumb, das ✎ hier lädt
// die Population dorthin). Löschen lebt im Admin (Ranking-Arenen) — das ✕
// hier SCHLIESST nur (X = Overlay zu, Konvention).
//
// Kommuniziert nur über den Bus (ADR 0015): die Sidebar öffnet Arenen per
// 'arena-open', die Chip-Leiste den Dialog per 'arena-dialog-open'; nach
// jeder Änderung am Arenen-Bestand feuert
// 'rankings-changed' (Sidebar lädt ihre Gruppe neu). Die Bestenliste springt
// per 'single-open' in die echte Einzelbildansicht (z-index 60 > Arena 50)
// für Prompt & Metadaten — Esc dort führt zurück in die Arena.
//
// Duelle sind die Rohwahrheit (ADR 0045): Sieg A/B schreibt einen
// Log-Eintrag + Elo-Update; Überspringen ruft NICHTS auf — das ehrliche
// „weiß nicht" erzeugt keine verfälschende Wertung. „Beide raus" (#87)
// nimmt beide dauerhaft aus dieser Arena; die Bestenliste zeigt sie
// gedimmt am Ende mit dem Rückweg „Wieder rein" (append-only, Elo bleibt).

import { STRINGS } from "./strings.js";
import {
  createRanking, parseFilter, getRankings,
  getRankingPair, recordDuel, recordBothLost, recordOut, reinstateRanking, getLeaderboard,
  getItem, mediaUrl, displayUrl, thumbUrl, loadThumb, releaseVideo, releaseVideos, wireMediaFallback,
  swapUnplayable } from "./api.js";
import { dotsHtml, rate } from "./curate.js";
import { emit, on } from "./main.js";
import { registerDialog } from "./overlays.js";
import { chipText } from "./search.js";
import { withoutSort } from "./context.js";

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const BOARD_PAGE = 100;

export function initRankings() {
  const root = document.getElementById("rankings");
  root.innerHTML = `
    <div class="lphead">
      <button type="button" id="rkBack">← ${STRINGS.rankingBack}</button>
      <span id="rkTitle"></span>
      <span id="rkPop" class="lpmeta"></span>
      <div class="lpspacer"></div>
      <div class="lpseg">
        <button type="button" id="rkSegBoard" class="active">${STRINGS.rankingSegBoard}</button>
        <button type="button" id="rkSegDuel">${STRINGS.rankingSegDuel}</button>
      </div>
      <button type="button" id="rkEdit" title="${STRINGS.rankingEdit}">✎</button>
      <button type="button" id="rkClose" title="${STRINGS.rankingClose}">✕</button>
    </div>
    <div class="rkbody" id="rkBody"></div>
    <div class="lpfoot" id="rkFoot"></div>`;

  const body = root.querySelector("#rkBody");
  const foot = root.querySelector("#rkFoot");
  const segDuel = root.querySelector("#rkSegDuel");
  const segBoard = root.querySelector("#rkSegBoard");

  let arena = null;      // {id, name, expression}
  let open = false;
  let mode = "board";    // Bestenliste ist die Standardansicht (R3, Feral Strawberry)
  let pair = null;       // aktuelles Paar (Reihenfolge = Anzeige links/rechts)
  let deciding = false;  // Klick-Sperre, während eine Wertung läuft
  let seq = 0;           // entwertet überholte Antworten (Muster loupe.js)

  // Arena-Kopf: Population, dazu die Zahl der Ausgeschiedenen (#87), wenn > 0.
  function setPop(n, out) {
    let text = n != null ? `${n.toLocaleString(STRINGS.locale)} ${STRINGS.rankingPopulation}` : "";
    if (n != null && out) text += ` · ${out.toLocaleString(STRINGS.locale)} ${STRINGS.rankingEliminated}`;
    root.querySelector("#rkPop").textContent = text;
  }

  // -- Duell-Modus ---------------------------------------------------------------
  //
  // Schwuppdizität (Feral Strawberry, 2026-07-13): Der Klick wartet auf NICHTS —
  // Elo-Feedback rechnet der Client selbst (identische Formel wie
  // db/rankings.py, rein kosmetisch: die Wahrheit bleibt das Duell-Log,
  // Replay überschreibt jede Abweichung), der POST läuft im Hintergrund
  // in Reihenfolge, und das nächste Paar ist beim Urteilen längst
  // vorgeholt (inkl. Bild-Preload) — der Wechsel ist damit sofort.

  const FEEDBACK_MS = 300;   // Sieger-Rahmen + Elo-Badge kurz sichtbar
  let nextPair = null;       // vorgeholtes {population, pair}
  let postChain = Promise.resolve();   // Duell-POSTs in Urteils-Reihenfolge

  // Videos im Duell (Feral Strawberrys Befund, #87-Beifang): Bilder waren
  // beim Wechsel schon im Cache, Videos begannen erst beim Anzeigen zu laden —
  // die Karte blieb leer, und das Video „blitzte" erst nach dem Urteil auf.
  // Zwei Griffe: (1) das Thumbnail als Poster, die Karte ist nie leer;
  // (2) beim Vorholen entsteht das <video preload="auto"> schon, und beim
  // Anzeigen wandert DASSELBE Element in die Karte — ein neues Element
  // würde den Puffer von vorn füllen.
  const warmVideos = new Map();   // hash → vorgeholtes <video>

  // Freigabe verworfener Videos: gemeinsamer Helfer in api.js (#89).
  function releaseWarm() {
    for (const v of warmVideos.values()) releaseVideo(v);
    warmVideos.clear();
  }

  function makeVideo(entry) {
    const v = document.createElement("video");
    v.setAttribute("src", mediaUrl(entry.file_hash));
    v.setAttribute("poster", thumbUrl(entry.file_hash));
    v.setAttribute("preload", "auto");
    v.setAttribute("muted", "");
    v.setAttribute("loop", "");
    v.setAttribute("playsinline", "");
    v.muted = true;   // Attribut allein reicht dem Autoplay-Regelwerk nicht immer
    return v;
  }

  function mediaEl(entry) {
    if (entry.media_kind !== "video") {
      const img = document.createElement("img");
      img.setAttribute("src", displayUrl(entry));
      img.setAttribute("alt", "");
      return img;
    }
    const v = warmVideos.get(entry.file_hash) || makeVideo(entry);
    warmVideos.delete(entry.file_hash);
    return v;
  }

  // Abspielen ERST, wenn das Element im DOM hängt UND abspielbereit ist
  // (Feral Strawberrys zweiter Befund, 5-Sekunden-Video blieb leer; in der
  // Sandbox nachgestellt): Zwei Fallen zugleich. (a) Ein beim Vorholen schon
  // komplett geladenes Video hat den Ladefortschritt hinter sich, an dem der
  // Browser das autoplay-Attribut auswertet — ein nachträglich gesetztes
  // Attribut bewirkt nichts, es braucht play(). (b) Bei einem frischen
  // Element ist der Ladealgorithmus nach src= erst EINGEPLANT; ein sofortiges
  // play() wird von ihm mit AbortError verworfen. Also: bereit → play()
  // sofort, sonst play() beim canplay-Ereignis; das autoplay-Attribut bleibt
  // als Sicherung für den Fall, dass der Browser beim Einhängen neu lädt.
  // Fehler ehrlich in der Karte nennen statt schwarzer Fläche; nicht
  // dekodierbare Codecs tauscht renderPair nach getItem gegen Poster +
  // Hinweis (#71 — die Paar-Einträge selbst tragen kein Codec-Wissen).
  function startVideo(v, card) {
    v.addEventListener("error", () => {
      const code = v.error?.code ?? "?";
      console.warn("Arena-Video-Fehler", v.getAttribute("src"), code);
      card.insertAdjacentHTML("beforeend",
        `<div class="rkvideoerr warn">${esc(STRINGS.rankingVideoError.replace("{code}", code))}</div>`);
    }, { once: true });
    const go = () => {
      const p = v.play?.();
      p?.catch?.((err) => console.warn("Arena-Video play() abgelehnt", v.getAttribute("src"), err?.name));
    };
    v.setAttribute("autoplay", "");
    if ((v.readyState ?? 0) >= 3) go();            // HAVE_FUTURE_DATA: vorgeholt, fertig
    else v.addEventListener("canplay", go, { once: true });
  }

  function renderPair(d) {
    pair = d.pair;
    deciding = false;
    setPop(d.population, d.eliminated);
    if (!pair) {
      // Pool erschöpft (#87): weniger als zwei Aktive. Hinweis mit Zahlen
      // statt stillem Wechsel — der Rückweg („Wieder rein") wohnt in der
      // Bestenliste, der Knopf führt hin.
      releaseVideos(body); body.innerHTML = `<div class="rkmsg vdim rkempty">${esc(STRINGS.rankingPoolEmpty
          .replace("{n}", d.eliminated.toLocaleString(STRINGS.locale))
          .replace("{m}", d.population.toLocaleString(STRINGS.locale)))}
        <button type="button" class="accentbtn" id="rkToBoard">${STRINGS.rankingPoolEmptyToBoard}</button></div>`;
      return;
    }
    // Kopfzeile je Karte mit primärem Fundort + Eckwerten (Muster
    // Vergleichsansicht; Feral Strawberrys Wunsch zum Eingrenzen leerer
    // Flächen): Pfad kommt asynchron über getItem, wie beim Dateinamen der
    // Bestenliste.
    const card = (side) => `
      <div class="rkcard" data-side="${side}">
        <div class="rkhead">
          <span class="rkpath vmono"></span><span class="lpmeta rkmeta"></span>
          <span class="ratedots rkrate" title="${esc(STRINGS.curateRateTitle)}"></span>
          <button type="button" class="rkout" title="${esc(STRINGS.rankingOutOneTitle)}">${STRINGS.rankingOutOne}</button>
        </div>
        <div class="rkmedia"></div>
        <div class="rkscore" hidden></div>
      </div>`;
    releaseVideos(body); body.innerHTML = `<div class="rkstage">${card(0)}<div class="rkvs">vs</div>${card(1)}</div>`;
    const shown = pair;
    detail = [null, null];
    for (const cardEl of body.querySelectorAll(".rkcard")) {
      const side = Number(cardEl.dataset.side);
      const entry = pair[side];
      const el = mediaEl(entry);
      cardEl.querySelector(".rkmedia").appendChild(el);
      if (el.tagName?.toLowerCase() === "video") startVideo(el, cardEl);
      getItem(entry.file_hash).then((d) => {
        if (pair !== shown) return;   // Paar inzwischen gewechselt
        detail[side] = d;
        swapUnplayable(cardEl.querySelector(".rkmedia"), d);   // #71
        const path = d.locations.length ? d.locations[0].path : STRINGS.rankingNoLocation;
        const pathEl = cardEl.querySelector(".rkpath");
        pathEl.textContent = path;
        pathEl.title = path;
        cardEl.querySelector(".rkmeta").textContent =
          `${d.width ? `${d.width}×${d.height} · ` : ""}${(d.container || "").toUpperCase()}`;
        cardEl.querySelector(".rkrate").innerHTML = dotsHtml(d.manual?.rating);
      }).catch(() => {});
    }
  }

  // Kopfzeile wie in der Vergleichsansicht (Feral Strawberrys Wunsch): wer über
  // einen Schatz stolpert, bewertet ihn gleich hier; wer ein Bild nie wieder
  // im Duell sehen will, nimmt es allein „raus" (statt Ablehnen — das wäre
  // „raus aus dem Katalog", ADR 0041).
  let detail = [null, null];   // Item-Details je Seite (Rating fürs Toggle)

  function rateSide(side, n) {
    const d = detail[side];
    if (!d) return;
    rate(d.file_hash, n !== 0 && n === d.manual?.rating ? 0 : n);
  }

  // „raus" (Variante 2, Feral Strawberry 2026-09-09): das Duell endet mit einem Sieg
  // des Partners, das andere Bild verliert und scheidet zusätzlich aus —
  // wie ein Klick auf den Sieger, nur dass der Verlierer nie wiederkommt.
  function outOne(side) {
    if (!pair || deciding || mode !== "duel") return;
    deciding = true;
    const gone = pair[side], winner = pair[1 - side];
    const gain = 32 * (1 - eloExpected(winner.score, gone.score));
    applyJudgement(
      { [winner.file_hash]: winner.score + gain, [gone.file_hash]: gone.score - gain },
      (entry) => entry === winner,
      () => recordOut(arena.id, winner.file_hash, gone.file_hash),
      (entry) => (entry === gone ? ` ${STRINGS.rankingOutMarker}` : ""),
    );
    if (nextPair?.pair?.some((e) => e.file_hash === gone.file_hash)) {
      nextPair = null;
      releaseWarm();
    }
  }

  // Nächstes Paar im Hintergrund holen; Bilder in den Browser-Cache wärmen
  // (Muster loupe.prefetchNeighbours — /api/media ist immutable-gecacht),
  // Videos als fertige Elemente puffern (s. o.).
  // Bewusst VOR der Wertung des laufenden Duells: die „Abdeckung"-Auswahl
  // hinkt dadurch ein Duell hinterher — statistisch egal, gefühlt sofort.
  async function prefetchPair() {
    const mySeq = seq;
    try {
      const d = await getRankingPair(arena.id, { prefetch: true });
      if (mySeq !== seq || !open) return;
      nextPair = d;
      releaseWarm();        // nur das aktuell vorgeholte Paar puffern
      for (const entry of d.pair || []) {
        if (entry.media_kind !== "video") { new Image().src = displayUrl(entry); continue; }
        const v = makeVideo(entry);
        v.dataset.prefetched = "1";
        warmVideos.set(entry.file_hash, v);
      }
    } catch { nextPair = null; }   // z. B. Population < 2 — loadPair meldet es
  }

  function showNextPair() {
    if (nextPair) {
      renderPair(nextPair);
      nextPair = null;
      prefetchPair();
    } else {
      loadPair();   // Vorgeholtes fehlt (Start/Fehler) — normal laden
    }
  }

  async function loadPair() {
    const mySeq = ++seq;
    nextPair = null;
    deciding = false;
    releaseVideos(body); body.innerHTML = `<div class="rkmsg vdim">${STRINGS.acLoading}</div>`;
    let d;
    try { d = await getRankingPair(arena.id); }
    catch (err) {
      if (mySeq === seq) { releaseVideos(body); body.innerHTML = `<div class="rkmsg warn">${esc(err.message)}</div>`; }
      return;
    }
    if (mySeq !== seq || !open || mode !== "duel") return;
    renderPair(d);
    prefetchPair();
  }

  function footError(message) {
    console.warn(message);
    const box = foot.querySelector("#rkErr");
    if (box) box.textContent = message;
  }

  // Optimistisches Elo (Start 1000, K=32 — Spiegel von db/rankings.py):
  // sofort anzeigen statt auf den Writer-Thread zu warten.
  const eloExpected = (a, b) => 1 / (1 + 10 ** ((b - a) / 400));

  // Gemeinsames Nachspiel jeder Wertung: Feedback sofort, vorgeholtes Paar
  // auffrischen, POST im Hintergrund, nach FEEDBACK_MS das nächste Paar.
  function applyJudgement(newScores, isWinner, post, suffix = () => "") {
    for (const card of body.querySelectorAll(".rkcard")) {
      const entry = pair[Number(card.dataset.side)];
      const won = isWinner(entry);
      card.classList.add(won ? "rkwin" : "rklose");
      const badge = card.querySelector(".rkscore");
      badge.hidden = false;
      badge.textContent = `${Math.round(newScores[entry.file_hash])} ${won ? "▲" : "▼"}${suffix(entry)}`;
    }
    // Das vorgeholte Paar kennt die Wertung noch nicht — Beteiligte auffrischen,
    // damit dessen Anzeige/Folge-Rechnung nicht auf altem Stand aufsetzt.
    if (nextPair) {
      for (const entry of nextPair.pair || []) {
        if (newScores[entry.file_hash] !== undefined) {
          entry.score = newScores[entry.file_hash];
          entry.duels += 1;
        }
      }
    }
    // POST im Hintergrund, in Urteils-Reihenfolge (Kette). Scheitert einer
    // (z. B. 503, weil der Writer gerade importiert), geht GENAU dieses
    // Urteil verloren — ehrlich in der Fußzeile melden statt still schlucken.
    postChain = postChain.then(post).catch((err) => footError(err.message));
    setTimeout(() => { if (open && mode === "duel") showNextPair(); }, FEEDBACK_MS);
  }

  function decide(side) {
    if (!pair || deciding || mode !== "duel") return;
    deciding = true;
    const winner = pair[side], loser = pair[1 - side];
    const gain = 32 * (1 - eloExpected(winner.score, loser.score));
    applyJudgement(
      { [winner.file_hash]: winner.score + gain, [loser.file_hash]: loser.score - gain },
      (entry) => entry === winner,
      () => recordDuel(arena.id, winner.file_hash, loser.file_hash),
    );
  }

  // „Beide raus" (#87, ADR-0045-Nachtrag): beide bekommen ein Duell,
  // verlieren gegen den virtuellen Durchschnittsgegner UND scheiden aus
  // dieser Arena aus — sie kommen in keinem Paar mehr vor.
  function bothLost() {
    if (!pair || deciding || mode !== "duel") return;
    deciding = true;
    const [a, b] = pair;
    applyJudgement(
      {
        [a.file_hash]: a.score - 32 * eloExpected(a.score, 1000),
        [b.file_hash]: b.score - 32 * eloExpected(b.score, 1000),
      },
      () => false,
      () => recordBothLost(arena.id, a.file_hash, b.file_hash),
    );
    // Das vorgeholte Paar wurde VOR diesem Urteil gebildet und kann einen
    // der beiden enthalten — dann verwerfen, sonst zeigte das nächste Duell
    // ein gerade ausgeschiedenes Item. showNextPair lädt dann frisch.
    if (nextPair?.pair?.some((e) => e.file_hash === a.file_hash || e.file_hash === b.file_hash)) {
      nextPair = null;
      releaseWarm();
    }
  }

  function skip() {
    if (mode !== "duel" || deciding) return;
    showNextPair();   // kein Log-Eintrag (ADR 0045) — sofort das nächste Paar
  }

  // -- Bestenliste: EINE Ansicht (R3.2, Feral Strawberry 2026-07-16) ----------------------------
  //
  // Liste und Durchsehen waren zwei Paradigmen übereinander („nicht aus
  // einem Guss") — jetzt IST die Bestenliste die große Ansicht: links das
  // Medium des aktuellen Rangs, rechts die Rangliste als mitscrollende
  // Spalte (bei Platz 55 ist die Umgebung ~50–60 sichtbar). ←/→ und ↑/↓
  // blättern nach Rang, Klick in die Spalte springt, die Spalte lädt beim
  // Scrollen seitenweise nach. Enter/Knopf öffnet die echte
  // Einzelbildansicht (Prompt & Metadaten), Esc schließt die Arena —
  // keine Zwischenebene mehr.

  let board = null;               // {current, entry} — aktueller Rang (0-basiert)
  let boardTotal = 0;             // Gesamtzahl der Platzierungen
  let rowsLoaded = 0;             // bereits gerenderte Rang-Zeilen
  let loadingRows = false;
  const boardCache = new Map();   // Rang-Index (0-basiert) → Eintrag

  async function fetchBoardPage(start) {
    const d = await getLeaderboard(arena.id, BOARD_PAGE, start);
    boardTotal = d.total;
    d.entries.forEach((entry, k) => boardCache.set(start + k, entry));
    return d;
  }

  // Rang-Zeilen anhängen. Thumbnails erst beim Sichtbarwerden über die
  // gedrosselte Warteschlange (ADR 0020) laden — ein Ende-Sprung hängt
  // sonst tausende Zeilen an und würde für jede sofort ein Thumbnail
  // anfordern (unsichtbare inklusive).
  let thumbWatcher = null;
  function appendRows(entries, start) {
    const list = body.querySelector("#rkbList");
    if (!list) return;
    // Ausgeschiedene (#87) stehen geschlossen am Ende: gedimmt, statt der
    // Rangzahl der Marker.
    list.insertAdjacentHTML("beforeend", entries.map((e, k) => `
      <div class="rkbrow${e.eliminated ? " rkout" : ""}" data-index="${start + k}">
        <span class="rkbrank">${e.eliminated ? STRINGS.rankingOutMarker : e.rank}</span>
        <span class="rkbthumb">${e.media_kind === "video" ? `<span class="rkbadge">${STRINGS.badgeVideo}</span>` : ""}</span>
        <span class="rkbelo" title="${e.duels} ${STRINGS.rankingDuels}">${Math.round(e.score)}</span>
      </div>`).join(""));
    if (!thumbWatcher) {
      thumbWatcher = new IntersectionObserver((hits) => {
        for (const hit of hits) {
          if (!hit.isIntersecting) continue;
          thumbWatcher.unobserve(hit.target);
          const box = hit.target.querySelector(".rkbthumb");
          if (box.querySelector("img")) continue;
          const img = document.createElement("img");
          box.prepend(img);
          loadThumb(img, boardCache.get(Number(hit.target.dataset.index)).file_hash);
        }
      }, { root: list, rootMargin: "200px" });
    }
    for (const row of [...list.querySelectorAll(".rkbrow")].slice(start)) thumbWatcher.observe(row);
    rowsLoaded = start + entries.length;
  }

  // Zeilen bis Rang-Index i nachladen (Scroll = nächstes Häppchen,
  // Ende-Sprung = Schleife bis zum Ziel; 500 = Server-Limit je Anfrage).
  async function loadRowsThrough(i) {
    if (loadingRows) return;
    loadingRows = true;
    const mySeq = seq;
    try {
      while (mySeq === seq && open && mode === "board"
             && rowsLoaded <= i && (!boardTotal || rowsLoaded < boardTotal)) {
        const d = await getLeaderboard(arena.id, 500, rowsLoaded);
        boardTotal = d.total;
        if (!d.entries.length) break;
        d.entries.forEach((entry, k) => boardCache.set(rowsLoaded + k, entry));
        appendRows(d.entries, rowsLoaded);
      }
    } catch (err) { console.warn(err); }
    loadingRows = false;
  }

  let boardOut = 0;               // Zahl der Ausgeschiedenen in der Liste (#87)

  // `startIndex`: Rang-Index, der nach dem Laden gezeigt wird (0 = Spitze).
  // Nach „Wieder rein" bleibt der Index stehen — das reinstatete Item rückt
  // nach vorn, an seiner Stelle steht der nächste Ausgeschiedene.
  async function loadBoard(startIndex = 0) {
    const mySeq = ++seq;
    board = null;
    boardCache.clear();   // Scores können sich seit dem letzten Mal bewegt haben
    boardTotal = 0;
    rowsLoaded = 0;
    loadingRows = false;
    thumbWatcher?.disconnect();   // beobachtete Zeilen fliegen gleich aus dem DOM
    thumbWatcher = null;
    releaseVideos(body); body.innerHTML = `<div class="rkmsg vdim">${STRINGS.acLoading}</div>`;
    let d;
    try { d = await fetchBoardPage(0); }
    catch (err) {
      if (mySeq === seq) { releaseVideos(body); body.innerHTML = `<div class="rkmsg warn">${esc(err.message)}</div>`; }
      return;
    }
    if (mySeq !== seq || !open || mode !== "board") return;
    boardOut = d.eliminated || 0;
    setPop(d.population, boardOut);
    if (!d.total) {
      // Nur einmal leer (R3): der Weg zum ersten Duell steht direkt daneben.
      releaseVideos(body); body.innerHTML = `<div class="rkmsg vdim rkempty">${STRINGS.rankingBoardEmpty}
        <button type="button" class="accentbtn" id="rkStartDuel">${STRINGS.rankingBoardStart}</button></div>`;
      return;
    }
    releaseVideos(body); body.innerHTML = `
      <div class="lpnav" id="rkbPrev" title="←"><span>‹</span></div>
      <div class="rkbmain">
        <div class="rkbstage" id="rkbStage"></div>
        <div class="rkbinfo" id="rkbInfo"></div>
      </div>
      <div class="lpnav" id="rkbNext" title="→"><span>›</span></div>
      <aside class="rkblist" id="rkbList"></aside>`;
    appendRows(d.entries, 0);
    // Spalte lädt beim Scrollen seitenweise nach (kein „Mehr laden"-Knopf).
    body.querySelector("#rkbList").addEventListener("scroll", (e) => {
      const el = e.target;
      if (el.scrollTop + el.clientHeight > el.scrollHeight - 300) loadRowsThrough(rowsLoaded);
    });
    showRank(Math.min(startIndex, d.total - 1));
  }

  async function showRank(i) {
    if (i < 0 || (boardTotal && i >= boardTotal)) return;
    if (!boardCache.has(i)) {
      // ←/→ holt das nächste Häppchen, Ende springt in einer Schleife hin.
      await loadRowsThrough(i);
      if (!boardCache.has(i)) return;
    }
    if (!open || mode !== "board") return;
    const entry = boardCache.get(i);
    board = { current: i, entry };
    releaseVideos(body.querySelector("#rkbStage"));
    body.querySelector("#rkbStage").innerHTML = entry.media_kind === "video"
      ? `<video src="${mediaUrl(entry.file_hash)}" poster="${thumbUrl(entry.file_hash)}" controls autoplay loop playsinline></video>`
      : `<img src="${displayUrl(entry)}" alt="">`;
    wireMediaFallback(body.querySelector("#rkbStage"), STRINGS.noPreview);   // Hinweis statt schwarzem Player (#25)
    // Ausgeschiedene (#87) haben keinen Platz, sondern den Marker und den
    // Rückweg „Wieder rein"; „von m" zählt nur die Aktiven.
    const head = entry.eliminated
      ? `<b class="rkoutlabel">${STRINGS.rankingOutInfo}</b>
         <button type="button" id="rkbReinstate" title="${esc(STRINGS.rankingReinstateTitle)}">${STRINGS.rankingReinstate}</button>`
      : `<b>${STRINGS.rankingRank} ${(i + 1).toLocaleString(STRINGS.locale)}</b>
         <span class="vdim">${STRINGS.rankingBoardOf} ${(boardTotal - boardOut).toLocaleString(STRINGS.locale)}</span>`;
    body.querySelector("#rkbInfo").innerHTML =
      `${head}
       · ${Math.round(entry.score)} ${STRINGS.rankingScore}
       · ${entry.duels} ${STRINGS.rankingDuels}
       <span class="vmono vdim" id="rkbName"></span>`;
    // Dateiname asynchron nachtragen (Muster Lupe: getItem liefert Fundorte).
    getItem(entry.file_hash).then((d) => {
      const nameEl = body.querySelector("#rkbName");
      if (nameEl && board?.entry === entry) {
        nameEl.textContent = d.locations.length
          ? d.locations[0].path.split("/").pop().split("\\").pop() : "";
        swapUnplayable(body.querySelector("#rkbStage"), d);   // #71
      }
    }).catch(() => {});
    // Markierung nachziehen; die Spalte scrollt mit (Umgebung bleibt sichtbar).
    for (const active of body.querySelectorAll(".rkbrow.active")) active.classList.remove("active");
    const row = body.querySelector(`.rkbrow[data-index="${i}"]`);
    if (row) { row.classList.add("active"); row.scrollIntoView({ block: "center" }); }
    // Rang-Nachbarn vorholen (Bilder in den Browser-Cache wärmen).
    for (const delta of [1, -1]) {
      const n = boardCache.get(i + delta);
      if (n && n.media_kind !== "video") new Image().src = displayUrl(n);
    }
  }

  const boardNav = (delta) => { if (board) showRank(board.current + delta); };

  // „Wieder rein" (#87): append-only Log-Zeile, dann die Liste neu laden
  // und am selben Index bleiben (dort steht jetzt der nächste Ausgeschiedene).
  async function reinstate() {
    if (!board?.entry.eliminated) return;
    const { current, entry } = board;
    try {
      await reinstateRanking(arena.id, entry.file_hash);
    } catch (err) { body.querySelector("#rkbInfo")?.insertAdjacentHTML("beforeend", ` <span class="warn">${esc(err.message)}</span>`); return; }
    if (open && mode === "board") loadBoard(current);
  }

  // -- Ansicht öffnen/schließen/umschalten -----------------------------------------

  function renderMode() {
    segDuel.classList.toggle("active", mode === "duel");
    segBoard.classList.toggle("active", mode === "board");
    foot.innerHTML = mode === "duel"
      ? `<button type="button" id="rkBothLost" title="${esc(STRINGS.rankingBothLostTitle)}">${STRINGS.rankingBothLost}</button>
         <button type="button" id="rkSkip" title="${esc(STRINGS.rankingSkipTitle)}">${STRINGS.rankingSkip}</button>
         <div class="vdim">${STRINGS.rankingDuelHint}</div>
         <span id="rkErr" class="warn"></span>`
      : `<button type="button" id="rkbSingle">${STRINGS.rankingBrowseSingle}</button>
         <div class="vdim">${STRINGS.rankingBoardHint}</div>`;
    mode === "duel" ? loadPair() : loadBoard();
  }

  function openArena(a, wantedMode) {
    arena = { id: a.id, name: a.name, expression: a.expression || "" };
    open = true;
    mode = wantedMode || "board";   // Bestenliste zuerst (R3) — Duell auf Wunsch
    root.hidden = false;
    emit("view-changed", { view: "rankings", open: true });
    root.querySelector("#rkTitle").textContent = arena.name;
    setPop(null);
    renderMode();
  }

  function close() {
    if (!open) return;
    open = false;
    board = null;
    releaseWarm();       // vorgeholte Videos nicht über das Schließen hinaus halten
    seq++;               // laufende Antworten entwerten
    deciding = false;    // Klick-Sperre nie über das Schließen hinaus (ADR 0069)
    root.hidden = true;
    releaseVideos(body); body.innerHTML = ""; // stoppt laufende Videos
    emit("view-changed", { view: "rankings", open: false });
    emit("rankings-changed", {});   // Sidebar: Duell-/Populationszähler nachziehen
  }

  // -- Neue Arena aus den Chips (ADR 0081) ----------------------------------------------
  //
  // Aufbau wie der Speicherdialog: Chip-Vorschau (ohne sort:, die Arena hat
  // ihre eigene Ordnung), Trefferzahl, Name. Dazu das aufklappbare
  // Expertenfeld „Ausdruck selbst tippen": Enter/Verlassen schickt den Text
  // durch /api/filter/parse (EIN Parser, ADR 0035), die Vorschau folgt; die
  // Trefferzahl entfällt dann, sie galt für den Galerie-Stand. Ohne Chips
  // und mit leerem Feld: ganze Bibliothek.

  const chipsHtml = (predicates) =>
    predicates.map((p) => `
      <span class="chip${p.negated ? " neg" : ""}">
        ${p.negated ? `<span class="chipneg">${STRINGS.chipNegated}</span>` : ""}
        <span class="chiptext">${esc(chipText(p))}</span>
      </span>`).join("") || `<b>${esc(STRINGS.allMedia)}</b>`;

  function openCreateDialog(d) {
    const noSort = (preds) => (preds || []).filter((p) => p.kind !== "sort");
    let expression = withoutSort(d.expression || "");
    let total = d.total ?? null;
    const overlay = document.createElement("div");
    overlay.className = "pickoverlay";
    overlay.innerHTML = `
      <div class="pickbox savebox rkdlg">
        <div class="pickhead"><b>${esc(STRINGS.arenaDlgTitle)}</b></div>
        <div class="sdchips" id="rkDlgChips"></div>
        <input type="text" class="sdname" id="rkDlgName" placeholder="${esc(STRINGS.arenaDlgNamePlaceholder)}">
        <details class="rkexpert">
          <summary>${esc(STRINGS.arenaDlgExpert)}</summary>
          <input type="text" class="sdname" id="rkDlgExpr" value="${esc(expression)}" placeholder="${esc(STRINGS.arenaDlgExprPlaceholder)}">
          <div class="sdhint">${esc(STRINGS.arenaDlgExprHint)}</div>
        </details>
        <span class="sderr" id="rkDlgMsg" hidden></span>
        <div class="sdactions">
          <button type="button" class="sdprimary" id="rkDlgGo">${esc(STRINGS.arenaDlgCreate)}</button>
          <button type="button" id="rkDlgCancel">${esc(STRINGS.arenaDlgCancel)}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    const nameInput = overlay.querySelector("#rkDlgName");
    const exprInput = overlay.querySelector("#rkDlgExpr");
    const msg = overlay.querySelector("#rkDlgMsg");
    const unregister = registerDialog(overlay, () => closeDlg());
    const closeDlg = () => { unregister(); overlay.remove(); };
    const showMsg = (text) => { msg.textContent = `⚠ ${text}`; msg.hidden = false; };
    const hideMsg = () => { msg.hidden = true; };

    function renderPreview(predicates) {
      overlay.querySelector("#rkDlgChips").innerHTML = chipsHtml(predicates)
        + (total == null ? ""
           : `<span class="sdcount">· ${total.toLocaleString(STRINGS.locale)} ${esc(STRINGS.saveDlgHits)}</span>`);
    }
    renderPreview(noSort(d.predicates));

    async function applyExpr() {
      const raw = exprInput.value.trim();
      if (raw === expression) return;
      try {
        const parsed = raw ? await parseFilter(raw) : { expression: "", predicates: [] };
        expression = withoutSort(parsed.expression);
        total = null;
        exprInput.value = expression;
        hideMsg();
        renderPreview(noSort(parsed.predicates));
      } catch (err) { showMsg(err.message); }
    }

    async function submit() {
      const name = nameInput.value.trim();
      if (!name) return void showMsg(STRINGS.arenaDlgNoName);
      try {
        const r = await createRanking(name, expression);
        closeDlg();
        emit("rankings-changed", {});
        openArena({ id: r.id, name, expression });
      } catch (err) { showMsg(err.message); }
    }
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay || e.target.closest("#rkDlgCancel")) return closeDlg();
      if (e.target.closest("#rkDlgGo")) submit();
    });
    overlay.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      if (e.target === exprInput) { e.preventDefault(); applyExpr(); }
      else if (e.target === nameInput) submit();
    });
    exprInput.addEventListener("change", applyExpr);
    nameInput.focus();
  }

  // -- Verdrahtung --------------------------------------------------------------------

  root.querySelector("#rkBack").addEventListener("click", close);
  root.querySelector("#rkClose").addEventListener("click", close);
  segDuel.addEventListener("click", () => { if (mode !== "duel") { mode = "duel"; renderMode(); } });
  segBoard.addEventListener("click", () => { if (mode !== "board") { mode = "board"; renderMode(); } });
  // ✎ = Name und Population in der Galerie bearbeiten (ADR 0081): die
  // Population wird als Chips geladen, das Kontext-Segment zeigt „🏆 Name";
  // Speichern/✕ dort führen zurück hierher ('arena-open').
  root.querySelector("#rkEdit").addEventListener("click", () => {
    const a = arena;
    close();
    emit("state-load", { expression: a.expression, label: a.name, arena: { id: a.id, name: a.name } });
  });

  body.addEventListener("click", (e) => {
    // Kopfzeile (Pfad/Eckwerte/Bewertung/raus) ist KEINE Wertungsfläche: wer
    // den Pfad markiert oder kopiert, darf kein Duell auslösen (Feral
    // Strawberrys Befund); Punkte bewerten, „raus" nimmt das eine Item.
    const head = e.target.closest(".rkhead");
    if (head) {
      const side = Number(head.closest(".rkcard").dataset.side);
      const dot = e.target.closest(".rdot");
      if (dot) rateSide(side, parseInt(dot.dataset.n, 10));
      else if (e.target.closest(".rkout")) outOne(side);
      return;
    }
    const card = e.target.closest(".rkcard");
    if (card) return void decide(Number(card.dataset.side));
    if (e.target.closest("#rkbPrev")) return void boardNav(-1);
    if (e.target.closest("#rkbNext")) return void boardNav(1);
    if (e.target.closest("#rkStartDuel")) { mode = "duel"; renderMode(); return; }
    if (e.target.closest("#rkToBoard")) { mode = "board"; renderMode(); return; }
    if (e.target.closest("#rkbReinstate")) return void reinstate();
    const row = e.target.closest(".rkbrow");
    if (row) showRank(Number(row.dataset.index));
  });
  foot.addEventListener("click", (e) => {
    if (e.target.closest("#rkSkip")) skip();
    else if (e.target.closest("#rkBothLost")) bothLost();
    else if (e.target.closest("#rkbSingle") && board) {
      emit("single-open", { hash: board.entry.file_hash });
    }
  });

  // CAPTURE-Phase (Muster curate.js): In der Bubble-Phase schließt die Lupe
  // ihr Esc ZUERST — dieser Handler sähe sie schon zu und schlösse die Arena
  // gleich mit. In der Capture-Phase ist die Ebenen-Lage noch unverfälscht.
  document.addEventListener("keydown", (e) => {
    if (!open || root.hidden) return;
    // Lupe, Einzelbildansicht und Dialoge liegen ÜBER der Arena — deren
    // Tasten gewinnen. Achtung: Reject-/Sammel-/Speicherdialog halten
    // dauerhaft VERSTECKTE .pickoverlay-Elemente im DOM — nur sichtbare
    // zählen (Muster search.js).
    if (!document.getElementById("loupe").hidden) return;
    if (!document.getElementById("single").hidden) return;
    if (document.querySelector(".pickoverlay:not([hidden])")) return;
    if (e.target instanceof Element && e.target.matches("input, textarea, select")) return;
    if (e.key === "Escape") { close(); return; }
    if (mode === "board") {
      if (!board) return;
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); boardNav(-1); }
      else if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); boardNav(1); }
      else if (e.key === "Home") { e.preventDefault(); showRank(0); }
      else if (e.key === "End") { e.preventDefault(); showRank(boardTotal - 1); }
      else if (e.key === "Enter") {
        // stopPropagation: singleview hat einen eigenen Galerie-Enter —
        // der würde sonst das GALERIE-Item statt des Rang-Items öffnen.
        e.preventDefault(); e.stopPropagation();
        emit("single-open", { hash: board.entry.file_hash });
      }
      return;
    }
    if (e.key === "ArrowLeft") { e.preventDefault(); decide(0); }
    else if (e.key === "ArrowRight") { e.preventDefault(); decide(1); }
    else if (e.key === "ArrowDown") { e.preventDefault(); bothLost(); }
    else if (e.key === " ") { e.preventDefault(); skip(); }
  }, true);

  // Bewertung aus Panel/Lupe/hier: Punkte der betroffenen Karte nachziehen.
  on("annotation-changed", (d) => {
    if (!open || mode !== "duel" || !pair) return;
    const side = pair.findIndex((e) => e.file_hash === d.hash);
    if (side < 0 || !detail[side]) return;
    detail[side].manual = d.manual;
    const dots = body.querySelector(`.rkcard[data-side="${side}"] .rkrate`);
    if (dots) dots.innerHTML = dotsHtml(d.manual.rating);
  });

  on("arena-open", (d) => openArena(d));
  on("arena-dialog-open", (d) => openCreateDialog(d));

  // Sprung aus dem Admin (Rankings → „Bearbeiten" je Zeile, #133): das
  // Ranking wie per ✎ in den Bearbeiten-Modus der Galerie laden. Der
  // Parameter verschwindet aus der Adresszeile (Reload lädt nicht erneut).
  const wanted = parseInt(new URLSearchParams(location.search || "").get("ranking") || "", 10);
  if (wanted) {
    history.replaceState(null, "", location.pathname);
    getRankings({ counts: false }).then((d) => {
      const a = d.rankings.find((r) => r.id === wanted);
      if (a) emit("state-load", { expression: a.expression || "", label: a.name, arena: { id: a.id, name: a.name } });
    }).catch((err) => console.warn(err));
  }
}
