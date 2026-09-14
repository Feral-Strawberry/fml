// workflow.js — ComfyUI-Workflow-Vorschau als statisches SVG (Issue #47).
//
// Rendert das eingebettete workflow-JSON (LiteGraph-Speicherformat: Positionen,
// Größen, Titel, Slots, Links, Gruppen, Subgraphs) — KEIN ComfyUI-Code, keine
// Frontend-Abhängigkeit (ADR 0015). Seit #47 mit den Konventionen von
// ComfyUIs eigenem Renderer (Maße, Palette, Slot-Farben je Datentyp, Widget-
// Pillen mit Name/Wert, Bypass/Mute, eingeklappte Nodes, Raster, Subgraph-
// Kästen mit Drill-down) — Quelle der Werte: ComfyUI_frontend
// `LiteGraphGlobal.ts`, `LGraphCanvas.ts`, Palette `dark.json` (siehe #47).
// Ziehen = pan, Mausrad = zoom, Klick auf einen Subgraph-Kasten = hinein.

import { STRINGS } from "./strings.js";
import { workflowUrl } from "./api.js";
import { displayName, labelWidgets, loadInstanceWidgets } from "./widgetnames.js";

const escHtml = (s) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const escAttr = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// -- Konventionen aus ComfyUI/LiteGraph -------------------------------------------
export const NODE = {
  TITLE_H: 30, SLOT_H: 20, WIDGET_H: 20, R: 8, TEXT: 14, SUBTEXT: 12,
  GROUP_TEXT: 20, COLLAPSED_W: 80, OPACITY: 0.9, LINK_W: 3, MIN_W: 120,
};
export const PALETTE = {
  canvas: "#141414", grid: "#1e1e1e", gridMajor: "#262626",
  title: "#333", body: "#353535", titleText: "#999", text: "#AAA", box: "#666",
  widget: "#222", widgetBorder: "#666", widgetText: "#DDD", link: "#9A9",
  bypass: "#FF00FF", groupText: "#8d8d98", subgraph: "#7aa2f7",
};
// Slot-/Link-Farben nach Datentyp (ComfyUI `LGraphCanvas.link_type_colors`).
export const SLOT_COLORS = {
  CLIP: "#FFD500", CLIP_VISION: "#A8DADC", CLIP_VISION_OUTPUT: "#ad7452",
  CONDITIONING: "#FFA931", CONTROL_NET: "#6EE7B7", IMAGE: "#64B5F6", LATENT: "#FF9CF9",
  MASK: "#81C784", MODEL: "#B39DDB", STYLE_MODEL: "#C2FFAE", VAE: "#FF6E6E",
  NOISE: "#B0B0B0", GUIDER: "#66FFFF", SAMPLER: "#ECB4B4", SIGMAS: "#CDFFCD",
  TAESD: "#DCC274", AUDIO: "#F5A623", VIDEO: "#8FD3FE", UPSCALE_MODEL: "#C2B280",
};
export const slotColor = (type) => SLOT_COLORS[String(type || "").toUpperCase()] || PALETTE.link;

// LiteGraph-Modus: 0 always, 1 on event, 2 never (stumm), 3 on trigger, 4 bypass.
export const MODE = { ALWAYS: 0, NEVER: 2, BYPASS: 4 };

