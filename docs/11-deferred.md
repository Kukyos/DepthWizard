# Deferred — the live status document

Everything knowingly incomplete, what it blocks, and what it would take. **This is the real
tracker.** `07-build-plan.md` is the plan and is allowed to go stale; this file is not.

Updated in the same pass as the shortcut that created the entry. Never in a cleanup at the end.

Status as of **2026-09-15**. Phase 1 is complete and Phase 3 is under way. A real
satellite tile goes through a fine-tuned Depth Anything V2 on the GPU, out as a GeoTIFF in
**metres above ground** with provenance, and into the viewer as textured 3D terrain with
slope, contour and error-vs-reference overlays, a height probe and an upload flow.

Phase 2 (scale calibration to absolute elevation) has not started, so output is AGL, not
elevation above sea level. See D-05.

---

## Blockers — work cannot proceed correctly until these are resolved

### D-02 · No terrain-diverse training or evaluation data
**Severity: blocks half of a 50%-weighted gate.** The GAMUS mirror is DC, NYC and Philadelphia —
flat East-Coast US urban. No hilly terrain, no forest.

*Blocks:* G3, and therefore the "performance stability across urban, sparse, hilly, and forested
landscapes" the criteria name explicitly. **The largest open risk in the project.**
*Interim behaviour:* hilly and forested rows read `NO DATA`. We do not estimate them.
*Fix:* assess DFC2019/US3D (Jacksonville, Omaha add relief), GeoNRW, ISPRS Vaihingen, any openly
licensed Indian-terrain DSM. The brief permits any openly available dataset.
*Effort:* days of assessment and download, plus harmonising a second dataset's format and units.
Start in Phase 0, not later.

### D-03 · GAMUS tiles have no georeferencing
**Severity: blocks one of three calibration anchors on the primary dataset.** The HDF5 files
contain no CRS, no affine transform and no attributes — verified by inspection. Only a city code
and a row/column index in the filename.

*Blocks:* evaluating the SRTM anchor on GAMUS at all; deriving hilliness from SRTM relief for
landscape labelling; the shadow anchor on GAMUS, which needs sun geometry tied to a location and
date.
*Consequence:* the SRTM and shadow anchors must be validated on a **different** dataset that
retains georeferencing. Plan for two evaluation datasets, not one.
*Fix:* source footprints (U-04), or accept a georeferenced second dataset as the anchor
validation set.
*Effort:* unknown — depends entirely on whether footprints are recoverable.

---

## Built and running

| Item | Phase | State |
|---|---|---|
| `io_raster.py` + `tests/test_raster.py` | 1 | CRS/transform round-trip proven exact |
| `backbone.py` — Depth Anything V2 | 1 | Runs on CUDA; Base default, Small/Large available |
| `dsm.py` — orchestrator + provenance | 1 | One image in, GeoTIFF + sidecar out |
| `eval/` — the harness | 1 | Both metric and relative paths; per-class; pinned split |
| `head.py` + `train/` — metric height head | 3 | Backbone frozen, decoder retrained, 11% of params |
| `shadow.py` — ray-cast + differentiable | 2 | Geometry checked against trigonometry, 10 tests |
| `overlays.py` — slope, contours, error | 4 | Computed server-side, swapped as textures |
| `mesh.py` — scene export | 4 | manifest + heightfield + texture + overlays |
| `api.py` — upload, process, download | 4 | Refusals tested; CORS localhost-only |
| Viewer | 4 | Texture draped, 3 cameras, probe, layer switch, upload |
| `tools/fetch_datasets.py` | 0 | Phased, resumable, retrying |
| `tools/resolve_class_legend.py` | 0 | Resolved D-04 from evidence |

**End to end works on real imagery**, including the trained path: a GAMUS tile through the
fine-tuned decoder to a GeoTIFF in metres above ground, exported to a navigable 3D scene
with a working height probe and error overlay.

## Not started

