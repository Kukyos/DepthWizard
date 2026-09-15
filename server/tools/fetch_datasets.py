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


_FILE_LIST: list[str] | None = None


def _repo_files(api, retries: int = 8) -> list[str]:
    """The repo's file list, fetched once and retried.

    Cached because phases() needs it once per split per group and the listing is ~26k
    entries; fetching it six times is both slow and six chances for a flaky connection to
    kill the run before a single byte of data is downloaded. Retried for the same reason --
    this failed on a hotspot with the listing, not the transfer.
    """
    global _FILE_LIST
    if _FILE_LIST is not None:
        return _FILE_LIST
    for attempt in range(1, retries + 1):
        try:
            _FILE_LIST = api.list_repo_files(REPO_ID, repo_type="dataset")
            return _FILE_LIST
        except Exception as exc:                      # noqa: BLE001 -- any transport error
            if attempt == retries:
                raise
            wait = min(30, 3 * attempt)
            print(f"  listing failed ({type(exc).__name__}); retrying in {wait}s", flush=True)
            time.sleep(wait)
    return []


def _common_stems(api, split: str) -> list[str]:
    """Tile stems present in all three layers of a split."""
    files = _repo_files(api)

    def stems(layer: str) -> set[str]:
        prefix, suffix = f"{layer}/{split}/", f"_{LAYERS[layer]}.h5"
        return {
            f[len(prefix):-len(suffix)]
            for f in files
            if f.startswith(prefix) and f.endswith(suffix)
        }

    return sorted(stems("images") & stems("heights") & stems("classes"))


def phases(api, splits: tuple[str, ...], count: int | None = None) -> list[tuple[str, list[str]]]:
    """Download work split into ordered phases, most useful first.

    Ordering matters more here than it looks, and passing an ordered pattern list does NOT
    achieve it: snapshot_download sorts internally, so whatever order you hand it, it walks
    the repo alphabetically -- classes/, then heights/, then images/. Measured, twice. The
    first run spent 11 GB and produced 3 usable tiles; the second, with patterns carefully
    ordered by tile, did exactly the same thing.

    The only way to control order is to call snapshot_download more than once, each call
    restricted to one group. So: imagery and heights first, because those are what training
    and evaluation actually need, and the semantic masks last -- they are the smallest part
    of the value and, through the accident above, already almost entirely on disk.
    """
    plan: list[tuple[str, list[str]]] = []
    for split in splits:
        common = _common_stems(api, split)
        chosen = common if count is None else common[:count]
        print(f"  {split:6s} {len(common):5d} complete triplets, taking {len(chosen)}")
        # images + heights together: a tile needs both to be trainable, and neither alone.
        pairs = [f"{layer}/{split}/{stem}_{LAYERS[layer]}.h5"
                 for stem in chosen for layer in ("images", "heights")]
        plan.append((f"{split}: imagery + heights", pairs))
    for split in splits:
        common = _common_stems(api, split)
        chosen = common if count is None else common[:count]
        plan.append((f"{split}: semantic masks",
                     [f"classes/{split}/{stem}_CLS.h5" for stem in chosen]))
    if not any(patterns for _, patterns in plan):
        print("no complete triplets found")
        raise SystemExit(1)
    return plan


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

    # Phased, most useful first -- see phases() for why one call cannot do this.
    splits = (args.split,) if args.split else ("val", "train", "test")
    plan = phases(api, splits, args.sample)

    print(f"repo        {REPO_ID}")
    print(f"destination {root}")
    print(f"phases      {len(plan)}")
    print("resumable -- interrupting and rerunning picks up where it stopped.")

    for label, patterns in plan:
        if not patterns:
            continue
        print("")
        print(f"=== {label}  ({len(patterns)} files) ===", flush=True)
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
                print("interrupted -- rerun to resume.")
                return 130
            except Exception as exc:                  # noqa: BLE001 -- any transport error
                if attempt == args.retries:
                    print(f"{label} failed after {attempt} attempts: "
                          f"{type(exc).__name__}: {exc}")
                    print("progress is kept; rerun to resume from here.")
                    status()
                    return 1
                wait = min(60, 5 * 2 ** (attempt - 1))
                print(f"attempt {attempt} failed ({type(exc).__name__}: {exc})")
                print(f"retrying in {wait}s -- downloaded files are kept", flush=True)
                time.sleep(wait)

    print("done.")
    status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
