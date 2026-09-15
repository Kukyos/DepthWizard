"""SRTM terrain: the DTM half of `DSM = DTM + nDSM`.

The network predicts height above the ground beneath each pixel. Nothing in a single image
says how high that ground is above sea level, so that term comes from outside, and SRTM is
the standard free global source at roughly 30 m.

Two traps here are larger than the thing being measured, and both are silent.

**Datum.** SRTM heights are orthometric -- above the EGM96 geoid. GNSS receivers and many
GeoTIFFs are ellipsoidal -- above the WGS84 ellipsoid. Across India the separation is on the
order of -30 to -100 m, which is far larger than any building. Mixing them produces a large
constant offset that looks exactly like a broken model, and every number downstream inherits
it. So every elevation here carries its datum explicitly and conversion is an operation, not
an assumption (U-07).

**SRTM is not bare earth.** C-band radar partly penetrates canopy but does not reach the
ground beneath it, so over forest SRTM sits somewhere inside the canopy rather than below it.
Adding a predicted canopy height to it therefore double-counts vegetation. That error is
bounded and known, and it is stated in the forest results rather than averaged away
(hard rule 8).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import config

#: SRTM 1-arc-second is about 30 m at the equator, in degrees of latitude.
ARCSECOND_DEG = 1.0 / 3600.0


@dataclass(frozen=True)
class Elevation:
    """An elevation with its vertical datum attached.

    The datum travels with the number because the two datums differ by tens of metres and a
    bare float gives no way to notice they have been mixed.
    """

    value_m: float
    datum: str          # "EGM96" (orthometric) or "WGS84" (ellipsoidal)
    source: str

    def __post_init__(self) -> None:
        if self.datum not in ("EGM96", "WGS84"):
            raise ValueError(f"unknown vertical datum {self.datum!r}")


def tile_name(latitude: float, longitude: float) -> str:
    """SRTM tile covering a point, in the standard `N28E077` naming.

    Tiles are named for their south-west corner, so the floor is taken before the hemisphere
    letter is chosen -- rounding toward zero instead would name the wrong tile everywhere
    south or west of the origin.
    """
    lat_floor = math.floor(latitude)
    lon_floor = math.floor(longitude)
    ns = "N" if lat_floor >= 0 else "S"
    ew = "E" if lon_floor >= 0 else "W"
    return f"{ns}{abs(lat_floor):02d}{ew}{abs(lon_floor):03d}"


def cache_path(latitude: float, longitude: float) -> Path:
    return config.SRTM_CACHE_DIR / f"{tile_name(latitude, longitude)}.hgt"


def is_cached(latitude: float, longitude: float) -> bool:
    return cache_path(latitude, longitude).is_file()


def read_hgt(path: str | Path) -> np.ndarray:
    """Read a raw `.hgt` tile.

    The format has no header: it is big-endian int16, square, north-up, with the side length
    implied by the file size (1201 for 3-arc-second, 3601 for 1-arc-second). -32768 marks
    voids, which are common in steep terrain and over water and must not be averaged in as if
    they were sea level.
    """
    path = Path(path)
    raw = np.fromfile(path, dtype=">i2")
    side = int(round(math.sqrt(raw.size)))
    if side * side != raw.size:
        raise ValueError(f"{path.name} is {raw.size} samples, not a square tile")
    grid = raw.reshape(side, side).astype(np.float32)
    grid[grid == -32768] = np.nan            # voids, not zero
    return grid


def sample(grid: np.ndarray, latitude: float, longitude: float,
           tile_lat: int, tile_lon: int) -> float:
    """Bilinear sample of a tile at a point.

    Bilinear rather than nearest because the grid is 30 m and the scenes are sub-metre: a
    nearest-neighbour DTM would introduce 30 m terraces into the final DSM that look like
    real structure and are not.
    """
    side = grid.shape[0]
    # Row 0 is the northern edge, so latitude runs backwards through the array.
    y = (tile_lat + 1 - latitude) * (side - 1)
    x = (longitude - tile_lon) * (side - 1)
    y = float(np.clip(y, 0, side - 1))
    x = float(np.clip(x, 0, side - 1))

    y0, x0 = int(math.floor(y)), int(math.floor(x))
    y1, x1 = min(y0 + 1, side - 1), min(x0 + 1, side - 1)
    fy, fx = y - y0, x - x0

    corners = np.array([grid[y0, x0], grid[y0, x1], grid[y1, x0], grid[y1, x1]])
    if np.isnan(corners).any():
        # A void anywhere in the cell makes the interpolation meaningless; say so rather
        # than quietly substituting the corners that happen to exist.
        return float("nan")
    top = grid[y0, x0] * (1 - fx) + grid[y0, x1] * fx
    bottom = grid[y1, x0] * (1 - fx) + grid[y1, x1] * fx
    return float(top * (1 - fy) + bottom * fy)


def elevation_at(latitude: float, longitude: float) -> Elevation:
    """Terrain elevation at a point, from the local cache.

    Raises rather than downloading: the viewer and the pipeline are offline by design
    (hard rule 6), so fetching is an explicit, separate step.
    """
    path = cache_path(latitude, longitude)
    if not path.is_file():
        raise FileNotFoundError(
            f"SRTM tile {tile_name(latitude, longitude)} is not cached at {path}. "
            "Fetch it first: python -m tools.fetch_srtm --lat ... --lon ...")
    grid = read_hgt(path)
    value = sample(grid, latitude, longitude,
                   math.floor(latitude), math.floor(longitude))
    return Elevation(value_m=value, datum="EGM96", source=f"SRTM {path.name}")


def to_ellipsoidal(elevation: Elevation, geoid_separation_m: float) -> Elevation:
    """Convert an orthometric height to an ellipsoidal one.

    `h = H + N`: ellipsoidal height is orthometric height plus the geoid separation. The
    separation must come from a published geoid model for the location -- it is roughly
    -30 to -100 m across India and varies over hundreds of kilometres, so a constant is not
    good enough for anything but a sanity check.
    """
    if elevation.datum == "WGS84":
        return elevation
    return Elevation(
        value_m=elevation.value_m + geoid_separation_m,
        datum="WGS84",
        source=f"{elevation.source} + geoid separation {geoid_separation_m:+.2f} m",
    )


def to_orthometric(elevation: Elevation, geoid_separation_m: float) -> Elevation:
    """The inverse: `H = h - N`."""
    if elevation.datum == "EGM96":
        return elevation
    return Elevation(
        value_m=elevation.value_m - geoid_separation_m,
        datum="EGM96",
        source=f"{elevation.source} - geoid separation {geoid_separation_m:+.2f} m",
    )


def combine(dtm_m: np.ndarray, ndsm_m: np.ndarray, datum: str) -> tuple[np.ndarray, dict]:
    """`DSM = DTM + nDSM`, with the result's datum recorded.

    The two grids must already be on the same pixel grid. Resampling SRTM onto the image
    grid belongs upstream, where the affine transform lives, so that this stays a statement
    about elevation rather than a place where georeferencing can quietly go wrong.
    """
    if dtm_m.shape != ndsm_m.shape:
        raise ValueError(
            f"DTM {dtm_m.shape} and nDSM {ndsm_m.shape} are on different grids; "
            "resample before combining")
    dsm = dtm_m.astype(np.float32) + ndsm_m.astype(np.float32)
    voids = int(np.isnan(dtm_m).sum())
    return dsm, {
        "terrain_source": "SRTM 1 arc-second",
        "vertical_datum": datum,
        "terrain_voids": voids,
        # Over canopy SRTM sits inside the vegetation rather than below it, so adding a
        # predicted canopy height double-counts. Recorded so forest results can say so.
        "known_bias": "SRTM is not bare earth under canopy; forest elevations are biased high",
    }
