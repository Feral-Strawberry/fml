// dom.mjs — winziger DOM-Stub für Node-Unit-Tests der ES-Module (ADR 0064).
//
// Kein jsdom, kein npm (§0.1): genau die Teilmenge des DOM, die die Module
// unter src/feral/web/static/js/ tatsächlich benutzen — Baum, innerHTML-
// Parser, Selektoren (#id .klasse tag [attr="x"] :not() Nachfahren),
// classList/dataset/style, Events mit Capture- und Bubble-Phase. Layout gibt
// es nicht: Maße sind 0 (oder je Element gesetzt), getComputedStyle liefert
// feste Werte. Fehlt etwas, hier ergänzen — bewusst klein halten.

const VOID = new Set([
  "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
  "source", "track", "wbr",
]);
const RAW_TEXT = new Set(["script", "style"]);
const BOOL_ATTRS = ["hidden", "disabled", "checked", "selected", "autoplay",
  "controls", "loop"];
const STRING_ATTRS = ["id", "title", "src", "alt", "href", "placeholder",
  "type", "name", "lang"];

const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
export function decodeEntities(s) {
  return s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => {
    if (e[0] === "#") {
      const n = e[1].toLowerCase() === "x" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      return Number.isFinite(n) ? String.fromCodePoint(n) : m;
    }
    return ENTITIES[e.toLowerCase()] ?? m;
  });
}
const escText = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const escAttr = (s) => s.replace(/[&"]/g, (c) => ({ "&": "&amp;", '"': "&quot;" }[c]));

// -- Events ---------------------------------------------------------------------

export class DomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.bubbles = !!init.bubbles;
    this.cancelable = !!init.cancelable;
    this.detail = init.detail;
    this.target = null;
    this.currentTarget = null;
    this.defaultPrevented = false;
    this._stop = false;
    this._stopNow = false;
    for (const k of ["key", "code", "ctrlKey", "shiftKey", "altKey", "metaKey",
      "clientX", "clientY", "deltaY", "pointerId", "button"]) {
      if (k in init) this[k] = init[k];
    }
  }
  preventDefault() { if (this.cancelable) this.defaultPrevented = true; }
  stopPropagation() { this._stop = true; }
  stopImmediatePropagation() { this._stop = true; this._stopNow = true; }
}
export class KeyboardEvent extends DomEvent {}
export class MouseEvent extends DomEvent {}
export class PointerEvent extends MouseEvent {}
export class UIEvent extends DomEvent {}

class EventNode {
  constructor() { this._listeners = new Map(); }
  _eventParent() { return null; }
  addEventListener(type, fn, opts) {
    if (!fn) return;
    const capture = typeof opts === "object" ? !!opts?.capture : !!opts;
    const once = typeof opts === "object" ? !!opts?.once : false;
    let list = this._listeners.get(type);
    if (!list) { list = []; this._listeners.set(type, list); }
    if (list.some((l) => l.fn === fn && l.capture === capture)) return;   // wie im Browser
    list.push({ fn, capture, once });
  }
  removeEventListener(type, fn, opts) {
    const capture = typeof opts === "object" ? !!opts?.capture : !!opts;
    const list = this._listeners.get(type);
    if (!list) return;
    const i = list.findIndex((l) => l.fn === fn && l.capture === capture);
    if (i >= 0) list.splice(i, 1);
  }
  /** Anzahl Listener eines Typs (optional nur Capture) — für „keine hängenden
   *  Listener"-Prüfungen in den Tests. */
  listenerCount(type, capture = null) {
    const list = this._listeners.get(type) || [];
    return capture === null ? list.length : list.filter((l) => l.capture === capture).length;
  }
  _invoke(ev, capture) {
    const list = this._listeners.get(ev.type);
    if (!list) return;
    for (const l of [...list]) {
      if (l.capture !== capture) continue;
      if (l.once) this.removeEventListener(ev.type, l.fn, l.capture);
      ev.currentTarget = this;
      if (typeof l.fn === "function") l.fn.call(this, ev);
      else l.fn.handleEvent(ev);
      if (ev._stopNow) return;
    }
  }
  dispatchEvent(ev) {
    // Native Events (new CustomEvent(...) aus Produktcode, z. B. das
    // Admin-Dokument meldet „fml:config-saved" am document) haben ein
    // schreibgeschütztes target — als DomEvent nachbauen.
    if (!(ev instanceof DomEvent)) {
      ev = new DomEvent(ev.type, { bubbles: ev.bubbles, cancelable: ev.cancelable, detail: ev.detail });
    }
    ev.target = this;
    const path = [];
    for (let n = this; n; n = n._eventParent()) path.push(n);
    for (let i = path.length - 1; i >= 1; i--) {
      path[i]._invoke(ev, true);
      if (ev._stop) return !ev.defaultPrevented;
    }
    this._invoke(ev, true);
    if (!ev._stop) this._invoke(ev, false);
    if (ev.bubbles && !ev._stop) {
      for (let i = 1; i < path.length; i++) {
        path[i]._invoke(ev, false);
        if (ev._stop) break;
      }
    }
    ev.currentTarget = null;
    return !ev.defaultPrevented;
  }
}

