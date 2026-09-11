/**
 * Viewer checks that do not need a browser.
 *
 * Run by `.\run.ps1 -Test`, after `tsc --noEmit`. These guard the one viewer-side rule that
 * is easy to break by accident and expensive to notice: hard rule 2, that a relative scene
 * never presents a value labelled in metres (docs/08-rules-and-conventions.md).
 */

import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

let failures = 0;

function check(name, fn) {
  try {
    fn();
    console.log(`  ok    ${name}`);
  } catch (error) {
    console.log(`  FAIL  ${name}\n        ${error.message}`);
    failures++;
  }
}

const main = readFileSync(new URL("./src/main.ts", import.meta.url), "utf8");
const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");

check("the units badge exists in the document", () => {
  assert.match(html, /id="units-label"/, "no units badge element");
});

check("the scene starts in the relative state, not metres", () => {
  // Metres must be earned from a CRS. A default of "absolute" would mislabel every
  // non-georeferenced scene, which is the exact failure hard rule 2 guards against.
  assert.match(html, /relative/i, "the badge does not default to relative");
  const init = main.match(/const manifest: SceneManifest = \{[\s\S]*?\}/);
  assert.ok(init, "no manifest initialiser found");
  assert.match(init[0], /units:\s*"relative_unitless"/, "manifest does not default to relative");
});

check("height formatting is funnelled through one function", () => {
  // If a second place formats heights, the rule has to be enforced twice and eventually
  // will not be.
  const defs = main.match(/function formatHeight/g) ?? [];
  assert.equal(defs.length, 1, `expected exactly one formatHeight, found ${defs.length}`);
});

check("formatHeight refuses metres for a relative scene", () => {
  const body = main.match(/function formatHeight[\s\S]*?\n\}/);
  assert.ok(body, "formatHeight not found");
  const guardIndex = body[0].indexOf('!== "metres_absolute"');
  const metreIndex = body[0].indexOf("} m");
  assert.ok(guardIndex > -1, "no guard on units in formatHeight");
  assert.ok(metreIndex > -1, "formatHeight never emits a metre label at all");
  assert.ok(
    guardIndex < metreIndex,
    "the relative guard must come before any metre-labelled return",
  );
});

check("units is a string union, never a boolean", () => {
  // A boolean makes "unset" read as false, and false would read as relative only by luck.
  assert.match(main, /type Units =\s*"metres_absolute"\s*\|\s*"relative_unitless"/);
});

check("no network calls — the viewer is offline by design", () => {
  // Hard rule 6. A CDN font or an analytics beacon would fail in a hall with bad wifi.
  for (const source of [html, main]) {
    assert.doesNotMatch(source, /https?:\/\/(?!localhost|127\.0\.0\.1)/, "external URL found");
  }
});

console.log("");
if (failures > 0) {
  console.log(`${failures} viewer check(s) failed`);
  process.exit(1);
}
console.log("viewer checks passed");
