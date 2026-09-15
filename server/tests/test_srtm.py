"""SRTM handling, concentrating on the two things that are silently catastrophic.

Tile naming: an off-by-one in the hemisphere logic fetches terrain from the wrong side of a
meridian and every elevation is wrong by hundreds of metres.

Vertical datum: EGM96 and WGS84 differ by tens of metres across India -- far more than any
building -- so a mixed pair produces a constant offset that looks exactly like a broken model.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from depthwizard import srtm  # noqa: E402


# ------------------------------------------------------------------- tile naming

@pytest.mark.parametrize(("lat", "lon", "expected"), [
    (28.6, 77.2, "N28E077"),      # Delhi
    (12.97, 77.59, "N12E077"),    # Bengaluru
    (0.5, 0.5, "N00E000"),
    (-1.5, -1.5, "S02W002"),      # floor first: -1.5 floors to -2, not -1
    (-0.1, -0.1, "S01W001"),      # just south-west of the origin
    (51.5, -0.12, "N51W001"),     # negative longitude, positive latitude
])
def test_tile_naming(lat: float, lon: float, expected: str):
    assert srtm.tile_name(lat, lon) == expected


def test_tiles_are_named_for_their_south_west_corner():
    """Every point inside a degree cell must map to the same tile."""
    names = {srtm.tile_name(lat, lon)
             for lat in (28.001, 28.5, 28.999)
             for lon in (77.001, 77.5, 77.999)}
    assert names == {"N28E077"}


# ------------------------------------------------------------------- datum

def test_datum_must_be_declared():
    with pytest.raises(ValueError, match="datum"):
        srtm.Elevation(100.0, "MSL", "invented")


def test_orthometric_to_ellipsoidal_round_trips():
    """The conversion that, done wrong, offsets an entire scene by tens of metres."""
    separation = -45.3                       # typical order of magnitude for India
    orthometric = srtm.Elevation(216.0, "EGM96", "SRTM")
    ellipsoidal = srtm.to_ellipsoidal(orthometric, separation)

    assert ellipsoidal.datum == "WGS84"
    assert ellipsoidal.value_m == pytest.approx(216.0 + separation)
    back = srtm.to_orthometric(ellipsoidal, separation)
    assert back.datum == "EGM96"
    assert back.value_m == pytest.approx(216.0)


def test_converting_to_the_datum_it_already_has_is_a_no_op():
    """Applying a separation twice is the realistic way to get this wrong."""
    already = srtm.Elevation(216.0, "WGS84", "GNSS")
    assert srtm.to_ellipsoidal(already, -45.3).value_m == pytest.approx(216.0)


def test_conversion_records_what_was_applied():
    """Provenance, so a later reader can tell whether a correction was already made."""
    converted = srtm.to_ellipsoidal(srtm.Elevation(216.0, "EGM96", "SRTM"), -45.3)
    assert "geoid separation" in converted.source
    assert "-45.30" in converted.source


# ------------------------------------------------------------------- reading

def _write_hgt(path: Path, grid: np.ndarray) -> Path:
    grid.astype(">i2").tofile(path)
    return path


def test_read_hgt_infers_side_and_marks_voids(tmp_path: Path):
    side = 11
    grid = np.arange(side * side, dtype=np.int16).reshape(side, side)
    grid[5, 5] = -32768                       # the void sentinel
    path = _write_hgt(tmp_path / "N00E000.hgt", grid)

    loaded = srtm.read_hgt(path)
    assert loaded.shape == (side, side)
    assert np.isnan(loaded[5, 5]), "voids must become NaN, never 0 m"
    assert loaded[0, 0] == 0


def test_non_square_file_is_refused(tmp_path: Path):
    path = tmp_path / "bad.hgt"
    np.arange(10, dtype=">i2").tofile(path)
    with pytest.raises(ValueError, match="square"):
        srtm.read_hgt(path)


def test_sampling_is_bilinear_not_nearest(tmp_path: Path):
    """Nearest-neighbour would put 30 m terraces into a sub-metre DSM."""
    side = 3
    # A pure west-to-east ramp, so the expected value at any longitude is exact.
    grid = np.tile(np.array([0.0, 50.0, 100.0], dtype=np.float32), (side, 1))
    halfway = srtm.sample(grid, latitude=0.5, longitude=0.25, tile_lat=0, tile_lon=0)
    assert halfway == pytest.approx(25.0), "a midpoint must interpolate, not snap"


def test_sampling_respects_north_up_row_order(tmp_path: Path):
    """Row 0 is the northern edge. Flipping this mirrors every scene north-south."""
    grid = np.array([[100.0, 100.0], [0.0, 0.0]], dtype=np.float32)   # north high
    north = srtm.sample(grid, 0.99, 0.5, 0, 0)
    south = srtm.sample(grid, 0.01, 0.5, 0, 0)
    assert north > south


def test_a_void_in_the_cell_yields_nan(tmp_path: Path):
    grid = np.array([[10.0, np.nan], [10.0, 10.0]], dtype=np.float32)
    assert np.isnan(srtm.sample(grid, 0.9, 0.9, 0, 0))


# ------------------------------------------------------------------- combining

def test_combine_adds_terrain_to_object_height():
    dtm = np.full((4, 4), 300.0, dtype=np.float32)
    ndsm = np.zeros((4, 4), dtype=np.float32)
    ndsm[1, 1] = 12.0                          # a 12 m building on 300 m terrain
    dsm, meta = srtm.combine(dtm, ndsm, datum="EGM96")

    assert dsm[1, 1] == pytest.approx(312.0)
    assert dsm[0, 0] == pytest.approx(300.0)
    assert meta["vertical_datum"] == "EGM96"
    # The canopy double-count is recorded rather than left for someone to rediscover.
    assert "bare earth" in meta["known_bias"]


def test_combine_refuses_mismatched_grids():
    with pytest.raises(ValueError, match="different grids"):
        srtm.combine(np.zeros((4, 4), np.float32), np.zeros((8, 8), np.float32), "EGM96")


def test_combine_counts_voids():
    dtm = np.full((3, 3), 100.0, dtype=np.float32)
    dtm[0, 0] = np.nan
    _, meta = srtm.combine(dtm, np.zeros((3, 3), np.float32), "EGM96")
    assert meta["terrain_voids"] == 1


def test_uncached_tile_raises_rather_than_downloading():
    """Hard rule 6: fetching is an explicit step, never a side effect of inference."""
    with pytest.raises(FileNotFoundError, match="not cached"):
        srtm.elevation_at(89.5, 179.5)          # a tile nobody has
