// api.js — dünne, benannte Funktionen über allen HTTP-Endpunkten (app.py).
//
// Zwei Helfer (portiert aus der alten Seite): `api()` wirft bei !ok einen
// Error mit dem `detail`-Text des Servers (FastAPI-Konvention), `postJSON()`
// schickt einen JSON-Body. Query-Parameter laufen immer über URLSearchParams,
// damit Nutzereingaben (Pfade, Suchtext) korrekt kodiert sind.

import { serverMsg } from "./servermsg.js";

/** Basis-Helfer: fetch + Fehler aus FastAPI-`detail` durchreichen.
 *  `detail` ist seit Block M.2 (ADR 0054) ein Meldungs-Dict {key, params} —
 *  HIER wird übersetzt, alle Anzeigestellen lesen weiter `err.message`. */
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(serverMsg(e.detail) || r.statusText);
  }
  return r.json();
}

/** POST mit JSON-Body. */
function postJSON(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Hängt nur die definierten Parameter als Query-String an. */
function withQuery(path, params) {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) q.set(key, String(value));
  }
  const s = q.toString();
  return s ? `${path}?${s}` : path;
}

// -- Bestand (lesend) ---------------------------------------------------------

/** Kennzahlen: total_items, total_bytes, total_locations, items_with_metadata, items_interpreted, by_container. */
export const getStats = () => api("/api/stats");

/** Eine Grid-Seite: {total, offset, items}. sort ∈ added|name|size|container|rating;
    optional gefiltert nach model (Schicht 2) und rating (manuelle Schicht, exakt). */
export const getItems = ({ limit, offset, sort, model, rating, filter, dupes, total } = {}) =>
  api(withQuery("/api/items", { limit, offset, sort, model, rating, filter, dupes, total }));

// -- Smart Folders (Stufe 3.3, ADR 0018) ----------------------------------------

/** Alle Smart Folders mit Live-Zählern: {folders}. */
export const getFolders = () => api("/api/folders");

/** Smart Folder anlegen (validiert die Grammatik): {id}. */
export const createFolder = (name, expression) =>
  postJSON("/api/folders", { name, expression });

