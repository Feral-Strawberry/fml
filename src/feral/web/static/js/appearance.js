// appearance.js — Theme und Instanz-Erscheinungsbild, geteilt von Galerie
// und Admin (zwei Dokumente, ADR 0074).
//
// Theme: Dark ist Standard (kein data-theme-Attribut); nur 'light' wird
// explizit gesetzt. Wahl überlebt in localStorage('feral-theme') und gilt
// für beide Dokumente. Umschalten: Schnellmenü der Galerie und Admin →
// Konfiguration → Oberfläche.
//
// Instanz (ADR 0041, I5): Name + Akzentfarbe aus [web] in der Config
// unterscheiden parallel laufende Instanzen: Badge, Tab-Titel und ein
// Farbpunkt im Favicon. Ohne Config-Einträge bleibt alles beim Standard.

export const THEME_KEY = "feral-theme";
export const DEFAULT_TITLE = "Feral Media Library";

export function initTheme() {
  if (localStorage.getItem(THEME_KEY) === "light") {
    document.documentElement.dataset.theme = "light";
  }
}

export const currentTheme = () =>
  document.documentElement.dataset.theme === "light" ? "light" : "dark";

export function setTheme(name) {
  if (name === "light") document.documentElement.dataset.theme = "light";
  else delete document.documentElement.dataset.theme;
  localStorage.setItem(THEME_KEY, name === "light" ? "light" : "dark");
}

let faviconBase = null; // Original-Href merken, um zum Standard zurückzukönnen

function tintFavicon(farbe) {
  const link = document.querySelector('link[rel="icon"]');
  if (!link) return;
  if (faviconBase === null) faviconBase = link.href;
  if (!farbe) { link.href = faviconBase; return; }
  const img = new Image();
  img.onload = () => {
    const c = document.createElement("canvas");
    c.width = c.height = 64;
    const ctx = c.getContext("2d");
    ctx.drawImage(img, 0, 0, 64, 64);
    // Farbpunkt unten rechts statt Um-Einfärben: die Erdbeere bleibt
    // erkennbar, der Punkt unterscheidet die Tabs.
    ctx.beginPath();
    ctx.arc(46, 46, 16, 0, Math.PI * 2);
    ctx.fillStyle = farbe;
    ctx.fill();
    ctx.lineWidth = 3;
    ctx.strokeStyle = "rgba(0, 0, 0, .35)";
    ctx.stroke();
    link.href = c.toDataURL("image/png");
  };
  img.src = faviconBase;
}

/** Instanzname/-farbe anwenden. `badge` (optional) zeigt den Namen als
 *  Pille; `title` ist der Seitentitel ohne Instanzname. */
export function applyInstance(inst, { badge = null, title = DEFAULT_TITLE, badgeTitle = "" } = {}) {
  const root = document.documentElement;
  const name = (inst && inst.name) || "";
  const farbe = (inst && inst.farbe) || "";
  document.title = name ? `${name} — ${title}` : title;
  if (badge) {
    badge.hidden = !name;
    badge.textContent = name;
    badge.title = badgeTitle;
  }
  if (/^#[0-9a-f]{6}$/i.test(farbe)) {
    // Die abgeleiteten Varianten (-dim/-line) sind in theme.css feste
    // rgba-Werte — hier aus dem Hex neu gerechnet, gleiche Alphas.
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(farbe.slice(i, i + 2), 16));
    root.style.setProperty("--accent", farbe);
    root.style.setProperty("--accent-dim", `rgba(${r}, ${g}, ${b}, .14)`);
    root.style.setProperty("--accent-line", `rgba(${r}, ${g}, ${b}, .5)`);
    tintFavicon(farbe);
  } else {
    root.style.removeProperty("--accent");
    root.style.removeProperty("--accent-dim");
    root.style.removeProperty("--accent-line");
    tintFavicon(null);
  }
}

// Topbar-Umschalter Dark/Light (#123, ersetzt das Schnellmenü): das Icon
// zeigt den AKTIVEN Modus (Mond = dark, Sonne = light), der Titel nennt die
// Wirkung des Klicks. Strings liefert der Aufrufer (eigene Ladewege).
const ICON_MOON = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';
const ICON_SUN = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';

export function initThemeToggle(btn, { toDark = "", toLight = "" } = {}) {
  const sync = () => {
    const light = currentTheme() === "light";
    btn.innerHTML = light ? ICON_SUN : ICON_MOON;
    btn.title = light ? toDark : toLight;
    btn.dataset.theme = currentTheme();
  };
  btn.addEventListener("click", () => {
    setTheme(currentTheme() === "light" ? "dark" : "light");
    sync();
  });
  sync();
}
