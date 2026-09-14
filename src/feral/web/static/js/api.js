// api.js — dünne, benannte Funktionen über allen HTTP-Endpunkten (app.py).
//
// Zwei Helfer (portiert aus der alten Seite): `api()` wirft bei !ok einen
// Error mit dem `detail`-Text des Servers (FastAPI-Konvention), `postJSON()`
// schickt einen JSON-Body. Query-Parameter laufen immer über URLSearchParams,
// damit Nutzereingaben (Pfade, Suchtext) korrekt kodiert sind.

import { serverMsg } from "./servermsg.js";
import { STRINGS } from "./strings.js";

/** Basis-Helfer: fetch + Fehler aus FastAPI-`detail` durchreichen.
 *  `detail` ist seit Block M.2 (ADR 0054) ein Meldungs-Dict {key, params} —
 *  HIER wird übersetzt, alle Anzeigestellen lesen weiter `err.message`. */
//
// Zeitlimits (ADR 0069): LESENDE Anfragen (GET) brechen nach READ_TIMEOUT_MS
// ab — eine nie beantwortete Anfrage blockierte sonst bis zum Reload
// (Galerie-Seite blieb „angefragt", Sperren gingen nie zurück). SCHREIBENDE
// Anfragen bekommen KEIN Zeitlimit: ein abgebrochener POST hinterließe
// unbekannten Serverzustand, und Wartungsläufe dürfen dauern. `opts.timeout`
// überschreibt (0 = keins), `opts.signal` (Abbruch-Bereich, s. u.) kommt
// dazu. Ein Zeitablauf ist ein normaler Fehler mit übersetzter Meldung.
const READ_TIMEOUT_MS = 60_000;