/** Smart Folder überschreiben/umbenennen (Block S7): {id}. */
export const updateFolder = (id, name, expression) =>
  api(`/api/folders/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, expression }),
  });

/** Smart Folder löschen. */
export const deleteFolder = (id) => api(`/api/folders/${id}`, { method: "DELETE" });

/** Verteilung der manuellen Bewertungen: {ratings: [{rating, count}]}.
    Mit filter (Block S4) zählt der Kontext des Suchzustands (eigene
    rating-Chips klammert der Server aus). */
export const getRatings = (filter) => api(withQuery("/api/ratings", { filter }));

/** Detail zu einem Item (404 → Error "Unbekanntes Item."). */
export const getItem = (hash) => api(`/api/item/${hash}`);

/** „Im Dateimanager anzeigen" (I6, ADR 0041): der Server öffnet Explorer/
 *  Finder mit markierter Datei — im localhost-Betrieb der eigene Rechner.
 *  Antwort: {revealed: pfad}; 404 wenn kein Fundort mehr existiert. */
export const revealItem = (hash) => postJSON(`/api/item/${hash}/reveal`, {});

/** Reveal-Knopf verdrahten (Lupe + Einzelbildansicht, EINE Implementierung):
 *  Klick öffnet den Dateimanager; Fehler melden sich am Knopf selbst
 *  (⚠ + Meldung als Tooltip, klingt nach 4 s ab) — die Overlays brauchen
 *  dafür keinen eigenen Dialog. */
export function wireReveal(btn, currentHash) {
  const idle = { text: btn.textContent, title: btn.title };
  let timer = null;
  btn.addEventListener("click", async () => {
    const hash = currentHash();
    if (!hash) return;
    try {
      await revealItem(hash);
    } catch (err) {
      console.warn(err);
      btn.textContent = "⚠";
      btn.title = err.message;
      clearTimeout(timer);
      timer = setTimeout(() => {
        btn.textContent = idle.text;
        btn.title = idle.title;
      }, 4000);
    }
  });
}

/** Modell-Zähler für die Sidebar-Gruppe „Nach Modell"; filter wie bei
    getRatings (mitfilternde Facetten, Block S4). */
export const getModels = (filter) => api(withQuery("/api/models", { filter }));

/** Sidebar-Facetten: containers/formats/megapixels/years/undated + (S4)
    loras und input_image — je Gruppe im Kontext der ANDEREN Chips. */
export const getFacets = (filter) => api(withQuery("/api/facets", { filter }));

// -- Chip-Suche (Block S3, ADR 0035) --------------------------------------------
// Chips ↔ Grammatik laufen IMMER über den Server (ein Parser, ein
// Serialisierer): parse zerlegt getippte Ausdrücke, build macht aus dem
// Chip-Zustand den kanonischen Text. Beide liefern {expression, predicates, sort}.

/** Ausdruck → kanonischer Text + Prädikat-Dicts (400 bei Grammatikfehler). */
export const parseFilter = (expr) => api(withQuery("/api/filter/parse", { expr }));

/** Chip-Zustand (Prädikat-Dicts) → kanonischer Ausdruck (validiert). */
export const buildFilter = (predicates) => postJSON("/api/filter/build", { predicates });

// -- Manuelle Schicht: Rating, Notizen, Tags (Stufe 3.2, ADR 0017) -------------
// Alle vier Schreib-Endpunkte antworten mit dem frischen Stand: {manual: {…}}.

/** Rating setzen (1–5) oder löschen (0/null). */
export const setRating = (hash, rating) =>
  postJSON(`/api/item/${hash}/rating`, { rating });

/** Notizen setzen; leer/null löscht. */
export const setNotes = (hash, notes) => postJSON(`/api/item/${hash}/notes`, { notes });

/** Tag ans Item hängen (legt ihn im Vokabular an, falls neu). */
export const addTag = (hash, name) => postJSON(`/api/item/${hash}/tags`, { name });

/** Tag vom Item lösen (bleibt im Vokabular). */
export const removeTag = (hash, name) =>
  postJSON(`/api/item/${hash}/tags/remove`, { name });

/** Watch-Quellen (ADR 0030): {sources:[{name,path,modus,exists,watching,
 *  pending,enqueued_total}], has_library}. */
export const getWatch = () => api("/api/watch");

/** Eine Watch-Quelle (per Pfad) überwachen / die Überwachung beenden. */
export const startWatchSource = (path) => postJSON("/api/watch/start", { path });
export const stopWatchSource = (path) => postJSON("/api/watch/stop", { path });

/** Die KOMPLETTE Watch-Liste speichern (Inline-Verwaltung im Dashboard):
 *  schreibt [[watch]] in die config.toml, setzt die Watcher neu auf und
 *  liefert die neue Liste zurück. */
export const saveWatchSources = (sources) => postJSON("/api/watch/save", { sources });

/** Sammel-Aktion für die Multiselect-Auswahl (ADR 0022): {updated, manual}.
 *  fields: {rating?, add_tag?, model?} — nur Gesendetes wird ausgeführt. */
export const batchAnnotate = (hashes, fields) =>
  postJSON("/api/batch/annotate", { hashes, ...fields });

/** Sammel-Aktion aufs Suchergebnis (ADR 0040): hashes ODER filter als Scope.
 *  fields: {rating?, add_tag?, model?, note?, reject?} — rating füllt nur
 *  Unbewertete, note hängt an, reject läuft allein (ADR 0041). Antwort:
 *  {matched, rating_set?, tagged?, model_set?, noted?, rejected?}. */
export const bulkApply = (scope, fields) => postJSON("/api/batch/apply", { ...scope, ...fields });

/** Ablehnen (ADR 0041, ersetzt Löschen): Items + Metadaten raus, Hashes
 *  gesperrt — die Dateien bleiben unangetastet. */
export const rejectItems = (hashes) => postJSON("/api/batch/apply", { hashes, reject: true });

/** Sperrliste (ADR 0023/0041): {blocked: [{file_hash, reason, blocked_at, last_paths}]}. */
export const getBlocked = () => api("/api/admin/blocked");

/** Sperr-Eintrag entfernen (null = alle) — danach ist Re-Import möglich. */
export const unblockHash = (hash) =>
  postJSON(withQuery("/api/admin/blocked/remove", { file_hash: hash }), {});

/** Rausverschiebe-Vorschau (I3, ADR 0041): {available, library_root?,
 *  total_blocked?, movable?, missing?, bytes?, sample?} — movable zählt nur
 *  noch existierende Dateien; der Hash wird erst beim Lauf geprüft. */
export const getMoveout = () => api("/api/admin/moveout");

/** Pauschalweg einreihen: alle Abgelehnten aus der Library nach `target`
 *  verschieben (Engine-Aufgabe; Protokoll im Import-Log). */
export const startMoveout = (target) => postJSON("/api/admin/moveout", { target });

/** Tag-Vokabular mit Zählern: {tags}. */
export const getTags = () => api("/api/tags");

// -- Ranking-Modul (Großbaustelle R, ADR 0045) ----------------------------------
// Arena = Name + Filterausdruck (leer = ganze Bibliothek). Die Endpunkte
// existieren unabhängig vom Modul-Schalter; die UI ruft sie nur, wenn
// /api/stats `rankings: true` meldet.

/** Alle Arenen mit Live-Populationszähler: {rankings: [{id, name, expression,
 *  duels, population, error}]}. */
export const getRankings = () => api("/api/rankings");

/** Arena anlegen (validiert die Grammatik): {id}. */
export const createRanking = (name, expression) =>
  postJSON("/api/rankings", { name, expression });

/** Arena umbenennen / Population ändern (Duelle bleiben): {id}. */
export const updateRanking = (id, name, expression) =>
  api(`/api/rankings/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, expression }),
  });

