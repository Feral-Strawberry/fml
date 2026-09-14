// admin/pages/logs.js — Seite „Logs" (ADR 0074): beide Serverlog-Dateien
// sofort sichtbar, nebeneinander auf breit, gestapelt auf schmal. Je Datei
// Name, Größe, Zeilenzahl 100/500/2000, Auffrischen und der Schalter „nur
// WARNING und höher" (Filter serverseitig, /api/admin/log?level=). Monospace,
// neueste Zeile unten und angescrollt. Seitenoptionen (Kopf, im Browser
// gemerkt): „Zeilenumbruch" (Standard an — erster Test 2026-09-12: selbst
// auf 4K musste man seitlich scrollen) und „untereinander" statt
// nebeneinander. Nach jeder fertigen Aufgabe frischen beide Fenster auf.

import { STRINGS } from "../../strings.js";
import { getAdminLog } from "../../api.js";
import { esc, fmtBytes } from "../util.js";

export const id = "logs";
export const icon = '<svg viewBox="0 0 24 24"><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/></svg>';
export const title = () => STRINGS.adminLogs;
export const subtitle = () => STRINGS.subLogs;

const FILES = [["web", "fml-web.log"], ["worker", "fml-worker.log"]];
const LINE_CHOICES = [100, 500, 2000];
const WRAP_KEY = "feral-admin-logwrap";
const STACK_KEY = "feral-admin-logstack";
let root = null;

const pref = (key, fallback) => {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v === "1"; } catch { return fallback; }
};
const remember = (key, on) => { try { localStorage.setItem(key, on ? "1" : "0"); } catch { /* egal */ } };

function applyOptions() {
  const wrap = root.querySelector("#logWrap").checked;
  const stack = root.querySelector("#logStack").checked;
  root.querySelector(".row").className = stack ? "row" : "row c2";
  for (const pre of root.querySelectorAll("[data-pre]")) pre.classList.toggle("wrap", wrap);
}

export function render(target) {
  root = target;
  root.innerHTML = `
    <div class="logopts" style="margin-bottom:12px">
      <label><input type="checkbox" id="logWrap" ${pref(WRAP_KEY, true) ? "checked" : ""}> ${STRINGS.logWrap}</label>
      <label><input type="checkbox" id="logStack" ${pref(STACK_KEY, false) ? "checked" : ""}> ${STRINGS.logStack}</label>
    </div>
    <div class="row c2">${FILES.map(([key, name]) => `
    <div class="card logcard" data-file="${key}">
      <div class="chead">
        <span class="mlabel">${name}</span>
        <span class="right" data-size></span>
        <div class="logctl">
          <select data-lines title="${STRINGS.logLines}">
            ${LINE_CHOICES.map((n) => `<option value="${n}">${n} ${STRINGS.logLines}</option>`).join("")}
          </select>
          <label><input type="checkbox" data-warn> ${STRINGS.logWarnOnly}</label>
          <button type="button" data-refresh>${STRINGS.logRefresh}</button>
        </div>
      </div>
      <pre class="logpre empty" data-pre>${STRINGS.logLoading}</pre>
    </div>`).join("")}</div>`;
  applyOptions();
  root.addEventListener("change", (e) => {
    if (e.target.matches("#logWrap, #logStack")) {
      remember(WRAP_KEY, root.querySelector("#logWrap").checked);
      remember(STACK_KEY, root.querySelector("#logStack").checked);
      applyOptions();
      return;
    }
    const card = e.target.closest(".logcard");
    if (card && (e.target.matches("[data-lines]") || e.target.matches("[data-warn]"))) loadFile(card);
  });
  root.addEventListener("click", (e) => {
    const card = e.target.closest(".logcard");
    if (card && e.target.closest("[data-refresh]")) loadFile(card);
  });
}

export async function load() {
  await Promise.all([...root.querySelectorAll(".logcard")].map(loadFile));
}

export function onTaskFinished() { if (root && root.isConnected) load(); }

/** Zeilen nach Stufe einfärben (WARNING gelb, ERROR/CRITICAL rot). */
export function lineHtml(line) {
  const m = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} (\w+)\s/.exec(line);
  const level = m ? m[1] : "";
  const cls = level === "WARNING" ? " warn" : (level === "ERROR" || level === "CRITICAL") ? " err" : "";
  return `<span class="logline${cls}">${esc(line)}</span>`;
}

async function loadFile(card) {
  const pre = card.querySelector("[data-pre]");
  const lines = parseInt(card.querySelector("[data-lines]").value, 10) || 100;
  const warn = card.querySelector("[data-warn]").checked;
  try {
    const d = await getAdminLog(lines, { level: warn ? "warning" : null, file: card.dataset.file });
    const f = d.files[0];
    card.querySelector("[data-size]").textContent = f.bytes ? fmtBytes(f.bytes) : STRINGS.adminLogEmpty;
    if (!f.lines.length) {
      pre.className = "logpre empty" + (root.querySelector("#logWrap").checked ? " wrap" : "");
      pre.textContent = warn ? STRINGS.logNoMatches : STRINGS.adminLogEmpty;
    } else {
      pre.className = "logpre" + (root.querySelector("#logWrap").checked ? " wrap" : "");
      pre.innerHTML = f.lines.map(lineHtml).join("\n");
    }
    pre.scrollTop = pre.scrollHeight;
  } catch (err) {
    pre.className = "logpre empty";
    pre.textContent = err.message;
  }
}