| Item | Phase | Note |
|---|---|---|
| `ingest.py` GSD normalise + tiling | 1 | Not needed yet; inputs so far are single 1024² tiles |
| Leave-one-city-out evaluation | 1 | **Blocked on data**: only DC tiles have downloaded so far (D-06) |
| `srtm.py` with datum handling | 2 | See U-07 — the datum trap is tens of metres |
| `shadow.py` | 2 | Our primary novelty. Blocked on D-03 for validation |
| `gcp.py` | 2 | |
| `calibrate.py` + confidence band | 2 | Band must be coverage-checked, not just emitted |
| nDSM head + training | 3 | Needs the GAMUS download to finish |
| GSD degradation sweep → the refusal floor | 3 | The floor must be measured, not chosen |
| Overlays, validation view, upload UI | 4 | Viewer currently loads a pre-exported scene only |
| `api.py` | 4 | No server yet; export is a CLI step |
| Electron installers | 5 | |

### D-06 · Only one city has downloaded
**Severity: blocks the honest transfer number.** The download fetches tiles alphabetically
within a split, so every tile on disk is Washington DC; Philadelphia begins after all 359 DC
val tiles. Until then, leave-one-city-out cannot run and every figure comes from a
**within-city pilot split**, which shares scene appearance between train and validation and
therefore overstates generalisation.

*Interim behaviour:* pilot numbers are labelled as pilot numbers everywhere they appear, and
the training script prints a warning banner. They are for checking that training converges.
*Fix:* wait for PHL tiles, then `--held-out-city PHL`.

### D-05 · No absolute heights yet
Phase 2 calibration does not exist, so **every output is relative**, including for a
georeferenced input whose CRS is preserved. This is correct rather than unfinished — emitting
metres before anything establishes a scale is the fabrication hard rules 1 and 2 exist to
prevent — but it does mean G1's absolute path is not yet demonstrable.

---

## Accepted limitations — deliberate, not to be "fixed"

These are design decisions that will look like gaps to someone who has not read the reasoning.

### L-01 · No metre values for non-georeferenced input
Hard rule 2. Without a CRS and pixel size, metres are unknowable; emitting them would be
fabrication. The impoverished branch is correct, not unfinished.

### L-02 · Refusal below the GSD floor
Hard rule 7. Below it a building spans under two pixels and height is not present in the data.
Refusing is a feature to demo.

### L-03 · Forest scored separately, never averaged in
Hard rule 8. Prediction and reference measure different surfaces over canopy. Averaging makes the
headline both worse and less meaningful.

### L-04 · Single-view only
The brief says single-view. Stereo would answer an easier question.

### L-05 · Not survey-grade
We deliver an estimate with calibrated error bars, not a certified survey.

---

## Stretch — wanted, not committed

### S-01 · Full-pipeline standalone bundle
Viewer-only Electron installer is committed (G5). The full bundle — PyInstaller'd FastAPI plus
PyTorch, spawned as a child process — is a stretch. With CUDA the artefact is multi-GB.

*Logged from day one so it is never mistaken for done.* The committed tier satisfies G5 on its
own, since the brief asks for a deployable standalone application, not specifically for inference
inside it.

### S-02 · Off-nadir lean as a fourth anchor
Tall buildings lean in off-nadir imagery, which is a genuine metric height cue. Orthorectified
products have it removed by construction, so this only helps on raw off-nadir imagery. Worth
trying only if such imagery appears.

### S-03 · Uncertainty beyond anchor disagreement
MC-dropout or an ensemble would give a per-pixel uncertainty rather than a scene-level band
(O6). Only if anchor disagreement fails its coverage check.

---

## Resolved

### D-01 · CUDA unavailable — **resolved 2026-09-15**
torch had been installed as the CPU build on a machine with an RTX 4060. Reinstalling from
the cu130 index gives torch 2.14.0+cu130 with CUDA available and 7.1 GiB VRAM free. A first
Base-model inference on a 1024x1024 tile took 61 s including model load; steady-state
timing not yet measured. `run.ps1 -Setup` installs torch from that index first, before
requirements.txt, so the CPU wheel cannot win the race again.

### D-04 · GAMUS class legend unknown — **resolved 2026-09-15**
Determined from evidence by `tools/resolve_class_legend.py`; see U-01 for the four checks.
Sample size 3 tiles, recorded in config as `GAMUS_CLASS_LEGEND_TILES`.

