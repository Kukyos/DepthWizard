# Novelties — what makes this more than a wrapper around a depth model

Proposed differentiators, what each is worth, and which survive contact with the gates in
`03-requirements.md`. A novelty that does not move a scored criterion is decoration.

---

## N-01 · Shadow geometry as a metric anchor

**Status: planned, Phase 2.** The brief's stated core challenge is converting relative depth
to metric elevation. Every route it suggests — SRTM, GCPs, scene statistics — needs an
external data source. Shadows do not.

For a vertical structure casting a shadow of ground length `L` under solar elevation `θ`:

```
h = L · tan(θ)
```

Plane geometry. A height in **metres**, from one image, with no DEM, no control points and
no training. Solar geometry comes from product metadata or from acquisition time plus
scene-centre lat/lon.

**Why it scores:** it is the only calibration route that works on an image with nothing
attached to it, and it cross-checks the SRTM and GCP anchors rather than competing with them.

**Known limits, to be measured not hand-waved:** shadows falling on sloped ground bias `L`;
shadows occluded by neighbouring structures truncate; dense urban cores have overlapping
shadows; `tan(θ)` is unstable as the sun approaches overhead; cloud shadow is a false
positive.

---

## N-02 · Shadow ray-casting as verification, not just measurement

**Status: proposed. Stronger than N-01 and supersedes it as the headline.**

N-01 measures one shadow at a time and needs a clean, isolated, unoccluded example. The
generalisation: once we have a height field and know where the sun is, we can **render the
shadows that height field would cast** and compare them against the shadows actually present
in the photograph.

```
    DSM + sun position  ──▶  ray-march toward the sun  ──▶  predicted shadow mask
                                                                     │
                            observed shadow mask  ◀── image          │
                                                        └── compare ─┘
```

For each surface point, step a ray toward the sun across the height field; if anything
occludes it, that point is in shadow. This is a standard horizon/shadow trace over a
heightmap — cheap, and parallel over pixels.

**Why this is better than N-01:**

| | N-01 shadow length | N-02 shadow rendering |
|---|---|---|
| Needs isolated structures | yes | no |
| Works on complex shapes | no | yes |
| Uses occluded / overlapping shadows | no | yes, they are *predicted* too |
| Produces | one height per shadow | agreement over the whole scene |
| Can correct the DSM | no | yes — the disagreement is a gradient |

**The strong version: analysis by synthesis.** Shadow agreement is a differentiable function
of the height field. Heights that are too low cast shadows that are too short, and the
mismatch says which direction to move. So instead of only *measuring* with shadows, the
height field can be *optimised* until the shadows it casts match the shadows observed. This
is inverse rendering, and it is a well-established idea (shape-from-shadow) that nobody
applying a foundation depth model to this problem will bother to do.

It also gives a scored criterion for free: the brief's visualization half asks for
"projection accuracy" and "visual fidelity". A scene whose rendered shadows line up with the
shadows in the draped photograph is *visibly* correct in a way a judge can check in two
seconds, with no metrics at all.

**Credit:** proposed by the project owner, 2026-09-15, as "make tunable models and raytrace
to verify the shadows". Recorded because it is a better idea than the one it replaces.

### Risks worth stating before building it

- **Shadow detection is its own problem.** Dark roofs, dark water and wet tarmac all look
  like shadow. Needs its own validation, and a false shadow mask would corrupt the
  optimisation it feeds.
- **Sun geometry must be right.** An error in azimuth rotates every predicted shadow and
  would push the optimisation confidently wrong.
- **It can only see what casts shadow.** Flat ground and shadowless interiors get no signal,
  so this constrains the DSM, it does not determine it.
- **GAMUS has no acquisition metadata and no georeferencing** (D-03, U-06), so this cannot
  be validated on the primary dataset. It needs georeferenced imagery with a timestamp.

---

## N-03 · Parametric object models with tunable height

**Status: proposed, speculative.** Fit simple parametric primitives — a box for a building,
a crown-shaped blob for a tree — with height as the free parameter, then tune the parameters
until the rendered result matches the image (and, with N-02, its shadows).

**Why it is interesting:** it injects a shape prior the network lacks. Buildings have flat
roofs and vertical walls; the current output gives them melted-mound roofs that slope into
the street (visible in any ground-level view of the baseline scene). A box prior would fix
that by construction, and would make roof edges sharp — which the evaluation criteria reward
under "visual fidelity" and which our gradient loss is only approximating.

**Why it is risky:** it is a second, parallel reconstruction system, and it fails on anything
not shaped like its primitives. Indian urban form — irregular rooflines, dense unplanned
settlement — is exactly where a box prior breaks. It would also need instance segmentation
to know where one building ends and the next begins, which is a whole subsystem.

**Verdict:** do not build this as the main path. It is a good *refinement* pass once a DSM
exists and a good demo, but building the pipeline around primitives would be betting the
project on a prior that may not hold on the evaluation imagery.

---

## N-04 · Physically correct sky and sun

**Status: planned, Phase 4.** Place the viewer's sun at the scene's actual azimuth and
elevation, derived from the same solar geometry N-01 and N-02 use.

Most of what this buys is credibility rather than accuracy: the shadows in the render line up
with the shadows in the photograph, so the lighting is not decoration but the physics the
heights were measured with. It is one of the cheapest visible wins available and it directly
serves "visual fidelity".

Cost is near zero once solar geometry exists for N-01.

---

## N-05 · GSD-aware refusal

**Status: planned, floor to be measured in Phase 3.** Detect ground sample distance, normalise
to the training scale, report accuracy per GSD band, and **decline to emit object heights**
below a measured floor.

**Why it scores:** every other submission will produce confident numbers at any resolution.
At several metres per pixel a building spans under two pixels and its height is not present
in the data — so those numbers are fabricated. A system that knows its own limit and says so
reads as engineering maturity to anyone with a remote-sensing background. Hard rule 7.

---

## N-06 · Terrain and objects estimated separately

**Status: built into the architecture (D6).** `DSM = DTM(SRTM) + nDSM(predicted)`. Not novel
in the literature, but it is the difference between asking the network for something it can
do and asking it for something no single image contains. Corroborated by the recommended
dataset shipping its heights as AGL.

---

## N-07 · The measured honesty layer

**Status: built.** Provenance on every output; the relative/absolute distinction enforced in
the file, the API and the UI; two eval splits with the pessimistic one quoted; `NO DATA`
where we have none; a published zero-shot baseline including its failures.

Not a feature, and it will not be on anyone's slide. But it is what lets every number in the
submission survive a hostile question, and the accuracy half of the marks is 50%.

---

## Cut

| Idea | Why not |
|---|---|
| Stereo or multi-view | The brief says single-view. It would answer an easier question. |
| Off-nadir lean as an anchor | Real, but orthorectified products have it removed by construction. Only helps on raw imagery we may never see (S-02). |
| Delivering semantic segmentation | We use GAMUS's class layer as a prior and for stratification. Shipping a land-cover map is scope creep. |
