// workflow.test.mjs — Workflow-Vorschau im ComfyUI-Look (Issue #47): Slot- und
// Link-Farben je Datentyp, Maße/Palette, Widget-Beschriftung (named > Instanz-
// Dump > Kern-Tabelle > roh), Bypass/Mute, eingeklappte Nodes, Gruppen,
// Subgraph-Kasten und Drill-down, Härtung gegen fremdes JSON (ADR 0032).

import { test } from "node:test";
import assert from "node:assert/strict";
import { WORKFLOW, SUB_ID } from "./wf_fixture.mjs";

const wf = await import("../../src/feral/web/static/js/workflow.js");
const wn = await import("../../src/feral/web/static/js/widgetnames.js");
const { renderWorkflowSVG, slotColor, NODE, PALETTE, graphAt } = wf;

const svg = renderWorkflowSVG(WORKFLOW);
const nodeG = (id) => {
  const m = svg.match(new RegExp(`<g class="wfnode[^"]*" data-id="${id}"[^>]*>[\\s\\S]*?</g>`));
  assert.ok(m, `Node ${id} nicht im SVG`);
  return m[0];
};

test("Slot- und Link-Farben folgen dem Datentyp wie in ComfyUI", () => {
  assert.equal(slotColor("MODEL"), "#B39DDB");
  assert.equal(slotColor("latent"), "#FF9CF9");          // Groß/Klein egal
  assert.equal(slotColor("SOMETHING_ELSE"), PALETTE.link);
  assert.match(svg, /<g class="wflink" data-type="CLIP"[^>]*>\s*<path[^>]*stroke="#FFD500" stroke-width="3"/);
  assert.match(svg, /<g class="wflink" data-type="VAE"[^>]*>\s*<path[^>]*stroke="#FF6E6E"/);
  // Mittelmarker in Linkfarbe
  assert.match(svg, /<g class="wflink" data-type="IMAGE"[^>]*>[\s\S]*?<circle[^>]*r="4" fill="#64B5F6"/);
  // Slot-Punkt: verbunden gefüllt, unverbunden nur Ring (KSampler negative)
  const ks = nodeG(8);
  assert.match(ks, /<circle[^>]*fill="#B39DDB" stroke="#B39DDB"/);            // model verbunden
  assert.match(ks, /<circle[^>]*fill="none" stroke="#FFA931"/);               // negative offen
});

test("Maße und Palette: Titelbalken 30, Radius 8, Standardfarben, Raster, Node-Opazität", () => {
  assert.deepEqual([NODE.TITLE_H, NODE.SLOT_H, NODE.WIDGET_H, NODE.R, NODE.TEXT, NODE.SUBTEXT, NODE.COLLAPSED_W],
                   [30, 20, 20, 8, 14, 12, 80]);
  const ks = nodeG(8);
  assert.match(ks, /<rect x="1140" y="90" width="315" height="292" rx="8" fill="#353535"/);   // Körper inkl. Titel
  assert.match(ks, /fill="#333"\/>/);                                                       // Titelbalken
  assert.match(ks, /fill="#999" font-size="14" font-weight="600">KSampler</);
  assert.match(ks, /opacity="0.9"/);
  assert.match(svg, /<pattern id="wfgrid\d+-minor" width="10" height="10"/);
  assert.match(svg, /fill="#141414"/);
});

test("Widgets: Kern-Tabelle beschriftet positional, lange Texte werden Textfelder, Anzeigename ohne Titel", () => {
  const ks = nodeG(8);
  for (const [name, val] of [["seed", "123456789"], ["control_after_generate", "randomize"], ["steps", "20"],
                             ["cfg", "1"], ["sampler_name", "euler"], ["scheduler", "simple"], ["denoise", "1"]]) {
    assert.match(ks, new RegExp(`>${name}</text>[\\s\\S]*?text-anchor="end">${val}</text>`), `${name}=${val}`);
  }
  const loader = nodeG(1);
  assert.match(loader, />Load Diffusion Model</);                     // DISPLAY_NAMES statt UNETLoader
  assert.match(loader, />unet_name</);
  const prompt = nodeG(5);
  assert.match(prompt, />Positive Prompt</);                           // eigener Titel gewinnt
  assert.match(prompt, /<rect x="410" y="[\d.]+" width="400"[^>]*fill="#222"/);   // Textfeld, keine Pille
  assert.match(prompt, />a red fox sitting in fresh snow,/);
  assert.match(prompt, /fill="#353"/);                                 // Nodefarbe aus dem JSON
});

test("Widgets: widgets_values_named schlägt die Tabelle, Instanz-Dump schlägt die Kern-Tabelle, sonst roh", () => {
  const named = renderWorkflowSVG({ nodes: [{ id: 1, type: "KSampler", pos: [0, 0], size: [300, 200],
    widgets_values: [1, 2], widgets_values_named: { seed: 42, steps: 30 } }], links: [] });
  assert.match(named, />seed<\/text>[\s\S]*?>42</);
  assert.match(named, />steps<\/text>[\s\S]*?>30</);
  wn.setInstanceWidgets({ MyCustomNode: ["strength", "mode"] });
  try {
    const custom = renderWorkflowSVG({ nodes: [{ id: 1, type: "MyCustomNode", pos: [0, 0], size: [300, 120],
      widgets_values: [0.5, "soft"] }], links: [] });
    assert.match(custom, />strength<\/text>[\s\S]*?>0.5</);
    assert.match(custom, />mode<\/text>[\s\S]*?>soft</);
  } finally { wn.setInstanceWidgets({}); }
  const raw = renderWorkflowSVG({ nodes: [{ id: 1, type: "UnknownNode", pos: [0, 0], size: [300, 120],
    widgets_values: [7, "x"] }], links: [] });
  assert.match(raw, /text-anchor="end">7</);
  assert.doesNotMatch(raw, /y="[\d.]+" fill="#AAA" font-size="12">null</);
});

