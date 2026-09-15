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

### Reading

**Zero-shot Depth Anything V2 has essentially no relationship with true height on nadir
satellite imagery.** Mean correlation +0.037 over three tiles is indistinguishable from
zero, and the sign is not even stable — it swings from −0.27 to +0.21 between tiles of the
same city.

That instability is the important part. A consistent negative correlation would indicate a
sign-convention bug on our side. A correlation that changes sign tile to tile cannot be a
convention error; it is the model producing something unrelated to height.

### What it is not

A plausible alternative explanation is that the model reports albedo — bright roofs read as
near, dark asphalt as far — which on this leaf-off winter imagery would anti-correlate with
height, since the tall canopy is dark and the bare ground is bright. That was tested and
**rejected**:

| Tile | r(pred, AGL) | r(pred, brightness) | r(brightness, AGL) |
|---|---|---|---|
| DC_02_26 | −0.2677 | +0.1705 | −0.2028 |
| DC_04_23 | +0.2126 | −0.0931 | +0.0461 |
| DC_04_27 | +0.1662 | −0.0202 | −0.1633 |

Correlation with brightness is as weak as correlation with height. The model is not
substituting albedo for depth; it is not tracking anything measurable in this domain.

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
| Building-only RMSE | Possible now that the class legend is resolved; harness not built |
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
