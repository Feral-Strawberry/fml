// admin/util.js — kleine Helfer für die Admin-Seiten (ADR 0074).

import { STRINGS } from "../strings.js";

export const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** Zahl in der UI-Sprache (Tausendertrenner). */
export const fmtNum = (n) => Number(n || 0).toLocaleString(STRINGS.locale);

/** Sekunden → m:ss bzw. h:mm:ss. */
export function fmtElapsed(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  const m = Math.floor(s / 60), h = Math.floor(m / 60);
  if (h) return `${h}:${String(m % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

/** Bytes → GB (2 Nachkommastellen) / MB / KB. */
export function fmtBytes(n) {
  n = n || 0;
  if (n >= 1e12) return (n / 1e12).toLocaleString(STRINGS.locale, { maximumFractionDigits: 2 }) + " TB";
  if (n >= 1e9) return (n / 1e9).toLocaleString(STRINGS.locale, { maximumFractionDigits: 2 }) + " GB";
  if (n >= 1e6) return (n / 1e6).toLocaleString(STRINGS.locale, { maximumFractionDigits: 1 }) + " MB";
  return Math.round(n / 1024).toLocaleString(STRINGS.locale) + " KB";
}

/** Prozent, ganzzahlig, 0 bei fehlendem Nenner. */
export const pct = (part, total) => (total ? Math.round((part / total) * 100) : 0);

/** Uhrzeit HH:MM(:SS) in der UI-Sprache. */
export const fmtTime = (d = new Date(), seconds = true) =>
  d.toLocaleTimeString(STRINGS.locale, seconds
    ? { hour: "2-digit", minute: "2-digit", second: "2-digit" }
    : { hour: "2-digit", minute: "2-digit" });

/** {n}-Platzhalter füllen: tpl("… {n} …", {n: 3}). */
export const tpl = (s, params) =>
  String(s).replace(/\{(\w+)\}/g, (w, k) => (k in params ? params[k] : w));

/** Kleines Query-Helferlein für Seiten: el(root, "#id") mit ehrlichem Fehler. */
export function q(root, sel) {
  const node = root.querySelector(sel);
  if (!node) throw new Error(`admin: ${sel} fehlt im Markup`);
  return node;
}

// -- Gemerkter Stand der teuren Zähler (#118, ADR 0077) ----------------------------
//
// /api/admin/info liefert verwaiste Fundorte (`orphans`) und Thumbnail-Cache
// (`cache`) als gemerkten Stand {count, …, at} oder null (noch nie gezählt);
// `checking` nennt die Zähler, die gerade im Hintergrund laufen. Solange
// einer läuft, fragt die Seite alle `timing.recheckMs` nach.

export const timing = { recheckMs: 2000 };   // Tests setzen kürzer

export const isChecking = (info, key) => !!(info && (info.checking || []).includes(key));

/** Zeitpunkt eines Standes: heute nur „18:23", sonst „12.09. 18:23" — der
 *  Stand überlebt Neustarts (ADR-0077-Nachtrag) und kann Tage alt sein. */
export function fmtStand(d) {
  const now = new Date();
  const sameDay = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
  const time = fmtTime(d, false);
  return sameDay ? time : `${d.toLocaleDateString(STRINGS.locale, { day: "2-digit", month: "2-digit" })} ${time}`;
}

/** Zeile unter der Zahl: „wird geprüft …" | „Stand 18:23" | `never`. */
export function standNote(info, key, never) {
  if (isChecking(info, key)) return STRINGS.standChecking;
  const stand = info && info[key];
  return stand ? tpl(STRINGS.standAt, { t: fmtStand(new Date(stand.at)) }) : never;
}

/** Zahl oder Platzhalter: „…" während einer Zählung, sonst „?". */
export const standValue = (info, key, fmt) => {
  const stand = info && info[key];
  return stand ? fmt(stand) : `<span class="pending">${isChecking(info, key) ? "…" : "?"}</span>`;
};
