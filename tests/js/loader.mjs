// loader.mjs — Resolve-Hook: `./main.js` der Module → tests/js/bus.mjs.
//
// Eigene Datei, weil module.register() (Node < 22.15) den Hook in einem
// separaten Thread lädt — dort soll NICHT die ganze Browser-Attrappe aus
// setup.mjs mitlaufen. Siehe setup.mjs für die Registrierung.

const BUS_URL = new URL("./bus.mjs", import.meta.url).href;

export function resolve(specifier, context, nextResolve) {
  const fromModule = (context.parentURL || "").includes("/web/static/js/");
  if (fromModule && /(^|\/)main\.js$/.test(specifier)) {
    return { url: BUS_URL, shortCircuit: true };
  }
  return nextResolve(specifier, context);
}
