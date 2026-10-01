"""Run the pre-registered stability test, version 2 (October goal O5).

Protocol and decision rule: docs/stability-v2-protocol.md, implemented in
src/scrollq/stability_protocol.py. For every volume in volumes.txt this scores
run A and run B at 48 chunks (primary) and at 24 chunks (secondary), using the
balanced candidate order and interleaved shard-disjoint parts. It records every
run's full sampling provenance, checks that A and B share no chunk, and writes
the verdict computed by decide().

    python bin/stability_v2.py OUT_DIR [--volumes volumes.txt] [--workers 8]
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from scrollq import stability_protocol as sp  # noqa: E402
from scrollq.score import score_volume  # noqa: E402

BASE = "https://dl.ash2txt.org"


def _score(root: str, n: int, part: tuple[int, int]) -> dict:
    try:
        return score_volume(BASE, root, samples=n, spread=sp.SPREAD, order=sp.ORDER, part=part)
    except Exception as exc:  # noqa: BLE001 - one volume must not stop the campaign
        return {"root": root, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _identities(run: dict) -> set[str]:
    return {p["identity"] for p in run.get("sample_provenance") or []}


def run_campaign(roots: list[str], workers: int = 8, scorer=_score) -> dict:
    jobs = [(root, n, part) for root in roots for n in (sp.N_PRIMARY, sp.N_SECONDARY) for part in sp.PARTS]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda job: scorer(*job), jobs))
    runs: dict[int, dict[tuple[int, int], dict[str, dict]]] = {
        n: {part: {} for part in sp.PARTS} for n in (sp.N_PRIMARY, sp.N_SECONDARY)
    }
    for (root, n, part), result in zip(jobs, results):
        runs[n][part][root] = result

    overlap = {
        n: {root: sorted(_identities(runs[n][sp.PARTS[0]][root]) & _identities(runs[n][sp.PARTS[1]][root]))
            for root in roots}
        for n in runs
    }
    violations = {n: {r: ids for r, ids in o.items() if ids} for n, o in overlap.items()}
    arms = {
        n: sp.arm_summary(runs[n][sp.PARTS[0]], runs[n][sp.PARTS[1]], n) for n in runs
    }
    primary = arms[sp.N_PRIMARY]
    if any(violations.values()):
        decision = {"verdict": "PROTOCOL_VIOLATION", "overlapping_chunks": violations}
    else:
        decision = sp.decide(primary)
    a, b = runs[sp.N_PRIMARY][sp.PARTS[0]], runs[sp.N_PRIMARY][sp.PARTS[1]]
    rows = {
        r: {"a": a[r]["score"], "b": b[r]["score"], "pooled": sp.pooled_score(a[r], b[r])}
        for r in primary["eligible_roots"]
    }
    return {
        "constants": sp.preregistered_constants(),
        "decision": decision,
        "arms": {str(n): arm for n, arm in arms.items()},
        "rank_bands": sp.rank_bands(rows) if rows else {},
        "pooled_scores": {r: v["pooled"] for r, v in rows.items()},
        "runs": {
            str(n): {f"part{part[1]}": by_part[part] for part in sp.PARTS}
            for n, by_part in runs.items()
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out_dir")
    ap.add_argument("--volumes", default=str(ROOT / "volumes.txt"))
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    roots = [line.strip() for line in open(args.volumes, encoding="utf-8") if line.strip()]
    result = run_campaign(roots, workers=args.workers)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        commit = None
    result["generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result["source_commit"] = commit
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "stability-v2.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    summary = {k: result[k] for k in ("constants", "decision", "generated_at", "source_commit")}
    summary["arms"] = {n: {k: v for k, v in arm.items() if k != "eligible_roots"} for n, arm in result["arms"].items()}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary["decision"], indent=2))
    for n, arm in summary["arms"].items():
        print(f"N={n}: eligible {arm['eligible']}/{arm['volumes']} rho={arm['spearman_rho']} "
              f"mean|d|={arm['mean_abs_diff']} shift={arm['mean_shift_b_minus_a']}")


if __name__ == "__main__":
    main()
