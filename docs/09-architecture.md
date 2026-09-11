# Architecture

How the pieces fit, and the path a single image takes from upload to a navigable scene.

---

## The pipeline

```
  ┌─────────┐   ┌────────┐   ┌──────────┐   ┌───────────┐   ┌───────────┐   ┌──────┐   ┌────────┐
  │ ingest  │──▶│backbone│──▶│  head    │──▶│ calibrate │──▶│    dsm    │──▶│ mesh │──▶│ viewer │
  └─────────┘   └────────┘   └──────────┘   └───────────┘   └───────────┘   └──────┘   └────────┘
   read CRS      DAv2         nDSM           SRTM / shadow   GeoTIFF out     heightfield  Babylon
   detect GSD    relative     regression     / GCP fusion    + provenance    + LOD        + Electron
   normalise     depth        metres AGL      + confidence    sidecar         + texture
   tile                                                                        tiles
```

Each stage is a pure-ish function over arrays plus a metadata record, so each is testable
alone and the harness can run the whole chain exactly as a user would.

### Stage by stage

| Stage | Module | In | Out |
|---|---|---|---|
| Ingest | `ingest.py`, `io_raster.py` | PNG/JPG/TIFF | normalised tiles + `SceneMeta` |
| Backbone | `backbone.py` | RGB tile | relative depth, unitless |
| Head | `head.py` | encoder features | nDSM, metres above ground |
| Calibrate | `calibrate.py`, `srtm.py`, `shadow.py`, `gcp.py` | nDSM + SceneMeta | DSM in metres + confidence |
| Write | `dsm.py` | DSM + provenance | GeoTIFF + sidecar |
| Mesh | `mesh.py` | DSM + RGB | heightfield/glTF + texture tiles |
| View | `viewer/` | mesh + textures + provenance | navigable 3D scene |

---

## The two paths, decided by the file itself

The brief's first requirement is that both input kinds work, and the user is never asked
which mode to use — the file's own metadata decides (G1).

```
                        ┌─ has CRS + transform? ─┐
                       yes                        no
                        │                          │
            ┌───────────▼──────────┐   ┌───────────▼───────────┐
            │ GEOREFERENCED        │   │ NON-GEOREFERENCED     │
            │ GeoTIFF              │   │ PNG / JPG             │
            ├──────────────────────┤   ├───────────────────────┤
            │ GSD from transform   │   │ GSD unknown           │
            │ SRTM DTM available   │   │ no DTM possible       │
            │ shadow anchor usable │   │ shadow: no ground     │
            │   (sun geometry)     │   │   length in metres    │
            │ GCPs accepted        │   │ GCPs meaningless      │
            ├──────────────────────┤   ├───────────────────────┤
            │ DSM = DTM + nDSM     │   │ rDSM, relative only   │
            │ metres, absolute     │   │ NO metric value       │
            │ CRS copied exactly   │   │ GeoTIFF, no CRS       │
            └──────────────────────┘   └───────────────────────┘
```

The right branch is **deliberately impoverished**, and that is correct rather than
unfinished. Without a pixel size there is no metre, so the whole branch carries no metric
claim — hard rule 2, enforced in the viewer by the units badge and by a test that greps the
output surface for metre labelling.

---

## The elevation decomposition

The single most important design decision (D6).

```
   DSM(x,y)   =   DTM(x,y)        +   nDSM(x,y)
   ────────       ────────            ─────────
   what we        SRTM 30 m,          what the network
   output         reprojected         predicts, at image
                  to image grid       resolution
   metres ASL     low frequency       high frequency
                  terrain             object height AGL
```

Nothing in a single image encodes absolute elevation above sea level, so we never ask the
network for it. Reasoning in full in `05-domain-reference.md`; corroborated by GAMUS shipping
its height layer as AGL.

### Where each calibration anchor attaches

```
   relative depth (unitless, from the backbone)
            │
            │  fine-tuned head converts to metres AGL
            ▼
   nDSM (metres above ground)
            │
            ├── SRTM  ──────▶ supplies DTM; residual bias check
            ├── shadow ─────▶ h = L·tan(θ); independent metric check on buildings
            └── GCP   ──────▶ robust affine fit where known elevations exist
            │
            ▼
   fusion ──▶ DSM + confidence band
```

The three anchors **cross-check each other**. Agreement narrows the confidence band;
disagreement widens it and is reported rather than hidden. Each is measured alone first, so
we can state which earn their place (D7).

---

## Server layout

