from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = "scroliq-sheetness-benchmark/3"
REQUIRED_CONTROL_ROLES = ("normal-offset", "wrong-wrap")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: str | Path) -> str:
    path = Path(path)
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def canonical_sha256(value: Any) -> str:
    blob = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be lowercase 64-hex sha256")
    return value


def _coord(value: Any, name: str) -> tuple[int, int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(type(v) is not int for v in value)
    ):
        raise ValueError(f"{name} must be [z, y, x] integer coordinates")
    return int(value[0]), int(value[1]), int(value[2])


def _unit(value: Any, name: str) -> np.ndarray:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value)
    ):
        raise ValueError(f"{name} must be a numeric 3-vector in ZYX order")
    vec = np.asarray(value, dtype=np.float64)
    if not np.isfinite(vec).all():
        raise ValueError(f"{name} must be finite")
    norm = float(np.linalg.norm(vec))
    if norm <= 0:
        raise ValueError(f"{name} must be non-zero")
    return vec / norm


def _value_at(array: np.ndarray, coord: tuple[int, int, int]) -> tuple[float | None, str | None]:
    if any(c < 0 or c >= size for c, size in zip(coord, array.shape)):
        return None, "out-of-bounds"
    value = float(array[coord])
    if not math.isfinite(value):
        return None, "non-finite"
    return value, None


def _normal_at(
    normals: np.ndarray, coord: tuple[int, int, int], reference: np.ndarray
) -> tuple[float | None, str | None]:
    if any(c < 0 or c >= size for c, size in zip(coord, normals.shape[:3])):
        return None, "out-of-bounds"
    pred = np.asarray(normals[coord], dtype=np.float64)
    if pred.shape != (3,) or not np.isfinite(pred).all():
        return None, "non-finite"
    norm = float(np.linalg.norm(pred))
    if norm <= 0:
        return None, "zero-vector"
    pred /= norm
    return float(abs(np.dot(pred, reference))), None


def _median(values: list[float]) -> float | None:
    return float(np.median(np.asarray(values, dtype=np.float64))) if values else None


def _validate_rule(rule: Any) -> dict[str, float]:
    if not isinstance(rule, dict):
        raise ValueError("decision_rule is required")
    names = {
        "min_score_completeness": (0.0, 1.0),
        "min_normal_offset_win_fraction": (0.0, 1.0),
        "min_median_normal_offset_margin": (None, None),
        "min_normal_completeness": (0.0, 1.0),
        "min_median_abs_cosine": (0.0, 1.0),
    }
    out: dict[str, float] = {}
    for name, bounds in names.items():
        value = rule.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"decision_rule.{name} must be numeric")
        value = float(value)
        if not math.isfinite(value):
            raise ValueError(f"decision_rule.{name} must be finite")
        lo, hi = bounds
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            raise ValueError(f"decision_rule.{name} must be between {lo} and {hi}")
        out[name] = value
    return out


