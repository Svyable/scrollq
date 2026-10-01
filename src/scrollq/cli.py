"""Console entry points: scrollq-score, scrollq-leaderboard."""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor

from .score import score_volume


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Score Vesuvius scroll volumes by data quality")
    ap.add_argument("--base", default="https://dl.ash2txt.org",
                    help="base URL of the volume store")
    ap.add_argument("--volumes", required=True,
                    help="text file with one volume root per line")
    ap.add_argument("--samples", type=int, default=4,
                    help="chunks decoded per volume")
    ap.add_argument("--spread", type=int, default=3,
                    help="per-dimension shard-candidate count (spread^3 candidates)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    with open(args.volumes, encoding="utf-8") as fh:
        roots = [l.strip() for l in fh if l.strip()]
    os.makedirs(args.out_dir, exist_ok=True)

    def work(root: str):
        print(f"scoring {root}", flush=True)
        try:
            return score_volume(args.base, root, samples=args.samples,
                                spread=args.spread)
        except Exception as exc:
            # Containment, not suppression: the failure is recorded in
            # volumes.json so one bad volume cannot discard a whole
            # campaign's results (ex.map re-raises on iteration).
            return {"root": root, "ok": False,
                    "error": f"unhandled {type(exc).__name__}: {exc}"}

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for res in ex.map(work, roots):
            results.append(res)
    results.sort(key=lambda r: r.get("score", -1), reverse=True)

    out = os.path.join(args.out_dir, "volumes.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=1)
    ok = sum(1 for r in results if r.get("ok"))
    partial = sum(
        1 for r in results
        if r.get("ok") and not r.get("sampling", {}).get("complete", True)
    )
    print(f"\nscored {ok}/{len(results)} volumes -> {out}")
    if partial:
        print(f"warning: {partial} scored volume(s) used fewer chunks than requested")
    for r in results[:10]:
        if r.get("ok"):
            print(f"  {r['score']:5.1f}  {r['root'].split('/')[-1]}")
