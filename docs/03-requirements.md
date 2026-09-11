# Requirements — gates, must-haves and lose conditions

Derived from `01-problem-statement.md`. Every item traces to a line in the official text.
If an item here is not in the brief, it is marked **[ours]**.

---

## The five gates

A gate is something that, if we fail it, no amount of quality elsewhere compensates.
These are phrased so they can be answered yes or no by someone who did not build it.

### G1 — Both input paths work, and are distinguished automatically

> *"The framework must support both non-georeferenced and georeferenced imagery."*

- A GeoTIFF with a CRS produces an **absolute DSM in metres**.
- A PNG or JPG produces a **relative rDSM** with no metric claim.
- The system decides which from the file's own metadata. The user is not asked.
- The distinction is **visible** in the UI and recorded in provenance.

**Fails if:** a PNG ever yields a number labelled in metres, or the user has to tell us
which mode to use.

### G2 — A standard geospatial format out, with georeferencing intact

> *"output a high-fidelity DSM in a standard geospatial format"*

- Output opens in QGIS without manual steps.
- CRS and affine transform are **bit-identical** to the input's, for georeferenced input.
- Proven by an automated test, not by eyeballing it.

**Fails if:** the output is a PNG of a heightmap, or lands in the wrong place on a map.

### G3 — Measured accuracy, stratified by landscape

> *"Evaluate RMSE, MAE, and correlation against LiDAR or reference data, including
> performance stability across urban, sparse, hilly, and forested landscapes."*

- RMSE, MAE and correlation reported against LiDAR-derived reference.
- Reported **separately for urban, sparse, hilly and forested** — not as one average.
- Produced by the harness from a held-out split, reproducible by a third party.

**Fails if:** we quote a single overall number, or any number we cannot regenerate on
demand. **This is the gate we are most likely to fail by omission**, because it requires
terrain-diverse data the recommended dataset does not contain (`11-deferred.md`).

### G4 — A navigable 3D flythrough with the photo projected on it

> *"project the original optical image onto a generated 3D terrain mesh… support seamless
> first-person navigation and analysis of structural heights and slopes"*

- The original image is textured onto the mesh, aligned correctly.
- First-person navigation that is **smooth** — the brief says "seamless" and "real time".
- Height and slope readable at arbitrary points from arbitrary viewpoints.

**Fails if:** the texture slides relative to the geometry, or navigation stutters.

### G5 — Standalone deployment

> *"deployable as a standalone application"* — in the milestones **and** the criteria.

- Installs and runs on a machine that has never had Python or Node.
- Works with no network connection.

**Fails if:** the demo needs `npm run dev` and a terminal.

---

## Must-haves

### Elevation module

| # | Requirement | Source |
|---|---|---|
| E1 | Accept PNG, JPG, TIFF | brief, deliverables |
| E2 | Pre-trained monocular depth backbone | brief, milestone 1 |
| E3 | Scale calibration from scene statistics, low-res DEM, semantic priors, or minimal GCPs | brief, milestone 2 |
| E4 | Output DSM in a standard geospatial format | brief, deliverables |
| E5 | Preserve CRS and transform exactly | implied by G2 **[ours: made testable]** |
| E6 | Provenance on every output | **[ours]** — hard rule 3 |
| E7 | GSD detection, normalisation, and refusal below a floor | **[ours]** — see `05-domain-reference.md` |
| E8 | Per-landscape and per-GSD-band metrics | brief, criteria; stratification is explicit |

### Visualization platform

| # | Requirement | Source |
|---|---|---|
| V1 | Upload imagery from the interface | brief, deliverables |
| V2 | Optical texture projected on the terrain mesh | brief |
| V3 | First-person navigation, seamless | brief |
| V4 | Structural height analysis at arbitrary points | brief |
| V5 | Slope analysis | brief |
| V6 | Arbitrary aerial viewpoints | brief |
| V7 | **Validate estimated heights against reference datasets, in the app** | brief, deliverables — user-facing, not a dev tool |
| V8 | Standalone deployable | brief |
| V9 | Units badge reflecting relative vs absolute at all times | **[ours]** — hard rule 2 |
| V10 | Fully offline | **[ours]** — hard rule 6 |

### Documentation

| # | Requirement | Source |
|---|---|---|
| D1 | Complete source code | brief |
| D2 | Technical documentation | brief |
| D3 | Reproducible metrics | implied by the criteria **[ours: made a rule]** |

---

## Lose conditions

Ways to score badly while appearing to have built the right thing.

1. **A beautiful flythrough with no accuracy numbers.** Half the marks are accuracy. This
   is the single most likely failure mode for a team in this problem, because the viewer is
   the fun part and the evaluation is the unglamorous part.

2. **One flattering average instead of stratified numbers.** The brief asks for stability
   across four landscape types. Reporting 2.1 m RMSE overall, when it is 1.4 m urban and
   9 m hilly, is not an answer to the question asked.

3. **Tuning on the test set.** We are evaluated on unseen ISRO imagery of a different
   country. Anything tuned until our own tiles look good transfers badly. Hard rule 4.

4. **Quoting metres for non-georeferenced input.** An invented unit is worse than an
   admitted absence of one, and a judge will test this by dropping in a JPG.

5. **Confident output at a GSD where height is not recoverable.** At coarse GSD a building
   is under two pixels and the information is simply not present. Emitting numbers anyway
   is fabrication; refusing is a feature. Hard rule 7.

6. **A demo that needs a developer.** G5 is explicit. A zip of source plus instructions is
   not a standalone application.

7. **Texture drift.** "Projection accuracy" is named first in the visualization criteria.
   A half-pixel misalignment is visible immediately and reads as carelessness.

8. **Training on three flat cities and claiming hilly performance.** The GAMUS mirror has
   no hills and no forest. Claiming a number we have no data to support would be the worst
   failure in the project — it breaks hard rule 1 and it is checkable.

9. **Datum confusion.** Mixing orthometric and ellipsoidal heights produces a tens-of-metres
   bias in India — larger than the buildings being measured. It looks like a broken model.

10. **A crash during the demo.** "Software stability" is named in the criteria. Large
    GeoTIFFs, 16-bit inputs, CMYK JPEGs, missing CRS, absurd aspect ratios — all must fail
    gracefully with a message.

---

## Explicitly out of scope

Stated so scope creep has something to bounce off.

- **Stereo or multi-view reconstruction.** The brief says single-view. Using two images
  would be answering an easier question.
- **Semantic segmentation as a product.** We use GAMUS's class layer as a *prior* for
  calibration; we are not delivering a land-cover map.
- **Change detection or time series.** One image.
- **Basemap streaming.** Offline, hard rule 6.
- **Survey-grade certification.** We deliver an estimate with error bars.
- **Real-time on-satellite inference.** Ground processing.
