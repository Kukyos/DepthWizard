# Decisions — settled and open

A logged default here is not a guess. Take it and move on. Reopen it only with a reason,
and record the reason.

---

## Settled

### D1 — Scope: the full build, not a nine-day sprint
**Decided 2026-09-11.** The 20 September 2026 deadline is the **idea submission** round;
selection and the full build follow. So we plan all six phases properly rather than
optimising for nine days.

*Consequence:* the 80 GB dataset download and cloud fine-tuning are both affordable.
Phase 0 starts the long-lead items immediately so they complete in the background.

### D2 — Fine-tune an nDSM head; do not ship zero-shot only
**Decided 2026-09-11.** Half the marks are accuracy, and the domain gap is the brief's own
stated problem. Calibration alone cannot fix a backbone that reports albedo as depth.

*Consequence:* GAMUS download and a cloud GPU are both required, not optional. The
zero-shot baseline is still built and kept — it is the evidence the fine-tuning worked
(`04-targets.md`).

### D3 — Viewer: Babylon.js, plain TypeScript, Vite. Electron for standalone.
**Decided 2026-09-11.** The brief permits Unity, Three.js or Babylon.js.

Babylon over Unity: Unity's scene assembly is editor-driven — wiring objects into inspector
slots, prefabs, build settings — which cannot be iterated on in a text workflow. Babylon is
code, runs in a browser, and is debuggable directly.

Babylon over Three.js: for this specific job Babylon is *less code*. Heightmap terrain,
purpose-built flythrough and orbit cameras, LOD, a GUI layer and a scene inspector are all
in the box; Three.js would need them hand-rolled.

Plain TypeScript, **no React and no Tailwind** — a deliberate departure from PS 26047's
stack. This app is one canvas plus a few panels; a component framework would add a layer
and buy nothing.

Electron over Tauri for the standalone: Electron bundles its own Chromium, so WebGL
behaviour on an unknown judge's machine is predictable rather than dependent on their
installed WebView2 version. The larger artefact is worth the removed risk.

### D4 — Hardware: local RTX 4060 for development and inference, cloud GPU for training
**Decided 2026-09-11.** 8 GB VRAM is enough for inference and for a frozen-encoder
baseline, but not for comfortable fine-tuning with a partial unfreeze.

*Consequence:* the training script must run unchanged in both places. No machine-specific
paths, no hardcoded batch sizes — everything through `config.py`.

### D5 — Backend: Python 3.14 / FastAPI
**Decided 2026-09-11, assumed rather than asked.** Forced by the domain, not inherited:
Depth Anything V2 is PyTorch, and GeoTIFF/CRS handling is rasterio/GDAL. There is no
credible non-Python path for either.

Verified available for cp314: rasterio 1.5.1, numpy 2.5.3, scipy 1.18.1, fastapi 0.141.1,
pillow 12.3.0, opencv-python-headless.

### D6 — Elevation decomposition: `DSM = DTM(SRTM) + nDSM(predicted)`
**Decided 2026-09-11.** Nothing in a single image encodes absolute elevation above sea
level, so we do not ask the network for it. SRTM supplies terrain; the network supplies
object height above ground.

Corroborated by the recommended dataset: GAMUS ships its height layer as **AGL**, so the
officially recommended training data trains the nDSM term specifically. Full reasoning in
`05-domain-reference.md`.

### D7 — Three calibration anchors, measured independently, then fused
**Decided 2026-09-11.** SRTM terrain, shadow geometry, and GCP fitting. Each is evaluated
alone against reference before any fusion, so we can state which ones earn their place
instead of asserting that all three help. Fusion emits a confidence band, and the band's
empirical coverage is itself checked.

### D8 — GSD is detected, normalised, and refused below a floor
**Decided 2026-09-11.** Accuracy is a function of pixel size, and evaluation GSD is unknown
and will differ from GAMUS's 0.33 m. Below the floor, object heights are not present in the
data; we emit terrain only and flag it. Hard rule 7.

