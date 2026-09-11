# Domain reference — glossary, datasets, and the measured facts

Read this before touching the elevation module. Most bugs in a geospatial pipeline are
not logic errors; they are unit errors, datum errors and resolution errors, and they are
invisible until someone checks against ground truth.

---

## Glossary — the four surfaces, and why confusing them is the classic failure

| Term | What it measures | In this project |
|---|---|---|
| **DEM** — Digital Elevation Model | Umbrella term. Often used loosely to mean either of the next two. Avoid it in code; it is ambiguous. | Used only when quoting the brief |
| **DTM** — Digital Terrain Model | The **bare earth**. Buildings and trees removed. Hills, valleys, riverbeds. | Comes from SRTM 30 m |
| **DSM** — Digital Surface Model | The **top of everything**. Roofs, canopy, bridges. What a laser hits first. | Our final output |
| **nDSM** — normalised DSM, a.k.a. **AGL** (Above Ground Level) | `DSM − DTM`. Height of objects *above the ground beneath them*. A 12 m building on a 300 m hill has nDSM 12. | What the network predicts |

The identity the whole pipeline rests on:

```
DSM  =  DTM  +  nDSM
        ^^^     ^^^^
        SRTM    predicted by the network
        30 m    at image resolution
```

**Why split it.** SRTM at 30 m per pixel cannot see a building — a house is a third of a
pixel. But it is entirely correct about whether you are in a valley at 300 m or on a
ridge at 900 m. Conversely a network looking at one image has a good chance of judging
"this roof is about 12 m above the street in front of it" and essentially no chance of
judging "this scene is 340 m above sea level", because **nothing in the pixels encodes
absolute elevation.** Asking one model to produce both is asking it to do an impossible
half and an achievable half at the same time. Splitting them lets each source do what it
is actually capable of.

This is not our invention, and it is corroborated by the recommended dataset: GAMUS
ships its height layer as **AGL** — see below. The officially recommended training data
trains the nDSM term specifically.

### Other terms

| Term | Meaning |
|---|---|
| **GSD** — Ground Sample Distance | Real-world size of one pixel. 0.33 m GSD means one pixel covers 33 cm of ground. The single most important number about any image here. |
| **CRS** — Coordinate Reference System | How pixel coordinates map to positions on Earth. Identified by an EPSG code, e.g. EPSG:4326 (lat/lon degrees) or a UTM zone like EPSG:32643 (metres). |
| **Affine transform** | The six numbers mapping pixel (row, col) to CRS coordinates. GSD is derived from it. Preserving it exactly is hard rule 5. |
| **Nadir / off-nadir** | Nadir = camera pointing straight down. Off-nadir = tilted, which makes tall buildings visibly lean — a genuine height cue. |
| **Orthophoto** | Imagery geometrically corrected so it behaves like a map: constant scale, no perspective lean. |
| **SRTM** | Shuttle Radar Topography Mission. Near-global DTM at 1 arc-second ≈ 30 m. The standard free coarse terrain source. |
| **GCP** — Ground Control Point | A pixel whose true elevation is known. A handful lets you fit relative depth to metres. |
| **Relative depth** | Ordering without scale: "A is higher than B", no metres. What pre-trained monocular models output. |
| **rDSM** | A DSM with relative values only. What we output for non-georeferenced input, and it carries **no metre labels anywhere**. |

---

## Why monocular depth models struggle here — the domain gap, concretely

Pre-trained monocular depth models (Depth Anything, MiDaS, Depth Pro) learn from
**egocentric** imagery: photos taken by a person or a car, where these cues dominate:

- perspective convergence — parallel lines meet at a vanishing point
- relative size of familiar objects — a person is ~1.7 m, so scale propagates
- ground-plane contact — objects visibly stand on a floor that recedes
- occlusion ordering and defocus

A nadir satellite orthophoto has **almost none of these**. It is near-orthographic: there
is no vanishing point, no visible ground plane receding into the distance, and the
entire scene is effectively at the same distance from the sensor. The cues that *do*
survive are different ones: cast shadows, off-nadir lean, and occlusion of neighbours.

The practical consequence, which the Phase 1 baseline measures rather than assumes: run
zero-shot on an orthophoto, these models partly report **albedo and texture** as depth. A
bright roof reads "near", dark asphalt reads "far". The output correlates with how the
surface *looks*, not how tall it *is*.

That is the gap. Closing it is where half the marks live.

### Surviving cues, ranked by how much we can exploit them

1. **Cast shadows.** Strongest and the only *physically metric* one. See below.
2. **Off-nadir lean.** Real but depends on the acquisition geometry, and orthophotos have
   it removed by construction.
3. **Semantic identity.** Knowing a pixel is "building" vs "road" bounds its plausible
   height. GAMUS gives us this layer for free, and the brief names semantic priors
   explicitly.
4. **Texture and context.** What the fine-tuned head learns. Works, but is the cue most
   likely to transfer badly across cities and sensors.

### The shadow anchor

For a vertical structure with a cast shadow of ground length `L`, illuminated at solar
elevation angle `θ`:

```
h = L · tan(θ)
```