export class Window extends EventNode {}

// -- Knoten ------------------------------------------------------------------------

export class Node extends EventNode {
  constructor(doc) {
    super();
    this.ownerDocument = doc;
    this.parentNode = null;
    this.childNodes = [];
  }
  _eventParent() { return this.parentNode; }
  get parentElement() { return this.parentNode instanceof Element ? this.parentNode : null; }
  get isConnected() {
    for (let n = this; n; n = n.parentNode) if (n instanceof Document) return true;
    return false;
  }
  get firstChild() { return this.childNodes[0] || null; }
  get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; }
  get nextSibling() {
    if (!this.parentNode) return null;
    const c = this.parentNode.childNodes;
    return c[c.indexOf(this) + 1] || null;
  }
  get previousSibling() {
    if (!this.parentNode) return null;
    const c = this.parentNode.childNodes;
    return c[c.indexOf(this) - 1] || null;
  }
  contains(node) {
    for (let n = node; n; n = n.parentNode) if (n === this) return true;
    return false;
  }
  remove() {
    if (this.parentNode) this.parentNode.removeChild(this);
  }
  replaceWith(node) {
    const parent = this.parentNode;
    if (!parent) return;
    parent.insertBefore(node, this);
    parent.removeChild(this);
  }
  appendChild(node) { return this.insertBefore(node, null); }
  insertBefore(node, ref) {
    if (node.parentNode) node.parentNode.removeChild(node);
    node.parentNode = this;
    if (ref) {
      const i = this.childNodes.indexOf(ref);
      if (i < 0) throw new Error("insertBefore: Referenzknoten ist kein Kind");
      this.childNodes.splice(i, 0, node);
    } else {
      this.childNodes.push(node);
    }
    return node;
  }
  removeChild(node) {
    const i = this.childNodes.indexOf(node);
    if (i < 0) throw new Error("removeChild: Knoten ist kein Kind");
    this.childNodes.splice(i, 1);
    node.parentNode = null;
    return node;
  }
  replaceChildren(...nodes) {
    for (const c of [...this.childNodes]) this.removeChild(c);
    for (const n of nodes) this.appendChild(n);
  }
  get textContent() {
    return this.childNodes.map((c) => c.textContent).join("");
  }
  set textContent(v) {
    this.replaceChildren(new Text(this.ownerDocument, String(v ?? "")));
  }
}

export class Text extends Node {
  constructor(doc, data) { super(doc); this.nodeType = 3; this.data = data; }
  get textContent() { return this.data; }
  set textContent(v) { this.data = String(v); }
  get outerHTML() { return escText(this.data); }
}

export class Comment extends Node {
  constructor(doc, data) { super(doc); this.nodeType = 8; this.data = data; }
  get textContent() { return ""; }
  get outerHTML() { return `<!--${this.data}-->`; }
}

export class Element extends Node {
  constructor(doc, tag) {
    super(doc);
    this.nodeType = 1;
    this.localName = tag.toLowerCase();
    this.tagName = tag.toUpperCase();
    this.attributes = new Map();
    this.style = makeStyle();
    // Layout-Maße: standardmäßig 0, Tests setzen sie bei Bedarf direkt.
    this.clientWidth = 0; this.clientHeight = 0;
    this.offsetWidth = 0; this.offsetHeight = 0;
    this.offsetLeft = 0; this.offsetTop = 0;
    this.scrollTop = 0; this.scrollLeft = 0; this.scrollHeight = 0;
    this.naturalWidth = 0; this.naturalHeight = 0; this.videoWidth = 0;
    this.paused = true;
    this._value = null;
    this._rect = null;
    this.classList = makeClassList(this);
    this.dataset = makeDataset(this);
  }

