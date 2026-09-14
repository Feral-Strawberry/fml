// admin/pages/config.js — Seite „Konfiguration" (ADR 0074, A2 #106).
//
// Fünf Karten in festen Reihen (Media Library | Thumbnails & Leistung,
// Oberfläche | Instanz, Module). Je Einstellung: Label mit Badge
// „sofort"/„Neustart", Eingabe, Erklärung DARUNTER. Änderungen sammeln sich
// in der Speicherleiste am unteren Rand („N Änderungen · Speichern ·
// Verwerfen"), die nur bei ungespeicherten Änderungen sichtbar ist.
//
// Dirty-Erkennung: jedes gespeicherte Feld trägt data-key; readForm() liest
// alle Felder in ein flaches Objekt, `saved` ist der Schnappschuss des
// zuletzt geladenen/gespeicherten Zustands, die Zahl der abweichenden
// Schlüssel ist die Anzeige. Sprache und Darstellung tragen KEIN data-key:
// sie sind Browser-Sache (localStorage, ADR 0054), wirken sofort und sind
// nie Teil der Speicherleiste.

import { STRINGS, LANG, LANGUAGES, setLang } from "../../strings.js";
import { getConfig, saveConfig } from "../../api.js";
import { serverMsg } from "../../servermsg.js";
import { currentTheme, setTheme } from "../../appearance.js";
import { pickFolder } from "../dialogs.js";
import { esc, tpl } from "../util.js";

export const id = "config";
export const icon = '<svg viewBox="0 0 24 24"><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2.5"/><circle cx="8" cy="17" r="2.5"/></svg>';
export const title = () => STRINGS.adminConfig;
export const subtitle = () => STRINGS.subConfig;

/** Profile der Langsam-Schwelle (#110): Wert in ms → String-Schlüssel. */
export const SLOW_PROFILES = [
  [250, "cfgSlowNvme"], [600, "cfgSlowSata"], [1500, "cfgSlowNas"], [0, "cfgSlowNever"],
];

let root = null;
let saved = null;     // Schnappschuss des gespeicherten Zustands (readForm-Form)
const el = (sel) => root.querySelector(sel);

export function render(target) {
  root = target;
  root.innerHTML = `<div class="cfgfile" id="cfgFile"></div><div class="cfgstatus" id="cfgStatus"></div><div id="cfgBody"></div>`;
}

export async function load() {
  const body = el("#cfgBody");
  try {
    const c = await getConfig();
    if (!c.editable) {
      body.innerHTML = `<div class="row"><div class="card"><span class="vdim">${STRINGS.cfgNotEditable}</span></div></div>`;
      return;
    }
    el("#cfgFile").innerHTML = `${STRINGS.cfgFile} <code>${esc(c.path)}</code>${c.exists ? "" : ` <span class="warn">${STRINGS.cfgNew}</span>`}`;
    body.innerHTML = markup(c);
    wire();
    saved = readForm();
    updateBar();
  } catch (err) {
    body.innerHTML = `<div class="row"><div class="card"><span class="warn">${esc(err.message)}</span></div></div>`;
  }
}

// -- Markup ------------------------------------------------------------------------

const badge = (now) => `<span class="badge${now ? " now" : ""}">${now ? STRINGS.cfgBadgeNow : STRINGS.cfgBadgeRestart}</span>`;

/** Eine Einstellungszeile: Label (+ Badge), Eingabe, Erklärung darunter. */
function line(label, now, input, hint = "") {
  return `<div class="cfgline"><span class="lab">${label}${now === null ? "" : badge(now)}</span>
    <div class="inp">${input}</div>${hint ? `<span class="hint2">${hint}</span>` : ""}</div>`;
}

const card = (title, right, lines) =>
  `<div class="card"><div class="chead"><span class="mlabel">${title}</span>${right ? `<span class="right">${right}</span>` : ""}</div>${lines}</div>`;

