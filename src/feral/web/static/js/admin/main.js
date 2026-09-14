// admin/main.js — Einstiegspunkt des Admin-Dokuments (/admin, ADR 0074).
//
// Hier leben nur: Boot (Theme, Instanz, Sprache), der Router (pushState/
// popstate, unbekannter Slug → Übersicht) und die Verteilung des Status-
// Pollers an Widget und aktive Seite. Die Seiten selbst sind Module in
// pages/ (register.js), Navi + Widget liegen in nav.js. Kein Bus, kein
// Dialog-Stapel der Galerie: der Admin ist ein eigenes Dokument, geteilt
// werden nur strings/api/servermsg/status/appearance.

import { getStats } from "../api.js";
import { initTheme } from "../appearance.js";
import { startStatusPolling, onStatus, onTaskFinished } from "../status.js";
import { PAGES, DEFAULT_PAGE } from "./register.js";
import { initNav, markActive, renderWidget, setInstance, setDocumentTitle } from "./nav.js";
import { esc } from "./util.js";

const pagesById = new Map(PAGES.map((p) => [p.id, p]));
let current = null;   // aktives Seitenmodul

// -- Router --------------------------------------------------------------------

/** Slug aus einem Pfad wie /admin/logs (leer/unbekannt → Standardseite). */
export function slugFromPath(path) {
  const m = /^\/admin(?:\/([a-z]+))?\/?$/.exec(path || "");
  const slug = m ? m[1] : null;
  return pagesById.has(slug) ? slug : DEFAULT_PAGE;
}

export const currentPage = () => current;

export async function show(slug, { push = false } = {}) {
  const page = pagesById.get(slug) || pagesById.get(DEFAULT_PAGE);
  const url = `/admin/${page.id}`;
  if (push) history.pushState({ page: page.id }, "", url);
  else if (location.pathname !== url) history.replaceState({ page: page.id }, "", url);
  if (current && current.unmount) current.unmount();
  current = page;
  setDocumentTitle(page.title());
  markActive(page.id);
  document.getElementById("pageTitle").textContent = page.title();
  document.getElementById("pageSub").textContent = page.subtitle();
  document.getElementById("pageHead").innerHTML = "";
  // Frisches Wurzelelement je Seitenaufruf: Seiten hängen ihre Handler an
  // die Wurzel — ein wiederverwendetes Element sammelte sie sonst an.
  const old = document.getElementById("pageBody");
  const body = document.createElement("div");
  body.id = "pageBody";
  old.replaceWith(body);
  document.getElementById("adpage").scrollTop = 0;
  try {
    await page.render(body);
    await page.load();
  } catch (err) {
    console.warn(err);
    body.insertAdjacentHTML("afterbegin", `<div class="card"><span class="warn">${esc(err.message)}</span></div>`);
  }
}

function initRouter() {
  // Alle Admin-Links im Dokument (Navi, Hinweiskarten, Widget) laufen über
  // den Router; Modifier-Klicks (neuer Tab) und fremde Ziele (/ = Galerie)
  // gehen an den Browser.
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[href]");
    if (!a || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button) return;
    const href = a.getAttribute("href");
    if (!/^\/admin(\/|$)/.test(href)) return;
    e.preventDefault();
    const slug = slugFromPath(href);
    if (current && current.id === slug) { document.getElementById("adpage").scrollTop = 0; return; }
    show(slug, { push: true });
  });
  window.addEventListener("popstate", () => show(slugFromPath(location.pathname)));
  return show(slugFromPath(location.pathname));
}

// -- Instanz (Name, Akzent) --------------------------------------------------------

async function loadInstance() {
  try {
    const st = await getStats();
    setInstance(st.instanz, current ? current.title() : "");
  } catch (err) { console.warn(err); }
}

// Seiten melden hier, was das Dokument als Ganzes betrifft (Instanzname
// nach Config-Speichern) — als DOM-Event, kein Import in Richtung Einstieg.
document.addEventListener("fml:config-saved", loadInstance);

// -- Boot ------------------------------------------------------------------------

initTheme();
initNav(PAGES);
loadInstance();
initRouter();
onStatus((s) => {
  renderWidget(s);
  if (current && current.onStatus) current.onStatus(s);
});
onTaskFinished((s) => {
  if (current && current.onTaskFinished) current.onTaskFinished(s);
});
startStatusPolling();
