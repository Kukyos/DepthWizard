"""Overlay textures: slope, contours, and signed error against reference.

The brief asks for slope analysis and for validating estimated heights against reference
data, both from arbitrary viewpoints. These are computed here as images and swapped onto the
terrain material in the viewer, rather than being done in a shader.

That is a deliberate trade. The geospatial context these need -- ground sample distance,
units, nodata, the reference raster -- already lives on this side, and reimplementing it in
GLSL would duplicate all of it for no gain, since the overlays are static per scene. It also
keeps the maths next to the data it describes, where it can be tested.

Colour choices matter more than they look. The error overlay is diverging (blue = too low,
red = too high, white = correct) because the sign of an error is the useful part: a DSM that
is uniformly 5 m short is a calibration bug, and one that is scattered is a model limit, and
a single-hue ramp makes those look identical.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def _save(array: np.ndarray, path: Path) -> str:
    from PIL import Image

    Image.fromarray(array).save(path)
    return path.name


def slope_degrees(heights_m: np.ndarray, gsd_m: float) -> np.ndarray:
    """Terrain slope in degrees.

    The gradient is divided by the pixel size, so this is a real angle rather than a
    per-pixel rise. Getting that wrong produces slopes that change when you resample the
    raster, which is the classic way to make a slope map meaningless.
    """
    if gsd_m <= 0:
        raise ValueError("slope needs a real pixel size")
    dy, dx = np.gradient(heights_m.astype(np.float32), gsd_m)
    return np.degrees(np.arctan(np.hypot(dx, dy)))


def _ramp(values: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Sequential ramp, dark blue through green to yellow. Perceptually ordered."""
    t = np.clip((values - lo) / max(hi - lo, 1e-6), 0, 1)
    red = np.clip(1.8 * t - 0.5, 0, 1)
    green = np.clip(1.6 * t - 0.1, 0, 1)
    blue = np.clip(1.0 - 1.6 * t, 0, 1)
    return (np.dstack([red, green, blue]) * 255).astype(np.uint8)


def _diverging(values: np.ndarray, limit: float) -> np.ndarray:
    """Blue-white-red about zero. Sign is the point, so zero must be visually neutral."""
    t = np.clip(values / max(limit, 1e-6), -1, 1)
    positive, negative = np.clip(t, 0, 1), np.clip(-t, 0, 1)
    red = 1.0 - negative * 0.8
    green = 1.0 - np.maximum(positive, negative) * 0.85
    blue = 1.0 - positive * 0.8
    return (np.dstack([red, green, blue]) * 255).astype(np.uint8)


def contour_lines(heights_m: np.ndarray, interval_m: float = 5.0) -> np.ndarray:
    """Contour bands as a transparent-ish overlay, drawn where the height crosses a multiple.

    Detected by looking for a change in `floor(h / interval)` between neighbours rather than
    by thresholding the height itself, so line density follows the terrain and lines stay
    one pixel wide on steep ground instead of disappearing.
    """
    band = np.floor(heights_m / max(interval_m, 1e-6))
    edge = np.zeros(heights_m.shape, dtype=bool)
    edge[:-1, :] |= band[:-1, :] != band[1:, :]
    edge[:, :-1] |= band[:, :-1] != band[:, 1:]

    image = np.full((*heights_m.shape, 3), 20, dtype=np.uint8)
    image[edge] = (255, 220, 120)
    return image


def build_overlays(
    heights_m: np.ndarray,
    out_dir: Path,
    gsd_m: float,
    reference: np.ndarray | None = None,
    contour_interval_m: float = 5.0,
) -> dict[str, str]:
    """Write every overlay texture and return {name: filename}."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}

    # Height, on its own ramp. Useful on its own and the reference for the error map.
    lo, hi = float(np.nanmin(heights_m)), float(np.nanmax(heights_m))
    files["height"] = _save(_ramp(heights_m, lo, hi), out_dir / "overlay_height.png")

    slope = slope_degrees(heights_m, gsd_m)
    # Capped at 60 degrees: above that everything is "a wall", and letting a few vertical
    # building faces set the scale would flatten all the real terrain variation to one colour.
    files["slope"] = _save(_ramp(slope, 0.0, 60.0), out_dir / "overlay_slope.png")
    files["contours"] = _save(contour_lines(heights_m, contour_interval_m),
                              out_dir / "overlay_contours.png")

    if reference is not None and reference.shape == heights_m.shape:
        error = heights_m.astype(np.float32) - reference.astype(np.float32)
        finite = error[np.isfinite(error)]
        # Scale to the 95th percentile of absolute error, not the maximum: a handful of
        # extreme pixels would otherwise wash the whole map out to neutral.
        limit = float(np.percentile(np.abs(finite), 95)) if finite.size else 1.0
        files["error"] = _save(_diverging(error, max(limit, 1e-3)),
                               out_dir / "overlay_error.png")
        files["reference"] = _save(_ramp(reference, lo, hi), out_dir / "overlay_reference.png")

    return files


def error_statistics(heights_m: np.ndarray, reference: np.ndarray) -> dict[str, float]:
    """Numbers to sit beside the error overlay in the validation panel."""
    error = (heights_m.astype(np.float64) - reference.astype(np.float64)).ravel()
    error = error[np.isfinite(error)]
    if error.size == 0:
        return {}
    return {
        "rmse_m": float(np.sqrt(np.mean(error**2))),
        "mae_m": float(np.mean(np.abs(error))),
        "bias_m": float(np.mean(error)),
        "p95_abs_error_m": float(np.percentile(np.abs(error), 95)),
        "pixels": int(error.size),
    }
