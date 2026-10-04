#!/usr/bin/env python3
"""Compare the magnitude-only fiber descriptor with the seam authenticator.

Synthetic shifted copies only. For each seed, patch A is compared with
(1) a genuinely shifted copy, (2) a phase-randomized copy, (3) a block-shuffled
copy and (4) an unrelated sheet, using the existing ``tangent-fiber-spectrum-v1``
descriptor distance and the seam authenticator's verdict and peak z.

This records a prediction that failed: the descriptor is NOT blind to phase
randomization. The difference between the two tools is the output (a similarity
versus a calibrated correspondence), not a failure of the older descriptor.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

import scrollq.seam_fingerprint as sf
from scrollq.fiber_fingerprint import cosine_distance, tangent_fiber_spectrum

SCALE = 40.0  # lifts the unit-variance synthetic sheet over the descriptor's IQR floor
CROP = (slice(None), slice(8, 57), slice(8, 57))


def _summary(values):
    arr = np.asarray(values, dtype=np.float64)
    return {"min": float(arr.min()), "median": float(np.median(arr)), "max": float(arr.max())}


def run(seed_base: int, n: int) -> dict:
    rows = {k: {"descriptor_distance": [], "seam_peak_z": [], "seam_verdict": []}
            for k in ("genuine_copy", "phase_randomized_copy", "block_shuffled_copy", "unrelated_sheet")}
    for i in range(n):
        seed = seed_base + 3 * i
        rng = np.random.default_rng(seed)
        field = sf.synthetic_sheet(seed)
        a = sf._slab(field)
        b = sf._slab(sf._translate(field, 1.0, -1.0))
        variants = {
            "genuine_copy": b,
            "phase_randomized_copy": sf._phase_randomized(b, rng),
            "block_shuffled_copy": sf._block_shuffle(b, rng),
            "unrelated_sheet": sf._slab(sf.synthetic_sheet(seed + 1)),
        }
        fa = tangent_fiber_spectrum(SCALE * a[CROP])
        for name, patch in variants.items():
            rows[name]["descriptor_distance"].append(
                cosine_distance(fa, tangent_fiber_spectrum(SCALE * patch[CROP]))
            )
            result = sf.authenticate_pair(a, patch)
            rows[name]["seam_peak_z"].append(result["peak"]["z"])
            rows[name]["seam_verdict"].append(result["verdict"])
    out = {}
    for name, row in rows.items():
        verdicts = row["seam_verdict"]
        out[name] = {
            "descriptor_distance": _summary(row["descriptor_distance"]),
            "seam_peak_z": _summary(row["seam_peak_z"]),
            "seam_verdicts": {v: verdicts.count(v) for v in sf.VERDICTS},
        }
    return {
        "schema": "scrollq-seam-descriptor-comparison/1",
        "synthetic": True,
        "seed_base": seed_base,
        "n": n,
        "source_sha256": sf.source_sha256(),
        "numpy_version": np.__version__,
        "results": out,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="new JSON path")
    parser.add_argument("--seed-base", type=int, default=800_000)
    parser.add_argument("--n", type=int, default=20)
    args = parser.parse_args(argv)
    out = Path(args.out)
    if out.exists():
        print(f"refusing to overwrite {out}", file=sys.stderr)
        return 2
    report = run(args.seed_base, args.n)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    for name, row in report["results"].items():
        print(f"{name:24s} descriptor median={row['descriptor_distance']['median']:.4f} "
              f"seam z median={row['seam_peak_z']['median']:.1f} {row['seam_verdicts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