async function api(path, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  const signals = [];
  if (opts.signal) signals.push(opts.signal);
  const timeout = opts.timeout ?? (method === "GET" ? READ_TIMEOUT_MS : 0);
  if (timeout > 0) signals.push(AbortSignal.timeout(timeout));
  const signal = signals.length ? AbortSignal.any(signals) : undefined;
  let r;
  try {
    r = await fetch(path, { ...opts, signal });
  } catch (err) {
    if (err?.name === "TimeoutError") throw new Error(STRINGS.requestTimeout);
    throw err;   // AbortError (Ansicht geschlossen) und Netzfehler unverändert
  }
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

// -- Abbruch-Bereiche (ADR 0069) ----------------------------------------------
//
// Eine Ansicht (Lupe, Einzelbild, Vergleich, Arena) holt ihre Daten mit dem
// Signal ihres Bereichs und bricht beim Schließen ALLE laufenden Anfragen
// auf einmal ab: `getItem(hash, { signal: scopeSignal("single") })` …
// `abortScope("single")`. Nach dem Abbruch ist der Bereich frisch.
const _scopes = new Map();

export function scopeSignal(name) {
  let c = _scopes.get(name);
  if (!c) { c = new AbortController(); _scopes.set(name, c); }
  return c.signal;
}

export function abortScope(name) {
  const c = _scopes.get(name);
  if (!c) return;
  _scopes.delete(name);
  c.abort();
}

/** Abbruch durch uns selbst (Ansicht geschlossen) — nicht melden. */
export const isAbort = (err) => err?.name === "AbortError";

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

/** Grid-Position eines Items in der aktuellen Treffermenge (ADR 0060) —
 *  Parameter wie getItems; Antwort {index} (0-basiert, null = nicht drin). */
export const getItemPosition = ({ hash, sort, model, rating, filter, dupes } = {}) =>
  api(withQuery("/api/items/position", { hash, sort, model, rating, filter, dupes }));

// -- Smart Folders (Stufe 3.3, ADR 0018) ----------------------------------------

/** Alle Smart Folders: {folders: [{id, name, expression, count, error}]}.
 *  counts=false liefert nur die Liste ohne Zähler („Liste vor Zahlen",
 *  Issue #69) — der Zähler fehlt dann im Eintrag (undefined), null = Ausdruck
 *  ungültig. Mit Zählern kommt die Zahl aus dem Epochen-Cache (ADR 0071). */
export const getFolders = ({ counts = true } = {}) =>
  api(withQuery("/api/folders", { counts: counts ? undefined : 0 }));

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

/** Alle Sidebar-Zähler eines Suchzustands in EINEM Request (#99, ADR 0073):
    {models, facets, ratings} — dieselben Nutzlasten wie /api/models,
    /api/facets und /api/ratings, aber aus einem Filterlauf und je Ausdruck
    serverseitig gemerkt (eigene Chips klammert der Server je Gruppe aus). */
export const getSidebar = (filter) => api(withQuery("/api/sidebar", { filter }));

/** Detail zu einem Item (404 → Error "Unbekanntes Item."). */
export const getItem = (hash, opts) => api(`/api/item/${hash}`, opts);

/** „Im Dateimanager anzeigen" (I6, ADR 0041): der Server öffnet Explorer/
 *  Finder mit markierter Datei — im localhost-Betrieb der eigene Rechner.
 *  Antwort: {revealed: pfad}; 404 wenn kein Fundort mehr existiert. */
export const revealItem = (hash) => postJSON(`/api/item/${hash}/reveal`, {});

/** Fundort-Breadcrumb (ADR-0041-Nachtrag): `what` = "folder" öffnet den Ordner
 *  im Dateimanager ohne Markierung, "file" die Datei im zugeordneten Programm.
 *  `path` muss ein Fundort dieses Items bzw. ein Verzeichnis-Präfix davon sein. */
export const openLocation = (hash, path, what) =>
  postJSON(`/api/item/${hash}/open`, { path, what });

/** Reveal-Knopf verdrahten (Lupe + Einzelbildansicht, EINE Implementierung):
 *  Klick öffnet den Dateimanager; Fehler melden sich am Knopf selbst
 *  (⚠ + Meldung als Tooltip, klingt nach 4 s ab) — die Overlays brauchen
 *  dafür keinen eigenen Dialog. Solange der Server prüft (Hash bis 64 MB,
 *  ADR-0062-Nachtrag), zeigt der Knopf ⏳; konnte nur der Ordner geöffnet
 *  werden (Windows-Langpfad), sagt er das ehrlich (📁 + Hinweis). */
export function wireReveal(btn, currentHash) {
  const idle = { text: btn.textContent, title: btn.title };
  let timer = null;
  let pending = false;
  const flash = (text, title) => {
    btn.textContent = text;
    btn.title = title;
    clearTimeout(timer);
    timer = setTimeout(() => {
      btn.textContent = idle.text;
      btn.title = idle.title;
    }, 4000);
  };
  btn.addEventListener("click", async () => {
    const hash = currentHash();
    if (!hash || pending) return;
    pending = true;
    clearTimeout(timer);
    btn.textContent = "⏳";
    btn.title = STRINGS.revealPending;
    try {
      const res = await revealItem(hash);
      if (res && res.selected === false) flash("📁", STRINGS.revealFolderOnly);
      else { btn.textContent = idle.text; btn.title = idle.title; }
    } catch (err) {
      console.warn(err);
      flash("⚠", err.message);
    } finally {
      pending = false;
    }
  });
}

/** Modell-Liste (Detail-Panel, Sammel-Dialog): {models, unknown, …}. Die
    Sidebar holt ihre Zähler über getSidebar. */
export const getModels = (filter) => api(withQuery("/api/models", { filter }));

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
/** Sperrliste seitenweise mit Suche (#66): {blocked, total, total_all, offset, limit}. */
export const getBlocked = ({ q = "", offset = 0, limit = 100 } = {}) =>
  api(withQuery("/api/admin/blocked", { q: q || undefined, offset: offset || undefined, limit }));

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
 *  duels, population, error}]}. counts=false: nur die Liste, population fehlt
 *  (Liste vor Zahlen wie getFolders, Issue #69). */
export const getRankings = ({ counts = true } = {}) =>
  api(withQuery("/api/rankings", { counts: counts ? undefined : 0 }));

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

/** Nächstes Duell-Paar: {population, eliminated, pair: [{file_hash,
 *  media_kind, score, duels}, …]}. 409 = Population < 2; pair === null =
 *  Pool erschöpft (weniger als zwei Aktive, #87). */
/** Nächstes Paar; ``prefetch`` markiert das Vorholen im Hintergrund (der
 *  Server loggt eine langsame Paarung dann als INFO, ADR-0072-Nachtrag). */
export const getRankingPair = (id, { prefetch = false } = {}) =>
  api(`/api/rankings/${id}/pair${prefetch ? "?prefetch=1" : ""}`);

/** Duell werten (Überspringen ruft NICHT auf, ADR 0045):
 *  {scores: {hash: neuerScore, …}}. */
export const recordDuel = (id, winner, loser) =>
  postJSON(`/api/rankings/${id}/duel`, { winner, loser });

/** „Beide raus" (#87, ADR-0045-Nachtrag): beide Items bekommen ein Duell,
 *  verlieren gegen den virtuellen Durchschnittsgegner UND scheiden aus
 *  dieser Arena aus — Reihenfolge egal. */
export const recordBothLost = (id, a, b) =>
  postJSON(`/api/rankings/${id}/duel`, { winner: a, loser: b, outcome: "beide_verloren" });

/** „Wieder rein" (#87): ausgeschiedenes Item zurück in den Pool der Arena
 *  (append-only Log-Zeile, Score bleibt): {reinstated: hash}. */
export const reinstateRanking = (id, hash) =>
  postJSON(`/api/rankings/${id}/reinstate`, { hash });

/** „raus" an der Duellkarte (#87-Nachtrag, Variante 2): der Partner gewinnt
 *  das Duell, das andere Bild verliert und scheidet aus: {scores}. */
export const recordOut = (id, winner, loser) =>
  postJSON(`/api/rankings/${id}/duel`, { winner, loser, outcome: "raus" });

/** Bestenliste: {population, total, eliminated, entries: [{rank, file_hash,
 *  media_kind, score, duels, eliminated}]} — Ausgeschiedene am Ende. */
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
/** Serverlog-Schwanz: beide Dateien, oder file: "web"|"worker"; level:
 *  "warning" = nur WARNING und höher (serverseitig gefiltert, ADR 0074). */
export const getAdminLog = (lines = 100, { level = null, file = null } = {}) =>
  api(withQuery("/api/admin/log", { lines, level: level || undefined, file: file || undefined }));
/** Zahlen für die Diagramme der Admin-Übersicht (ADR 0074 Nachtrag). */
export const getAdminOverview = () => api("/api/admin/overview");

/** Offene Scan-Probleme, gruppiert nach Fehlerart (Block N):
 *  {total, kinds: [{kind, count, issues}]} — issues sind je Art gedeckelt. */
export const getIssues = (perKind) =>
  api(withQuery("/api/admin/issues", { per_kind: perKind }));

/** Quittieren: ein Problem (issueId), eine ganze Fehlerart (kind) oder alle. */
export const resolveIssues = (issueId = null, kind = null) =>
  postJSON(withQuery("/api/admin/issues/resolve", { issue_id: issueId, kind }), {});

/** Fundorte, deren Datei verschwunden ist: {orphans}. */
/** Verwaiste Fundorte zählen (teuer: stat je Fundort): {total, sample, under}. */
export const getOrphans = (under = null) =>
  api(withQuery("/api/admin/orphans", { under: under || undefined }));

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

/** Wartungskarten (A3): {parsers:[{parser,version,items}], undated, open_issues, blocked_count}. */
export const getMaintenanceStats = () => api("/api/admin/maintenance");

/** DB-Aufteilung per dbstat (nur auf Knopfdruck): {available, free_bytes, index_bytes, groups}. */
export const getDbBreakdown = () => api("/api/admin/dbstat");

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
// „Cache zählen" (#118): Verzeichnislauf nur auf Klick, Ergebnis = gemerkter Stand.
export const getThumbCache = () => api("/api/admin/thumbcache");

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
// Zeitlimit je Thumbnail-Anfrage (ADR 0069, #27): vier hängende Verbindungen
// hielten die Pumpe bis zum Reload an — volle Bilder luden weiter, nur
// Kacheln blieben leer. Nach Ablauf gilt „Server kurz weg" → Backoff, erneut.
const THUMB_TIMEOUT_MS = 20_000;
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
    res = await fetch(thumbUrl(task.hash), { signal: AbortSignal.timeout(THUMB_TIMEOUT_MS) });
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

/** Video-Element AUSDRÜCKLICH freigeben (#87/#89): ein verworfenes <video>
 *  hält seine Range-Verbindung offen, bis der Garbage Collector es einsammelt;
 *  Browser erlauben nur wenige Verbindungen je Host, Firefox hat zudem ein
 *  Media-Cache-Budget — ein paar solcher Leichen (4-GB-Videos!) und neue
 *  Medien laden minutenlang nicht. pause + src/poster weg + load() gibt die
 *  Verbindung sofort zurück (Standardweg laut HTML-Spec). ÜBERALL rufen, wo
 *  ein <video> ersetzt oder entfernt wird — innerHTML="" reicht NICHT. */
export function releaseVideo(v) {
  try { v.pause?.(); } catch { /* egal */ }
  v.removeAttribute("src");
  v.removeAttribute("poster");
  try { v.load?.(); } catch { /* egal */ }
}

/** Alle <video> unterhalb von `scope` freigeben (vor jedem innerHTML-Ersatz). */
export function releaseVideos(scope) {
  if (!scope) return;
  for (const v of scope.querySelectorAll("video")) releaseVideo(v);
}

/** Medien-Ladefehler dezent auffangen (fehlender Fundort, PSD ohne Composite,
 *  Video, das der Browser nicht öffnet …): statt des kaputten Browser-Icons
 *  oder einer schwarzen Bühne einen Hinweis im Container zeigen (ADR 0052,
 *  Video seit ADR 0069/#25). `scope` ist das umschließende Element, `label`
 *  der Hinweistext. Ein Video gibt dabei seine Verbindung frei. */
export function wireMediaFallback(scope, label, d = null) {
  const media = scope.querySelector("img, video");
  if (!media) return;
  const fail = () => {
    if (!media.isConnected) return;   // längst ersetzt (Blättern) — nichts überschreiben
    if (media.tagName === "VIDEO") releaseVideo(media);
    // `label` darf eine Funktion sein (#71): erst im Fehlerfall steht fest,
    // ob ein MediaError-Code vorliegt, den die Codec-Meldung nennt.
    const text = typeof label === "function" ? label(media) : label;
    // Mit Item-Wissen (Video): Poster + Hinweis + 📂-Knopf, wie beim Vorabtest.
    if (d && media.tagName === "VIDEO") mountUnplayable(scope, d, text);
    else scope.innerHTML = `<div class="nopreview">${escHtml(text)}</div>`;
  };
  media.addEventListener("error", fail, { once: true });
  if (media.tagName === "VIDEO") {
    // Zweites Netz (#71, Feral Strawberrys Firefox-Befund): Ein Browser, der die
    // Bildspur nicht dekodiert, wirft nicht immer einen Fehler — Firefox
    // spielt bei ProRes im MOV einfach nur die Tonspur. Dann hat das Video
    // nach den Metadaten KEINE Bildmaße: videoWidth 0 heißt „kein Bild",
    // egal was canPlayType vorher versprochen hat.
    media.addEventListener("loadedmetadata", () => {
      if (media.isConnected && !media.videoWidth) fail();
    }, { once: true });
  }
}

const escHtml = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// -- Ehrlicher Player (#71, ADR 0070) -----------------------------------------
// Schicht 2 (Parser »video«) nennt Codec, Profil und Pixelformat; der Browser
// selbst sagt per canPlayType, ob er das dekodiert. Nicht Abspielbares
// bekommt Poster-Frame + Hinweis statt eines Players, der nur Ton bringt oder
// schwarz bleibt — und es wird gar kein Stream angefordert (4-GB-Dateien!).

/** Codec-Wissen eines Items aus den interpretierten Feldern, oder null. */
export function videoCodecFacts(d) {
  const pick = (f) => (d?.interpreted || []).find((x) => x.field === f)?.value || "";
  const codec = pick("video_codec").toLowerCase();
  if (!codec) return null;
  return { codec, profile: pick("video_profile"), pixFmt: pick("pixel_format").toLowerCase() };
}

// Anzeigenamen sind Eigennamen, nicht übersetzt.
const CODEC_NAMES = {
  prores: "ProRes", hevc: "HEVC (H.265)", h264: "H.264", av1: "AV1", vp9: "VP9",
  vp8: "VP8", dnxhd: "DNxHD", mjpeg: "Motion JPEG", cineform: "CineForm", ffv1: "FFV1",
};

/** „ProRes (HQ, 10-bit)" — Codec-Name plus Profil und Bittiefe aus dem Pixelformat. */
export function codecLabel(facts) {
  if (!facts) return "";
  const base = CODEC_NAMES[facts.codec] || facts.codec.toUpperCase();
  const bits = /p(\d{2})(?:le|be)?$/.exec(facts.pixFmt)?.[1];
  const extra = [facts.profile, bits ? `${bits}-bit` : ""].filter(Boolean).join(", ");
  return extra ? `${base} (${extra})` : base;
}

// H.264 spielen Browser nur als 8-bit 4:2:0; canPlayType bejaht High 10
// trotzdem (Chrome parst nur die Profil-Nummer) — deshalb harte Regel.
const H264_WEB_PIXEL_FORMATS = new Set(["", "yuv420p", "yuvj420p", "nv12"]);

/** MIME-Kandidaten für canPlayType je Codec; leere Liste = „unbekannt, probieren". */
function codecTypeCandidates(facts, mime) {
  switch (facts.codec) {
    case "prores":
      // Nur Safari (AVFoundation kennt die ProRes-FourCCs). Bewusst IMMER
      // mit codecs-Angabe: nacktes "video/quicktime" beantwortet Firefox
      // mit „maybe" (behandelt es als MP4-Container) und baute den Player,
      // der dann nur Ton brachte (Feral Strawberrys Befund, 2026-09-11).
      return ['video/quicktime; codecs="apch"', `${mime}; codecs="apch"`];
    case "hevc":
      return [`${mime}; codecs="hvc1.1.6.L93.B0"`, `${mime}; codecs="hev1.1.6.L93.B0"`];
    case "h264":
      return [`${mime}; codecs="avc1.64001F"`];
    case "vp9":
      return [`${mime}; codecs="vp09.00.10.08"`, `${mime}; codecs="vp9"`];
    case "vp8":
      return [`${mime}; codecs="vp8"`];
    case "av1":
      return [`${mime}; codecs="av01.0.08M.08"`];
    default:
      return [];
  }
}

/** Kann DIESER Browser das Video dekodieren? Ohne Codec-Wissen: ja (probieren). */
export function canPlayVideo(d) {
  const facts = videoCodecFacts(d);
  if (!facts) return true;
  if (facts.codec === "h264" && !H264_WEB_PIXEL_FORMATS.has(facts.pixFmt)) return false;
  const probe = document.createElement("video");
  if (typeof probe.canPlayType !== "function") return true;
  const mime = d.container === "matroska" ? "video/webm" : "video/mp4";
  const candidates = codecTypeCandidates(facts, mime);
  if (!candidates.length) return true;
  return candidates.some((type) => probe.canPlayType(type) !== "");
}

/** Poster-Frame + Hinweis + 📂-Knopf anstelle des Players (Panel, Lupe,
 *  Einzelbild, Arena). Der Knopf ist ein ECHTER Reveal-Knopf (Feral Strawberrys Befund:
 *  ein bloß erwähntes 📂 wirkt kaputt, weil man es nicht anklicken kann und
 *  das Panel sonst keins hat) — nach dem Einhängen `wireUnplayable(scope, d)`
 *  rufen, oder gleich `mountUnplayable()`. */
export function unplayableHtml(d, text = null) {
  const note = text ?? STRINGS.videoUnplayable.replace("{codec}", codecLabel(videoCodecFacts(d)));
  return `<div class="nopreview codecnote"><img src="${thumbUrl(d.file_hash)}" alt="">`
    + `<span>${escHtml(note)}</span>`
    + `<button type="button" class="codecreveal" title="${escHtml(STRINGS.revealTitle)}">${escHtml(STRINGS.videoOpenElsewhere)}</button></div>`;
}

/** Den 📂-Knopf eines eingehängten Hinweises verdrahten (idempotent). */
export function wireUnplayable(scope, d) {
  const btn = scope?.querySelector(".codecreveal:not([data-wired])");
  if (!btn) return;
  btn.dataset.wired = "1";
  wireReveal(btn, () => d.file_hash);
}

/** Hinweis einhängen UND verdrahten — für Stellen, die den Container selbst füllen. */
export function mountUnplayable(scope, d, text = null) {
  scope.innerHTML = unplayableHtml(d, text);
  wireUnplayable(scope, d);
}

/** Hinweistext für wireMediaFallback: mit Codec-Wissen die Codec-Meldung
 *  samt Fehlercode, sonst das allgemeine „Keine Vorschau verfügbar". */
export function mediaFallbackLabel(d) {
  const facts = d?.media_kind === "video" ? videoCodecFacts(d) : null;
  if (!facts) return STRINGS.noPreview;
  return (media) => (media?.error
    ? STRINGS.videoPlayFailed
      .replace("{codec}", codecLabel(facts))
      .replace("{code}", String(media.error.code ?? "?"))
    : STRINGS.videoUnplayable.replace("{codec}", codecLabel(facts)));   // kein Bild, kein Fehler
}

/** Nachträglich (Item-Details kamen asynchron, z. B. Arena): läuft in `scope`
 *  ein Video, das dieser Browser nicht dekodiert, wird es freigegeben und
 *  durch Poster + Hinweis ersetzt. Liefert true, wenn getauscht wurde. */
export function swapUnplayable(scope, d) {
  if (!scope || d?.media_kind !== "video" || canPlayVideo(d)) return false;
  if (!scope.querySelector("video")) return false;
  releaseVideos(scope);
  mountUnplayable(scope, d);
  return true;
}

/** Eingebetteter Workflow als Roh-JSON (auch als Download für ComfyUI). */
export const workflowUrl = (hash) => `/api/workflow/${hash}`;
