"""Draw the O1 blinded review sample from the 2026-10-01 corpus mesh audit.

Protocol: docs/mesh-review-protocol.md (frozen before any segment is reviewed).

Segments, not meshes, are the unit: a segment is
  flagged  multi-defect (3+ finding kinds) on every audited registration
  clean    no findings on any audited registration
  mixed    anything else (not sampled; the claim under test is the flag)
Flagged segments whose name contains ``z_dbg`` are debug/generated segments
already known to be broken; they are kept out of the precision stratum and
used only as reviewer-calibration controls.

Strata drawn (seeded, deterministic):
  F  flagged, non-debug    30, allocated across scrolls by largest remainder
  D  flagged, debug         4, always including the hand-confirmed PHerc1447
                              segment, plus 3 drawn from the rest
  C  clean                 20, drawn uniformly

One registration per segment is shown to the reviewer: a registration bound to
a volcomp CT root if there is one, then the lowest volume id. The reviewer
sheet is shuffled across strata and carries no tier or finding information.

    python bin/mesh_review_sample.py OUT_DIR [--seed 20261001]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "artifacts" / "2026-10-01-corpus-mesh-audit"
BUCKET = "https://vesuvius-challenge-open-data.s3.us-east-1.amazonaws.com"
KNOWN_BROKEN = "20251105093211-z_dbg_gen_00320"
SIZES = {"F": 30, "D": 4, "C": 20}
SEED = 20261001


def _segments(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    by_seg: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        by_seg[(row["scroll"], row["segment"])].append(row)
    return dict(sorted(by_seg.items()))


def classify(regs: list[dict]) -> str:
    tiers = {r["tier"] for r in regs}
    if tiers == {"multi-defect"}:
        return "flagged"
    if tiers == {"clean"}:
        return "clean"
    return "mixed"


def allocate(counts: dict[str, int], total: int) -> dict[str, int]:
    """Largest-remainder proportional allocation; every scroll gets >= 1."""
    population = sum(counts.values())
    if total >= population:
        return dict(counts)
    keys = sorted(counts)
    alloc = {k: 1 for k in keys}
    remaining = total - len(keys)
    if remaining < 0:
        raise ValueError("sample smaller than the number of scrolls")
    spare = {k: counts[k] - 1 for k in keys}
    spare_total = sum(spare.values())
    quotas = {k: remaining * spare[k] / spare_total for k in keys}
    for k in keys:
        alloc[k] += int(quotas[k])
    left = total - sum(alloc.values())
    for k in sorted(keys, key=lambda k: (-(quotas[k] - int(quotas[k])), k))[:left]:
        alloc[k] += 1
    return alloc


def pick_registration(regs: list[dict]) -> dict:
    return sorted(regs, key=lambda r: (r["volume_root"] is None, r["volume_id"] or "", r["report"]))[0]


def mesh_dir(reg: dict) -> str:
    stem = Path(reg["report"]).name[: -len(".json")]
    scroll, segment, mesh = stem.split(".", 2)
    return f"{scroll}/segments/{segment}/mesh/{mesh}.tifxyz/"


def draw(rows: list[dict], *, seed: int = SEED, sizes: dict[str, int] = SIZES) -> list[dict]:
    rng = random.Random(seed)
    segs = _segments(rows)
    groups: dict[str, list[tuple[str, str]]] = {"F": [], "D": [], "C": []}
    for key, regs in segs.items():
        kind = classify(regs)
        if kind == "flagged":
            groups["D" if "z_dbg" in key[1] else "F"].append(key)
        elif kind == "clean":
            groups["C"].append(key)

    picked: list[tuple[str, tuple[str, str]]] = []
    by_scroll: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for key in groups["F"]:
        by_scroll[key[0]].append(key)
    alloc = allocate({k: len(v) for k, v in by_scroll.items()}, sizes["F"])
    for scroll in sorted(alloc):
        picked += [("F", k) for k in rng.sample(sorted(by_scroll[scroll]), alloc[scroll])]

    control = [k for k in groups["D"] if k[1] == KNOWN_BROKEN]
    rest = sorted(k for k in groups["D"] if k[1] != KNOWN_BROKEN)
    picked += [("D", k) for k in control + rng.sample(rest, sizes["D"] - len(control))]
    picked += [("C", k) for k in rng.sample(sorted(groups["C"]), min(sizes["C"], len(groups["C"])))]

    rng.shuffle(picked)
    out = []
    for index, (stratum, key) in enumerate(picked, start=1):
        regs = segs[key]
        reg = pick_registration(regs)
        out.append(
            {
                "review_id": f"R{index:02d}",
                "stratum": stratum,
                "scroll": key[0],
                "segment": key[1],
                "registrations": len(regs),
                "mesh_dir": mesh_dir(reg),
                "mesh_url": f"{BUCKET}/{mesh_dir(reg)}",
                "volume_root": reg["volume_root"],
                "volume_id": reg["volume_id"],
                "findings": reg["findings"],
                "tier": reg["tier"],
                "audit_report": f"artifacts/2026-10-01-corpus-mesh-audit/{reg['report']}",
            }
        )
    return out


SHEET_FIELDS = ["review_id", "scroll", "segment", "mesh_url", "volume_root", "label", "defect_type", "notes"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(out_dir: Path, sample: list[dict], *, seed: int) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = out_dir / "review-sheet.csv"
    with sheet.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=SHEET_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in sample:
            writer.writerow({k: row.get(k) or "" for k in SHEET_FIELDS if k not in {"label", "defect_type", "notes"}})
    key = out_dir / "key.json"
    key.write_text(json.dumps(sample, indent=2) + "\n", encoding="utf-8")
    summary = json.loads((AUDIT / "summary.json").read_bytes())
    manifest = {
        "diagnostic": "mesh-review-sample",
        "protocol": "docs/mesh-review-protocol.md",
        "seed": seed,
        "sizes": {s: sum(1 for r in sample if r["stratum"] == s) for s in ("F", "D", "C")},
        "source": {
            "summary": "artifacts/2026-10-01-corpus-mesh-audit/summary.json",
            "summary_sha256": _sha256(AUDIT / "summary.json"),
            "as_of": summary.get("as_of"),
        },
        "files_sha256": {"review-sheet.csv": _sha256(sheet), "key.json": _sha256(key)},
        "blinding": (
            "procedural: the sheet carries no stratum, tier or finding; the key is "
            "regenerable from public inputs, so reviewers are asked not to open "
            "key.json, the audit reports, or this script's output before labelling. "
            "Debug controls are recognisable by name (z_dbg)."
        ),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out_dir")
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()
    rows = json.loads((AUDIT / "summary.json").read_bytes())["rows"]
    manifest = write(Path(args.out_dir), draw(rows, seed=args.seed), seed=args.seed)
    print(json.dumps(manifest["sizes"]), manifest["files_sha256"])


if __name__ == "__main__":
    main()