  // -- Attribute ---------------------------------------------------------------
  getAttribute(n) { return this.attributes.has(n) ? this.attributes.get(n) : null; }
  setAttribute(n, v) { this.attributes.set(n, String(v)); }
  hasAttribute(n) { return this.attributes.has(n); }
  removeAttribute(n) { this.attributes.delete(n); }
  get className() { return this.getAttribute("class") || ""; }
  set className(v) { this.setAttribute("class", v); }
  get value() {
    if (this._value !== null) return this._value;
    if (this.localName === "select") {
      const opts = this.options;
      const sel = opts.find((o) => o.hasAttribute("selected")) || opts[0];
      return sel ? sel.value : "";
    }
    if (this.localName === "option") {
      return this.hasAttribute("value") ? this.getAttribute("value") : this.textContent;
    }
    return this.getAttribute("value") || "";
  }
  set value(v) { this._value = String(v); }
  get options() { return this.localName === "select" ? this.querySelectorAll("option") : []; }

  // -- Baum ----------------------------------------------------------------------
  get children() { return this.childNodes.filter((c) => c instanceof Element); }
  get firstElementChild() { return this.children[0] || null; }
  get innerHTML() { return this.childNodes.map((c) => c.outerHTML).join(""); }
  set innerHTML(html) {
    this.replaceChildren();
    parseInto(this, String(html ?? ""));
  }
  get outerHTML() {
    const attrs = [...this.attributes].map(([k, v]) => v === "" ? ` ${k}` : ` ${k}="${escAttr(v)}"`).join("");
    if (VOID.has(this.localName)) return `<${this.localName}${attrs}>`;
    return `<${this.localName}${attrs}>${this.innerHTML}</${this.localName}>`;
  }
  insertAdjacentHTML(pos, html) {
    const frag = new Element(this.ownerDocument, "template");
    parseInto(frag, String(html));
    const nodes = [...frag.childNodes];
    if (pos === "beforeend") nodes.forEach((n) => this.appendChild(n));
    else if (pos === "afterbegin") nodes.reverse().forEach((n) => this.insertBefore(n, this.firstChild));
    else if (pos === "beforebegin") nodes.forEach((n) => this.parentNode.insertBefore(n, this));
    else if (pos === "afterend") nodes.reverse().forEach((n) => this.parentNode.insertBefore(n, this.nextSibling));
  }

  // -- Selektoren ----------------------------------------------------------------
  matches(sel) { return parseSelectorList(sel).some((s) => matchComplex(this, s)); }
  closest(sel) {
    for (let n = this; n instanceof Element; n = n.parentNode) if (n.matches(sel)) return n;
    return null;
  }
  querySelectorAll(sel) {
    const list = parseSelectorList(sel);
    const out = [];
    walk(this, (el) => { if (list.some((s) => matchComplex(el, s))) out.push(el); });
    return out;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  getElementsByTagName(tag) { return this.querySelectorAll(tag); }

  // -- Layout-/Browser-Attrappen -------------------------------------------------
  getBoundingClientRect() {
    // Je Element gesetzt (_rect) oder per Dokument-Regel (document.rectFor,
    // z. B. „jede .tile ist 100 px hoch"), sonst 0 — es gibt kein Layout.
    const r = this._rect || this.ownerDocument?.rectFor?.(this);
    return { x: 0, y: 0, left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0, ...r };
  }
  scrollIntoView() {}
  focus() { this.ownerDocument.activeElement = this; }
  select() { /* Text markieren — im Stub nichts zu tun */ }
  blur() { if (this.ownerDocument.activeElement === this) this.ownerDocument.activeElement = null; }
  click() { this.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })); }
  setPointerCapture() {}
  releasePointerCapture() {}
  play() { this.paused = false; return Promise.resolve(); }
  pause() { this.paused = true; }
  // canPlayType (#71): Standard „maybe" wie ein Browser, der alles probiert;
  // Tests überschreiben Element.prototype.canPlayType für „kann nicht".
  canPlayType() { return "maybe"; }
}

for (const name of BOOL_ATTRS) {
  Object.defineProperty(Element.prototype, name, {
    get() { return this.hasAttribute(name); },
    set(v) { v ? this.setAttribute(name, "") : this.removeAttribute(name); },
  });
}
for (const name of STRING_ATTRS) {
  Object.defineProperty(Element.prototype, name, {
    get() { return this.getAttribute(name) || ""; },
    set(v) { this.setAttribute(name, v); },
  });
}

function makeStyle() {
  const style = {
    setProperty(k, v) { style[k] = v; },
    removeProperty(k) { delete style[k]; },
    getPropertyValue(k) { return style[k] || ""; },
  };
  return style;
}

