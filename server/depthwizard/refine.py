"""Edge-aware refinement: push height discontinuities onto the edges in the photograph.

Measured cause, not a guess. Depth Anything V2 uses 14-pixel patches, so a 1024x1024 tile is
reasoned about on a **73x73 grid**. At 0.33 m ground sampling that is 4.6 m per cell, and a
10 m building spans 2.2 of them. The decoder then upsamples 14x with bilinear interpolation.

Two consequences, both visible in any flythrough:

  * a tree and the road beside it fall in the same cell, so the tree's height bleeds onto the
    road -- the height map has no way to place the boundary between them
  * buildings arrive as smooth mounds, because two cells cannot describe a flat roof with
    vertical walls

The height map does not know where the edges are. The photograph does: a roof against a road
is a strong colour boundary at full resolution. Guided filtering (He, Sun and Tang) transfers
that structure onto the height map -- within a window it fits height as a local linear
function of the guide image, so the output follows the guide's edges while staying close to
the input's values.

This is a reconstruction fix, not a cosmetic one: it moves height discontinuities to where
the physical discontinuities actually are.
"""

from __future__ import annotations

import numpy as np


def _box(image: np.ndarray, radius: int) -> np.ndarray:
    """Box mean via summed-area table: O(1) per pixel regardless of radius."""
    from scipy.ndimage import uniform_filter

    return uniform_filter(image, size=2 * radius + 1, mode="nearest")


def guided_filter(source: np.ndarray, guide: np.ndarray, radius: int = 8,
                  eps: float = 1e-3) -> np.ndarray:
    """Filter `source` so it follows the edges in `guide`.

    Within each window the output is `a * guide + b`, with `a` and `b` chosen to best match
    the source. Where the guide has no structure, `a` goes to zero and the result is a local
    average -- smoothing flat ground. Where the guide has a strong edge, `a` is large and the
    output reproduces that edge sharply.

    `eps` sets what counts as an edge: smaller preserves weaker ones. It is scaled against the
    guide's variance, so it does not depend on the image's brightness range.
    """
    source = source.astype(np.float32)
    guide = guide.astype(np.float32)

    mean_g = _box(guide, radius)
    mean_s = _box(source, radius)
    corr_gg = _box(guide * guide, radius)
    corr_gs = _box(guide * source, radius)

    var_g = corr_gg - mean_g * mean_g
    cov_gs = corr_gs - mean_g * mean_s

    a = cov_gs / (var_g + eps)
    b = mean_s - a * mean_g
    return _box(a, radius) * guide + _box(b, radius)


def refine_heights(heights_m: np.ndarray, rgb: np.ndarray, radius: int = 8,
                   eps: float = 1e-4) -> np.ndarray:
    """Snap a blurry height map onto the structure visible in its own photograph.

    The guide is luminance, normalised to 0..1 so `eps` means the same thing on a dark winter
    scene as on a bright one. Colour would be better for separating a green roof from grey
    tarmac at equal brightness; luminance is used because it is one channel rather than three
    and the dominant edges here -- roof against road, canopy against ground -- are luminance
    edges anyway.
    """
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        raise ValueError(f"guide must be (H, W, 3) RGB, got {rgb.shape}")
    if heights_m.shape != rgb.shape[:2]:
        raise ValueError(
            f"heights {heights_m.shape} and guide {rgb.shape[:2]} are different sizes")

    channels = rgb[..., :3].astype(np.float32)
    luminance = (0.299 * channels[..., 0] + 0.587 * channels[..., 1]
                 + 0.114 * channels[..., 2])
    lo, hi = float(luminance.min()), float(luminance.max())
    guide = (luminance - lo) / max(hi - lo, 1e-6)

    return guided_filter(heights_m, guide, radius=radius, eps=eps)


def edge_sharpness(heights_m: np.ndarray) -> float:
    """Mean absolute height gradient: how abrupt the surface is, on average.

    A blurred field spreads a roof edge over many pixels and scores low; a crisp one
    concentrates the change and scores high. Used to check that refinement actually sharpens
    rather than merely rearranging, which a visual comparison alone cannot establish.
    """
    dy, dx = np.gradient(heights_m.astype(np.float32))
    return float(np.hypot(dx, dy).mean())
