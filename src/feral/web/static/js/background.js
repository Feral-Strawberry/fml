// background.js — Hintergrund-Knöpfe der Galerie (ADR 0093, #226/#223).
//
// Zwei Icon-Knöpfe in der Kopfzeile, für alle Installationen:
//   Leistung  — Blitz = Normal, Blatt = Leise (ein Prozess, unter Windows
//               hart auf einen Kern, niedrigste Priorität). Klick schaltet um.
//   Anhalten  — „Zz" (bewusst kein ❚❚: das gehört dem Player), angehalten in
//               Akzentfarbe als Hinweis, warum nichts läuft. Klick hält
//               die Warteschlange an der nächsten Datei an, nochmal Klick
//               setzt im eingestellten Leistungsmodus fort.
// Beide Zustände gehören dem Server (app_state), nicht dem Browser: die
// Knöpfe zeigen, was /api/status meldet, und schicken nur Wechsel.

import { setBackground } from "./api.js";
import { STRINGS } from "./strings.js";
import { onStatus } from "./status.js";

const svg = (body) =>
  `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
export const ICON_BOLT = svg('<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>');
export const ICON_LEAF = svg('<path d="M11 20A7 7 0 0 1 4 13C4 7 10 3 20 3c0 10-4 16-9 17z"/><path d="M4 21c3-6 7-9 12-12"/>');
export const ICON_SLEEP = svg('<path d="M3 5h6l-6 7h6"/><path d="M12 11h9l-9 9h9"/>');

export function initBackgroundButtons(power, pause) {
  let state = { quiet: null, paused: null, waiting: 0 };

  const render = () => {
    power.innerHTML = state.quiet ? ICON_LEAF : ICON_BOLT;
    power.dataset.icon = state.quiet ? "leaf" : "bolt";   // Symbol allein zeigt den Zustand, wie Hell/Dunkel
    power.setAttribute("aria-pressed", state.quiet ? "true" : "false");
    power.title = state.quiet ? STRINGS.bgPowerQuiet : STRINGS.bgPowerNormal;
    pause.innerHTML = ICON_SLEEP;
    pause.classList.toggle("on", !!state.paused);
    pause.setAttribute("aria-pressed", state.paused ? "true" : "false");
    pause.title = state.paused
      ? STRINGS.bgPauseOn.replace("{n}", state.waiting)
      : STRINGS.bgPauseOff;
  };

  async function send(change) {
    const before = { ...state };
    state = { ...state, ...change };
    render();                              // sofort sichtbar, der nächste Poll bestätigt
    try {
      await setBackground(change);
    } catch {
      state = before;
      render();
    }
  }

  power.addEventListener("click", () => send({ quiet: !state.quiet }));
  pause.addEventListener("click", () => send({ paused: !state.paused }));

  onStatus((s) => {
    if (s.quiet === undefined) return;
    state = { quiet: !!s.quiet, paused: !!s.paused, waiting: s.queue_pending || 0 };
    render();
  });
  render();
}
