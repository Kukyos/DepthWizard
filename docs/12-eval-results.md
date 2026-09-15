# Eval results

> **Interim, hand-written — 2026-09-15.** The eval harness does not exist yet, so this file
> is not yet machine-generated. Once `server/eval/run_eval.py` is built it overwrites this
> file and it is never hand-edited again (hard rule 1). Everything below was produced by
> `depthwizard.dsm --reference` and the diagnostic in the notes, on a **3-tile sample**.
> Treat it as a first reading, not a result.

---

## The Phase 1 zero-shot baseline

**What was run.** Depth Anything V2 (Base, `depth-anything/Depth-Anything-V2-Base-hf`),
frozen, zero-shot, no calibration and no fine-tuning, on GAMUS validation tiles. Scored
against each tile's LiDAR-derived AGL reference.

**Why scale-free metrics only.** The prediction is relative and unitless; no anchor has been
built yet, so absolute RMSE against metric ground truth is undefined. Correlation and
scale-invariant error are the measures that *are* defined, and they answer the Phase 1
question — is the shape right — rather than the Phase 2 question.

| Tile | r(pred, AGL) | SI-RMSE | SI-MAE | Reference range |
|---|---|---|---|---|
| DC_02_26 | **−0.2677** | 9.43 m | 7.64 m | 0.0 – 41.5 m |
| DC_04_23 | **+0.2126** | — | — | — |
| DC_04_27 | **+0.1662** | — | — | — |
| **mean** | **+0.037** | | | |

Pooled, that reads as no relationship. Stratified, it is not — see below.

### Stratified by land cover — where the signal actually is

The pooled figure hides the result. Restricting the correlation to each class, using the
legend resolved in U-01:

| Scope | mean r over 3 tiles | What it says |
|---|---|---|
| **Everything** | **+0.037** | Looks like the model is useless |
| **Building** | **+0.189** | Weak but consistently positive on all three tiles |
| **Tree** | **−0.056** | No relationship at all |
| **Everything except trees** | **+0.210** | ~5x the pooled figure |

Per tile, so the consistency is visible rather than asserted:

| Tile | all | building | tree | non-tree | tree share |
|---|---|---|---|---|---|
| DC_02_26 | −0.268 | +0.054 | −0.448 | +0.177 | 34.9% |
| DC_04_23 | +0.213 | +0.281 | +0.139 | +0.147 | 83.9% |
| DC_04_27 | +0.166 | +0.234 | +0.141 | +0.306 | 27.4% |

**Building correlation is positive on every tile. Tree correlation is not.** The pooled
+0.037 is an average of a weak real signal over built surfaces and a failure over canopy —
and since canopy is 27–84% of these scenes, the failure dominates the pooled number.

This is visible directly in `out/baseline_comparison.png`: the predicted panel picks out
building footprints as raised rectangles, in roughly the right places. The reference panel
is dominated by tree crowns at ~17 m that the prediction leaves flat. The model is finding
structures and missing vegetation.

### Why vegetation fails here

The imagery is **leaf-off winter** — bare deciduous canopy, brown rather than green, with
ground texture showing through it. A 17 m tree that looks like a patch of twigs over bare
earth offers nothing a depth model trained on summer street photography would recognise as
an elevated surface. Whether this persists on leaf-on or evergreen imagery is untested and
matters: it decides whether the forest problem is seasonal or fundamental.

### It is not a sign-convention bug

A consistent negative correlation would suggest we had inverted the model's output. Two
findings rule that out: the pooled sign **swings between tiles of the same city**
(−0.27 to +0.21), and building correlation is **positive on all three tiles** while tree
correlation is not. An inverted convention would flip both together.

### It is not albedo

The model might simply be reporting brightness — bright roofs as near, dark asphalt as far —
which on leaf-off imagery would anti-correlate with height. Tested and rejected:

| Tile | r(pred, AGL) | r(pred, brightness) | r(brightness, AGL) |
|---|---|---|---|
| DC_02_26 | −0.2677 | +0.1705 | −0.2028 |
| DC_04_23 | +0.2126 | −0.0931 | +0.0461 |
| DC_04_27 | +0.1662 | −0.0202 | −0.1633 |

Correlation with brightness is as weak as correlation with height.

### What this changes about the plan

1. **Hard rule 8 now has evidence behind it.** Scoring forest separately was adopted on
   principle; this is the first measurement showing that pooling canopy with built surfaces
   destroys an otherwise readable signal.
2. **Building-only metrics are the honest headline** for built-up scenes, and the brief's
   disaster-management framing is about structures.
3. **Fine-tuning has something to build on.** A backbone at r ≈ 0 everywhere would be a
   weak starting point; one already at +0.19 on buildings is being asked to sharpen an
   existing signal rather than create one.

### Why this number is kept

This is the baseline the project exists to beat, and it is evidence for the brief's own
premise — that foundational monocular models "face domain gaps" on remote sensing. The
headline claim at submission is the **delta** between this row and the fine-tuned pipeline.
An unmeasured baseline would make that claim unsupportable.

It is also visible without any metrics: in the viewer, buildings reconstruct as smeared
mounds rather than flat-roofed boxes.

---

## Not yet measured

Listed so absence is not mistaken for a pending good result.

| Metric | Status |
|---|---|
| Absolute RMSE / MAE in metres | Undefined until Phase 2 calibration exists (D-05) |
| Per-landscape stratification | Harness not built; and no hilly/forested data exists at all (D-02) |
| Per-GSD-band accuracy | GAMUS is single-GSD; the degradation sweep is Phase 3 |
| Building-only RMSE in metres | Needs calibration (D-05). Building *correlation* is measured above |
| Leave-one-city-out split | Harness not built. Only DC tiles have been touched so far |
| Steady-state inference time | 61 s for the first tile **including model load** — not a throughput figure |
| Viewer frame rate | Not instrumented |

---

## Provenance

| | |
|---|---|
| Backbone | `depth-anything/Depth-Anything-V2-Base-hf`, frozen, zero-shot |
| Device | RTX 4060 Laptop, torch 2.14.0+cu130 |
| Data | GAMUS val split, 3 tiles (DC_02_26, DC_04_23, DC_04_27), 0.33 m GSD, 1024² |
| Reference | GAMUS `_AGL` layer, LiDAR-derived, metres above ground |
| Calibration | none |
| Sample size | **3 tiles.** Far too small to be a finding. |

**The sample is the main caveat.** Three tiles from one city, chosen only because they were
the first to finish downloading. The direction of the result is clear enough to act on, but
the numbers will move once the harness runs over the full held-out split.
