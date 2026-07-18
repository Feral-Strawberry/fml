// servermsg.js — serverseitige Meldungen übersetzen (Block M.2, ADR 0054).
//
// Der Server liefert sichtbare Texte als Meldungs-Dicts {key, params};
// die Sätze stehen in strings.<lang>.js unter `server`. Parameter dürfen
// Zahlen (lokalisiert formatiert), Strings, verschachtelte Meldungen oder
// Listen von Meldungen sein — Listen werden mit « · » gejoint (so bauen
// sich zusammengesetzte Zusammenfassungen wie „Import: 3 neu · 2 Dubletten").
//
// Übergangsregel (ADR 0054): rohe Strings (Alt-Einträge, technische
// Fehlertexte) gehen unverändert durch; unbekannte Schlüssel (alte UI
// gegen neuen Server oder umgekehrt) erscheinen roh als Schlüssel + Werte —
// ehrlich statt leer.

import { STRINGS } from "./strings.js";

function fmtParam(value) {
  if (Array.isArray(value)) return value.map(serverMsg).join(" · ");
  if (value && typeof value === "object") return serverMsg(value);
  if (typeof value === "number") return value.toLocaleString(STRINGS.locale);
  return String(value);
}

/** Meldung (Dict/String/Liste) → anzeigbarer Text der aktiven UI-Sprache. */
export function serverMsg(m) {
  if (m == null) return "";
  if (typeof m === "string") return m;
  if (Array.isArray(m)) return m.map(serverMsg).join(" · ");
  const tpl = STRINGS.server[m.key];
  const params = m.params || {};
  if (typeof tpl !== "string") {
    const values = Object.values(params).map(fmtParam).join(" · ");
    return values ? `${m.key}: ${values}` : String(m.key ?? "");
  }
  return tpl.replace(/\{(\w+)\}/g, (whole, name) =>
    name in params ? fmtParam(params[name]) : whole);
}
