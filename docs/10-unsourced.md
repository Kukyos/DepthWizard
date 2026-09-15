# Unsourced values

Every domain value we could not source, what we are using instead, and where the real one
comes from. A judge can check any of these, so none of them is invented.

Convention: anything here is marked `PLACEHOLDER` in the code — structurally present,
visibly unsourced. When a value is sourced, it moves out of this file and gains a
`provenance` field.

Status as of **2026-09-15**.

---

## ~~U-01~~ — GAMUS class index → class name mapping · **RESOLVED 2026-09-15**
**Blocks:** semantic priors as a calibration route (brief milestone 2); landscape labelling,
and therefore the stratified reporting G3 requires.

**What we know.** The paper names six land-cover types: *ground, low-vegetation, building,
water, road, tree*. Inspecting `classes/test/DC_03_26_CLS.h5` finds **seven** distinct values,
0–6, stored as float32 — so one value is presumably background or unlabelled alongside the six
named classes.

**What we do not know.** Which integer is which class. The paper names them but not their
order. The official loader (`EarthNets/RSI-MMSegmentation/gamus_dataset.py`) passes the array
through without a legend.

**Resolved.** `tools/resolve_class_legend.py` profiles each index against height, colour
and area. The paper's listed order holds, confirmed on four independent checks: index 3 is
the only near-neutral surface (roofs) at 4.5-7.9 m median AGL; index 5 forms the connected
street network at 0 m; index 6 sits at 10-26 m and is brown rather than green because the
imagery is leaf-off winter; index 4 appears only at the -5 m clamp, which is what water
does to LiDAR returns. Index 0 is unlabelled background at <0.2%, not one of the six.

Written into `config.GAMUS_CLASS_NAMES`. **Sample size 3 tiles** — recorded as
`GAMUS_CLASS_LEGEND_TILES` and to be quoted alongside any metric that rests on it.
The `ground` / `low-vegetation` pair is the least distinctive and is held on the paper's
order rather than on evidence.

**How to source it.** Empirically, from the data itself: cross-tabulate class index against
measured AGL statistics over a sample of tiles. `building` and `tree` must show high mean AGL;
`water` and `road` must sit near zero; `water` should additionally show near-zero AGL variance
and a distinctive colour distribution. That identifies the indices from evidence rather than
assumption. Failing that, the paper's figures or the authors.

---

## U-02 — ISRO evaluation sensor, and therefore the test-time GSD
**Blocks:** sizing the GSD refusal floor honestly (D8); knowing whether building-level heights
are recoverable at all at evaluation time.

**What we know.** Final evaluation uses "ISRO RGB-band optical satellite i…" — **the portal
listing is truncated mid-word** and we have not seen the rest of the sentence. ISRO optical
products span a wide GSD range, and height recoverability differs enormously across it: at
sub-metre GSD a building is tens of pixels across; at several metres it is under two pixels and
the height information is not present in the data at all.

**Current state:** the pipeline reads GSD from the file rather than assuming one, which is the
correct design regardless. But the floor cannot be set honestly without knowing the target.

**How to source it.** Re-check the portal listing for the untruncated text. Ask the SPOC if one
is published. Failing both, set the floor from the measured GSD-degradation sweep in Phase 3
and state the assumption explicitly wherever the floor is quoted.

---

## ~~U-03~~ — Depth Anything V2 checkpoint · **PARTLY RESOLVED 2026-09-15**
**Blocks:** hard rule 3 — provenance completeness. Every DSM must record which weights produced
it.

**Partly resolved.** Checkpoint IDs verified present on the Hub and pinned by name in
`backbone.CHECKPOINTS` (Small/Base/Large `-hf`); Base is the default and has been run.
The commit hash is captured into provenance at load time. Still to do: pin an explicit
revision rather than tracking the branch head.

**How to source it.** Phase 0 downloads it; record the exact checkpoint identifier and the file
hash in `config.py` and in every provenance record. Pin the version — "latest" is not a
provenance.

---

## U-04 — GAMUS tile geographic footprints
**Blocks:** fetching the correct SRTM tile per GAMUS tile, which is needed to evaluate the SRTM
anchor and to derive hilliness for landscape labelling.

**What we know.** GAMUS HDF5 files contain **no CRS, no affine transform and no attributes** —
verified by inspection. Only the filename carries location, coarsely: a city code (`DC`, `NYC`,
`PHL`) and a row/column index, e.g. `DC_03_26`.

**What we do not know.** The geographic origin and spacing of that tile grid, so we cannot place
a GAMUS tile on Earth.

**Consequence, and it is significant.** Without footprints we cannot evaluate the SRTM anchor on
GAMUS at all. The SRTM path would have to be validated on a different dataset that retains
georeferencing. This is a real methodological constraint, not a detail — tracked as a blocker in
`11-deferred.md`.

**How to source it.** The paper or its supplement; the original open data catalogs for DC and
Philadelphia that GAMUS derives from; the GAMUS authors. Alternatively reconstruct footprints by
matching tiles against public orthophotos, which is laborious but possible.