test("Bypass zeigt den Magenta-Schleier, Mute dimmt, eingeklappte Nodes sind nur Titelbalken", () => {
  const bypass = nodeG(13);
  assert.match(bypass, /data-mode="bypass"/);
  assert.match(bypass, /fill="#FF00FF" opacity="0.2"/);
  const muted = nodeG(14);
  assert.match(muted, /data-mode="muted"/);
  assert.match(muted, /opacity="0.4"/);
  const collapsed = nodeG(4);
  assert.match(collapsed, /height="30" rx="8"/);
  assert.doesNotMatch(collapsed, /lora_name/);                      // keine Widgets im eingeklappten Zustand
  const w = Number(collapsed.match(/width="([\d.]+)"/)[1]);
  assert.ok(w >= NODE.COLLAPSED_W && w <= 240, `Breite ${w}`);
});

test("Gruppe mit Titelbalken und Alpha, Subgraph-Kasten mit Badge und Drill-down", () => {
  assert.match(svg, /<g class="wfgroup">\s*<rect x="20" y="40" width="360" height="470" rx="8" fill="#3f789e" opacity="0.25"/);
  assert.match(svg, /font-size="20" font-weight="600">Loader</);
  const sub = nodeG(12);
  assert.match(sub, new RegExp(`data-subgraph="${SUB_ID}"`));
  assert.match(sub, />Upscale 2x</);
  assert.match(sub, />⧉ 2 Nodes · Klick öffnet</);
  // Innenansicht: Ein-/Ausgänge als Kästen, Links vom Eingangsknoten
  const inner = renderWorkflowSVG(WORKFLOW, { path: [SUB_ID] });
  assert.match(inner, /data-id="-10"[\s\S]*?>Eingänge</);
  assert.match(inner, /data-id="-20"[\s\S]*?>Ausgänge</);
  assert.match(inner, /data-type="UPSCALE_MODEL"[^>]*>\s*<path[^>]*stroke="#C2B280"/);
  assert.equal((inner.match(/class="wflink"/g) || []).length, 3);
  assert.equal(graphAt(WORKFLOW, [SUB_ID]).name, "Upscale 2x");
  assert.equal(graphAt(WORKFLOW, ["gibt-es-nicht"]), WORKFLOW);
});

test("Härtung: Strings in Geometrie werden 0, fremde Farbwerte fallen auf die Palette zurück, Text ist escaped", () => {
  const evil = renderWorkflowSVG({ nodes: [{ id: 1, type: "KSampler", pos: ['"><script>', 5], size: ["1e9x", "bad"],
    color: 'red" onload="x', bgcolor: "url(javascript:1)", title: "<b>&amp;</b>",
    widgets_values: ["<img src=x onerror=1>"] }], links: [], groups: [{ title: "<x>", bounding: ["a", 0, 100, 50], color: "x" }] });
  assert.doesNotMatch(evil, /<script>|onload=|onerror=1>|javascript:/);
  assert.match(evil, /x="0" y="-25"/);                                // pos-String → 0, Titelbalken darüber
  assert.match(evil, /fill="#353535"/);                               // bgcolor verworfen
  assert.match(evil, />&lt;b&gt;&amp;amp;&lt;\/b&gt;</);
  assert.match(evil, /fill="#3f789e" opacity="0.25"/);                // Gruppenfarbe verworfen
});

test("renderWorkflowInto: Leiste mit Node-Zahl, SVG, Subgraph-Kasten klickbar; Fehlerpfad bleibt ehrlich", async () => {
  const { loadShell, flush } = await import("./harness.mjs");
  const { mockApi } = await import("./apimock.mjs");
  loadShell();
  const hash = "ab".repeat(32);
  mockApi.get(`/api/workflow/${hash}`, () => WORKFLOW);
  mockApi.get("/static/widgets.json", () => mockApi.status(404, {}));
  const box = document.createElement("div");
  document.body.appendChild(box);
  await wf.renderWorkflowInto(box, hash);
  await flush();
  assert.match(box.querySelector(".wfbar").textContent, /14 Nodes/);
  assert.ok(box.querySelector("svg"), "kein SVG");
  assert.ok(box.querySelector(`[data-subgraph="${SUB_ID}"]`), "Subgraph-Kasten fehlt");
  const missing = document.createElement("div");
  mockApi.get(`/api/workflow/${"cd".repeat(32)}`, () => mockApi.status(404, { detail: "nein" }));
  await wf.renderWorkflowInto(missing, "cd".repeat(32));
  await flush();
  assert.match(missing.textContent, /Kein Workflow eingebettet/);
});
