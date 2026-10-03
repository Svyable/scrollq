"""Held-out evaluator for deterministic horizon-path experiments.

The frozen specification binds score/truth hashes, tracker parameters, anchors,
anchor exclusion, tolerance, and the decision rule. Missing predictions remain
in the denominator. This evaluates 2-D path recovery only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path
from statistics import median
from typing import Any


HEX64 = re.compile(r"[0-9a-f]{64}")


def digest(document: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            document, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _finite_number(value: Any, field: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{field} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    return value


def _integer(value: Any, field: str, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise ValueError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field} must be >= {minimum}")
    return value


def _hex64(value: Any, field: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise ValueError(f"{field} must be lowercase 64-hex")
    return value


def _anchors(value: Any, rows: int, cols: int) -> list[dict[str, int]]:
    if not isinstance(value, list) or not value:
        raise ValueError("anchors must be a non-empty list")
    out: list[dict[str, int]] = []
    seen: set[int] = set()
    for i, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {"x", "y"}:
            raise ValueError(f"anchor {i} must contain exactly x and y")
        x = _integer(item["x"], f"anchor {i} x", minimum=0)
        y = _integer(item["y"], f"anchor {i} y", minimum=0)
        if x >= cols or y >= rows:
            raise ValueError(f"anchor {i} is outside shape_yx")
        if x in seen:
            raise ValueError("anchors contain duplicate x coordinates")
        seen.add(x)
        out.append({"x": x, "y": y})
    return sorted(out, key=lambda row: row["x"])


def validate_spec(spec: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ValueError("specification must be an object")
    if spec.get("schema_version") != 1 or type(spec.get("schema_version")) is not int:
        raise ValueError("schema_version must be 1")
    if spec.get("coordinate_system") != "score_map_xy":
        raise ValueError("coordinate_system must be score_map_xy")

    protocol_id = spec.get("protocol_id")
    if not isinstance(protocol_id, str) or not protocol_id.strip():
        raise ValueError("protocol_id must be a non-empty string")

    shape = spec.get("shape_yx")
    if (
        not isinstance(shape, list)
        or len(shape) != 2
        or any(type(v) is not int or v <= 0 for v in shape)
    ):
        raise ValueError("shape_yx must contain two positive integers")
    rows, cols = shape

    score_sha = _hex64(spec.get("score_sha256"), "score_sha256")
    truth_sha = _hex64(spec.get("truth_sha256"), "truth_sha256")

    tracker = spec.get("tracker")
    if not isinstance(tracker, dict):
        raise ValueError("tracker must be an object")
    max_step = _integer(tracker.get("max_step"), "tracker.max_step", minimum=0)
    smoothness = _finite_number(tracker.get("smoothness"), "tracker.smoothness")
    if smoothness < 0:
        raise ValueError("tracker.smoothness must be >= 0")

    normalization = tracker.get("normalization")
    if not isinstance(normalization, dict) or type(normalization.get("enabled")) is not bool:
        raise ValueError("tracker.normalization.enabled must be boolean")
    norm = {"enabled": normalization["enabled"]}
    if normalization["enabled"]:
        low = _finite_number(
            normalization.get("lower_percentile"),
            "tracker.normalization.lower_percentile",
        )
        high = _finite_number(
            normalization.get("upper_percentile"),
            "tracker.normalization.upper_percentile",
        )
        if not 0 <= low < high <= 100:
            raise ValueError("normalization percentiles must satisfy 0 <= low < high <= 100")
        norm.update(lower_percentile=low, upper_percentile=high)

    anchor_rows = _anchors(spec.get("anchors"), rows, cols)
    exclusion = _integer(
        spec.get("anchor_exclusion_columns"),
        "anchor_exclusion_columns",
        minimum=0,
    )
    tolerance = _finite_number(spec.get("tolerance_rows"), "tolerance_rows")
    if tolerance <= 0:
        raise ValueError("tolerance_rows must be > 0")
    required_rate = _finite_number(
        spec.get("minimum_within_tolerance_rate"),
        "minimum_within_tolerance_rate",
    )
    if not 0 <= required_rate <= 1:
        raise ValueError("minimum_within_tolerance_rate must be in [0, 1]")

    return {
        "schema_version": 1,
        "coordinate_system": "score_map_xy",
        "protocol_id": protocol_id,
        "shape_yx": [rows, cols],
        "score_sha256": score_sha,
        "truth_sha256": truth_sha,
        "tracker": {
            "max_step": max_step,
            "smoothness": smoothness,
            "normalization": norm,
        },
        "anchors": anchor_rows,
        "anchor_exclusion_columns": exclusion,
        "tolerance_rows": tolerance,
        "minimum_within_tolerance_rate": required_rate,
    }


def _load_truth(path: Path, rows: int, cols: int) -> dict[int, float]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None or not {"x", "y"}.issubset(reader.fieldnames):
            raise ValueError("truth CSV must contain x and y columns")
        truth: dict[int, float] = {}
        for line, row in enumerate(reader, start=2):
            try:
                x_float = float(row["x"])
                y = float(row["y"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"truth CSV line {line} has invalid x/y") from exc
            if not math.isfinite(x_float) or int(x_float) != x_float:
                raise ValueError(f"truth CSV line {line} x must be an integer")
            x = int(x_float)
            if not math.isfinite(y):
                raise ValueError(f"truth CSV line {line} y must be finite")
            if not 0 <= x < cols or not 0 <= y <= rows - 1:
                raise ValueError(f"truth CSV line {line} is outside shape_yx")
            if x in truth:
                raise ValueError(f"truth CSV contains duplicate x={x}")
            truth[x] = y
    if not truth:
        raise ValueError("truth CSV must contain at least one point")
    return truth


def _same_number(a: Any, b: Any) -> bool:
    try:
        return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-12)
    except (TypeError, ValueError, OverflowError):
        return False


def _verify_prediction(
    prediction: dict[str, Any],
    spec: dict[str, Any],
    *,
    prediction_csv: Path | None,
) -> tuple[dict[int, int], Path]:
    if not isinstance(prediction, dict):
        raise ValueError("prediction must be an object")
    if prediction.get("schema_version") != 1 or prediction.get("kind") != "horizon-path":
        raise ValueError("prediction must be a schema-version 1 horizon-path report")
    if prediction.get("method") != "deterministic-first-order-horizon-dp-v1":
        raise ValueError("prediction method mismatch")

    inp = prediction.get("input")
    if not isinstance(inp, dict):
        raise ValueError("prediction input metadata is missing")
    if inp.get("sha256") != spec["score_sha256"]:
        raise ValueError("prediction score SHA-256 does not match frozen specification")
    if inp.get("shape_yx") != spec["shape_yx"]:
        raise ValueError("prediction shape_yx does not match frozen specification")

    params = prediction.get("parameters")
    expected_tracker = spec["tracker"]
    if not isinstance(params, dict):
        raise ValueError("prediction parameters are missing")
    if params.get("max_step") != expected_tracker["max_step"]:
        raise ValueError("prediction max_step does not match frozen specification")
    if not _same_number(params.get("smoothness"), expected_tracker["smoothness"]):
        raise ValueError("prediction smoothness does not match frozen specification")

    norm = prediction.get("normalization")
    expected_norm = expected_tracker["normalization"]
    if not isinstance(norm, dict) or norm.get("enabled") is not expected_norm["enabled"]:
        raise ValueError("prediction normalization mode does not match frozen specification")
    if expected_norm["enabled"]:
        for key in ("lower_percentile", "upper_percentile"):
            if not _same_number(norm.get(key), expected_norm[key]):
                raise ValueError(
                    f"prediction normalization {key} does not match frozen specification"
                )

    path = prediction.get("path")
    if not isinstance(path, dict):
        raise ValueError("prediction path metadata is missing")
    if path.get("anchors") != spec["anchors"]:
        raise ValueError("prediction anchors do not match frozen specification")

    points = path.get("points")
    if not isinstance(points, list):
        raise ValueError("prediction path points must be a list")
    rows, cols = spec["shape_yx"]
    observed: dict[int, int] = {}
    for i, item in enumerate(points):
        if not isinstance(item, dict) or set(item) != {"x", "y"}:
            raise ValueError(f"prediction point {i} must contain exactly x and y")
        x = _integer(item["x"], f"prediction point {i} x", minimum=0)
        y = _integer(item["y"], f"prediction point {i} y", minimum=0)
        if x >= cols or y >= rows:
            raise ValueError(f"prediction point {i} is outside shape_yx")
        if x in observed:
            raise ValueError(f"prediction contains duplicate x={x}")
        observed[x] = y

    declared_csv = path.get("csv_path")
    declared_sha = _hex64(path.get("csv_sha256"), "prediction path csv_sha256")
    csv_path = prediction_csv or (Path(declared_csv) if isinstance(declared_csv, str) else None)
    if csv_path is None:
        raise ValueError("prediction CSV path is unavailable; pass --prediction-csv")
    if _sha256(csv_path) != declared_sha:
        raise ValueError("prediction CSV SHA-256 does not match prediction report")
    return observed, csv_path


def evaluate(
    spec_document: dict[str, Any],
    prediction: dict[str, Any],
    *,
    truth_path: Path,
    prediction_csv: Path | None = None,
) -> dict[str, Any]:
    spec = validate_spec(spec_document)
    if _sha256(truth_path) != spec["truth_sha256"]:
        raise ValueError("truth CSV SHA-256 does not match frozen specification")

    rows, cols = spec["shape_yx"]
    truth = _load_truth(truth_path, rows, cols)
    predicted, resolved_csv = _verify_prediction(
        prediction, spec, prediction_csv=prediction_csv
    )

    exclusion = spec["anchor_exclusion_columns"]
    anchor_x = [row["x"] for row in spec["anchors"]]
    target_rows: list[dict[str, Any]] = []
    errors: list[float] = []
    within = 0
    expected = 0
    missing = 0

    for x, reference_y in sorted(truth.items()):
        excluded_by = [ax for ax in anchor_x if abs(x - ax) <= exclusion]
        if excluded_by:
            target_rows.append(
                {
                    "x": x,
                    "reference_y": reference_y,
                    "status": "excluded-anchor-neighborhood",
                    "excluded_by_anchor_x": excluded_by,
                }
            )
            continue

        expected += 1
        if x not in predicted:
            missing += 1
            target_rows.append(
                {
                    "x": x,
                    "reference_y": reference_y,
                    "status": "missing",
                    "within_tolerance": False,
                }
            )
            continue

        y = predicted[x]
        error = abs(float(y) - reference_y)
        ok = error <= spec["tolerance_rows"]
        within += int(ok)
        errors.append(error)
        target_rows.append(
            {
                "x": x,
                "reference_y": reference_y,
                "predicted_y": y,
                "status": "ok",
                "absolute_error_rows": error,
                "within_tolerance": ok,
            }
        )

    if expected == 0:
        raise ValueError("anchor exclusion leaves no held-out truth points")

    rate = within / expected
    verdict = (
        "PASS"
        if rate >= spec["minimum_within_tolerance_rate"]
        else "FAIL"
    )
    sorted_errors = sorted(errors)
    p95 = None
    if sorted_errors:
        index = max(0, math.ceil(0.95 * len(sorted_errors)) - 1)
        p95 = sorted_errors[index]

    return {
        "schema_version": 1,
        "tool": "scroliq-horizon-validate",
        "status": "measured",
        "verdict": verdict,
        "coordinate_system": "score_map_xy",
        "protocol_id": spec["protocol_id"],
        "spec_sha256": digest(spec_document),
        "prediction_sha256": digest(prediction),
        "prediction_csv_sha256": _sha256(resolved_csv),
        "truth_sha256": spec["truth_sha256"],
        "shape_yx": spec["shape_yx"],
        "anchor_exclusion_columns": exclusion,
        "anchors": spec["anchors"],
        "tolerance_rows": spec["tolerance_rows"],
        "minimum_within_tolerance_rate": spec[
            "minimum_within_tolerance_rate"
        ],
        "expected_heldout_points": expected,
        "predicted_heldout_points": expected - missing,
        "missing_predictions": missing,
        "within_tolerance": within,
        "within_tolerance_rate": rate,
        "predicted_only_mean_absolute_error_rows": (
            sum(errors) / len(errors) if errors else None
        ),
        "predicted_only_median_absolute_error_rows": (
            median(errors) if errors else None
        ),
        "predicted_only_p95_absolute_error_rows": p95,
        "predicted_only_max_absolute_error_rows": max(errors) if errors else None,
        "fit_input_check": (
            "declared anchor neighborhoods excluded from scoring; no claim that "
            "parameter tuning or upstream score construction was independently blind"
        ),
        "limitations": (
            "2-D path correspondence only; not papyrus identity, winding identity, "
            "3-D topology, recto/verso, ink, readability, or proof of training-history separation"
        ),
        "targets": target_rows,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--prediction")
    parser.add_argument("--truth")
    parser.add_argument("--prediction-csv")
    parser.add_argument("--print-spec-hash", action="store_true")
    parser.add_argument("--out", help="new report path; refuses overwrite")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        spec_document = json.loads(Path(args.spec).read_text())
        validate_spec(spec_document)
        if args.print_spec_hash:
            print(digest(spec_document))
            return 0
        if not args.prediction or not args.truth:
            parser.error("--prediction and --truth are required unless --print-spec-hash is used")
        prediction = json.loads(Path(args.prediction).read_text())
        result = evaluate(
            spec_document,
            prediction,
            truth_path=Path(args.truth),
            prediction_csv=Path(args.prediction_csv) if args.prediction_csv else None,
        )
        text = json.dumps(result, indent=2, allow_nan=False) + "\n"
        if args.out:
            with Path(args.out).open("x") as f:
                f.write(text)
        print(text, end="")
        return 0 if result["verdict"] == "PASS" else 1
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
