"""GAMUS tile loading and augmentation for height-head training.

Two things here are specific to overhead imagery and easy to get wrong.

**Augmentation.** A nadir orthophoto has no gravity direction in the image plane, so all
four 90-degree rotations and both mirror flips are valid — unlike egocentric photography,
where a vertical flip produces an image no camera could take. That gives 8x augmentation
for free, which matters on a dataset this size. What is *not* valid is any change to
brightness or contrast that would alter apparent structure, since we already know from the
baseline that the model's response to this domain is fragile.

**Masking.** GAMUS clamps AGL at -5.0 m and that value is not a nodata sentinel but is also
not a real height (U-05). Those pixels are excluded from the loss rather than trained
against, along with the unlabelled background class. Training on a clamp would teach the
model to predict the clamp.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from depthwizard import config  # noqa: E402
from eval.scenes import Tile, discover, leave_one_city_out  # noqa: E402


class GamusTiles:
    """Random crops from GAMUS tiles, with masks marking which pixels may be trained on."""

    def __init__(self, tiles: list[Tile], crop: int = 518, augment: bool = True,
                 seed: int = 0):
        if not tiles:
            raise ValueError("no tiles given")
        self.tiles = tiles
        self.crop = crop
        self.augment = augment
        self.rng = np.random.default_rng(seed)

    def __len__(self) -> int:
        return len(self.tiles)

    def _crop(self, *arrays):
        h, w = arrays[0].shape[:2]
        if h < self.crop or w < self.crop:
            raise ValueError(f"tile {h}x{w} is smaller than the {self.crop} crop")
        top = int(self.rng.integers(0, h - self.crop + 1))
        left = int(self.rng.integers(0, w - self.crop + 1))
        return [a[top:top + self.crop, left:left + self.crop] for a in arrays]

    def _augment(self, rgb, agl, cls):
        # All 8 dihedral transforms are valid for nadir imagery: no horizon, no gravity.
        k = int(self.rng.integers(0, 4))
        if k:
            rgb, agl, cls = (np.rot90(a, k) for a in (rgb, agl, cls))
        if self.rng.random() < 0.5:
            rgb, agl, cls = (np.fliplr(a) for a in (rgb, agl, cls))
        return [np.ascontiguousarray(a) for a in (rgb, agl, cls)]

    def sample(self, count: int):
        """A batch of (rgb uint8, agl float32, mask bool) crops."""
        rgbs, agls, masks = [], [], []
        for _ in range(count):
            tile = self.tiles[int(self.rng.integers(0, len(self.tiles)))]
            rgb, agl, cls = self._crop(tile.rgb(), tile.agl(), tile.cls())
            if self.augment:
                rgb, agl, cls = self._augment(rgb, agl, cls)

            # Exclude the AGL clamp and unlabelled background from the loss (see U-05).
            mask = (cls != config.GAMUS_BACKGROUND_CLASS) & (agl > config.GAMUS_AGL_CLAMP_M + 1e-3)
            # The decoder ends in ReLU, so it cannot emit negatives; clamp the few remaining
            # sub-zero targets to 0 rather than asking it to predict something it cannot.
            agls.append(np.maximum(agl, 0.0).astype(np.float32))
            rgbs.append(rgb.astype(np.uint8))
            masks.append(mask)
        return np.stack(rgbs), np.stack(agls), np.stack(masks)


def splits(root: Path, held_out_city: str | None = None, limit: int | None = None):
    """Training and validation tiles.

    Default is the official GAMUS split. Passing `held_out_city` gives the leave-one-city-out
    split instead, which is the honest transfer estimate and the one we quote when the two
    disagree (D9) -- evaluation is on imagery from another country, so a split that shares
    city appearance between train and test will flatter us.
    """
    train = discover(root, "train", limit)
    val = discover(root, "val", limit)

    if held_out_city:
        pool = train + val
        train, val = leave_one_city_out(pool, held_out_city)
    return train, val


def describe(train: list[Tile], val: list[Tile]) -> dict:
    from collections import Counter

    return {
        "train_tiles": len(train),
        "val_tiles": len(val),
        "train_cities": dict(Counter(t.city for t in train)),
        "val_cities": dict(Counter(t.city for t in val)),
    }
