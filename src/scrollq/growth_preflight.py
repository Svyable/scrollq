"""Preflight Will Stevens scrollreading growth trees before bad-patch mode c.

This checker is intentionally geometry-free.  It reads the relationship graph
that mode c will consume, mirrors AugmentAlignmentMap's reverse-edge expansion,
checks that every relationship id has a corresponding patch file when a patch
folder is supplied, and counts graph-walk states through the chain lengths used
by BadPatchFinder::FindBadPatchesGeneral.

The walk count is not a runtime prediction: the optimized upstream code prunes
dead prefixes once bad/repeated patches are known.  It is a deterministic
tractability signal for exactly the combinatorial fan-out that made tangled
PHerc. 1447 growths impractical in the unpruned implementation.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = "scroliq-growth-preflight-v1"
UPSTREAM_PR = "https://github.com/WillStevens/scrollreading/pull/4"
UPSTREAM_ISSUE = "https://github.com/WillStevens/scrollreading/issues/2"
ARTICLE = (
    "https://github.com/evilaliv3/vesuvius-challenge-pipeline/blob/main/"
    "results/aeb2e975-badpatchfinder-acceleration/article.pdf"
)

WARNING_STATES = 50_000_000
HIGH_STATES = 1_000_000_000


def _parse_patch_number(name: str) -> int | None:
    """Mirror scrollreading's filename parsing for *.bin patch files."""

    if len(name) < 4 or not name.endswith(".bin"):
        return None
    digits = "".join(ch for ch in name if ch.isdigit())
    if not digits:
        return None
    return int(digits)


def patch_ids_from_dir(path: str | Path) -> set[int]:
    patch_dir = Path(path)
    if not patch_dir.is_dir():
        raise FileNotFoundError(f"patch directory does not exist: {patch_dir}")

    ids: set[int] = set()
    for item in patch_dir.iterdir():
        if not item.is_file():
            continue
        patch_id = _parse_patch_number(item.name)
        if patch_id is not None:
            ids.add(patch_id)
    return ids


def read_relationships(path: str | Path) -> list[tuple[int, int]]:
    """Read rel.csv endpoints using the same float-to-int semantics as C++."""

    rel_path = Path(path)
    edges: list[tuple[int, int]] = []
    with rel_path.open("r", newline="", encoding="utf-8") as fh:
        for line_no, row in enumerate(csv.reader(fh), start=1):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) < 2:
                raise ValueError(f"{rel_path}:{line_no}: expected at least two columns")
            try:
                a = int(float(row[0]))
                b = int(float(row[1]))
            except ValueError as exc:
                raise ValueError(
                    f"{rel_path}:{line_no}: relationship ids must be numeric"
                ) from exc
            edges.append((a, b))
    if not edges:
        raise ValueError(f"{rel_path}: no relationship rows found")
    return edges


def augment_adjacency(edges: Iterable[tuple[int, int]]) -> dict[int, list[int]]:
    """Mirror AugmentAlignmentMap: retain every edge and append its reverse."""

    adjacency: dict[int, list[int]] = defaultdict(list)
    frozen = list(edges)
    for a, b in frozen:
        adjacency[a].append(b)
    for a, b in frozen:
        adjacency[b].append(a)
    return dict(adjacency)


