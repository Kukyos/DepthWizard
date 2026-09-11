# Deferred — the live status document

Everything knowingly incomplete, what it blocks, and what it would take. **This is the real
tracker.** `07-build-plan.md` is the plan and is allowed to go stale; this file is not.

Updated in the same pass as the shortcut that created the entry. Never in a cleanup at the end.

Status as of **2026-09-11**. The repository is scaffolded; no pipeline code exists yet.

---

## Blockers — work cannot proceed correctly until these are resolved

### D-01 · CUDA is not available
**Severity: blocking all performance work.** torch 2.13.0 is installed as the **CPU build**.
`torch.cuda.is_available()` returns `False` on a machine with an RTX 4060 Laptop (8188 MiB,
driver 616.56).

*Blocks:* every timing number in the project; any practical inference; the local baseline run.
*Fix:* `pip install torch --index-url https://download.pytorch.org/whl/cu130` — 2.13.0+cu130
exists and matches the installed version, and driver 616.56 supports CUDA 13.
*Effort:* minutes, plus a large download. Wired into `run.ps1 -Setup`.

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

### D-04 · GAMUS class legend unknown
**Severity: blocks stratification and one calibration route.** Six class names are known from the
paper; their integer order is not (U-01).

*Blocks:* semantic priors as a calibration route (a named brief milestone); landscape labelling
from the class layer, which is the preferred route for stratifying G3.
*Fix:* empirical — cross-tabulate class index against AGL statistics. Building and tree must show
high mean AGL; water and road near zero.
*Effort:* an hour once a sample of tiles is downloaded.

---

## Not started — planned, nothing written yet

Listed so the repository's emptiness is not mistaken for progress. All of Phase 1 onward.

| Item | Phase | Note |
|---|---|---|
| `io_raster.py` + round-trip test | 1 | First code to be written. Everything sits on it. |
| `ingest.py` GSD detect/normalise/tile | 1 | |
| `backbone.py` Depth Anything V2 wrapper | 1 | Needs U-03 pinned |
| Eval harness, both splits, all metrics | 1 | The measuring tool, before the model |
| **Zero-shot baseline numbers** | 1 | The headline comparison depends on this existing |
| `srtm.py` with datum handling | 2 | See U-07 — the datum trap is tens of metres |
| `shadow.py` | 2 | Our primary novelty. Blocked on D-03 for validation |
| `gcp.py` | 2 | |
| `calibrate.py` + confidence band | 2 | Band must be coverage-checked, not just emitted |
| nDSM head + training | 3 | Needs D-01 and the GAMUS download |
| GSD degradation sweep → the refusal floor | 3 | The floor must be measured, not chosen |
| Whole viewer | 4 | |
| Electron installers | 5 | |

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

*(Nothing yet. Entries move here with the date and what fixed them.)*
