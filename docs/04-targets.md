# Targets, metrics and the eval harness

The brief sets no numeric thresholds. It names the metrics — RMSE, MAE, correlation — and
demands stability across four landscape types. So we set our own targets and then prove
them.

**Nothing in this file is a measured result.** Measured results live in
`13-eval-results.md`, written by the harness. This file says what we will measure and what
would count as good. Hard rule 1.

---

## Why the harness comes before the model

Correctness here is **invisible**. A height map can be completely wrong and look entirely
plausible — smooth, detailed, buildings in the right places, every value off by 40%. Unlike
a UI bug, nothing on screen tells you. A 3D flythrough of a wrong DSM is just as pretty as
a flythrough of a right one.

This is the single biggest technical risk in the project, and it is why Phase 1 builds the
measuring tool before the thing it measures. The same reasoning that drove PS 26047's
build order.

Corollary: the **zero-shot baseline is a deliverable**, not a throwaway. The number that
makes our work legible is the *delta* between an off-the-shelf depth model and our
pipeline. Measure it first, keep it, put it on a slide.

---

## The metrics

### Primary — asked for by name

| Metric | Definition | Units | Reads as |
|---|---|---|---|
| **RMSE** | `sqrt(mean((pred − ref)²))` | m | Typical error, punishing large mistakes |
| **MAE** | `mean(|pred − ref|)` | m | Typical error, all mistakes weighted equally |
| **Correlation** | Pearson r between pred and ref | — | Is the *shape* right, even if the scale is off |

RMSE and MAE together are diagnostic: RMSE ≫ MAE means a few large outliers; RMSE ≈ MAE
means uniformly distributed error. Report both, and report the gap.

### Secondary — ours, because the primaries hide things

| Metric | Why it earns its place |
|---|---|
| **Bias** — `mean(pred − ref)` | Separates a constant offset (a calibration bug, fixable) from scatter (a model limit). A 5 m bias and 5 m scatter are the same RMSE and completely different problems. |
| **Building-only RMSE** | Most pixels in any scene are ground at ~0 m AGL. A model predicting zero everywhere scores a deceptively good overall RMSE. Masking to buildings is the honest test of whether heights are recovered at all. |
| **δ1 threshold accuracy** | Fraction of pixels within a relative tolerance. Standard in depth literature, so it makes our numbers comparable to published work. |
| **Slope error** | The criteria name slope analysis. A DSM can have good absolute heights and unusable gradients if it is noisy. |
| **Edge localisation** | Do building footprints land in the right place? Blurry 3 m-wide roof edges look terrible in the viewer even at good RMSE — this connects the accuracy half to the visualization half. |
| **Scale-invariant RMSE** | RMSE after the optimal global scale+shift is removed. Separates "the shape is wrong" from "only the calibration is wrong", which is exactly the distinction the brief's central challenge is about. |

### Always reported with a metric

A bare number is not a result. Every row in `13-eval-results.md` carries: pixel count, the
split it came from, the landscape class, the GSD band, and the calibration method.

---

## Stratification — required, not optional

> *"performance stability across urban, sparse, hilly, and forested landscapes"*

Every primary metric is reported **per landscape class**, never only pooled. A single
average is not an answer to the question the brief asks.

| Class | What it is | What we expect to be hard |
|---|---|---|
| **Urban** | Dense buildings, sharp height discontinuities | Occlusion, overlapping shadows in street canyons |
| **Sparse** | Scattered structures, mostly open ground | Little context; the model has few cues |
| **Hilly** | Significant terrain relief | Separating terrain from objects; SRTM resampling error dominates |
| **Forested** | Canopy cover | **A definitional mismatch, not just difficulty** — see below |

> **The data problem.** The recommended dataset's HF mirror is three flat US cities. It
> contains no hilly and no forested terrain. We cannot report G3-satisfying numbers for half
> these classes without supplementary data. This is the largest open risk in the project and
> it is tracked in `11-deferred.md`. Until it is resolved, those rows read
> `NO DATA — see 11-deferred.md`, never an estimate.

### Forest is scored separately, and the reason is stated

Over canopy, prediction and reference are not measuring the same surface: LiDAR returns
reach through gaps toward the ground, optical RGB sees only treetops, and SRTM sits at an
uncertain level inside the canopy. A forest error figure therefore mixes genuine model error
with a disagreement about what "height" means. Averaging it into the headline makes that
number both worse and less meaningful. Hard rule 8.

### Stratification by GSD, as well

Because evaluation is on ISRO imagery at an unknown GSD, and accuracy is a function of
pixel size (`05-domain-reference.md`), metrics are also reported **per GSD band**. Bands are
set in `config.py`. This produces the honest statement we want to be able to make: *"at
≤0.5 m we achieve X; at 2 m, Y; below the floor we decline to estimate object heights."*

---

## Targets

Aims, not claims. Each becomes a measured number or is reported as missed.

### Accuracy — absolute DSM, georeferenced input

| Metric | Target | Reasoning |
|---|---|---|
| Building-only RMSE, urban, ≤0.5 m GSD | **≤ 3.0 m** | Roughly one storey. Useful for disaster assessment; honest for single-view. |
| Overall RMSE, urban, ≤0.5 m GSD | ≤ 2.0 m | Easier than building-only, since most pixels are ground |
| MAE, urban | ≤ 1.5 m | |
| Correlation, urban | ≥ 0.85 | Shape correctness is the precondition for everything else |
| Bias, any class | within ±0.5 m | A residual bias is a calibration bug and should be fixed, not reported |
| Hilly / sparse / forested | **report, no target** | We have no data yet; setting a target we cannot test would be dishonest |

