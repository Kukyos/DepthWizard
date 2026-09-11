"""Checks on configuration that encode the project's hard rules.

These are not box-ticking tests. Each one fails if a rule in
docs/08-rules-and-conventions.md has been quietly violated by a config edit -- which is
the likeliest way for it to happen, since a constant is easier to change than a document.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from depthwizard import config


def test_gsd_floor_above_canonical():
    """Refusing below a floor is only meaningful if the floor is coarser than training GSD."""
    assert config.GSD_FLOOR_M > config.CANONICAL_GSD_M


def test_gsd_bands_are_contiguous_and_cover_everything():
    """A GSD with no band would silently drop out of the stratified report."""
    bands = config.GSD_BANDS_M
    assert bands[0][0] == 0.0, "bands must start at zero"
    assert bands[-1][1] == float("inf"), "bands must cover arbitrarily coarse imagery"
    for (_, upper), (lower, _) in zip(bands, bands[1:]):
        assert upper == lower, "bands must be contiguous, with no gap or overlap"


def test_units_are_distinct_strings():
    """Hard rule 2: 'relative' is a first-class state, not the absence of a flag.

    If these ever collapse to the same value, or one becomes falsy, a relative scene
    could present metre values.
    """
    assert config.Units.METRES_ABSOLUTE != config.Units.RELATIVE_UNITLESS
    assert config.Units.METRES_ABSOLUTE and config.Units.RELATIVE_UNITLESS


def test_landscape_classes_match_the_brief():
    """The brief names exactly these four. Stratified reporting is a requirement, not a choice."""
    assert set(config.LANDSCAPE_CLASSES) == {"urban", "sparse", "hilly", "forested"}


def test_classes_without_data_are_a_subset():
    """A class listed as dataless but not declared at all would never be reported as NO DATA."""
    assert set(config.LANDSCAPE_WITHOUT_DATA) <= set(config.LANDSCAPE_CLASSES)


def test_class_legend_is_not_invented():
    """U-01: six class names are known from the paper, their integer order is not.

    If someone fills this in, the placeholder flag must be cleared in the same edit --
    and that should only happen once the mapping is sourced empirically.
    """
    if config.GAMUS_CLASS_LEGEND_IS_PLACEHOLDER:
        assert config.GAMUS_CLASS_NAMES == {}, (
            "legend populated while still flagged as a placeholder -- either it was "
            "guessed, or the flag was not cleared. See U-01 in docs/10-unsourced.md."
        )
    else:
        assert len(config.GAMUS_CLASS_NAMES) >= 6


def test_tile_overlap_is_smaller_than_the_tile():
    assert 0 <= config.TILE_OVERLAP < config.TILE_SIZE


def test_confidence_coverage_range_brackets_one_sigma():
    """A +/-1 sigma band should contain ~68% of errors. The gate must bracket that."""
    low, high = config.CONFIDENCE_COVERAGE_RANGE
    assert low < 0.68 < high


def test_placeholders_are_enumerable():
    """The harness relies on this to refuse publishing numbers that rest on unsourced values."""
    for p in config.placeholders():
        assert p.key and p.doc_ref and p.blocks


def test_nodata_is_outside_any_plausible_elevation():
    """Earth's surface spans roughly -430 m to 8850 m. The sentinel must not collide."""
    assert config.DSM_NODATA < -500
