# What we're building, in plain words

No jargon in this file. If a term is unavoidable it is explained where it appears. The
precise version is in `05-domain-reference.md`.

---

## The problem, as a person would describe it

You have one photograph taken from a satellite, looking straight down at a city. You can
see roofs, trees, roads, cars. What you **cannot** see is how tall anything is.

That matters more than it sounds. For flood modelling you need to know which buildings sit
low. For disaster response you need to know how many storeys are standing. For urban
planning you need building volumes. Today that information comes from LiDAR — a laser
scanner flown over the area — or from stereo pairs, or from radar. All three are expensive,
need specific equipment, and cannot be done retroactively on an image you already have.

So: can we recover height from **one ordinary photograph**? Mostly yes, and the gap
between "mostly" and "reliably" is the project.

## What goes in, what comes out

**In:** one image. Either a plain photo (PNG or JPG) with no location information, or a
GeoTIFF — the same photo plus a header saying exactly where on Earth it sits and how big
each pixel is.

**Out, part one — the height map.** Same grid of pixels, but each pixel now holds a number:
the elevation at that point. Open it as a greyscale picture and you see the city's height
as brightness — towers white, houses grey, roads black. Saved as a GeoTIFF so it opens in
QGIS, ArcGIS or anything else a surveyor uses.

Which *kind* of number depends on what came in, and the distinction is strict:

| You gave us | You get back | Example reading |
|---|---|---|
| A GeoTIFF, with location | **Absolute heights in metres** | "that roof is 312.4 m above sea level" |
| A plain PNG or JPG | **Relative heights, no units** | "that roof is higher than its neighbour" — and **no number in metres anywhere** |

That second row is a hard rule, not a limitation we are apologising for. Without knowing
where the image is or how big a pixel is, metres are unknowable. Printing a confident
"14 m" would be a fabrication, so the system refuses to — in the file, in the viewer, in
every tooltip.

**Out, part two — the 3D scene.** The height map becomes real 3D terrain, and the original
photo is draped over it like a tablecloth over a pile of books. Now you can fly through it,
look along a street, click a roof and read its height, see slopes shaded, and compare
against real survey data if you have it.

## Why it is hard

Two separate difficulties. The brief names both.

**First: a top-down photo barely contains height.** Looking straight down, a 50-storey
tower and a circle painted on the tarmac of the same size look remarkably similar. Almost
all the cues humans use for depth come from *perspective* — parallel lines converging,
distant things looking smaller, objects standing on a visible floor. From 500 km up,
looking straight down, there is no perspective. Everything is the same distance away.

The AI models that do "estimate depth from one photo" were trained on phone photos of rooms
and streets, where perspective does the work. Give one a satellite image and it partly
reports *brightness* as depth — a white roof reads "close", dark asphalt reads "far". It is
not stupid; it is answering a different question from the one we asked.

**Second: it only knows *more* and *less*, never *how much*.** Even when the model
correctly decides one thing is higher than another, it has no metres. It is the difference
between "Ravi is taller than Sita" and "Ravi is 174 cm". Turning the first into the second,
from a single image, is what the brief calls the critical challenge.

## How we address both

**The domain gap** — we take the pre-trained model's general visual understanding but
retrain the part that outputs height, using a dataset of satellite photos paired with real
laser-measured heights (GAMUS, which ISRO's own reference repo recommends). The model keeps
what it knows about edges, shapes and materials, and learns afresh what "height" means when
you are looking straight down.

We also **measure how bad it is beforehand**, and keep that number. "The off-the-shelf
model scores X, ours scores Y" is the evidence that the work did something. Skipping the
embarrassing baseline would throw away the proof.

**The missing metres** — three independent routes, because each fails in different
conditions:

1. **Split terrain from buildings.** Free coarse elevation data (SRTM) covers the whole
   planet at 30 m per pixel. Far too coarse to see a building — but perfectly good at
   "this neighbourhood sits 340 m above sea level". So SRTM supplies the ground, the
   network supplies how far things stick up from it, and the two add together. Each source
   does only what it is actually good at.

2. **Measure the shadows.** This one is just geometry, no AI. If you know where the sun
   was — and satellite images record that — then a building's shadow length tells you its
   height directly: `height = shadow length × tan(sun angle)`. A real measurement in real
   metres, from one image, needing no other data at all. It is the neatest answer to the
   brief's core challenge, and almost nobody will do it.

3. **Use a few known points.** If a user can supply even a handful of locations whose true
   elevation is known, we fit the relative values onto those and get metres for the whole
   scene.

All three run where possible, and they **check each other**. When they agree, confidence is
high and we say so. When they disagree, that is reported too rather than hidden behind a
single number.

## A walkthrough

Asha works in a state disaster management authority. A river is rising and she needs to
know which parts of a town sit low enough to flood first. She has a recent satellite image.
She has no LiDAR survey, no budget for one, and no time.

1. She opens DepthWizard and drags the GeoTIFF in.
2A badge appears: **"Georeferenced — EPSG:32644, 0.5 m/px. Absolute metres available."**
   The system read that from the file; she did not have to know it.
3. Processing runs. The height map is written next to her image as a GeoTIFF she can load
   into the GIS she already uses.
4. The 3D scene loads — her town, the real photo draped over real terrain. She switches to
   the flythrough camera and follows the riverbank at rooftop level.
5. She clicks a building. The readout says **"14.2 m ± 1.8 m — above ground. Scale from:
   SRTM + 3 shadow anchors (agreeing)."** Not a bare number: a number, its uncertainty, and
   where the scale came from.
6. She turns on the slope overlay and sees the low-lying quarter immediately.
7. She has two survey benchmarks from an old report. She drops them in as control points;
   the validation panel shows her the error at those points and the scene recalibrates.

Nothing here claims to replace a LiDAR survey. It claims to give her a defensible estimate
this afternoon instead of a precise one next quarter — and to be honest about how
defensible.

## What it is not

- **Not X-ray vision.** It does not see underground or inside buildings. It estimates the
  height of the surface you can see.
- **Not a LiDAR replacement.** It is an estimate with stated error bars. Where survey-grade
  accuracy is legally required, this is not it.
- **Not a stereo or multi-view system.** One image, by design. That constraint is the point.
- **Not a map viewer.** It does not stream basemaps. It reconstructs and displays the one
  image you gave it, fully offline.

## The two deliverables

The brief asks for exactly two components, and marks them 50/50:

**1. Elevation Estimation Module.** Takes PNG, JPG or TIFF. Outputs a DSM in a standard
geospatial format, with a provenance record saying which model produced it, how it was
scaled to metres, and how confident it is.

**2. Interactive Visualization Platform.** Upload imagery, fly through the reconstructed
terrain, read structural heights and slopes, and **validate against reference data** — the
brief puts validation inside the app, as something the user does, not something we run
offline. Deployable as a standalone application.
