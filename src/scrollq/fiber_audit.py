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
import math
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA_VERSION = 2
DIAGNOSTIC = "fiber-trace-audit"
VC3D_FORMAT_REFERENCE_COMMIT = "56d7c3aeea4bbccf5f56b195ce2a44ea2cf601dd"
VC3D_FORMAT_REFERENCE_PATH = "vesuvius/src/vc3d_fiber_format/__init__.py"
_VC3D_VERSIONS = {1, 3, 4}
_GOALS = {"global", "cspline", "lasagna", "trace"}
_MODES = {"cspline", "lasagna", "trace"}
_SEGMENT_FIELDS = {
    "optimizer", "metadata_version", "tracer_version", "interp_goal",
    "interp_mode", "metric", "msg", "normal_manifest", "fiber_manifest",
    "trace_to_base_scale", "meeting_error_base_voxels", "meeting_error_ratio",
    "meeting_source", "failure_code", "failure_detail",
    "lasagna_failure_code", "lasagna_failure_detail", "config",
}
_CONFIG_FIELDS = {
    "step_voxels", "cone_angle_degrees", "cone_angle_step_degrees",
    "cone_grid_size", "beam_width", "beam_prune_distance_voxels",
    "beam_lookahead_steps", "smoothness_weight", "smoothness_normal_weight",
    "smoothness_tangent_weight", "smoothness_free_angle_degrees",
    "cumulative_smoothness_steps", "cumulative_smoothness_tangent_weight",
    "initial_free_angle_degrees", "max_step_factor",
    "meeting_accept_max_error_ratio", "endpoint_accept_threshold_base_voxels",
}
_INTEGER_CONFIG_FIELDS = {
    "cone_grid_size", "beam_width", "beam_lookahead_steps",
    "cumulative_smoothness_steps",
}
_POSITIVE_CONFIG_FIELDS = {
    "step_voxels", "cone_angle_degrees", "cone_angle_step_degrees",
    "cone_grid_size", "beam_width", "beam_prune_distance_voxels",
    "max_step_factor", "endpoint_accept_threshold_base_voxels",
}


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
        "diagnostic": DIAGNOSTIC,
        "schema_version": SCHEMA_VERSION,
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


def audit_csv(path, *, volume_root: str | None = None, **kwargs) -> dict:
    """Audit a CSV file and record its SHA-256 for provenance."""
    path = Path(path)
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = audit_rows(rows, **kwargs)
    out["input_format"] = "csv"
    out["volume_root"] = volume_root
    out["input"] = {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    }
    return out


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{label} must be finite")
    return out


def _point3(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} must be [x, y, z]")
    return [_finite_number(v, label) for v in value]


def _validate_trace_config(config: Any, index: int) -> None:
    if not isinstance(config, dict) or set(config) != _CONFIG_FIELDS:
        raise ValueError(f"control_points[{index}] trace config schema mismatch")
    for key, value in config.items():
        number = _finite_number(value, f"control_points[{index}] config.{key}")
        if key in _INTEGER_CONFIG_FIELDS and (
            isinstance(value, bool) or not isinstance(value, int)
        ):
            raise ValueError(f"control_points[{index}] config.{key} must be an integer")
        if key in _POSITIVE_CONFIG_FIELDS and number <= 0:
            raise ValueError(f"control_points[{index}] config.{key} must be positive")
        if key not in _POSITIVE_CONFIG_FIELDS and number < 0:
            raise ValueError(f"control_points[{index}] config.{key} must be non-negative")
    if float(config["meeting_accept_max_error_ratio"]) > 1:
        raise ValueError(
            f"control_points[{index}] meeting_accept_max_error_ratio must be <= 1"
        )


