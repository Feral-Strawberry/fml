// strings.js — Sprachlader (ADR 0054): alle Module importieren STRINGS von HIER.
//
// Sprache ist Sache des Browsers: localStorage gewinnt (harter Umschalter in
// der Kopfzeile / Admin → Konfiguration), sonst entscheidet die
// Browser-Sprache (de* → Deutsch, alles andere → Englisch). Der dynamische
// Import mit top-level await hält den Modulgraphen an, bis die Sprachdatei
// da ist — kein Konsumenten-Modul muss sich um Asynchronität kümmern.
//
// Eine weitere Sprache = eine weitere strings.XX.js + ein Eintrag in
// LANGUAGES (Label in der jeweiligen Sprache selbst, wird nie übersetzt).

export const LANGUAGES = [
  { code: "de", label: "Deutsch" },
  { code: "en", label: "English" },
];

const LANG_KEY = "feral-lang";

function detectLang() {
  const saved = localStorage.getItem(LANG_KEY);
  if (LANGUAGES.some((l) => l.code === saved)) return saved;
  return (navigator.language || "").toLowerCase().startsWith("de") ? "de" : "en";
}

/** Aktive UI-Sprache dieser Seite (steht für die Lebensdauer der Seite fest). */
export const LANG = detectLang();

/** Harter Umschalter: merken + Reload (ADR 0054 — einmal gesetzt, übersteuert
    die Browser-Sprache dauerhaft; Speichern auch ohne Wechsel, damit die
    aktuelle Sprache gegen künftige Browser-Umstellungen gepinnt ist). */
export function setLang(code) {
  if (!LANGUAGES.some((l) => l.code === code)) return;
  localStorage.setItem(LANG_KEY, code);
  if (code !== LANG) location.reload();
}

document.documentElement.lang = LANG;

// Fallback Deutsch (Quelle der Wahrheit): falls eine Sprachdatei fehlt oder
// kaputt ist, bleibt die Oberfläche benutzbar statt weiß.
let _mod;
try {
  _mod = await import(`./strings.${LANG}.js`);
} catch (err) {
  console.warn(`strings.${LANG}.js nicht ladbar — falle auf Deutsch zurück`, err);
  _mod = await import("./strings.de.js");
}

export const STRINGS = _mod.STRINGS;