/** Arena löschen (CASCADE räumt Duelle + Scores ab — bewusster Akt,
 *  Bestätigung macht die UI). */
export const deleteRanking = (id) => api(`/api/rankings/${id}`, { method: "DELETE" });

/** Nächstes Duell-Paar: {population, pair: [{file_hash, media_kind, score,
 *  duels}, …]}. 409 = Population < 2. */
export const getRankingPair = (id) => api(`/api/rankings/${id}/pair`);

/** Duell werten (Überspringen ruft NICHT auf, ADR 0045):
 *  {scores: {hash: neuerScore, …}}. */
export const recordDuel = (id, winner, loser) =>
  postJSON(`/api/rankings/${id}/duel`, { winner, loser });

/** „Beide verlieren" (ADR-0045-Ergänzung): beide Items bekommen ein Duell
 *  und verlieren gegen den virtuellen Durchschnittsgegner — Reihenfolge egal. */
export const recordBothLost = (id, a, b) =>
  postJSON(`/api/rankings/${id}/duel`, { winner: a, loser: b, outcome: "beide_verloren" });

/** Bestenliste: {population, total, entries: [{rank, file_hash, media_kind,
 *  score, duels}]}. */
export const getLeaderboard = (id, limit, offset) =>
  api(withQuery(`/api/rankings/${id}/leaderboard`, { limit, offset }));

/** „Scores neu berechnen" (Rescan-Prinzip): Replay über das Duell-Log aller
 *  Arenen — Engine-Aufgabe auf dem Writer-Thread. */
export const recomputeRankings = () => postJSON("/api/admin/rankings/recompute", {});

// -- Ordner-Browser -----------------------------------------------------------

/** Einstiegspunkte ins Dateisystem: {roots: [{name, path}]} —
 *  Projektordner, Home, Laufwerke (ADR 0029). */
export const getRoots = () => api("/api/roots");

/** Verzeichnis auflisten: {path, parent, subdirs, file_count}. */
export const browse = (path) => api(withQuery("/api/browse", { path }));

// -- Scan & Watch ---------------------------------------------------------------

/** Ordner-Scan einreihen: {queued_files}. */
export const startScan = (path) => postJSON("/api/scan", { path });