def _validate_cutout_manifest(
    spec: dict[str, Any],
    manifest: dict[str, Any],
    *,
    volume_root: str,
    source: dict[str, Any],
    expected_input_sha: str,
    manifest_file_sha256: str,
) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ValueError("cutout manifest must be a JSON object")
    expected_manifest_sha = _require_sha(
        spec.get("cutout_manifest_sha256"), "spec.cutout_manifest_sha256"
    )
    if expected_manifest_sha != manifest_file_sha256:
        raise ValueError("cutout manifest sha256 does not match frozen spec")
    if manifest.get("schema") != "scroliq-ct-cutout/1":
        raise ValueError("cutout manifest must be scroliq-ct-cutout/1")
    if manifest.get("status") != "measured":
        raise ValueError("cutout manifest status must be measured")
    if manifest.get("volume_root") != volume_root:
        raise ValueError("cutout manifest volume_root does not match frozen spec")
    if manifest.get("level") != 0 or manifest.get("coordinate_space") != "level0-voxel-index":
        raise ValueError("cutout manifest must describe level-0 voxel-index coordinates")

    attestation = manifest.get("source_attestation")
    if not isinstance(attestation, dict):
        raise ValueError("cutout manifest source_attestation is required")
    for key in ("algorithm", "state", "metadata_semantics_sha256"):
        if attestation.get(key) != source.get(key):
            raise ValueError(
                f"cutout manifest source_attestation.{key} does not match frozen spec"
            )
    if attestation.get("axes") != ["z", "y", "x"]:
        raise ValueError("cutout manifest source_attestation.axes must be ['z', 'y', 'x']")

    zpa_report = manifest.get("zpa_report")
    if not isinstance(zpa_report, dict) or zpa_report.get("integrity") != "PASS":
        raise ValueError("cutout manifest must retain a PASS ZPA report proof")
    zpa_report_sha = _require_sha(
        zpa_report.get("sha256"), "cutout manifest zpa_report.sha256"
    )

    cutout = manifest.get("cutout")
    if not isinstance(cutout, dict):
        raise ValueError("cutout manifest cutout block is required")
    if cutout.get("sha256") != expected_input_sha:
        raise ValueError("cutout manifest sha256 does not match frozen input_sha256")
    shape = _coord(cutout.get("shape_zyx"), "cutout manifest cutout.shape_zyx")
    if cutout.get("dtype") != "uint8":
        raise ValueError("cutout manifest dtype must be uint8")

    bbox = manifest.get("bbox_zyx_half_open")
    if not isinstance(bbox, dict):
        raise ValueError("cutout manifest bbox_zyx_half_open is required")
    start = _coord(bbox.get("start"), "cutout manifest bbox start")
    stop = _coord(bbox.get("stop"), "cutout manifest bbox stop")
    if any(a >= b for a, b in zip(start, stop)):
        raise ValueError("cutout manifest bbox must use increasing half-open bounds")
    if tuple(stop[d] - start[d] for d in range(3)) != shape:
        raise ValueError("cutout manifest bbox extent does not match cutout shape")

    transform = manifest.get("local_to_global")
    if (
        not isinstance(transform, dict)
        or transform.get("kind") != "integer-translation"
        or transform.get("start_zyx") != list(start)
    ):
        raise ValueError("cutout manifest local_to_global transform is inconsistent")

    chunks = manifest.get("source_chunks")
    if not isinstance(chunks, dict) or chunks.get("missing_count") != 0:
        raise ValueError("cutout manifest must prove zero missing source chunks")

    return {
        "file_sha256": manifest_file_sha256,
        "bbox_zyx_half_open": {"start": list(start), "stop": list(stop)},
        "start_zyx": start,
        "shape_zyx": list(shape),
        "zpa_report_sha256": zpa_report_sha,
    }