function makeClassList(el) {
  const get = () => (el.getAttribute("class") || "").split(/\s+/).filter(Boolean);
  const set = (list) => el.setAttribute("class", list.join(" "));
  return {
    add(...names) { const l = get(); for (const n of names) if (!l.includes(n)) l.push(n); set(l); },
    remove(...names) { set(get().filter((c) => !names.includes(c))); },
    contains(n) { return get().includes(n); },
    toggle(n, force) {
      const has = get().includes(n);
      const want = force === undefined ? !has : !!force;
      if (want && !has) this.add(n);
      if (!want && has) this.remove(n);
      return want;
    },
  };
}

const toDataAttr = (k) => "data-" + k.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
function makeDataset(el) {
  return new Proxy({}, {
    get(_, k) { return typeof k === "string" ? el.getAttribute(toDataAttr(k)) ?? undefined : undefined; },
    set(_, k, v) { el.setAttribute(toDataAttr(k), v); return true; },
    deleteProperty(_, k) { el.removeAttribute(toDataAttr(k)); return true; },
    has(_, k) { return el.hasAttribute(toDataAttr(k)); },
  });
}

function walk(root, fn) {
  for (const c of root.childNodes) {
    if (c instanceof Element) { fn(c); walk(c, fn); }
  }
}

// -- Selektor-Engine (Teilmenge) ---------------------------------------------------
//
// Unterstützt: tag, #id, .klasse, [attr], [attr="wert"], :not(<einfach>),
// Nachfahren-Kombinator (Leerzeichen), Kind-Kombinator (>), Listen (Komma).

const selCache = new Map();
function parseSelectorList(sel) {
  if (selCache.has(sel)) return selCache.get(sel);
  const parts = splitTop(sel, ",").map((s) => parseComplex(s.trim()));
  selCache.set(sel, parts);
  return parts;
}

function splitTop(s, sep) {
  const out = [];
  let depth = 0, cur = "";
  for (const ch of s) {
    if (ch === "(" || ch === "[") depth++;
    if (ch === ")" || ch === "]") depth--;
    if (ch === sep && depth === 0) { out.push(cur); cur = ""; } else cur += ch;
  }
  out.push(cur);
  return out;
}

function parseComplex(s) {
  // Token: Compound-Selektoren und Kombinatoren, rechts nach links gespeichert.
  const tokens = [];
  let cur = "", depth = 0, i = 0;
  const flush = () => { if (cur.trim()) tokens.push({ compound: parseCompound(cur.trim()) }); cur = ""; };
  while (i < s.length) {
    const ch = s[i];
    if (ch === "(" || ch === "[") depth++;
    if (ch === ")" || ch === "]") depth--;
    if (depth === 0 && (ch === " " || ch === ">")) {
      flush();
      let comb = ch === ">" ? ">" : " ";
      while (i + 1 < s.length && (s[i + 1] === " " || s[i + 1] === ">")) { if (s[i + 1] === ">") comb = ">"; i++; }
      if (tokens.length) tokens.push({ comb });
    } else cur += ch;
    i++;
  }
  flush();
  return tokens;
}

function parseCompound(s) {
  const c = { tag: null, id: null, classes: [], attrs: [], not: [] };
  const re = /([a-zA-Z][\w-]*)|#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\]]*)))?\]|:not\(([^)]*)\)/g;
  let m;
  while ((m = re.exec(s))) {
    if (m[1]) c.tag = m[1].toLowerCase();
    else if (m[2]) c.id = m[2];
    else if (m[3]) c.classes.push(m[3]);
    else if (m[4]) c.attrs.push({ name: m[4], value: m[5] ?? m[6] ?? m[7] ?? null });
    else if (m[8] !== undefined) c.not.push(parseCompound(m[8]));
  }
  return c;
}

function matchCompound(el, c) {
  if (c.tag && el.localName !== c.tag) return false;
  if (c.id && el.getAttribute("id") !== c.id) return false;
  for (const k of c.classes) if (!el.classList.contains(k)) return false;
  for (const a of c.attrs) {
    if (!el.hasAttribute(a.name)) return false;
    if (a.value !== null && el.getAttribute(a.name) !== a.value) return false;
  }
  for (const n of c.not) if (matchCompound(el, n)) return false;
  return true;
}

