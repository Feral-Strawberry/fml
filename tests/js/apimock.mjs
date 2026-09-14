// apimock.mjs — fetch-Attrappe für die Node-Tests (ADR 0064).
//
// Die Module reden über api.js ausschließlich per fetch() mit dem Server.
// Hier antwortet eine Routentabelle: Tests registrieren je Pfad einen
// Handler (Daten oder {status, data}); jeder Aufruf wird mitgeschrieben,
// damit Tests prüfen können, WAS angefragt wurde (z. B. „kein Rücksprung-
// Lookup nach ‚Alle Medien'"). Unbekannte Pfade liefern eine ehrliche 404
// mit sprechendem Text statt still zu hängen.

export const mockApi = {
  routes: [],
  calls: [],
  reset() { this.routes = []; this.calls = []; },
  /** Route registrieren: `path` exakt (String) oder RegExp auf den Pfad. */
  on(method, path, handler) {
    const match = path instanceof RegExp ? (p) => path.test(p) : (p) => p === path;
    this.routes.unshift({ method: method.toUpperCase(), match, handler });   // neueste gewinnt
  },
  get(path, handler) { this.on("GET", path, handler); },
  post(path, handler) { this.on("POST", path, handler); },
  /** Antwort mit explizitem Status (z. B. 202 für Thumbnails). */
  status(code, data = {}) { return { __status: code, data }; },
  /** Aufrufe eines Pfads (Präfix) — für „wurde X angefragt?"-Prüfungen. */
  callsTo(prefix) { return this.calls.filter((c) => c.path.startsWith(prefix)); },
  /** Tor: Handler wartet, bis der Test `open()` ruft (Zwischenzustände prüfen). */
  gate() {
    let open;
    const promise = new Promise((r) => { open = r; });
    return { promise, open };
  },
};

function response(status, data) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: `mock ${status}`,
    headers: { get: () => null },
    json: async () => data,
    text: async () => JSON.stringify(data),
    blob: async () => new Blob([]),
  };
}

export async function mockFetch(input, opts = {}) {
  const url = new URL(String(input), "http://fml.test");
  const method = (opts.method || "GET").toUpperCase();
  let body = null;
  if (opts.body) { try { body = JSON.parse(opts.body); } catch { body = opts.body; } }
  const call = { method, path: url.pathname, url, body, params: url.searchParams };
  mockApi.calls.push(call);
  const route = mockApi.routes.find((r) => r.method === method && r.match(url.pathname));
  if (!route) return response(404, { detail: `mock: keine Route für ${method} ${url.pathname}` });
  // Abbruch-Signal ehren wie der Browser: Zeitlimit (AbortSignal.timeout) und
  // Bereichsabbruch (abortScope) lassen fetch mit signal.reason scheitern.
  const signal = opts.signal;
  if (signal?.aborted) throw signal.reason;
  const out = await (signal
    ? Promise.race([route.handler(call), new Promise((_, reject) =>
        signal.addEventListener("abort", () => reject(signal.reason), { once: true }))])
    : route.handler(call));
  if (out && typeof out === "object" && "__status" in out) return response(out.__status, out.data);
  return response(200, out ?? {});
}