def _segment_summary(raw: Any, index: int, version: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"control_points[{index}].segment_to_next must be an object")
    keys = set(raw)
    if version >= 4:
        keys.discard("tags")
    if keys != _SEGMENT_FIELDS:
        missing = sorted(_SEGMENT_FIELDS - keys)
        unknown = sorted(keys - _SEGMENT_FIELDS)
        raise ValueError(
            f"control_points[{index}] segment_to_next schema mismatch "
            f"(missing={missing}, unknown={unknown})"
        )
    if raw["optimizer"] != "native_fiber_trace3d":
        raise ValueError(f"control_points[{index}] optimizer is unsupported")
    if (raw["metadata_version"], raw["tracer_version"]) != (3, 2):
        raise ValueError(f"control_points[{index}] metadata/tracer version is unsupported")

    goal, mode = raw["interp_goal"], raw["interp_mode"]
    if goal not in _GOALS:
        raise ValueError(f"control_points[{index}] interp_goal is invalid")
    if mode not in _MODES:
        raise ValueError(f"control_points[{index}] interp_mode is invalid")

    for field in (
        "msg", "normal_manifest", "fiber_manifest", "meeting_source",
        "failure_code", "failure_detail", "lasagna_failure_code",
        "lasagna_failure_detail",
    ):
        if not isinstance(raw[field], str):
            raise ValueError(f"control_points[{index}] {field} must be a string")

    metric = raw["metric"]
    if metric is not None:
        metric = _finite_number(metric, f"control_points[{index}] metric")
        if metric < 0:
            raise ValueError(f"control_points[{index}] metric must be non-negative")
    if mode == "cspline" and metric is not None:
        raise ValueError(f"control_points[{index}] cspline span cannot contain metric")

    trace_scale = _finite_number(
        raw["trace_to_base_scale"], f"control_points[{index}] trace_to_base_scale"
    )
    if trace_scale <= 0:
        raise ValueError(f"control_points[{index}] trace_to_base_scale must be positive")

    meeting_error = raw["meeting_error_base_voxels"]
    meeting_ratio = raw["meeting_error_ratio"]
    if meeting_error is not None:
        meeting_error = _finite_number(
            meeting_error, f"control_points[{index}] meeting_error_base_voxels"
        )
        if meeting_error < 0:
            raise ValueError(f"control_points[{index}] meeting error must be non-negative")
    if meeting_ratio is not None:
        meeting_ratio = _finite_number(
            meeting_ratio, f"control_points[{index}] meeting_error_ratio"
        )
        if meeting_ratio < 0:
            raise ValueError(f"control_points[{index}] meeting ratio must be non-negative")

    if mode == "trace":
        if (
            metric is None or meeting_error is None or meeting_ratio is None
            or not raw["meeting_source"] or raw["failure_code"]
            or raw["failure_detail"] or not raw["normal_manifest"]
            or not raw["fiber_manifest"]
        ):
            raise ValueError(
                f"control_points[{index}] trace span has inconsistent acceptance diagnostics"
            )
    elif meeting_error is not None or meeting_ratio is not None or raw["meeting_source"]:
        raise ValueError(
            f"control_points[{index}] non-trace span contains trace meeting diagnostics"
        )

    tags = raw.get("tags", [])
    if tags:
        if version < 4:
            raise ValueError(f"control_points[{index}] version-3 span cannot contain tags")
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError(f"control_points[{index}] span tags must be strings")

    _validate_trace_config(raw["config"], index)
    return {
        "index": index,
        "interp_goal": goal,
        "interp_mode": mode,
        "metric": metric,
        "meeting_error_base_voxels": meeting_error,
        "meeting_error_ratio": meeting_ratio,
        "failure_code": raw["failure_code"],
        "lasagna_failure_code": raw["lasagna_failure_code"],
        "tags": list(tags),
    }



