// rankings.js — Ranking-Modul (Großbaustelle R, ADR 0045; UI-Nachbesserung
// R3/R3.2, 2026-07-16): Vollbild-Ansicht je Arena mit der Bestenliste als
// Standard — EINE große Ansicht (Medium links, mitscrollende Rangliste
// rechts, ←/→/↑/↓ blättern nach Rang) — und Duell-Modus (zwei Medien,
// Klick/Tastatur wertet, Überspringen); dazu der Arena-Dialog (anlegen/
// bearbeiten). Löschen lebt im Admin (Wartung → Ranking-Arenen) — das ✕
// hier SCHLIESST nur (X = Overlay zu, Konvention).
//
// Kommuniziert nur über den Bus (ADR 0015): die Sidebar öffnet Arenen per
// 'arena-open'/'arena-create'; nach jeder Änderung am Arenen-Bestand feuert
// 'rankings-changed' (Sidebar lädt ihre Gruppe neu). Die Bestenliste springt
// per 'single-open' in die echte Einzelbildansicht (z-index 60 > Arena 50)
// für Prompt & Metadaten — Esc dort führt zurück in die Arena.
//
// Duelle sind die Rohwahrheit (ADR 0045): Sieg A/B schreibt einen
// Log-Eintrag + Elo-Update; Überspringen ruft NICHTS auf — das ehrliche
// „weiß nicht" erzeugt keine verfälschende Wertung.

