#!/usr/bin/env python3
"""Re-derive the Grand Prize and First Letters frontiers from the v2 sampling design.

Input is the committed, pre-registered stability v2 run
(``artifacts/2026-10-stability-v2/stability-v2.json``: balanced order, spread 7,
two disjoint 48-chunk runs and their pooled 96-chunk score). Nothing is rescored.

For each prize the frontier is computed three times, with the unchanged
``scrollq.grand_prize.qualify``:

* ``pooled`` -- the v2 pooled score (primary, as in the leaderboard's rank bands);
* ``run_a`` / ``run_b`` -- each disjoint 48-chunk run alone.

A frontier member is ``robust`` only if it is on all three. Volumes whose v2
sample is incomplete get no score (AGENTS.md lesson 6) and stay off the frontier.

Usage: python bin/prize_frontier_v2.py <out_dir>
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from scrollq.grand_prize import MANIFESTS, qualify

ROOT = Path(__file__).resolve().parents[1]
STABILITY = ROOT / "artifacts/2026-10-stability-v2/stability-v2.json"
SEPTEMBER = {
    "grand-prize": ROOT / "artifacts/2026-09-30-grand-prize-qualifier-n24-dense/targets.json",
    "first-letters": ROOT / "artifacts/2026-09-30-first-letters-qualifier-n24-dense/targets.json",
}
ARM = "48"


def views(stability: dict) -> dict[str, list[dict]]:
    pooled = [{"root": r, "ok": True, "score": s} for r, s in stability["pooled_scores"].items()]

    def run(part: str) -> list[dict]:
        rows = []
        for root, v in stability["runs"][ARM][part].items():
            complete = bool(v.get("ok")) and bool((v.get("sampling") or {}).get("complete"))
            rows.append({"root": root, "ok": complete,
                         "score": v.get("score") if complete else None,
                         **({} if complete else {"error": "incomplete v2 sample"})})
        return rows

    return {"pooled": pooled, "run_a": run("part0"), "run_b": run("part1")}


def frontier_v2(stability: dict, prize: str) -> dict:
    manifest = MANIFESTS[prize]
    results = {name: qualify(vols, manifest) for name, vols in views(stability).items()}
    sets = {name: set(r["frontier"]) for name, r in results.items()}
    robust = sorted(set.intersection(*sets.values()))
    ever = sorted(set.union(*sets.values()))
    sept = json.loads(SEPTEMBER[prize].read_text())
    rows = []
    for t in results["pooled"]["targets"]:
        by = {name: next(x for x in r["targets"] if x["scroll"] == t["scroll"])
              for name, r in results.items()}
        rows.append({
            "scroll": t["scroll"],
            "volume_id": t["volume_id"],
            "segments": t["segments"],
            "score_pooled": by["pooled"]["quality_score"],
            "score_run_a": by["run_a"]["quality_score"],
            "score_run_b": by["run_b"]["quality_score"],
            "on_frontier": {name: t["scroll"] in sets[name] for name in sets},
            "qualification_pooled": by["pooled"].get("qualification"),
        })
    return {
        "prize": results["pooled"]["prize"],
        "manifest_as_of": manifest.get("as_of"),
        "frontier_pooled": results["pooled"]["frontier"],
        "frontier_run_a": results["run_a"]["frontier"],
        "frontier_run_b": results["run_b"]["frontier"],
        "robust_members": robust,
        "unstable_members": sorted(set(ever) - set(robust)),
        "september_frontier": sept["frontier"],
        "september_members_dropped": sorted(set(sept["frontier"]) - set(results["pooled"]["frontier"])),
        "targets": rows,
        "full_qualify_output": results,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    out = Path(argv[1])
    if out.exists() and any(out.iterdir()) and (out / "summary.json").exists():
        print(f"refusing to overwrite {out}", file=sys.stderr)
        return 2
    raw = STABILITY.read_bytes()
    stability = json.loads(raw)
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "source": str(STABILITY.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_commit": stability.get("source_commit"),
        "quality_measured": stability.get("generated_at"),
        "design": stability["constants"],
        "arm": ARM,
        "robustness_rule": "robust = on the pooled, run A and run B frontiers",
        "prizes": {},
    }
    for prize in MANIFESTS:
        result = frontier_v2(stability, prize)
        (out / f"{prize}.json").write_text(json.dumps(result, indent=1) + "\n")
        summary["prizes"][prize] = {k: result[k] for k in (
            "manifest_as_of", "frontier_pooled", "frontier_run_a", "frontier_run_b",
            "robust_members", "unstable_members", "september_frontier",
            "september_members_dropped")}
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary["prizes"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