const text = (key, value, extra = "") =>
  `<input type="text" data-key="${key}" value="${esc(value ?? "")}" ${extra}>`;
const number = (key, value, min, max, extra = "") =>
  `<input type="number" data-key="${key}" value="${esc(String(value ?? ""))}" min="${min}" max="${max}" ${extra}>`;
const check = (key, on, label) =>
  `<label><input type="checkbox" data-key="${key}" ${on ? "checked" : ""}> ${label}</label>`;
const select = (key, value, options) =>
  `<select data-key="${key}">${options.map(([v, l]) =>
    `<option value="${esc(String(v))}" ${String(v) === String(value) ? "selected" : ""}>${l}</option>`).join("")}</select>`;

function markup(c) {
  const rules = c.import_rules || {};
  const slow = c.slow_request_ms ?? 250;
  const slowKnown = SLOW_PROFILES.some(([ms]) => ms === slow);
  const library = card(STRINGS.cfgLibrary, "", [
    line(STRINGS.cfgLibrary, true,
      `${text("library_root", c.library_root, `placeholder="${STRINGS.cfgLibraryPlaceholder}"`)}
       <button type="button" class="pick" id="cfgLibPick" title="${STRINGS.cfgPick}">📁</button>`,
      STRINGS.cfgLibraryHint),
    line(STRINGS.cfgVerwaltung, true, check("verwaltung", c.verwaltung, STRINGS.cfgVerwaltung), STRINGS.cfgVerwaltungHint),
    line(STRINGS.cfgMinDate, true, text("import_min_date", c.import_min_date || "2015-01-01", 'style="max-width:130px"'), STRINGS.cfgMinDateHint),
    line(STRINGS.cfgMinKante, true, `${number("import_min_kante", rules.min_kante || 0, 0, 1000000)} px`, STRINGS.cfgMinKanteHint),
    line(STRINGS.cfgMaxKante, true, `${number("import_max_kante", rules.max_kante || 0, 0, 1000000)} px`, STRINGS.cfgMaxKanteHint),
    line(STRINGS.cfgFormate, true, text("import_formate", (rules.formate || []).join(", "), 'placeholder="psd, arw"'), STRINGS.cfgFormateHint),
  ].join(""));
  const perf = card(STRINGS.cfgPerf, "", [
    line(STRINGS.cfgThumbSize, false, `${number("thumbnail_size", c.thumbnail_size, 16, 2048)} px`, STRINGS.cfgThumbHint),
    line(STRINGS.cfgWorkers, false, number("thumbnail_workers", c.thumbnail_workers ?? 0, 0, 128), STRINGS.cfgWorkersHint),
    line(STRINGS.cfgVollgas, true, check("vollgas", c.thumbnail_low_priority === false, STRINGS.cfgVollgasOn), STRINGS.cfgVollgasHint),
    line(STRINGS.cfgSlow, true,
      `<select id="cfgSlowProfile">${SLOW_PROFILES.map(([ms, key]) =>
        `<option value="${ms}" ${slowKnown && ms === slow ? "selected" : ""}>${STRINGS[key]}</option>`).join("")}
        <option value="x" ${slowKnown ? "" : "selected"}>${STRINGS.cfgSlowCustom}</option></select>
       ${number("slow_request_ms", slow, 0, 600000, slowKnown ? "hidden" : "")} <span id="cfgSlowUnit" ${slowKnown ? "hidden" : ""}>ms</span>`,
      STRINGS.cfgSlowHint),
  ].join(""));
  const ui = card(STRINGS.cfgUi, STRINGS.cfgBrowserOnly, [
    line(STRINGS.cfgLang, true,
      `<select id="cfgLang">${LANGUAGES.map((l) => `<option value="${l.code}" ${l.code === LANG ? "selected" : ""}>${l.label}</option>`).join("")}</select>`,
      STRINGS.cfgLangHint),
    line(STRINGS.cfgTheme, true,
      `<select id="cfgTheme"><option value="dark" ${currentTheme() === "dark" ? "selected" : ""}>${STRINGS.cfgThemeDark}</option>
        <option value="light" ${currentTheme() === "light" ? "selected" : ""}>${STRINGS.cfgThemeLight}</option></select>`,
      STRINGS.cfgThemeHint),
    line(STRINGS.cfgShowDupes, true, check("show_dupes", c.show_dupes !== false, STRINGS.cfgShowDupesOn), STRINGS.cfgShowDupesHint),
    line(STRINGS.cfgModelSort, true, select("model_sort_order", c.model_sort, [
      ["zuletzt", STRINGS.cfgModelSortLast], ["alphabet", STRINGS.cfgModelSortAlpha], ["anzahl", STRINGS.cfgModelSortCount],
    ])),
  ].join(""));
  const inst = card(STRINGS.cfgInstanz, "", [
    line(STRINGS.cfgInstName, true, text("instanz_name", c.instanz_name, `placeholder="${STRINGS.cfgInstNamePlaceholder}" style="max-width:220px"`), STRINGS.cfgInstNameHint),
    line(STRINGS.cfgAccent, true,
      `${check("akzent_on", !!c.akzentfarbe, STRINGS.cfgAccentOn)}
       <input type="color" data-key="akzentfarbe" id="cfgAccent" value="${esc(c.akzentfarbe || "#ff3b48")}">`,
      STRINGS.cfgAccentHint),
    line(STRINGS.cfgPort, false, number("web_port", c.web_port ?? "", 1, 65535, 'placeholder="8765"'), STRINGS.cfgPortHint),
  ].join(""));
  const modules = card(STRINGS.cfgModule, "", [
    line(STRINGS.cfgRankings, true, check("rankings_enabled", c.rankings_enabled, STRINGS.cfgRankingsOn), STRINGS.cfgRankingsHint),
  ].join(""));
  return `
    <div class="row c2">${library}${perf}</div>
    <div class="row c2">${ui}${inst}</div>
    <div class="row">${modules}</div>
    <div class="savebar" id="cfgBar" hidden>
      <span class="count" id="cfgCount"></span>
      <button type="button" class="accentbtn" id="cfgSave">${STRINGS.cfgSave}</button>
      <button type="button" id="cfgDiscard">${STRINGS.cfgDiscard}</button>
      <span class="bak">${STRINGS.cfgBakHint}</span>
      <span class="msg" id="cfgBarMsg"></span>
    </div>`;
}