// Koordinaten-Zugriff (pos/size/bounding) — IMMER als endliche Zahl. Das
// Workflow-JSON stammt aus fremden Dateien (eingebetteter ComfyUI-Chunk); ein
// String-Wert würde sonst ungefiltert in ein SVG-Attribut interpoliert und
// könnte aus dem Markup ausbrechen (DOM-XSS, ADR 0032). Zahl erzwingen schließt
// das an der einzigen Geometriestelle und macht das Rendern robust (Müll → 0).
function _n(v, i) {
  const raw = Array.isArray(v) ? v[i] : (v ? (v[i] ?? v[String(i)]) : undefined);
  const n = Number(raw);
  return Number.isFinite(n) ? n : 0;
}
const _num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);
function _trunc(s, n) { s = String(s); return s.length > n ? s.slice(0, Math.max(1, n - 1)) + "…" : s; }
// Farbwerte nur als CSS-Hexfarbe durchlassen (fremdes JSON) — sonst Standard.
const _color = (v, fallback) => (typeof v === "string" && /^#[0-9a-fA-F]{3,8}$/.test(v) ? v : fallback);
const CHAR_W = 6.6;   // mittlere Zeichenbreite bei 12 px Systemschrift

// -- Laden + Bedienung ----------------------------------------------------------------

/** Workflow eines Items laden und als bedienbares SVG in `box` rendern. */
export async function renderWorkflowInto(box, hash) {
  box.innerHTML = `<span class="wfmuted">${STRINGS.workflowLoading}</span>`;
  let wf;
  try {
    const [r] = await Promise.all([fetch(workflowUrl(hash)), loadInstanceWidgets()]);
    if (!r.ok) throw new Error(STRINGS.workflowMissing);
    wf = await r.json();
  } catch (err) {
    box.innerHTML = `<span class="warn">${escHtml(err.message)}</span>`;
    return;
  }
  const path = [];   // Subgraph-Pfad (IDs) fürs Drill-down
  const draw = () => {
    try {
      const view = graphAt(wf, path);
      const genHint = wf.extra?.fml?.generated_from === "a1111"
        ? ` · ${STRINGS.workflowGenerated}` : "";
      const crumbs = path.length
        ? `<span class="wfcrumbs"><a href="#" data-wfback="0">${STRINGS.workflowRoot}</a>`
          + path.map((id, i) => ` › ${i < path.length - 1
              ? `<a href="#" data-wfback="${i + 1}">${escHtml(subgraphName(wf, id))}</a>`
              : `<b>${escHtml(subgraphName(wf, id))}</b>`}`).join("")
          + ` · <a href="#" data-wfback="${path.length - 1}">${STRINGS.workflowBack}</a></span> · `
        : "";
      box.innerHTML = `
        <div class="wfbar">${crumbs}🕸 ${(view.nodes || []).length} Nodes${genHint} · ${STRINGS.workflowHint}
          · <a href="${workflowUrl(hash)}" download="workflow_${escAttr(hash.slice(0, 12))}.json">${STRINGS.workflowDownload}</a></div>
        ${renderWorkflowSVG(wf, { path })}`;
      const svg = box.querySelector("svg");
      attachPanZoom(svg, (target) => {
        const sub = target.closest?.("[data-subgraph]");
        if (sub) { path.push(sub.getAttribute("data-subgraph")); draw(); }
      });
      box.querySelectorAll("[data-wfback]").forEach((a) => a.addEventListener("click", (e) => {
        e.preventDefault();
        path.length = parseInt(a.dataset.wfback, 10);
        draw();
      }));
    } catch (err) {
      box.innerHTML = `<span class="warn">${STRINGS.workflowUnrenderable}</span>`;
    }
  };
  draw();
}

// -- Subgraphs ------------------------------------------------------------------------

function subgraphs(wf) {
  const list = wf?.definitions?.subgraphs;
  return Array.isArray(list) ? list : [];
}
function subgraphById(wf, id) { return subgraphs(wf).find((s) => String(s.id) === String(id)) || null; }
export function subgraphName(wf, id) {
  const s = subgraphById(wf, id);
  return (s && s.name) || STRINGS.workflowSubgraph;
}
/** Der (Teil-)Graph am Pfad: Wurzel oder die Subgraph-Definition. */
export function graphAt(wf, path = []) {
  let g = wf;
  for (const id of path) {
    const s = subgraphById(wf, id);
    if (!s) break;
    g = s;
  }
  return g;
}

// -- SVG ------------------------------------------------------------------------------

function fmtValue(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Math.round(v * 1000) / 1000);
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "object") return _trunc(JSON.stringify(v), 40);
  return String(v);
}
// Zeilenumbruch nach Zeichenbudget (Wörter bleiben ganz, harte Umbrüche gelten).
function wrap(text, cols, maxLines) {
  const out = [];
  for (const para of String(text).split(/\r?\n/)) {
    let line = "";
    for (const word of para.split(/\s+/)) {
      if (!word) continue;
      if (line && (line + " " + word).length > cols) { out.push(line); line = word; }
      else line = line ? line + " " + word : word;
      while (line.length > cols) { out.push(line.slice(0, cols)); line = line.slice(cols); }
      if (out.length >= maxLines) break;
    }
    if (line || !para) out.push(line);
    if (out.length >= maxLines) break;
  }
  if (out.length > maxLines) out.length = maxLines;
  return out;
}

