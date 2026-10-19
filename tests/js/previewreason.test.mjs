// previewreason.test.mjs — gerechnete Ansicht ohne Bild (ADR 0104): Scheitert
// ein <img> auf /api/preview, fragt der Fehlerfang einmal nach und zeigt den
// Grund des Servers (JXR ohne Windows, PSD ohne Composite) statt nur
// „Keine Vorschau verfügbar". Andere Bilder bleiben beim allgemeinen Hinweis.

import { test } from "node:test";
import assert from "node:assert/strict";
import { loadShell, flush, hashOf } from "./harness.mjs";
import { mockApi } from "./apimock.mjs";
import { DomEvent } from "./dom.mjs";

const { wireMediaFallback, displayUrl } = await import("../../src/feral/web/static/js/api.js");
const { STRINGS } = await import("../../src/feral/web/static/js/strings.js");

function stage(src) {
  const scope = document.createElement("div");
  scope.innerHTML = `<img src="${src}" alt="">`;
  document.body.appendChild(scope);
  wireMediaFallback(scope, STRINGS.noPreview);
  return scope;
}

test("JXR ohne Windows: der Hinweis nennt den Grund des Servers", async () => {
  loadShell();
  const jxr = { file_hash: hashOf(1), container: "jxr", media_kind: "image" };
  assert.equal(displayUrl(jxr), `/api/preview/${jxr.file_hash}`);
  mockApi.get(displayUrl(jxr), () => mockApi.status(404, { detail: {
    key: "errPreviewFailed", params: { reason: { key: "thumbJxrWindowsOnly" } } } }));

  const scope = stage(displayUrl(jxr));
  scope.querySelector("img").dispatchEvent(new DomEvent("error"));
  assert.equal(scope.querySelector(".nopreview").textContent, STRINGS.noPreview);   // sofort
  await flush();
  const text = scope.querySelector(".nopreview").textContent;
  assert.ok(text.includes(STRINGS.server.thumbJxrWindowsOnly), text);
});

test("Original ohne gerechnete Ansicht: kein Nachfragen, allgemeiner Hinweis", async () => {
  loadShell();
  const scope = stage(`/api/media/${hashOf(2)}`);
  scope.querySelector("img").dispatchEvent(new DomEvent("error"));
  await flush();
  assert.equal(scope.querySelector(".nopreview").textContent, STRINGS.noPreview);
  assert.equal(mockApi.calls.length, 0);
});