function matchComplex(el, tokens) {
  // Rechts nach links: letzter Compound muss el treffen, davor Vorfahren.
  let idx = tokens.length - 1;
  if (!matchCompound(el, tokens[idx].compound)) return false;
  let node = el;
  idx--;
  while (idx >= 0) {
    const comb = tokens[idx].comb; idx--;
    const compound = tokens[idx].compound;
    if (comb === ">") {
      node = node.parentElement;
      if (!node || !matchCompound(node, compound)) return false;
    } else {
      node = node.parentElement;
      while (node && !matchCompound(node, compound)) node = node.parentElement;
      if (!node) return false;
    }
    idx--;
  }
  return true;
}

// -- HTML-Parser (Teilmenge) -------------------------------------------------------

function parseInto(root, html) {
  const doc = root.ownerDocument;
  const stack = [root];
  let i = 0;
  const top = () => stack[stack.length - 1];
  while (i < html.length) {
    if (html[i] !== "<") {
      const j = html.indexOf("<", i);
      const text = html.slice(i, j < 0 ? html.length : j);
      top().appendChild(new Text(doc, decodeEntities(text)));
      i = j < 0 ? html.length : j;
      continue;
    }
    if (html.startsWith("<!--", i)) {
      const j = html.indexOf("-->", i + 4);
      top().appendChild(new Comment(doc, html.slice(i + 4, j < 0 ? html.length : j)));
      i = j < 0 ? html.length : j + 3;
      continue;
    }
    if (html.startsWith("<!", i)) {                       // <!doctype …>
      const j = html.indexOf(">", i);
      i = j < 0 ? html.length : j + 1;
      continue;
    }
    if (html.startsWith("</", i)) {
      const j = html.indexOf(">", i);
      const name = html.slice(i + 2, j).trim().toLowerCase();
      for (let k = stack.length - 1; k > 0; k--) {
        if (stack[k].localName === name) { stack.length = k; break; }
      }
      i = j + 1;
      continue;
    }
    // Start-Tag
    const m = /^<([a-zA-Z][\w-]*)/.exec(html.slice(i));
    if (!m) { top().appendChild(new Text(doc, "<")); i++; continue; }
    const el = new Element(doc, m[1]);
    i += m[0].length;
    const attrRe = /\s*([^\s=\/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/y;
    for (;;) {
      attrRe.lastIndex = i;
      const a = attrRe.exec(html);
      if (!a || a[0].trim() === "") break;
      el.setAttribute(a[1], decodeEntities(a[2] ?? a[3] ?? a[4] ?? ""));
      i = attrRe.lastIndex;
    }
    while (i < html.length && /\s/.test(html[i])) i++;
    let selfClosing = false;
    if (html[i] === "/") { selfClosing = true; i++; }
    if (html[i] === ">") i++;
    top().appendChild(el);
    if (RAW_TEXT.has(el.localName)) {
      const end = html.indexOf(`</${el.localName}`, i);
      el.appendChild(new Text(doc, html.slice(i, end < 0 ? html.length : end)));
      i = end < 0 ? html.length : html.indexOf(">", end) + 1;
      continue;
    }
    if (!selfClosing && !VOID.has(el.localName)) stack.push(el);
  }
}

// -- Dokument ---------------------------------------------------------------------

export class Document extends Node {
  constructor(win) {
    super(null);
    this.ownerDocument = this;
    this.nodeType = 9;
    this._window = win;
    this.activeElement = null;
    this.rectFor = null;   // optionale Maß-Regel für getBoundingClientRect
    this.title = "";
    this.documentElement = new Element(this, "html");
    this.head = new Element(this, "head");
    this.body = new Element(this, "body");
    this.documentElement.appendChild(this.head);
    this.documentElement.appendChild(this.body);
    this.appendChild(this.documentElement);
  }
  _eventParent() { return this._window; }
  createElement(tag) { return new Element(this, tag); }
  createTextNode(s) { return new Text(this, String(s)); }
  createComment(s) { return new Comment(this, String(s)); }
  getElementById(id) {
    let found = null;
    walk(this, (el) => { if (!found && el.getAttribute("id") === id) found = el; });
    return found;
  }
  querySelectorAll(sel) { return Element.prototype.querySelectorAll.call(this, sel); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  /** Ganze Seite aus HTML aufbauen (Kopf + Rumpf werden ersetzt). */
  loadHtml(html) {
    const tmp = new Element(this, "template");
    parseInto(tmp, html);
    const htmlEl = tmp.querySelector("html");
    const head = tmp.querySelector("head");
    const body = tmp.querySelector("body");
    if (htmlEl) for (const [k, v] of htmlEl.attributes) this.documentElement.setAttribute(k, v);
    this.head.replaceChildren(...(head ? head.childNodes : []));
    this.body.replaceChildren(...(body ? body.childNodes : tmp.childNodes));
  }
}
