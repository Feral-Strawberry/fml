// dom.test.mjs — Selbsttest des DOM-Stubs (ADR 0064): die Teilmenge, auf
// die sich die Modul-Tests verlassen, muss sich wie der Browser verhalten.

import { test } from "node:test";
import assert from "node:assert/strict";
import { loadShell, keydown, click } from "./harness.mjs";

test("innerHTML-Parser + Selektoren", () => {
  loadShell();
  const box = document.createElement("div");
  box.innerHTML = `
    <div class="pickbox"><span id="t" class="a b" data-path="/x&amp;y">Hi &amp; ho</span>
      <button type="button" data-zoom="fit" hidden>Anpassen</button><img alt="">
      <select id="s"><option value="k" selected>K</option><option value="v">V</option></select>
    </div>`;
  document.body.appendChild(box);
  assert.equal(document.getElementById("t").textContent, "Hi & ho");
  assert.equal(document.getElementById("t").dataset.path, "/x&y");
  assert.ok(box.querySelector(".pickbox > span.a.b"));
  assert.ok(box.querySelector("button[data-zoom]").hidden);
  assert.equal(box.querySelector("button[data-zoom=\"fit\"]").textContent, "Anpassen");
  assert.equal(box.querySelectorAll(".pickbox:not([hidden])").length, 1);
  assert.equal(box.querySelectorAll("input, textarea, select").length, 1);
  assert.equal(document.getElementById("s").value, "k");
  assert.equal(document.getElementById("s").options.length, 2);
  assert.ok(box.querySelector("img").matches("img"));
  assert.equal(box.querySelector("#t").closest(".pickbox"), box.firstElementChild);
  // Serialisierung ist rundlauffähig.
  assert.ok(box.innerHTML.includes('data-path="/x&amp;y"'));
});

test("Events: Capture vor Target vor Bubble, stopPropagation, once", () => {
  loadShell();
  const seen = [];
  const btn = document.createElement("button");
  document.body.appendChild(btn);
  document.addEventListener("keydown", () => seen.push("doc-capture"), true);
  document.addEventListener("keydown", () => seen.push("doc-bubble"));
  btn.addEventListener("keydown", () => seen.push("target"));
  keydown("Escape", { target: btn });
  assert.deepEqual(seen, ["doc-capture", "target", "doc-bubble"]);

  seen.length = 0;
  const stopper = (e) => { seen.push("stop"); e.stopPropagation(); };
  document.addEventListener("keydown", stopper, true);
  keydown("Escape", { target: btn });
  assert.deepEqual(seen, ["doc-capture", "stop"]);
  document.removeEventListener("keydown", stopper, true);
  assert.equal(document.listenerCount("keydown", true), 1);

  seen.length = 0;
  btn.addEventListener("click", () => seen.push("once"), { once: true });
  click(btn); click(btn);
  assert.deepEqual(seen, ["once"]);
  assert.equal(click(btn).defaultPrevented, false);
});

test("Baum: insertBefore/children/replaceWith/isConnected, Shell-IDs", () => {
  loadShell();
  for (const id of ["loupe", "single", "rankings", "gridwrap", "grid", "q", "panel"]) {
    assert.ok(document.getElementById(id), `#${id} fehlt in index.html`);
  }
  assert.ok(document.getElementById("loupe").hidden);
  const grid = document.getElementById("grid");
  const a = document.createElement("div"), b = document.createElement("div");
  grid.appendChild(b);
  grid.insertBefore(a, grid.children[0] ?? null);
  assert.deepEqual(grid.children, [a, b]);
  assert.ok(a.isConnected);
  const marker = document.createComment("home");
  a.replaceWith(marker);
  assert.ok(!a.isConnected && grid.childNodes[0] === marker);
  marker.replaceWith(a);
  assert.equal(grid.children[0], a);
  a.dataset.hash = "abc";
  assert.equal(a.getAttribute("data-hash"), "abc");
  delete a.dataset.hash;
  assert.equal(a.dataset.hash, undefined);
  a.classList.toggle("selected", true);
  assert.ok(a.matches(".selected[data-hash]") === false && a.matches(".selected"));
});
