"""Shadows: cast them from a height field, detect them in an image, compare the two.

This is N-02 in docs/14-novelties.md, and it is the project's main differentiator.

The simple use of shadows is to measure one: a structure casting a shadow of ground length
`L` under solar elevation theta has height `h = L * tan(theta)`. That needs an isolated,
unoccluded structure with a cleanly visible shadow, which dense urban scenes do not provide.

The general form inverts the problem. Given a height field and the sun's position, **render
the shadows that height field would cast**, then compare against the shadows actually present
in the photograph. Occlusion stops being a failure mode and becomes signal: overlapping
shadows are predicted too, and agreement is measured over the whole scene rather than at a
few clean examples.

And because that agreement varies smoothly with the heights, the disagreement points
somewhere: a structure predicted too short casts a shadow that is too short. So the height
field can be *optimised* until its shadows match the observed ones, not merely sampled.
`cast_shadow_soft` is the differentiable version that makes that possible.

Everything here needs three things the imagery must supply: a metric height field, a ground
sample distance, and the solar geometry. Without all three this module cannot run, which is
why it is validated on georeferenced imagery rather than on GAMUS (D-03).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np


@dataclass(frozen=True)
class SunPosition:
    """Where the sun was when the image was taken.

    `azimuth_deg` is compass bearing, degrees clockwise from north, of the direction the
    sunlight comes *from*. `elevation_deg` is the angle above the horizon.
    """

    azimuth_deg: float
    elevation_deg: float
    source: str = "given"

    @property
    def usable(self) -> bool:
        """Shadow geometry degenerates at both ends of the elevation range.

        Near the horizon shadows run to the edge of the scene and mostly leave it; near
        overhead they shrink toward nothing and h = L*tan(theta) divides by a length that is
        approaching zero, so a one-pixel error in L becomes a huge error in h.
        """
        return 10.0 <= self.elevation_deg <= 80.0


def sun_from_metadata(when: datetime, latitude: float, longitude: float,
                      altitude_m: float = 0.0) -> SunPosition:
    """Solar position from acquisition time and scene centre.

    Uses pvlib's implementation of the NREL solar position algorithm rather than hand-rolled
    trigonometry -- this is a value a judge can check, and an azimuth error would rotate
    every predicted shadow and drive the optimisation confidently wrong (U-06).

    `when` must be timezone-aware; a naive timestamp is ambiguous by up to a day's rotation.
    """
    if when.tzinfo is None:
        raise ValueError("acquisition time must be timezone-aware; a naive one is ambiguous")
    try:
        import pandas as pd
        import pvlib
    except ImportError as exc:
        raise RuntimeError("pvlib and pandas are needed for solar geometry") from exc

    frame = pvlib.solarposition.get_solarposition(
        pd.DatetimeIndex([when]), latitude, longitude, altitude=altitude_m)
    return SunPosition(
        azimuth_deg=float(frame["azimuth"].iloc[0]),
        elevation_deg=float(frame["apparent_elevation"].iloc[0]),
        source=f"pvlib NREL SPA @ {when.isoformat()} ({latitude:.4f},{longitude:.4f})",
    )


def height_from_shadow_length(shadow_length_m: float, sun: SunPosition) -> float:
    """h = L * tan(theta). The simple anchor (N-01), kept for cross-checking N-02."""
    if not sun.usable:
        raise ValueError(
            f"solar elevation {sun.elevation_deg:.1f} deg is outside the usable 10-80 range")
    return shadow_length_m * np.tan(np.radians(sun.elevation_deg))


def _sun_step(sun: SunPosition) -> tuple[float, float]:
    """Per-step pixel offset toward the sun, as (d_row, d_col).

    Azimuth is compass bearing of where the light comes from, so we march *toward* it. North
    is negative rows because rasters are north-up with row 0 at the top -- getting this wrong
    mirrors every shadow and is the single easiest mistake to make here.
    """
    theta = np.radians(sun.azimuth_deg)
    return -np.cos(theta), np.sin(theta)


def cast_shadow(
    heights_m: np.ndarray,
    gsd_m: float,
    sun: SunPosition,
    max_distance_m: float = 200.0,
) -> np.ndarray:
    """Which pixels the height field puts in shadow. Returns a boolean mask.

    For each pixel, walk toward the sun. At ground distance d the sun ray sits at
    `h0 + d*tan(elevation)`. If the terrain anywhere along that walk rises above the ray, the
    starting pixel is occluded.

    Marching the whole grid one step at a time -- rather than each pixel's ray separately --
    turns this into a handful of vectorised array comparisons.
    """
    if heights_m.ndim != 2:
        raise ValueError(f"expected a 2-D height field, got {heights_m.shape}")
    if gsd_m <= 0:
        raise ValueError("gsd_m must be positive; shadow geometry needs a real pixel size")

    d_row, d_col = _sun_step(sun)
    slope = np.tan(np.radians(sun.elevation_deg))
    steps = max(1, int(max_distance_m / gsd_m))

    rows, cols = heights_m.shape
    row_index, col_index = np.meshgrid(np.arange(rows), np.arange(cols), indexing="ij")
    shadow = np.zeros((rows, cols), dtype=bool)

    for step in range(1, steps + 1):
        sample_row = np.rint(row_index + d_row * step).astype(np.intp)
        sample_col = np.rint(col_index + d_col * step).astype(np.intp)
        inside = ((sample_row >= 0) & (sample_row < rows)
                  & (sample_col >= 0) & (sample_col < cols))
        if not inside.any():
            break                      # the whole grid has walked off the edge
        occluder = heights_m[np.clip(sample_row, 0, rows - 1),
                             np.clip(sample_col, 0, cols - 1)]
        ray = heights_m + step * gsd_m * slope
        shadow |= inside & (occluder > ray)

    return shadow


def cast_shadow_soft(heights_m, gsd_m: float, sun: SunPosition,
                     max_distance_m: float = 200.0, sharpness: float = 2.0):
    """Differentiable shadow casting, for optimising a height field against observed shadows.

    Same march as `cast_shadow`, but the hard `occluder > ray` test becomes a sigmoid, so the
    result has a gradient with respect to the heights. That is what lets the disagreement
    between predicted and observed shadows *correct* the DSM rather than merely score it.

    `sharpness` is in inverse metres: larger gives a harder shadow edge and a narrower band
    of useful gradient. Torch in, torch out.
    """
    import torch

    d_row, d_col = _sun_step(sun)
    slope = float(np.tan(np.radians(sun.elevation_deg)))
    steps = max(1, int(max_distance_m / gsd_m))
    rows, cols = heights_m.shape[-2:]

    shadow = torch.zeros_like(heights_m)
    for step in range(1, steps + 1):
        shift_r, shift_c = int(round(d_row * step)), int(round(d_col * step))
        if abs(shift_r) >= rows or abs(shift_c) >= cols:
            break
        # torch.roll wraps around, which would let a tall building on one edge shadow the
        # opposite edge. Zero the wrapped band so it cannot occlude anything.
        occluder = torch.roll(heights_m, shifts=(-shift_r, -shift_c), dims=(-2, -1))
        valid = torch.ones_like(heights_m)
        if shift_r > 0:
            valid[..., rows - shift_r:, :] = 0
        elif shift_r < 0:
            valid[..., :(-shift_r), :] = 0
        if shift_c > 0:
            valid[..., :, cols - shift_c:] = 0
        elif shift_c < 0:
            valid[..., :, :(-shift_c)] = 0

        ray = heights_m + step * gsd_m * slope
        shadow = torch.maximum(shadow, valid * torch.sigmoid(sharpness * (occluder - ray)))
    return shadow


def detect_shadow(rgb: np.ndarray, percentile: float = 20.0) -> np.ndarray:
    """A first-pass shadow mask from RGB alone.

    Shadowed ground is lit by skylight rather than sunlight, so it is both darker and
    relatively bluer than the same surface in sun. This thresholds on that combination.

    **This is the weakest link in N-02 and is deliberately marked as such.** Dark roofs, deep
    water, wet tarmac and newly laid asphalt all imitate shadow, and a false shadow mask
    would drive the optimisation it feeds confidently wrong. It needs its own validation
    against hand-labelled shadows before any height is trusted to it -- logged as a risk in
    docs/14-novelties.md.
    """
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        raise ValueError(f"expected (H, W, 3) RGB, got {rgb.shape}")
    channels = rgb[..., :3].astype(np.float32)
    red, green, blue = channels[..., 0], channels[..., 1], channels[..., 2]

    intensity = channels.mean(axis=2)
    # Relative blueness, guarded against division by zero on black pixels.
    blueness = (blue - red) / np.maximum(intensity, 1.0)

    dark = intensity < np.percentile(intensity, percentile)
    bluer = blueness > np.percentile(blueness, 100.0 - percentile)
    return dark & bluer


def agreement(predicted: np.ndarray, observed: np.ndarray) -> dict[str, float]:
    """How well a cast shadow mask matches a detected one.

    Intersection-over-union plus precision and recall, because they fail differently:
    predicting shadow everywhere gives perfect recall and useless precision, and the
    optimisation would happily exploit that if IoU were the only number watched.
    """
    p = np.asarray(predicted, dtype=bool)
    o = np.asarray(observed, dtype=bool)
    intersection = float(np.logical_and(p, o).sum())
    union = float(np.logical_or(p, o).sum())
    return {
        "iou": intersection / union if union else float("nan"),
        "precision": intersection / p.sum() if p.any() else float("nan"),
        "recall": intersection / o.sum() if o.any() else float("nan"),
        "predicted_fraction": float(p.mean()),
        "observed_fraction": float(o.mean()),
    }