/** Einmal-Import eines Quellordners (ADR 0019); modus wie bei Watchordnern:
 *  "verschieben" leert die Quelle nach erfolgreichem Import (ADR 0025).
 *  leereOrdner (ADR 0033): leer gewordene Unterordner mit abräumen. */
export const startImport = (path, modus = "kopieren", leereOrdner = false) =>
  postJSON("/api/import", { path, modus, leere_ordner_entfernen: leereOrdner });

/** Engine-Status (Warteschlange, Watcher-Liste, last_result) — Polling-Ziel. */
export const getStatus = () => api("/api/status");

// -- Admin & Wartung (ADR 0014) --------------------------------------------------

/** DB-/Cache-/Werkzeug-Infos für die Status-Sektion. */
export const getAdminInfo = () => api("/api/admin/info");

/** Offene Scan-Probleme, gruppiert nach Fehlerart (Block N):
 *  {total, kinds: [{kind, count, issues}]} — issues sind je Art gedeckelt. */
export const getIssues = (perKind) =>
  api(withQuery("/api/admin/issues", { per_kind: perKind }));

/** Quittieren: ein Problem (issueId), eine ganze Fehlerart (kind) oder alle. */
export const resolveIssues = (issueId = null, kind = null) =>
  postJSON(withQuery("/api/admin/issues/resolve", { issue_id: issueId, kind }), {});

/** Fundorte, deren Datei verschwunden ist: {orphans}. */
export const getOrphans = () => api("/api/admin/orphans");

/** Verwaiste Fundorte löschen: {pruned}. under (ADR 0033) beschränkt auf
 *  Pfade unterhalb eines Ordners — schützt Fundorte auf Offline-Speichern. */
export const pruneOrphans = (under = null) =>
  postJSON("/api/admin/prune", under ? { under } : {});

/** Schicht 2 rückwirkend neu interpretieren (asynchron, Fortschritt via Status). */
export const startReparse = () => postJSON("/api/admin/reparse", {});

/** Erstelldaten (media_date) für den Alt-Bestand nachtragen. */
export const startBackfillDates = () => postJSON("/api/admin/backfill-dates", {});

/** FTS5-Suchindex komplett neu aufbauen. */
export const startReindex = () => postJSON("/api/admin/reindex", {});

/** Re-Scan aller bekannten Fundorte einreihen. */
export const startRescan = () => postJSON("/api/admin/rescan", {});

/** Import-Regeln (ADR 0046): Vorschau, wie viele Bestand-Items träfen. */
export const getImportRulesPreview = () => api("/api/admin/import-rules");

/** Import-Regeln rückwirkend anwenden (lehnt Treffer ab; Warteschlange). */
export const applyImportRules = () => postJSON("/api/admin/import-rules/apply", {});

/** SQLite-Integritätscheck einreihen. */
export const startIntegrityCheck = () => postJSON("/api/admin/integrity", {});

/** VACUUM einreihen. */
export const startVacuum = () => postJSON("/api/admin/vacuum", {});

/** Fehlende Thumbnails im Hintergrund vorwärmen (Engine-Warteschlange). */
export const startThumbWarm = () => postJSON("/api/admin/thumbwarm", {});

/** Thumbnail-Platten-Cache leeren: {deleted}. */
export const clearThumbCache = () => postJSON("/api/admin/thumbcache/clear", {});

/** Config lesen: {editable, path, exists, locations, thumbnail_size, raw}. */
export const getConfig = () => api("/api/admin/config");

/** Config schreiben (legt .bak-Backup an): {saved, hint}.
 *  Nimmt das komplette Feld-Objekt (locations, thumbnail_size, library_root,
 *  import_min_date, hotfolder_*, thumbnail_workers/low_priority, show_dupes). */
export const saveConfig = (fields) => postJSON("/api/admin/config", fields);

// -- URL-Bauer (für src/href — keine fetch-Aufrufe) --------------------------------

/** Thumbnail-JPEG (unveränderlich, aggressiv gecacht). */
export const thumbUrl = (hash) => `/api/thumb/${hash}`;