def _percentile_nearest_rank(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[idx]


def count_walk_states(
    adjacency: dict[int, list[int]],
    starts: set[int],
    max_chain_length: int,
) -> dict[str, int]:
    """Count exact augmented-graph walks for chain lengths 2..N in O(E*N)."""

    current = {patch_id: 1 for patch_id in starts if adjacency.get(patch_id)}
    out: dict[str, int] = {}
    for chain_length in range(2, max_chain_length + 1):
        nxt: dict[int, int] = defaultdict(int)
        for source, count in current.items():
            for target in adjacency.get(source, ()):
                nxt[target] += count
        out[str(chain_length)] = sum(nxt.values())
        current = dict(nxt)
    return out


def _runtime_risk(chain_states: dict[str, int]) -> str:
    peak = max(chain_states.values(), default=0)
    if peak >= HIGH_STATES:
        return "high"
    if peak >= WARNING_STATES:
        return "warning"
    return "low"


def analyze_growth(
    rel_csv: str | Path,
    *,
    patch_dir: str | Path | None = None,
    max_chain_length: int = 5,
) -> dict[str, object]:
    if not 2 <= max_chain_length <= 8:
        raise ValueError("max_chain_length must be between 2 and 8")

    edges = read_relationships(rel_csv)
    adjacency = augment_adjacency(edges)
    relationship_ids = set(adjacency)

    geometry_check = "not_run"
    patch_ids: set[int]
    missing_geometry: list[int] = []
    isolated_patches: list[int] = []

    if patch_dir is None:
        patch_ids = set(relationship_ids)
    else:
        geometry_check = "checked"
        patch_ids = patch_ids_from_dir(patch_dir)
        missing_geometry = sorted(relationship_ids - patch_ids)
        isolated_patches = sorted(pid for pid in patch_ids if not adjacency.get(pid))

    chain_states = count_walk_states(adjacency, patch_ids, max_chain_length)
    runtime_risk = _runtime_risk(chain_states)
    degrees = [len(adjacency.get(pid, ())) for pid in patch_ids if adjacency.get(pid)]
    peak = max(chain_states.values(), default=0)

    if missing_geometry:
        integrity = "blocked"
    elif geometry_check == "not_run":
        integrity = "unknown"
    else:
        integrity = "pass"

    if missing_geometry:
        recommendation = (
            "BLOCK: rel.csv references ids without patch geometry. Use a clean growth "
            "output directory or otherwise repair provenance before mode c; skipping "
            "those chains can avoid a crash but cannot prove the remaining alignments "
            "belong to one growth run."
        )
    elif runtime_risk == "high":
        recommendation = (
            "Runtime risk is high for the unpruned bad-patch enumerator. Use the "
            "prefix-pruning implementation in upstream PR #4 or an output-equivalent "
            "implementation, and preserve byte-identity regression evidence."
        )
    elif runtime_risk == "warning":
        recommendation = (
            "Runtime risk is elevated. Benchmark mode c on a fresh copy before scaling "
            "seed search, and prefer the output-preserving upstream acceleration."
        )
    else:
        recommendation = (
            "No static integrity blocker or large walk-state explosion was detected. "
            "This does not establish geometric correctness."
        )

    first = chain_states.get("2", 0)
    last = chain_states.get(str(max_chain_length), 0)
    fanout_ratio = (last / first) if first else None

    return {
        "schema_version": SCHEMA_VERSION,
        "rel_csv": str(Path(rel_csv)),
        "patch_dir": str(Path(patch_dir)) if patch_dir is not None else None,
        "relationship_rows": len(edges),
        "augmented_relationship_rows": len(edges) * 2,
        "relationship_ids": len(relationship_ids),
        "patch_files": len(patch_ids) if patch_dir is not None else None,
        "geometry_check": geometry_check,
        "integrity": integrity,
        "missing_geometry_count": len(missing_geometry),
        "missing_geometry_ids": missing_geometry,
        "isolated_patch_count": len(isolated_patches),
        "isolated_patch_ids": isolated_patches,
        "degree": {
            "mean": (sum(degrees) / len(degrees)) if degrees else 0.0,
            "p95": _percentile_nearest_rank(degrees, 0.95),
            "max": max(degrees, default=0),
        },
        "chain_walk_states": chain_states,
        "max_chain_length": max_chain_length,
        "peak_walk_states": peak,
        "length2_to_max_fanout_ratio": fanout_ratio,
        "runtime_risk": runtime_risk,
        "thresholds": {
            "warning_walk_states": WARNING_STATES,
            "high_walk_states": HIGH_STATES,
        },
        "recommendation": recommendation,
        "claim_boundary": (
            "Walk states are a topology-only tractability signal, not a runtime "
            "prediction or a correctness metric. The optimized bad-patch finder can "
            "prune dead prefixes after bad/repeated patches are known."
        ),
        "upstream_evidence": {
            "acceleration_pr": UPSTREAM_PR,
            "stale_growth_issue": UPSTREAM_ISSUE,
            "article": ARTICLE,
        },
    }


def _exit_for(report: dict[str, object], fail_on_runtime: str) -> int:
    if report["integrity"] == "blocked":
        return 2
    risk = str(report["runtime_risk"])
    if fail_on_runtime == "high" and risk == "high":
        return 1
    if fail_on_runtime == "warning" and risk in {"warning", "high"}:
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Preflight a scrollreading growth tree for stale rel.csv patch ids and "
            "bad-patch chain-enumeration blow-up."
        )
    )
    parser.add_argument("rel_csv", help="path to the growth tree's rel.csv")
    parser.add_argument(
        "--patch-dir",
        help="path to the matching patches/ directory; enables fail-closed geometry-id checks",
    )
    parser.add_argument(
        "--max-chain-length",
        type=int,
        default=5,
        choices=range(2, 9),
        metavar="N",
        help="largest chain length to count (default: 5, matching bad-patch mode c)",
    )
    parser.add_argument("--out", help="write stable JSON report to this path")
    parser.add_argument(
        "--fail-on-runtime",
        choices=("none", "warning", "high"),
        default="none",
        help="optional nonzero exit for tractability risk; missing geometry always exits 2",
    )
    args = parser.parse_args()

    try:
        report = analyze_growth(
            args.rel_csv,
            patch_dir=args.patch_dir,
            max_chain_length=args.max_chain_length,
        )
    except (OSError, ValueError) as exc:
        print(f"scroliq-growth-preflight: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)

    raise SystemExit(_exit_for(report, args.fail_on_runtime))


if __name__ == "__main__":
    main()
