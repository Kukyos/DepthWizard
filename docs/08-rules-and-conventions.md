# Rules and conventions

The eight hard rules, why each exists, and how we work. Violating a hard rule needs a
decision logged in `06-decisions.md`, not a judgement call in the moment.

---

## The eight hard rules

### 1. Never report a metric the eval harness did not produce

Correctness here is invisible — a height map can be entirely wrong and look perfectly
plausible. So a number that did not come from the harness is not evidence, it is a feeling.

*In practice:* every figure in a doc, a slide or a README traces to a harness run.
`12-eval-results.md` is generated and never hand-edited. If we have not measured it, the
doc says `NOT MEASURED`, not an estimate.

### 2. Relative and absolute are never visually confused

Without a CRS and a pixel size, metres are unknowable. Printing a confident "14 m" for a
plain JPG is fabrication.

*In practice:* units come from provenance, never from a guess. A non-georeferenced input
shows **no metre value anywhere** — not in the viewer, not in a tooltip, not in an export,
not in a log line a judge might see. The viewer carries an always-visible units badge
reading `metres (absolute)` or `relative (no scale)`. A regression test drops in a PNG and
greps the entire output surface for metre labelling.

### 3. Every DSM carries provenance

A height raster with no record of how it was made cannot be checked, reproduced or trusted,
and six weeks later nobody remembers which checkpoint made it.

*Minimum record:* backbone identifier and weights hash, calibration method, anchor sources
and counts, input GSD, output GSD, CRS, confidence band, pipeline git commit, timestamp.
A DSM written without it is a bug, not a shortcut.

### 4. Reference height data is never touched at inference

We are evaluated on imagery we have never seen, from a different country and sensor.
Anything that peeks at ground truth at inference time produces a number that will not
survive contact with the evaluation.

*In practice:* the split is declared once, before training, in code. It is never re-split to
improve a number. The harness runs the pipeline exactly as a user would, with no privileged
access. GCPs supplied *by a user* are an input, not reference data — but GCPs drawn from the
evaluation reference are leakage.

### 5. Georeferencing round-trips exactly

A DSM in the wrong place is worse than no DSM: it looks authoritative and is unusable. A
half-pixel transform drift also shows up instantly as texture slide in the viewer, which is
the first thing the visualization criteria name.

*In practice:* CRS and affine transform in == out, bit-identical, proven by
`server/tests/test_raster.py`. Not by opening QGIS and looking.

### 6. The viewer runs fully offline

A demo that needs network is a demo that fails in a hall with bad wifi. The brief also asks
for standalone deployment.

*In practice:* no CDN, no tile server, no font fetch, no telemetry. Dependencies are bundled.
Checked by running with the adapter disabled.

### 7. Refuse rather than fake

Below a certain GSD, a building spans under two pixels and its height is **not present in
the data**. A model will still emit a confident number. That number is fabrication.

*In practice:* below the GSD floor in `config.py`, output terrain only and flag
`objects_not_resolvable`, visibly in the UI. The floor is derived from a measured
degradation sweep, not chosen. Refusing is a feature to demo, not an embarrassment.

### 8. Forest is reported honestly

Over canopy, prediction and reference measure different surfaces: LiDAR reaches through
gaps toward ground, optical RGB sees treetops, SRTM sits at an uncertain level inside the
canopy. A forest error figure therefore mixes model error with a disagreement about what
"height" means.

*In practice:* forest is scored separately with the reason stated, never averaged into the
headline. Where we have no forested data at all, the row reads `NO DATA`.

---

## How we work

- **Ask before guessing.** Batch questions into one round, then build uninterrupted. A
  logged default in `06-decisions.md` is not a guess — take it.
- **Build whole things.** A feature means the module, its test, the server route, the viewer
  surface and the doc update — not a stub to expand later.
- **Correctness over speed.** This problem punishes plausible-looking wrongness more than
  slowness.
- **Never invent domain data a judge can check.** GSDs, class legends, EPSG codes, sun
  geometry constants, published benchmark numbers. Every such value carries provenance;
  anything unsourced is `PLACEHOLDER` in the data and listed in `10-unsourced.md` —
  structurally present, visibly unsourced.
- **Keep the ledgers current in the same pass.** When you take a shortcut, append to
  `11-deferred.md` then, not in a cleanup at the end. "Later" otherwise means never.

## Docs are the default output format

Prefer writing it down as `.md` in `docs/` over explaining it in conversation. Docs are
written as plain project documents for a teammate or a judge — never as instructions to a
tool.

Two ledgers are live documents:

| File | Holds |
|---|---|
| `10-unsourced.md` | Every value we could not source, and where the real one comes from |
| `11-deferred.md` | Every knowingly incomplete thing, what it blocks, what it would take |

One file is generated:

| File | Rule |
|---|---|
| `12-eval-results.md` | Written by `eval/run_eval.py`. **Never hand-edited.** |

## Repo hygiene

This repository is public and goes into an SIH presentation.

- **No AI attribution anywhere** — not in commits, code comments, docs or the README.
- Commits are authored by the project owner's own git identity, with plain factual messages.
- Secrets live in `.env`, which is gitignored. `.env.example` is committed with empty values.
- **Nothing under `data/` is ever committed.** GAMUS alone is 80 GB. Weights, checkpoints and
  generated rasters are gitignored too.

## Code conventions

### Python

- Units in the name when ambiguity is possible: `height_m`, `gsd_m`, `azimuth_deg`. A bare
  `height` invites exactly the bug this project is most vulnerable to.
- Say which surface: `dsm`, `dtm`, `ndsm`. Never a bare `elevation`.
- Arrays carry their dtype intent — heights are `float32`, classes are integer-valued.
- No silent fallbacks. If the GPU is missing, or SRTM is unavailable, or a shadow is
  unusable, that is recorded in provenance and surfaced — never quietly substituted.
- Nodata is explicit. GAMUS has no nodata sentinel and clamps AGL at −5.0 m; do not assume a
  sentinel exists, and do not treat the clamp as missing data.
- Configuration in `config.py`, not scattered constants. The training script must run
  unchanged locally and on the cloud GPU (D4), which forbids machine-specific paths.

### TypeScript

- Plain TypeScript and Babylon. No React, no Tailwind (D3).
- Height values crossing the API boundary carry their unit and provenance as data, so the UI
  cannot accidentally label a relative value in metres.
- Vertical exaggeration is an explicit, labelled control. Applying it silently would make
  every height on screen a lie.

### Tests

One runnable check behind any non-trivial logic, via `run.ps1 -Test`. The non-negotiable one
is the CRS/transform round-trip: every number the project reports sits on top of it.
