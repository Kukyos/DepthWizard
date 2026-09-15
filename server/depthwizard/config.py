"""Configuration for the whole pipeline.

Everything tunable lives here rather than scattered through the modules, because the
training script has to run unchanged on this laptop and on a cloud GPU (docs/06-decisions.md
D4). Values that differ per machine come from the environment, not from code.

Values marked PLACEHOLDER are not yet sourced and are tracked in docs/10-unsourced.md.
They are structurally present and visibly unsourced, never quietly guessed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv is optional; the defaults below are all usable
    def load_dotenv(*_a, **_k) -> bool:
        return False

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _env_path(name: str, default: str) -> Path:
    p = Path(os.getenv(name) or default)
    return p if p.is_absolute() else ROOT / p


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


# --------------------------------------------------------------------------- paths
GAMUS_ROOT = _env_path("GAMUS_ROOT", "data/gamus")
SRTM_CACHE_DIR = _env_path("SRTM_CACHE_DIR", "data/srtm")
WEIGHTS_DIR = _env_path("WEIGHTS_DIR", "data/weights")
SAMPLES_DIR = _env_path("SAMPLES_DIR", "data/samples")
DOCS_DIR = ROOT / "docs"

# The harness writes here. Never hand-edited (hard rule 1).
EVAL_RESULTS = DOCS_DIR / "12-eval-results.md"


# ----------------------------------------------------------------- ground sampling
# GAMUS is 0.33 m/px (paper, arXiv 2305.14914). The backbone is trained at that scale,
# so every input is resampled to it before inference and the original GSD is recorded
# in provenance. A model run at a GSD it did not train on degrades silently.
CANONICAL_GSD_M = 0.33

# Below this, a building spans under ~2 px and its height is not present in the data.
# Output terrain only and flag objects_not_resolvable (hard rule 7).
#
# PLACEHOLDER: this must come from the measured GSD-degradation sweep in Phase 3, not
# from a guess. 2.0 is a provisional stand-in chosen only so the code path exists and
# is exercised by tests. Do not quote it as a finding. See U-02, and D8.
GSD_FLOOR_M = 2.0
GSD_FLOOR_IS_PLACEHOLDER = True

# Accuracy is reported per band, not as one average (docs/04-targets.md), because
# evaluation GSD is unknown and differs from training GSD.
GSD_BANDS_M: tuple[tuple[float, float], ...] = (
    (0.0, 0.5),
    (0.5, 1.0),
    (1.0, 2.0),
    (2.0, 6.0),
    (6.0, float("inf")),
)


# ----------------------------------------------------------------------- landscape
# The four classes the brief requires stratified reporting across.
LANDSCAPE_CLASSES: tuple[str, ...] = ("urban", "sparse", "hilly", "forested")

# We have no hilly or forested data (D-02). Rows for these read NO DATA rather than an
# estimate. This tuple exists so the harness can assert that rather than silently
# producing an empty average.
LANDSCAPE_WITHOUT_DATA: tuple[str, ...] = ("hilly", "forested")


# ------------------------------------------------------------------------- tiling
TILE_SIZE = 1024          # matches GAMUS tiles exactly
TILE_OVERLAP = 128        # blended on reassembly so seams do not appear as ridges


# -------------------------------------------------------------------------- model
# PLACEHOLDER: pin an exact checkpoint and its hash in Phase 0. Every DSM records which
# weights produced it (hard rule 3), and "latest" is not a provenance. See U-03.
BACKBONE_ID = os.getenv("DEPTH_BACKBONE_ID") or "PLACEHOLDER"
BACKBONE_SHA256 = os.getenv("DEPTH_BACKBONE_SHA256") or "PLACEHOLDER"
TORCH_DEVICE = os.getenv("TORCH_DEVICE") or ""   # blank = autodetect


# ---------------------------------------------------------------------- GAMUS data
# Verified by inspecting heights/test/DC_03_26_AGL.h5 on 2026-09-11: every file holds a
# single HDF5 dataset named 'image', including the height and class files.
GAMUS_H5_KEY = "image"
GAMUS_GSD_M = 0.33
GAMUS_CITIES: tuple[str, ...] = ("DC", "NYC", "PHL")   # the HF mirror; paper lists five

# Measured AGL clamp. NOT established to be a nodata sentinel -- see U-05. Treated as
# valid-but-clamped until measured across many tiles.
GAMUS_AGL_CLAMP_M = -5.0

# Resolved empirically on 2026-09-15 from 3 val tiles (tools/resolve_class_legend.py).
# The paper names six classes but not their order; the indices below are the paper's listed
# order, which four independent checks confirm rather than assume:
#
#   3  roofs are the only near-neutral surface in the scene (B-R = -2 to -3.5) and sit at
#      4.5-7.9 m median AGL -- house height
#   5  forms the connected linear street network in the class map, at 0.0 m median AGL
#   6  10-26 m median AGL, brown not green because the imagery is leaf-off winter
#   4  appears only at the -5 m AGL clamp, which is what water does to LiDAR returns
#
# 1 vs 2 (ground vs low-vegetation) is the least distinctive pair: both sit at ~0 m and
# differ mainly in brightness. Held as the paper's order; recheck if a metric depends on
# separating them. 0 is not one of the six named classes and appears at <0.2% -- treated
# as unlabelled background, not silently merged into ground.
GAMUS_CLASS_NAMES: dict[int, str] = {
    0: "background",
    1: "ground",
    2: "low-vegetation",
    3: "building",
    4: "water",
    5: "road",
    6: "tree",
}
GAMUS_CLASS_LEGEND_IS_PLACEHOLDER = False
# Sample size behind the legend above. Small; state it alongside any metric that rests on
# the legend rather than letting 3 tiles read as settled fact.
GAMUS_CLASS_LEGEND_TILES = 3
GAMUS_BUILDING_CLASS = 3          # for building-only RMSE (docs/04-targets.md)
GAMUS_BACKGROUND_CLASS = 0        # excluded from metrics


# ------------------------------------------------------------------------- outputs
@dataclass(frozen=True)
class Units:
    """How a height field is to be interpreted.

    A string-valued state rather than a boolean, so 'relative' is a first-class case and
    an unset value cannot silently read as metres (hard rule 2).
    """

    METRES_ABSOLUTE = "metres_absolute"      # elevation above sea level: DTM + nDSM
    METRES_AGL = "metres_agl"                # height above the ground beneath: nDSM only
    RELATIVE_UNITLESS = "relative_unitless"  # ordering with no scale at all

    #: Units that carry real metres. Relative is deliberately not in here.
    METRIC = ("metres_absolute", "metres_agl")


DSM_DTYPE = "float32"
DSM_NODATA = -9999.0


# ------------------------------------------------------------------------- server
SERVER_HOST = os.getenv("SERVER_HOST") or "127.0.0.1"
SERVER_PORT = _env_int("SERVER_PORT", 8000)
VIEWER_PORT = _env_int("VIEWER_PORT", 5173)

# Guards against a 50000x50000 TIFF ending the demo. "Software stability" is in the
# evaluation criteria.
MAX_INPUT_MEGAPIXELS = _env_int("MAX_INPUT_MEGAPIXELS", 400)


# ------------------------------------------------------------------------ training
TRAIN_BATCH_SIZE = _env_int("TRAIN_BATCH_SIZE", 4)
TRAIN_TILE_SIZE = _env_int("TRAIN_TILE_SIZE", 512)
TRAIN_NUM_WORKERS = _env_int("TRAIN_NUM_WORKERS", 4)


# ------------------------------------------------------------------- regression gates
# run.ps1 -Test fails if a primary metric regresses by more than this fraction against
# the last committed results (docs/04-targets.md).
MAX_METRIC_REGRESSION = 0.10

# A stated +/-1 sigma confidence band should contain ~68% of errors. If empirical
# coverage falls outside this range the band is miscalibrated, which is worse than no
# band at all because it invites misplaced trust.
CONFIDENCE_COVERAGE_RANGE = (0.60, 0.75)


@dataclass(frozen=True)
class Placeholder:
    """One unsourced value, so the harness can refuse to publish numbers that depend on it."""

    key: str
    doc_ref: str
    blocks: str


def placeholders() -> list[Placeholder]:
    """Every value that is still unsourced.

    The harness calls this and labels any dependent result, rather than letting a
    provisional constant quietly become a published finding.
    """
    out: list[Placeholder] = []
    if GSD_FLOOR_IS_PLACEHOLDER:
        out.append(Placeholder("GSD_FLOOR_M", "U-02", "the refusal floor (hard rule 7)"))
    if GAMUS_CLASS_LEGEND_IS_PLACEHOLDER:
        out.append(
            Placeholder("GAMUS_CLASS_NAMES", "U-01", "semantic priors, landscape labelling")
        )
    if BACKBONE_ID == "PLACEHOLDER":
        out.append(Placeholder("BACKBONE_ID", "U-03", "provenance completeness (hard rule 3)"))
    return out