This is plane geometry, not learning. It yields a height in **metres** from a single
image, with no DEM, no GCPs and no training. The inputs it needs are solar elevation and
azimuth, which come from satellite product metadata, or are computable from acquisition
timestamp plus scene-centre latitude/longitude.

It is the cleanest available answer to the brief's stated core challenge — converting
relative depth to metric elevation — because it is the one route that does not depend on
an external elevation product being available for the scene.

Known limits, to be measured in Phase 2 rather than hand-waved: shadows falling on
sloped ground bias `L`; shadows occluded by other structures truncate; dense urban cores
have overlapping shadows; `tan(θ)` is numerically unstable as θ approaches 90°
(overhead sun, short shadows); and cloud shadow is a false positive. Treated as **one
anchor among three**, cross-validated against SRTM and GCPs, not as the sole source.

---

## GSD — why it decides accuracy, and why we refuse below a floor

Height estimation accuracy is a function of pixel size. At 0.33 m GSD a 10 m building is
~30 px across and its shadow is resolvable. At 5.8 m GSD that same building is under
2 px: its edges, its roof structure and its shadow are all gone. **The height information
is not merely harder to recover — it is not present in the data.**

This matters because final evaluation is on ISRO imagery, and ISRO optical products span
a wide GSD range, while GAMUS trains at a single GSD of 0.33 m. A model trained at one
GSD and run at another degrades silently — it returns confident, wrong numbers, because
nothing in the architecture notices the scale changed.

Our handling, in three parts:

1. **Detect** GSD from the GeoTIFF affine transform on ingest.
2. **Normalise** — resample to the canonical GSD the model was trained at, so the model
   always sees the scale it learned. Record both GSDs in provenance.
3. **Refuse below a floor.** Under the GSD floor set in `server/depthwizard/config.py`,
   emit terrain only and flag `objects_not_resolvable`. Hard rule 7.

Reporting accuracy **per GSD band** rather than as one average follows from the same
logic, and is how we can state honestly where the method works.

> **Unsourced:** the specific GSDs of the ISRO products used at evaluation. We have not
> been told which sensor. Logged in `docs/10-unsourced.md`; the pipeline is built to read
> GSD from the file rather than assume one.

---

## GAMUS — the recommended dataset, as measured

Officially recommended by the organisation's reference repo (`docs/01-problem-statement.md`).

| Property | Value | How we know |
|---|---|---|
| Name | GAMUS — *Geometry-aware Multi-modal Semantic Segmentation Benchmark for Remote Sensing Data* | Paper title |
| Paper | arXiv 2305.14914 | Search |
| Official loader | `github.com/EarthNets/RSI-MMSegmentation` → `gamus_dataset.py` | Read directly |
| HF mirror | `huggingface.co/datasets/earthflow/GAMUS` | Reference repo link |
| Licence | CC-BY-4.0 | HF dataset card |
| Download size | ~80 GB | HF dataset card |
| GSD | **0.33 m** | Paper |
| Tile size | **1024 × 1024** | Paper, and verified by inspecting a tile |
| Height layer | **AGL — metres above ground (nDSM), not absolute elevation** | Filename suffix `_AGL`, verified by inspection |
| Ground truth origin | nDSM derived from LiDAR point clouds; open data catalogs of Washington DC and Philadelphia | Paper |

### Layout, verified by inspection

Three parallel directories, each split `train` / `val` / `test`, filenames sharing a stem:

```
images/<split>/<CITY>_<rr>_<cc>_RGB.h5     (1024, 1024, 3)  uint8
heights/<split>/<CITY>_<rr>_<cc>_AGL.h5    (1024, 1024)     float32, metres AGL
classes/<split>/<CITY>_<rr>_<cc>_CLS.h5    (1024, 1024)     float32, integer-valued 0..6
```

Every file contains exactly one HDF5 dataset, named **`image`** — including the height
and class files. That naming is confusing but it is what the official loader reads.

Measured on `DC_03_26`: AGL ranges −5.0 to 42.57 m, mean 11.09, **no NaN**. The −5.0
floor appears to be a clamp rather than a nodata marker; treat negative AGL as valid-
but-clamped, and do not assume a nodata sentinel exists. Verify per-tile rather than
globally.

### File counts, as mirrored (measured from the HF file listing)

| Split | DC | NYC | PHL | Total |
|---|---|---|---|---|
| train | 1439 | 1167 | 2398 | **5004** |
| val | 359 | — | 500 | **859** |
| test | 361 | 1000 | 1500 | **2861** |
| | | | | **8724** |

### Three discrepancies and gaps we must not paper over

1. **The HF mirror is a subset of the published dataset.** The paper describes 11,507
   tiles across **five** cities — Oklahoma, Washington DC, Philadelphia, Jacksonville and
   New York City — split 6304 / 1059 / 4144. The mirror has 8,724 tiles across **three**
   — DC, NYC, PHL. Oklahoma and Jacksonville are absent. The HF dataset card's own row
   counts (1.2k / 1.6k / 3.1k) match neither; our table above is counted from the actual
   file list and is the one to trust.

