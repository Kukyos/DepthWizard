"""Work out which GAMUS class index is which land-cover type, from evidence.

    python -m tools.resolve_class_legend            # all local tiles with a full triplet
    python -m tools.resolve_class_legend --limit 40

The GAMUS paper names six types -- ground, low-vegetation, building, water, road, tree --
but neither the paper nor the official loader says which integer is which, and inspection
finds seven distinct values (0..6). Guessing the order would put invented domain data into
a system whose whole argument is that its numbers are measured (U-01, D-04).

So this measures it instead. Each class index gets profiled on properties that separate the
six types unambiguously:

  height      buildings and trees stand well above ground; roads, water and bare ground
              sit at ~0 m AGL by construction, since AGL is height above the ground surface
  greenness   2G - R - B, positive for living vegetation, near zero for concrete and water
  brightness  water is dark in RGB; bare ground and concrete are bright
  flatness    height variance within the class -- water is the flattest surface there is
  area        ground and road dominate the pixel count; water is usually a small minority

The mapping is then argued from those numbers rather than assumed, and nothing is written
to config.py automatically: this prints the evidence and its proposed reading, and a human
confirms. Report sample size with any conclusion -- three tiles is a hint, not a finding.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from depthwizard import config  # noqa: E402


def triplets(root: Path, limit: int | None) -> list[tuple[Path, Path, Path]]:
    """Every tile that has all three layers locally. Partial tiles are skipped, not guessed."""
    found: list[tuple[Path, Path, Path]] = []
    for split in ("train", "val", "test"):
        img_dir = root / "images" / split
        if not img_dir.is_dir():
            continue
        for img in sorted(img_dir.glob("*_RGB.h5")):
            stem = img.name[: -len("_RGB.h5")]
            agl = root / "heights" / split / f"{stem}_AGL.h5"
            cls = root / "classes" / split / f"{stem}_CLS.h5"
            if agl.exists() and cls.exists():
                found.append((img, agl, cls))
            if limit and len(found) >= limit:
                return found
    return found


def profile(files: list[tuple[Path, Path, Path]]) -> dict[int, dict[str, float]]:
    """Accumulate per-class statistics across tiles."""
    import h5py

    acc: dict[int, dict[str, float]] = {}
    for img_p, agl_p, cls_p in files:
        with h5py.File(img_p, "r") as f:
            rgb = f[config.GAMUS_H5_KEY][()].astype(np.float32)
        with h5py.File(agl_p, "r") as f:
            agl = f[config.GAMUS_H5_KEY][()].astype(np.float32)
        with h5py.File(cls_p, "r") as f:
            cls = f[config.GAMUS_H5_KEY][()].astype(np.int32)

        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        greenness = 2.0 * g - r - b          # excess green: positive for live vegetation
        brightness = rgb.mean(axis=-1)

        for idx in np.unique(cls):
            mask = cls == idx
            a = acc.setdefault(int(idx), {"n": 0.0, "h": 0.0, "h2": 0.0,
                                          "green": 0.0, "bright": 0.0, "hi": 0.0})
            heights = agl[mask]
            a["n"] += mask.sum()
            a["h"] += float(heights.sum())
            a["h2"] += float((heights.astype(np.float64) ** 2).sum())
            a["green"] += float(greenness[mask].sum())
            a["bright"] += float(brightness[mask].sum())
            a["hi"] += float((heights > 2.0).sum())    # fraction standing clear of the ground
    return acc


def summarise(acc: dict[int, dict[str, float]]) -> dict[int, dict[str, float]]:
    total = sum(a["n"] for a in acc.values())
    out = {}
    for idx, a in sorted(acc.items()):
        n = a["n"]
        mean_h = a["h"] / n
        var = max(0.0, a["h2"] / n - mean_h**2)
        out[idx] = {
            "share": 100.0 * n / total,
            "mean_h": mean_h,
            "std_h": var**0.5,
            "above2m": 100.0 * a["hi"] / n,
            "green": a["green"] / n,
            "bright": a["bright"] / n,
        }
    return out


def propose(stats: dict[int, dict[str, float]]) -> dict[int, str]:
    """Argue a mapping from the profile.

    Deliberately conservative: a class only gets a name when the evidence for it is
    distinctive. Anything ambiguous is left unnamed rather than filled in with a guess,
    because a wrong legend is worse than a missing one -- it would silently mislabel every
    stratified metric downstream.
    """
    named: dict[int, str] = {}
    taken: set[str] = set()

    def claim(idx: int, name: str) -> None:
        if name not in taken:
            named[idx] = name
            taken.add(name)

    tall = {i: s for i, s in stats.items() if s["above2m"] > 25}
    flat = {i: s for i, s in stats.items() if i not in tall}

    # Among tall classes, trees are the green ones and buildings are not.
    for idx in sorted(tall, key=lambda i: -tall[i]["green"]):
        claim(idx, "tree" if tall[idx]["green"] > 5 else "building")

    # Among flat classes: water is dark and the most uniform; vegetation is green;
    # of what remains, the larger share is ground and the smaller is road.
    if flat:
        water = min(flat, key=lambda i: flat[i]["bright"])
        if flat[water]["bright"] < 90 and flat[water]["std_h"] < 2.0:
            claim(water, "water")
        veg = max(flat, key=lambda i: flat[i]["green"])
        if veg not in named and flat[veg]["green"] > 5:
            claim(veg, "low-vegetation")
        rest = sorted((i for i in flat if i not in named), key=lambda i: -flat[i]["share"])
        for idx, name in zip(rest, ("ground", "road")):
            claim(idx, name)
    return named


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, help="stop after this many tiles")
    args = parser.parse_args()

    files = triplets(config.GAMUS_ROOT, args.limit)
    if not files:
        print(f"no complete tile triplets under {config.GAMUS_ROOT}")
        print("run: python -m tools.fetch_datasets --sample 20 --split val")
        return 1

    print(f"profiling {len(files)} tiles from {config.GAMUS_ROOT}\n")
    stats = summarise(profile(files))

    print(f"{'idx':>3}  {'share%':>7} {'meanAGL':>8} {'stdAGL':>7} {'>2m%':>6} "
          f"{'green':>7} {'bright':>7}")
    print("-" * 56)
    for idx, s in stats.items():
        print(f"{idx:>3}  {s['share']:7.2f} {s['mean_h']:8.2f} {s['std_h']:7.2f} "
              f"{s['above2m']:6.1f} {s['green']:7.1f} {s['bright']:7.1f}")

    named = propose(stats)
    print("\nproposed reading of the evidence:")
    for idx in sorted(stats):
        print(f"  {idx} -> {named.get(idx, '?  (ambiguous, left unnamed on purpose)')}")

    missing = {"ground", "low-vegetation", "building", "water", "road", "tree"} - set(named.values())
    if missing:
        print(f"\nunassigned names: {sorted(missing)}")

    print(f"\nsample size: {len(files)} tiles.")
    print("Confirm against more tiles before writing this into config.GAMUS_CLASS_NAMES,")
    print("and clear GAMUS_CLASS_LEGEND_IS_PLACEHOLDER in the same edit. See U-01.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
