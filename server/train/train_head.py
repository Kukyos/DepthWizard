"""Train the metric height decoder on GAMUS.

    python -m train.train_head --steps 2000
    python -m train.train_head --held-out-city PHL      # honest transfer split
    python -m train.train_head --steps 20 --limit 3     # smoke test on whatever is local

Runs unchanged on the laptop and on a cloud GPU (D4): everything machine-specific comes from
config/.env, and batch size is the only thing worth changing between them.

Trains the DPT neck and output head; the DINOv2 backbone stays frozen. Target is metres
above ground, from GAMUS's `_AGL` layer.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from depthwizard import config, head  # noqa: E402
from train.datasets import GamusTiles, describe, splits  # noqa: E402


def evaluate(model, processor, device, data: GamusTiles, batches: int, batch: int) -> dict:
    """Validation L1 in metres, plus correlation. No gradient, no augmentation."""
    import torch

    mean = torch.tensor(processor.image_mean, device=device).view(1, 3, 1, 1)
    std = torch.tensor(processor.image_std, device=device).view(1, 3, 1, 1)

    model.eval()
    l1s, rs = [], []
    with torch.no_grad():
        for _ in range(batches):
            rgb, agl, mask = data.sample(batch)
            x = head.normalise(rgb, mean.cpu(), std.cpu()).to(device)
            pred = model(pixel_values=x).predicted_depth
            target = torch.as_tensor(agl, device=device)
            m = torch.as_tensor(mask, device=device)
            if pred.shape[-2:] != target.shape[-2:]:
                pred = torch.nn.functional.interpolate(
                    pred.unsqueeze(1), size=target.shape[-2:], mode="bilinear",
                    align_corners=False).squeeze(1)
            valid = m & torch.isfinite(target)
            if valid.sum() < 100:
                continue
            p, t = pred[valid].float(), target[valid].float()
            l1s.append(float((p - t).abs().mean()))
            if p.std() > 0 and t.std() > 0:
                rs.append(float(torch.corrcoef(torch.stack([p, t]))[0, 1]))
    model.train()
    model.backbone.eval()          # stays frozen and in eval mode throughout
    return {"val_l1_m": float(np.mean(l1s)) if l1s else float("nan"),
            "val_r": float(np.mean(rs)) if rs else float("nan")}


def main() -> int:
    import torch

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument("--batch", type=int, default=config.TRAIN_BATCH_SIZE)
    parser.add_argument("--crop", type=int, default=518)
    parser.add_argument("--lr", type=float, default=3e-5)
    parser.add_argument("--size", default="base", choices=("small", "base", "large"))
    parser.add_argument("--held-out-city", help="leave-one-city-out split (D9)")
    parser.add_argument("--limit", type=int, help="cap tiles per split, for smoke tests")
    parser.add_argument("--pilot", action="store_true",
                        help="split the val tiles when train has not downloaded yet. "
                             "Shares a city between train and val, so the numbers overstate "
                             "generalisation and are for convergence checking only.")
    parser.add_argument("--height-weight", type=float, default=0.0, metavar="SCALE",
                        help="weight pixels by 1 + height/SCALE, to counter the low-pixel "
                             "majority that drives range compression. 0 disables.")
    parser.add_argument("--eval-every", type=int, default=200)
    parser.add_argument("--out", default=str(config.WEIGHTS_DIR / "height_head.pt"))
    args = parser.parse_args()

    train_tiles, val_tiles = splits(config.GAMUS_ROOT, args.held_out_city, args.limit,
                                   allow_pilot=args.pilot)
    if not train_tiles or not val_tiles:
        print(f"Not enough tiles under {config.GAMUS_ROOT}.")
        print("  train:", len(train_tiles), " val:", len(val_tiles))
        print("Fetch some:  python -m tools.fetch_datasets --split val")
        return 1

    info = describe(train_tiles, val_tiles)
    print(json.dumps(info, indent=2))

    model, processor, device, counts = head.build(args.size, None)
    print(f"\ndevice {device}   trainable {counts['trainable']/1e6:.1f}M "
          f"of {counts['total']/1e6:.1f}M ({100*counts['trainable']/counts['total']:.0f}%)")

    train_data = GamusTiles(train_tiles, args.crop, augment=True, seed=0)
    val_data = GamusTiles(val_tiles, args.crop, augment=False, seed=1)

    params = [p for p in model.parameters() if p.requires_grad]
    optimiser = torch.optim.AdamW(params, lr=args.lr, weight_decay=1e-4)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=args.steps)
    scaler = torch.amp.GradScaler(device) if device == "cuda" else None

    mean = torch.tensor(processor.image_mean).view(1, 3, 1, 1)
    std = torch.tensor(processor.image_std).view(1, 3, 1, 1)

    model.train()
    model.backbone.eval()
    started = time.perf_counter()
    history: list[dict] = []
    best = float("inf")

    for step in range(1, args.steps + 1):
        rgb, agl, mask = train_data.sample(args.batch)
        x = head.normalise(rgb, mean, std).to(device)
        target = torch.as_tensor(agl, device=device)
        m = torch.as_tensor(mask, device=device)

        with torch.autocast(device_type=device, dtype=torch.float16, enabled=device == "cuda"):
            pred = model(pixel_values=x).predicted_depth
            if pred.shape[-2:] != target.shape[-2:]:
                pred = torch.nn.functional.interpolate(
                    pred.unsqueeze(1), size=target.shape[-2:], mode="bilinear",
                    align_corners=False).squeeze(1)
            loss = head.masked_loss(pred.float(), target, m,
                                    height_weight_scale=args.height_weight)

        if loss is None:
            continue
        optimiser.zero_grad(set_to_none=True)
        if scaler:
            scaler.scale(loss).backward()
            scaler.unscale_(optimiser)
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            scaler.step(optimiser)
            scaler.update()
        else:
            loss.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            optimiser.step()
        schedule.step()

        if step % 25 == 0 or step == 1:
            rate = step / (time.perf_counter() - started)
            print(f"  step {step:5d}/{args.steps}  loss {float(loss):7.3f}  "
                  f"{rate:5.2f} it/s", flush=True)

        if step % args.eval_every == 0 or step == args.steps:
            scores = evaluate(model, processor, device, val_data, 8, args.batch)
            print(f"    val  L1 {scores['val_l1_m']:.3f} m   r {scores['val_r']:+.4f}",
                  flush=True)
            history.append({"step": step, **scores})
            if scores["val_l1_m"] < best:
                best = scores["val_l1_m"]
                head.save(model, args.out, {
                    "created_utc": datetime.now(timezone.utc).isoformat(),
                    "backbone": head.bb.CHECKPOINTS[args.size],
                    "frozen": "backbone (DINOv2); neck and head trained",
                    "step": step, "steps_planned": args.steps,
                    "batch": args.batch, "crop": args.crop, "lr": args.lr,
                    "held_out_city": args.held_out_city,
                    "height_weight": args.height_weight,
                    "pilot_split": bool(args.pilot and not args.held_out_city),
                    "split": info, "history": history,
                    "best_val_l1_m": best,
                    "target": "metres above ground (GAMUS _AGL)",
                })
                print(f"    saved {args.out}  (best so far)", flush=True)

    print(f"\ndone in {(time.perf_counter()-started)/60:.1f} min. best val L1 {best:.3f} m")
    print(f"weights: {args.out}")
    print("\nNow re-run the harness to measure the delta against the zero-shot baseline:")
    print("  python -m eval.run_eval --split val")
    return 0


if __name__ == "__main__":
    sys.exit(main())