// -- Zustand ---------------------------------------------------------------------

/** Alle gespeicherten Felder (data-key) als flaches Objekt. */
export function readForm() {
  const out = {};
  for (const f of root.querySelectorAll("[data-key]")) {
    out[f.dataset.key] = f.type === "checkbox" ? f.checked : f.value;
  }
  return out;
}

function writeForm(values) {
  for (const f of root.querySelectorAll("[data-key]")) {
    if (!(f.dataset.key in values)) continue;
    if (f.type === "checkbox") f.checked = values[f.dataset.key];
    else f.value = values[f.dataset.key];
  }
  syncSlowProfile();
}

/** Schlüssel, die vom gespeicherten Stand abweichen. */
export function dirtyKeys() {
  if (!saved) return [];
  const now = readForm();
  return Object.keys(now).filter((k) => String(now[k]) !== String(saved[k]));
}

function updateBar() {
  const keys = dirtyKeys();
  const bar = el("#cfgBar");
  bar.hidden = keys.length === 0;
  el("#cfgCount").textContent = keys.length === 1 ? STRINGS.cfgChange1 : tpl(STRINGS.cfgChanges, { n: keys.length });
  if (keys.length === 0) el("#cfgBarMsg").textContent = "";
}

/** Profil-Auswahl ↔ Zahlenfeld der Langsam-Schwelle (#110). */
function syncSlowProfile() {
  const sel = el("#cfgSlowProfile");
  const num = el('[data-key="slow_request_ms"]');
  const known = SLOW_PROFILES.some(([ms]) => String(ms) === String(num.value));
  sel.value = known ? String(num.value) : "x";
  num.hidden = known;
  el("#cfgSlowUnit").hidden = known;
}