export function renderWorkflowSVG(wf, { path = [] } = {}) {
  const g = graphAt(wf, path);
  const subs = new Map(subgraphs(wf).map((s) => [String(s.id), s]));
  const insideSub = path.length > 0 && g !== wf;

  const nodes = (g.nodes || []).map((nd) => {
    const sub = subs.get(String(nd.type));
    const collapsed = !!(nd.flags && nd.flags.collapsed);
    const inputs = Array.isArray(nd.inputs) ? nd.inputs : [];
    const outputs = Array.isArray(nd.outputs) ? nd.outputs : [];
    const title = nd.title || (sub ? (sub.name || STRINGS.workflowSubgraph) : displayName(nd.type || "?"));
    const widgets = labelWidgets(nd).filter(([, v]) => v !== null && v !== undefined && v !== "");
    const rows = Math.max(inputs.length, outputs.length);
    const w = collapsed
      ? Math.max(NODE.COLLAPSED_W, Math.min(240, title.length * 7.5 + 40))
      : Math.max(_n(nd.size, 0), NODE.MIN_W);
    const h = collapsed ? 0 : Math.max(_n(nd.size, 1), rows * NODE.SLOT_H + 10);
    return {
      id: nd.id, type: nd.type, title, sub, collapsed, mode: _num(nd.mode),
      x: _n(nd.pos, 0), y: _n(nd.pos, 1), w, h,
      color: _color(nd.color, PALETTE.title), bg: _color(nd.bgcolor, PALETTE.body),
      inputs, outputs, widgets, rows,
    };
  });
  // Subgraph-Innenansicht: Ein-/Ausgangsknoten der Definition als Kästen.
  if (insideSub) {
    const io = (spec, id, kind) => {
      if (!spec) return null;
      const b = spec.bounding || spec.pos || [0, 0, 120, 60];
      const slots = Array.isArray(kind === "in" ? g.inputs : g.outputs) ? (kind === "in" ? g.inputs : g.outputs) : [];
      return {
        id, type: kind === "in" ? "SubgraphInputs" : "SubgraphOutputs",
        title: kind === "in" ? STRINGS.workflowSubInputs : STRINGS.workflowSubOutputs,
        sub: null, collapsed: false, mode: 0, x: _n(b, 0), y: _n(b, 1),
        w: Math.max(_n(b, 2), NODE.MIN_W), h: Math.max(_n(b, 3), slots.length * NODE.SLOT_H + 10),
        color: "#2a3a4a", bg: "#243040",
        inputs: kind === "in" ? [] : slots, outputs: kind === "in" ? slots : [], widgets: [], rows: slots.length,
      };
    };
    const inNode = io(g.inputNode, (g.inputNode && g.inputNode.id) ?? -10, "in");
    const outNode = io(g.outputNode, (g.outputNode && g.outputNode.id) ?? -20, "out");
    if (inNode) nodes.push(inNode);
    if (outNode) nodes.push(outNode);
  }
  const byId = new Map(nodes.map((nd) => [String(nd.id), nd]));
  const slotY = (nd, i) => nd.collapsed ? nd.y - NODE.TITLE_H / 2 : nd.y + 10 + i * NODE.SLOT_H;
  const inPos = (nd, i) => [nd.x, slotY(nd, i)];
  const outPos = (nd, i) => [nd.x + nd.w, slotY(nd, i)];

  const parts = [];

  // Gruppen: Fläche (Alpha .25) + Titelbalken 30 px + Text 20 px.
  for (const grp of (g.groups || [])) {
    const [gx, gy, gw, gh] = [_n(grp.bounding, 0), _n(grp.bounding, 1), _n(grp.bounding, 2), _n(grp.bounding, 3)];
    const gc = _color(grp.color, "#3f789e");
    parts.push(`<g class="wfgroup">
      <rect x="${gx}" y="${gy}" width="${gw}" height="${gh}" rx="${NODE.R}" fill="${gc}" opacity="0.25"/>
      <rect x="${gx}" y="${gy}" width="${gw}" height="${NODE.TITLE_H}" rx="${NODE.R}" fill="${gc}" opacity="0.35"/>
      <text x="${gx + 10}" y="${gy + 22}" fill="${PALETTE.groupText}" font-size="${_num(grp.font_size) || NODE.GROUP_TEXT}" font-weight="600">${escHtml(grp.title || "")}</text></g>`);
  }

  // Links: Spline, Breite 3, Farbe nach Typ, Mittelmarker.
  for (const ln of (g.links || [])) {
    const [o, os, t, ts, ty] = Array.isArray(ln)
      ? [ln[1], ln[2], ln[3], ln[4], ln[5]]
      : [ln.origin_id, ln.origin_slot, ln.target_id, ln.target_slot, ln.type];
    const a = byId.get(String(o)), b = byId.get(String(t));
    if (!a || !b) continue;
    const type = ty || (a.outputs[os || 0] && a.outputs[os || 0].type) || "";
    const [x1, y1] = outPos(a, os || 0), [x2, y2] = inPos(b, ts || 0);
    const dx = Math.max(40, Math.abs(x2 - x1) * 0.25);
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    const c = slotColor(type);
    const dim = (a.mode === MODE.NEVER || b.mode === MODE.NEVER) ? ' opacity="0.4"' : "";
    parts.push(`<g class="wflink" data-type="${escAttr(type)}"${dim}>
      <path d="M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}" fill="none" stroke="${c}" stroke-width="${NODE.LINK_W}" stroke-linecap="round"/>
      <circle cx="${mx}" cy="${my}" r="4" fill="${c}"/></g>`);
  }

  // Nodes.
  for (const nd of nodes) {
    const ty = nd.y - NODE.TITLE_H;
    const cols = Math.max(6, Math.floor((nd.w - 30) / CHAR_W));
    const modeAttr = nd.mode === MODE.BYPASS ? "bypass" : nd.mode === MODE.NEVER ? "muted" : "";
    let inner = "";
    if (nd.collapsed) {
      inner += `<rect x="${nd.x}" y="${ty}" width="${nd.w}" height="${NODE.TITLE_H}" rx="${NODE.R}" fill="${nd.color}" stroke="#222"/>
        <circle cx="${nd.x + 12}" cy="${ty + NODE.TITLE_H / 2}" r="5" fill="${nd.sub ? PALETTE.subgraph : PALETTE.box}"/>
        <text x="${nd.x + 24}" y="${ty + 19}" fill="${PALETTE.titleText}" font-size="${NODE.TEXT}" font-weight="600">${escHtml(_trunc(nd.title, Math.floor((nd.w - 30) / 7.5)))}</text>`;
    } else {
      // Körper (runde Ecken unten), Titelbalken (runde Ecken oben).
      inner += `<rect x="${nd.x}" y="${ty}" width="${nd.w}" height="${nd.h + NODE.TITLE_H}" rx="${NODE.R}" fill="${nd.bg}" stroke="#222"/>
        <path d="M ${nd.x} ${nd.y} V ${ty + NODE.R} Q ${nd.x} ${ty} ${nd.x + NODE.R} ${ty} H ${nd.x + nd.w - NODE.R} Q ${nd.x + nd.w} ${ty} ${nd.x + nd.w} ${ty + NODE.R} V ${nd.y} Z" fill="${nd.color}"/>
        <circle cx="${nd.x + 12}" cy="${ty + NODE.TITLE_H / 2}" r="5" fill="${nd.sub ? PALETTE.subgraph : PALETTE.box}"/>
        <text x="${nd.x + 24}" y="${ty + 19}" fill="${PALETTE.titleText}" font-size="${NODE.TEXT}" font-weight="600">${escHtml(_trunc(nd.title, Math.floor((nd.w - 30) / 7.5)))}</text>`;
      if (nd.sub) {
        const n = (nd.sub.nodes || []).length;
        const badge = STRINGS.workflowSubgraphBadge.replace("{n}", n);
        inner += `<text x="${nd.x + nd.w - 8}" y="${ty + 19}" fill="${PALETTE.subgraph}" font-size="${NODE.SUBTEXT}" text-anchor="end">⧉ ${escHtml(badge)}</text>`;
      }
      nd.inputs.forEach((s, i) => {
        const [sx, sy] = inPos(nd, i);
        const c = slotColor(s.type);
        const connected = s.link !== null && s.link !== undefined;
        inner += `<circle cx="${sx}" cy="${sy}" r="4" fill="${connected ? c : "none"}" stroke="${c}" stroke-width="1.5"/>
          <text x="${sx + 10}" y="${sy + 4}" fill="${PALETTE.text}" font-size="${NODE.SUBTEXT}">${escHtml(_trunc(s.label || s.name || "", 22))}</text>`;
      });
      nd.outputs.forEach((s, i) => {
        const [sx, sy] = outPos(nd, i);
        const c = slotColor(s.type);
        const connected = Array.isArray(s.links) && s.links.length > 0;
        inner += `<circle cx="${sx}" cy="${sy}" r="4" fill="${connected ? c : "none"}" stroke="${c}" stroke-width="1.5"/>
          <text x="${sx - 10}" y="${sy + 4}" fill="${PALETTE.text}" font-size="${NODE.SUBTEXT}" text-anchor="end">${escHtml(_trunc(s.label || s.name || "", 22))}</text>`;
      });
      // Widgets: Pillen Name links / Wert rechts; lange Texte als Textfeld.
      let wy = nd.y + nd.rows * NODE.SLOT_H + 6;
      const bottom = nd.y + nd.h - 6;
      for (const [name, value] of nd.widgets) {
        if (wy + NODE.WIDGET_H > bottom) break;
        const text = fmtValue(value);
        const isLong = typeof value === "string" && (text.length > cols - (name ? name.length + 3 : 0) || text.includes("\n"));
        if (isLong) {
          const maxLines = Math.max(1, Math.floor((bottom - wy - 6) / 15));
          const lines = wrap(text, cols, maxLines);
          const bh = lines.length * 15 + 8;
          inner += `<rect x="${nd.x + 10}" y="${wy}" width="${nd.w - 20}" height="${bh}" rx="6" fill="${PALETTE.widget}" stroke="${PALETTE.widgetBorder}" stroke-opacity="0.6"/>`
            + lines.map((l, i) => `<text x="${nd.x + 18}" y="${wy + 16 + i * 15}" fill="${PALETTE.widgetText}" font-size="${NODE.SUBTEXT}">${escHtml(l)}</text>`).join("");
          wy += bh + 4;
        } else {
          // Name bekommt den Platz, den der Wert nicht braucht (mindestens 45 %):
          // „control_after_generate · randomize" passt so in eine 315er-Node.
          const label = name ? _trunc(name, Math.max(Math.floor(cols * 0.45), cols - text.length - 3)) : "";
          const val = _trunc(text, Math.max(4, cols - label.length - 3));
          inner += `<rect x="${nd.x + 15}" y="${wy}" width="${nd.w - 30}" height="${NODE.WIDGET_H}" rx="10" fill="${PALETTE.widget}" stroke="${PALETTE.widgetBorder}" stroke-opacity="0.6"/>
            ${label ? `<text x="${nd.x + 26}" y="${wy + 14}" fill="${PALETTE.text}" font-size="${NODE.SUBTEXT}">${escHtml(label)}</text>` : ""}
            <text x="${nd.x + nd.w - 26}" y="${wy + 14}" fill="${PALETTE.widgetText}" font-size="${NODE.SUBTEXT}" text-anchor="end">${escHtml(val)}</text>`;
          wy += NODE.WIDGET_H + 4;
        }
      }
    }
    // Bypass: Magenta-Schleier; Mute: Node gedimmt.
    if (nd.mode === MODE.BYPASS) {
      inner += `<rect x="${nd.x}" y="${ty}" width="${nd.w}" height="${(nd.collapsed ? 0 : nd.h) + NODE.TITLE_H}" rx="${NODE.R}" fill="${PALETTE.bypass}" opacity="0.2"/>`;
    }
    const attrs = [
      `class="wfnode${nd.sub ? " wfsub" : ""}"`,
      `data-id="${escAttr(nd.id)}"`, `data-type="${escAttr(nd.type || "")}"`,
      modeAttr ? `data-mode="${modeAttr}"` : "",
      nd.sub ? `data-subgraph="${escAttr(nd.sub.id)}" style="cursor:pointer"` : "",
      `opacity="${nd.mode === MODE.NEVER ? 0.4 : NODE.OPACITY}"`,
    ].filter(Boolean).join(" ");
    parts.push(`<g ${attrs}>${inner}</g>`);
  }

  // Sichtfenster über alles spannen (inkl. Titelbalken oberhalb der Nodes).
  const xs = nodes.map((nd) => nd.x), ys = nodes.map((nd) => nd.y - NODE.TITLE_H);
  const xe = nodes.map((nd) => nd.x + nd.w), ye = nodes.map((nd) => nd.y + nd.h);
  for (const grp of (g.groups || [])) {
    xs.push(_n(grp.bounding, 0)); ys.push(_n(grp.bounding, 1));
    xe.push(_n(grp.bounding, 0) + _n(grp.bounding, 2)); ye.push(_n(grp.bounding, 1) + _n(grp.bounding, 3));
  }
  if (!xs.length) throw new Error("keine Nodes");
  const pad = 50;
  const minX = Math.min(...xs) - pad, minY = Math.min(...ys) - pad;
  const vw = Math.max(...xe) - minX + pad, vh = Math.max(...ye) - minY + pad;
  // Raster wie in ComfyUI: 10-px-Linien, alle 100 px kräftiger; Muster im
  // Nutzerraum, damit es beim Zoomen mitskaliert.
  const gridId = `wfgrid${Math.abs(Math.round(minX * 7 + minY * 13)) % 100000}`;
  return `<svg viewBox="${minX} ${minY} ${vw} ${vh}" xmlns="http://www.w3.org/2000/svg"
    preserveAspectRatio="xMidYMid meet" font-family="-apple-system, 'Helvetica Neue', Helvetica, Arial, sans-serif">
    <defs>
      <pattern id="${gridId}-minor" width="10" height="10" patternUnits="userSpaceOnUse">
        <path d="M 10 0 L 0 0 0 10" fill="none" stroke="${PALETTE.grid}" stroke-width="1"/></pattern>
      <pattern id="${gridId}" width="100" height="100" patternUnits="userSpaceOnUse">
        <rect width="100" height="100" fill="url(#${gridId}-minor)"/>
        <path d="M 100 0 L 0 0 0 100" fill="none" stroke="${PALETTE.gridMajor}" stroke-width="1"/></pattern>
    </defs>
    <rect x="${minX - 100000}" y="${minY - 100000}" width="200000" height="200000" fill="${PALETTE.canvas}"/>
    <rect x="${minX - 100000}" y="${minY - 100000}" width="200000" height="200000" fill="url(#${gridId})"/>
    ${parts.join("")}</svg>`;
}

