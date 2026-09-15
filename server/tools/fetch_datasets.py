"""Download GAMUS, the dataset the organisation's reference repo recommends.

    python -m tools.fetch_datasets              # everything, ~80 GB
    python -m tools.fetch_datasets --split val  # one split, to start work sooner
    python -m tools.fetch_datasets --sample 12  # a dozen tile triplets, for development
    python -m tools.fetch_datasets --status     # what is on disk already

Destination comes from GAMUS_ROOT in .env (config.GAMUS_ROOT), which points off the system
drive -- 80 GB does not belong next to the source tree.

The transfer itself is huggingface_hub's snapshot_download: it already does resume,
parallel connections, hash verification and a local cache, so there is nothing here worth
reimplementing. This module exists for the parts it does not do -- choosing coherent
subsets, and keeping the triplets aligned.

Licence: GAMUS is CC-BY-4.0. It is downloaded, never redistributed by us.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from depthwizard import config  # noqa: E402

REPO_ID = "earthflow/GAMUS"
SPLITS = ("train", "val", "test")
# The three co-registered layers. Filenames share a stem and differ only in this suffix,
# which is what lets a sample stay aligned across all three.
LAYERS = {"images": "RGB", "heights": "AGL", "classes": "CLS"}


def _hub():
    try:
        from huggingface_hub import HfApi, snapshot_download
    except ImportError:
        print("huggingface_hub is not installed. Run: pip install huggingface_hub[hf_transfer]")
        raise SystemExit(1)
    return HfApi(), snapshot_download


def status() -> None:
    """What is on disk, per split and layer."""
    root = config.GAMUS_ROOT
    print(f"GAMUS_ROOT  {root}")
    if not root.exists():
        print("  (nothing downloaded yet)")
        return

    total_files = 0
    total_bytes = 0
    for layer in LAYERS:
        for split in SPLITS:
            d = root / layer / split
            if not d.is_dir():
                continue
            files = list(d.glob("*.h5"))
            size = sum(f.stat().st_size for f in files)
            total_files += len(files)
            total_bytes += size
            print(f"  {layer:8s} {split:6s} {len(files):5d} files  {size / 2**30:7.2f} GiB")
    print(f"  {'total':15s} {total_files:5d} files  {total_bytes / 2**30:7.2f} GiB")

    # The three layers must stay in lockstep: a tile with an image but no height is not
    # trainable, and a silent mismatch would show up much later as a confusing loader error.
    for split in SPLITS:
        counts = {
            layer: len(list((root / layer / split).glob("*.h5")))
            for layer in LAYERS
            if (root / layer / split).is_dir()
        }
        if counts and len(set(counts.values())) > 1:
            print(f"  WARNING  {split}: layers are out of step {counts} -- rerun to fill gaps")


def sample_patterns(api, count: int, split: str) -> list[str]:
    """Allow-patterns for `count` complete tile triplets from one split.

    Picks stems that exist in all three layers, so a development subset is never missing
    a height or a class map for an image it has.
    """
    files = api.list_repo_files(REPO_ID, repo_type="dataset")

    def stems(layer: str) -> set[str]:
        prefix, suffix = f"{layer}/{split}/", f"_{LAYERS[layer]}.h5"
        return {
            f[len(prefix):-len(suffix)]
            for f in files
            if f.startswith(prefix) and f.endswith(suffix)
        }

    common = sorted(stems("images") & stems("heights") & stems("classes"))
    if not common:
        print(f"no complete triplets found in split '{split}'")
        raise SystemExit(1)

    chosen = common[:count]
    print(f"{len(common)} complete triplets in '{split}'; taking {len(chosen)}")
    return [f"{layer}/{split}/{stem}_{suf}.h5" for stem in chosen for layer, suf in LAYERS.items()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=SPLITS, help="one split only")
    parser.add_argument("--sample", type=int, metavar="N",
                        help="N complete tile triplets only, for development")
    parser.add_argument("--status", action="store_true", help="report what is on disk, then exit")
    parser.add_argument("--workers", type=int, default=8, help="parallel downloads (default 8)")
    parser.add_argument("--retries", type=int, default=12,
                        help="attempts before giving up (default 12)")
    parser.add_argument("--no-xet", action="store_true",
                        help="use plain HTTPS instead of the Xet transfer backend, which is "
                             "what the first failed run died inside")
    args = parser.parse_args()

    if args.no_xet:
        os.environ["HF_HUB_DISABLE_XET"] = "1"

    if args.status:
        status()
        return 0

    api, snapshot_download = _hub()
    root = config.GAMUS_ROOT
    root.mkdir(parents=True, exist_ok=True)

    if args.sample:
        split = args.split or "val"     # val is the smallest split
        patterns = sample_patterns(api, args.sample, split)
    elif args.split:
        patterns = [f"{layer}/{args.split}/*" for layer in LAYERS]
    else:
        patterns = None                 # everything

    print(f"repo        {REPO_ID}")
    print(f"destination {root}")
    print(f"patterns    {patterns if patterns else 'ALL (~80 GB)'}")
    print("resumable -- interrupting and rerunning picks up where it stopped.\n")

    # An 80 GB transfer will meet a dropped connection sooner or later; the first attempt
    # died on one after about 1 GB. snapshot_download resumes from what is already on disk,
    # so a retry costs only the reconnect. Backoff is capped rather than unbounded so a
    # genuinely dead network fails in minutes instead of hanging overnight.
    for attempt in range(1, args.retries + 1):
        try:
            snapshot_download(
                repo_id=REPO_ID,
                repo_type="dataset",
                local_dir=root,
                allow_patterns=patterns,
                max_workers=args.workers,
            )
            break
        except KeyboardInterrupt:
            print("\ninterrupted -- rerun to resume.")
            return 130
        except Exception as exc:                      # noqa: BLE001 -- any transport error
            if attempt == args.retries:
                print(f"\nfailed after {attempt} attempts: {type(exc).__name__}: {exc}")
                print("progress is kept; rerun to resume from here.")
                status()
                return 1
            wait = min(60, 5 * 2 ** (attempt - 1))
            print(f"\nattempt {attempt} failed ({type(exc).__name__}: {exc})")
            print(f"retrying in {wait}s -- already-downloaded files are kept\n")
            time.sleep(wait)

    print("\ndone.")
    status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
