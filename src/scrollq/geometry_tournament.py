"""Compare held-out geometry candidates without collapsing evidence into a weighted score.

Each candidate must be a complete ``scroliq-geometry-validate`` report produced
against the same frozen specification. The tournament computes a Pareto
frontier over coverage-aware held-out metrics and names a winner only when every
candidate is complete and exactly one candidate is non-dominated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

SCHEMA = "scroliq-geometry-tournament/1"
REPORT_TOOL = "scroliq-geometry-validate"


class GeometryTournamentError(ValueError):
    """Candidate evidence is malformed, incomparable, or insufficient."""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _hex64(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise GeometryTournamentError(f"{field} must be lowercase 64-hex sha256")
    return value


def _finite_number(value: Any, field: str, *, lower: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GeometryTournamentError(f"{field} must be numeric")
    out = float(value)
    if not math.isfinite(out) or (lower is not None and out < lower):
        raise GeometryTournamentError(f"{field} must be finite and >= {lower}")
    return out


def _count(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise GeometryTournamentError(f"{field} must be a non-negative integer")
    return value


def _validate_report(report: dict[str, Any], *, candidate_id: str) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise GeometryTournamentError(f"{candidate_id}: report must be a JSON object")
    if type(report.get("schema_version")) is not int or report.get("schema_version") != 1 or report.get("tool") != REPORT_TOOL:
        raise GeometryTournamentError(
            f"{candidate_id}: report must be schema_version 1 from {REPORT_TOOL}"
        )
    if report.get("coordinate_system") != "base_voxel_xyz":
        raise GeometryTournamentError(f"{candidate_id}: coordinate system mismatch")
    volume_root = report.get("volume_root")
    if not isinstance(volume_root, str) or not volume_root.strip():
        raise GeometryTournamentError(f"{candidate_id}: volume_root is required")
    spec_sha = _hex64(report.get("spec_sha256"), f"{candidate_id}: spec_sha256")
    prediction_sha = _hex64(
        report.get("prediction_sha256"), f"{candidate_id}: prediction_sha256"
    )
    checkpoint_sha = _hex64(
        report.get("checkpoint_sha256"), f"{candidate_id}: checkpoint_sha256"
    )
    tolerance = _finite_number(
        report.get("tolerance_voxels"), f"{candidate_id}: tolerance_voxels", lower=0.0
    )
    if tolerance <= 0:
        raise GeometryTournamentError(f"{candidate_id}: tolerance_voxels must be positive")

    expected = _count(report.get("expected"), f"{candidate_id}: expected")
    if expected == 0:
        raise GeometryTournamentError(f"{candidate_id}: expected must be positive")
    predicted = _count(report.get("predicted"), f"{candidate_id}: predicted")
    missing = _count(report.get("missing"), f"{candidate_id}: missing")
    failed = _count(report.get("failed"), f"{candidate_id}: failed")
    within = _count(report.get("within_tolerance"), f"{candidate_id}: within_tolerance")
    rate = _finite_number(
        report.get("within_tolerance_rate"),
        f"{candidate_id}: within_tolerance_rate",
        lower=0.0,
    )
    if rate > 1:
        raise GeometryTournamentError(f"{candidate_id}: within_tolerance_rate must be <= 1")

    targets = report.get("targets")
    if not isinstance(targets, list) or len(targets) != expected:
        raise GeometryTournamentError(f"{candidate_id}: targets must contain exactly expected rows")
    seen: set[str] = set()
    ok_errors: list[float] = []
    recomputed_missing = recomputed_failed = recomputed_within = 0
    target_signature: list[tuple[str, tuple[float, float, float]]] = []
    for row in targets:
        if not isinstance(row, dict):
            raise GeometryTournamentError(f"{candidate_id}: target row must be an object")
        target_id = row.get("id")
        if not isinstance(target_id, str) or not target_id or target_id in seen:
            raise GeometryTournamentError(
                f"{candidate_id}: target ids must be unique non-empty strings"
            )
        seen.add(target_id)
        xyz = row.get("reference_xyz")
        if (
            not isinstance(xyz, list)
            or len(xyz) != 3
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in xyz)
        ):
            raise GeometryTournamentError(f"{candidate_id}: reference_xyz must be three numbers")
        xyz_tuple = tuple(float(v) for v in xyz)
        if not all(math.isfinite(v) for v in xyz_tuple):
            raise GeometryTournamentError(f"{candidate_id}: reference_xyz must be finite")
        target_signature.append((target_id, xyz_tuple))

        status = row.get("status")
        within_row = row.get("within_tolerance")
        if type(within_row) is not bool:
            raise GeometryTournamentError(
                f"{candidate_id}: target within_tolerance must be boolean"
            )
        if status == "ok":
            predicted_xyz = row.get("xyz")
            if (
                not isinstance(predicted_xyz, list)
                or len(predicted_xyz) != 3
                or any(
                    isinstance(v, bool) or not isinstance(v, (int, float))
                    for v in predicted_xyz
                )
            ):
                raise GeometryTournamentError(
                    f"{candidate_id}: predicted xyz must be three numbers"
                )
            predicted_tuple = tuple(float(v) for v in predicted_xyz)
            if not all(math.isfinite(v) for v in predicted_tuple):
                raise GeometryTournamentError(
                    f"{candidate_id}: predicted xyz must be finite"
                )
            error = _finite_number(
                row.get("error_voxels"), f"{candidate_id}: target error_voxels", lower=0.0
            )
            coordinate_error = math.dist(xyz_tuple, predicted_tuple)
            if not math.isclose(error, coordinate_error, rel_tol=0, abs_tol=1e-12):
                raise GeometryTournamentError(
                    f"{candidate_id}: target error_voxels does not match coordinates"
                )
            ok_errors.append(error)
            should_be_within = error <= tolerance
            if within_row != should_be_within:
                raise GeometryTournamentError(
                    f"{candidate_id}: target tolerance flag does not match error"
                )
            recomputed_within += int(should_be_within)
        elif status == "failed":
            recomputed_failed += 1
            if row.get("xyz") is not None:
                raise GeometryTournamentError(
                    f"{candidate_id}: failed target cannot supply xyz"
                )
            if within_row:
                raise GeometryTournamentError(
                    f"{candidate_id}: failed target cannot be within tolerance"
                )
        elif status == "missing":
            recomputed_missing += 1
            if row.get("xyz") is not None:
                raise GeometryTournamentError(
                    f"{candidate_id}: missing target cannot supply xyz"
                )
            if within_row:
                raise GeometryTournamentError(
                    f"{candidate_id}: missing target cannot be within tolerance"
                )
        else:
            raise GeometryTournamentError(
                f"{candidate_id}: unsupported target status {status!r}"
            )

    if predicted != len(ok_errors) or missing != recomputed_missing or failed != recomputed_failed:
        raise GeometryTournamentError(
            f"{candidate_id}: summary counts do not reconcile with targets"
        )
    if predicted + missing + failed != expected:
        raise GeometryTournamentError(
            f"{candidate_id}: candidate denominator does not reconcile"
        )
    if within != recomputed_within:
        raise GeometryTournamentError(
            f"{candidate_id}: within_tolerance count does not reconcile"
        )
    if not math.isclose(rate, within / expected, rel_tol=0, abs_tol=1e-12):
        raise GeometryTournamentError(
            f"{candidate_id}: within_tolerance_rate does not reconcile"
        )

    expected_median = median(ok_errors) if ok_errors else None
    expected_max = max(ok_errors) if ok_errors else None
    report_median = report.get("predicted_only_median_error_voxels")
    report_max = report.get("predicted_only_max_error_voxels")
    for name, actual, expected_value in (
        ("predicted_only_median_error_voxels", report_median, expected_median),
        ("predicted_only_max_error_voxels", report_max, expected_max),
    ):
        if expected_value is None:
            if actual is not None:
                raise GeometryTournamentError(
                    f"{candidate_id}: {name} must be null with no predictions"
                )
        else:
            value = _finite_number(actual, f"{candidate_id}: {name}", lower=0.0)
            if not math.isclose(value, expected_value, rel_tol=0, abs_tol=1e-12):
                raise GeometryTournamentError(f"{candidate_id}: {name} does not reconcile")

    status = report.get("status")
    complete = predicted == expected and missing == 0 and failed == 0
    expected_status = "measured" if complete else "incomplete"
    if status != expected_status:
        raise GeometryTournamentError(f"{candidate_id}: report status does not reconcile")

    return {
        "id": candidate_id,
        "volume_root": volume_root,
        "spec_sha256": spec_sha,
        "prediction_sha256": prediction_sha,
        "checkpoint_sha256": checkpoint_sha,
        "tolerance_voxels": tolerance,
        "expected": expected,
        "predicted": predicted,
        "missing": missing,
        "failed": failed,
        "within_tolerance": within,
        "within_tolerance_rate": rate,
        "median_error_voxels": expected_median,
        "max_error_voxels": expected_max,
        "complete": complete,
        "target_signature": tuple(sorted(target_signature)),
    }


def _axis_value(candidate: dict[str, Any], axis: str) -> float:
    if axis == "within_tolerance_rate":
        return float(candidate[axis])
    if axis == "predicted":
        return float(candidate[axis])
    value = candidate[axis]
    return math.inf if value is None else float(value)


def _dominates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Return true when left is no worse on every axis and better on at least one."""
    maximize = ("within_tolerance_rate", "predicted")
    minimize = ("median_error_voxels", "max_error_voxels")
    no_worse = all(_axis_value(left, a) >= _axis_value(right, a) for a in maximize)
    no_worse &= all(_axis_value(left, a) <= _axis_value(right, a) for a in minimize)
    if not no_worse:
        return False
    better = any(_axis_value(left, a) > _axis_value(right, a) for a in maximize)
    better |= any(_axis_value(left, a) < _axis_value(right, a) for a in minimize)
    return better


