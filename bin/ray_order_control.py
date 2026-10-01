"""Injection control for the umbilicus ray-order winding check.

A clean ray-order result means little unless the check can catch a wrong
winding number on the same real geometry. This harness measures that
directly: it takes the published annotations, mis-numbers ONE real point at a
time by a fixed shift (sign drawn at random), reruns the check, and records
whether the corrupted point surfaces in the review queue and at what rank.

Points the unmodified data already flags are excluded from sampling, so every
detection is attributable to the injection. A point with no comparable pair
after the shift cannot be flagged at all; it is counted as "untestable" and
reported separately rather than silently folded into recall.

    python bin/ray_order_control.py DATASET OUT.json [--injections 200]
        [--shifts 2,3,5] [--seed 0] [--umbilicus PATH]

DATASET holds abs_winding.json / relative_windings.json and umbilicus.json in
the spiral-fitting layout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from scrollq.winding_geometry import check_ray_order, load_umbilicus  # noqa: E402

ROLE_FILES = {"absolute": "abs_winding.json", "relative": "relative_windings.json"}
UNLIMITED = 10**9


def _key(role: str, collection_id: str, point_id: str) -> str:
    frame = "absolute" if role == "absolute" else f"relative:{collection_id}"
    return f"{frame}|{collection_id}|{point_id}"


def _pool(documents: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(role, collection_id, point_id) of every point the check can evaluate."""
    out = []
    for role, document in documents.items():
        for cid, collection in (document.get("collections") or {}).items():
            if not isinstance(collection, dict):
                continue
            for pid, point in (collection.get("points") or {}).items():
                if not isinstance(point, dict):
                    continue
                wind = point.get("wind_a")
                if isinstance(wind, (int, float)) and not isinstance(wind, bool) and float(wind).is_integer():
                    out.append((role, str(cid), str(pid)))
    return sorted(out)


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    testable = [row for row in rows if row["testable"]]
    detected = [row for row in testable if row["rank"] is not None]
    ranks = [row["rank"] for row in detected]
    return {
        "injections": len(rows),
        "testable": len(testable),
        "untestable": len(rows) - len(testable),
        "detected": len(detected),
        "recall_of_testable": len(detected) / len(testable) if testable else None,
        "recall_of_all": len(detected) / len(rows) if rows else None,
        "rank1_of_detected": sum(r == 1 for r in ranks) / len(ranks) if ranks else None,
        "median_rank_of_detected": statistics.median(ranks) if ranks else None,
    }


def run_control(
    documents: dict[str, Any],
    umbilicus,
    *,
    injections: int = 200,
    shifts: tuple[int, ...] = (2, 3, 5),
    seed: int = 0,
) -> dict[str, Any]:
    baseline = check_ray_order(documents, umbilicus, max_review_points=UNLIMITED)
    flagged = {_key(item["role"], item["collection_id"], item["point_id"]) for item in baseline["review_queue"]}
    pool = [p for p in _pool(documents) if _key(*p) not in flagged]
    rng = random.Random(seed)
    sample = rng.sample(pool, min(injections, len(pool)))

    by_shift: dict[str, Any] = {}
    all_rows = []
    for shift in shifts:
        rows = []
        for role, cid, pid in sample:
            point = documents[role]["collections"][cid]["points"][pid]
            original = point["wind_a"]
            delta = shift if rng.random() < 0.5 else -shift
            point["wind_a"] = int(original) + delta
            try:
                report = check_ray_order(
                    documents,
                    umbilicus,
                    max_review_points=UNLIMITED,
                    max_candidates=0,
                    include_point_comparisons=True,
                )
            finally:
                point["wind_a"] = original
            key = _key(role, cid, pid)
            rank = next(
                (
                    index
                    for index, item in enumerate(report["review_queue"], start=1)
                    if _key(item["role"], item["collection_id"], item["point_id"]) == key
                ),
                None,
            )
            rows.append(
                {
                    "role": role,
                    "collection_id": cid,
                    "point_id": pid,
                    "delta": delta,
                    "testable": key in report["point_comparisons"],
                    "comparable_pairs": report["point_comparisons"].get(key, 0),
                    "rank": rank,
                    "queue_length": len(report["review_queue"]),
                }
            )
        by_shift[str(shift)] = {
            "summary": _summary(rows),
            "by_role": {
                role: _summary([row for row in rows if row["role"] == role])
                for role in ("absolute", "relative")
            },
            "injections": rows,
        }
        all_rows.extend(rows)

    return {
        "diagnostic": "umbilicus-ray-order-injection-control",
        "seed": seed,
        "shifts": list(shifts),
        "sample_size": len(sample),
        "pool_size": len(pool),
        "excluded_already_flagged": len(flagged),
        "baseline": {
            key: baseline[key]
            for key in ("status", "parameters", "points", "comparable_pairs", "inversion_candidates")
        },
        "by_shift": by_shift,
        "overall": _summary(all_rows),
        "method": (
            "One real annotated point at a time has its wind_a shifted by +/-shift "
            "(sign drawn from the seeded RNG); the ray-order check is rerun on the "
            "otherwise unmodified data. Detected = the corrupted point appears in "
            "the review queue; rank 1 = it heads the queue. Untestable = after the "
            "shift it has no comparable pair, so no ordering test can see it."
        ),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dataset")
    ap.add_argument("out")
    ap.add_argument("--injections", type=int, default=200)
    ap.add_argument("--shifts", default="2,3,5")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--umbilicus")
    args = ap.parse_args()

    dataset = Path(args.dataset)
    documents: dict[str, Any] = {}
    inputs: dict[str, str] = {}
    for role, name in ROLE_FILES.items():
        path = dataset / name
        if path.is_file():
            raw = path.read_bytes()
            inputs[name] = hashlib.sha256(raw).hexdigest()
            documents[role] = json.loads(raw)
    umbilicus_path = Path(args.umbilicus) if args.umbilicus else dataset / "umbilicus.json"
    umbilicus = load_umbilicus(umbilicus_path)
    inputs["umbilicus.json"] = umbilicus.sha256

    shifts = tuple(int(part) for part in args.shifts.split(","))
    report = run_control(
        documents, umbilicus, injections=args.injections, shifts=shifts, seed=args.seed
    )
    report["inputs_sha256"] = inputs
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for shift, block in report["by_shift"].items():
        s = block["summary"]
        print(
            f"shift ±{shift}: detected {s['detected']}/{s['testable']} testable "
            f"({s['untestable']} untestable of {s['injections']}); "
            f"rank-1 share {s['rank1_of_detected']}; median rank {s['median_rank_of_detected']}"
        )


if __name__ == "__main__":
    main()
