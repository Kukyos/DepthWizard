"""Raster in, raster out, with the georeferencing kept exactly.

This module is the foundation of the project in a literal sense. A half-pixel error in the
affine transform shifts the whole DSM, which corrupts every metric, mislocates every ground
control point, misaligns the SRTM lookup, and shows up in the viewer as the photo sliding
off the geometry -- the first thing the evaluation criteria name. So CRS and transform are
copied, never recomputed, and `tests/test_raster.py` proves the round trip.

It also decides the pipeline's one branch (G1): a file carrying a CRS gets the absolute
metric path, a file without one gets the relative path and no metre value anywhere. The
user is never asked which; the file says.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine

from . import config


@dataclass(frozen=True)
class SceneMeta:
    """Everything known about an input raster before any inference runs.

    `units` is derived here, once, from whether a CRS is present -- so no later stage has
    to decide, and none can decide differently (hard rule 2).
    """

    path: str
    width: int
    height: int
    band_count: int
    crs: str | None                  # EPSG string, e.g. "EPSG:32644", or None
    transform: tuple[float, ...] | None   # the six affine coefficients, in gdal order
    gsd_m: float | None              # ground sample distance, metres per pixel
    units: str                       # config.Units.METRES_ABSOLUTE | RELATIVE_UNITLESS
    driver: str
    dtype: str

    @property
    def georeferenced(self) -> bool:
        return self.units in config.Units.METRIC

    @property
    def objects_resolvable(self) -> bool:
        """False when the pixels are too coarse to carry object height at all.

        Below the floor a building spans under ~2 px and its height is not present in the
        data; emitting one anyway would be fabrication (hard rule 7). An unknown GSD is
        treated as resolvable, because the relative path makes no metric claim to begin with.
        """
        return self.gsd_m is None or self.gsd_m <= config.GSD_FLOOR_M


def _gsd_from_transform(transform: Affine, crs: CRS | None) -> float | None:
    """Metres per pixel, or None when it cannot be known honestly.

    A projected CRS has linear units, so pixel width is already a length. A geographic CRS
    (degrees) is converted at the equator, which is an upper bound -- flagged rather than
    silently trusted, since the error grows with latitude.
    """
    if crs is None:
        return None
    px = abs(transform.a)
    if px == 0:
        return None
    if crs.is_geographic:
        # 1 degree of longitude is ~111.32 km at the equator and shrinks with latitude, so
        # this overestimates. Callers that need precision should reproject first.
        return px * 111_320.0
    factor = crs.linear_units_factor[1] if crs.linear_units_factor else 1.0
    return px * factor


def read_scene(path: str | Path) -> tuple[np.ndarray, SceneMeta]:
    """Read an image and describe it. Returns (H, W, C) uint8-or-native array and its meta."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"no such image: {path}")

    with rasterio.open(path) as src:
        megapixels = (src.width * src.height) / 1e6
        if megapixels > config.MAX_INPUT_MEGAPIXELS:
            raise ValueError(
                f"{path.name} is {megapixels:.0f} MP, over the "
                f"{config.MAX_INPUT_MEGAPIXELS} MP limit. Tile it first."
            )

        data = src.read()                      # (bands, rows, cols)
        array = np.transpose(data, (1, 2, 0))  # (rows, cols, bands)

        crs = src.crs
        # rasterio hands back a default identity transform for a plain PNG or JPG. That is
        # not georeferencing, and treating it as such would put a scene at the origin with
        # 1-metre pixels and quietly enable the metric path. A CRS is the real signal.
        has_geo = crs is not None
        transform = src.transform if has_geo else None

        meta = SceneMeta(
            path=str(path),
            width=src.width,
            height=src.height,
            band_count=src.count,
            crs=crs.to_string() if crs else None,
            transform=tuple(transform)[:6] if transform else None,
            gsd_m=_gsd_from_transform(src.transform, crs) if has_geo else None,
            units=(config.Units.METRES_ABSOLUTE if has_geo
                   else config.Units.RELATIVE_UNITLESS),
            driver=src.driver,
            dtype=str(src.dtypes[0]),
        )
    return array, meta


def write_dsm(
    path: str | Path,
    heights: np.ndarray,
    meta: SceneMeta,
    provenance: dict[str, Any],
) -> Path:
    """Write a single-band float32 GeoTIFF, carrying the input's georeferencing unchanged.

    The relative path writes the same container with no CRS attached: a CRS-less GeoTIFF is
    still a valid raster, so there is one writer and one reader rather than two formats
    (D10). What it must never do is invent a CRS to look more complete.
    """
    path = Path(path)
    if heights.ndim != 2:
        raise ValueError(f"a DSM is single-band; got shape {heights.shape}")
    if heights.shape != (meta.height, meta.width):
        raise ValueError(
            f"DSM shape {heights.shape} does not match the source raster "
            f"{(meta.height, meta.width)} -- georeferencing would be wrong"
        )
    if not provenance:
        raise ValueError("refusing to write a DSM with no provenance (hard rule 3)")

    profile: dict[str, Any] = {
        "driver": "GTiff",
        "width": meta.width,
        "height": meta.height,
        "count": 1,
        "dtype": config.DSM_DTYPE,
        "nodata": config.DSM_NODATA,
        "compress": "deflate",
        "predictor": 3,        # floating-point predictor, for float rasters
        "tiled": True,
    }
    if meta.crs is not None and meta.transform is not None:
        profile["crs"] = CRS.from_string(meta.crs)
        profile["transform"] = Affine(*meta.transform)

    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(heights.astype(np.float32), 1)
        # Units travel inside the file too, not only in the sidecar, so a DSM opened in QGIS
        # months from now still says whether its numbers are metres.
        dst.update_tags(
            UNITS=meta.units,
            DEPTHWIZARD_PROVENANCE=json.dumps(provenance, default=str),
        )

    write_provenance(path.with_suffix(".json"), meta, provenance, heights)
    return path


def write_provenance(
    path: Path,
    meta: SceneMeta,
    provenance: dict[str, Any],
    heights: np.ndarray,
) -> Path:
    """The sidecar. A DSM whose origin cannot be reconstructed is not a result."""
    valid = heights[heights != config.DSM_NODATA]
    record = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "units": meta.units,
        "crs": meta.crs,
        "transform": list(meta.transform) if meta.transform else None,
        "gsd_in_m": meta.gsd_m,
        "objects_resolvable": meta.objects_resolvable,
        "gsd_floor_m": config.GSD_FLOOR_M,
        "gsd_floor_is_placeholder": config.GSD_FLOOR_IS_PLACEHOLDER,
        "source": {"path": meta.path, "width": meta.width, "height": meta.height,
                   "driver": meta.driver, "dtype": meta.dtype},
        "vertical_range": ([float(valid.min()), float(valid.max())] if valid.size else None),
        **provenance,
    }
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf8")
    return path


def read_dsm(path: str | Path) -> tuple[np.ndarray, dict[str, Any]]:
    """Read a DSM back, with whatever provenance it carries."""
    path = Path(path)
    with rasterio.open(path) as src:
        heights = src.read(1)
        tags = src.tags()
        info = {
            "units": tags.get("UNITS"),
            "crs": src.crs.to_string() if src.crs else None,
            "transform": tuple(src.transform)[:6],
            "nodata": src.nodata,
        }
        raw = tags.get("DEPTHWIZARD_PROVENANCE")
        if raw:
            try:
                info["provenance"] = json.loads(raw)
            except json.JSONDecodeError:
                info["provenance"] = None
    return heights, info
