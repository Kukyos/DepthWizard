"""Metrics, and the rules about which ones are defined when.

The central distinction: a **relative** prediction has no metres, so absolute RMSE against
metric ground truth is meaningless for it. Computing one anyway would produce a number that
looks like accuracy and is not. So the absolute metrics refuse to run on relative input
rather than quietly returning something (hard rules 1 and 2).

Scale-free metrics -- correlation, and error after the single best global scale and shift
are removed -- are defined for both, and are what Phase 1 can honestly report.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np


@dataclass(frozen=True)
class Scores:
    pixels: int
    pearson_r: float
    si_rmse: float          # after optimal scale+shift; metres when reference is metric
    si_mae: float
    fit_scale: float
    fit_offset: float
    rmse: float | None      # absolute; None unless the prediction is already metric
    mae: float | None
    bias: float | None
    delta1: float | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean(pred: np.ndarray, ref: np.ndarray, mask: np.ndarray | None):
    pred = np.asarray(pred, dtype=np.float64).ravel()
    ref = np.asarray(ref, dtype=np.float64).ravel()
    ok = np.isfinite(pred) & np.isfinite(ref)
    if mask is not None:
        ok &= np.asarray(mask).ravel().astype(bool)
    return pred[ok], ref[ok]


def score(
    pred: np.ndarray,
    ref: np.ndarray,
    *,
    metric: bool,
    mask: np.ndarray | None = None,
) -> Scores | None:
    """Compare a prediction against reference heights.

    `metric` says whether `pred` is already in the same units as `ref`. When it is False the
    absolute fields come back None -- deliberately, so a caller cannot print an RMSE for a
    unitless prediction without noticing the None.

    Returns None when there is too little valid data to say anything, rather than a score
    built on a handful of pixels.
    """
    p, r = _clean(pred, ref, mask)
    if p.size < 100 or p.std() == 0 or r.std() == 0:
        return None

    correlation = float(np.corrcoef(p, r)[0, 1])

    # Best global scale and shift, which is what "scale-invariant" means here: it removes
    # exactly the freedom a relative prediction has, and nothing else.
    scale, offset = np.polyfit(p, r, 1)
    residual = (scale * p + offset) - r

    absolute: dict[str, float | None] = {"rmse": None, "mae": None, "bias": None, "delta1": None}
    if metric:
        diff = p - r
        absolute["rmse"] = float(np.sqrt(np.mean(diff**2)))
        absolute["mae"] = float(np.mean(np.abs(diff)))
        absolute["bias"] = float(np.mean(diff))
        # delta1: fraction within 25% relative error, on pixels with a meaningful height.
        # Near-zero ground would otherwise make the ratio explode and the metric meaningless.
        tall = r > 1.0
        if tall.sum() > 50:
            ratio = np.maximum(p[tall] / r[tall], r[tall] / np.maximum(p[tall], 1e-6))
            absolute["delta1"] = float(np.mean(ratio < 1.25))

    return Scores(
        pixels=int(p.size),
        pearson_r=correlation,
        si_rmse=float(np.sqrt(np.mean(residual**2))),
        si_mae=float(np.mean(np.abs(residual))),
        fit_scale=float(scale),
        fit_offset=float(offset),
        **absolute,
    )


def aggregate(rows: list[Scores]) -> dict[str, float] | None:
    """Pixel-weighted mean across tiles.

    Weighted by pixel count rather than a plain mean of per-tile figures, so a tile with a
    handful of building pixels does not carry the same weight as one that is half buildings.
    """
    rows = [r for r in rows if r is not None]
    if not rows:
        return None
    weights = np.array([r.pixels for r in rows], dtype=np.float64)
    out: dict[str, float] = {"tiles": len(rows), "pixels": int(weights.sum())}
    for field in ("pearson_r", "si_rmse", "si_mae", "rmse", "mae", "bias", "delta1"):
        values = np.array([getattr(r, field) for r in rows], dtype=np.float64)
        ok = np.isfinite(values)
        if ok.any():
            out[field] = float(np.average(values[ok], weights=weights[ok]))
    return out
