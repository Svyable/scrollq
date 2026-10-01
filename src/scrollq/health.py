"""Unified data-health report for a single volume.

Combines the two halves of the suite:

- **integrity** (zarr-pyramid-audit): header-only pyramid audit —
  missing levels, chunkless levels, metadata drift. "Don't train on lies."
- **quality** (scrollq): sampled voxel decode scored 0-100 —
  signal, texture, dynamic range, dead slices. "Train on the best first."

One command answers: should anyone train on this volume?
"""

from __future__ import annotations

import argparse
import json

from zpa.httpstore import open_store
from zpa.zarrmeta import read_pyramid
from zpa.audit_pyramid import audit_one

from .score import score_volume


def health_report(base_url: str, root: str, samples: int = 24,
                 spread: int = 5) -> dict:
    report: dict = {"root": root, "base_url": base_url,
                   "quality_samples": samples, "quality_spread": spread}

    # --- integrity: header-only, never reads array data ---
    store = open_store(base_url)
    try:
        pm = read_pyramid(store, root)
        findings, levels, prec = audit_one(pm)
    except Exception as exc:
        findings, levels, prec = [], [], {}
        report["integrity_error"] = str(exc)
    high = [f for f in findings if f["severity"] == "high"]
    med = [f for f in findings if f["severity"] == "medium"]
    integrity = ("FAIL" if high else
                 "WARN" if med else "PASS")
    report["integrity"] = {
        "verdict": integrity,
        "n_levels": prec.get("n_levels", 0),
        "n_findings": len(findings),
        "high": [{"code": f["code"], "level": f["level"],
                  "detail": f["detail"][:160]} for f in high],
        "medium": [{"code": f["code"], "level": f["level"],
                    "detail": f["detail"][:160]} for f in med],
    }

    # --- quality: sampled voxel decode (24 samples, 5x5x5 grid: the campaign standard) ---
    q = score_volume(base_url, root, samples=samples, spread=spread)
    report["quality"] = q

    # --- combined verdict ---
    if integrity == "FAIL":
        verdict, reason = ("DO NOT TRAIN",
                           f"{len(high)} high-severity integrity finding(s)")
    elif integrity == "WARN":
        verdict, reason = ("CAUTION",
                           f"{len(med)} medium-severity integrity finding(s)")
    elif not q.get("ok"):
        verdict, reason = ("CAUTION",
                           f"quality unscorable: {q.get('error', '?')}")
    elif q["score"] < 40:
        verdict, reason = ("CAUTION",
                           f"quality score {q['score']} below 40")
    else:
        verdict, reason = ("TRAIN",
                           f"integrity {integrity}, quality {q['score']}")
    report["verdict"] = verdict
    report["verdict_reason"] = reason
    return report


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Unified data-health report: integrity + quality")
    ap.add_argument("--root", required=True,
                    help="volume root, e.g. community-uploads/forrest/volcomp/PHerc0009B/volumes/....zarr")
    ap.add_argument("--base", default="https://dl.ash2txt.org")
    ap.add_argument("--samples", type=int, default=24,
                    help="quality samples per volume (campaign standard: 24)")
    ap.add_argument("--spread", type=int, default=5,
                    help="per-dimension candidate spread (campaign standard: 5)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rep = health_report(args.base, args.root,
                        samples=args.samples, spread=args.spread)
    text = json.dumps(rep, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {args.out}")
    print(f"\nverdict: {rep['verdict']} ({rep['verdict_reason']})")
    print(f"integrity: {rep['integrity']['verdict']} "
          f"({rep['integrity']['n_levels']} levels, "
          f"{rep['integrity']['n_findings']} findings)")
    q = rep["quality"]
    if q.get("ok"):
        print(f"quality: {q['score']}/100 "
              f"(signal {q['components']['signal_40']}, "
              f"texture {q['components']['texture_30']}, "
              f"dynamic {q['components']['dynamic_20']})")
    else:
        print(f"quality: unscorable ({q.get('error')})")


if __name__ == "__main__":
    main()