def evaluate(
    spec: dict[str, Any],
    report: dict[str, Any],
    response: np.ndarray,
    normals: np.ndarray,
    *,
    spec_file_sha256: str,
    report_file_sha256: str,
    response_file_sha256: str,
    normal_file_sha256: str,
    cutout_manifest: dict[str, Any],
    cutout_manifest_file_sha256: str,
) -> dict[str, Any]:
    if spec.get("schema_version") != 3:
        raise ValueError("spec.schema_version must be 3")
    volume_root = spec.get("volume_root")
    if not isinstance(volume_root, str) or not volume_root.strip():
        raise ValueError("spec.volume_root is required")

    source = spec.get("source_attestation")
    if not isinstance(source, dict):
        raise ValueError("spec.source_attestation is required")
    if source.get("algorithm") != "zpa-metadata-semantics-v1":
        raise ValueError("source_attestation.algorithm must be zpa-metadata-semantics-v1")
    if source.get("state") != "PRESENT":
        raise ValueError("source_attestation.state must be PRESENT")
    metadata_sha = _require_sha(
        source.get("metadata_semantics_sha256"),
        "source_attestation.metadata_semantics_sha256",
    )

    expected_report_sha = _require_sha(
        spec.get("sheetness_report_sha256"), "spec.sheetness_report_sha256"
    )
    if expected_report_sha != report_file_sha256:
        raise ValueError("sheetness report sha256 does not match frozen spec")

    expected_input_sha = _require_sha(spec.get("input_sha256"), "spec.input_sha256")
    cutout_binding = _validate_cutout_manifest(
        spec,
        cutout_manifest,
        volume_root=volume_root,
        source=source,
        expected_input_sha=expected_input_sha,
        manifest_file_sha256=cutout_manifest_file_sha256,
    )
    if report.get("kind") != "sheetness" or report.get("schema_version") != 1:
        raise ValueError("report must be a scroliq-sheetness schema v1 report")
    report_input = report.get("input")
    if not isinstance(report_input, dict) or report_input.get("sha256") != expected_input_sha:
        raise ValueError("sheetness report input sha256 does not match frozen spec")

    response_meta = report.get("response")
    if (
        not isinstance(response_meta, dict)
        or response_meta.get("output_sha256") != response_file_sha256
    ):
        raise ValueError("response array sha256 does not match sheetness report")

    normal_meta = report.get("normal")
    if (
        not isinstance(normal_meta, dict)
        or normal_meta.get("output_sha256") != normal_file_sha256
    ):
        raise ValueError("normal array sha256 does not match sheetness report")

    response = np.asarray(response)
    normals = np.asarray(normals)
    if response.ndim != 3:
        raise ValueError("response array must be 3-D")
    if normals.shape != response.shape + (3,):
        raise ValueError("normal array must have response.shape + (3,)")
    if report_input.get("shape_zyx") != [int(v) for v in response.shape]:
        raise ValueError("response shape does not match sheetness report input shape")
    if cutout_binding["shape_zyx"] != [int(v) for v in response.shape]:
        raise ValueError("response shape does not match provenance-bound cutout shape")
    global_start = cutout_binding["start_zyx"]

    groups = spec.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("spec.groups must be a non-empty list")
    rule = _validate_rule(spec.get("decision_rule"))

    ids: set[str] = set()
    rows: list[dict[str, Any]] = []
    normal_offset_margins: list[float] = []
    wrong_wrap_margins: list[float] = []
    cosines: list[float] = []
    score_complete_count = 0
    normal_complete_count = 0
    normal_offset_win_count = 0
    wrong_wrap_win_count = 0

    for index, group in enumerate(groups):
        path = f"groups[{index}]"
        if not isinstance(group, dict):
            raise ValueError(f"{path} must be an object")
        gid = group.get("id")
        if not isinstance(gid, str) or not gid:
            raise ValueError(f"{path}.id is required")
        if gid in ids:
            raise ValueError(f"duplicate group id {gid!r}")
        ids.add(gid)

        surface = group.get("surface")
        if not isinstance(surface, dict):
            raise ValueError(f"{path}.surface is required")
        surface_coord = _coord(surface.get("zyx"), f"{path}.surface.zyx")
        reference = _unit(
            surface.get("reference_normal_zyx"),
            f"{path}.surface.reference_normal_zyx",
        )

        controls = group.get("controls")
        if not isinstance(controls, list) or not controls:
            raise ValueError(f"{path}.controls must be non-empty")
        seen_roles: set[str] = set()
        seen_control_ids: set[str] = set()
        control_rows: list[dict[str, Any]] = []
        control_scores_by_role: dict[str, list[float]] = {
            "normal-offset": [],
            "wrong-wrap": [],
        }
        control_complete = True
        for c_index, control in enumerate(controls):
            cpath = f"{path}.controls[{c_index}]"
            if not isinstance(control, dict):
                raise ValueError(f"{cpath} must be an object")
            cid = control.get("id")
            if not isinstance(cid, str) or not cid:
                raise ValueError(f"{cpath}.id is required")
            if cid in seen_control_ids:
                raise ValueError(f"{path}: duplicate control id {cid!r}")
            seen_control_ids.add(cid)
            role = control.get("role")
            if role not in REQUIRED_CONTROL_ROLES:
                raise ValueError(
                    f"{cpath}.role must be one of {', '.join(REQUIRED_CONTROL_ROLES)}"
                )
            seen_roles.add(str(role))
            coord = _coord(control.get("zyx"), f"{cpath}.zyx")
            score, reason = _value_at(response, coord)
            if score is None:
                control_complete = False
            else:
                control_scores_by_role[str(role)].append(score)
            control_rows.append(
                {
                    "id": cid,
                    "role": role,
                    "zyx": list(coord),
                    "global_zyx": [
                        int(coord[d] + global_start[d]) for d in range(3)
                    ],
                    "score": score,
                    "failure": reason,
                }
            )
        missing_roles = sorted(set(REQUIRED_CONTROL_ROLES) - seen_roles)
        if missing_roles:
            raise ValueError(f"{path} missing required control roles: {missing_roles}")

        surface_score, surface_failure = _value_at(response, surface_coord)
        score_complete = surface_score is not None and control_complete
        normal_offset_margin = None
        wrong_wrap_margin = None
        surface_beats_normal_offsets = False
        surface_beats_wrong_wraps = False
        if score_complete:
            score_complete_count += 1

            normal_scores = control_scores_by_role["normal-offset"]
            wrong_scores = control_scores_by_role["wrong-wrap"]
            normal_offset_margin = float(surface_score - max(normal_scores))
            wrong_wrap_margin = float(surface_score - max(wrong_scores))
            normal_offset_margins.append(normal_offset_margin)
            wrong_wrap_margins.append(wrong_wrap_margin)

            surface_beats_normal_offsets = bool(surface_score > max(normal_scores))
            surface_beats_wrong_wraps = bool(surface_score > max(wrong_scores))
            if surface_beats_normal_offsets:
                normal_offset_win_count += 1
            if surface_beats_wrong_wraps:
                wrong_wrap_win_count += 1

        cosine, normal_failure = _normal_at(normals, surface_coord, reference)
        if cosine is not None:
            normal_complete_count += 1
            cosines.append(cosine)

        rows.append(
            {
                "id": gid,
                "surface": {
                    "zyx": list(surface_coord),
                    "global_zyx": [
                        int(surface_coord[d] + global_start[d]) for d in range(3)
                    ],
                    "score": surface_score,
                    "score_failure": surface_failure,
                    "reference_normal_zyx": [float(v) for v in reference],
                    "predicted_normal_abs_cosine": cosine,
                    "normal_failure": normal_failure,
                },
                "controls": control_rows,
                "score_complete": score_complete,
                "surface_beats_all_normal_offsets": surface_beats_normal_offsets,
                "surface_minus_best_normal_offset": normal_offset_margin,
                "surface_beats_all_wrong_wraps": surface_beats_wrong_wraps,
                "surface_minus_best_wrong_wrap": wrong_wrap_margin,
            }
        )

    total = len(rows)
    score_completeness = score_complete_count / total
    normal_completeness = normal_complete_count / total
    normal_offset_win_fraction = normal_offset_win_count / total
    wrong_wrap_win_fraction = wrong_wrap_win_count / total
    median_normal_offset_margin = _median(normal_offset_margins)
    median_wrong_wrap_margin = _median(wrong_wrap_margins)
    median_abs_cosine = _median(cosines)

    metrics = {
        "group_count": total,
        "score_complete_count": score_complete_count,
        "score_completeness": score_completeness,
        "normal_offset_win_count": normal_offset_win_count,
        "normal_offset_win_fraction": normal_offset_win_fraction,
        "median_surface_minus_best_normal_offset": median_normal_offset_margin,
        "wrong_wrap_win_count_descriptive": wrong_wrap_win_count,
        "wrong_wrap_win_fraction_descriptive": wrong_wrap_win_fraction,
        "median_surface_minus_best_wrong_wrap_descriptive": median_wrong_wrap_margin,
        "normal_complete_count": normal_complete_count,
        "normal_completeness": normal_completeness,
        "median_abs_cosine": median_abs_cosine,
    }

    checks = {
        "score_completeness": score_completeness >= rule["min_score_completeness"],
        "normal_offset_win_fraction": (
            normal_offset_win_fraction >= rule["min_normal_offset_win_fraction"]
        ),
        "median_normal_offset_margin": (
            median_normal_offset_margin is not None
            and median_normal_offset_margin >= rule["min_median_normal_offset_margin"]
        ),
        "normal_completeness": normal_completeness >= rule["min_normal_completeness"],
        "median_abs_cosine": (
            median_abs_cosine is not None
            and median_abs_cosine >= rule["min_median_abs_cosine"]
        ),
    }
    status = "pass" if all(checks.values()) else "fail"

    return {
        "schema": SCHEMA,
        "status": status,
        "volume_root": volume_root,
        "source_attestation": {
            "algorithm": source["algorithm"],
            "state": source["state"],
            "metadata_semantics_sha256": metadata_sha,
        },
        "spec": {
            "file_sha256": spec_file_sha256,
            "canonical_sha256": canonical_sha256(spec),
            "decision_rule": rule,
        },
        "engine": {
            "report_sha256": report_file_sha256,
            "method": report.get("method"),
            "parameters": report.get("parameters"),
            "normalization": report.get("normalization"),
            "stochastic": False,
            "seed": None,
        },
        "inputs": {
            "cutout_sha256": expected_input_sha,
            "cutout_manifest_sha256": cutout_binding["file_sha256"],
            "global_bbox_zyx_half_open": cutout_binding["bbox_zyx_half_open"],
            "zpa_report_sha256": cutout_binding["zpa_report_sha256"],
            "response_sha256": response_file_sha256,
            "normal_sha256": normal_file_sha256,
            "shape_zyx": [int(v) for v in response.shape],
        },
        "metrics": metrics,
        "decision_checks": checks,
        "wrong_wrap_interpretation": (
            "descriptive-only: a genuine competing papyrus sheet is also expected "
            "to be sheet-like, so wrong-wrap response measures the method's sheet-"
            "identity limitation and is not a pass/fail criterion"
        ),
        "groups": rows,
        "claim_boundary": (
            "This result tests whether a frozen sheetness field localizes a candidate "
            "surface relative to deliberate normal offsets on an exact audited CT "
            "volume. Wrong-wrap/competing-sheet probes are retained as mandatory "
            "descriptive controls, not a pass/fail target, because another papyrus "
            "sheet is itself sheet-like. This does not establish physical sheet "
            "identity/topology or demonstrate readable ink."
        ),
    }


