"""Fail-closed audit of letter-by-letter Grand Prize legibility evidence.

This tool does not infer text and does not decide papyrological truth. It checks
an explicit reviewer ledger against the exact submitted mesh/render hashes and
applies the published 70% preserved-character threshold mechanically.

A character only counts as recorded legible when the ledger gives a single
visible character reading, a pixel bounding box, and explicitly says it was
not interpolated. Missing or uncertain preserved characters stay in the
denominator as illegible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import unicodedata
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
TOOL = "scroliq-legibility"
LEGIBILITY_THRESHOLD = 0.70
VALID_STATUSES = {"legible", "illegible", "lost"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _error(
    errors: list[dict[str, str]],
    code: str,
    path: str,
    message: str,
) -> None:
    errors.append({"code": code, "path": path, "message": message})


def _index_by_id(
    value: Any,
    kind: str,
    errors: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(value, list):
        _error(errors, "LEGIBILITY_MANIFEST", kind, f"{kind} must be a list")
        return out
    for i, row in enumerate(value):
        path = f"{kind}[{i}]"
        if not isinstance(row, dict):
            _error(errors, "LEGIBILITY_MANIFEST", path, "record must be an object")
            continue
        ident = row.get("id")
        if not isinstance(ident, str) or not ident:
            _error(errors, "LEGIBILITY_MANIFEST", f"{path}.id", "id is required")
            continue
        if ident in out:
            _error(
                errors,
                "LEGIBILITY_MANIFEST",
                f"{path}.id",
                f"duplicate id {ident!r}",
            )
            continue
        out[ident] = row
    return out


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _bbox(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    if any(
        isinstance(v, bool)
        or not isinstance(v, (int, float))
        or not math.isfinite(float(v))
        for v in value
    ):
        return False
    x0, y0, x1, y1 = map(float, value)
    return 0 <= x0 < x1 and 0 <= y0 < y1


def _single_visible_character(value: Any) -> bool:
    if not isinstance(value, str) or not value or value.isspace():
        return False
    base = [ch for ch in value if not unicodedata.combining(ch)]
    return len(base) == 1 and not any(ch.isspace() for ch in value)


def _manifest_column_map(
    renders: dict[str, dict[str, Any]],
    meshes: dict[str, dict[str, Any]],
    errors: list[dict[str, str]],
) -> dict[int, tuple[str, dict[str, Any], str, dict[str, Any]]]:
    out: dict[int, tuple[str, dict[str, Any], str, dict[str, Any]]] = {}
    for render_id, render in renders.items():
        column = render.get("column")
        path = f"renders[{render_id}]"
        if not _positive_int(column):
            _error(
                errors,
                "LEGIBILITY_MANIFEST",
                f"{path}.column",
                "positive integer column is required",
            )
            continue
        mesh_id = render.get("mesh_id")
        mesh = meshes.get(mesh_id) if isinstance(mesh_id, str) else None
        if mesh is None:
            _error(
                errors,
                "LEGIBILITY_MANIFEST",
                f"{path}.mesh_id",
                f"unknown mesh {mesh_id!r}",
            )
            continue
        if mesh.get("column") != column:
            _error(
                errors,
                "LEGIBILITY_MANIFEST",
                f"{path}.column",
                "render and mesh column numbers differ",
            )
        if column in out:
            _error(
                errors,
                "LEGIBILITY_MANIFEST",
                f"{path}.column",
                f"duplicate render column {column}",
            )
            continue
        out[int(column)] = (render_id, render, str(mesh_id), mesh)
    return out


def _audit_character(
    char: Any,
    path: str,
    errors: list[dict[str, str]],
) -> tuple[str | None, bool]:
    if not isinstance(char, dict):
        _error(errors, "LEGIBILITY_CHARACTER", path, "character must be an object")
        return None, False

    status = char.get("status")
    if status not in VALID_STATUSES:
        _error(
            errors,
            "LEGIBILITY_CHARACTER_STATUS",
            f"{path}.status",
            "status must be legible, illegible, or lost",
        )
        return None, False

    ident = char.get("id")
    if not isinstance(ident, str) or not ident.strip():
        _error(
            errors,
            "LEGIBILITY_CHARACTER_ID",
            f"{path}.id",
            "stable non-empty character id is required",
        )

    if status in {"legible", "illegible"} and not _bbox(char.get("bbox_xyxy")):
        _error(
            errors,
            "LEGIBILITY_CHARACTER_BBOX",
            f"{path}.bbox_xyxy",
            "preserved characters require finite pixel [x0,y0,x1,y1] bounds",
        )

    reading = char.get("reading")
    if status == "legible":
        if char.get("interpolated") is not False:
            _error(
                errors,
                "LEGIBILITY_INTERPOLATED",
                f"{path}.interpolated",
                "a counted legible character must explicitly be non-interpolated",
            )
        if not _single_visible_character(reading):
            _error(
                errors,
                "LEGIBILITY_NOT_LETTER_BY_LETTER",
                f"{path}.reading",
                "legible reading must identify exactly one visible character",
            )
    elif reading not in (None, ""):
        _error(
            errors,
            "LEGIBILITY_UNCOUNTED_READING",
            f"{path}.reading",
            "illegible/lost characters may not carry a counted reading",
        )

    if status == "lost":
        loss_evidence = char.get("loss_evidence")
        if not isinstance(loss_evidence, str) or not loss_evidence.strip():
            _error(
                errors,
                "LEGIBILITY_LOSS_EVIDENCE",
                f"{path}.loss_evidence",
                "lost characters require a short evidence note",
            )

    return str(status), isinstance(ident, str) and bool(ident.strip())


def audit_legibility(
    manifest: dict[str, Any],
    ledger: dict[str, Any],
    *,
    manifest_sha256: str | None = None,
    ledger_sha256: str | None = None,
) -> dict[str, Any]:
    """Audit one explicit legibility ledger against one provenance manifest."""
    errors: list[dict[str, str]] = []

    if ledger.get("schema_version") != SCHEMA_VERSION:
        _error(
            errors,
            "LEGIBILITY_SCHEMA",
            "schema_version",
            f"ledger schema_version must be {SCHEMA_VERSION}",
        )

    submission = manifest.get("submission")
    if not isinstance(submission, dict):
        submission = {}
        _error(
            errors,
            "LEGIBILITY_MANIFEST",
            "submission",
            "submission block is required",
        )
    scroll_id = submission.get("scroll_id")
    if ledger.get("scroll_id") != scroll_id:
        _error(
            errors,
            "LEGIBILITY_SCROLL_BINDING",
            "scroll_id",
            f"ledger scroll_id must equal manifest scroll_id {scroll_id!r}",
        )

    meshes = _index_by_id(manifest.get("meshes"), "meshes", errors)
    renders = _index_by_id(manifest.get("renders"), "renders", errors)
    expected = _manifest_column_map(renders, meshes, errors)

    rows = ledger.get("columns")
    if not isinstance(rows, list):
        _error(
            errors,
            "LEGIBILITY_COLUMNS",
            "columns",
            "columns must be a list",
        )
        rows = []

    seen_columns: set[int] = set()
    reports: list[dict[str, Any]] = []
    counted_columns = 0
    excluded_columns = 0
    total_preserved = 0
    total_legible = 0
    total_lines_above = 0
    total_lines_with_identified = 0
    total_fully_identified_lines = 0

    for i, row in enumerate(rows):
        path = f"columns[{i}]"
        if not isinstance(row, dict):
            _error(errors, "LEGIBILITY_COLUMN", path, "column must be an object")
            continue

        column = row.get("column")
        if not _positive_int(column):
            _error(
                errors,
                "LEGIBILITY_COLUMN",
                f"{path}.column",
                "positive integer column is required",
            )
            continue
        column = int(column)
        if column in seen_columns:
            _error(
                errors,
                "LEGIBILITY_COLUMN",
                f"{path}.column",
                f"duplicate column {column}",
            )
            continue
        seen_columns.add(column)

        binding = expected.get(column)
        if binding is None:
            _error(
                errors,
                "LEGIBILITY_COLUMN_BINDING",
                path,
                f"column {column} is not a submitted render column",
            )
            continue
        render_id, render, mesh_id, mesh = binding

        if row.get("render_id") != render_id:
            _error(
                errors,
                "LEGIBILITY_RENDER_BINDING",
                f"{path}.render_id",
                f"must equal {render_id!r}",
            )
        if row.get("mesh_id") != mesh_id:
            _error(
                errors,
                "LEGIBILITY_MESH_BINDING",
                f"{path}.mesh_id",
                f"must equal {mesh_id!r}",
            )
        if row.get("render_sha256") != render.get("sha256"):
            _error(
                errors,
                "LEGIBILITY_RENDER_BINDING",
                f"{path}.render_sha256",
                "ledger must bind the exact submitted render SHA-256",
            )
        if row.get("mesh_sha256") != mesh.get("sha256"):
            _error(
                errors,
                "LEGIBILITY_MESH_BINDING",
                f"{path}.mesh_sha256",
                "ledger must bind the exact submitted mesh SHA-256",
            )

        counted = row.get("counted")
        if not isinstance(counted, bool):
            _error(
                errors,
                "LEGIBILITY_COUNTED",
                f"{path}.counted",
                "counted must be explicitly true or false",
            )
            counted = False

        if counted:
            counted_columns += 1
        else:
            excluded_columns += 1
            exclusion = row.get("exclusion")
            if (
                not isinstance(exclusion, dict)
                or exclusion.get("challenge_acknowledged") is not True
                or not isinstance(exclusion.get("reason"), str)
                or not exclusion.get("reason", "").strip()
                or not isinstance(exclusion.get("reference"), str)
                or not exclusion.get("reference", "").strip()
            ):
                _error(
                    errors,
                    "LEGIBILITY_EXCLUSION_ACK",
                    f"{path}.exclusion",
                    "an uncounted column requires a documented Challenge-acknowledged reason and reference",
                )

        lines = row.get("lines")
        if not isinstance(lines, list):
            _error(
                errors,
                "LEGIBILITY_LINES",
                f"{path}.lines",
                "lines must be a list",
            )
            lines = []

        seen_lines: set[int] = set()
        seen_char_ids: set[str] = set()
        preserved = 0
        legible = 0
        lost = 0
        lines_above = 0
        lines_with_identified = 0
        fully_identified_lines = 0
        line_reports: list[dict[str, Any]] = []

        for j, line in enumerate(lines):
            lpath = f"{path}.lines[{j}]"
            if not isinstance(line, dict):
                _error(errors, "LEGIBILITY_LINE", lpath, "line must be an object")
                continue
            line_no = line.get("line")
            if not _positive_int(line_no):
                _error(
                    errors,
                    "LEGIBILITY_LINE",
                    f"{lpath}.line",
                    "positive integer line number is required",
                )
                continue
            line_no = int(line_no)
            if line_no in seen_lines:
                _error(
                    errors,
                    "LEGIBILITY_LINE",
                    f"{lpath}.line",
                    f"duplicate line {line_no}",
                )
                continue
            seen_lines.add(line_no)

            chars = line.get("characters")
            if not isinstance(chars, list):
                _error(
                    errors,
                    "LEGIBILITY_CHARACTERS",
                    f"{lpath}.characters",
                    "characters must be a list",
                )
                chars = []

            lp = ll = lx = 0
            for k, char in enumerate(chars):
                cpath = f"{lpath}.characters[{k}]"
                status, has_id = _audit_character(char, cpath, errors)
                if has_id and isinstance(char, dict):
                    ident = str(char["id"])
                    if ident in seen_char_ids:
                        _error(
                            errors,
                            "LEGIBILITY_CHARACTER_ID",
                            f"{cpath}.id",
                            f"duplicate character id {ident!r} in column",
                        )
                    seen_char_ids.add(ident)
                if status == "legible":
                    lp += 1
                    ll += 1
                elif status == "illegible":
                    lp += 1
                elif status == "lost":
                    lx += 1

            line_rate = (ll / lp) if lp else None
            if ll:
                lines_with_identified += 1
            if lp and ll == lp:
                fully_identified_lines += 1
            if line_rate is not None and line_rate >= LEGIBILITY_THRESHOLD:
                lines_above += 1

            preserved += lp
            legible += ll
            lost += lx
            line_reports.append(
                {
                    "line": line_no,
                    "preserved_characters": lp,
                    "legible_characters": ll,
                    "lost_characters": lx,
                    "recorded_legibility_rate": line_rate,
                }
            )

        rate = (legible / preserved) if preserved else None
        threshold_pass = (
            bool(counted)
            and rate is not None
            and rate >= LEGIBILITY_THRESHOLD
        )
        if counted and preserved == 0:
            _error(
                errors,
                "LEGIBILITY_NO_PRESERVED_CHARACTERS",
                path,
                "a counted column must record at least one preserved character",
            )
        elif counted and rate is not None and rate < LEGIBILITY_THRESHOLD:
            _error(
                errors,
                "LEGIBILITY_BELOW_70_PERCENT",
                path,
                f"recorded legibility is {rate:.3%}; required threshold is 70%",
            )

        total_preserved += preserved
        total_legible += legible
        total_lines_above += lines_above
        total_lines_with_identified += lines_with_identified
        total_fully_identified_lines += fully_identified_lines

        reports.append(
            {
                "column": column,
                "render_id": render_id,
                "mesh_id": mesh_id,
                "counted": counted,
                "preserved_characters": preserved,
                "legible_characters": legible,
                "lost_characters": lost,
                "recorded_legibility_rate": rate,
                "passes_70_percent": threshold_pass,
                "lines_with_identified_characters": lines_with_identified,
                "lines_at_or_above_70_percent": lines_above,
                "fully_identified_preserved_lines": fully_identified_lines,
                "lines": line_reports,
            }
        )

    missing = sorted(set(expected) - seen_columns)
    extra = sorted(seen_columns - set(expected))
    if missing or extra:
        _error(
            errors,
            "LEGIBILITY_COLUMN_COVERAGE",
            "columns",
            f"ledger must cover every submitted render column; missing={missing}, extra={extra}",
        )

    reports.sort(key=lambda row: int(row["column"]))
    weighted_rate = total_legible / total_preserved if total_preserved else None
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "threshold": LEGIBILITY_THRESHOLD,
        "manifest_sha256": manifest_sha256,
        "ledger_sha256": ledger_sha256,
        "scroll_id": scroll_id,
        "passes_recorded_thresholds": not errors,
        "error_count": len(errors),
        "errors": errors,
        "summary": {
            "submitted_columns": len(expected),
            "counted_columns": counted_columns,
            "excluded_columns": excluded_columns,
            "preserved_characters": total_preserved,
            "legible_characters": total_legible,
            "weighted_recorded_legibility_rate": weighted_rate,
            "lines_with_identified_characters": total_lines_with_identified,
            "lines_at_or_above_70_percent": total_lines_above,
            "fully_identified_preserved_lines": total_fully_identified_lines,
        },
        "columns": reports,
        "scope_note": (
            "This report audits the supplied letter-by-letter ledger and exact "
            "artifact bindings. It is not an independent papyrological judgment "
            "and does not certify the Grand Prize result."
        ),
    }


def _load_json(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot parse {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return raw, value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", required=True, help="Grand Prize provenance JSON")
    ap.add_argument("--ledger", required=True, help="letter-by-letter legibility ledger JSON")
    ap.add_argument("--out", help="optional machine-readable audit report JSON")
    ap.add_argument("--format", choices=("text", "json", "github"), default="text")
    args = ap.parse_args(argv)

    try:
        manifest_raw, manifest = _load_json(Path(args.manifest), "manifest")
        ledger_raw, ledger = _load_json(Path(args.ledger), "ledger")
        report = audit_legibility(
            manifest,
            ledger,
            manifest_sha256=_sha256(manifest_raw),
            ledger_sha256=_sha256(ledger_raw),
        )
    except (OSError, ValueError) as exc:
        print(f"ScrolIQ legibility ledger: FAIL: {exc}", file=sys.stderr)
        return 2

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
    elif args.format == "github":
        for item in report["errors"]:
            print(
                f"::error title={item['code']}::"
                f"{item['path']}: {item['message']}"
            )
        if report["passes_recorded_thresholds"]:
            print("::notice title=LEGIBILITY_LEDGER_PASS::recorded thresholds pass")
    else:
        verdict = "PASS" if report["passes_recorded_thresholds"] else "FAIL"
        summary = report["summary"]
        print(f"ScrolIQ recorded legibility ledger: {verdict}")
        print(
            "columns: "
            f"{summary['counted_columns']} counted, "
            f"{summary['excluded_columns']} acknowledged exclusions, "
            f"{summary['submitted_columns']} submitted"
        )
        print(
            "characters: "
            f"{summary['legible_characters']}/"
            f"{summary['preserved_characters']} recorded legible/preserved"
        )
        print(
            "lines: "
            f"{summary['lines_at_or_above_70_percent']} at/above 70%, "
            f"{summary['fully_identified_preserved_lines']} fully identified"
        )
        for item in report["errors"]:
            print(f"- {item['code']} {item['path']}: {item['message']}")

    return 0 if report["passes_recorded_thresholds"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