function payload(v) {
  return {
    thumbnail_size: parseInt(v.thumbnail_size, 10) || 320,
    library_root: v.library_root,
    verwaltung: v.verwaltung,
    import_min_date: v.import_min_date,
    // Import-Regeln (ADR 0046): 0/leer = Regel aus.
    import_min_kante: parseInt(v.import_min_kante, 10) || 0,
    import_max_kante: parseInt(v.import_max_kante, 10) || 0,
    import_formate_ausschliessen: v.import_formate.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean),
    thumbnail_workers: parseInt(v.thumbnail_workers, 10) || 0,
    thumbnail_low_priority: !v.vollgas,
    show_dupes: v.show_dupes,
    model_sort_order: v.model_sort_order,
    // Instanz (I5): 0/leer = Eintrag raus, zurück zum Standard.
    web_port: parseInt(v.web_port, 10) || 0,
    instanz_name: v.instanz_name,
    akzentfarbe: v.akzent_on ? v.akzentfarbe : "",
    // Modul-Schalter Rankings (ADR 0045): wirkt sofort in der Galerie.
    rankings_enabled: v.rankings_enabled,
    // Langsam-Schwelle (#110): wirkt sofort, 0 = nie warnen.
    slow_request_ms: Math.max(0, parseInt(v.slow_request_ms, 10) || 0),
  };
}

// -- Handler ---------------------------------------------------------------------

function wire() {
  const body = el("#cfgBody");
  body.addEventListener("input", onEdit);
  body.addEventListener("change", onEdit);

  // Sprache und Darstellung: Browser-Sache, wirken sofort, kein Speichern.
  el("#cfgLang").addEventListener("change", (e) => setLang(e.target.value));
  el("#cfgTheme").addEventListener("change", (e) => setTheme(e.target.value));

  el("#cfgLibPick").addEventListener("click", async () => {
    const input = el('[data-key="library_root"]');
    const chosen = await pickFolder(input.value.trim() || null);
    if (chosen) { input.value = chosen; updateBar(); }
  });
  el("#cfgSlowProfile").addEventListener("change", (e) => {
    const num = el('[data-key="slow_request_ms"]');
    const custom = e.target.value === "x";
    if (!custom) num.value = e.target.value;
    num.hidden = !custom;
    el("#cfgSlowUnit").hidden = !custom;
    if (custom) num.focus();
    updateBar();
  });
  el("#cfgDiscard").addEventListener("click", () => { writeForm(saved); updateBar(); });
  el("#cfgSave").addEventListener("click", save);
}

function onEdit(e) {
  // Farbwahl aktiviert die eigene Akzentfarbe gleich mit (ein Klick weniger).
  if (e.target.dataset.key === "akzentfarbe") el('[data-key="akzent_on"]').checked = true;
  if (e.target.dataset.key) updateBar();
}

async function save() {
  const btn = el("#cfgSave");
  const msg = el("#cfgBarMsg");
  btn.disabled = true;
  try {
    const now = readForm();
    const r = await saveConfig(payload(now));
    saved = now;
    el("#cfgStatus").innerHTML = `<span class="adok">${STRINGS.cfgSaved}</span> <span class="vdim">${esc(serverMsg(r.hint))}</span>`;
    updateBar();
    // Instanzname/Akzent im Admin-Dokument nachziehen (nav.js hört zu).
    document.dispatchEvent(new CustomEvent("fml:config-saved"));
  } catch (err) {
    msg.innerHTML = `<span class="warn">${esc(err.message)}</span>`;
  } finally { btn.disabled = false; }
}