```
server/
  depthwizard/
    config.py      canonical GSD, GSD floor and bands, paths, model ids
    io_raster.py   read/write; CRS + affine preserved exactly  [hard rule 5]
    ingest.py      GSD detect, normalise, tile with overlap, reassemble seam-free
    backbone.py    Depth Anything V2 wrapper, frozen
    head.py        nDSM regression head
    srtm.py        fetch, cache, reproject, resample; EGM96/WGS84 datum handling
    shadow.py      sun geometry, shadow detection, h = L·tan(θ)
    gcp.py         RANSAC affine fit to known elevations
    calibrate.py   anchor fusion, confidence band
    dsm.py         orchestrator; writes the provenance sidecar  [hard rule 3]
    mesh.py        DSM -> heightfield/glTF, LOD, texture tiles
    api.py         FastAPI
  train/           datasets.py, train_head.py — identical local and cloud  [D4]
  eval/            run_eval.py, scenes.py, metrics.py — writes 12-eval-results.md
  tools/           fetch_datasets.py, fetch_srtm.py
  tests/           test_raster.py is the non-negotiable one
```

### Why `io_raster.py` is written first

Every number the project ever reports sits on top of the georeferencing being exactly right.
A half-pixel transform error shifts the whole DSM, which corrupts every metric, mislocates
every GCP, misaligns the SRTM lookup, **and** shows up as texture slide in the viewer. It is
the foundation in the literal sense, so it and its round-trip test come before anything else.

---

## Viewer layout

```
viewer/src/
  main.ts       engine + scene bootstrap, render loop
  terrain.ts    heightfield -> mesh, texture projection, LOD
  cameras.ts    flythrough / ground first-person / orbit; state preserved across switches
  probe.ts      click-to-measure height, slope, profile along a line
  overlays.ts   RGB / slope / contour / signed-error texture swap
  validate.ts   predicted vs reference, error heatmap, live metrics
  ui.ts         upload, layer toggles, readouts, the units badge
viewer/electron/
  main.cjs      standalone shell; spawns the bundled server in the full tier
```

Plain TypeScript and Babylon, no component framework (D3) — this is one canvas plus a few
panels.

**Overlays are textures, not shaders.** Slope, contours and error maps are computed
server-side in numpy, where the geospatial context already lives, and swapped onto the
material as images. Far less code than equivalent shader work, and it keeps the maths next to
the data it describes.

**The units badge is the UI enforcement of hard rule 2.** It reads from provenance, not from
a local flag, so there is no code path where a relative scene can present a metre value.

---

## Data contract between server and viewer

The viewer never infers units. It receives them.

```
SceneManifest
  id                  scene identifier
  extent              pixel dimensions, and CRS bounds when georeferenced
  units               "metres_absolute" | "relative_unitless"      <- drives the badge
  crs                 EPSG code, or null
  gsd_in_m            detected input GSD, or null
  gsd_out_m           GSD actually processed at
  vertical_range      min/max of the height field
  objects_resolvable  false when below the GSD floor  [hard rule 7]
  confidence          band in metres, or null when relative
  provenance          backbone id, weights hash, calibration method,
                      anchor sources and counts, git commit, timestamp
  terrain             heightfield / glTF tile URIs
  textures            RGB, slope, contour, error tile URIs
```

`units` is a string the viewer switches on, not a boolean — so "relative" is a first-class
state rather than the absence of a flag, and an unset value cannot silently read as metres.

---

## Where the eval harness sits

Deliberately **outside** the pipeline, entering at the same place a user does:

```
  held-out tiles ──▶ [ the full pipeline, unmodified ] ──▶ DSM
                                                            │
                          reference nDSM ───────────────────┤
                                                            ▼
                                    metrics, per landscape class and GSD band
                                                            │
                                                            ▼
                                              docs/12-eval-results.md
```

It gets no privileged access to reference data and no special inference path (hard rule 4).
Both splits are always reported, and where they disagree the leave-one-city-out number is
the one quoted (D9).

---

## Deployment tiers

| Tier | Contents | Status |
|---|---|---|
| **Dev** | `run.ps1` — FastAPI + Vite dev server | working target |
| **Viewer standalone** | Electron + Babylon, opens a DSM from disk, fully offline | **committed** (G5) |
| **Full standalone** | the above plus a PyInstaller'd inference server, spawned as a child process | **stretch** — multi-GB with CUDA, logged in `11-deferred.md` |

Electron rather than Tauri so the bundle carries its own Chromium and WebGL behaves
predictably on an unknown machine (D3).
