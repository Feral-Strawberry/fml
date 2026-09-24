// waveform.js — dreibandige Wellenform und Lautheitsangleich (A5 #162, ADR 0087).
//
// Reine Rechen- und Zeichenhilfen ohne Zustand: player.js und audiolist.js
// entscheiden, WAS gezeichnet wird, hier steht nur WIE. Die Daten kommen aus
// der Analyse von A4 (ADR 0086): je Band (low/mid/high) höchstens 1000
// Min/Max-Paare als int16-Rohwerte, ungenormt — die Skalierung entscheidet
// die Zeichnung: absolut (Vollaussteuerung = volle Höhe), damit leise und
// laute Songs auf der gemeinsamen Zeitachse vergleichbar bleiben.

/** Bezugspegel des Lautheitsangleichs (Streaming-Norm, integrierte Lautheit). */
export const REF_LUFS = -14;
/** Obergrenze für den True Peak nach dem Anheben — darüber übersteuert es. */
export const PEAK_CEILING = -1;

const BANDS = ["low", "mid", "high"];
const BAR = 2;     // Balkenbreite in CSS-Pixeln
const STEP = 3;    // Balken + Lücke

/** Verstärkung in dB, die ein Song für den Angleich braucht: Bezug minus
 *  integrierte Lautheit. Lautes wird abgesenkt; Leises nur so weit
 *  angehoben, wie der True Peak unter PEAK_CEILING bleibt (sonst übersteuert
 *  die Wiedergabe). Ohne Messung (Stille, keine Analyse): 0. */
export function matchGainDb(loudness) {
  const i = loudness?.integrated;
  if (i == null || !Number.isFinite(i)) return 0;
  let g = REF_LUFS - i;
  const tp = loudness.true_peak;
  if (g > 0 && tp != null && Number.isFinite(tp)) g = Math.min(g, Math.max(0, PEAK_CEILING - tp));
  return Math.round(g * 10) / 10;
}

/** dB → linearer Faktor. */
export const dbToGain = (db) => 10 ** (db / 20);

/** dB mit Vorzeichen und Sprach-Dezimalzeichen: „+2,1" / „−4,6" / „0,0". */
export function fmtDb(db, locale) {
  const v = Math.abs(db).toLocaleString(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  return `${db > 0 ? "+" : db < 0 ? "−" : "±"}${v}`;
}

/** Spitzen je Balken: `n` Balken über die ganze Analyse → [[low, mid, high], …]
 *  mit Werten 0…1 (Anteil an der Vollaussteuerung). Jeder Balken nimmt das
 *  Maximum seiner Buckets — kurze Spitzen verschwinden beim Verdichten nicht. */
export function barPeaks(analysis, n) {
  const wf = analysis?.waveform;
  const total = wf?.buckets || 0;
  if (!total || !(n >= 1)) return [];
  const bands = BANDS.map((b) => wf[b]);
  const out = new Array(n);
  for (let i = 0; i < n; i++) {
    const a = Math.floor((i * total) / n);
    const b = Math.max(a + 1, Math.floor(((i + 1) * total) / n));
    out[i] = bands.map(({ min, max }) => {
      let m = 0;
      for (let k = a; k < b && k < total; k++) {
        const x = Math.max(Math.abs(min[k]), Math.abs(max[k]));
        if (x > m) m = x;
      }
      return Math.min(1, m / 32768);
    });
  }
  return out;
}

/** Striche des Lineals über der Liste: Sekunden 0…axis in einer Schrittweite,
 *  die höchstens ~10 Beschriftungen ergibt. */
export function rulerTicks(axis) {
  if (!(axis > 0)) return [];
  const step = [10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600].find((s) => axis / s <= 10) || 7200;
  const out = [];
  for (let t = 0; t <= axis + 1e-6; t += step) out.push(t);
  return out;
}

function colors() {
  const cs = getComputedStyle(document.documentElement);
  const v = (n, d) => cs.getPropertyValue(n).trim() || d;
  return { low: v("--wave-lo", "#3d86e0"), mid: v("--wave-mid", "#3fb596"),
           high: v("--wave-hi", "#d9d9df"), line: v("--border", "#28282e") };
}

/** Wellenform in `cv` zeichnen (füllt die Fläche des Elternelements).
 *  `axis` = Sekunden der vollen Breite (Liste: gemeinsame Zeitachse; Player:
 *  die eigene Dauer), `duration` = Länge des Songs → er belegt den Anteil
 *  duration/axis von links. `played` 0…1 = gespielter Teil (hell, der Rest
 *  gedämpft), `gainDb` = Angleich — gezeichnet wird, was zu hören ist.
 *  `analysis` undefined/false (lädt/fehlgeschlagen) → Grundlinie.
 *  Zeichnet nur bei geändertem Stand neu (Schlüssel am Canvas). */
export function drawWave(cv, analysis, { axis, duration, played = 0, gainDb = 0 }) {
  const box = cv?.parentElement;
  const w = box?.clientWidth || 0, h = box?.clientHeight || 0;
  const ctx = w && h ? cv.getContext?.("2d") : null;
  if (!ctx) return false;
  const dpr = window.devicePixelRatio || 1;
  const frac = axis > 0 && duration > 0 ? Math.min(1, duration / axis) : 1;
  const used = Math.max(STEP, Math.round(w * frac));
  const n = Math.max(1, Math.floor(used / STEP));
  const upto = played > 0 ? Math.floor(played * n) : -1;
  const theme = document.documentElement.dataset.theme || "";
  const key = `${w}x${h}@${dpr}|${used}|${gainDb}|${theme}|${upto}`;
  if (cv._key === key && cv._analysis === analysis) return true;
  cv._key = key;
  cv._analysis = analysis;
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
    cv.width = Math.round(w * dpr);
    cv.height = Math.round(h * dpr);
  }
  cv.style.width = `${w}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const c = colors();
  const cy = h / 2;
  if (!analysis) {
    ctx.fillStyle = c.line;
    ctx.fillRect(0, Math.floor(cy), used, 1);
    return true;
  }
  const peaks = barPeaks(analysis, n);
  const k = dbToGain(gainDb) * (h - 2);
  // Bänder hinten nach vorn: Bass (meist am größten) hinten, Höhen vorn —
  // jedes Band mit seiner eigenen Höhe, sichtbar, wo es über das vordere ragt.
  for (let i = 0; i < peaks.length; i++) {
    ctx.globalAlpha = i < upto ? 1 : 0.45;
    const x = i * STEP;
    for (let b = 0; b < 3; b++) {
      const H = Math.max(1, Math.min(h, peaks[i][b] * k));
      ctx.fillStyle = c[BANDS[b]];
      ctx.fillRect(x, cy - H / 2, BAR, H);
    }
  }
  ctx.globalAlpha = 1;
  return true;
}