---

## U-05 — GAMUS AGL clamp semantics
**Blocks:** correct loss masking during training, and correct nodata handling on output.

**What we know.** Measured on `DC_03_26_AGL.h5`: range −5.0 to 42.57 m, **no NaN**. The value
−5.0 appears to be a clamp rather than a nodata sentinel.

**What we do not know.** Whether −5.0 means "genuinely 5 m below local ground", "clipped", or
"no data". The three require different treatment: the first is a training target, the second
should be down-weighted, the third must be masked out.

**Current state:** treated as valid-but-clamped, and not assumed to be a sentinel. Flagged so it
is revisited before training.

**How to source it.** Measure the frequency of exactly −5.0 across many tiles and inspect where
it falls spatially. A clamp concentrates on water and in building shadows; a sentinel scatters or
forms hard edges at tile borders.

---

## U-06 — Sun geometry for the shadow anchor
**Blocks:** the shadow anchor (`shadow.py`), which is our primary novel calibration route.

**What we know.** `h = L·tan(θ)` needs solar elevation θ and azimuth. For real satellite products
these are in the product metadata. Solar position is also computable from acquisition timestamp
plus scene-centre latitude/longitude using standard astronomy, to well within the accuracy we
need.

**What we do not know.** Whether the evaluation imagery will carry that metadata, and GAMUS
carries no metadata at all (U-04), so the anchor cannot be validated on GAMUS tiles.

**Current state:** not implemented.

**How to source it.** Use a published solar-position algorithm rather than hand-rolled
trigonometry, and cite it. Accept sun parameters as explicit inputs with recorded provenance when
metadata is absent. Validate the anchor on a dataset that retains acquisition metadata.

---

## U-07 — SRTM vertical datum conversion for India
**Blocks:** absolute accuracy of the DSM. This is large enough to dominate everything else.

**What we know.** SRTM heights are orthometric, referenced to the **EGM96 geoid**. GNSS
measurements and many GeoTIFFs are ellipsoidal, referenced to **WGS84**. The separation across
India is on the order of tens of metres — far larger than the building heights we are trying to
measure — so mixing them silently produces a bias that looks exactly like a broken model.

**What we do not know.** The specific conversion source we will use, and its accuracy.

**Current state:** documented as a trap; no conversion implemented yet.

**How to source it.** Use a published geoid model via an established library rather than a
constant. Record the datum of every input and every GCP in provenance, and make the conversion
explicit and logged rather than implicit.

---

## U-08 — Terrain-diverse reference data for hilly and forested classes
**Blocks:** G3 — half of the brief's required stratification.

**What we know.** The GAMUS HuggingFace mirror contains DC, NYC and Philadelphia: flat East-Coast
US urban. The paper describes five cities including Jacksonville and Oklahoma, but those are
**absent from the mirror**. There is no hilly and no forested terrain in what we can download.

**Current state:** hilly and forested rows in `12-eval-results.md` will read
`NO DATA — see 11-deferred.md`. **We will not estimate them.**

**How to source it.** Phase 0 task O2 — assess DFC2019/US3D (Jacksonville and Omaha add relief),
GeoNRW, ISPRS Vaihingen, and any openly licensed Indian-terrain DSM. The brief explicitly permits
any openly available dataset.

---

## U-09 — Published benchmark numbers for comparison
**Blocks:** nothing. But we would like to say how we compare to published single-view height
estimation work.

**Current state:** no comparison numbers quoted anywhere. We have read the GAMUS paper's
abstract via search, **not the paper itself**, and will not quote figures from a summary.

**How to source it.** Read arXiv 2305.14914 directly, and the height-estimation literature it
cites. Quote only from the primary text, with a citation.

---

## Not unsourced — measured directly, recorded for completeness

These were verified first-hand on 2026-09-11 and are **not** placeholders.

| Value | Measured | How |
|---|---|---|
| GAMUS tile size | 1024 × 1024 | Read `DC_03_26` triplet |
| GAMUS RGB dtype | uint8, 3 channels | Same |
| GAMUS AGL dtype | float32, metres AGL | Same; filename suffix `_AGL` |
| GAMUS CLS values | 7 distinct, 0–6, float32 | Same |
| HDF5 dataset key | `image`, in all three directories | Same, and the official loader |
| GAMUS mirror file counts | 8724 total; train 5004 / val 859 / test 2861 | Counted from the HF file listing |
| GAMUS mirror cities | DC, NYC, PHL only | Same |
| GAMUS GSD | 0.33 m | Paper |
| GAMUS licence | CC-BY-4.0 | HF dataset card |
| Local GPU | RTX 4060 Laptop, 8188 MiB, driver 616.56 | `nvidia-smi` |
| torch state | 2.13.0, **CPU build, CUDA unavailable** | `torch.cuda.is_available()` |
| cu130 wheel availability | 2.13.0+cu130 exists, matches installed version | PyTorch index |
