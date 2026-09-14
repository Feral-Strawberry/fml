// bus.mjs — Ersatz für main.js in den Node-Tests (ADR 0064).
//
// main.js bootet beim Import die komplette Shell (alle init…()-Aufrufe);
// die Module importieren daraus nur den Event-Bus. Der Loader in setup.mjs
// leitet `./main.js` hierher um — gleiche drei Exporte, kein Boot.
// MUSS mit dem Bus in src/feral/web/static/js/main.js übereinstimmen.

export const bus = new EventTarget();
export const emit = (type, detail) => bus.dispatchEvent(new CustomEvent(type, { detail }));
export const on = (type, fn) => {
  const h = (e) => fn(e.detail);
  bus.addEventListener(type, h);
  return h;
};

/** Testhilfe: Mitschrift aller Events eines Typs (Reihenfolge prüfbar). */
export function record(type) {
  const seen = [];
  const h = on(type, (d) => seen.push(d));
  seen.stop = () => bus.removeEventListener(type, h);
  return seen;
}
