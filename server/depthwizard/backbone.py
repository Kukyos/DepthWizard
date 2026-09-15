"""Depth Anything V2 -- the pre-trained monocular depth backbone the brief asks for.

What this produces is **relative inverse depth**: a unitless field where larger means nearer
the camera. Two conversions therefore stand between it and a DSM, and both are somebody
else's job:

  sign    looking straight down, nearer the camera means higher off the ground, so the
          field is flipped here into a height-like ordering. Still unitless.
  scale   turning that ordering into metres is calibrate.py's problem, and the brief's
          stated core challenge.

Expect the zero-shot output on overhead imagery to be poor. The model was trained on
egocentric photographs where perspective carries depth, and a nadir orthophoto has almost
none; it partly reports albedo and texture instead. That is the domain gap, and measuring
it honestly in Phase 1 is what makes the Phase 3 delta mean anything (docs/04-targets.md).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np

from . import config

# Verified present on the Hub, 2026-09-15. Pinned by name here and by revision at load
# time, because "latest" is not a provenance (hard rule 3).
CHECKPOINTS = {
    "small": "depth-anything/Depth-Anything-V2-Small-hf",
    "base": "depth-anything/Depth-Anything-V2-Base-hf",
    "large": "depth-anything/Depth-Anything-V2-Large-hf",
}
DEFAULT_SIZE = "base"     # fits 8 GB VRAM comfortably; large is for the cloud GPU


@dataclass(frozen=True)
class DepthResult:
    """Relative height ordering, plus enough provenance to reproduce it."""

    relative: np.ndarray          # (H, W) float32, unitless, larger = higher
    backbone_id: str
    revision: str
    device: str
    input_size: tuple[int, int]

    def provenance(self) -> dict[str, Any]:
        return {
            "backbone": self.backbone_id,
            "backbone_revision": self.revision,
            "backbone_device": self.device,
            "backbone_input_size": list(self.input_size),
            "output_kind": "relative_inverse_depth_flipped_to_height_ordering",
        }


def pick_device() -> str:
    if config.TORCH_DEVICE:
        return config.TORCH_DEVICE
    try:
        import torch
    except ImportError:
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


@lru_cache(maxsize=2)
def _load(size: str, device: str):
    """Load once and keep. Raises with a useful message rather than a bare ImportError."""
    try:
        import torch
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    except ImportError as exc:
        raise RuntimeError(
            f"{exc.name} is not installed. Run: .\\run.ps1 -Setup\n"
            "Note that torch must come from the CUDA index or it installs CPU-only."
        ) from exc

    model_id = CHECKPOINTS[size]
    processor = AutoImageProcessor.from_pretrained(model_id, cache_dir=config.WEIGHTS_DIR)
    model = AutoModelForDepthEstimation.from_pretrained(model_id, cache_dir=config.WEIGHTS_DIR)
    model.to(device).eval()

    # The encoder stays frozen throughout Phase 1: this is the honest zero-shot baseline,
    # and the number it produces is a deliverable, not a throwaway.
    for param in model.parameters():
        param.requires_grad_(False)

    revision = getattr(getattr(model, "config", None), "_commit_hash", None) or "unpinned"
    return processor, model, revision, torch


def estimate_relative_depth(rgb: np.ndarray, size: str = DEFAULT_SIZE) -> DepthResult:
    """Run the backbone on an (H, W, 3) uint8 image and return a height-like ordering."""
    if rgb.ndim != 3 or rgb.shape[2] < 3:
        raise ValueError(f"expected an (H, W, 3) RGB image, got {rgb.shape}")
    rgb = rgb[..., :3]
    if rgb.dtype != np.uint8:
        # 16-bit satellite products are common; scale per-image rather than clipping, which
        # would flatten exactly the bright roofs whose height we care about.
        lo, hi = float(rgb.min()), float(rgb.max())
        rgb = (((rgb.astype(np.float32) - lo) / max(hi - lo, 1e-6)) * 255).astype(np.uint8)

    device = pick_device()
    processor, model, revision, torch = _load(size, device)

    inputs = processor(images=rgb, return_tensors="pt").to(device)
    with torch.no_grad():
        predicted = model(**inputs).predicted_depth

    # Back to the source grid. The model works at its own internal resolution, and the DSM
    # must land on exactly the input grid or the georeferencing is a lie (hard rule 5).
    resized = torch.nn.functional.interpolate(
        predicted.unsqueeze(1), size=rgb.shape[:2], mode="bicubic", align_corners=False,
    ).squeeze()
    depth = resized.detach().cpu().numpy().astype(np.float32)

    # Depth Anything emits inverse depth: larger = nearer. From a nadir viewpoint nearer
    # means taller, so the ordering is already height-like and needs no flip -- but it is
    # normalised here so downstream code never depends on the raw scale, which varies
    # per image and is meaningless anyway.
    lo, hi = float(np.nanmin(depth)), float(np.nanmax(depth))
    relative = (depth - lo) / max(hi - lo, 1e-6)

    return DepthResult(
        relative=relative.astype(np.float32),
        backbone_id=CHECKPOINTS[size],
        revision=revision,
        device=device,
        input_size=(rgb.shape[0], rgb.shape[1]),
    )


def estimate_stub(rgb: np.ndarray) -> DepthResult:
    """A deterministic stand-in for wiring up the pipeline without the model.

    Explicitly NOT a prediction, and labelled as such in provenance so no number derived
    from it can be mistaken for a result. It exists so the chain can be tested end to end
    while the backbone weights are still downloading -- nothing more.
    """
    grey = rgb[..., :3].mean(axis=2).astype(np.float32)
    lo, hi = float(grey.min()), float(grey.max())
    digest = hashlib.sha256(rgb[..., :3].tobytes()).hexdigest()[:12]
    return DepthResult(
        relative=((grey - lo) / max(hi - lo, 1e-6)).astype(np.float32),
        backbone_id=f"STUB-NOT-A-PREDICTION:{digest}",
        revision="none",
        device="none",
        input_size=(rgb.shape[0], rgb.shape[1]),
    )
