# Build plan

Ordered so the riskiest and longest-lead things start first, and the demo is always in a
showable state.

Principle: **the eval harness and the honest baseline come before the model work.**
Everything else is replaceable; the ability to measure is the product.

> This file is the **plan**, not the tracker, and the checkboxes below are deliberately left
> as originally written. For what is actually outstanding read `11-deferred.md`; for measured
> numbers `12-eval-results.md`, and for what they mean `13-baseline-analysis.md`.
>
> **Progress, 2026-09-15.** Phase 0 and Phase 1 are done. Phase 3 (fine-tuning) came earlier
> than planned, because the Phase 1 baseline showed the domain gap was the dominant error and
> closing it was worth more than calibration. Phase 4's viewer is largely built. Phase 2
> (calibration to absolute elevation) is the main remaining gap, and the shadow ray-caster
> that Phase 2 depends on is already written and tested.

---

## Phase 0 — Unblock the long poles (in parallel, now)

Nothing here needs the pipeline to exist.

- [ ] **Fix CUDA.** torch is installed as the **CPU build**; `torch.cuda.is_available()` is
      `False` on a machine with an RTX 4060 (8188 MiB, driver 616.56).
      `pip install torch --index-url https://download.pytorch.org/whl/cu130` — 2.13.0+cu130
      exists and matches the installed version. **Until this is done, every timing number in
      the project is meaningless.**
- [ ] **Start the GAMUS download** — ~80 GB, the longest lead time. Background it; it does
      not block Phase 1 code, which can be written against a handful of tiles.
- [ ] **Resolve O2: terrain-diverse supplementary data.** Assess DFC2019/US3D, GeoNRW,
      ISPRS Vaihingen and any open Indian-terrain DSM. **The biggest open risk in the
      project** — G3 is unsatisfiable without hilly and forested data.
- [ ] **Resolve O3: the GAMUS class legend**, empirically — cross-tabulate class index
      against AGL statistics over a sample of tiles.
- [ ] **Settle SRTM access** (O4) and cache a tile to prove the route works.
- [ ] **Obtain real ISRO imagery at two or more GSDs** to exercise GSD handling against
      something real rather than a resampled proxy.
- [ ] Pin the Depth Anything V2 checkpoint and record its hash.
- [ ] Confirm the Babylon terrain extension's current package name and API (O7).
- [ ] Re-check the portal for the **truncated Dataset Link sentence**, plus the YouTube link
      and SPOC contact. Re-check the reference repo for added data.

## Phase 1 — The spine

No UI, no fine-tuning, no calibration. All of it testable.

- [ ] **`io_raster.py`** — read PNG/JPG/TIFF, write float32 single-band GeoTIFF, CRS and
      affine transform preserved **exactly**. Georeferenced and non-georeferenced paths
      distinguished from the file's own metadata.
- [ ] **`tests/test_raster.py`** — the round-trip proof. Written with the module, not after.
      Every number the project ever reports depends on this being right.
- [ ] **`ingest.py`** — GSD detection from the transform, canonical resample, tiling with
      overlap, and seam-free reassembly.
- [ ] **`backbone.py`** — Depth Anything V2 wrapper. Zero-shot relative depth. Frozen.
- [ ] **`dsm.py`** — orchestrator, writing a complete provenance sidecar from day one.
- [ ] **Landscape labelling** from the semantic layer and SRTM relief, so stratification is
      possible at all.
- [ ] **`eval/` — the harness.** Both splits (official and leave-one-city-out), every metric
      in `04-targets.md`, per landscape class and per GSD band. Writes
      `docs/12-eval-results.md`. Exits non-zero on a regression gate.
- [ ] **Measure and commit the zero-shot baseline, however bad it is.**

**Milestone:** one command turns a GeoTIFF into a GeoTIFF, and one command prints RMSE, MAE
and correlation per landscape class and per GSD band. No UI, no trained model. If this is
solid, everything after it is improvement rather than guesswork.

## Phase 2 — Scale calibration

The brief's stated core challenge. Each anchor measured **alone** before any fusion.

- [ ] **`srtm.py`** — fetch, cache, reproject and resample SRTM to a DTM on the image grid.
      Handle the **EGM96 vs WGS84 datum** difference explicitly; it is tens of metres in
      India and will otherwise look like a broken model.
- [ ] **`shadow.py`** — sun geometry from metadata or timestamp+location, shadow detection,
      `h = L·tan(θ)`. Reject shadows on slopes, occluded shadows and cloud shadow. Report how
      often a usable shadow exists at all.
