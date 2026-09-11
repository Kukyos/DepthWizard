# Problem statement — official text, verbatim

**This file is the source of truth.** It is the text as published, reproduced without
paraphrase. When there is an argument about scope, this file settles it. Do not edit it
to match what we built; edit what we built to match it.

Two sources are reproduced below: the SIH portal listing, and the README of the
organisation's own reference repository.

---

## Source 1 — SIH portal listing

**Problem Statement ID:** 26175

**Problem Statement Title:** DepthWizard - Single-View Height Estimation and 3D Flythrough

**Description**

Background Accurate Digital Elevation Models (DEMs) and Digital Surface Models (DSMs)
are fundamental to urban planning, disaster management, and military reconnaissance.
Traditionally, elevation data is acquired through stereo-imaging pairs, LiDAR, or
Interferometric Synthetic Aperture Radar (InSAR). These approaches can be
cost-prohibitive, dependent on specific sensor availability, and computationally
intensive. Single-view height estimation offers an agile alternative, but foundational
monocular depth models are trained largely on natural egocentric imagery and predict
relative depth. When applied to remote sensing, they face domain gaps, structural
variations, and a lack of absolute-scale mapping. Converting relative depth into metric
elevation remains a critical challenge, alongside the operational need to transform
static elevation profiles into interactive 3D assets that can be navigated in real time.

Description Develop an end-to-end software pipeline that transforms single-view optical
RGB remote-sensing images into high-precision elevation maps. The framework must support
both non-georeferenced and georeferenced imagery.

• Non-Georeferenced RGB Imagery (for example, PNG or JPG): Produce a Relative Digital
Surface Model (rDSM) for images without spatial metadata.
• Georeferenced RGB Imagery (for example, GeoTIFF): Produce an Absolute Digital Surface
Model (DSM) with metric height values for images containing coordinate-system metadata.

The solution should use a pre-trained monocular depth-estimation backbone to generate
initial relative-depth maps. For georeferenced imagery, a lower-resolution DEM source
such as SRTM or a limited set of Ground Control Points may be used to map scale-agnostic
depth features to absolute metric elevations. For non-georeferenced imagery, relative
height may be used directly in the visualization stage.

After computing the elevation map, the system should project the original optical image
onto a generated 3D terrain mesh and integrate the result with a rendering engine such
as Unity, Three.js, or Babylon.js. The interface should support seamless first-person
navigation and analysis of structural heights and slopes from arbitrary aerial
perspectives.

**Key Milestones**

• Elevation Extraction: Use a robust pre-trained monocular depth model to extract
geometric and structural representations from single-view optical imagery.
• Scale Calibration: Develop a module that converts relative depth to absolute height
using scene-level statistics, low-resolution DEMs, semantic priors, or minimal Ground
Control Points for georeferenced inputs.
• Visualization Layer: Build an immersive, preferably interactive, rendering pipeline
that converts the optical texture and derived depth map into a navigable 3D environment
deployable as a standalone application.

**Evaluation Criteria:**

• DSM Estimation - Accuracy and Validation (50%): Evaluate RMSE, MAE, and correlation
against LiDAR or reference data, including performance stability across urban, sparse,
hilly, and forested landscapes.
• Visualization - Rendering Quality and User Experience (50%): Assess projection
accuracy, visual fidelity, navigability of the 3D flythrough, interface intuitiveness,
software stability, and successful standalone deployment.

**Expected Solution** Deliver a fully integrated software suite with complete source code
and technical documentation. The solution must be deployable as a unified module
containing the following components:

• Elevation Estimation Module: Accept single-view optical satellite imagery in PNG, JPG,
or TIFF format and output a high-fidelity DSM in a standard geospatial format.
• Interactive Visualization Platform: Provide a user-friendly 3D flythrough experience
that lets users upload imagery, visualize reconstructed terrain, and validate estimated
height values against reference datasets.

**Organization:** Indian Space Research Organisation (ISRO)

**Department:** Department of Space / Indian Space Research Organisation

**Category:** Software

**Theme:** Disaster Management

**Youtube Link:** *(blank on the listing)*

**Dataset Link:** Any high-resolution remote-sensing dataset openly available on the
internet may be used for development. Reference dataset:
https://github.com/IMG-PROCESS-SAC/SIH2026/. A lower-resolution DEM source such as SRTM
30 m may be used to map scale-agnostic depth features to absolute metric elevations.
During final evaluation, ISRO RGB-band optical satellite i

> **Note on the truncation.** The listing's Dataset Link field is cut off mid-word at
> "optical satellite i". The sentence almost certainly continues "...imagery will be
> used" or similar, but **we have not seen the rest of it.** Re-check the portal before
> submission. The operative fact we can rely on: final evaluation uses ISRO RGB-band
> optical satellite imagery, which is why GSD handling is a first-class concern
> (`docs/05-domain-reference.md`).

---

## Source 2 — the organisation's reference repository

Repository: `https://github.com/IMG-PROCESS-SAC/SIH2026`
Repository name: `SIH-DepthWizard-2026`
Last updated: 2026-09-09. Contents as of 2026-09-11: **`README.md` only — no data.**

Reproduced verbatim:

