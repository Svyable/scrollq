"""Join ScrolIQ scores with S3 label/segment coverage per scroll.

Reads the S3 bucket's discovered Zarr roots and counts, per scroll,
ink-detection roots and surface-volume (segment) roots. Output is a
coverage map consumed by the leaderboard builder.

An inventory with no ink-detection and no surface-volume roots at all is
treated as a failed join, not as "nothing is labelled": the command exits
non-zero instead of flagging every top-quartile volume as label-next.
``--inventory-from`` rebuilds the join from the per-scroll counts recorded
in an earlier coverage.json when the S3 roots file is not at hand.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter


def counts_from_roots(path: str) -> tuple[Counter, Counter]:
    """Per-scroll ink-detection and surface-volume root counts."""
    ink: Counter = Counter()
    surf: Counter = Counter()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)["root"]
            scroll = r.split("/")[0]
            if "ink-detection" in r:
                ink[scroll] += 1
            if "surface-volumes" in r:
                surf[scroll] += 1
    return ink, surf


def counts_from_coverage(path: str) -> tuple[Counter, Counter]:
    """Per-scroll counts recorded in an earlier coverage.json.

    Every volume of a scroll must carry the same counts; disagreement means
    the source is not a single inventory and is rejected.
    """
    with open(path, encoding="utf-8") as fh:
        prior = json.load(fh)
    ink: Counter = Counter()
    surf: Counter = Counter()
    seen: dict[str, tuple[int, int]] = {}
    for root, c in prior.items():
        pair = (int(c["ink_labels"]), int(c["segments"]))
        if seen.setdefault(c["scroll"], pair) != pair:
            raise ValueError(f"inconsistent counts for {c['scroll']} in {path} "
                             f"({root}: {pair} vs {seen[c['scroll']]})")
        ink[c["scroll"]] = pair[0]
        surf[c["scroll"]] = pair[1]
    return ink, surf


def build_coverage(vols: list[dict], ink: Counter, surf: Counter) -> dict:
    if sum(ink.values()) == 0 and sum(surf.values()) == 0:
        raise ValueError("inventory has no ink-detection or surface-volume "
                         "roots; refusing to treat a failed join as zero labels")
    ok = [v for v in vols if v.get("ok")]
    scores = sorted(v["score"] for v in ok)
    q75 = scores[int(0.75 * len(scores))]

    coverage = {}
    for v in ok:
        scroll = next(p for p in v["root"].split("/")
                      if p.startswith("PHerc"))
        coverage[v["root"]] = {
            "scroll": scroll,
            "ink_labels": ink.get(scroll, 0),
            "segments": surf.get(scroll, 0),
            # top-quartile quality but no ink labels in the open-data
            # bucket: the "label this next" recommendation
            "label_next": bool(v["score"] >= q75
                               and ink.get(scroll, 0) == 0),
        }
    return coverage


def main() -> None:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--s3-roots",
                     help="discover_zarr.roots.jsonl from the S3 audit")
    src.add_argument("--inventory-from",
                     help="earlier coverage.json whose per-scroll counts to reuse")
    ap.add_argument("--volumes", required=True,
                    help="volumes.json from scrollq-score")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.volumes, encoding="utf-8") as fh:
        vols = json.load(fh)
    try:
        ink, surf = (counts_from_roots(args.s3_roots) if args.s3_roots
                     else counts_from_coverage(args.inventory_from))
        coverage = build_coverage(vols, ink, surf)
    except ValueError as exc:
        sys.exit(f"scrollq-coverage: {exc}")
    ok = [v for v in vols if v.get("ok")]
    q75 = sorted(v["score"] for v in ok)[int(0.75 * len(ok))]
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(coverage, fh, indent=1)
    n_next = sum(1 for c in coverage.values() if c["label_next"])
    print(f"coverage for {len(coverage)} volumes; "
          f"{n_next} flagged label-next (q75={q75:.1f})")


if __name__ == "__main__":
    main()