### D9 — Two eval splits, and the pessimistic one is what we quote
**Decided 2026-09-11.** The official GAMUS split shares cities between train and test, which
rewards memorising city appearance. Evaluation is on ISRO imagery of another country. So the
harness reports both the official split and a leave-one-city-out split, and **where they
disagree we quote leave-one-city-out.**

### D10 — Output is GeoTIFF for both paths
**Decided 2026-09-11.** The brief asks for "a standard geospatial format". A CRS-less
GeoTIFF is still a valid raster, so the relative path uses the same container with no CRS
attached and no metric labelling. One writer, one reader, no second format to maintain.

### D11 — Docs are the primary output, numbered as in PS 26047
**Decided 2026-09-11.** Carried over deliberately: it is the convention that made the
previous project defensible under questioning. `12-eval-results.md` is generated and never
hand-edited; `10-unsourced.md` and `11-deferred.md` are updated in the same pass as the
shortcut that created the entry.

---

## Open

### O1 — Which ISRO sensor and GSD does final evaluation use?
**Blocks:** sizing the GSD floor honestly; knowing whether building-level heights are even
recoverable at test time.
**Default until answered:** read GSD from the file; set the floor from a measured
GSD-degradation sweep rather than an assumption.
**Route:** the portal listing is truncated mid-sentence; re-check it, and ask the SPOC if
one is published.

### O2 — Where does terrain-diverse training data come from?
**Blocks:** G3 — half the brief's required stratification. **The largest open risk.**
**Default until answered:** report `NO DATA` for hilly and forested rather than estimating.
**Candidates to assess in Phase 0:** DFC2019/US3D (Jacksonville and Omaha add relief),
GeoNRW, ISPRS Vaihingen, and any openly licensed Indian-terrain DSM. The brief explicitly
permits any openly available dataset.

### O3 — GAMUS class index → class name mapping
**Blocks:** semantic priors as a calibration route; landscape labelling for stratification.
**Default:** `PLACEHOLDER` in code, logged in `10-unsourced.md`.
**Route:** empirical — cross-tabulate class index against measured AGL statistics. Building
and tree must show high mean AGL; water and road must sit near zero. This identifies indices
from the data rather than by assumption.

### O4 — SRTM access route
**Options:** OpenTopography API (needs a key, simple) versus direct tile download (no key,
more plumbing).
**Default:** whichever works without an account; cache tiles under `data/srtm/` either way
so the viewer stays offline.

### O5 — Cloud GPU provider and instance
**Blocks:** Phase 3 only.
**Default:** decide when Phase 3 starts; keep the training script provider-agnostic so this
stays a late decision.

### O6 — Confidence band method
**Options:** anchor disagreement spread (cheap, interpretable), MC-dropout, or an ensemble.
**Default:** anchor disagreement for v1 — it is nearly free and directly interpretable.
Revisit if empirical coverage fails the calibration check in `04-targets.md`.

### O7 — Terrain LOD approach in the viewer
**Default:** start with Babylon's heightmap ground, which is one call. Move to a tiled
quadtree only when tile size demands it, and confirm the DynamicTerrain extension's current
package name before relying on it.

### O9 — What licence does the source code carry?
**Blocks:** nothing technical, but the repository is public and currently **unlicensed**,
which means default copyright applies and nobody may legally reuse it. SIH submissions are
usually expected to be shareable.
**Default until answered:** none. A licence is a legal choice with real consequences and is
the project owner's to make, not a default to guess at. The README states the position
plainly rather than pointing at a file that does not exist.
**Route:** pick one (MIT and Apache-2.0 are the usual choices for a hackathon submission;
Apache-2.0 additionally grants patent rights), add `LICENCE`, and update the README.

### O8 — Does the standalone bundle include inference?
**Default:** two tiers. Viewer-only Electron installer is **committed**; the full bundle
with PyInstaller'd PyTorch is a **stretch**, logged in `11-deferred.md` from day one so it
is never mistaken for done. A CUDA-enabled bundle is multi-GB.