> # SIH2026
> ## Problem Statement ID: 26175
> ## Problem Statement: DepthWizard - Single-View Height Estimation and 3D Flythrough
> ### 🗄️ Recommended Dataset: GAMUS
> To train, test, and validate the monocular depth-estimation backbone for this pipeline,
> the GAMUS Dataset is the recommended open-source foundation. It provides the essential
> paired data required to translate 2D satellite imagery into accurate depth models.
>  * Dataset Name: GAMUS
>  * Provider: Earthflow
>  * Platform: Hugging Face
>  * Access Link: https://huggingface.co/datasets/earthflow/GAMUS
>
> **A lower-resolution DEM source such as SRTM 30 m may be used to map scale-agnostic
> depth features to absolute metric elevations.**
>
> **NOTE** -> While GAMUS is recommended, you are free to utilize any open-source dataset
> containing remote-sensing depth data, provided it supports both relative depth training
> and metric scale calibration.
> > Dataset Application Strategy:
> > Use this data to overcome the domain gap between natural egocentric imagery (what
> > most foundational models are trained on) and top-down remote sensing imagery. The
> > dataset will be critical for training your model to handle structural variations
> > across urban, sparse, hilly, and forested landscapes.
> >
> ### 📖 Background
> Accurate Digital Elevation Models (DEMs) and Digital Surface Models (DSMs) are
> fundamental to urban planning, disaster management, and military reconnaissance.
> Traditional elevation data acquisition methods—such as stereo-imaging pairs, LiDAR, or
> Interferometric Synthetic Aperture Radar (InSAR)—are often cost-prohibitive,
> computationally intensive, and dependent on specific sensors.
> Single-view height estimation offers an agile alternative. However, current foundational
> monocular depth models predict relative depth and struggle with remote sensing
> applications due to domain gaps and a lack of absolute-scale mapping. Converting this
> relative depth into metric elevation, and transforming those profiles into interactive
> 3D flythrough assets, remains the primary challenge.
> ### ⚙️ System Pipeline Description
> Develop an end-to-end software pipeline that transforms single-view optical RGB
> remote-sensing images into high-precision elevation maps. The system must adapt based on
> the metadata of the uploaded imagery:
>  * Non-Georeferenced RGB Imagery (PNG, JPG): Produce a Relative Digital Surface Model
>    (rDSM) for images without spatial metadata, using relative height directly in the
>    visualization stage.
>  * Georeferenced RGB Imagery (GeoTIFF): Produce an Absolute Digital Surface Model (DSM)
>    with metric height values. Use a lower-resolution DEM source (e.g., SRTM) or limited
>    Ground Control Points to map scale-agnostic depth features to absolute metric
>    elevations.
> 3D Rendering & Visualization:
> After computing the elevation map, project the original optical image onto the generated
> 3D terrain mesh. Integrate this with a robust rendering engine (such as Unity, Three.js,
> or Babylon.js) to support seamless first-person navigation, structural height analysis,
> and slope assessment from arbitrary aerial perspectives.
> ### 🎯 Key Milestones
>  * Elevation Extraction: Deploy a robust pre-trained monocular depth model to extract
>    geometric and structural representations from single-view optical imagery.
>  * Scale Calibration: Build a conversion module to map relative depth to absolute height
>    using scene-level statistics, low-resolution DEMs, semantic priors, or minimal Ground
>    Control Points.
>  * Visualization Layer: Create an immersive, interactive rendering pipeline that converts
>    the optical texture and depth map into a navigable 3D environment deployable as a
>    standalone application.
> ### 📊 Evaluation Criteria
> | Category | Weight | Key Metrics & Focus Areas |
> |---|---|---|
> | DSM Estimation Accuracy | 50% | RMSE, MAE, and correlation against LiDAR/reference data. Must demonstrate performance stability across urban, sparse, hilly, and forested landscapes. |
> | Rendering & UX | 50% | Projection accuracy, visual fidelity, 3D flythrough navigability, interface intuitiveness, software stability, and successful standalone deployment. |
> ### 📦 Expected Solution Deliverables
> Deliver a fully integrated software suite, including complete source code and technical
> documentation. The module must contain two core components:
>  * Elevation Estimation Module: Accepts single-view optical satellite imagery (PNG, JPG,
>    or TIFF) and outputs a high-fidelity DSM in a standard geospatial format.
>  * Interactive Visualization Platform: A user-friendly interface that allows users to
>    upload imagery, seamlessly fly through the reconstructed 3D terrain, and validate
>    estimated structural heights against reference datasets.

---

## What the two sources add beyond each other

The reference repo is not a restatement. It adds four operative facts the portal
listing does not carry:

1. **GAMUS is the recommended dataset**, by name, provider and link. The portal only
   says "any openly available dataset".
2. **Semantic priors are named as a calibration route** in the milestone text — and
   GAMUS ships a semantic class layer, so this is an intended pairing, not a
   coincidence.
3. **"Deployable as a standalone application"** appears in the milestone text as well as
   the evaluation criteria, so it is a requirement and not just a scoring nicety.
4. The evaluation criteria are given as a **weighted table**, confirming the 50/50 split
   is literal and not an approximation.

## Observations about the brief that shape the build

These are our readings, not the brief's words. Kept here because they follow directly
from the text above.

- The brief **states the core difficulty itself**: foundational models "predict relative
  depth" and face "domain gaps" and "a lack of absolute-scale mapping". It is not asking
  us to call a depth model. It is asking us to fix those three things.
- "Performance stability across urban, sparse, hilly, and forested landscapes" is an
  explicit requirement to report **stratified** numbers. One flattering average does not
  satisfy it. See `docs/04-targets.md`.
- "Validate estimated height values against reference datasets" places validation
  **inside the visualization platform**, as a user-facing feature. It is not a developer
  tool we run offline.
- Final evaluation on **ISRO** imagery means the input GSD at test time is not the GSD
  we train on. See the GSD discussion in `docs/05-domain-reference.md`.
