// admin/register.js — Seitenregister des Admin-Dokuments (ADR 0074 Punkt 2),
// nach dem Muster der Parser-Registry (interpret/registry.py): eine Seite =
// ein Modul in pages/ mit
//   id          Slug in der URL (/admin/<id>)
//   icon        SVG-Markup für die Seitennavigation
//   title()     Seitentitel (Sprache ist zur Ladezeit fest, ADR 0054)
//   subtitle()  eine Zeile: was die Seite tut
//   render(root)  Markup + Handler in den Seitenbereich bauen
//   load()      Daten holen (nach render)
//   onStatus(s)        optional: jeder Poll von /api/status
//   onTaskFinished(s)  optional: eine Aufgabe ist fertig geworden
//   unmount()          optional: Aufräumen beim Seitenwechsel
// Reihenfolge hier = Reihenfolge in der Navigation. Neue Seite: Modul
// anlegen, hier eintragen, Strings in ALLEN strings.<lang>.js.

import * as overview from "./pages/overview.js";
import * as config from "./pages/config.js";
import * as sources from "./pages/sources.js";
import * as maintenance from "./pages/maintenance.js";
import * as issues from "./pages/issues.js";
import * as arenas from "./pages/arenas.js";
import * as logs from "./pages/logs.js";

export const PAGES = [overview, config, sources, maintenance, issues, arenas, logs];
export const DEFAULT_PAGE = "overview";