import { STRINGS } from "./strings.js";
import {
  createRanking, updateRanking,
  getRankingPair, recordDuel, recordBothLost, getLeaderboard,
  getItem, mediaUrl, displayUrl, loadThumb,
} from "./api.js";
import { emit, on } from "./main.js";

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

  function setPop(n) {
    root.querySelector("#rkPop").textContent =
      n != null ? `${n.toLocaleString(STRINGS.locale)} ${STRINGS.rankingPopulation}` : "";
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

  const mediaHtml = (entry) => entry.media_kind === "video"
    ? `<video src="${mediaUrl(entry.file_hash)}" autoplay muted loop playsinline></video>`
    : `<img src="${displayUrl(entry)}" alt="">`;

  function renderPair(d) {
    pair = d.pair;
    deciding = false;
    setPop(d.population);
    body.innerHTML = `
      <div class="rkstage">
        <div class="rkcard" data-side="0">${mediaHtml(pair[0])}<div class="rkscore" hidden></div></div>
        <div class="rkvs">vs</div>
        <div class="rkcard" data-side="1">${mediaHtml(pair[1])}<div class="rkscore" hidden></div></div>
      </div>`;
  }

  // Nächstes Paar im Hintergrund holen; Bilder in den Browser-Cache wärmen
  // (Muster loupe.prefetchNeighbours — /api/media ist immutable-gecacht).
  // Bewusst VOR der Wertung des laufenden Duells: die „Abdeckung"-Auswahl
  // hinkt dadurch ein Duell hinterher — statistisch egal, gefühlt sofort.
  async function prefetchPair() {
    const mySeq = seq;
    try {
      const d = await getRankingPair(arena.id);
      if (mySeq !== seq || !open) return;
      nextPair = d;
      for (const entry of d.pair) {
        if (entry.media_kind !== "video") new Image().src = displayUrl(entry);
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
    body.innerHTML = `<div class="rkmsg vdim">${STRINGS.acLoading}</div>`;
    let d;
    try { d = await getRankingPair(arena.id); }
    catch (err) {
      if (mySeq === seq) body.innerHTML = `<div class="rkmsg warn">${esc(err.message)}</div>`;
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
  function applyJudgement(newScores, isWinner, post) {
    for (const card of body.querySelectorAll(".rkcard")) {
      const entry = pair[Number(card.dataset.side)];
      const won = isWinner(entry);
      card.classList.add(won ? "rkwin" : "rklose");
      const badge = card.querySelector(".rkscore");
      badge.hidden = false;
      badge.textContent = `${Math.round(newScores[entry.file_hash])} ${won ? "▲" : "▼"}`;
    }
    // Das vorgeholte Paar kennt die Wertung noch nicht — Beteiligte auffrischen,
    // damit dessen Anzeige/Folge-Rechnung nicht auf altem Stand aufsetzt.
    if (nextPair) {
      for (const entry of nextPair.pair) {
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

  // „Beide verlieren" (ADR-0045-Ergänzung, Feral Strawberrys Praxisbefund): beide
  // bekommen ein Duell (Abdeckung erfüllt — das Paar drängt sich nicht
  // wieder auf) und verlieren gegen den virtuellen Durchschnittsgegner.
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
    list.insertAdjacentHTML("beforeend", entries.map((e, k) => `
      <div class="rkbrow" data-index="${start + k}">
        <span class="rkbrank">${e.rank}</span>
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

  async function loadBoard() {
    const mySeq = ++seq;
    board = null;
    boardCache.clear();   // Scores können sich seit dem letzten Mal bewegt haben
    boardTotal = 0;
    rowsLoaded = 0;
    loadingRows = false;
    thumbWatcher?.disconnect();   // beobachtete Zeilen fliegen gleich aus dem DOM
    thumbWatcher = null;
    body.innerHTML = `<div class="rkmsg vdim">${STRINGS.acLoading}</div>`;
    let d;
    try { d = await fetchBoardPage(0); }
    catch (err) {
      if (mySeq === seq) body.innerHTML = `<div class="rkmsg warn">${esc(err.message)}</div>`;
      return;
    }
    if (mySeq !== seq || !open || mode !== "board") return;
    setPop(d.population);
    if (!d.total) {
      // Nur einmal leer (R3): der Weg zum ersten Duell steht direkt daneben.
      body.innerHTML = `<div class="rkmsg vdim rkempty">${STRINGS.rankingBoardEmpty}
        <button type="button" class="accentbtn" id="rkStartDuel">${STRINGS.rankingBoardStart}</button></div>`;
      return;
    }
    body.innerHTML = `
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
    showRank(0);
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
    body.querySelector("#rkbStage").innerHTML = entry.media_kind === "video"
      ? `<video src="${mediaUrl(entry.file_hash)}" controls autoplay loop playsinline></video>`
      : `<img src="${displayUrl(entry)}" alt="">`;
    body.querySelector("#rkbInfo").innerHTML =
      `<b>${STRINGS.rankingRank} ${(i + 1).toLocaleString(STRINGS.locale)}</b>
       <span class="vdim">${STRINGS.rankingBoardOf} ${boardTotal.toLocaleString(STRINGS.locale)}</span>
       · ${Math.round(entry.score)} ${STRINGS.rankingScore}
       · ${entry.duels} ${STRINGS.rankingDuels}
       <span class="vmono vdim" id="rkbName"></span>`;
    // Dateiname asynchron nachtragen (Muster Lupe: getItem liefert Fundorte).
    getItem(entry.file_hash).then((d) => {
      const nameEl = body.querySelector("#rkbName");
      if (nameEl && board?.entry === entry) {
        nameEl.textContent = d.locations.length
          ? d.locations[0].path.split("/").pop().split("\\").pop() : "";
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
    root.querySelector("#rkTitle").textContent = arena.name;
    setPop(null);
    renderMode();
  }

  function close() {
    if (!open) return;
    open = false;
    board = null;
    seq++;               // laufende Antworten entwerten
    root.hidden = true;
    body.innerHTML = ""; // stoppt laufende Videos
    emit("rankings-changed", {});   // Sidebar: Duell-/Populationszähler nachziehen
  }

  // -- Arena-Dialog (anlegen/bearbeiten) ---------------------------------------------

  function openDialog(existing) {
    document.querySelector(".pickoverlay")?.remove();   // nie zwei übereinander
    const overlay = document.createElement("div");
    overlay.className = "pickoverlay";
    overlay.innerHTML = `
      <div class="pickbox rkdlg">
        <div class="pickhead"><span class="mlabel">${existing ? STRINGS.rankingDlgTitleEdit : STRINGS.rankingDlgTitleNew}</span></div>
        <label class="cfgline">${STRINGS.rankingDlgName}
          <input type="text" id="rkDlgName" value="${esc(existing?.name || "")}" placeholder="${STRINGS.rankingDlgNamePlaceholder}"></label>
        <label class="cfgline">${STRINGS.rankingDlgExpr}
          <input type="text" id="rkDlgExpr" value="${esc(existing?.expression || "")}" placeholder="${esc(STRINGS.rankingDlgExprPlaceholder)}"></label>
        <div class="cfghint">${STRINGS.rankingDlgExprHint}</div>
        <div id="rkDlgMsg" class="warn"></div>
        <div class="adactions" style="margin-bottom:0;">
          <button type="button" class="accentbtn" id="rkDlgGo">${existing ? STRINGS.rankingDlgSave : STRINGS.rankingDlgCreate}</button>
          <button type="button" id="rkDlgCancel">${STRINGS.rankingDlgCancel}</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    const nameInput = overlay.querySelector("#rkDlgName");
    const closeDlg = () => {
      document.removeEventListener("keydown", onKey, true);
      overlay.remove();
    };
    const onKey = (e) => {
      if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); closeDlg(); }
    };
    document.addEventListener("keydown", onKey, true);

    async function submit() {
      const name = nameInput.value.trim();
      const expression = overlay.querySelector("#rkDlgExpr").value.trim();
      const msg = overlay.querySelector("#rkDlgMsg");
      if (!name) { msg.textContent = STRINGS.rankingDlgNoName; return; }
      try {
        if (existing) {
          await updateRanking(existing.id, name, expression);
          closeDlg();
          emit("rankings-changed", {});
          openArena({ id: existing.id, name, expression }, mode);   // Population ggf. neu
        } else {
          const r = await createRanking(name, expression);
          closeDlg();
          emit("rankings-changed", {});
          openArena({ id: r.id, name, expression });
        }
      } catch (err) { msg.textContent = err.message; }
    }
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay || e.target.closest("#rkDlgCancel")) return closeDlg();
      if (e.target.closest("#rkDlgGo")) submit();
    });
    overlay.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
    nameInput.focus();
  }

  // -- Verdrahtung --------------------------------------------------------------------

  root.querySelector("#rkBack").addEventListener("click", close);
  root.querySelector("#rkClose").addEventListener("click", close);
  segDuel.addEventListener("click", () => { if (mode !== "duel") { mode = "duel"; renderMode(); } });
  segBoard.addEventListener("click", () => { if (mode !== "board") { mode = "board"; renderMode(); } });
  root.querySelector("#rkEdit").addEventListener("click", () => openDialog(arena));

  body.addEventListener("click", (e) => {
    const card = e.target.closest(".rkcard");
    if (card) return void decide(Number(card.dataset.side));
    if (e.target.closest("#rkbPrev")) return void boardNav(-1);
    if (e.target.closest("#rkbNext")) return void boardNav(1);
    if (e.target.closest("#rkStartDuel")) { mode = "duel"; renderMode(); return; }
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

  on("arena-open", (d) => openArena(d));
  on("arena-create", () => openDialog(null));
}
