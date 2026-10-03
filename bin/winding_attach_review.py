"""Post-hoc, descriptive: context for each flagged attachment (O2 step 3).

Not part of the pre-registered decision. Re-solves the primary constraint
set from a committed result directory and lists, for every point in the
review queue, all of its attachments within the primary distance with their
residuals, so a reviewer can see whether the point disagrees with all its
patches (annotation cue) or only with one far or lone patch (patch cue).

    python bin/winding_attach_review.py artifacts/2026-10-03-paris4-winding-attachment DATASET
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import winding_attach as wa  # noqa: E402


def review_context(attachments: list[dict], points: dict, sense: int, cut: float) -> list[dict]:
    cons = wa.constraints(attachments, points, sense=sense, cut_degrees=cut)
    sol = wa.solve(cons)
    dist = {(a["point"], a["node"]): a["distance"] for a in attachments}
    by_point: dict[str, list[dict]] = {}
    for c, r in zip(cons, sol["residuals"]):
        by_point.setdefault(c["point"], []).append(
            {"patch_piece": c["node"], "distance": dist[(c["point"], c["node"])], "residual": r})
    out = []
    for key in sorted({c["point"] for c, r in zip(cons, sol["residuals"])
                       if abs(r) >= wa.INCONSISTENT_ABS_RESIDUAL}):
        rows = sorted(by_point[key], key=lambda x: x["distance"])
        flagged = [x for x in rows if abs(x["residual"]) >= wa.INCONSISTENT_ABS_RESIDUAL]
        agreeing = [x for x in rows if x["residual"] == 0]
        nearest_flagged = min(x["distance"] for x in flagged)
        if not agreeing:
            reading = "no attachment agrees: annotation or every patch here is off"
        elif all(x["distance"] < nearest_flagged for x in agreeing):
            reading = "closer patches agree: the flagged patch is likely a neighbouring winding"
        else:
            reading = "patches at similar distance disagree: patch-level conflict"
        out.append({"point": key, "attachments": len(rows), "agreeing": len(agreeing),
                    "flagged": len(flagged), "reading": reading, "rows": rows})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("result_dir")
    ap.add_argument("dataset")
    args = ap.parse_args()
    d = Path(args.result_dir)
    result = json.loads((d / "result.json").read_text())
    attachments = json.loads((d / "attachments.json").read_text())
    dataset = Path(args.dataset)
    for name, digest in result["inputs"]["sha256"].items():
        if hashlib.sha256((dataset / name).read_bytes()).hexdigest() != digest:
            sys.exit(f"{name} changed since the frozen run; refusing to mix inputs")
    points = wa.load_annotation_points(dataset)
    p = result["primary"]
    print(json.dumps(review_context(attachments, points, p["sense"], p["cut_degrees"]), indent=1))


if __name__ == "__main__":
    main()