2. **The mirror has no hilly or forested terrain.** DC, NYC and Philadelphia are flat
   East-Coast US urban. The brief explicitly demands "performance stability across urban,
   sparse, hilly, and forested landscapes". **Training on the mirror alone cannot produce
   evidence for half of that requirement.** This is the single largest data gap in the
   project and it is logged in `docs/11-deferred.md`. Supplementary terrain-diverse data
   is required, not optional.

3. **The official split shares cities between train and test.** DC tiles appear in train,
   val *and* test; PHL in all three. Tile-level splitting within the same city lets a
   model memorise city-specific appearance — the same roof materials, the same street
   grid, the same sun angle — and score well without generalising. Since evaluation is on
   **ISRO imagery of a different country**, the official split will overstate our real
   performance.

   Therefore the harness reports **two** splits: the official one, for comparability with
   published work, and a **leave-one-city-out** split, as the honest estimate of transfer.
   Where they disagree, the leave-one-city-out number is the one we quote.

### Semantic classes

The paper names six land-cover types: **ground, low-vegetation, building, water, road,
tree**. Inspection finds **seven** distinct values, 0–6, so one value is presumably
background / unlabelled alongside the six named classes.

> **Unsourced:** the mapping from integer index to class name. The paper names the classes
> but not their order; the official loader passes the array through without a legend. We
> will not invent it. Until verified it is `PLACEHOLDER` in the code and logged in
> `docs/10-unsourced.md`. Verification route: cross-tabulate class index against measured
> AGL statistics — `building` and `tree` must show high mean AGL, `water` and `road` must
> sit near zero — which identifies the indices empirically rather than by assumption.

---

## SRTM — the coarse terrain source

| Property | Value |
|---|---|
| Resolution | 1 arc-second ≈ 30 m at the equator |
| Coverage | ~56°S to 60°N — covers all of India |
| Vertical datum | EGM96 geoid, **not** the WGS84 ellipsoid |
| Surface type | Nominally a DSM, not a true DTM — C-band radar partly penetrates canopy but does not reach bare earth under dense forest |

Two traps that will silently corrupt metre values:

1. **Datum mismatch.** SRTM heights are orthometric (above the EGM96 geoid). GNSS and
   many GeoTIFFs are ellipsoidal (above WGS84). The difference across India is on the
   order of tens of metres — far larger than the building heights we are trying to
   measure. Mixing them without conversion produces a large constant bias that looks
   like a calibration failure. Any GCP elevation must have its datum recorded in
   provenance.

2. **SRTM is not truly bare-earth.** Over forest it sits somewhere inside the canopy. So
   `DSM = SRTM + nDSM` double-counts vegetation height over forest. This is a known,
   bounded error that must be stated in the forest results rather than averaged away —
   hard rule 8, and part of why forest is scored separately.

---

## Why forest is reported separately — a definitional problem, not a model failure

Over dense canopy, the reference and the prediction are not measuring the same surface:

- **LiDAR-derived ground truth** gets returns through gaps in foliage and is typically
  processed toward the ground.
- **Optical RGB** sees only the top of the canopy. What is underneath is not in the data.
- **SRTM** sits at an uncertain level *inside* the canopy, as above.

So a forest error figure mixes genuine model error with a disagreement about what
"height" means there. Averaging forest into an overall RMSE makes the headline number
both worse and less meaningful. We report it separately and state the reason. A judge who
knows remote sensing will expect exactly this; one who does not will learn something.

---

## Depth Anything V2 — the backbone

Chosen as the "robust pre-trained monocular depth model" the brief asks for. DINOv2 ViT
encoder plus a DPT decode head, trained for relative depth.

How we use it:

- **Phase 1 baseline:** entirely frozen, zero-shot, no adaptation. Produces the honest
  "what does a foundation model do out of the box on overhead imagery" number. This
  number is an asset — the delta between it and the final system *is* the technical
  contribution, and it is the evidence that the domain gap is real.
- **Phase 3:** replace the relative-depth head with an nDSM regression head trained on
  GAMUS, and unfreeze the last N encoder blocks on the cloud GPU.

> **Unsourced:** exact checkpoint identifier and weights hash. Pinned and recorded in
> provenance once Phase 0 downloads it.

---

## Output formats

| Input | Output | Units | Georeferencing |
|---|---|---|---|
| GeoTIFF with CRS | GeoTIFF, float32, single band | metres, absolute | CRS + transform copied exactly from input |
| PNG / JPG | GeoTIFF, float32, single band, **no CRS** | **relative, unitless** | none — and the viewer must show no metre value |

GeoTIFF for both, because the brief asks for "a standard geospatial format" and a
CRS-less GeoTIFF is still a valid, readable raster. Every output is written alongside a
provenance sidecar (hard rule 3).

---

## Sources

- GAMUS paper — https://arxiv.org/abs/2305.14914
- GAMUS on HuggingFace — https://huggingface.co/datasets/earthflow/GAMUS
- Official GAMUS loader — https://github.com/EarthNets/RSI-MMSegmentation
- Organisation reference repo — https://github.com/IMG-PROCESS-SAC/SIH2026
