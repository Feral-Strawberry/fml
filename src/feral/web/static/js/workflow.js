// workflow.js — ComfyUI-Workflow-Vorschau als statisches SVG.
//
// 1:1 aus der alten Seite portiert (erprobtes Kapital, Plan Task 8): rendert
// das eingebettete workflow-JSON (LiteGraph-Speicherformat: Positionen,
// Größen, Titel, Slots, Links) — KEIN ComfyUI-Code nötig, unbekannte
// Node-Typen sind einfach Kästen mit Titel. Ziehen = pan, Mausrad = zoom.
// Einziger Unterschied: statt toggleWorkflow() gibt es renderWorkflowInto()
// für beliebige Container (Loupe-Workflow-Modus, Task 10).

import { STRINGS } from "./strings.js";
import { workflowUrl } from "./api.js";

const escHtml = (s) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const escAttr = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

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
function _trunc(s, n) { s = String(s); return s.length > n ? s.slice(0, Math.max(1, n - 1)) + "…" : s; }

/** Workflow eines Items laden und als bedienbares SVG in `box` rendern. */
export async function renderWorkflowInto(box, hash) {
  box.innerHTML = `<span class="wfmuted">${STRINGS.workflowLoading}</span>`;
  let wf;
  try {
    const r = await fetch(workflowUrl(hash));
    if (!r.ok) throw new Error(STRINGS.workflowMissing);
    wf = await r.json();
  } catch (err) {
    box.innerHTML = `<span class="warn">${escHtml(err.message)}</span>`;
    return;
  }
  try {
    // Generierte Graphen (A1111, Block N) tragen einen extra-Marker —
    // ehrlich dazusagen, dass das kein eingebetteter Workflow ist.
    const genHint = wf.extra?.fml?.generated_from === "a1111"
      ? ` · ${STRINGS.workflowGenerated}` : "";
    box.innerHTML = `
      <div class="wfbar">🕸 ${(wf.nodes || []).length} Nodes${genHint} · ${STRINGS.workflowHint}
        · <a href="${workflowUrl(hash)}" download="workflow_${escAttr(hash.slice(0, 12))}.json">${STRINGS.workflowDownload}</a></div>
      ${renderWorkflowSVG(wf)}`;
    attachPanZoom(box.querySelector("svg"));
  } catch (err) {
    box.innerHTML = `<span class="warn">${STRINGS.workflowUnrenderable}</span>`;
  }
}

