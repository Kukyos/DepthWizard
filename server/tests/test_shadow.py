"""Shadow casting checked against geometry we can compute by hand.

The point of these tests is that the ray-caster and the trigonometry must agree. A box of
known height under a known sun casts a shadow of known length; if the marcher disagrees with
`h = L*tan(theta)`, one of them is wrong, and both feed the same calibration.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from depthwizard import shadow  # noqa: E402

GSD = 1.0          # 1 m pixels keeps pixel counts and metres interchangeable


def box_scene(height_m: float = 10.0, size: int = 120, box: int = 10) -> np.ndarray:
    """Flat ground with one square block in the middle."""
    field = np.zeros((size, size), dtype=np.float32)
    centre = size // 2
    half = box // 2
    field[centre - half:centre + half, centre - half:centre + half] = height_m
    return field


def test_shadow_length_matches_trigonometry():
    """A 10 m box at 45 degrees must cast a 10 m shadow. tan(45) = 1."""
    heights = box_scene(10.0)
    # Sun in the south (azimuth 180): light comes from below the image, shadow falls upward
    # in row terms. Elevation 45 so the shadow length equals the height.
    sun = shadow.SunPosition(azimuth_deg=180.0, elevation_deg=45.0)
    mask = shadow.cast_shadow(heights, GSD, sun)

    centre = heights.shape[0] // 2
    column = mask[:, centre]
    shadowed_rows = np.flatnonzero(column)
    assert shadowed_rows.size > 0, "a 10 m box in 45-degree sun must cast some shadow"

    # Shadow extends away from the box; measure how far beyond the box edge it reaches.
    box_top = centre - 5
    reach_px = box_top - shadowed_rows.min()
    expected = shadow.height_from_shadow_length(10.0, sun)   # == 10 m
    assert expected == pytest.approx(10.0)
    # One pixel of slack for the rounding in the march.
    assert abs(reach_px * GSD - 10.0) <= 1.5, f"shadow reached {reach_px} px, expected ~10"


def test_lower_sun_casts_longer_shadow():
    """The relationship that makes shadows usable as a height cue at all."""
    heights = box_scene(10.0, size=200)
    lengths = []
    for elevation in (60.0, 45.0, 30.0, 20.0):
        sun = shadow.SunPosition(azimuth_deg=180.0, elevation_deg=elevation)
        lengths.append(int(shadow.cast_shadow(heights, GSD, sun).sum()))
    assert lengths == sorted(lengths), f"shadow area must grow as the sun drops: {lengths}"


def test_taller_box_casts_longer_shadow():
    sun = shadow.SunPosition(azimuth_deg=180.0, elevation_deg=45.0)
    areas = [int(shadow.cast_shadow(box_scene(h), GSD, sun).sum()) for h in (5, 10, 20)]
    assert areas == sorted(areas), f"taller must mean more shadow: {areas}"


def test_flat_ground_casts_nothing():
    """No relief, no shadow -- and no spurious shadow from the marcher's edge handling."""
    flat = np.zeros((80, 80), dtype=np.float32)
    sun = shadow.SunPosition(azimuth_deg=135.0, elevation_deg=40.0)
    assert not shadow.cast_shadow(flat, GSD, sun).any()


def test_azimuth_rotates_the_shadow():
    """Shadow direction must follow the sun. Mirroring this is the easiest error to make."""
    heights = box_scene(15.0, size=160)
    north = shadow.cast_shadow(
        heights, GSD, shadow.SunPosition(azimuth_deg=0.0, elevation_deg=40.0))
    south = shadow.cast_shadow(
        heights, GSD, shadow.SunPosition(azimuth_deg=180.0, elevation_deg=40.0))
    centre = heights.shape[0] // 2
    # Light from the north puts the shadow on the far (higher-row) side, and vice versa.
    assert north[centre + 8:, centre].any(), "sun from north should shadow below the box"
    assert south[:centre - 8, centre].any(), "sun from south should shadow above the box"
    assert not np.array_equal(north, south)


def test_usable_elevation_band():
    """Both extremes are refused: shadows leave the scene, or the tangent explodes."""
    assert shadow.SunPosition(azimuth_deg=0, elevation_deg=45).usable
    assert not shadow.SunPosition(azimuth_deg=0, elevation_deg=3).usable
    assert not shadow.SunPosition(azimuth_deg=0, elevation_deg=88).usable
    with pytest.raises(ValueError, match="usable"):
        shadow.height_from_shadow_length(10.0, shadow.SunPosition(0, 88))


def test_zero_gsd_is_refused():
    """Without a real pixel size there is no metre, so there is no shadow geometry."""
    with pytest.raises(ValueError, match="gsd"):
        shadow.cast_shadow(box_scene(), 0.0, shadow.SunPosition(180, 45))


def test_agreement_scores_a_perfect_and_an_empty_match():
    mask = box_scene(1.0).astype(bool)
    perfect = shadow.agreement(mask, mask)
    assert perfect["iou"] == pytest.approx(1.0)
    assert perfect["precision"] == pytest.approx(1.0)
    assert perfect["recall"] == pytest.approx(1.0)

    # Predicting shadow everywhere: perfect recall, poor precision. Watching IoU alone
    # would let an optimiser exploit exactly this.
    everywhere = np.ones_like(mask)
    lazy = shadow.agreement(everywhere, mask)
    assert lazy["recall"] == pytest.approx(1.0)
    assert lazy["precision"] < 0.2


def test_soft_cast_tracks_the_hard_one():
    """The differentiable version must describe the same shadows, or the gradient is a lie."""
    torch = pytest.importorskip("torch")
    heights = box_scene(12.0, size=100)
    sun = shadow.SunPosition(azimuth_deg=180.0, elevation_deg=40.0)

    hard = shadow.cast_shadow(heights, GSD, sun)
    soft = shadow.cast_shadow_soft(
        torch.tensor(heights), GSD, sun, sharpness=6.0).numpy() > 0.5

    overlap = shadow.agreement(soft, hard)
    assert overlap["iou"] > 0.5, f"soft and hard casts disagree: {overlap}"


def test_soft_cast_has_a_gradient():
    """The whole point of the soft version: shadow disagreement must reach the heights."""
    torch = pytest.importorskip("torch")
    heights = torch.tensor(box_scene(10.0, size=80), requires_grad=True)
    sun = shadow.SunPosition(azimuth_deg=180.0, elevation_deg=40.0)
    shadow.cast_shadow_soft(heights, GSD, sun, sharpness=4.0).sum().backward()
    assert heights.grad is not None
    assert torch.isfinite(heights.grad).all()
    assert heights.grad.abs().sum() > 0, "no gradient reached the height field"
