/**
 * Viewer checks that do not need a browser.
 *
 * Run by `.\run.ps1 -Test`, after `tsc --noEmit`. These guard the one viewer-side rule that
 * is easy to break by accident and expensive to notice: hard rule 2, that a relative scene
 * never presents a value labelled in metres (docs/08-rules-and-conventions.md).
 */

import { readFileSync, readdirSync } from "node:fs";
import assert from "node:assert/strict";

/** Every .ts under src/, so these checks keep covering the code as Phase 4 splits main.ts
 *  into terrain / cameras / probe / overlays / validate / ui. Scanning a fixed filename
 *  would let the offline rule quietly stop being enforced the moment a new module appears. */
function sources(dir = new URL("./src/", import.meta.url)) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) out.push(...sources(new URL(`${entry.name}/`, dir)));
    else if (entry.name.endsWith(".ts")) {
      out.push({ name: entry.name, text: readFileSync(new URL(entry.name, dir), "utf8") });
    }
  }
  return out;
}

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

const files = sources();
const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
/** All TypeScript sources concatenated, for checks that ask "does this exist anywhere". */
const all = files.map((f) => f.text).join("\n");
/** The one module that must define the units contract. */
const main = files.find((f) => f.name === "main.ts")?.text ?? "";

check("the units badge exists in the document", () => {
  assert.match(html, /id="units-label"/, "no units badge element");
});

check("the scene starts in the relative state, not metres", () => {
  // Metres must be earned from a CRS. If the fallback manifest ever defaulted to
  // "metres_absolute", every non-georeferenced scene would be mislabelled — the exact
  // failure hard rule 2 exists to prevent.
  assert.match(html, /relative/i, "the badge does not default to relative");
  const init = all.match(/const manifest: SceneManifest =[\s\S]*?\n  \};/);
  assert.ok(init, "no manifest initialiser found");
  assert.match(init[0], /units:\s*"relative_unitless"/, "fallback manifest is not relative");
  assert.doesNotMatch(init[0], /units:\s*"metres_absolute"/, "fallback claims metres");
});

check("the probe reports stored heights, not exaggerated ones", () => {
  // Vertical exaggeration stretches the mesh for legibility. If the probe read the mesh
  // value directly, every reported height would be wrong by that factor, invisibly.
  if (!/exaggeration/.test(all)) return;          // no exaggeration in play yet
  assert.match(all, /\/\s*exaggeration/, "probe does not divide out the exaggeration");
});

check("height formatting is funnelled through one function", () => {
  // If a second place formats heights, the rule has to be enforced twice and eventually
  // will not be.
  const defs = all.match(/function formatHeight/g) ?? [];
  assert.equal(defs.length, 1, `expected exactly one formatHeight, found ${defs.length}`);
});

check("formatHeight refuses metres for a relative scene", () => {
  const body = all.match(/function formatHeight[\s\S]*?\n\}/);
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
  assert.match(all, /type Units =\s*"metres_absolute"\s*\|\s*"relative_unitless"/);
});

check("no network calls — the viewer is offline by design", () => {
  // Hard rule 6. A CDN font or an analytics beacon would fail in a hall with bad wifi.
  const sourcesToScan = [{ name: "index.html", text: html }, ...files];
  for (const { name, text } of sourcesToScan) {
    // Doc comments legitimately cite URLs, so comments are excluded -- but carefully.
    // Stripping "//" to end-of-line would also eat the "//" in "https://", which silently
    // defeats this entire check. So: remove block comments, then drop whole lines that
    // are comments, rather than trimming trailing ones.
    const code = text
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/<!--[\s\S]*?-->/g, "")
      .split("\n")
      .filter((line) => !/^\s*(\/\/|\*)/.test(line))
      .join("\n");
    assert.doesNotMatch(
      code,
      /https?:\/\/(?!localhost|127\.0\.0\.1)/,
      `external URL in ${name}`,
    );
  }
});

console.log("");
if (failures > 0) {
  console.log(`${failures} viewer check(s) failed`);
  process.exit(1);
}
console.log("viewer checks passed");