def _control_line_consistency(
    line_points: list[list[float]],
    controls: list[list[float]],
    *,
    distance_factor: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compare persisted control points with the rendered VC3D line.

    Distances are normalized by the rendered line's median non-zero step so
    the audit does not bake in an absolute voxel-size assumption.
    """
    if distance_factor <= 1:
        raise ValueError("control_line_factor must be > 1")
    if not line_points or not controls:
        return {
            "status": "unknown",
            "reason": "line_points and control_points are both required",
            "distance_factor": distance_factor,
        }, []

    line = np.asarray(line_points, dtype=np.float64)
    cps = np.asarray(controls, dtype=np.float64)
    if len(line) < 2:
        return {
            "status": "unknown",
            "reason": "at least two line_points are required for a scale-relative check",
            "distance_factor": distance_factor,
            "control_points": int(len(cps)),
        }, []

    steps = np.linalg.norm(np.diff(line, axis=0), axis=1)
    positive = steps[np.isfinite(steps) & (steps > 0)]
    baseline = float(np.median(positive)) if positive.size else 0.0
    if baseline <= 0:
        return {
            "status": "unknown",
            "reason": "rendered line has no non-zero step length",
            "distance_factor": distance_factor,
            "control_points": int(len(cps)),
        }, []

    nearest_indices: list[int] = []
    nearest_distances: list[float] = []
    findings: list[dict[str, Any]] = []
    for index, point in enumerate(cps):
        distances2 = np.sum((line - point) ** 2, axis=1)
        nearest = int(np.argmin(distances2))
        distance = float(math.sqrt(float(distances2[nearest])))
        ratio = distance / baseline
        nearest_indices.append(nearest)
        nearest_distances.append(distance)
        if ratio > distance_factor:
            findings.append({
                "trace_id": "line_points",
                "kind": "control_line_offset",
                "control_point": index,
                "nearest_line_point": nearest,
                "distance": distance,
                "ratio_to_median_step": ratio,
            })

    order_inversions = 0
    for index, (a, b) in enumerate(zip(nearest_indices, nearest_indices[1:])):
        if b < a:
            order_inversions += 1
            findings.append({
                "trace_id": "line_points",
                "kind": "control_order_inversion",
                "control_segment": index,
                "from_nearest_line_point": a,
                "to_nearest_line_point": b,
            })

    distances = np.asarray(nearest_distances, dtype=np.float64)
    ratios = distances / baseline
    return {
        "status": "measured",
        "distance_factor": distance_factor,
        "median_line_step": baseline,
        "control_points": int(len(cps)),
        "offset_candidates": sum(
            1 for item in findings if item["kind"] == "control_line_offset"
        ),
        "order_inversions": order_inversions,
        "nearest_distance": {
            "max": float(distances.max()) if distances.size else None,
            "p95": float(np.quantile(distances, 0.95)) if distances.size else None,
        },
        "ratio_to_median_step": {
            "max": float(ratios.max()) if ratios.size else None,
            "p95": float(np.quantile(ratios, 0.95)) if ratios.size else None,
        },
        "nearest_index_monotonic": order_inversions == 0,
    }, findings


def audit_vc3d_json(
    path: str | Path,
    *,
    volume_root: str | None = None,
    gap_factor: float = 4.0,
    turn_degrees: float = 60.0,
    control_line_factor: float = 4.0,
) -> dict:
    src = Path(path)
    payload = src.read_bytes()
    provenance = {
        "path": str(src),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }
    try:
        obj = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "diagnostic": DIAGNOSTIC,
            "schema_version": SCHEMA_VERSION,
            "status": "fail",
            "input_format": "vc3d_fiber_json",
            "volume_root": volume_root,
            "input": provenance,
            "counts": {"rows": 0, "valid_traces": 0, "parse_errors": 1,
                       "gaps": 0, "sharp_turns": 0},
            "total_trace_length": 0.0,
            "findings": [],
            "errors": [{"field": "$", "error": f"invalid JSON: {exc}"}],
            "interpretation": "Could not parse VC3D fiber JSON.",
        }

    errors: list[dict[str, Any]] = []
    line_points: list[list[float]] = []
    controls: list[list[float]] = []
    segments: list[dict[str, Any]] = []
    version = None
    generation = None
    optimization_mode = None
    try:
        if not isinstance(obj, dict):
            raise ValueError("top-level JSON must be an object")
        version = obj.get("version", 1)
        if (
            isinstance(version, bool) or not isinstance(version, int)
            or version not in _VC3D_VERSIONS
        ):
            raise ValueError("only vc3d_fiber versions 1, 3 and 4 are supported")
        if obj.get("type", "vc3d_fiber") != "vc3d_fiber":
            raise ValueError("type must be vc3d_fiber")
        if version >= 3 and "type" not in obj:
            raise ValueError("version-3/4 fiber must declare type")

        raw_line = obj.get("line_points")
        if not isinstance(raw_line, list):
            raise ValueError("line_points must be a list")
        line_points = [_point3(p, f"line_points[{i}]") for i, p in enumerate(raw_line)]

        raw_controls = obj.get("control_points")
        if not isinstance(raw_controls, list):
            raise ValueError("control_points must be a list")
        if version == 1:
            controls = [_point3(p, f"control_points[{i}]")
                        for i, p in enumerate(raw_controls)]
            optimization_mode = "lasagna"
        else:
            optimization_mode = obj.get("optimization_mode")
            if optimization_mode not in {"lasagna", "native_fiber_trace3d"}:
                raise ValueError("optimization_mode is invalid")
            for i, control in enumerate(raw_controls):
                if not isinstance(control, dict):
                    raise ValueError(f"control_points[{i}] must be an object")
                allowed = {"position", "segment_to_next", "tags"}
                if not set(control) <= allowed:
                    raise ValueError(f"control_points[{i}] contains unknown fields")
                controls.append(
                    _point3(control.get("position"), f"control_points[{i}].position")
                )
                cp_tags = control.get("tags", [])
                if cp_tags and (
                    not isinstance(cp_tags, list)
                    or not all(isinstance(tag, str) for tag in cp_tags)
                ):
                    raise ValueError(f"control_points[{i}].tags must be strings")
                if i + 1 == len(raw_controls):
                    if "segment_to_next" in control:
                        raise ValueError("final control point cannot contain segment_to_next")
                else:
                    if "segment_to_next" not in control:
                        raise ValueError(f"control_points[{i}] is missing segment_to_next")
                    segments.append(_segment_summary(
                        control["segment_to_next"], i, version
                    ))

        generation = obj.get("generation", 1)
        if isinstance(generation, bool) or not isinstance(generation, int):
            raise ValueError("generation must be an integer")
        if version >= 3 and generation < 0:
            raise ValueError("generation must be non-negative")
    except ValueError as exc:
        errors.append({"field": "vc3d_fiber", "error": str(exc)})

    rows = [
        {"trace_id": "line_points", "x": p[0], "y": p[1], "z": p[2]}
        for p in line_points
    ]
    out = audit_rows(rows, gap_factor=gap_factor, turn_degrees=turn_degrees)
    try:
        control_line, control_findings = _control_line_consistency(
            line_points, controls, distance_factor=control_line_factor
        )
    except ValueError as exc:
        control_line = {
            "status": "fail",
            "distance_factor": control_line_factor,
            "reason": str(exc),
        }
        control_findings = []
        errors.append({"field": "parameters.control_line_factor", "error": str(exc)})
    out["control_line"] = control_line
    out["findings"].extend(control_findings)
    out["counts"]["control_line_offsets"] = sum(
        1 for item in control_findings if item["kind"] == "control_line_offset"
    )
    out["counts"]["control_order_inversions"] = sum(
        1 for item in control_findings if item["kind"] == "control_order_inversion"
    )
    if control_findings and out["status"] == "pass":
        out["status"] = "caution"
    if errors:
        out["status"] = "fail"
        out["errors"].extend(errors)
        out["counts"]["parse_errors"] += len(errors)
    out["input_format"] = "vc3d_fiber_json"
    out["volume_root"] = volume_root
    out["input"] = provenance
    out["format_reference"] = {
        "repository": "ScrollPrize/villa",
        "commit": VC3D_FORMAT_REFERENCE_COMMIT,
        "path": VC3D_FORMAT_REFERENCE_PATH,
    }

    if version is not None:
        native = [s for s in segments if s["interp_mode"] == "trace"]
        fallback = [s for s in segments if s["interp_mode"] != "trace"]
        ratios = [s["meeting_error_ratio"] for s in native
                  if s["meeting_error_ratio"] is not None]
        out["vc3d_fiber"] = {
            "version": version,
            "generation": generation,
            "optimization_mode": optimization_mode,
            "line_points": len(line_points),
            "control_points": len(controls),
            "segments": len(segments),
            "interp_mode_counts": {
                mode: sum(1 for s in segments if s["interp_mode"] == mode)
                for mode in sorted(_MODES)
            },
            "interp_goal_counts": {
                goal: sum(1 for s in segments if s["interp_goal"] == goal)
                for goal in sorted(_GOALS)
            },
            "native_trace_segments": len(native),
            "fallback_segments": len(fallback),
            "fallback_fraction": len(fallback) / len(segments) if segments else None,
            "native_meeting_error_ratio": {
                "count": len(ratios),
                "max": max(ratios) if ratios else None,
                "mean": float(sum(ratios) / len(ratios)) if ratios else None,
            },
            "failure_codes": [
                {"segment": s["index"], "failure_code": s["failure_code"],
                 "lasagna_failure_code": s["lasagna_failure_code"]}
                for s in segments
                if s["failure_code"] or s["lasagna_failure_code"]
            ],
            "tagged_segments": [
                {"segment": s["index"], "tags": s["tags"]}
                for s in segments if s["tags"]
            ],
        }
    out["interpretation"] = (
        "Geometry findings flag candidate discontinuities in the rendered VC3D "
        "fiber line. Native trace coverage, fallbacks, and acceptance errors are "
        "reported separately; fallback interpolation is not itself a geometry defect."
    )
    return out


def audit_path(path: str | Path, *, input_format: str = "auto", **kwargs: Any) -> dict:
    src = Path(path)
    fmt = input_format
    if fmt == "auto":
        fmt = "vc3d-json" if src.suffix.lower() == ".json" else "csv"
    if fmt == "vc3d-json":
        return audit_vc3d_json(src, **kwargs)
    if fmt == "csv":
        return audit_csv(src, **kwargs)
    raise ValueError(f"unsupported input format: {fmt}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Audit ordered CSV fiber traces or native VC3D vc3d_fiber JSON "
            "(versions 1, 3, and 4)."
        )
    )
    ap.add_argument("input")
    ap.add_argument(
        "--format", choices=("auto", "csv", "vc3d-json"), default="auto",
        help="input format; auto uses .json for VC3D JSON and CSV otherwise",
    )
    ap.add_argument("--volume-root", default=None, help="exact CT volume root this fiber belongs to")
    ap.add_argument("--gap-factor", type=float, default=4.0)
    ap.add_argument("--turn-degrees", type=float, default=60.0)
    ap.add_argument("--control-line-factor", type=float, default=4.0, help="flag a control point farther from rendered line_points than this multiple of the median non-zero line step")
    ap.add_argument("--fail-on-findings", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    result = audit_path(
        a.input, input_format=a.format, volume_root=a.volume_root,
        gap_factor=a.gap_factor, turn_degrees=a.turn_degrees,
        control_line_factor=a.control_line_factor,
    )
    text = json.dumps(result, indent=2)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    fail = result["status"] == "fail"
    gated = a.fail_on_findings and bool(result.get("findings"))
    raise SystemExit(2 if fail or gated else 0)

if __name__ == "__main__":
    main()
