"""Score the O1 mesh review against the pre-registered rules.

Protocol: docs/mesh-review-protocol.md. Inputs are the labelled
review-sheet.csv and the key.json written by bin/mesh_review_sample.py.

Labels are ``defect``, ``not_defect`` or ``unclear``. Rules, frozen before review:

1. Calibration: at least 3 of the 4 debug controls (stratum D) must be
   labelled ``defect``. Otherwise the review is ``uncalibrated`` and no
   precision is published as a finding.
2. Precision of the flag = defect / (defect + not_defect) over stratum F,
   with a Wilson 95% interval. ``unclear`` is excluded from the point estimate
   and reported as bounds (all unclear counted as defect / as not_defect).
3. Defect rate of clean segments, the same way, over stratum C.
4. The flag may be described as enriched for real defects only if the Wilson
   lower bound for F exceeds the Wilson upper bound for C.

    python bin/mesh_review_score.py REVIEW_DIR [--out result.json]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

LABELS = ("defect", "not_defect", "unclear")
CALIBRATION_MIN = 3
Z = 1.959963984540054


def wilson(successes: int, n: int, z: float = Z) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _rate(labels: list[str]) -> dict:
    d = labels.count("defect")
    nd = labels.count("not_defect")
    u = labels.count("unclear")
    n = d + nd
    return {
        "defect": d,
        "not_defect": nd,
        "unclear": u,
        "rate": d / n if n else None,
        "wilson95": wilson(d, n),
        "bounds_with_unclear": (
            [d / (n + u), (d + u) / (n + u)] if n + u else None
        ),
    }


def score(sheet_rows: list[dict], key: list[dict]) -> dict:
    # Never silently overwrite duplicate IDs or score substituted surfaces.
    errors = []
    for name, rows in (("sheet", sheet_rows), ("key", key)):
        ids = [r.get("review_id") for r in rows]
        if any(not isinstance(rid, str) or not rid.strip() for rid in ids):
            errors.append(f"{name}: missing review_id")
        elif len(set(ids)) != len(ids):
            errors.append(f"{name}: duplicate review_id")
    if not key:
        errors.append("key: empty sample")
    if errors:
        return {"status": "invalid", "errors": errors}
    by_id = {row["review_id"]: row for row in sheet_rows}
    expected = {k["review_id"] for k in key}
    if set(by_id) - expected:
        errors.append("sheet: unexpected review_id")
    for k in key:
        if k.get("stratum") not in {"F", "D", "C"}:
            errors.append(f"{k['review_id']}: invalid stratum")
        row = by_id.get(k["review_id"])
        if row is not None:
            for field in ("scroll", "segment", "mesh_url", "volume_root"):
                # CSV serializes a missing optional CT root (JSON null) as "".
                if field in k and row.get(field) != (k[field] if k[field] is not None else ""):
                    errors.append(f"{k['review_id']}: changed {field}")
    if errors:
        return {"status": "invalid", "errors": errors}
    missing = [k["review_id"] for k in key if k["review_id"] not in by_id]
    bad = sorted(
        {
            str(by_id[k["review_id"]].get("label") or "").strip()
            for k in key
            if k["review_id"] in by_id
            and str(by_id[k["review_id"]].get("label") or "").strip() not in LABELS
        }
    )
    if missing or bad:
        return {
            "status": "incomplete",
            "missing_review_ids": missing,
            "invalid_labels": bad,
        }
    labels = {s: [] for s in ("F", "D", "C")}
    kinds: dict[str, list[str]] = {}
    for k in key:
        label = by_id[k["review_id"]]["label"].strip()
        labels[k["stratum"]].append(label)
        if k["stratum"] == "F":
            for kind in k["findings"]:
                kinds.setdefault(kind, []).append(label)
    calibration = labels["D"].count("defect")
    calibrated = calibration >= CALIBRATION_MIN
    flagged = _rate(labels["F"])
    clean = _rate(labels["C"])
    enriched = bool(
        calibrated
        and flagged["wilson95"]
        and clean["wilson95"]
        and flagged["wilson95"][0] > clean["wilson95"][1]
    )
    return {
        "status": "calibrated" if calibrated else "uncalibrated",
        "calibration": {"defect": calibration, "of": len(labels["D"]), "min": CALIBRATION_MIN},
        "flag_precision": flagged,
        "clean_defect_rate": clean,
        "flag_enriched_for_defects": enriched,
        "by_finding_kind_descriptive": {k: _rate(v) for k, v in sorted(kinds.items())},
        "rules": "docs/mesh-review-protocol.md",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("review_dir")
    ap.add_argument("--out")
    ap.add_argument("--sheet", help="returned labelled CSV; leaves the frozen sample untouched")
    ap.add_argument("--require-complete", action="store_true",
                    help="exit 1 for invalid, incomplete, or uncalibrated reviews")
    args = ap.parse_args()
    root = Path(args.review_dir)
    sheet = Path(args.sheet) if args.sheet else root / "review-sheet.csv"
    key_path = root / "key.json"
    with sheet.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    key_bytes = key_path.read_bytes()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    key_hash = hashlib.sha256(key_bytes).hexdigest()
    if key_hash != manifest["files_sha256"]["key.json"]:
        result = {"status": "invalid", "errors": ["key checksum mismatch"]}
    else:
        result = score(rows, json.loads(key_bytes))
    result["inputs_sha256"] = {"sheet": hashlib.sha256(sheet.read_bytes()).hexdigest(),
                              "key": key_hash}
    text = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return int(args.require_complete and result["status"] != "calibrated")


if __name__ == "__main__":
    raise SystemExit(main())
