"""Offline, point-correspondence evaluation for a frozen held-out geometry set.

This does not fit a spiral, choose correspondences, or verify training history.
Coordinates and tolerance are explicitly in the same base-volume voxel frame.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
from statistics import median


def digest(document: dict) -> str:
    """Canonical JSON hash used to bind predictions to the frozen specification."""
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _name(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _ids(values, field):
    if not isinstance(values, list):
        raise ValueError(f"{field} must be a list")
    result = [_name(v, field) for v in values]
    if len(set(result)) != len(result):
        raise ValueError(f"{field} contains duplicate IDs")
    return set(result)


def _xyz(value):
    if (not isinstance(value, list) or len(value) != 3
            or any(type(v) not in (int, float) for v in value)):
        raise ValueError("xyz must contain three finite numbers")
    try:
        result = [float(v) for v in value]
    except OverflowError as exc:
        raise ValueError("xyz is outside numeric range") from exc
    if not all(math.isfinite(v) for v in result):
        raise ValueError("xyz must contain three finite numbers")
    return result


def evaluate(spec: dict, prediction: dict) -> dict:
    if not isinstance(spec, dict) or not isinstance(prediction, dict):
        raise ValueError("specification and prediction must be objects")
    for document in (spec, prediction):
        if type(document.get("schema_version")) is not int or document["schema_version"] != 1:
            raise ValueError("schema_version must be 1")
        if document.get("coordinate_system") != "base_voxel_xyz":
            raise ValueError("coordinate_system must be base_voxel_xyz")
    volume = _name(spec.get("volume_root"), "volume_root")
    if prediction.get("volume_root") != volume:
        raise ValueError("exact volume_root mismatch")
    tolerance = spec.get("tolerance_voxels")
    if type(tolerance) not in (int, float) or not 0 < tolerance < float("inf"):
        raise ValueError("tolerance_voxels must be finite and positive")
    expected_fit = _ids(spec.get("fit_ids"), "fit_ids")
    used_fit = _ids(prediction.get("used_fit_ids"), "used_fit_ids")
    if not expected_fit or not used_fit:
        raise ValueError("fit input declarations must not be empty")
    checkpoint = prediction.get("checkpoint_sha256")
    if not isinstance(checkpoint, str) or not re.fullmatch(r"[0-9a-f]{64}", checkpoint):
        raise ValueError("checkpoint_sha256 must be lowercase 64-hex")
    targets = spec.get("targets")
    outputs = prediction.get("predictions")
    if not isinstance(targets, list) or not targets or not isinstance(outputs, list):
        raise ValueError("targets must be non-empty; predictions must be a list")
    expected = {}
    for row in targets:
        if not isinstance(row, dict):
            raise ValueError("target must be an object")
        identifier = _name(row.get("id"), "target id")
        if identifier in expected:
            raise ValueError("duplicate target id")
        expected[identifier] = _xyz(row.get("xyz"))
    if set(expected) & expected_fit or set(expected) & used_fit:
        raise ValueError("held-out target overlaps declared fit inputs")
    if used_fit - expected_fit:
        raise ValueError("undeclared fit inputs")
    spec_hash = digest(spec)
    if prediction.get("spec_sha256") != spec_hash:
        raise ValueError("spec_sha256 mismatch: evaluation specification changed")
    observed = {}
    for row in outputs:
        if not isinstance(row, dict):
            raise ValueError("prediction row must be an object")
        identifier = _name(row.get("id"), "prediction id")
        if identifier not in expected or identifier in observed:
            raise ValueError("unknown or duplicate prediction id")
        if row.get("status") == "failed":
            if row.get("xyz") is not None:
                raise ValueError("failed prediction cannot also supply xyz")
            observed[identifier] = {"status": "failed", "reason": _name(row.get("reason"), "failure reason")}
        elif row.get("status") == "ok":
            observed[identifier] = {"status": "ok", "xyz": _xyz(row.get("xyz"))}
        else:
            raise ValueError("prediction status must be ok or failed")
    rows, distances = [], []
    for identifier, xyz in sorted(expected.items()):
        output = observed.get(identifier, {"status": "missing"})
        row = {"id": identifier, "reference_xyz": xyz, **output, "within_tolerance": False}
        if output["status"] == "ok":
            distance = math.dist(xyz, output["xyz"])
            if not math.isfinite(distance):
                raise ValueError("residual outside finite numeric range")
            row.update(error_voxels=distance, within_tolerance=distance <= tolerance)
            distances.append(distance)
        rows.append(row)
    n = len(rows)
    return {
        "schema_version": 1, "tool": "scroliq-geometry-validate",
        "status": "measured" if len(distances) == n else "incomplete",
        "volume_root": volume, "coordinate_system": "base_voxel_xyz",
        "spec_sha256": spec_hash, "prediction_sha256": digest(prediction),
        "checkpoint_sha256": checkpoint, "tolerance_voxels": tolerance,
        "expected": n, "predicted": len(distances),
        "missing": sum(r["status"] == "missing" for r in rows),
        "failed": sum(r["status"] == "failed" for r in rows),
        "within_tolerance": sum(r["within_tolerance"] for r in rows),
        "within_tolerance_rate": sum(r["within_tolerance"] for r in rows) / n,
        "predicted_only_median_error_voxels": median(distances) if distances else None,
        "predicted_only_max_error_voxels": max(distances) if distances else None,
        "fit_input_check": "declared IDs disjoint; training history not independently verified",
        "limitations": "Point correspondence only; not sheet identity, topology, surface coverage or readability. Spatial exclusion must be certified separately.",
        "targets": rows,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--predictions", help="prediction JSON; omit with --print-spec-hash")
    parser.add_argument("--print-spec-hash", action="store_true")
    parser.add_argument("--out", help="new report path; refuses overwrite")
    args = parser.parse_args(argv)
    try:
        spec = json.loads(Path(args.spec).read_text())
        if args.print_spec_hash:
            print(digest(spec))
            return 0
        if not args.predictions:
            parser.error("--predictions is required unless --print-spec-hash is used")
        prediction = json.loads(Path(args.predictions).read_text())
        result = evaluate(spec, prediction)
        text = json.dumps(result, indent=2, allow_nan=False) + "\n"
        if args.out:
            with Path(args.out).open("x") as fh:
                fh.write(text)
        print(text, end="")
        return int(result["within_tolerance"] != result["expected"])
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
