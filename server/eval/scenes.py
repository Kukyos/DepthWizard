"""Which tiles the harness runs on, and the splits it reports.

Two splits, always. The official GAMUS split shares cities between train and test, which
rewards a model for memorising city-specific appearance -- the same roof materials, street
grid and sun angle. Since evaluation is on ISRO imagery of another country, that split will
flatter us. Leave-one-city-out is the honest transfer estimate, and where the two disagree
it is the number we quote (D9).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from depthwizard import config


@dataclass(frozen=True)
class Tile:
    """One tile with all three layers present. Partial tiles are never half-used."""

    stem: str
    split: str
    rgb_path: Path
    agl_path: Path
    cls_path: Path

    @property
    def city(self) -> str:
        return self.stem.split("_")[0]

    def _read(self, path: Path) -> np.ndarray:
        import h5py

        with h5py.File(path, "r") as f:
            return f[config.GAMUS_H5_KEY][()]

    def rgb(self) -> np.ndarray:
        array = self._read(self.rgb_path)
        if array.ndim == 2:
            array = np.repeat(array[..., None], 3, axis=2)
        return array[..., :3]

    def agl(self) -> np.ndarray:
        return self._read(self.agl_path)

    def cls(self) -> np.ndarray:
        return self._read(self.cls_path).astype(int)


def discover(root: Path, split: str, limit: int | None = None) -> list[Tile]:
    """Every tile in a split with all three layers on disk.

    A tile missing its height or class layer is skipped rather than partially scored: a
    prediction with no reference contributes nothing, and silently dropping the reference
    would quietly change what the metric means.
    """
    img_dir = root / "images" / split
    if not img_dir.is_dir():
        return []

    tiles: list[Tile] = []
    for image in sorted(img_dir.glob("*_RGB.h5")):
        stem = image.name[: -len("_RGB.h5")]
        agl = root / "heights" / split / f"{stem}_AGL.h5"
        cls = root / "classes" / split / f"{stem}_CLS.h5"
        if agl.exists() and cls.exists():
            tiles.append(Tile(stem, split, image, agl, cls))
        if limit and len(tiles) >= limit:
            break
    return tiles


def leave_one_city_out(tiles: list[Tile], held_out: str) -> tuple[list[Tile], list[Tile]]:
    """Split by city, so the test set shares no scene appearance with training.

    This is the split whose number we publish when it disagrees with the official one.
    """
    keep = [t for t in tiles if t.city != held_out]
    out = [t for t in tiles if t.city == held_out]
    return keep, out


def cities(tiles: list[Tile]) -> list[str]:
    return sorted({t.city for t in tiles})
