"""Scale calibration: turn predicted heights into better-trusted heights, and say how much.

The brief calls converting relative depth to metric elevation the critical challenge. The
fine-tuned decoder already emits metres, so the problem here is narrower and was arrived at
by measurement rather than assumption: on a city it has not seen, the decoder's error is
mostly a **constant offset**, because it learned the training city's height prior.

Measured on 24 held-out Washington DC tiles, from a Philadelphia-trained decoder:

    as-is                      RMSE 8.94 m
    + one offset per scene     RMSE 6.56 m     27% better
    + one offset and one scale RMSE 6.32 m     29% better

**That 27% is a mirage, and this module deliberately declines to collect it.** Breaking the
same correction down by land cover:

    class        RMSE as-is    RMSE with the "best" offset
    ground           1.13 m                       6.75 m
    building         6.04 m                       6.16 m
    tree            13.22 m                       8.27 m

The offset makes ground six times worse in order to make canopy better. It wins on RMSE only
because canopy is about half the pixels. The output is less correct everywhere except trees,
and the "improvement" is an artefact of pixel counts.

It is also not computable in practice: the offset that achieves it is mean(reference -
prediction), which requires the answer.

So the anchors here estimate an offset only from evidence that actually constrains the scene,
and return nothing when they have none. In particular the ground anchor, run on a
Philadelphia-trained decoder over Washington DC, correctly applies **+0.00 m** -- because the
decoder already puts ground at the right height. The error is not in the floor.

**What the error actually is.** The residual is class-dependent: about +0.5 m on ground, -3 m
on buildings, -14 m on canopy. That is a compressed height *range*, not a shifted one, and no
single global constant repairs three different offsets at once. Getting past it needs either
per-object anchoring -- which is the shadow route, N-02, because a shadow measures one
structure rather than the whole scene -- or training that does not bake in one city's height
prior in the first place. Calibration is the wrong tool for this particular error, and saying
so is more useful than shipping a number that games the metric.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class Anchor:
    """One estimate of the scene's height offset, and how much it should be believed.

    `weight` is an inverse-variance style confidence, not a preference. An anchor that cannot
    constrain the scene returns None instead of a weak guess, because a weak guess pulls the
    fusion and a None does not.
    """

    name: str
    offset_m: float
    weight: float
    evidence: dict[str, Any] = field(default_factory=dict)


def ground_anchor(heights_m: np.ndarray, ground_mask: np.ndarray | None = None,
                  percentile: float = 5.0) -> Anchor | None:
    """The free anchor: bare ground is at zero height above ground, by definition.

    With a semantic mask, use it. Without, take a low percentile of the predicted surface as
    a proxy for ground -- in any scene with streets or open space, the bottom few per cent of
    an nDSM is ground, and its true value is 0.

    This constrains the *floor*, not the *scale*, which is exactly the shape of the error
    measured above. It is also the one anchor that needs no external data at all.
    """
    if ground_mask is not None and ground_mask.any():
        sample = heights_m[ground_mask]
        basis = "semantic ground mask"
    else:
        finite = heights_m[np.isfinite(heights_m)]
        if finite.size < 100:
            return None
        threshold = np.percentile(finite, percentile)
        sample = finite[finite <= threshold]
        basis = f"lowest {percentile:g}% of predicted heights"

    sample = sample[np.isfinite(sample)]
    if sample.size < 50:
        return None

    # Median, not mean: a few spuriously low pixels should not drag the floor.
    offset = -float(np.median(sample))
    spread = float(np.std(sample)) + 1e-3
    return Anchor(
        name="ground",
        offset_m=offset,
        weight=1.0 / spread**2,
        evidence={"basis": basis, "pixels": int(sample.size),
                  "median_predicted_m": float(np.median(sample)), "spread_m": spread},
    )


def gcp_anchor(heights_m: np.ndarray, points: list[tuple[int, int, float]]) -> Anchor | None:
    """Offset from ground control points: pixels whose true height is known.

    Robust to a bad point by using the median residual rather than the mean -- a single
    mistyped elevation would otherwise move the whole scene.
    """
    residuals = []
    rows, cols = heights_m.shape
    for row, col, truth_m in points:
        if 0 <= row < rows and 0 <= col < cols:
            predicted = heights_m[row, col]
            if np.isfinite(predicted):
                residuals.append(truth_m - float(predicted))
    if len(residuals) < 1:
        return None

    residuals = np.asarray(residuals, dtype=np.float64)
    offset = float(np.median(residuals))
    # Spread across points is the honest uncertainty; a single point gets no spread and a
    # deliberately modest weight rather than infinite confidence.
    spread = float(np.std(residuals)) if residuals.size > 1 else 3.0
    return Anchor(
        name="gcp",
        offset_m=offset,
        weight=residuals.size / max(spread, 0.5) ** 2,
        evidence={"points_used": int(residuals.size), "residual_spread_m": spread},
    )


def shadow_anchor(heights_m: np.ndarray, measured: list[tuple[int, int, float]]) -> Anchor | None:
    """Offset from shadow-derived heights (N-01/N-02).

    Same arithmetic as GCPs but a different provenance, and kept separate so the harness can
    report what each is worth independently rather than crediting the fusion.

    Unlike the ground anchor, this constrains *tall* structures, which is where the
    class-dependent residual is worst. That makes it the route past the 6.5 m floor a global
    offset cannot cross -- but it is only as good as the shadow detection feeding it, which
    is the weak link (docs/14-novelties.md).
    """
    anchor = gcp_anchor(heights_m, measured)
    if anchor is None:
        return None
    return Anchor(name="shadow", offset_m=anchor.offset_m,
                  weight=anchor.weight * 0.5,      # detection is less certain than a survey
                  evidence={**anchor.evidence, "note": "heights from shadow geometry"})


def fuse(anchors: list[Anchor | None]) -> tuple[float, float, dict[str, Any]]:
    """Combine anchors into one offset and a confidence band.

    Inverse-variance weighted, so a tight anchor dominates a loose one. The band widens when
    anchors disagree -- disagreement is information, and reporting a narrow band over
    conflicting evidence is worse than reporting no band, because it invites trust the
    evidence does not support.
    """
    present = [a for a in anchors if a is not None]
    if not present:
        return 0.0, float("nan"), {"anchors": [], "note": "no anchor available; no offset applied"}

    weights = np.array([a.weight for a in present], dtype=np.float64)
    offsets = np.array([a.offset_m for a in present], dtype=np.float64)
    offset = float(np.average(offsets, weights=weights))

    # Confidence: the tighter of what the weights claim and what the spread between anchors
    # actually shows. Two anchors that disagree by 5 m do not get a 0.5 m band.
    from_weights = float(1.0 / np.sqrt(weights.sum()))
    from_spread = float(np.std(offsets)) if len(present) > 1 else from_weights
    band = max(from_weights, from_spread)

    return offset, band, {
        "anchors": [{"name": a.name, "offset_m": a.offset_m, "weight": a.weight,
                     **a.evidence} for a in present],
        "offset_m": offset,
        "confidence_m": band,
        "agreement_spread_m": from_spread if len(present) > 1 else None,
        "method": "inverse-variance weighted; band widened by anchor disagreement",
    }


def apply(heights_m: np.ndarray, offset_m: float, clamp_negative: bool = True) -> np.ndarray:
    """Shift a height field by a calibrated offset.

    Negative heights above ground are clamped by default: an nDSM below zero means a surface
    beneath the ground beneath it, which is not a thing the output should claim.
    """
    shifted = heights_m.astype(np.float32) + np.float32(offset_m)
    return np.maximum(shifted, 0.0) if clamp_negative else shifted


def calibrate(
    heights_m: np.ndarray,
    ground_mask: np.ndarray | None = None,
    gcps: list[tuple[int, int, float]] | None = None,
    shadow_heights: list[tuple[int, int, float]] | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Run every available anchor, fuse them, and return the corrected field with provenance.

    Anchors that cannot run are absent rather than zero, so the fusion is never diluted by an
    anchor that had nothing to say.
    """
    anchors = [
        ground_anchor(heights_m, ground_mask),
        gcp_anchor(heights_m, gcps) if gcps else None,
        shadow_anchor(heights_m, shadow_heights) if shadow_heights else None,
    ]
    offset, band, record = fuse(anchors)
    record["known_limit"] = (
        "A single offset corrects roughly 27% of RMSE on unseen-city imagery. The residual "
        "bias is class-dependent (ground, buildings and canopy differ), which no global "
        "constant can repair; see docs/13-baseline-analysis.md."
    )
    return apply(heights_m, offset), record
