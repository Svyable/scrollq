"""Deterministic work queue for improving Grand Prize legibility evidence.

Consumes a scroliq-legibility report. It does not change the prize rule or
claim that the Challenge counts a line at a 70% per-line threshold. The
per-line calculation is an optimization proxy: with the preserved-character
denominator fixed, it tells an ink/rendering loop how many currently
illegible characters would need to become letter-by-letter legible to cross
that same threshold.

The official gate remains per counted column in scroliq-legibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
TOOL = "scroliq-legibility-plan"
SOURCE_TOOL = "scroliq-legibility"


def _required_legible(preserved: int, threshold: float) -> int:
    """Smallest integer number of legible characters meeting the threshold."""
    if preserved <= 0:
        return 0
    return int(math.ceil((threshold * preserved) - 1e-12))


def _count(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def build_plan(
    report: dict[str, Any],
    *,
    report_sha256: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic rescue/fragility queue from a legibility report."""
    if report.get("tool") != SOURCE_TOOL:
        raise ValueError(f"report must be produced by {SOURCE_TOOL}")

    threshold = report.get("threshold")
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(float(threshold))
        or not 0 < float(threshold) <= 1
    ):
        raise ValueError("report threshold must be a finite number in (0, 1]")
    threshold = float(threshold)

    columns = report.get("columns")
    if not isinstance(columns, list):
        raise ValueError("report columns must be a list")

    column_queue: list[dict[str, Any]] = []
    line_queue: list[dict[str, Any]] = []
    fragile_lines: list[dict[str, Any]] = []
    secure_lines: list[dict[str, Any]] = []
    excluded_columns: list[int] = []
    counted_columns = 0
    total_lines = 0

    for ci, column in enumerate(columns):
        if not isinstance(column, dict):
            raise ValueError(f"columns[{ci}] must be an object")
        column_no = column.get("column")
        if isinstance(column_no, bool) or not isinstance(column_no, int) or column_no <= 0:
            raise ValueError(f"columns[{ci}].column must be a positive integer")

        if column.get("counted") is not True:
            excluded_columns.append(column_no)
            continue
        counted_columns += 1

        preserved = _count(
            column.get("preserved_characters"),
            f"columns[{ci}].preserved_characters",
        )
        legible = _count(
            column.get("legible_characters"),
            f"columns[{ci}].legible_characters",
        )
        if legible > preserved:
            raise ValueError(f"columns[{ci}] legible characters exceed preserved")

        required = _required_legible(preserved, threshold)
        needed = max(0, required - legible)
        margin = legible - required
        column_entry = {
            "column": column_no,
            "preserved_characters": preserved,
            "legible_characters": legible,
            "required_legible_characters": required,
            "characters_needed": needed,
            "qualification_margin_characters": margin,
            "recorded_legibility_rate": (
                legible / preserved if preserved else None
            ),
        }
        if needed:
            column_queue.append(column_entry)

        lines = column.get("lines")
        if not isinstance(lines, list):
            raise ValueError(f"columns[{ci}].lines must be a list")
        for li, line in enumerate(lines):
            if not isinstance(line, dict):
                raise ValueError(f"columns[{ci}].lines[{li}] must be an object")
            line_no = line.get("line")
            if isinstance(line_no, bool) or not isinstance(line_no, int) or line_no <= 0:
                raise ValueError(
                    f"columns[{ci}].lines[{li}].line must be a positive integer"
                )
            lp = _count(
                line.get("preserved_characters"),
                f"columns[{ci}].lines[{li}].preserved_characters",
            )
            ll = _count(
                line.get("legible_characters"),
                f"columns[{ci}].lines[{li}].legible_characters",
            )
            if ll > lp:
                raise ValueError(
                    f"columns[{ci}].lines[{li}] legible characters exceed preserved"
                )

            total_lines += 1
            line_required = _required_legible(lp, threshold)
            line_needed = max(0, line_required - ll)
            line_margin = ll - line_required
            entry = {
                "column": column_no,
                "line": line_no,
                "preserved_characters": lp,
                "legible_characters": ll,
                "required_legible_characters": line_required,
                "characters_needed": line_needed,
                "qualification_margin_characters": line_margin,
                "recorded_legibility_rate": ll / lp if lp else None,
            }

            if lp == 0:
                continue
            if line_needed:
                line_queue.append(entry)
            elif line_margin <= 1:
                fragile_lines.append(entry)
            else:
                secure_lines.append(entry)

    column_queue.sort(
        key=lambda row: (
            row["characters_needed"],
            -row["preserved_characters"],
            row["column"],
        )
    )
    line_queue.sort(
        key=lambda row: (
            row["characters_needed"],
            -row["preserved_characters"],
            row["column"],
            row["line"],
        )
    )
    fragile_lines.sort(
        key=lambda row: (
            row["qualification_margin_characters"],
            -row["preserved_characters"],
            row["column"],
            row["line"],
        )
    )
    secure_lines.sort(key=lambda row: (row["column"], row["line"]))

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "source_tool": SOURCE_TOOL,
        "legibility_report_sha256": report_sha256,
        "scroll_id": report.get("scroll_id"),
        "threshold": threshold,
        "summary": {
            "counted_columns": counted_columns,
            "excluded_columns": len(excluded_columns),
            "columns_below_threshold": len(column_queue),
            "lines_with_preserved_characters": (
                len(line_queue) + len(fragile_lines) + len(secure_lines)
            ),
            "lines_below_planning_threshold": len(line_queue),
            "lines_at_or_above_planning_threshold": (
                len(fragile_lines) + len(secure_lines)
            ),
            "one_character_column_rescues": sum(
                row["characters_needed"] == 1 for row in column_queue
            ),
            "one_character_line_rescues": sum(
                row["characters_needed"] == 1 for row in line_queue
            ),
            "line_records_seen": total_lines,
        },
        "excluded_column_numbers": sorted(excluded_columns),
        "column_rescue_queue": column_queue,
        "line_rescue_queue": line_queue,
        "fragile_lines": fragile_lines,
        "secure_lines": secure_lines,
        "scope_note": (
            "The official Grand Prize legibility threshold is enforced per "
            "counted column by scroliq-legibility. Applying the same threshold "
            "to individual lines here is only a deterministic optimization "
            "proxy for deciding where another render/model iteration may buy "
            "the most letter-by-letter evidence; it is not a claim about how "
            "the Challenge will count a legible line."
        ),
    }


def _load_report(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot parse report: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("report must be a JSON object")
    return raw, value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", required=True, type=Path,
                    help="JSON report produced by scroliq-legibility")
    ap.add_argument("--out", required=True, type=Path,
                    help="write deterministic rescue plan JSON here")
    args = ap.parse_args(argv)

    try:
        raw, report = _load_report(args.report)
        plan = build_plan(
            report,
            report_sha256=hashlib.sha256(raw).hexdigest(),
        )
    except (OSError, ValueError) as exc:
        print(f"{TOOL}: {exc}", file=sys.stderr)
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = plan["summary"]
    print(
        f"{TOOL}: {summary['lines_below_planning_threshold']} line rescue(s), "
        f"{summary['one_character_line_rescues']} one-character win(s), "
        f"{summary['columns_below_threshold']} column rescue(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
