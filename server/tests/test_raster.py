"""The non-negotiable test: georeferencing survives the pipeline exactly.

Every number the project reports sits on top of this. A half-pixel drift in the affine
transform corrupts every metric, mislocates every GCP, misaligns the SRTM lookup, and shows
as texture slide in the viewer. Checking it by opening QGIS and looking is not checking it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from depthwizard import config, io_raster  # noqa: E402

# A deliberately awkward transform: non-round pixel size, real-world origin, and a negative
# north-south term (as every north-up raster has). Rounding anywhere shows up immediately.
TRANSFORM = Affine(0.3333333333333333, 0.0, 412345.6789,
                   0.0, -0.3333333333333333, 1234567.8901)
EPSG = "EPSG:32644"          # UTM 44N, a projected CRS covering part of India


def _rgb(width: int = 40, height: int = 30) -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.integers(0, 255, size=(height, width, 3), dtype=np.uint8)


@pytest.fixture
def geotiff(tmp_path: Path) -> Path:
    """A georeferenced RGB GeoTIFF."""
    path = tmp_path / "scene.tif"
    array = _rgb()
    with rasterio.open(
        path, "w", driver="GTiff", width=array.shape[1], height=array.shape[0],
        count=3, dtype="uint8", crs=CRS.from_string(EPSG), transform=TRANSFORM,
    ) as dst:
        for band in range(3):
            dst.write(array[..., band], band + 1)
    return path


@pytest.fixture
def png(tmp_path: Path) -> Path:
    """A plain PNG: no CRS, no transform, no way to know metres."""
    path = tmp_path / "scene.png"
    array = _rgb()
    with rasterio.open(
        path, "w", driver="PNG", width=array.shape[1], height=array.shape[0],
        count=3, dtype="uint8",
    ) as dst:
        for band in range(3):
            dst.write(array[..., band], band + 1)
    return path


# ------------------------------------------------------------------ the branch (G1)

def test_geotiff_takes_the_absolute_path(geotiff: Path):
    _, meta = io_raster.read_scene(geotiff)
    assert meta.georeferenced
    assert meta.units == config.Units.METRES_ABSOLUTE
    assert meta.crs == EPSG


def test_png_takes_the_relative_path(png: Path):
    """A PNG must never reach the metric path, however plausible its pixels look."""
    _, meta = io_raster.read_scene(png)
    assert not meta.georeferenced
    assert meta.units == config.Units.RELATIVE_UNITLESS
    assert meta.crs is None
    assert meta.transform is None
    assert meta.gsd_m is None, "a GSD without a CRS is invented"


# ------------------------------------------------- hard rule 5: exact round trip

def test_crs_and_transform_round_trip_exactly(geotiff: Path, tmp_path: Path):
    array, meta = io_raster.read_scene(geotiff)
    out = io_raster.write_dsm(
        tmp_path / "dsm.tif",
        np.zeros((meta.height, meta.width), dtype=np.float32),
        meta,
        {"backbone": "test"},
    )
    with rasterio.open(out) as dst:
        assert dst.crs == CRS.from_string(EPSG)
        # Exact equality, not approximate: this is the whole point of the test.
        assert tuple(dst.transform)[:6] == tuple(TRANSFORM)[:6]
        assert dst.width == meta.width and dst.height == meta.height


def test_gsd_comes_from_the_transform(geotiff: Path):
    _, meta = io_raster.read_scene(geotiff)
    assert meta.gsd_m == pytest.approx(0.3333333333, rel=1e-9)


# ------------------------------------------------------------------ refusals

def test_dsm_without_provenance_is_refused(geotiff: Path, tmp_path: Path):
    """Hard rule 3. A DSM nobody can trace is a bug, not a shortcut."""
    _, meta = io_raster.read_scene(geotiff)
    with pytest.raises(ValueError, match="provenance"):
        io_raster.write_dsm(tmp_path / "x.tif",
                            np.zeros((meta.height, meta.width), np.float32), meta, {})


def test_shape_mismatch_is_refused(geotiff: Path, tmp_path: Path):
    """A DSM of the wrong size would silently mean wrong georeferencing."""
    _, meta = io_raster.read_scene(geotiff)
    with pytest.raises(ValueError, match="does not match"):
        io_raster.write_dsm(tmp_path / "x.tif", np.zeros((5, 5), np.float32),
                            meta, {"backbone": "test"})


def test_missing_file_is_a_clear_error(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        io_raster.read_scene(tmp_path / "nope.tif")


# ------------------------------------------------------- units travel with the data

def test_relative_dsm_is_labelled_relative_in_the_file(png: Path, tmp_path: Path):
    """Hard rule 2 at the file level: the raster itself says it carries no metres."""
    _, meta = io_raster.read_scene(png)
    out = io_raster.write_dsm(
        tmp_path / "rdsm.tif",
        np.full((meta.height, meta.width), 0.5, np.float32),
        meta,
        {"backbone": "test"},
    )
    _, info = io_raster.read_dsm(out)
    assert info["units"] == config.Units.RELATIVE_UNITLESS
    assert info["crs"] is None


def test_provenance_sidecar_is_written_and_complete(geotiff: Path, tmp_path: Path):
    import json

    _, meta = io_raster.read_scene(geotiff)
    out = io_raster.write_dsm(
        tmp_path / "dsm.tif",
        np.linspace(0, 10, meta.height * meta.width, dtype=np.float32).reshape(
            meta.height, meta.width),
        meta,
        {"backbone": "test", "calibration": "none"},
    )
    record = json.loads(out.with_suffix(".json").read_text(encoding="utf8"))
    for key in ("created_utc", "units", "crs", "transform", "gsd_in_m",
                "objects_resolvable", "backbone", "vertical_range"):
        assert key in record, f"provenance is missing {key}"
    assert record["vertical_range"][0] == pytest.approx(0.0)
    assert record["vertical_range"][1] == pytest.approx(10.0)


def test_heights_survive_the_round_trip(geotiff: Path, tmp_path: Path):
    _, meta = io_raster.read_scene(geotiff)
    rng = np.random.default_rng(1)
    heights = rng.uniform(-5, 300, (meta.height, meta.width)).astype(np.float32)
    out = io_raster.write_dsm(tmp_path / "dsm.tif", heights, meta, {"backbone": "test"})
    read_back, _ = io_raster.read_dsm(out)
    np.testing.assert_array_equal(read_back, heights)


# ------------------------------------------------------ the GSD floor (hard rule 7)

def test_coarse_gsd_marks_objects_unresolvable(tmp_path: Path):
    """Above the floor, object heights are not in the data and we say so."""
    coarse = Affine(config.GSD_FLOOR_M * 2, 0, 0, 0, -config.GSD_FLOOR_M * 2, 0)
    path = tmp_path / "coarse.tif"
    with rasterio.open(path, "w", driver="GTiff", width=10, height=10, count=3,
                       dtype="uint8", crs=CRS.from_string(EPSG), transform=coarse) as dst:
        dst.write(np.zeros((3, 10, 10), np.uint8))
    _, meta = io_raster.read_scene(path)
    assert not meta.objects_resolvable


def test_fine_gsd_is_resolvable(geotiff: Path):
    _, meta = io_raster.read_scene(geotiff)
    assert meta.objects_resolvable