def evaluate_tournament(
    candidates: list[tuple[str, dict[str, Any], str]]
) -> dict[str, Any]:
    """Evaluate (candidate_id, report, report_sha256) triples."""
    if len(candidates) < 2:
        raise GeometryTournamentError("at least two candidates are required")
    ids = [candidate_id for candidate_id, _, _ in candidates]
    if any(not isinstance(v, str) or not v.strip() for v in ids) or len(set(ids)) != len(ids):
        raise GeometryTournamentError("candidate ids must be unique non-empty strings")

    validated: list[dict[str, Any]] = []
    for candidate_id, report, report_file_sha in candidates:
        item = _validate_report(report, candidate_id=candidate_id)
        item["report_sha256"] = _hex64(
            report_file_sha, f"{candidate_id}: report_sha256"
        )
        validated.append(item)

    first = validated[0]
    shared_fields = (
        "volume_root",
        "spec_sha256",
        "tolerance_voxels",
        "expected",
        "target_signature",
    )
    for item in validated[1:]:
        for field in shared_fields:
            if item[field] != first[field]:
                raise GeometryTournamentError(
                    f"{item['id']}: {field} does not match frozen tournament evidence"
                )
    predictions = [item["prediction_sha256"] for item in validated]
    if len(set(predictions)) != len(predictions):
        raise GeometryTournamentError(
            "candidate prediction_sha256 values must be unique"
        )

    dominated_by: dict[str, list[str]] = {item["id"]: [] for item in validated}
    pairwise: list[dict[str, Any]] = []
    for left in validated:
        for right in validated:
            if left["id"] == right["id"]:
                continue
            if _dominates(left, right):
                dominated_by[right["id"]].append(left["id"])
                pairwise.append(
                    {"dominant": left["id"], "dominated": right["id"]}
                )
    for value in dominated_by.values():
        value.sort()
    pairwise.sort(key=lambda row: (row["dominant"], row["dominated"]))

    frontier = sorted(
        candidate_id for candidate_id, parents in dominated_by.items() if not parents
    )
    all_complete = all(item["complete"] for item in validated)
    if all_complete and len(frontier) == 1:
        decision = "winner"
        winner = frontier[0]
        reason = (
            "one complete candidate Pareto-dominates the field on frozen "
            "held-out evidence"
        )
    else:
        decision = "indeterminate"
        winner = None
        if not all_complete:
            reason = "one or more candidate reports are incomplete"
        else:
            reason = (
                "multiple non-dominated candidates remain on the Pareto frontier"
            )

    public_candidates = []
    for item in sorted(validated, key=lambda row: row["id"]):
        public_candidates.append(
            {k: v for k, v in item.items() if k != "target_signature"}
        )

    return {
        "schema": SCHEMA,
        "tool": "scroliq-geometry-tournament",
        "status": "measured" if all_complete else "incomplete",
        "volume_root": first["volume_root"],
        "spec_sha256": first["spec_sha256"],
        "tolerance_voxels": first["tolerance_voxels"],
        "expected_targets": first["expected"],
        "axes": [
            {
                "name": "within_tolerance_rate",
                "direction": "maximize",
                "denominator": "all held-out targets",
            },
            {"name": "predicted", "direction": "maximize"},
            {
                "name": "median_error_voxels",
                "direction": "minimize",
                "population": "predicted targets only",
            },
            {
                "name": "max_error_voxels",
                "direction": "minimize",
                "population": "predicted targets only",
            },
        ],
        "decision": decision,
        "winner": winner,
        "decision_reason": reason,
        "frontier": frontier,
        "pairwise_dominance": pairwise,
        "candidates": public_candidates,
        "limitations": (
            "Geometry-only held-out comparison. A tournament winner is not proof "
            "of correct sheet identity, topology, CT support, flattening quality, "
            "ink, or Grand Prize readiness. No weighted score is used."
        ),
    }


def _parse_candidate(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("candidate must be NAME=REPORT.json")
    candidate_id, path = value.split("=", 1)
    if not candidate_id.strip() or not path.strip():
        raise argparse.ArgumentTypeError("candidate must be NAME=REPORT.json")
    return candidate_id.strip(), Path(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate",
        action="append",
        required=True,
        type=_parse_candidate,
        metavar="NAME=REPORT.json",
        help="held-out geometry report; provide at least two",
    )
    parser.add_argument("--out", help="new tournament report path; refuses overwrite")
    args = parser.parse_args(argv)
    try:
        rows: list[tuple[str, dict[str, Any], str]] = []
        for candidate_id, path in args.candidate:
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise GeometryTournamentError(
                    f"cannot read {candidate_id} report {path}: {exc}"
                ) from exc
            rows.append((candidate_id, report, _sha256_file(path)))
        result = evaluate_tournament(rows)
        output = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.out:
            with Path(args.out).open("x", encoding="utf-8") as fh:
                fh.write(output)
        print(output, end="")
        return 0 if result["decision"] == "winner" else 1
    except (GeometryTournamentError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