/** Thumbnail in ein <img> laden — gedrosselt und mit Nachfassen (ADR 0020).
 *
 * Alle Thumb-Ladevorgänge laufen über EINE kleine Warteschlange: höchstens
 * 4 gleichzeitig — beim Sprung ans Ende von 7.500 Kacheln feuerte sonst
 * jede passierte Kachel sofort ihren fetch (hunderte parallel = Browser-
 * Vollast, und die Item-Daten-Anfragen standen wieder hinten an → leere
 * Kacheln statt Platzhalter; Feral Strawberrys Windows-Runde 4). Zuletzt Angefragtes
 * zuerst (das ist das Sichtbare), weggescrollte Kacheln werden beim Dequeue
 * verworfen (Scroll-zurück baut die Kachel sowieso neu auf).
 * /api/thumb: 200 = fertig, 202/503 = Pool generiert noch (Backoff, erneut),
 * 404 = endgültig keins → <img> weg, der Platzhalter dahinter bleibt.
 */
const THUMB_MAX_PARALLEL = 4;
const _thumbQueue = [];
let _thumbActive = 0;

function _pumpThumbs() {
  while (_thumbActive < THUMB_MAX_PARALLEL && _thumbQueue.length) {
    const task = _thumbQueue.pop();          // LIFO: Sichtbares zuerst
    if (!task.img.isConnected) continue;     // weggescrollt → verwerfen
    _thumbActive++;
    _fetchThumb(task).finally(() => { _thumbActive--; _pumpThumbs(); });
  }
}

async function _fetchThumb(task) {
  let res;
  try {
    res = await fetch(thumbUrl(task.hash));
  } catch {
    res = null;                              // Server kurz weg → wie 202
  }
  if (res && res.status === 200) {
    const url = URL.createObjectURL(await res.blob());
    task.img.addEventListener("load", () => URL.revokeObjectURL(url), { once: true });
    task.img.src = url;
    return;
  }
  if (res && res.status !== 202 && res.status !== 503) {
    task.img.remove();                       // endgültig keins → Platzhalter bleibt
    return;
  }
  if (task.attempt < 10) {
    setTimeout(() => {
      if (!task.img.isConnected) return;
      _thumbQueue.push({ ...task, attempt: task.attempt + 1 });
      _pumpThumbs();
    }, Math.min(400 * 2 ** task.attempt, 5000));
  } else {
    task.img.remove();
  }
}

export function loadThumb(img, hash) {
  _thumbQueue.push({ img, hash, attempt: 0 });
  _pumpThumbs();
}

/** Original-Medium (Bild/Video) in Loupe und Panel-Vorschau. */
export const mediaUrl = (hash) => `/api/media/${hash}`;

/** Container, die der Browser nicht nativ rendert — die Anzeige nutzt das
 *  serverseitig gerenderte JPEG statt der Originalbytes (ADR 0052). */
const RENDERED_CONTAINERS = new Set(["tiff", "psd"]);

/** Anzeige-URL eines Items ({file_hash, container}): das Original — oder für
 *  TIFF/PSD die gerenderte /api/preview-Ansicht. Überall verwenden, wo ein
 *  <img src> aus einem Item entsteht (Loupe, Panel, Einzelbild, Arena). */
export const displayUrl = (item) =>
  RENDERED_CONTAINERS.has(item.container)
    ? `/api/preview/${item.file_hash}`
    : mediaUrl(item.file_hash);

/** Bild-Ladefehler dezent auffangen (fehlender Fundort, PSD ohne Composite …):
 *  statt des kaputten Browser-Bild-Icons einen Hinweis im Container zeigen
 *  (ADR 0052). `scope` ist das umschließende Element, `label` der Hinweistext. */
export function wireImageFallback(scope, label) {
  const img = scope.querySelector("img");
  if (!img) return;   // Video o. Ä. — nichts aufzufangen
  img.addEventListener(
    "error",
    () => { scope.innerHTML = `<div class="nopreview">${label}</div>`; },
    { once: true },
  );
}

/** Eingebetteter Workflow als Roh-JSON (auch als Download für ComfyUI). */
export const workflowUrl = (hash) => `/api/workflow/${hash}`;
