"""Unified data-health report for a single volume.

Combines the two halves of the suite:

- **integrity** (zarr-pyramid-audit): header-only pyramid audit —
  missing levels, chunkless levels, metadata drift. "Don't train on lies."
- **quality** (scrollq): sampled voxel decode scored 0-100 —
  signal, texture, dynamic range, dead slices. Scan-health triage only:
  "measure the bottleneck before you train."

One command answers: should anyone train on this volume?
"""

from __future__ import annotations

import argparse
import json
import math
from numbers import Real

from zpa.httpstore import open_store
from zpa.report import RECOMMENDED_CONSUMER_VERDICT, audit_root

from .score import score_volume

# Integrity states the companion contract says a consumer must not train on.
# UNKNOWN (unreadable level, absent root, nothing to audit) fails closed like
# FAIL: missing evidence is never read as a clean result.
_BLOCKING = {state for state, action in RECOMMENDED_CONSUMER_VERDICT.items()
             if action == "DO NOT TRAIN"}


def _finding_row(f: dict) -> dict:
    return {"code": f["code"], "severity": f["severity"], "level": f["level"],
            "evidence_state": f.get("evidence_state"),
            "detail": f["detail"][:160]}


def health_report(base_url: str, root: str, samples: int = 24,
                 spread: int = 5, *, store=None, scorer=score_volume) -> dict:
    for name, value in (("samples", samples), ("spread", spread)):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    report: dict = {"root": root, "base_url": base_url,
                   "quality_samples": samples, "quality_spread": spread}

    # --- integrity: header-only, never reads array data ---
    # zpa.report.audit_root never raises: transport failures become UNKNOWN
    # evidence and an unexpected exception becomes a high AUDIT_ERROR (FAIL).
    if store is None:
        store = open_store(base_url)
    audit = audit_root(store, root)
    integrity = audit["integrity"]
    findings = audit["findings"]
    high = [f for f in findings if f["severity"] == "high"]
    med = [f for f in findings if f["severity"] == "medium"]
    unknown = [f for f in findings if f.get("evidence_state") == "UNKNOWN"]
    if any(f["code"] == "AUDIT_ERROR" for f in findings):
        report["integrity_error"] = next(
            f["detail"] for f in findings if f["code"] == "AUDIT_ERROR")
    report["integrity"] = {
        "verdict": integrity,
        "consumer_action": RECOMMENDED_CONSUMER_VERDICT[integrity],
        "evidence": audit.get("evidence"),
        "schema_version": audit.get("schema_version"),
        "tool_version": audit.get("tool_version"),
        "n_levels": audit["coverage"]["levels_declared"],
        "n_findings": len(findings),
        "high": [_finding_row(f) for f in high],
        "medium": [_finding_row(f) for f in med],
        "unknown_evidence": [_finding_row(f) for f in unknown],
        "findings": [_finding_row(f) for f in findings],
    }

    # --- quality: sampled voxel decode (24 samples, 5x5x5 grid: the campaign standard) ---
    try:
        q = scorer(base_url, root, samples=samples, spread=spread)
    except Exception as exc:
        # A failed decode must not discard an already measured integrity
        # failure or prevent the caller from receiving a health verdict.
        q = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if not isinstance(q, dict):
        q = {"ok": False, "error": "scorer must return a quality dictionary"}
    report["quality"] = q
    score = q.get("score")
    sampling = q.get("sampling")

    # --- combined verdict ---
    if integrity == "FAIL":
        verdict, reason = ("DO NOT TRAIN",
                           f"{len(high)} high-severity integrity finding(s)")
    elif integrity in _BLOCKING:
        codes = sorted({f["code"] for f in unknown or findings}) or [
            (audit.get("evidence") or {}).get("reason") or "no auditable evidence"]
        verdict, reason = ("DO NOT TRAIN",
                           f"integrity {integrity}: missing evidence ({', '.join(codes)})")
    elif integrity == "WARN":
        verdict, reason = ("CAUTION",
                           f"{len(med)} medium-severity integrity finding(s)")
    elif q.get("ok") is not True:
        verdict, reason = ("CAUTION",
                           f"quality unscorable: {q.get('error', '?')}")
    elif (isinstance(score, bool) or not isinstance(score, Real)
          or not 0 <= score <= 100 or not math.isfinite(score)):
        verdict, reason = ("CAUTION", "quality score is invalid; expected finite 0–100")
    elif q["score"] < 40:
        verdict, reason = ("CAUTION",
                           f"quality score {q['score']} below 40")
    elif (not isinstance(sampling, dict)
          or sampling.get("complete") is not True
          or type(sampling.get("requested")) is not int
          or type(sampling.get("decoded")) is not int
          or samples <= 0
          or sampling["requested"] != samples
          or sampling["decoded"] != samples):
        verdict, reason = ("CAUTION", "quality sampling is incomplete or unverified")
    else:
        verdict, reason = ("TRAIN",
                           f"integrity {integrity}, quality {q['score']}")
    report["verdict"] = verdict
    report["verdict_reason"] = reason
    return report


def _positive_int(text: str) -> int:
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Unified data-health report: integrity + quality")
    ap.add_argument("--root", required=True,
                    help="volume root, e.g. community-uploads/forrest/volcomp/PHerc0009B/volumes/....zarr")
    ap.add_argument("--base", default="https://dl.ash2txt.org")
    ap.add_argument("--samples", type=_positive_int, default=24,
                    help="quality samples per volume (campaign standard: 24)")
    ap.add_argument("--spread", type=_positive_int, default=5,
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
    if q.get("ok") is True:
        print(f"quality: {q.get('score', 'unknown')}/100")
        components = q.get("components")
        if isinstance(components, dict):
            print(f"components: signal {components.get('signal_40', 'unknown')}, "
                  f"texture {components.get('texture_30', 'unknown')}, "
                  f"dynamic {components.get('dynamic_20', 'unknown')}")
        sampling = q.get("sampling")
        if isinstance(sampling, dict):
            print(f"sampling: {sampling.get('decoded', 'unknown')}/"
                  f"{sampling.get('requested', 'unknown')} chunks, "
                  f"complete={sampling.get('complete', 'unknown')}")
        else:
            print("sampling: unverified")
    else:
        print(f"quality: unscorable ({q.get('error')})")


if __name__ == "__main__":
    main()
