"""Fiber trace continuity diagnostics.

Reads ordered fiber traces (CSV columns ``trace_id,x,y,z``, rows in trace
order) and flags two kinds of discontinuity per trace:

- *gap*: a step longer than ``gap_factor`` times the trace's median non-zero
  step;
- *sharp turn*: a direction change above ``turn_degrees`` between
  consecutive steps.

Traces with fewer than two points are reported as ``short_trace``. Any parse
error fails the audit; findings without errors give ``caution``. This flags
candidate trace breaks for review. It does not prove that a trace follows one
fiber or one sheet.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np


def audit_rows(rows, gap_factor: float = 4.0, turn_degrees: float = 60.0) -> dict:
    """Audit already-parsed CSV rows (dicts with trace_id, x, y, z)."""
    traces: dict[str, list[list[float]]] = {}
    errors = []
    for i, row in enumerate(rows, 2):  # row 1 is the CSV header
        try:
            p = [float(row[k]) for k in ("x", "y", "z")]
            if not np.all(np.isfinite(p)):
                raise ValueError("non-finite coordinate")
            traces.setdefault(str(row["trace_id"]), []).append(p)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append({"row": i, "error": str(exc)})

    findings = []
    total = 0.0
    gaps = turns = 0
    for tid, raw in traces.items():
        pts = np.asarray(raw, float)
        if len(pts) < 2:
            findings.append({"trace_id": tid, "kind": "short_trace",
                             "points": len(pts)})
            continue
        vec = np.diff(pts, axis=0)
        seg = np.linalg.norm(vec, axis=1)
        total += float(seg.sum())

        pos = seg[seg > 0]
        baseline = float(np.median(pos)) if pos.size else 0.0
        if baseline:
            for j in np.flatnonzero(seg > gap_factor * baseline):
                gaps += 1
                findings.append({"trace_id": tid, "kind": "gap",
                                 "segment": int(j),
                                 "ratio": float(seg[j] / baseline)})

        if len(vec) >= 2:
            a, b = vec[:-1], vec[1:]
            den = np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1)
            valid = den > 0
            angles = np.zeros(len(den))
            cos = np.sum(a[valid] * b[valid], axis=1) / den[valid]
            angles[valid] = np.degrees(np.arccos(np.clip(cos, -1, 1)))
            for j in np.flatnonzero(angles > turn_degrees):
                turns += 1
                findings.append({"trace_id": tid, "kind": "sharp_turn",
                                 "vertex": int(j + 1),
                                 "degrees": float(angles[j])})

    status = "fail" if errors else ("caution" if findings else "pass")
    return {
        "diagnostic": "fiber-trace-audit",
        "schema_version": 1,
        "status": status,
        "parameters": {"gap_factor": gap_factor, "turn_degrees": turn_degrees},
        "counts": {
            "rows": len(rows),
            "valid_traces": len(traces),
            "parse_errors": len(errors),
            "gaps": gaps,
            "sharp_turns": turns,
        },
        "total_trace_length": total,
        "findings": findings,
        "errors": errors,
        "interpretation": (
            "Flags discontinuities and abrupt direction changes in ordered "
            "fiber traces; it does not prove fiber or sheet identity."
        ),
    }


def audit_csv(path, **kwargs) -> dict:
    """Audit a CSV file and record its SHA-256 for provenance."""
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = audit_rows(rows, **kwargs)
    out["input"] = {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        description="Audit ordered CSV fiber traces (trace_id,x,y,z)."
    )
    ap.add_argument("csv")
    ap.add_argument("--gap-factor", type=float, default=4.0)
    ap.add_argument("--turn-degrees", type=float, default=60.0)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    result = audit_csv(a.csv, gap_factor=a.gap_factor,
                       turn_degrees=a.turn_degrees)
    text = json.dumps(result, indent=2)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    raise SystemExit(2 if result["status"] == "fail" else 0)


if __name__ == "__main__":
    main()
