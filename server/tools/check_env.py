"""Environment report. Run before trusting any timing or accuracy number.

    python -m tools.check_env

Exists because this machine was found with the CPU build of torch installed alongside an
RTX 4060 -- CUDA silently unavailable, every performance number meaningless (D-01 in
docs/11-deferred.md). That class of problem is invisible until something explicitly looks
for it, so something explicitly looks for it.

Exit code is 0 if the pipeline can run at all, 1 if a hard dependency is missing. A
missing GPU is reported loudly but is not an error: the pipeline works on CPU, slowly.
"""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from depthwizard import config  # noqa: E402

OK, WARN, BAD = "  ok ", " warn", " MISS"

# Hard dependencies: the pipeline cannot run without these.
REQUIRED = ["numpy", "rasterio", "pyproj", "scipy", "PIL", "h5py", "fastapi", "uvicorn"]
# Soft: needed for specific stages, not for the whole thing to import.
OPTIONAL = {
    "torch": "the backbone",
    "transformers": "loading Depth Anything V2",
    "cv2": "shadow detection",
    "pvlib": "solar geometry for the shadow anchor",
    "trimesh": "glTF export for the viewer",
    "pytest": "the test suite",
}


def _ver(mod) -> str:
    return getattr(mod, "__version__", "?")


def check_packages() -> bool:
    print("packages")
    ok = True
    for name in REQUIRED:
        try:
            print(f"  {OK}  {name:16s} {_ver(importlib.import_module(name))}")
        except ImportError:
            print(f"  {BAD}  {name:16s} required -- run .\\run.ps1 -Setup")
            ok = False
    for name, why in OPTIONAL.items():
        try:
            print(f"  {OK}  {name:16s} {_ver(importlib.import_module(name))}")
        except ImportError:
            print(f"  {WARN}  {name:16s} absent -- needed for {why}")
    return ok


def check_gpu() -> None:
    """Report the CUDA state plainly, including the CPU-build trap."""
    print("\ngpu")
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run(
                [smi, "--query-gpu=name,memory.total,driver_version",
                 "--format=csv,noheader"],
                capture_output=True, text=True, timeout=20, check=False,
            ).stdout.strip()
            for line in out.splitlines():
                print(f"  {OK}  device         {line.strip()}")
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"  {WARN}  nvidia-smi failed: {exc}")
    else:
        print(f"  {WARN}  nvidia-smi not on PATH -- no NVIDIA driver visible")

    try:
        import torch
    except ImportError:
        print(f"  {WARN}  torch absent, cannot check CUDA")
        return

    build = "cpu-only" if "+cu" not in torch.__version__ else torch.__version__.split("+")[1]
    print(f"  {OK if '+cu' in torch.__version__ else WARN}  torch build    "
          f"{torch.__version__}  ({build})")

    if torch.cuda.is_available():
        print(f"  {OK}  cuda           available, {torch.cuda.get_device_name(0)}")
        free, total = torch.cuda.mem_get_info()
        print(f"  {OK}  vram           {free // 2**20} MiB free of {total // 2**20} MiB")
    else:
        print(f"  {WARN}  cuda           NOT AVAILABLE -- inference and training will")
        print("                         run on CPU, and every timing number is")
        print("                         meaningless until this is fixed.")
        if smi and "+cu" not in torch.__version__:
            print("                         Cause: the CPU build of torch is installed on a")
            print("                         machine that has a GPU. This is D-01. Fix:")
            print("                         pip install torch --index-url \\")
            print("                           https://download.pytorch.org/whl/cu130")


def check_data() -> None:
    print("\ndata")
    gamus = config.GAMUS_ROOT
    if (gamus / "images").is_dir():
        n = sum(1 for _ in (gamus / "images").rglob("*.h5"))
        print(f"  {OK}  gamus          {n} image tiles under {gamus}")
    else:
        print(f"  {WARN}  gamus          absent ({gamus}) -- ~80 GB, start the download")
    for label, path in (("srtm cache", config.SRTM_CACHE_DIR),
                        ("weights", config.WEIGHTS_DIR),
                        ("samples", config.SAMPLES_DIR)):
        files = list(path.iterdir()) if path.is_dir() else []
        mark = OK if files else WARN
        print(f"  {mark}  {label:14s} {len(files)} files in {path}")


def check_placeholders() -> None:
    """Unsourced values that must not silently become published findings."""
    print("\nunsourced values (docs/10-unsourced.md)")
    ph = config.placeholders()
    if not ph:
        print(f"  {OK}  none -- every configured value is sourced")
        return
    for p in ph:
        print(f"  {WARN}  {p.key:22s} {p.doc_ref}  blocks: {p.blocks}")


def main() -> int:
    print(f"DepthWizard environment report\npython {sys.version.split()[0]}\n")
    ok = check_packages()
    check_gpu()
    check_data()
    check_placeholders()
    print("\n" + ("ready" if ok else "NOT ready -- install missing required packages"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