export function renderWorkflowSVG(wf) {
  const nodes = (wf.nodes || []).map((nd) => ({
    id: nd.id,
    title: nd.title || nd.type || "?",
    x: _n(nd.pos, 0), y: _n(nd.pos, 1),
    w: Math.max(_n(nd.size, 0), 120), h: Math.max(_n(nd.size, 1), 34),
    color: nd.color || "#26262e", bg: nd.bgcolor || "#1d1d26",
    inputs: nd.inputs || [], outputs: nd.outputs || [],
    widgets: Array.isArray(nd.widgets_values) ? nd.widgets_values : [],
  }));
  const byId = new Map(nodes.map((nd) => [String(nd.id), nd]));
  const inPos = (nd, slot) => [nd.x, nd.y + 12 + slot * 20];
  const outPos = (nd, slot) => [nd.x + nd.w, nd.y + 12 + slot * 20];

  let parts = [];

  for (const g of (wf.groups || [])) {
    const [gx, gy, gw, gh] = [_n(g.bounding, 0), _n(g.bounding, 1), _n(g.bounding, 2), _n(g.bounding, 3)];
    parts.push(`<rect x="${gx}" y="${gy}" width="${gw}" height="${gh}" rx="8"
        fill="${escAttr(g.color || "#3f3f3f")}" opacity="0.18"/>
      <text x="${gx + 10}" y="${gy + 26}" fill="#8d8d98" font-size="20">${escHtml(g.title || "")}</text>`);
  }

  for (const ln of (wf.links || [])) {
    const [o, os, t, ts] = Array.isArray(ln)
      ? [ln[1], ln[2], ln[3], ln[4]]
      : [ln.origin_id, ln.origin_slot, ln.target_id, ln.target_slot];
    const a = byId.get(String(o)), b = byId.get(String(t));
    if (!a || !b) continue;
    const [x1, y1] = outPos(a, os || 0), [x2, y2] = inPos(b, ts || 0);
    const dx = Math.max(60, Math.abs(x2 - x1) * 0.45);
    parts.push(`<path d="M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}"
        fill="none" stroke="#ffd166" stroke-opacity="0.55" stroke-width="2"/>`);
  }

  for (const nd of nodes) {
    const slotRows = Math.max(nd.inputs.length, nd.outputs.length);
    const charW = Math.max(8, Math.floor(nd.w / 6.5));
    let inner = `
      <rect x="${nd.x}" y="${nd.y - 24}" width="${nd.w}" height="24" rx="6" fill="${escAttr(nd.color)}"/>
      <rect x="${nd.x}" y="${nd.y}" width="${nd.w}" height="${nd.h}" rx="4"
            fill="${escAttr(nd.bg)}" stroke="#34343f" stroke-width="1"/>
      <text x="${nd.x + 8}" y="${nd.y - 7}" fill="#ececed" font-size="13" font-weight="600">${escHtml(_trunc(nd.title, charW))}</text>`;
    nd.inputs.forEach((s, i) => {
      const [sx, sy] = inPos(nd, i);
      inner += `<circle cx="${sx}" cy="${sy}" r="4" fill="#6ee7a8"/>
        <text x="${sx + 8}" y="${sy + 4}" fill="#9a9aa2" font-size="11">${escHtml(_trunc(s.name || "", 18))}</text>`;
    });
    nd.outputs.forEach((s, i) => {
      const [sx, sy] = outPos(nd, i);
      inner += `<circle cx="${sx}" cy="${sy}" r="4" fill="#ff5470"/>
        <text x="${sx - 8}" y="${sy + 4}" fill="#9a9aa2" font-size="11" text-anchor="end">${escHtml(_trunc(s.name || "", 18))}</text>`;
    });
    nd.widgets.slice(0, 8).forEach((v, i) => {
      const wy = nd.y + 12 + slotRows * 20 + 8 + i * 15;
      if (wy > nd.y + nd.h - 6 || v === null || typeof v === "object") return;
      inner += `<text x="${nd.x + 8}" y="${wy}" fill="#7d7d88" font-size="10">${escHtml(_trunc(v, charW))}</text>`;
    });
    parts.push(inner);
  }

  // Sichtfenster über alles spannen (inkl. Titelbalken oberhalb der Nodes).
  const xs = nodes.map((nd) => nd.x), ys = nodes.map((nd) => nd.y - 30);
  const xe = nodes.map((nd) => nd.x + nd.w), ye = nodes.map((nd) => nd.y + nd.h);
  for (const g of (wf.groups || [])) {
    xs.push(_n(g.bounding, 0)); ys.push(_n(g.bounding, 1));
    xe.push(_n(g.bounding, 0) + _n(g.bounding, 2)); ye.push(_n(g.bounding, 1) + _n(g.bounding, 3));
  }
  if (!xs.length) throw new Error("keine Nodes");
  const pad = 50;
  const minX = Math.min(...xs) - pad, minY = Math.min(...ys) - pad;
  const vw = Math.max(...xe) - minX + pad, vh = Math.max(...ye) - minY + pad;
  return `<svg viewBox="${minX} ${minY} ${vw} ${vh}" xmlns="http://www.w3.org/2000/svg"
    preserveAspectRatio="xMidYMid meet">${parts.join("")}</svg>`;
}

export function attachPanZoom(svg) {
  if (!svg) return;
  let dragging = false, lastX = 0, lastY = 0;
  const vb = svg.viewBox.baseVal;
  svg.addEventListener("pointerdown", (e) => {
    dragging = true; lastX = e.clientX; lastY = e.clientY;
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const scale = vb.width / svg.clientWidth;
    vb.x -= (e.clientX - lastX) * scale;
    vb.y -= (e.clientY - lastY) * scale;
    lastX = e.clientX; lastY = e.clientY;
  });
  svg.addEventListener("pointerup", () => dragging = false);
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