- [ ] **`gcp.py`** — robust (RANSAC) affine fit of relative depth to known elevations.
      Record each point's datum. Produce the error-vs-number-of-points curve for 3, 5, 10, 20.
- [ ] **`calibrate.py`** — fuse the anchors, emit a confidence band, and **check the band's
      empirical coverage**. An uncalibrated uncertainty is worse than none.
- [ ] Re-run the harness. Report each anchor's independent contribution, and cut any that
      does not earn its place.

**Milestone:** a georeferenced image yields heights in metres with a stated, *calibrated*
uncertainty, and we can say which anchor produced the scale.

## Phase 3 — Close the domain gap

- [ ] **`train/datasets.py`** — GAMUS loader (HDF5, dataset key `image` in all three
      directories), both split definitions, augmentation that is valid for overhead imagery
      (rotation and flips are; vertical-axis tricks that imply a horizon are not).
- [ ] **`head.py` + `train/train_head.py`** — nDSM regression head on the frozen encoder
      first, then a partial encoder unfreeze on the cloud GPU. Runs unchanged in both places.
- [ ] Loss design for height: scale-invariant plus gradient terms, so edges stay sharp —
      blurry roof edges look bad in the viewer even at good RMSE.
- [ ] **GSD-degradation sweep** — train at 0.33 m, evaluate at simulated coarser GSDs, and
      set the refusal floor (D8) from the measured curve rather than an assumption.
- [ ] Re-run the harness unchanged. Report the ablation table from `04-targets.md`.

**Milestone:** the delta against the Phase 1 baseline is measured and published, and the GSD
floor is a number we derived rather than chose.

## Phase 4 — The viewer

- [ ] **`mesh.py`** — DSM to heightfield/glTF, LOD tiles, texture tiles. Vertical exaggeration
      as an explicit, labelled control — never silently applied.
- [ ] **`terrain.ts`** — mesh from the heightfield, original image projected. **Alignment
      verified against a checkerboard GeoTIFF to ≤1 px**, since "projection accuracy" is the
      first thing the visualization criteria name.
- [ ] **`cameras.ts`** — flythrough, ground-level first-person, and orbit. State preserved
      across switches.
- [ ] **`probe.ts`** — click to read height; slope; a terrain profile along a drawn line.
      Readout always shows units, anchor source and confidence — never a bare number.
- [ ] **`overlays.ts`** — RGB, slope, contours, signed error. Computed server-side into
      textures and swapped on the material; far less code than shader work.
- [ ] **`validate.ts`** — predicted vs reference side by side, signed error heatmap, live
      RMSE/MAE/correlation over the visible extent. **A first-class user-facing screen**, per
      the brief's deliverables, not a dev tool.
- [ ] **`ui.ts`** — upload, layer toggles, readouts, and the always-visible **units badge**
      reading relative or absolute straight from provenance (hard rule 2).
- [ ] **`api.py`** — upload, process, download, validate.
- [ ] Frame-time histogram, not average fps, against the ≥30 fps target.

**Milestone:** drop in a GeoTIFF, fly through the result, click a roof and get a height with
its units and uncertainty, and compare against reference inside the app.

## Phase 5 — Standalone and hardening

- [ ] **Electron viewer installer** — committed tier. Runs on a machine that never had Node
      or Python, fully offline.
- [ ] **Full-pipeline bundle** — stretch tier, PyInstaller + spawned server. Multi-GB with
      CUDA. Logged in `11-deferred.md` from day one.
- [ ] **Malformed input pass:** 16-bit, CMYK JPEG, missing CRS, absurd aspect ratio, a
      50000×50000 TIFF, a 1-pixel image. Graceful message, never a traceback.
- [ ] Memory ceiling on large rasters — stream rather than load whole.
- [ ] Interface pass for a judge with 90 seconds and no explanation.

## Phase 6 — Submission layer

- [ ] README: clone and one command.
- [ ] Docs audit — every doc checked against the code, stale claims removed.
- [ ] The numbers table, regenerated from the harness.
- [ ] The ablation chart: off-the-shelf versus ours, per landscape class.
- [ ] The deck, and a rehearsed demo.

---

## What "done" looks like for the demo

A judge drops in a satellite image they brought themselves. Thirty seconds later they are
flying through the terrain it describes, with the photo correctly draped over real geometry.
They click a building and read "14.2 m ± 1.8 m above ground — scale from SRTM + 3 shadow
anchors, agreeing."

Then they drop in a plain JPG, and the badge switches to **"relative — no metric scale
available"**, and every metre value in the interface disappears.

Then you show the table: off-the-shelf depth model versus ours, per landscape class, on a
city neither was trained on. And you say which landscape classes you have no data for, and
why.
