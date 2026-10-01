#!/usr/bin/env python3
"""Compare stable public Fiber IQ campaign evidence against the frozen result."""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOP_FIELDS = (
    "schema_version",
    "campaign",
    "campaign_date",
    "input_count",
    "download_errors",
    "hash_mismatches",
    "total_input_bytes",
    "status_counts",
    "finding_kind_totals",
)
ROW_FIELDS = (
    "file",
    "source_url",
    "sha256",
    "bytes",
    "status",
    "fiber_version",
    "line_points",
    "control_points",
    "segments",
    "native_trace_segments",
    "fallback_segments",
    "gaps",
    "sharp_turns",
    "control_line_offsets",
    "control_order_inversions",
    "finding_kinds",
)


def stable(report: dict) -> dict:
    return {
        "top": {key: report.get(key) for key in TOP_FIELDS},
        "rows": [
            {key: row.get(key) for key in ROW_FIELDS}
            for row in report.get("rows", [])
        ],
    }


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: verify.py FRESH.json FROZEN.json")
    fresh = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    frozen = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    if stable(fresh) != stable(frozen):
        print("public Fiber IQ stable evidence differs from frozen summary", file=sys.stderr)
        return 1
    print("public Fiber IQ stable evidence matches frozen summary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