### Accuracy — relative rDSM, non-georeferenced input

Absolute error is undefined here. Targets are scale-free:

| Metric | Target |
|---|---|
| Correlation against reference | ≥ 0.80 |
| Scale-invariant RMSE | report |
| δ1 | report |

### The headline comparison

| Configuration | Purpose |
|---|---|
| Depth Anything V2, zero-shot, no calibration | The baseline. Expected to be poor. **Kept and published.** |
| + GSD normalisation | Isolates how much of the gap is a resolution mismatch |
| + calibration (SRTM / shadow / GCP) | Isolates the contribution of metric anchoring |
| + fine-tuned nDSM head | Isolates domain adaptation |
| Full pipeline | The number we quote |

Reporting the ablation, not just the final number, is what distinguishes a measured result
from a claim. It also tells us which stages to cut.

### Calibration anchors, measured independently

Each anchor is evaluated alone against reference, so we can say which ones earn their place
rather than asserting that all three help.

| Anchor | What we want to know |
|---|---|
| SRTM DTM | Residual bias after adding predicted nDSM; error as a function of terrain relief |
| Shadow geometry | Absolute height error on buildings with clean shadows; how often a usable shadow exists at all |
| GCPs | Error versus number of points — the practically important curve is 3, 5, 10, 20 |
| Fusion | Does combining beat the best single anchor, and is the confidence band honest |

**The confidence band must be calibrated.** If we state ±1.8 m, then ~68% of errors should
fall inside ±1.8 m. The harness checks this directly. An uncalibrated uncertainty is worse
than none, because it invites misplaced trust.

### Performance and stability

| Metric | Target | Why |
|---|---|---|
| Inference, 1024×1024 tile, RTX 4060 | report | Needs CUDA fixed first — see `11-deferred.md` |
| End-to-end, 4096×4096 GeoTIFF to viewable scene | ≤ 60 s | Demo patience limit |
| Viewer frame rate, 4096² terrain | **≥ 30 fps sustained** | "Seamless" and "real time" are the brief's words |
| Viewer cold start to first frame | ≤ 5 s | |
| Crashes during a demo | **zero** | "Software stability" is in the criteria |
| Malformed input handling | graceful message, never a traceback | 16-bit, CMYK, no CRS, absurd aspect ratio |

### Visualization quality

Half the marks, so these are measured too, not left to taste.

| Metric | Target | How |
|---|---|---|
| Texture projection alignment | **≤ 1 px** | Render a known checkerboard GeoTIFF, measure corner offset |
| Height probe agreement with the source DSM | exact | Clicking a pixel must return that pixel's stored value |
| Navigation responsiveness | no stutter > 100 ms | Frame-time histogram, not average fps |
| Judge comprehension | reads a height unaided in ≤ 90 s | Test on a person who has not seen it |

---

## The eval harness

Lives in `server/eval/`. One command, no arguments, reproducible.

```
python -m eval.run_eval
```

### What it does

1. Loads the declared held-out split. **Never re-split** to improve a number (hard rule 4).
2. Runs the full pipeline per tile, exactly as a user would — no privileged access to
   reference data at inference.
3. Computes every metric above, per landscape class and per GSD band.
4. Writes `docs/13-eval-results.md`, including the git commit, date, weights hash and
   configuration, so any number in it can be traced to the code that produced it.
5. Exits non-zero if a regression gate is breached, so `run.ps1 -Test` catches it.

### Two splits, always both

| Split | Purpose |
|---|---|
| **Official GAMUS split** | Comparability with published work |
| **Leave-one-city-out** | The honest transfer estimate |

The official split shares cities between train and test (`05-domain-reference.md`), which
lets a model memorise city-specific appearance and score well without generalising. Since
evaluation is on ISRO imagery of a different country, **where the two disagree we quote the
leave-one-city-out number.**

### Landscape labelling

Tiles must be labelled urban / sparse / hilly / forested to stratify at all. Route, in
preference order:

1. **Derive from GAMUS's semantic class layer** — building fraction and tree fraction give
   urban/sparse/forested directly. Free, objective, reproducible.
2. **Derive hilliness from SRTM relief** over the tile footprint — terrain range, not land
   cover, so it is an independent axis.
3. Hand-label only as a last resort, and record that it was hand-labelled.

Blocked on resolving the class legend (`10-unsourced.md`).

---

## Regression gates

`run.ps1 -Test` fails if:

- CRS or affine transform round-trip is not exact
- A non-georeferenced input produces any metre-labelled value anywhere
- Any primary metric regresses more than 10% against the last committed results
- A DSM is written without complete provenance
- The confidence band's empirical coverage falls outside 60–75% where ±1σ was claimed

---

## Data we need, starting now

| What | Why | Lead time |
|---|---|---|
| GAMUS, 80 GB | The recommended training set | **Start immediately** — longest pole |
| Terrain-diverse supplementary data (hilly, forested) | **G3 is unsatisfiable without it.** Biggest open risk. | Start immediately |
| Real ISRO imagery at ≥2 GSDs | To exercise GSD handling against something real | Unknown — may need the SPOC |
| SRTM tiles for every scene footprint | The DTM term | An afternoon once access is settled |
| A few real GCPs with a recorded datum | To measure the GCP anchor honestly | Low |
