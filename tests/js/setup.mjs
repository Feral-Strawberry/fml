// setup.mjs — Browser-Umgebung für die Node-Tests der ES-Module (ADR 0064).
//
// Wird per `node --import tests/js/setup.mjs <test>` VOR dem Testmodul
// geladen (die Modul-Auflösung des Testgraphen passiert vor jeder
// Auswertung — ein normaler Import im Test käme für den Loader zu spät):
//   1. Loader-Hook: `./main.js` → tests/js/bus.mjs (Bus ohne Shell-Boot).
//   2. Globale Attrappen: document/window aus dom.mjs, localStorage,
//      fetch (apimock.mjs), Observer, matchMedia, rAF, Timer.
// Kein npm, keine Abhängigkeit — Node ≥ 20.6 (module.register) genügt.

import { register, registerHooks } from "node:module";
import {
  Document, Window, Element, KeyboardEvent, MouseEvent, PointerEvent, UIEvent, DomEvent,
} from "./dom.mjs";
import { mockFetch } from "./apimock.mjs";
import { resolve } from "./loader.mjs";

// -- 1. Loader: main.js umleiten ------------------------------------------------

if (typeof registerHooks === "function") {
  registerHooks({ resolve });                       // Node ≥ 22.15 / 23.5: synchron, im Thread
} else {
  register("./loader.mjs", import.meta.url);        // Node 20.6–22.14: Hook-Thread
}

// -- 2. Globale Attrappen ---------------------------------------------------------

const win = new Window();
const document = new Document(win);

Object.assign(globalThis, {
  window: globalThis,
  document,
  Element, HTMLElement: Element,
  KeyboardEvent, MouseEvent, PointerEvent, UIEvent, DomEvent,
  innerWidth: 1280, innerHeight: 800, devicePixelRatio: 1,
  addEventListener: win.addEventListener.bind(win),
  removeEventListener: win.removeEventListener.bind(win),
  dispatchEvent: win.dispatchEvent.bind(win),
  requestAnimationFrame: (fn) => setTimeout(() => fn(performance.now()), 0),
  cancelAnimationFrame: (id) => clearTimeout(id),
  getComputedStyle: (el) => ({
    gridTemplateColumns: "1px 1px 1px 1px",         // 4 Spalten
    rowGap: "0px", columnGap: "0px",
    paddingTop: "0px", paddingLeft: "0px", paddingRight: "0px",
    ...(el && el._computed),
  }),
  matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  MutationObserver: class { observe() {} disconnect() {} },
  ResizeObserver: class { observe() {} disconnect() {} },
  IntersectionObserver: class { observe() {} disconnect() {} },
  Image: class { constructor() { this.src = ""; } },
  location: { reload() { globalThis.__reloads = (globalThis.__reloads || 0) + 1; },
              href: "http://fml.test/", pathname: "/", search: "" },
  // Router des Admin-Dokuments (ADR 0074): pushState/replaceState setzen nur
  // location.pathname; popstate schicken die Tests selbst an window.
  history: {
    state: null, length: 1,
    pushState(state, _title, url) { this.state = state; this.length++; globalThis.location.pathname = String(url); },
    replaceState(state, _title, url) { this.state = state; globalThis.location.pathname = String(url); },
  },
  // alert()/confirm() blockieren im Browser — hier nur mitschreiben, damit
  // ein Test prüfen kann, ob ein Fehlerpfad die Attrappe getroffen hat.
  __alerts: [],
  alert: (msg) => globalThis.__alerts.push(String(msg)),
  confirm: () => true,
  fetch: mockFetch,
});

// Node hat seit v22 eine eigene localStorage-Attrappe (nur mit Datei aktiv);
// hier ein simples In-Memory-Objekt mit der Web-API.
const store = new Map();
Object.defineProperty(globalThis, "localStorage", {
  configurable: true,
  value: {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
    clear: () => store.clear(),
    get length() { return store.size; },
  },
});
localStorage.setItem("feral-lang", "de");           // Sprache deterministisch (ADR 0054)
if (typeof navigator === "undefined") globalThis.navigator = { language: "de" };   // Node < 21

// URL.createObjectURL gibt es in Node nur für Blobs mit Registrierung —
// die Kacheln brauchen nur EINEN String je Thumb.
let blobSeq = 0;
URL.createObjectURL = () => `blob:fml/${++blobSeq}`;
URL.revokeObjectURL = () => {};

// Intervalle (Status-Poller in admin.js) dürfen den Prozess nach dem letzten
// Test nicht am Leben halten. setTimeout bleibt unangetastet — darauf warten
// die Tests selbst (flush()).
const realSetInterval = globalThis.setInterval;
globalThis.setInterval = (fn, ms, ...args) => {
  const t = realSetInterval(fn, ms, ...args);
  t.unref?.();
  return t;
};

