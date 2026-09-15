"""Orchestrator: one image in, one DSM out, with provenance.

    python -m depthwizard.dsm scene.tif -o out/scene_DSM.tif
    python -m depthwizard.dsm tile.h5 -o out/t.tif --reference tile_AGL.h5

Phase 1 scope. There is no scale calibration yet, so **every output is relative** -- the
absolute path needs SRTM, shadow or GCP anchoring, which is Phase 2. A georeferenced input
therefore keeps its CRS and transform (so the raster lands correctly on a map) while still
declaring relative units, and the viewer shows no metre value for it.

That is deliberate rather than unfinished. Emitting metres before anything establishes a
scale would be exactly the fabrication hard rules 1 and 2 exist to prevent.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from . import backbone, config, io_raster
from .io_raster import SceneMeta


@dataclass(frozen=True)
class Product:
    heights: np.ndarray
    meta: SceneMeta
    provenance: dict[str, Any]


def _read_gamus(path: Path) -> np.ndarray:
    """Read a GAMUS HDF5 tile. Every layer stores one dataset named 'image'."""
    import h5py

    with h5py.File(path, "r") as f:
        return f[config.GAMUS_H5_KEY][()]


def load_any(path: str | Path) -> tuple[np.ndarray, SceneMeta]:
    """Read PNG/JPG/TIFF through rasterio, or a GAMUS .h5 tile.

    GAMUS tiles carry no CRS or transform at all (verified by inspection, D-03), so they
    take the relative path -- which is correct, not a workaround.
    """
    path = Path(path)
    if path.suffix.lower() != ".h5":
        return io_raster.read_scene(path)

    array = _read_gamus(path)
    if array.ndim == 2:
        array = array[..., None]
    meta = SceneMeta(
        path=str(path), width=array.shape[1], height=array.shape[0],
        band_count=array.shape[2], crs=None, transform=None, gsd_m=None,
        units=config.Units.RELATIVE_UNITLESS, driver="GAMUS-HDF5",
        dtype=str(array.dtype),
    )
    return array, meta


def estimate(path: str | Path, size: str = backbone.DEFAULT_SIZE,
             stub: bool = False) -> Product:
    """Run the pipeline on one image."""
    rgb, meta = load_any(path)
    if rgb.shape[2] == 1:
        rgb = np.repeat(rgb, 3, axis=2)

    started = perf_counter()
    result = backbone.estimate_stub(rgb) if stub else backbone.estimate_relative_depth(rgb, size)
    elapsed = perf_counter() - started

    provenance = {
        **result.provenance(),
        "pipeline_phase": 1,
        "calibration": "none -- Phase 2 not built; output is relative",
        "calibration_anchors": [],
        "confidence_m": None,
        "inference_seconds": round(elapsed, 3),
        "git_commit": _git_commit(),
        "unsourced_values": [p.key for p in config.placeholders()],
    }

    # Phase 1 has no anchor, so nothing can legitimately be called metres yet -- including
    # for a georeferenced input, whose CRS is still preserved for correct placement.
    meta_out = SceneMeta(**{**meta.__dict__, "units": config.Units.RELATIVE_UNITLESS})
    return Product(heights=result.relative, meta=meta_out, provenance=provenance)


def _git_commit() -> str:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
            cwd=Path(__file__).resolve().parents[2], check=False,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def score_against_reference(pred: np.ndarray, reference: np.ndarray) -> dict[str, float]:
    """Scale-free agreement between a relative prediction and metric ground truth.

    Absolute RMSE is undefined for a relative prediction, so only scale-free measures are
    reported here -- correlation, and RMSE after the single best global scale and shift are
    removed. Those are exactly the measures that say whether the *shape* is right, which is
    the question Phase 1 asks. Absolute error arrives with calibration in Phase 2.

    The fit is least-squares on the reference, so this is an evaluation-time measurement,
    never an inference-time one: nothing here feeds back into the product (hard rule 4).
    """
    pred = pred.astype(np.float64).ravel()
    ref = reference.astype(np.float64).ravel()
    ok = np.isfinite(pred) & np.isfinite(ref)
    pred, ref = pred[ok], ref[ok]
    if pred.size < 2:
        return {}

    correlation = float(np.corrcoef(pred, ref)[0, 1])
    # ref ~= a*pred + b
    a, b = np.polyfit(pred, ref, 1)
    fitted = a * pred + b
    residual = fitted - ref
    return {
        "pearson_r": correlation,
        "si_rmse_m": float(np.sqrt(np.mean(residual**2))),
        "si_mae_m": float(np.mean(np.abs(residual))),
        "fit_scale": float(a),
        "fit_offset_m": float(b),
        "reference_range_m": [float(ref.min()), float(ref.max())],
        "pixels": int(pred.size),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="PNG, JPG, TIFF/GeoTIFF, or a GAMUS .h5 tile")
    parser.add_argument("-o", "--out", required=True, help="output GeoTIFF path")
    parser.add_argument("--size", choices=sorted(backbone.CHECKPOINTS), default=backbone.DEFAULT_SIZE)
    parser.add_argument("--reference", help="ground-truth heights to score against (.h5 or raster)")
    parser.add_argument("--stub", action="store_true",
                        help="wire-test without the model; output is NOT a prediction")
    args = parser.parse_args()

    product = estimate(args.image, size=args.size, stub=args.stub)

    if args.reference:
        ref_path = Path(args.reference)
        ref = (_read_gamus(ref_path) if ref_path.suffix.lower() == ".h5"
               else io_raster.read_dsm(ref_path)[0])
        scores = score_against_reference(product.heights, ref)
        product.provenance["scored_against"] = str(ref_path)
        product.provenance["scale_free_scores"] = scores

    out = io_raster.write_dsm(args.out, product.heights, product.meta, product.provenance)

    print(f"wrote  {out}")
    print(f"       {out.with_suffix('.json')}")
    print(f"units  {product.meta.units}")
    print(f"crs    {product.meta.crs or 'none (relative)'}")
    print(f"model  {product.provenance['backbone']} on {product.provenance['backbone_device']}"
          f" in {product.provenance['inference_seconds']}s")
    if args.reference and product.provenance.get("scale_free_scores"):
        s = product.provenance["scale_free_scores"]
        print("\nscale-free agreement with reference (no calibration yet):")
        print(f"  pearson r    {s['pearson_r']:+.4f}")
        print(f"  SI-RMSE      {s['si_rmse_m']:.2f} m")
        print(f"  SI-MAE       {s['si_mae_m']:.2f} m")
        print(f"  ref range    {s['reference_range_m'][0]:.1f} to "
              f"{s['reference_range_m'][1]:.1f} m over {s['pixels']:,} px")
    return 0


if __name__ == "__main__":
    sys.exit(main())
