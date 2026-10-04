#!/usr/bin/env python3
"""Census the stored value distribution of published uint8 surface predictions.

Question answered: is a published surface-prediction array *graded* (many
nonzero values, so a confidence exists) or *binary* (one nonzero value, so the
export already discarded confidence)? Probability-threshold and confidence-guided
conformal constructions are only meaningful on a graded source.

The census is a read-only sample, not an exhaustive scan. Candidate chunks come
from ``scrollq.support._candidates`` (per-dimension spread, AGENTS.md lesson 1)
with a fixed seed. Chunks that are unstored or entirely zero carry no
information about the encoding and are skipped but counted. A verdict is
``unverified`` when no chunk with a nonzero voxel was inspected (lesson 9): a
clean answer about nothing is not ``binary``.

It reads no CT, no TIFXYZ and no ROI, and uses no ink.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Protocol

import numpy as np
import requests

from scrollq.support import ZarrV2Level, _candidates

SCHEMA = "scrollq-surface-prediction-value-census-v1"


class _Level(Protocol):
    shape: tuple[int, ...]
    chunks: tuple[int, ...]

    def chunk(self, idx: tuple[int, int, int]) -> np.ndarray | None: ...


def census(
    level: _Level,
    candidates: Iterable[tuple[int, int, int]],
    max_chunks: int,
) -> dict[str, Any]:
    """Tally nonzero values over up to ``max_chunks`` informative chunks."""
    hist = np.zeros(256, dtype=np.int64)
    used: list[list[int]] = []
    unstored = all_zero = 0
    for idx in candidates:
        if len(used) >= max_chunks:
            break
        arr = level.chunk(idx)
        if arr is None:
            unstored += 1
            continue
        counts = np.bincount(arr.ravel(), minlength=256)
        if counts[1:].sum() == 0:
            all_zero += 1
            continue
        hist += counts
        used.append(list(idx))
    nonzero_values = [int(v) for v in np.nonzero(hist[1:])[0] + 1]
    if not used:
        verdict = "unverified"
    elif len(nonzero_values) == 1:
        verdict = "binary"
    else:
        verdict = "graded"
    return {
        "verdict": verdict,
        "chunks_inspected": len(used),
        "chunk_ids": used,
        "unstored_candidates_skipped": unstored,
        "all_zero_chunks_skipped": all_zero,
        "nonzero_voxels": int(hist[1:].sum()),
        "distinct_nonzero_values": len(nonzero_values),
        "nonzero_histogram": {str(v): int(hist[v]) for v in nonzero_values},
    }


def census_url(
    url: str, session: requests.Session, *, per_dim: int, seed: int, max_chunks: int
) -> dict[str, Any]:
    level = ZarrV2Level(url, session)
    grid = tuple(math.ceil(s / c) for s, c in zip(level.shape, level.chunks))
    result = census(level, _candidates(grid, per_dim, seed), max_chunks)
    return {
        "url": url,
        "shape": list(level.shape),
        "chunks": list(level.chunks),
        "seed": seed,
        "per_dim": per_dim,
        "max_chunks": max_chunks,
        **result,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--url", action="append", required=True,
                   help="uint8 zarr v2 level-array URL; repeatable")
    p.add_argument("--per-dim", type=int, default=5)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--max-chunks", type=int, default=8)
    p.add_argument("--out", type=Path, required=True,
                   help="create-only result JSON; an existing file is refused")
    args = p.parse_args(argv)

    if args.out.exists():
        print(f"refusing to overwrite {args.out}", file=sys.stderr)
        return 2
    session = requests.Session()
    results = [
        census_url(u, session, per_dim=args.per_dim, seed=args.seed,
                   max_chunks=args.max_chunks)
        for u in args.url
    ]
    doc = {
        "schema": SCHEMA,
        "sampled_not_exhaustive": True,
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    for r in results:
        print(f"{r['verdict']:>10}  chunks={r['chunks_inspected']:>3}  "
              f"nonzero_voxels={r['nonzero_voxels']}  {r['url']}")
    return 0 if all(r["verdict"] != "unverified" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
