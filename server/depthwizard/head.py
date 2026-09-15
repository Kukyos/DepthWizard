"""The metric height head: Depth Anything V2 with its decoder retrained to predict nDSM.

The baseline measured what the frozen model does on overhead imagery -- r = +0.16 on
buildings, ~0 on canopy (docs/13-baseline-analysis.md). The encoder is clearly extracting
*something* structural; what fails is the mapping from those features to height, which was
learned from egocentric photographs where depth means distance-from-camera.

So the encoder is kept and the mapping is relearned:

    backbone   DINOv2, 86.6M params   FROZEN     general visual structure, still useful
    neck       DPT fusion, 10.8M      TRAINED    reassembles features into a dense map
    head       output conv, 0.09M     TRAINED    emits metres above ground

That is 11% of the parameters, which fits an 8 GB card at a useful batch size and cannot
destroy the pre-trained representation the way full fine-tuning on 5k tiles would.

The output is **metres above ground (nDSM)**, not absolute elevation -- the terrain term
comes from SRTM (D6). GAMUS supplies exactly this target as its `_AGL` layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import backbone as bb
from . import config


@dataclass(frozen=True)
class TrainConfig:
    size: str = "base"
    crop: int = 518            # 37 x 37 patches at patch_size 14
    batch: int = 2
    lr: float = 3e-5           # neck and head only; low enough not to thrash the decoder
    epochs: int = 8
    grad_accum: int = 4        # effective batch 8 without the memory of batch 8
    gradient_loss_weight: float = 0.5


def build(size: str = "base", device: str | None = None):
    """Load Depth Anything V2 with the backbone frozen and the decoder trainable."""
    import torch
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation

    device = device or bb.pick_device()
    model_id = bb.CHECKPOINTS[size]
    processor = AutoImageProcessor.from_pretrained(model_id, cache_dir=config.WEIGHTS_DIR)
    model = AutoModelForDepthEstimation.from_pretrained(model_id, cache_dir=config.WEIGHTS_DIR)

    for param in model.backbone.parameters():
        param.requires_grad_(False)
    model.backbone.eval()          # keeps norm layers from drifting on frozen weights
    for part in (model.neck, model.head):
        for param in part.parameters():
            param.requires_grad_(True)

    model.to(device)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    return model, processor, device, {"trainable": trainable, "total": total}


def normalise(rgb, mean, std):
    """Apply the processor's normalisation to a uint8 (B,H,W,3) batch."""
    import torch

    x = torch.as_tensor(np.ascontiguousarray(rgb)).float().div_(255.0)
    x = x.permute(0, 3, 1, 2)
    return (x - mean) / std


def masked_loss(pred, target, mask, gradient_weight: float = 0.5,
                height_weight_scale: float = 0.0):
    """L1 on valid pixels, plus a gradient term so edges stay sharp.

    Plain L1 alone produces the smeared mounds the zero-shot baseline already shows: it is
    minimised by blurring a roof edge across several metres, which costs little error but
    looks wrong in a flythrough and misplaces every building boundary. The gradient term
    penalises getting the *change* in height wrong, which is what a roof edge is.

    `height_weight_scale` addresses a different failure, found by measurement: the trained
    decoder under-predicts tall structures badly (about -14 m on canopy) while getting ground
    right to about a metre. Height is heavily right-skewed -- most pixels are near zero and a
    minority are tall -- so unweighted L1 is dominated by the low majority, and the cheapest
    way to reduce it is to pull everything toward the low mode. That is exactly the range
    compression observed.

    Setting a scale weights each pixel by `1 + target/scale`, so a 20 m tree counts several
    times a patch of road. Zero disables it, which is the default until it is shown to help.
    """
    import torch

    valid = mask & torch.isfinite(target)
    if valid.sum() < 16:
        return None

    error = (pred - target).abs()
    if height_weight_scale > 0:
        weights = 1.0 + target / height_weight_scale
        l1 = (error * weights)[valid].sum() / weights[valid].sum()
    else:
        l1 = error[valid].mean()

    # Finite differences, comparing only where both neighbours are valid.
    def grads(t):
        return t[..., :, 1:] - t[..., :, :-1], t[..., 1:, :] - t[..., :-1, :]

    px, py = grads(pred)
    tx, ty = grads(target)
    mx = valid[..., :, 1:] & valid[..., :, :-1]
    my = valid[..., 1:, :] & valid[..., :-1, :]
    gx = (px - tx).abs()[mx].mean() if mx.any() else l1.new_zeros(())
    gy = (py - ty).abs()[my].mean() if my.any() else l1.new_zeros(())

    return l1 + gradient_weight * (gx + gy)


def save(model, path: str | Path, meta: dict) -> Path:
    """Save only the trained parts. The frozen backbone is reproducible from its checkpoint."""
    import json

    import torch

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {"neck": model.neck.state_dict(), "head": model.head.state_dict(), "meta": meta},
        path,
    )
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf8")
    return path


def load_trained(size: str = "base", weights: str | Path | None = None, device: str | None = None):
    """Rebuild the model and restore trained decoder weights."""
    import torch

    model, processor, device, counts = build(size, device)
    if weights:
        state = torch.load(weights, map_location=device, weights_only=False)
        model.neck.load_state_dict(state["neck"])
        model.head.load_state_dict(state["head"])
        counts = {**counts, "weights": str(weights), "meta": state.get("meta", {})}
    model.eval()
    return model, processor, device, counts