def run(
    spec_path: str | Path,
    cutout_manifest_path: str | Path,
    report_path: str | Path,
    response_path: str | Path,
    normal_path: str | Path,
) -> dict[str, Any]:
    spec_path = Path(spec_path)
    cutout_manifest_path = Path(cutout_manifest_path)
    report_path = Path(report_path)
    response_path = Path(response_path)
    normal_path = Path(normal_path)

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    cutout_manifest = json.loads(cutout_manifest_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    response = np.load(response_path, allow_pickle=False)
    normals = np.load(normal_path, allow_pickle=False)

    return evaluate(
        spec,
        report,
        response,
        normals,
        spec_file_sha256=sha256_file(spec_path),
        report_file_sha256=sha256_file(report_path),
        response_file_sha256=sha256_file(response_path),
        normal_file_sha256=sha256_file(normal_path),
        cutout_manifest=cutout_manifest,
        cutout_manifest_file_sha256=sha256_file(cutout_manifest_path),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate a frozen ScrolIQ sheetness field against surface, "
            "normal-offset, and wrong-wrap controls."
        )
    )
    parser.add_argument("--spec", required=True)
    parser.add_argument("--cutout-manifest", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--response", required=True)
    parser.add_argument("--normal", required=True)
    parser.add_argument("--out")
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="exit 1 when the frozen decision rule fails; negative results are otherwise exit 0",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(
            args.spec,
            args.cutout_manifest,
            args.report,
            args.response,
            args.normal,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"schema": SCHEMA, "status": "invalid", "error": str(exc)}))
        return 2

    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return int(args.require_pass and result["status"] != "pass")


if __name__ == "__main__":
    raise SystemExit(main())
