"""Join ScrolIQ scores with S3 label/segment coverage per scroll.

Reads the S3 bucket's discovered Zarr roots and counts, per scroll,
ink-detection roots and surface-volume (segment) roots. Output is a
coverage map consumed by the leaderboard builder.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--s3-roots", required=True,
                    help="discover_zarr.roots.jsonl from the S3 audit")
    ap.add_argument("--volumes", required=True,
                    help="volumes.json from scrollq-score")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    ink = Counter()
    surf = Counter()
    with open(args.s3_roots, encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)["root"]
            scroll = r.split("/")[0]
            if "ink-detection" in r:
                ink[scroll] += 1
            if "surface-volumes" in r:
                surf[scroll] += 1

    with open(args.volumes, encoding="utf-8") as fh:
        vols = json.load(fh)
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
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(coverage, fh, indent=1)
    n_next = sum(1 for c in coverage.values() if c["label_next"])
    print(f"coverage for {len(coverage)} volumes; "
          f"{n_next} flagged label-next (q75={q75:.1f})")
