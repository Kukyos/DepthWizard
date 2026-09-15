"""Turn a DSM plus its source image into something the viewer can load.

    python -m depthwizard.mesh out/scene_DSM.tif --rgb scene.h5 -o viewer/public/scene

Writes three files into one directory:

    manifest.json   units, extent, vertical range, provenance -- the viewer reads units
                    from here and never infers them (hard rule 2)
    height.bin      raw float32, row-major, mesh resolution
    texture.png     the original optical image, full resolution

Raw float32 rather than a 16-bit PNG heightmap on purpose: a PNG would quantise heights
into 65536 buckets, and quantisation error in a DSM is indistinguishable from model error
once it reaches the viewer. The file is larger and exactly right.

Mesh resolution is decoupled from texture resolution. A 1024x1024 DSM is a million vertices
if taken literally, which no browser enjoys; the texture stays full resolution because
projection accuracy is the first thing the evaluation criteria name, and that is a texture
property, not a geometry one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from . import config, io_raster
from .overlays import build_overlays, error_statistics

# 1024 keeps the mesh at the DSM's own resolution. 512 halved it, which threw away
# exactly the edge detail the tiled + edge-refined inference exists to recover.
# A million vertices is comfortable for one tile; large rasters will need LOD.
DEFAULT_MESH_SIZE = 1024


def _resample(field: np.ndarray, size: int) -> np.ndarray:
    """Nearest-neighbour decimation onto a size x size grid.

    Nearest rather than averaged: averaging a DSM rounds off roof edges, and a roof that
    slopes into the street looks wrong immediately in a flythrough. Sharpness matters more
    than smoothness for built structures.
    """
    rows, cols = field.shape
    if (rows, cols) == (size, size):
        return field.astype(np.float32)
    r = np.linspace(0, rows - 1, size).round().astype(int)
    c = np.linspace(0, cols - 1, size).round().astype(int)
    return field[np.ix_(r, c)].astype(np.float32)


def export(
    dsm_path: str | Path,
    out_dir: str | Path,
    rgb_path: str | Path | None = None,
    mesh_size: int = DEFAULT_MESH_SIZE,
    reference_path: str | Path | None = None,
) -> Path:
    from PIL import Image

    dsm_path, out_dir = Path(dsm_path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    heights, info = io_raster.read_dsm(dsm_path)
    nodata = info.get("nodata")
    valid = heights != nodata if nodata is not None else np.ones_like(heights, bool)
    if not valid.any():
        raise ValueError(f"{dsm_path.name} contains no valid data")

    # Fill nodata with the minimum valid height rather than leaving sentinels in the mesh:
    # a -9999 vertex would stretch the terrain into a spike across the whole scene.
    clean = np.where(valid, heights, heights[valid].min()).astype(np.float32)
    mesh = _resample(clean, mesh_size)

    (out_dir / "height.bin").write_bytes(mesh.tobytes(order="C"))

    texture_written = False
    if rgb_path:
        rgb = _load_rgb(Path(rgb_path))
        Image.fromarray(rgb).save(out_dir / "texture.png")
        texture_written = True

    # Overlays are computed here, in numpy, where the geospatial context already lives --
    # gsd, units, nodata. Doing it in a shader would mean reimplementing all of that in GLSL
    # for no gain, since these are static per scene.
    reference = None
    if reference_path:
        reference = _load_reference(Path(reference_path), clean.shape)
    overlay_files = build_overlays(clean, out_dir, gsd_m=(info.get("provenance") or {}).get(
        "gsd_in_m") or config.GAMUS_GSD_M, reference=reference)

    provenance = info.get("provenance") or {}
    units = info.get("units") or config.Units.RELATIVE_UNITLESS
    manifest = {
        "id": dsm_path.stem,
        "units": units,
        "crs": info.get("crs"),
        "sourceSize": [int(heights.shape[1]), int(heights.shape[0])],
        "meshSize": mesh_size,
        "heightFile": "height.bin",
        "textureFile": "texture.png" if texture_written else None,
        "overlays": overlay_files,
        # Numbers to sit beside the error overlay. The brief puts validation inside the
        # app, as something a user does, so the figures travel with the scene.
        "validation": (error_statistics(clean, reference, metric=units in config.Units.METRIC)
                       if reference is not None else None),
        "verticalRange": [float(clean.min()), float(clean.max())],
        "gsdOutM": provenance.get("gsd_in_m"),
        "gsdVerified": provenance.get("gsd_verified", True),
        "gsdAssumedM": provenance.get("gsd_assumed_m"),
        "objectsResolvable": provenance.get("objects_resolvable", True),
        "confidenceM": provenance.get("confidence_m"),
        "provenance": provenance,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf8")
    return out_dir


def _load_reference(path: Path, shape: tuple[int, int]) -> np.ndarray | None:
    """Ground-truth heights for the validation view, on the DSM's grid."""
    if path.suffix.lower() == ".h5":
        import h5py

        with h5py.File(path, "r") as f:
            ref = f[config.GAMUS_H5_KEY][()]
    else:
        ref, _ = io_raster.read_dsm(path)
    ref = np.asarray(ref, dtype=np.float32)
    if ref.shape != shape:
        print(f"  reference is {ref.shape}, DSM is {shape}; skipping validation overlay")
        return None
    return ref


def _load_rgb(path: Path) -> np.ndarray:
    if path.suffix.lower() == ".h5":
        import h5py

        with h5py.File(path, "r") as f:
            array = f[config.GAMUS_H5_KEY][()]
    else:
        array, _ = io_raster.read_scene(path)
    array = np.asarray(array)
    if array.ndim == 2:
        array = np.repeat(array[..., None], 3, axis=2)
    array = array[..., :3]
    if array.dtype != np.uint8:
        lo, hi = float(array.min()), float(array.max())
        array = (((array.astype(np.float32) - lo) / max(hi - lo, 1e-6)) * 255).astype(np.uint8)
    return array


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dsm", help="DSM GeoTIFF produced by depthwizard.dsm")
    parser.add_argument("-o", "--out", required=True, help="output scene directory")
    parser.add_argument("--rgb", help="the optical image to drape over it")
    parser.add_argument("--mesh-size", type=int, default=DEFAULT_MESH_SIZE)
    parser.add_argument("--reference", help="ground truth heights, for the validation view")
    args = parser.parse_args()

    out = export(args.dsm, args.out, args.rgb, args.mesh_size, args.reference)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf8"))
    print(f"wrote {out}")
    for key in ("units", "sourceSize", "meshSize", "verticalRange"):
        print(f"  {key:14s} {manifest[key]}")
    print(f"  {'overlays':14s} {sorted(manifest['overlays'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