/** Pan (ziehen) + Zoom (Mausrad); `onClick(target)` feuert bei einem Klick ohne
 *  Ziehen — für den Subgraph-Drill-down. */
export function attachPanZoom(svg, onClick) {
  if (!svg) return;
  const vb = svg.viewBox && svg.viewBox.baseVal;
  if (!vb) return;   // kein SVG-DOM (Tests) — Rendern bleibt trotzdem gültig
  let dragging = false, moved = 0, lastX = 0, lastY = 0, downTarget = null;
  svg.addEventListener("pointerdown", (e) => {
    dragging = true; moved = 0; lastX = e.clientX; lastY = e.clientY; downTarget = e.target;
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const scale = vb.width / svg.clientWidth;
    moved += Math.abs(e.clientX - lastX) + Math.abs(e.clientY - lastY);
    vb.x -= (e.clientX - lastX) * scale;
    vb.y -= (e.clientY - lastY) * scale;
    lastX = e.clientX; lastY = e.clientY;
  });
  svg.addEventListener("pointerup", () => {
    const click = dragging && moved < 4;
    dragging = false;
    if (click && onClick && downTarget) onClick(downTarget);
  });
  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const f = e.deltaY > 0 ? 1.15 : 1 / 1.15;
    const rect = svg.getBoundingClientRect();
    const mx = vb.x + (e.clientX - rect.left) / rect.width * vb.width;
    const my = vb.y + (e.clientY - rect.top) / rect.height * vb.height;
    vb.x = mx - (mx - vb.x) * f;
    vb.y = my - (my - vb.y) * f;
    vb.width *= f; vb.height *= f;
  }, { passive: false });
}
